"""Data access: the only module that talks SQL.

Everything above this layer works in domain objects. Everything below is
SQLite. Keeping that boundary sharp is what makes a later move to Postgres a
contained change.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .config import CONFIG
from .db import connect, hash_token, init_db, new_join_code, new_token, transaction
from .drills import DRILLS_BY_KEY, get_drill
from . import assignments as assignments_mod
from . import guardians as guardians_mod
from . import load as load_mod
from . import notifications as notify
from .integrity import RepEvent, SessionClaim, evaluate
from .quality import RepFeature, analyze as analyze_quality
from .scoring import (
    AthleteStats,
    BADGES_BY_KEY,
    compute_streak,
    earned_badges,
    level_progress,
    score_session,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _opt_float(value: Any) -> float | None:
    """Coerce a client-supplied number, treating anything unusable as absent."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _opt_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# How far back a device-reported completion time may be honoured. Past this
# the claim is unverifiable, so the session is credited to the day it arrived.
OFFLINE_BACKDATE_LIMIT_DAYS = 14


class StoreError(Exception):
    """A request that is well-formed but not permissible."""


@dataclass
class Principal:
    """The authenticated caller."""

    id: int
    org_id: int
    role: str
    display_name: str
    dominant_hand: str | None

    @property
    def is_staff(self) -> bool:
        return self.role in ("coach", "director")


class Store:
    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self.conn = conn or connect()
        init_db(self.conn)

    # ------------------------------------------------------------------
    # Org / team / user setup
    # ------------------------------------------------------------------

    def create_org(self, name: str, sport: str = "lacrosse") -> int:
        with transaction(self.conn) as c:
            cur = c.execute(
                "INSERT INTO organizations(name, sport, created_at) VALUES (?,?,?)",
                (name, sport, _iso(_now())),
            )
        return int(cur.lastrowid)

    def create_team(self, org_id: int, name: str, season: str = "") -> dict[str, Any]:
        # Retry on the astronomically unlikely join-code collision rather than
        # surfacing a UNIQUE constraint error to a coach mid-setup.
        for _ in range(10):
            code = new_join_code()
            try:
                with transaction(self.conn) as c:
                    cur = c.execute(
                        "INSERT INTO teams(org_id, name, season, join_code, created_at) "
                        "VALUES (?,?,?,?,?)",
                        (org_id, name, season, code, _iso(_now())),
                    )
                return {"id": int(cur.lastrowid), "name": name, "join_code": code}
            except sqlite3.IntegrityError:
                continue
        raise StoreError("could not allocate a unique join code")

    def create_user(
        self,
        org_id: int,
        role: str,
        display_name: str,
        *,
        email: str | None = None,
        birth_year: int | None = None,
        dominant_hand: str | None = None,
        guardian_consent: bool = False,
    ) -> dict[str, Any]:
        """Create a user and return their one-time API token.

        The token is shown exactly once. Only its hash is stored, so a lost
        token is reissued, never recovered.
        """
        if role not in ("athlete", "coach", "director"):
            raise StoreError(f"invalid role: {role!r}")
        if dominant_hand not in (None, "left", "right"):
            raise StoreError(f"invalid dominant_hand: {dominant_hand!r}")

        token = new_token()
        consent_at = _iso(_now()) if guardian_consent else None
        with transaction(self.conn) as c:
            cur = c.execute(
                "INSERT INTO users(org_id, role, display_name, email, birth_year, "
                "guardian_consent_at, dominant_hand, token_hash, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    org_id, role, display_name, email, birth_year,
                    consent_at, dominant_hand, hash_token(token), _iso(_now()),
                ),
            )
        return {"id": int(cur.lastrowid), "token": token, "display_name": display_name}

    def join_team(self, join_code: str, user_id: int, jersey: str = "", position: str = "") -> int:
        row = self.conn.execute(
            "SELECT id, org_id FROM teams WHERE join_code = ?", (join_code.upper().strip(),)
        ).fetchone()
        if row is None:
            raise StoreError("no team matches that join code")
        user = self.conn.execute(
            "SELECT org_id FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if user is None:
            raise StoreError("unknown user")
        if user["org_id"] != row["org_id"]:
            raise StoreError("that team belongs to a different program")
        with transaction(self.conn) as c:
            c.execute(
                "INSERT OR REPLACE INTO team_members(team_id, user_id, jersey, position, joined_at) "
                "VALUES (?,?,?,?,?)",
                (row["id"], user_id, jersey, position, _iso(_now())),
            )
        return int(row["id"])

    def authenticate(self, token: str) -> Principal:
        row = self.conn.execute(
            "SELECT id, org_id, role, display_name, dominant_hand FROM users "
            "WHERE token_hash = ? AND active = 1",
            (hash_token(token),),
        ).fetchone()
        if row is None:
            raise StoreError("invalid or inactive token")
        return Principal(
            id=row["id"],
            org_id=row["org_id"],
            role=row["role"],
            display_name=row["display_name"],
            dominant_hand=row["dominant_hand"],
        )

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def _require_participation_consent(self, athlete_id: int) -> None:
        """Block recording when a guardian has withdrawn consent.

        Only enforced once a guardian is actually linked. Athletes onboarded
        before parent accounts existed have no consent rows, and defaulting
        those to "denied" would lock out every existing user on deploy -- so
        enforcement begins when a parent joins, which is also the point at
        which their decision is the one that counts.
        """
        row = self.conn.execute(
            "SELECT 1 FROM guardians WHERE athlete_id = ? LIMIT 1", (athlete_id,)
        ).fetchone()
        if row is None:
            return
        if not guardians_mod.has_consent(
            self.conn, athlete_id, guardians_mod.Scope.PARTICIPATION
        ):
            raise StoreError(
                "Training is paused for this account until a parent or guardian "
                "gives consent in their AthleteIQ portal."
            )

    def start_session(self, athlete_id: int, drill_key: str) -> dict[str, Any]:
        """Open a session and hand back the nonce required to submit it."""
        if drill_key not in DRILLS_BY_KEY:
            raise StoreError(f"unknown drill: {drill_key!r}")
        self._require_participation_consent(athlete_id)
        nonce = new_token()
        with transaction(self.conn) as c:
            cur = c.execute(
                "INSERT INTO sessions(athlete_id, drill_key, nonce, started_at, status) "
                "VALUES (?,?,?,?,'open')",
                (athlete_id, drill_key, nonce, _iso(_now())),
            )
        return {"session_id": int(cur.lastrowid), "nonce": nonce, "drill_key": drill_key}

    def reserve_sessions(
        self, athlete_id: int, drill_key: str, count: int = 3
    ) -> list[dict[str, Any]]:
        """Pre-issue session slots so capture can start with no network.

        Athletes train in driveways and on fields with no signal. Requiring a
        round-trip before counting begins means a dead zone costs a whole
        session, which costs a streak, which costs the athlete. The client
        stocks up on slots while it has signal and spends them offline.
        """
        if drill_key not in DRILLS_BY_KEY:
            raise StoreError(f"unknown drill: {drill_key!r}")
        self._require_participation_consent(athlete_id)
        count = max(1, min(int(count), 10))

        issued = []
        with transaction(self.conn) as c:
            for _ in range(count):
                nonce = new_token()
                cur = c.execute(
                    "INSERT INTO sessions(athlete_id, drill_key, nonce, started_at, "
                    "status, reserved) VALUES (?,?,?,?,'open',1)",
                    (athlete_id, drill_key, nonce, _iso(_now())),
                )
                issued.append(
                    {
                        "session_id": int(cur.lastrowid),
                        "nonce": nonce,
                        "drill_key": drill_key,
                    }
                )
        return issued

    def _effective_day(self, completed_at: str | None) -> tuple[str, str]:
        """Resolve the day a session should be credited to.

        Prefers the device's own completion time: a session trained Sunday in a
        dead zone and synced Monday has to earn Sunday's credit, or every lost
        signal silently breaks a streak. The value is clamped -- a device clock
        set far forward would otherwise let an athlete bank XP against future
        days and dodge the daily cap.
        """
        now = _now()
        if not completed_at:
            return now.date().isoformat(), _iso(now)

        parsed = _parse(completed_at)
        if parsed is None:
            return now.date().isoformat(), _iso(now)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        # Small forward skew is ordinary clock drift; anything more is wrong.
        if parsed > now + timedelta(minutes=5):
            parsed = now
        # Beyond this the claim is unverifiable, so credit it to today.
        earliest = now - timedelta(days=OFFLINE_BACKDATE_LIMIT_DAYS)
        if parsed < earliest:
            parsed = now
        return parsed.date().isoformat(), _iso(parsed)

    def submit_session(
        self,
        athlete_id: int,
        session_id: int,
        nonce: str,
        *,
        duration_ms: int,
        reps: list[dict[str, Any]],
        hold_ms: int = 0,
        mean_confidence: float = 0.0,
        client_version: str = "",
        device_label: str = "",
        completed_at: str | None = None,
    ) -> dict[str, Any]:
        """Validate, score, and record a completed session.

        Idempotent: resubmitting with the correct nonce returns the original
        result rather than erroring or scoring twice. An offline client that
        never saw its acknowledgement will retry, and a retry must not be
        punished.
        """
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise StoreError("unknown session")
        if row["athlete_id"] != athlete_id:
            raise StoreError("session belongs to a different athlete")
        # The nonce is what makes a submission single-use. Checked before the
        # status branch below so a wrong nonce can never read back a result.
        if row["nonce"] != nonce:
            raise StoreError("session nonce does not match")
        if row["status"] != "open":
            # Already scored. Hand back exactly what the first submit returned,
            # so a duplicate delivery is a no-op rather than an error the
            # athlete sees. Scoring still happened only once.
            if row["result_json"]:
                stored = json.loads(row["result_json"])
                stored["duplicate"] = True
                return stored
            raise StoreError("session has already been submitted")

        drill = get_drill(row["drill_key"])
        claim = SessionClaim(
            drill_key=drill.key,
            duration_ms=int(duration_ms),
            reps=[
                RepEvent(
                    t_ms=int(r.get("t_ms", 0)),
                    hand=str(r.get("hand", "none")),
                    confidence=float(r.get("confidence", 0.0)),
                    peak=_opt_float(r.get("peak")),
                    rom=_opt_float(r.get("rom")),
                    cycle_ms=_opt_int(r.get("cycle_ms")),
                )
                for r in reps
            ],
            hold_ms=int(hold_ms),
            mean_confidence=float(mean_confidence),
            client_version=client_version,
        )
        verdict = evaluate(claim, drill)

        hand = self._dominant_hand(athlete_id)

        # Form quality reads the same rep stream the counting did, so it costs
        # nothing extra to collect and is the half of the signal a rep count
        # throws away.
        report = analyze_quality(
            drill,
            [
                RepFeature(
                    t_ms=r.t_ms, hand=r.hand, confidence=r.confidence,
                    peak=r.peak, rom=r.rom, cycle_ms=r.cycle_ms,
                )
                for r in claim.reps
            ],
            dominant_hand=hand,
            hold_ms=claim.hold_ms,
            duration_ms=claim.duration_ms,
        )

        today, effective_at = self._effective_day(completed_at)
        already = self._xp_on_day(athlete_id, today)
        breakdown = score_session(
            drill,
            verdict,
            hold_ms=claim.hold_ms,
            dominant_hand=hand,
            xp_already_today=already,
            quality_score=report.score,
        )
        awarded = breakdown.total

        with transaction(self.conn) as c:
            c.execute(
                "UPDATE sessions SET submitted_at=?, completed_at=?, duration_ms=?, "
                "reps_total=?, reps_left=?, reps_right=?, hold_ms=?, mean_confidence=?, "
                "cadence_cv=?, integrity_score=?, integrity_notes=?, xp_awarded=?, "
                "status=?, client_version=?, device_label=?, quality_score=?, "
                "quality_json=? WHERE id=?",
                (
                    _iso(_now()), effective_at, claim.duration_ms, verdict.reps_total,
                    verdict.reps_left, verdict.reps_right, claim.hold_ms,
                    claim.mean_confidence, verdict.cadence_cv, verdict.score,
                    json.dumps(verdict.notes), awarded, verdict.status,
                    client_version, device_label, report.score,
                    json.dumps(report.to_dict()), session_id,
                ),
            )
            # Per-rep timings are kept only for integrity review and pruned by
            # `prune_rep_events`. They are timings, never imagery.
            c.executemany(
                "INSERT INTO rep_events(session_id, t_ms, hand, confidence, peak, rom, cycle_ms) "
                "VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        session_id, r.t_ms,
                        r.hand if r.hand in ("left", "right") else "none",
                        r.confidence, r.peak, r.rom, r.cycle_ms,
                    )
                    for r in claim.reps
                ],
            )
            if awarded > 0:
                c.execute(
                    "INSERT INTO xp_ledger(athlete_id, session_id, amount, reason, day, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (athlete_id, session_id, awarded, f"{drill.name} session", today, _iso(_now())),
                )

        new_badges = self._sync_badges(athlete_id)
        notify.notify_badges(self.conn, athlete_id, new_badges)

        result = {
            "session_id": session_id,
            "status": verdict.status,
            "integrity_score": round(verdict.score, 3),
            "notes": verdict.notes,
            "reps_total": verdict.reps_total,
            "reps_left": verdict.reps_left,
            "reps_right": verdict.reps_right,
            "xp_awarded": awarded,
            "xp_breakdown": [{"label": l, "amount": a} for l, a in breakdown.lines],
            "new_badges": [
                {"key": k, "name": BADGES_BY_KEY[k].name, "tier": BADGES_BY_KEY[k].tier}
                for k in new_badges
            ],
            "counted_for_day": today,
            "quality": report.to_dict(),
            "load": self.load_state(athlete_id).to_dict(),
        }
        # Stored so a duplicate delivery replays this exact response.
        with transaction(self.conn) as c:
            c.execute(
                "UPDATE sessions SET result_json = ? WHERE id = ?",
                (json.dumps(result), session_id),
            )
        return result

    def review_session(self, session_id: int, approve: bool, reviewer_id: int) -> dict[str, Any]:
        """Coach decision on a session held for review.

        Approving credits the XP that was withheld at submit time.
        """
        row = self.conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise StoreError("unknown session")
        if row["status"] != "review":
            raise StoreError(f"session is {row['status']}, not awaiting review")

        if not approve:
            with transaction(self.conn) as c:
                c.execute("UPDATE sessions SET status='rejected' WHERE id=?", (session_id,))
            return {"session_id": session_id, "status": "rejected", "xp_awarded": 0}

        drill = get_drill(row["drill_key"])
        athlete_id = row["athlete_id"]
        day = (_parse(row["submitted_at"]) or _now()).date().isoformat()

        from .integrity import IntegrityResult

        verdict = IntegrityResult(
            score=row["integrity_score"],
            status="counted",
            reps_total=row["reps_total"],
            reps_left=row["reps_left"],
            reps_right=row["reps_right"],
        )
        breakdown = score_session(
            drill,
            verdict,
            hold_ms=row["hold_ms"],
            dominant_hand=self._dominant_hand(athlete_id),
            xp_already_today=self._xp_on_day(athlete_id, day),
        )
        awarded = breakdown.total
        with transaction(self.conn) as c:
            c.execute(
                "UPDATE sessions SET status='counted', xp_awarded=? WHERE id=?",
                (awarded, session_id),
            )
            if awarded > 0:
                c.execute(
                    "INSERT INTO xp_ledger(athlete_id, session_id, amount, reason, day, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        athlete_id, session_id, awarded,
                        f"{drill.name} session (coach approved)", day, _iso(_now()),
                    ),
                )
        self._sync_badges(athlete_id)
        return {"session_id": session_id, "status": "counted", "xp_awarded": awarded}

    # ------------------------------------------------------------------
    # Athlete views
    # ------------------------------------------------------------------

    def _dominant_hand(self, athlete_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT dominant_hand FROM users WHERE id=?", (athlete_id,)
        ).fetchone()
        return row["dominant_hand"] if row else None

    def _xp_on_day(self, athlete_id: int, day: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(amount),0) AS t FROM xp_ledger WHERE athlete_id=? AND day=?",
            (athlete_id, day),
        ).fetchone()
        return int(row["t"])

    def athlete_stats(self, athlete_id: int) -> AthleteStats:
        c = self.conn
        total_xp = int(
            c.execute(
                "SELECT COALESCE(SUM(amount),0) AS t FROM xp_ledger WHERE athlete_id=?",
                (athlete_id,),
            ).fetchone()["t"]
        )
        agg = c.execute(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT drill_key) AS drills "
            "FROM sessions WHERE athlete_id=? AND status='counted'",
            (athlete_id,),
        ).fetchone()

        wall = c.execute(
            "SELECT COALESCE(SUM(reps_total),0) AS r FROM sessions "
            "WHERE athlete_id=? AND status='counted' AND drill_key IN ('lax_wall_ball','lax_quick_stick')",
            (athlete_id,),
        ).fetchone()["r"]

        hand = self._dominant_hand(athlete_id) or "right"
        offhand_col = "reps_left" if hand == "right" else "reps_right"
        offhand = c.execute(
            f"SELECT COALESCE(SUM({offhand_col}),0) AS r FROM sessions "
            "WHERE athlete_id=? AND status='counted'",
            (athlete_id,),
        ).fetchone()["r"]

        balanced = c.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE athlete_id=? AND status='counted' "
            "AND (reps_left + reps_right) >= 20 "
            "AND (MIN(reps_left, reps_right) * 1.0 / (reps_left + reps_right)) >= ?",
            (athlete_id, CONFIG.scoring.balance_threshold),
        ).fetchone()["n"]

        # "Before 8am" is evaluated on the stored UTC timestamp. A real
        # deployment needs the athlete's local timezone stored on the user row;
        # this is the known simplification here.
        early = c.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE athlete_id=? AND status='counted' "
            "AND CAST(strftime('%H', submitted_at) AS INTEGER) < 8",
            (athlete_id,),
        ).fetchone()["n"]

        streak = compute_streak(self._streak_days(athlete_id), _now().date())

        return AthleteStats(
            total_xp=total_xp,
            session_count=int(agg["n"]),
            wall_ball_reps=int(wall),
            offhand_reps=int(offhand),
            balanced_sessions=int(balanced),
            early_sessions=int(early),
            distinct_drills=int(agg["drills"]),
            current_streak=streak.current,
            longest_streak=streak.longest,
        )

    def _sync_badges(self, athlete_id: int) -> list[str]:
        """Award any newly-earned badges. Idempotent."""
        stats = self.athlete_stats(athlete_id)
        deserved = set(earned_badges(stats))
        held = {
            r["badge_key"]
            for r in self.conn.execute(
                "SELECT badge_key FROM badges WHERE athlete_id=?", (athlete_id,)
            )
        }
        fresh = sorted(deserved - held)
        if fresh:
            with transaction(self.conn) as c:
                c.executemany(
                    "INSERT OR IGNORE INTO badges(athlete_id, badge_key, awarded_at) VALUES (?,?,?)",
                    [(athlete_id, k, _iso(_now())) for k in fresh],
                )
        return fresh

    def athlete_profile(self, athlete_id: int) -> dict[str, Any]:
        user = self.conn.execute(
            "SELECT id, display_name, dominant_hand, birth_year FROM users WHERE id=?",
            (athlete_id,),
        ).fetchone()
        if user is None:
            raise StoreError("unknown athlete")

        stats = self.athlete_stats(athlete_id)
        prog = level_progress(stats.total_xp)
        streak = compute_streak(self._streak_days(athlete_id), _now().date())

        badges = [
            {
                "key": r["badge_key"],
                "name": BADGES_BY_KEY[r["badge_key"]].name,
                "description": BADGES_BY_KEY[r["badge_key"]].description,
                "tier": BADGES_BY_KEY[r["badge_key"]].tier,
                "awarded_at": r["awarded_at"],
            }
            for r in self.conn.execute(
                "SELECT badge_key, awarded_at FROM badges WHERE athlete_id=? ORDER BY awarded_at",
                (athlete_id,),
            )
            if r["badge_key"] in BADGES_BY_KEY
        ]

        recent = [
            dict(r)
            for r in self.conn.execute(
                "SELECT id, drill_key, submitted_at, duration_ms, reps_total, reps_left, "
                "reps_right, xp_awarded, status, quality_score FROM sessions "
                "WHERE athlete_id=? AND status != 'open' "
                "ORDER BY submitted_at DESC LIMIT 20",
                (athlete_id,),
            )
        ]
        for r in recent:
            r["drill_name"] = DRILLS_BY_KEY[r["drill_key"]].name if r["drill_key"] in DRILLS_BY_KEY else r["drill_key"]

        return {
            "athlete_id": user["id"],
            "display_name": user["display_name"],
            "dominant_hand": user["dominant_hand"],
            "level": prog.level,
            "total_xp": prog.total_xp,
            "xp_into_level": prog.xp_into_level,
            "xp_for_next": prog.xp_for_next,
            "level_fraction": round(prog.fraction, 3),
            "streak": streak.current,
            "longest_streak": streak.longest,
            "streak_at_risk": streak.at_risk,
            "xp_today": self._xp_on_day(athlete_id, _now().date().isoformat()),
            "daily_cap": CONFIG.scoring.daily_xp_cap,
            "quality": self.quality_trend(athlete_id),
            "load": self.load_state(athlete_id).to_dict(),
            "stats": {
                "sessions": stats.session_count,
                "wall_ball_reps": stats.wall_ball_reps,
                "offhand_reps": stats.offhand_reps,
                "balanced_sessions": stats.balanced_sessions,
                "distinct_drills": stats.distinct_drills,
            },
            "badges": badges,
            "recent_sessions": recent,
        }

    def load_history(self, athlete_id: int, days: int = 28) -> list[load_mod.DayLoad]:
        """Daily training load, derived from counted sessions."""
        cutoff = (_now().date() - timedelta(days=days - 1)).isoformat()
        rows = self.conn.execute(
            "SELECT date(COALESCE(completed_at, submitted_at)) AS day, drill_key, "
            "       reps_total, hold_ms "
            "FROM sessions WHERE athlete_id = ? AND status = 'counted' "
            "AND date(COALESCE(completed_at, submitted_at)) >= ?",
            (athlete_id, cutoff),
        ).fetchall()

        by_day: dict[str, load_mod.DayLoad] = {}
        for row in rows:
            day = row["day"]
            if day is None:
                continue
            entry = by_day.setdefault(day, load_mod.DayLoad(day=date.fromisoformat(day)))
            units, throws = load_mod.session_load(
                row["drill_key"], int(row["reps_total"]), int(row["hold_ms"])
            )
            entry.load += units
            entry.throws += throws
            entry.sessions += 1
        return sorted(by_day.values(), key=lambda d: d.day)

    def load_state(self, athlete_id: int) -> load_mod.LoadState:
        """Current workload assessment for one athlete."""
        row = self.conn.execute(
            "SELECT birth_year FROM users WHERE id = ?", (athlete_id,)
        ).fetchone()
        age = None
        if row and row["birth_year"]:
            age = _now().year - int(row["birth_year"])
        return load_mod.analyze(
            self.load_history(athlete_id, CONFIG.load.chronic_days),
            today=_now().date(),
            age=age,
        )

    def log_recovery_day(self, athlete_id: int, day: date | None = None) -> dict[str, Any]:
        """Record a deliberate rest day, which counts toward the streak.

        Only granted when the athlete has actually earned it -- otherwise this
        is just a button that keeps a streak alive without training, which
        would make the streak meaningless.
        """
        day = day or _now().date()
        state = self.load_state(athlete_id)
        cfg = CONFIG.load

        # Live run only: a recovery day is credit for stopping, not something
        # to claim a week after they last trained.
        recent = state.days_since_training is not None and state.days_since_training <= 1
        earned = recent and (
            state.rest_recommended or state.consecutive_days >= cfg.recovery_min_streak
        )
        if not earned:
            raise StoreError(
                "A recovery day counts once you have trained "
                f"{cfg.recovery_min_streak} days in a row. Keep going today."
            )

        reason = (
            "load spike" if state.zone == load_mod.Zone.HIGH
            else f"{state.consecutive_days} consecutive training days"
        )
        with transaction(self.conn) as c:
            c.execute(
                "INSERT OR IGNORE INTO recovery_days(athlete_id, day, reason, created_at) "
                "VALUES (?,?,?,?)",
                (athlete_id, day.isoformat(), reason, _iso(_now())),
            )
        return {"day": day.isoformat(), "reason": reason, "counts_toward_streak": True}

    def _recovery_days(self, athlete_id: int) -> list[date]:
        return [
            date.fromisoformat(r["day"])
            for r in self.conn.execute(
                "SELECT day FROM recovery_days WHERE athlete_id = ? ORDER BY day",
                (athlete_id,),
            )
        ]

    def _streak_days(self, athlete_id: int) -> list[date]:
        """Days that count toward a streak: trained, or deliberately rested."""
        trained = [
            date.fromisoformat(r["day"])
            for r in self.conn.execute(
                "SELECT DISTINCT day FROM xp_ledger WHERE athlete_id = ? "
                "GROUP BY day HAVING SUM(amount) >= ? ORDER BY day",
                (athlete_id, CONFIG.scoring.streak_min_xp),
            )
        ]
        if not CONFIG.load.recovery_day_protects_streak:
            return trained
        return sorted(set(trained) | set(self._recovery_days(athlete_id)))

    def quality_trend(self, athlete_id: int, window: int = 10) -> dict[str, Any]:
        """Recent form scores, and whether they are moving.

        Trend is the point: a single session's quality is noisy, and what an
        athlete or a coach can act on is whether it is climbing or slipping.
        """
        rows = self.conn.execute(
            "SELECT quality_score, drill_key, COALESCE(completed_at, submitted_at) AS at "
            "FROM sessions WHERE athlete_id = ? AND status = 'counted' "
            "AND quality_score IS NOT NULL ORDER BY at DESC LIMIT ?",
            (athlete_id, window * 2),
        ).fetchall()
        if not rows:
            return {"current": None, "trend": None, "samples": 0, "recent": []}

        scores = [int(r["quality_score"]) for r in rows]
        recent = scores[:window]
        current = round(sum(recent) / len(recent))

        trend = None
        if len(scores) >= 6:
            older = scores[window:]
            if older:
                trend = current - round(sum(older) / len(older))

        return {
            "current": current,
            "trend": trend,
            "samples": len(scores),
            "recent": [
                {"score": int(r["quality_score"]), "drill_key": r["drill_key"], "at": r["at"]}
                for r in rows[:window]
            ],
        }

    # ------------------------------------------------------------------
    # Guardian view
    # ------------------------------------------------------------------

    def guardian_summary(self, guardian_id: int) -> dict[str, Any]:
        """What a parent sees: their own children, and nothing else.

        Deliberately excludes two things the athlete and coach views carry.
        There is no leaderboard, because a ranked list of other people's
        children for adults to scroll is the mechanism behind the worst
        behaviour in youth sports. And there is no integrity or review status,
        because "your child's session was held for review" reads as an
        accusation and is a coach's conversation to have.
        """
        athletes = []
        for row in guardians_mod.athletes_for(self.conn, guardian_id):
            athlete_id = row["id"]
            profile = self.athlete_profile(athlete_id)
            state = self.load_state(athlete_id)

            week_start = (_now().date() - timedelta(days=6)).isoformat()
            week = self.conn.execute(
                "SELECT COUNT(*) AS sessions, COALESCE(SUM(reps_total),0) AS reps "
                "FROM sessions WHERE athlete_id = ? AND status = 'counted' "
                "AND date(COALESCE(completed_at, submitted_at)) >= ?",
                (athlete_id, week_start),
            ).fetchone()
            week_xp = self.conn.execute(
                "SELECT COALESCE(SUM(amount),0) AS t FROM xp_ledger "
                "WHERE athlete_id = ? AND day >= ?",
                (athlete_id, week_start),
            ).fetchone()["t"]

            athletes.append({
                "athlete_id": athlete_id,
                "display_name": row["display_name"],
                "relationship": row["relationship"],
                "level": profile["level"],
                "streak": profile["streak"],
                "week_sessions": int(week["sessions"]),
                "week_reps": int(week["reps"]),
                "week_xp": int(week_xp),
                "quality": profile["quality"],
                # Only the advisories that are actually about wellbeing. A
                # parent does not need a monotony note; they do need to know if
                # their child has not rested in two weeks.
                "load_advisories": [
                    a.to_dict() for a in state.advisories if a.level != "info"
                ],
                "rest_recommended": state.rest_recommended,
                "consecutive_days": state.consecutive_days,
                "badges": profile["badges"][-4:],
                "assignments": [
                    {
                        "title": a["title"],
                        "drill_name": a["drill_name"],
                        "due_on": a["due_on"],
                        "days_remaining": a["days_remaining"],
                        "complete": a["progress"]["complete"],
                    }
                    for a in assignments_mod.for_athlete(self.conn, athlete_id)
                ],
                "consents": guardians_mod.consent_detail(self.conn, athlete_id),
            })

        return {"athletes": athletes}

    def purge_rep_detail(self, athlete_id: int) -> int:
        """Drop granular rep timings for one athlete.

        Called when a guardian withdraws retention consent. Applied immediately
        rather than at the next scheduled prune, because a consent decision that
        takes effect tomorrow is not really a decision.
        """
        with transaction(self.conn) as c:
            cur = c.execute(
                "DELETE FROM rep_events WHERE session_id IN "
                "(SELECT id FROM sessions WHERE athlete_id = ?)",
                (athlete_id,),
            )
        return cur.rowcount

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def prune_rep_events(self, retention_days: int | None = None) -> int:
        """Drop per-rep timings past the retention window.

        Aggregate session records survive; only the granular stream goes. Keeps
        the stored footprint on a minor proportional to what review actually
        requires.
        """
        days = retention_days if retention_days is not None else CONFIG.rep_event_retention_days
        cutoff = _iso(_now() - timedelta(days=days))
        with transaction(self.conn) as c:
            cur = c.execute(
                "DELETE FROM rep_events WHERE session_id IN "
                "(SELECT id FROM sessions WHERE submitted_at IS NOT NULL AND submitted_at < ?)",
                (cutoff,),
            )
        return cur.rowcount
