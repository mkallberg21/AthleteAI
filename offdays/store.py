"""Data access: the only module that talks SQL.

Everything above this layer works in domain objects. Everything below is
SQLite. Keeping that boundary sharp is what makes a later move to Postgres a
contained change.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .config import CONFIG
from . import sports
from . import ball as ball_mod
from . import footwork
from . import goalie
from . import rewatch
from . import notifications
from . import recognition
from .drills.catalog import ALL_DRILLS
from . import family
from . import film
from . import rtp
from . import wellness
from .db import connect, hash_token, init_db, new_join_code, new_token, transaction
from .drills import DRILLS_BY_KEY, get_drill
from .drills.base import SignalKind
from . import assignments as assignments_mod
from . import billing as billing_mod
from . import guardians as guardians_mod
from . import load as load_mod
from . import roster as roster_mod
from . import absence
from . import adaptive
from . import i18n
from . import injury_history
from . import roster_sync
from . import technique
from . import notifications as notify
from .integrity import RepEvent, SessionClaim, evaluate
from .quality import QualityReport, RepFeature, analyze as analyze_quality
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
class Membership:
    org_id: int
    org_name: str
    role: str


@dataclass
class Principal:
    """The authenticated caller, in one program at a time."""

    id: int
    org_id: int
    role: str
    display_name: str
    dominant_hand: str | None
    memberships: list[Membership] = field(default_factory=list)
    # Teams this caller may see. None means every team in the program.
    team_ids: list[int] | None = None

    @property
    def is_staff(self) -> bool:
        return self.role in ("coach", "director")

    @property
    def is_director(self) -> bool:
        return self.role == "director"

    @property
    def team_scoped(self) -> bool:
        return self.team_ids is not None

    def can_see_team(self, team_id: int | None) -> bool:
        if self.team_ids is None:
            return True
        return team_id in self.team_ids

    def scope_filter(self) -> tuple[str, list[Any]]:
        """SQL fragment restricting a query to this caller's teams.

        Returns an empty fragment for unscoped callers so the same query text
        works for a director and a single-team assistant coach.
        """
        if self.team_ids is None:
            return "", []
        if not self.team_ids:
            # Scoped to nothing: a condition that is false rather than one that
            # is absent, so an empty scope cannot silently mean "everything".
            return " AND 1 = 0", []
        placeholders = ",".join("?" for _ in self.team_ids)
        return (
            f" AND EXISTS (SELECT 1 FROM team_members tmx WHERE tmx.user_id = u.id "
            f"AND tmx.team_id IN ({placeholders}))",
            list(self.team_ids),
        )


def _write_imported_sports(
    conn: sqlite3.Connection, athlete_id: int, keys: list[str], now: str
) -> None:
    """Record sports from a roster import, without seasons.

    Seasons are left empty on purpose. A roster column will not carry them,
    and inventing a plausible season span would relax the specialisation gate
    on data nobody actually gave us. An empty season list scores as a short
    year, which is the cautious direction: it never makes an athlete look more
    single-sport than they are, and the athlete can fill in the real seasons.
    """
    if not keys:
        return
    conn.executemany(
        "INSERT OR REPLACE INTO athlete_sports(athlete_id, sport, seasons, "
        "is_primary, updated_at) VALUES (?,?,?,?,?)",
        [(athlete_id, key, "", int(i == 0), now) for i, key in enumerate(keys)],
    )


class Store:
    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self.conn = conn or connect()
        init_db(self.conn)

    # ------------------------------------------------------------------
    # Multi-sport participation
    # ------------------------------------------------------------------

    def set_athlete_sports(
        self, athlete_id: int, entries: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Replace an athlete's recorded sports.

        A full replace rather than a merge: the picker this backs shows the
        whole list, so what comes back *is* the answer. Merging would leave a
        sport a kid deliberately unticked sitting in the table, which is the
        direction that matters -- a stale extra sport makes them look more
        multi-sport than they are, and that relaxes the specialisation gate.
        """
        cleaned: list[tuple[str, str, int]] = []
        seen: set[str] = set()
        primary_taken = False
        for entry in entries or []:
            sport = sports.normalize(entry.get("sport"))
            if sport is None or sport.key in seen:
                continue
            seen.add(sport.key)
            seasons = sports.clean_seasons(entry.get("seasons"))
            is_primary = bool(entry.get("is_primary")) and not primary_taken
            primary_taken = primary_taken or is_primary
            cleaned.append((sport.key, ",".join(seasons), int(is_primary)))

        # Exactly one primary. Falling back to the sport with the longest
        # season keeps `assess` from having to invent one, and keeps the
        # stored rows honest about what the athlete was actually asked.
        if cleaned and not primary_taken:
            widest = max(range(len(cleaned)), key=lambda i: len(cleaned[i][1]))
            key, seasons, _ = cleaned[widest]
            cleaned[widest] = (key, seasons, 1)

        now = _iso(_now())
        with transaction(self.conn) as conn:
            conn.execute("DELETE FROM athlete_sports WHERE athlete_id = ?", (athlete_id,))
            conn.executemany(
                "INSERT INTO athlete_sports(athlete_id, sport, seasons, is_primary, "
                "updated_at) VALUES (?,?,?,?,?)",
                [(athlete_id, key, seasons, primary, now) for key, seasons, primary in cleaned],
            )
        return self.athlete_sports(athlete_id)

    def athlete_sports(self, athlete_id: int) -> list[dict[str, Any]]:
        return [
            {
                "sport": row["sport"],
                "seasons": [s for s in (row["seasons"] or "").split(",") if s],
                "is_primary": bool(row["is_primary"]),
            }
            for row in self.conn.execute(
                "SELECT sport, seasons, is_primary FROM athlete_sports "
                "WHERE athlete_id = ? ORDER BY is_primary DESC, sport",
                (athlete_id,),
            )
        ]

    # ------------------------------------------------------------------
    # Soreness and injury
    # ------------------------------------------------------------------

    def check_in(
        self, athlete_id: int, soreness: str, day: date | None = None
    ) -> dict[str, Any]:
        """Record how an athlete feels today.

        Awards nothing and costs nothing. It protects the streak the same way
        a recovery day does, which is the point: an athlete who loses a streak
        by admitting they are sore learns to tick "fine", and then the whole
        feature is a machine for producing false reassurance.
        """
        if soreness not in wellness.Severity.ORDER:
            raise StoreError(f"unknown soreness value: {soreness}")
        day = day or _now().date()
        with transaction(self.conn) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO wellness_checkins(athlete_id, day, soreness, "
                "created_at) VALUES (?,?,?,?)",
                (athlete_id, day.isoformat(), soreness, _iso(_now())),
            )
        return {"day": day.isoformat(), "soreness": soreness, "counts_toward_streak": True}

    def report_discomfort(
        self,
        athlete_id: int,
        area: str,
        severity: str,
        *,
        side: str = "",
        flags: list[str] | None = None,
        note: str = "",
        started_on: date | None = None,
        day: date | None = None,
    ) -> dict[str, Any]:
        """Log something that hurts, or update today's report for that area.

        One open report per area: a second report on the same knee is the same
        knee, and stacking rows would make "days running" meaningless and the
        coach view a wall of duplicates.
        """
        if area not in wellness.AREAS_BY_KEY:
            raise StoreError(f"unknown body area: {area}")
        if severity not in wellness.Severity.ORDER:
            raise StoreError(f"unknown severity: {severity}")
        if side not in wellness.SIDES:
            raise StoreError(f"unknown side: {side}")

        day = day or _now().date()
        kept = [f for f in (flags or []) if f in wellness.FLAGS]
        open_row = self.conn.execute(
            "SELECT id, severity, previous_severity, started_on FROM discomfort_reports "
            "WHERE athlete_id = ? AND area = ? AND resolved_on IS NULL "
            "ORDER BY reported_on DESC LIMIT 1",
            (athlete_id, area),
        ).fetchone()

        with transaction(self.conn) as conn:
            if open_row is not None:
                # Only moved when the severity actually changes: a kid fixing a
                # typo in today's report must not overwrite the real previous
                # reading and erase the trend.
                previous = (
                    open_row["severity"] if open_row["severity"] != severity
                    else open_row["previous_severity"]
                )
                conn.execute(
                    "UPDATE discomfort_reports SET severity = ?, side = ?, flags = ?, "
                    "note = ?, reported_on = ?, previous_severity = ? WHERE id = ?",
                    (severity, side, ",".join(kept), note, day.isoformat(),
                     previous, open_row["id"]),
                )
                report_id = int(open_row["id"])
            else:
                cur = conn.execute(
                    "INSERT INTO discomfort_reports(athlete_id, area, side, severity, "
                    "flags, note, started_on, reported_on, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (athlete_id, area, side, severity, ",".join(kept), note,
                     (started_on or day).isoformat(), day.isoformat(), _iso(_now())),
                )
                report_id = int(cur.lastrowid)

        # Reporting it is itself a check-in. Asking a kid who just described a
        # sore knee to also tick a mood face is friction with no information
        # behind it, and friction is what stops the next report happening.
        self.check_in(athlete_id, max(severity, "sore", key=wellness.Severity.rank), day)

        # A live ramp on this area steps back rather than carrying on as if
        # nothing happened -- and it steps back one stage, not to the start.
        setback = None
        if severity != wellness.Severity.FINE:
            setback = self.record_setback(athlete_id, area, day)

        previous = open_row["severity"] if open_row is not None else None
        return {"id": report_id, "previous": previous, "setback": setback}

    def resolve_discomfort(
        self, athlete_id: int, report_id: int, day: date | None = None
    ) -> dict[str, Any]:
        """Close a report. Something serious opens a ramp rather than ending.

        An athlete saying "better now" about a knee that gave way is not the
        same event as saying it about a stiff thigh, and treating them the same
        is how a kid walks straight from an injury back into full training. The
        report still closes -- what changes is that a plan opens behind it, and
        the plan needs an adult.
        """
        day = day or _now().date()
        status = self.wellness_status(athlete_id, day)
        pair = next(
            ((r, a) for r, a in zip(status.reports, status.assessments) if r.id == report_id),
            None,
        )

        with transaction(self.conn) as conn:
            changed = conn.execute(
                "UPDATE discomfort_reports SET resolved_on = ? "
                "WHERE id = ? AND athlete_id = ? AND resolved_on IS NULL",
                (day.isoformat(), report_id, athlete_id),
            ).rowcount
        if not changed or pair is None:
            return {"resolved": bool(changed), "plan": None}

        report, assessment = pair
        clearance = rtp.required_clearance(report.area.urgent, assessment.action)
        if clearance == rtp.Clearance.NONE:
            return {"resolved": True, "plan": None}

        opened = self.open_return_plan(
            athlete_id, report_id, report.area.key, clearance, day
        )
        return {
            "resolved": True,
            "plan": self.return_plan(opened["id"], day) if opened else None,
        }

    def wellness_status(
        self, athlete_id: int, today: date | None = None
    ) -> wellness.Status:
        """Open reports for an athlete, with what to do about each."""
        today = today or _now().date()
        stale = (today - timedelta(days=wellness.STALE_AFTER_DAYS)).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM discomfort_reports WHERE athlete_id = ? "
            "AND resolved_on IS NULL AND reported_on >= ? ORDER BY reported_on DESC",
            (athlete_id, stale),
        ).fetchall()

        reports, assessments = [], []
        for row in rows:
            report = wellness.Report(
                id=int(row["id"]),
                athlete_id=athlete_id,
                area=wellness.AREAS_BY_KEY[row["area"]],
                side=row["side"] or "",
                severity=row["severity"],
                started_on=date.fromisoformat(row["started_on"]),
                reported_on=date.fromisoformat(row["reported_on"]),
                flags=tuple(f for f in (row["flags"] or "").split(",") if f),
                note=row["note"] or "",
                previous=row["previous_severity"],
            )
            reports.append(report)
            assessments.append(wellness.assess(report))

        checked = self.conn.execute(
            "SELECT 1 FROM wellness_checkins WHERE athlete_id = ? AND day = ?",
            (athlete_id, today.isoformat()),
        ).fetchone()
        return wellness.Status(
            reports, assessments, checked is not None,
            plans=self.active_return_plans(athlete_id, today),
            today=today,
        )

    def _checkin_days(self, athlete_id: int) -> list[date]:
        return [
            date.fromisoformat(r["day"])
            for r in self.conn.execute(
                "SELECT day FROM wellness_checkins WHERE athlete_id = ?", (athlete_id,)
            )
        ]

    # ------------------------------------------------------------------
    # Returning to training
    # ------------------------------------------------------------------

    def _log_plan_event(
        self, conn, plan_id: int, kind: str, detail: str = "",
        actor_id: int | None = None, actor_name: str = "", day: date | None = None,
    ) -> None:
        conn.execute(
            "INSERT INTO return_plan_events(plan_id, kind, detail, actor_id, "
            "actor_name, day, created_at) VALUES (?,?,?,?,?,?,?)",
            (plan_id, kind, detail, actor_id, actor_name,
             (day or _now().date()).isoformat(), _iso(_now())),
        )

    def open_return_plan(
        self,
        athlete_id: int,
        report_id: int,
        area: str,
        clearance: str,
        day: date | None = None,
    ) -> dict[str, Any] | None:
        """Start a ramp back. Returns None if one is already open for this area.

        Called from `resolve_discomfort` rather than exposed on its own: a plan
        exists because an athlete tried to say they were better after something
        serious, and inventing plans any other way would let one be started
        without a report behind it.
        """
        day = day or _now().date()
        existing = self.conn.execute(
            "SELECT id FROM return_plans WHERE athlete_id = ? AND area = ? "
            "AND completed_on IS NULL",
            (athlete_id, area),
        ).fetchone()
        if existing is not None:
            return None

        with transaction(self.conn) as conn:
            cur = conn.execute(
                "INSERT INTO return_plans(athlete_id, report_id, area, stage, "
                "clearance, started_on, stage_started_on, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (athlete_id, report_id, area, rtp.FIRST_STAGE.key, clearance,
                 day.isoformat(), day.isoformat(), _iso(_now())),
            )
            plan_id = int(cur.lastrowid)
            self._log_plan_event(
                conn, plan_id, "opened", f"clearance required: {clearance}", day=day
            )
        return {"id": plan_id, "clearance": clearance}

    def clear_return_plan(
        self,
        plan_id: int,
        actor_id: int,
        actor_name: str,
        clinician_name: str = "",
        day: date | None = None,
    ) -> dict[str, Any]:
        """Record that a human said this athlete can start their ramp.

        The app is storing someone else's decision, never making one. For a
        plan that needs a clinician, a name is required -- not because we can
        check it, but because typing one makes the step deliberate rather than
        a tap on the way to the pitch.
        """
        day = day or _now().date()
        row = self.conn.execute(
            "SELECT * FROM return_plans WHERE id = ?", (plan_id,)
        ).fetchone()
        if row is None or row["completed_on"] is not None:
            raise StoreError("no open return plan with that id")
        if row["cleared_on"] is not None:
            raise StoreError("that return plan has already been cleared")
        if row["clearance"] == rtp.Clearance.CLINICIAN and not clinician_name.strip():
            raise StoreError(
                "this return needs the name of the doctor or physio who cleared them"
            )

        with transaction(self.conn) as conn:
            conn.execute(
                "UPDATE return_plans SET cleared_on = ?, cleared_by = ?, "
                "cleared_by_name = ?, clinician_name = ?, stage = ?, "
                "stage_started_on = ? WHERE id = ?",
                (day.isoformat(), actor_id, actor_name, clinician_name.strip(),
                 rtp.next_stage(row["stage"]).key, day.isoformat(), plan_id),
            )
            detail = f"cleared by {actor_name}"
            if clinician_name.strip():
                detail += f", attested clinician: {clinician_name.strip()}"
            self._log_plan_event(
                conn, plan_id, "cleared", detail, actor_id, actor_name, day
            )
        return self.return_plan(plan_id)

    def advance_return_plan(
        self, athlete_id: int, plan_id: int, day: date | None = None
    ) -> dict[str, Any]:
        day = day or _now().date()
        plan = self._load_plan(plan_id, athlete_id)
        gate = rtp.can_advance(plan, day)
        if not gate["ok"]:
            raise StoreError(gate["reason"])

        moved = rtp.next_stage(plan.stage)
        done = moved.key == rtp.LAST_STAGE.key
        with transaction(self.conn) as conn:
            conn.execute(
                "UPDATE return_plans SET stage = ?, stage_started_on = ?, "
                "completed_on = ? WHERE id = ?",
                (moved.key, day.isoformat(), day.isoformat() if done else None, plan_id),
            )
            self._log_plan_event(
                conn, plan_id, "advanced", f"{plan.stage} -> {moved.key}", day=day
            )
        return self.return_plan(plan_id)

    def record_setback(
        self, athlete_id: int, area: str, day: date | None = None
    ) -> dict[str, Any] | None:
        """Step an active plan back one stage because symptoms returned.

        One stage, never back to the start. Resetting the plan is the same
        mistake as charging a streak for reporting soreness: if speaking up
        costs a week, a kid who wants to play on Saturday stops speaking up.
        """
        day = day or _now().date()
        row = self.conn.execute(
            "SELECT * FROM return_plans WHERE athlete_id = ? AND area = ? "
            "AND completed_on IS NULL AND cleared_on IS NOT NULL",
            (athlete_id, area),
        ).fetchone()
        if row is None or row["stage"] == rtp.FIRST_STAGE.key:
            return None

        dropped = rtp.previous_stage(row["stage"])
        setbacks = int(row["setbacks"]) + 1
        # Two is the point where the ramp itself is not the answer any more.
        needs_reclearance = setbacks >= rtp.SETBACKS_BEFORE_RECLEARANCE
        with transaction(self.conn) as conn:
            conn.execute(
                "UPDATE return_plans SET stage = ?, stage_started_on = ?, "
                "setbacks = ?, cleared_on = ? WHERE id = ?",
                (dropped.key, day.isoformat(), setbacks,
                 None if needs_reclearance else row["cleared_on"], row["id"]),
            )
            self._log_plan_event(
                conn, row["id"], "setback",
                f"{row['stage']} -> {dropped.key} (setback {setbacks})", day=day,
            )
        return self.return_plan(int(row["id"]))

    def _load_plan(self, plan_id: int, athlete_id: int | None = None) -> rtp.Plan:
        sql = "SELECT * FROM return_plans WHERE id = ?"
        params: list[Any] = [plan_id]
        if athlete_id is not None:
            sql += " AND athlete_id = ?"
            params.append(athlete_id)
        row = self.conn.execute(sql, params).fetchone()
        if row is None:
            raise StoreError("no return plan with that id")

        started = date.fromisoformat(row["started_on"])
        clear_days = tuple(
            date.fromisoformat(r["day"])
            for r in self.conn.execute(
                "SELECT day FROM wellness_checkins WHERE athlete_id = ? AND day >= ? "
                "AND soreness IN ('fine', 'niggle')",
                (row["athlete_id"], started.isoformat()),
            )
        )
        return rtp.Plan(
            id=int(row["id"]),
            athlete_id=int(row["athlete_id"]),
            area=row["area"],
            area_label=wellness.AREAS_BY_KEY[row["area"]].label,
            stage=row["stage"],
            started_on=started,
            stage_started_on=date.fromisoformat(row["stage_started_on"]),
            clearance=row["clearance"],
            cleared_on=date.fromisoformat(row["cleared_on"]) if row["cleared_on"] else None,
            cleared_by_name=row["cleared_by_name"] or "",
            clinician_name=row["clinician_name"] or "",
            setbacks=int(row["setbacks"]),
            completed_on=(
                date.fromisoformat(row["completed_on"]) if row["completed_on"] else None
            ),
            clear_days=clear_days,
        )

    def return_plan(self, plan_id: int, today: date | None = None) -> dict[str, Any]:
        return self._load_plan(plan_id).to_dict(today or _now().date())

    def active_return_plans(
        self, athlete_id: int, today: date | None = None
    ) -> list[rtp.Plan]:
        """Live ramps, ignoring any the athlete has clearly walked away from."""
        today = today or _now().date()
        stale = (today - timedelta(days=rtp.STALE_AFTER_DAYS)).isoformat()
        return [
            self._load_plan(int(row["id"]))
            for row in self.conn.execute(
                "SELECT id FROM return_plans WHERE athlete_id = ? "
                "AND completed_on IS NULL AND stage_started_on >= ? ORDER BY id",
                (athlete_id, stale),
            )
        ]

    def plan_history(self, plan_id: int) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT kind, detail, actor_name, day FROM return_plan_events "
                "WHERE plan_id = ? ORDER BY id",
                (plan_id,),
            )
        ]

    # ------------------------------------------------------------------
    # Film study
    # ------------------------------------------------------------------

    def create_clip(
        self,
        org_id: int,
        raw_video: str,
        title: str,
        *,
        focus: str = "",
        provider: str = "youtube",
        start_s: int = 0,
        end_s: int | None = None,
        positions: list[str] | None = None,
        min_age: int = 0,
        max_age: int = 200,
        question: dict[str, Any] | None = None,
        created_by: int | None = None,
    ) -> dict[str, Any]:
        """Curate a clip. Coaches paste a link; this works out what it is."""
        if provider not in film.PROVIDERS:
            raise StoreError(f"unknown clip provider: {provider}")
        if provider == "youtube":
            video_id = film.parse_youtube_id(raw_video)
            if video_id is None:
                raise StoreError("that does not look like a YouTube link or video id")
        else:
            video_id = (raw_video or "").strip()
            if not video_id.startswith("https://"):
                raise StoreError("a self-hosted clip needs an https link")

        if end_s is not None and end_s <= start_s:
            raise StoreError("the clip has to end after it starts")

        # The length cap is a product rule, not a preference: a ten-minute
        # "short clip" is how a film feature turns into homework.
        longest = max(b.clip_max_s for b in film.BANDS)
        if end_s is not None and (end_s - start_s) > longest:
            raise StoreError(
                f"clips are capped at {longest} seconds — trim it to the moment "
                "that actually teaches something"
            )

        # A highlight reel is not a bad video; it is a video that teaches
        # nothing while looking exactly like film study. It fills the shelf, it
        # earns the same XP, and the athlete comes away having watched somebody
        # else be good at lacrosse. Refused rather than warned about, because a
        # warning on a screen a coach sees once is a warning nobody reads -- and
        # the fix is to retitle it, which costs nothing.
        marker = film.looks_like_highlights(title)
        if marker is not None:
            raise StoreError(
                f"\u201c{marker}\u201d in the title -- this shelf is for clips that "
                "teach a decision, not for highlight reels. " + film.WHAT_TO_CUT
                + " If it really does teach something, give it a title that "
                "says what."
            )

        parsed = film.Question(**question) if question else None
        if parsed is not None and not (0 <= parsed.answer < len(parsed.options)):
            raise StoreError("the answer has to be one of the options")

        with transaction(self.conn) as conn:
            cur = conn.execute(
                "INSERT INTO clips(org_id, provider, video_id, title, focus, start_s, "
                "end_s, positions, min_age, max_age, question, created_by, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (org_id, provider, video_id, title.strip(), focus.strip(), int(start_s),
                 end_s, ",".join(positions or []), int(min_age), int(max_age),
                 json.dumps(question) if question else None, created_by, _iso(_now())),
            )
        return self.clip(int(cur.lastrowid))

    def _row_to_clip(self, row) -> film.Clip:
        raw = json.loads(row["question"]) if row["question"] else None
        return film.Clip(
            id=int(row["id"]), org_id=int(row["org_id"]), provider=row["provider"],
            video_id=row["video_id"], title=row["title"], focus=row["focus"] or "",
            start_s=int(row["start_s"]), end_s=row["end_s"],
            positions=tuple(p for p in (row["positions"] or "").split(",") if p),
            min_age=int(row["min_age"]), max_age=int(row["max_age"]),
            question=film.Question(
                prompt=raw["prompt"], options=tuple(raw["options"]),
                answer=int(raw["answer"]), because=raw.get("because", ""),
            ) if raw else None,
            active=bool(row["active"]),
        )

    def clip(self, clip_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if row is None:
            raise StoreError("no clip with that id")
        return self._row_to_clip(row).to_dict()

    def retire_clip(self, org_id: int, clip_id: int) -> bool:
        with transaction(self.conn) as conn:
            return bool(conn.execute(
                "UPDATE clips SET active = 0 WHERE id = ? AND org_id = ?",
                (clip_id, org_id),
            ).rowcount)

    def film_day(self, athlete_id: int, day: date | None = None) -> film.DayState:
        """How much film this athlete has had today, against their allowance."""
        day = day or _now().date()
        profile = self.conn.execute(
            "SELECT birth_year, birth_year_estimated FROM users WHERE id = ?",
            (athlete_id,),
        ).fetchone()
        age = None
        if profile is not None and profile["birth_year"]:
            age = day.year - int(profile["birth_year"])
        band = film.band_for(
            age, bool(profile["birth_year_estimated"]) if profile else False
        )
        row = self.conn.execute(
            "SELECT COALESCE(SUM(watched_s), 0) AS secs, COUNT(*) AS n "
            "FROM clip_watches WHERE athlete_id = ? AND day = ?",
            (athlete_id, day.isoformat()),
        ).fetchone()
        return film.DayState(band, float(row["secs"]) / 60.0, int(row["n"]))

    def clips_for_athlete(
        self, athlete_id: int, org_id: int, day: date | None = None, limit: int = 12
    ) -> dict[str, Any]:
        """Today's shortlist, already filtered by age and by what is left.

        Returns an empty list once the day's allowance is gone rather than a
        list with a disabled flag: a grid of clips an athlete cannot watch is
        an invitation to find them somewhere else.
        """
        day = day or _now().date()
        state = self.film_day(athlete_id, day)
        profile = self.conn.execute(
            "SELECT birth_year FROM users WHERE id = ?", (athlete_id,)
        ).fetchone()
        age = day.year - int(profile["birth_year"]) if profile and profile["birth_year"] else None

        seen = {
            int(r["clip_id"]) for r in self.conn.execute(
                "SELECT clip_id FROM clip_watches WHERE athlete_id = ? AND day = ?",
                (athlete_id, day.isoformat()),
            )
        }
        out: list[dict[str, Any]] = []
        # Anything already watched, offered back rather than hidden. Going over
        # a clip a second time is what film study is; a feed that removed a
        # clip the moment it was watched made the one thing an athlete is most
        # likely to want -- another look before practice -- the one thing the
        # screen would not give them.
        #
        # Kept in its own list so a revisit never displaces a new clip, and so
        # the screen can say plainly which is which.
        again: list[dict[str, Any]] = []
        for row in self.conn.execute(
            "SELECT * FROM clips WHERE org_id = ? AND active = 1 ORDER BY id DESC",
            (org_id,),
        ):
            clip = self._row_to_clip(row)
            if not clip.suits(age, state.band):
                continue
            if clip.id in seen:
                again.append({
                    **clip.to_dict(),
                    "looks": rewatch.for_athlete(self.conn, athlete_id, clip.id),
                })
                continue
            if state.spent or len(out) >= limit:
                continue
            out.append(clip.to_dict())
        return {
            "day": state.to_dict(),
            "clips": out,
            "again": again,
            # Said before anything is recorded. Nothing else in this product
            # watches a child quietly and this will not be the first thing.
            "rewatch_notice": rewatch.NOTICE,
        }

    def start_watch(
        self, athlete_id: int, clip_id: int, day: date | None = None
    ) -> dict[str, Any]:
        day = day or _now().date()
        clip = self.conn.execute(
            "SELECT * FROM clips WHERE id = ? AND active = 1", (clip_id,)
        ).fetchone()
        if clip is None:
            raise StoreError("no clip with that id")

        state = self.film_day(athlete_id, day)
        existing = self.conn.execute(
            "SELECT id, looks, verdict FROM clip_watches "
            "WHERE athlete_id = ? AND clip_id = ? AND day = ?",
            (athlete_id, clip_id, day.isoformat()),
        ).fetchone()
        # The cap gates starting something new. Finishing a clip already begun
        # is never blocked -- stopping a kid halfway through is a worse
        # outcome than a minute over.
        if existing is None and state.spent:
            raise StoreError(state.message())

        now = _iso(_now())
        if existing is not None:
            looks = int(existing["looks"])
            # A clip already covered and started again is a deliberate second
            # pass, not a resume. Counted, never blocked: the daily cap exists
            # against burning a kid out on new material, and refusing to let
            # them re-check something they have already seen would make this
            # feature useless exactly when it matters, the night before a game.
            #
            # Nothing about the watch state is reset. Coverage stays where it
            # was, so a second pass cannot manufacture credit that a first one
            # did not earn.
            if existing["verdict"] == film.Verdict.WATCHED:
                looks += 1
                with transaction(self.conn) as conn:
                    conn.execute(
                        "UPDATE clip_watches SET looks = ? WHERE id = ?",
                        (looks, int(existing["id"])),
                    )
            return {
                "watch_id": int(existing["id"]),
                "resumed": True,
                "looks": looks,
                "rewatch_notice": rewatch.NOTICE,
            }
        with transaction(self.conn) as conn:
            cur = conn.execute(
                "INSERT INTO clip_watches(athlete_id, clip_id, day, started_at, "
                "last_beat_at) VALUES (?,?,?,?,?)",
                (athlete_id, clip_id, day.isoformat(), now, now),
            )
        return {
            "watch_id": int(cur.lastrowid),
            "resumed": False,
            "looks": rewatch.for_athlete(self.conn, athlete_id, clip_id),
            "rewatch_notice": rewatch.NOTICE,
        }

    def record_beat(
        self,
        athlete_id: int,
        watch_id: int,
        position_s: float,
        *,
        muted: bool = False,
        hidden: bool = False,
        rate: float = 1.0,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Fold one heartbeat into a watch and re-score it.

        The wall-clock gap comes from the server's own record of the last beat,
        never from the client: a payload that reports its own elapsed time can
        report whatever makes the numbers work.
        """
        row = self.conn.execute(
            "SELECT w.*, c.start_s, c.end_s FROM clip_watches w "
            "JOIN clips c ON c.id = w.clip_id WHERE w.id = ? AND w.athlete_id = ?",
            (watch_id, athlete_id),
        ).fetchone()
        if row is None:
            raise StoreError("no watch with that id")

        now = now or _now()
        gap = (now - datetime.fromisoformat(row["last_beat_at"])).total_seconds()
        length = max(0, int(row["end_s"] - row["start_s"])) if row["end_s"] else 0

        state = film.WatchState(
            length_s=length,
            position_s=float(row["position_s"]),
            watched_s=float(row["watched_s"]),
            audible_s=float(row["audible_s"]),
            focused_s=float(row["focused_s"]),
            wall_s=float(row["wall_s"]),
            seeks=int(row["seeks"]),
            max_rate=float(row["max_rate"]),
            seen=set(json.loads(row["seen_json"] or "[]")),
        )
        film.apply_beat(
            state, position_s, gap, muted=muted, hidden=hidden, rate=rate,
        )
        verdict = film.assess(state)

        awarded = int(row["xp_awarded"])
        if verdict == film.Verdict.WATCHED and not awarded:
            awarded = self._award_film_xp(athlete_id, watch_id, now.date())

        with transaction(self.conn) as conn:
            conn.execute(
                "UPDATE clip_watches SET position_s = ?, watched_s = ?, audible_s = ?, "
                "focused_s = ?, wall_s = ?, seeks = ?, max_rate = ?, seen_json = ?, "
                "verdict = ?, xp_awarded = ?, last_beat_at = ? WHERE id = ?",
                (state.position_s, state.watched_s, state.audible_s, state.focused_s,
                 state.wall_s, state.seeks, state.max_rate,
                 json.dumps(sorted(state.seen)), verdict, awarded,
                 _iso(now), watch_id),
            )
        return {
            "watch_id": watch_id, "verdict": verdict, "xp_awarded": awarded,
            **state.to_dict(),
            "day": self.film_day(athlete_id, now.date()).to_dict(),
        }

    def _award_film_xp(self, athlete_id: int, watch_id: int, day: date) -> int:
        """Small, capped, and the same whether the answer was right.

        Being wrong about a slide is the entire reason to watch film, so the
        reward is for attention rather than correctness -- and it is capped
        low so that a kid cannot out-earn training by watching video.

        Paid once per clip, ever. Rewatching is deliberately outside the
        economy: the moment it pays, the cheapest XP in the product is
        replaying yesterday's clip with the sound on, and the second look --
        the behaviour this whole feature exists to encourage -- stops meaning
        anything the moment it is worth points.
        """
        paid = self.conn.execute(
            "SELECT 1 FROM clip_watches w "
            "WHERE w.athlete_id = ? AND w.xp_awarded > 0 AND w.id != ? "
            "  AND w.clip_id = (SELECT clip_id FROM clip_watches WHERE id = ?)",
            (athlete_id, watch_id, watch_id),
        ).fetchone()
        if paid is not None:
            return 0

        already = self.conn.execute(
            "SELECT COALESCE(SUM(xp_awarded), 0) AS t FROM clip_watches "
            "WHERE athlete_id = ? AND day = ?",
            (athlete_id, day.isoformat()),
        ).fetchone()
        room = max(0, film.XP_DAILY_CAP - int(already["t"]))
        amount = min(film.XP_PER_WATCH, room)
        if amount <= 0:
            return 0
        with transaction(self.conn) as conn:
            conn.execute(
                "INSERT INTO xp_ledger(athlete_id, session_id, amount, reason, day, "
                "created_at) VALUES (?,?,?,?,?,?)",
                (athlete_id, None, amount, f"film:{watch_id}", day.isoformat(),
                 _iso(_now())),
            )
        return amount

    def answer_clip(
        self, athlete_id: int, watch_id: int, choice: int
    ) -> dict[str, Any]:
        """Record what they picked, and tell them why.

        Getting it wrong costs nothing and is not reported to a coach as a
        score. What a coach sees is who is watching, not who is clever.
        """
        row = self.conn.execute(
            "SELECT w.id, c.question FROM clip_watches w JOIN clips c ON c.id = w.clip_id "
            "WHERE w.id = ? AND w.athlete_id = ?",
            (watch_id, athlete_id),
        ).fetchone()
        if row is None:
            raise StoreError("no watch with that id")
        if not row["question"]:
            raise StoreError("that clip has no question")

        question = json.loads(row["question"])
        correct = int(choice) == int(question["answer"])
        with transaction(self.conn) as conn:
            conn.execute(
                "UPDATE clip_watches SET answered = ?, answer_ok = ? WHERE id = ?",
                (int(choice), int(correct), watch_id),
            )
        return {
            "correct": correct,
            "answer": int(question["answer"]),
            "because": question.get("because", ""),
        }

    def second_looks(
        self, athlete_ids: list[int], days: int = 28
    ) -> dict[str, Any]:
        """Clips these athletes went back to, grouped by clip.

        Grouped by clip rather than by athlete because the useful output is a
        practice plan. The same rows sorted athlete-first would be a list of
        the kids who need the most help, which nobody asked for and which
        would be read that way whatever it was labelled.
        """
        start = (_now().date() - timedelta(days=days - 1)).isoformat()
        clips = rewatch.for_clips(self.conn, athlete_ids, since=start)
        return {
            "days": days,
            "clips": [clip.to_dict() for clip in clips],
            # Said on the coach's screen too, so nobody reads this list as a
            # list of athletes who are behind.
            "how_to_read": (
                "Going back to a clip is the film module working. These are "
                "the athletes checking their own understanding, and the clips "
                "worth a few minutes at practice -- not a list of who is "
                "struggling."
            ),
        }

    def film_history(
        self, athlete_id: int, days: int = 28
    ) -> dict[str, Any]:
        start = (_now().date() - timedelta(days=days - 1)).isoformat()
        rows = self.conn.execute(
            "SELECT w.day, w.verdict, w.watched_s, c.title FROM clip_watches w "
            "JOIN clips c ON c.id = w.clip_id "
            "WHERE w.athlete_id = ? AND w.day >= ? ORDER BY w.day DESC, w.id DESC",
            (athlete_id, start),
        ).fetchall()
        watched = [r for r in rows if r["verdict"] == film.Verdict.WATCHED]
        # Film keeps its own streak rather than feeding the training one. A
        # clip is worth less XP than the streak threshold on purpose: letting
        # film hold the training streak would mean a streak maintained from
        # the sofa, which is the opposite of what the streak is for.
        watched_days = sorted({date.fromisoformat(r["day"]) for r in watched})
        # Paused by an absence too. A child on a family holiday is not
        # expected to keep up with the app at all, and a film streak that
        # survives the trip while the training streak does not would be an
        # odd thing to teach them.
        streak = compute_streak(
            watched_days, _now().date(),
            paused=absence.paused_days(self.conn, athlete_id),
        )
        return {
            "streak": streak.current,
            "longest_streak": streak.longest,
            "days": len({r["day"] for r in watched}),
            "clips": len(watched),
            "minutes": round(sum(float(r["watched_s"]) for r in watched) / 60.0, 1),
            "recent": [
                {"day": r["day"], "title": r["title"], "verdict": r["verdict"]}
                for r in rows[:20]
            ],
        }

    def team_film(
        self, athlete_ids: list[int], days: int = 7
    ) -> dict[str, Any]:
        """Who is putting the time in, without ranking anyone by minutes."""
        if not athlete_ids:
            return {"athletes": [], "clips_watched": 0, "days": days}
        start = (_now().date() - timedelta(days=days - 1)).isoformat()
        marks = ",".join("?" for _ in athlete_ids)
        rows = self.conn.execute(
            f"SELECT w.athlete_id, u.display_name, "
            f"  SUM(CASE WHEN w.verdict = 'watched' THEN 1 ELSE 0 END) AS watched, "
            f"  COUNT(*) AS started, "
            f"  COUNT(DISTINCT CASE WHEN w.verdict = 'watched' THEN w.day END) AS days "
            f"FROM clip_watches w JOIN users u ON u.id = w.athlete_id "
            f"WHERE w.athlete_id IN ({marks}) AND w.day >= ? "
            f"GROUP BY w.athlete_id ORDER BY days DESC, watched DESC",
            (*athlete_ids, start),
        ).fetchall()
        return {
            "days": days,
            "clips_watched": sum(int(r["watched"]) for r in rows),
            "athletes": [
                {
                    "athlete_id": int(r["athlete_id"]),
                    "display_name": r["display_name"],
                    "clips_watched": int(r["watched"]),
                    "clips_started": int(r["started"]),
                    "days_with_film": int(r["days"]),
                }
                for r in rows
            ],
        }

    def team_ball_drills(
        self, athlete_ids: list[int], days: int = 14
    ) -> dict[str, Any]:
        """Skill work, and who needs help pointing their phone.

        The framing figure is the useful half. An athlete whose sessions keep
        coming back with the ball barely visible is not slacking and is not
        cheating -- they have propped their phone somewhere it cannot see, and
        that is two minutes of a coach's time to fix. Nothing else in this
        product can tell a coach that.

        Reports touches rather than minutes, and does not rank by volume, for
        the same reason every other board here does not.
        """
        if not athlete_ids:
            return {"days": days, "athletes": [], "drills": [], "needs_framing_help": []}

        start = (_now().date() - timedelta(days=days - 1)).isoformat()
        marks = ",".join("?" for _ in athlete_ids)
        ball_keys = [d.key for d in ALL_DRILLS if d.ball is not None]
        if not ball_keys:
            return {"days": days, "athletes": [], "drills": [], "needs_framing_help": []}
        drill_marks = ",".join("?" for _ in ball_keys)

        rows = self.conn.execute(
            f"SELECT s.athlete_id, u.display_name, s.drill_key, s.status, "
            f"       s.reps_total, s.reps_left, s.reps_right, s.mean_confidence, "
            f"       s.duration_ms, s.day AS day "
            f"FROM ("
            f"  SELECT *, date(COALESCE(completed_at, submitted_at)) AS day "
            f"  FROM sessions WHERE athlete_id IN ({marks}) "
            f"  AND drill_key IN ({drill_marks}) AND status != 'open'"
            f") s JOIN users u ON u.id = s.athlete_id "
            f"WHERE s.day >= ? ORDER BY s.athlete_id",
            (*athlete_ids, *ball_keys, start),
        ).fetchall()

        by_athlete: dict[int, dict[str, Any]] = {}
        by_drill: dict[str, dict[str, Any]] = {}
        for row in rows:
            athlete = by_athlete.setdefault(int(row["athlete_id"]), {
                "athlete_id": int(row["athlete_id"]),
                "display_name": row["display_name"],
                "touches": 0, "sessions": 0, "held": 0,
                "left": 0, "right": 0,
                "framing_sum": 0.0, "framing_n": 0,
                "drills": set(),
            })
            athlete["sessions"] += 1
            athlete["drills"].add(row["drill_key"])
            if row["status"] == "counted":
                athlete["touches"] += int(row["reps_total"] or 0)
                athlete["left"] += int(row["reps_left"] or 0)
                athlete["right"] += int(row["reps_right"] or 0)
            elif row["status"] == "review":
                athlete["held"] += 1
            # Ball drills store the track quality in mean_confidence, which is
            # what the client sends for them.
            athlete["framing_sum"] += float(row["mean_confidence"] or 0)
            athlete["framing_n"] += 1

            drill = by_drill.setdefault(row["drill_key"], {
                "drill_key": row["drill_key"],
                "name": DRILLS_BY_KEY[row["drill_key"]].name,
                "sport": DRILLS_BY_KEY[row["drill_key"]].sport,
                "athletes": set(), "touches": 0, "sessions": 0,
            })
            drill["athletes"].add(int(row["athlete_id"]))
            drill["sessions"] += 1
            if row["status"] == "counted":
                drill["touches"] += int(row["reps_total"] or 0)

        athletes = []
        for entry in by_athlete.values():
            framing = entry["framing_sum"] / entry["framing_n"] if entry["framing_n"] else 0
            hands = entry["left"] + entry["right"]
            athletes.append({
                **{k: v for k, v in entry.items()
                   if k not in ("framing_sum", "framing_n", "drills", "left", "right")},
                "drills": sorted(entry["drills"]),
                "framing": round(framing, 3),
                # Only reported where the drill attributes a side at all, and
                # as a share rather than a ranking.
                "weak_side_share": round(entry["left"] / hands, 3) if hands else None,
            })
        athletes.sort(key=lambda a: -a["touches"])

        drills = [
            {**d, "athletes": len(d["athletes"])}
            for d in sorted(by_drill.values(), key=lambda d: -d["sessions"])
        ]

        # The actionable list. Two or more sessions, because one badly propped
        # phone is an accident and three is a habit worth a word about.
        help_needed = [
            a for a in athletes
            if a["sessions"] >= 2 and a["framing"] < 0.30
        ]
        return {
            "days": days,
            "athletes": athletes,
            "drills": drills,
            "needs_framing_help": help_needed,
        }

    # ------------------------------------------------------------------
    # Coach recognition
    # ------------------------------------------------------------------

    def recognition_templates(self, org_id: int) -> list[dict[str, Any]]:
        """Every milestone, with the writer's own words where they wrote any.

        The shipped defaults differ for a household: a parent saying "see you
        at practice" sounds like a parent trying to talk like a coach, and a
        child hears the difference.
        """
        kind = "family" if self.is_family(org_id) else "program"
        rows = {
            r["milestone"]: r for r in self.conn.execute(
                "SELECT * FROM recognition_templates WHERE org_id = ?", (org_id,)
            )
        }
        out = []
        for milestone in recognition.MILESTONES:
            row = rows.get(milestone.key)
            entry = milestone.to_dict(
                body=row["body"] if row else "",
                customised=row is not None,
                from_voice=row["from_voice"] if row else "",
                kind=kind,
            )
            entry["enabled"] = bool(row["enabled"]) if row else True
            out.append(entry)
        return out

    def set_recognition_template(
        self, org_id: int, milestone: str, body: str, enabled: bool, actor_id: int,
        from_voice: str = recognition.Voice.COACH,
    ) -> dict[str, Any]:
        if milestone not in recognition.BY_KEY:
            raise StoreError(f"unknown milestone: {milestone!r}")
        if from_voice not in recognition.Voice.ALL:
            raise StoreError(f"unknown voice: {from_voice!r}")
        text = (body or "").strip()
        if enabled and not text:
            raise StoreError("a message needs some words, or turn the milestone off")
        with transaction(self.conn) as conn:
            conn.execute(
                "INSERT INTO recognition_templates(org_id, milestone, body, enabled, "
                "from_voice, updated_by, updated_at) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(org_id, milestone) DO UPDATE SET "
                "body = excluded.body, enabled = excluded.enabled, "
                "from_voice = excluded.from_voice, "
                "updated_by = excluded.updated_by, updated_at = excluded.updated_at",
                (org_id, milestone, text, 1 if enabled else 0, from_voice,
                 actor_id, _iso(_now())),
            )
        return {
            "milestone": milestone, "body": text,
            "enabled": enabled, "from_voice": from_voice,
        }

    def recognition_sent(self, org_id: int, limit: int = 40) -> list[dict[str, Any]]:
        """Recognition already sent to this program's athletes.

        The athlete's own copy rather than a guardian's, so a household with
        two parents linked does not read as two messages.
        """
        rows = self.conn.execute(
            "SELECT n.title, n.body, n.from_name, n.created_at, u.display_name "
            "FROM notifications n JOIN users u ON u.id = n.user_id "
            "WHERE n.kind = ? AND n.is_copy = 0 AND u.org_id = ? "
            "ORDER BY n.id DESC LIMIT ?",
            (notifications.Kind.RECOGNITION, org_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def preview_recognition(
        self, org_id: int, body: str, athlete_id: int | None = None,
    ) -> dict[str, Any]:
        """Show exactly what a message will look like when it lands.

        Rendered by the same function that sends it rather than a copy in the
        browser, so what a parent reads in the preview and what their child
        reads on the day cannot drift apart.
        """
        athlete = None
        if athlete_id is not None:
            athlete = self.conn.execute(
                "SELECT display_name, org_id FROM users WHERE id = ? AND org_id = ?",
                (athlete_id, org_id),
            ).fetchone()
        if athlete is None:
            athlete = self.conn.execute(
                "SELECT display_name, org_id FROM users WHERE org_id = ? "
                "AND role = 'athlete' AND active = 1 ORDER BY id LIMIT 1",
                (org_id,),
            ).fetchone()

        name = (athlete["display_name"] if athlete else "") or "Your athlete"
        first_name = name.split()[0]
        sender_id, sender = (
            self._recognising_coach(int(athlete["id"]), org_id)
            if athlete and "id" in athlete.keys()
            else (None, "")
        )
        if not sender:
            row = self.conn.execute(
                "SELECT display_name FROM users WHERE org_id = ? AND role = 'director' "
                "ORDER BY id LIMIT 1",
                (org_id,),
            ).fetchone()
            sender = row["display_name"] if row else "Your coach"

        team = self.conn.execute(
            "SELECT name FROM teams WHERE org_id = ? ORDER BY id LIMIT 1", (org_id,)
        ).fetchone()
        return {
            "preview": recognition.render(
                body, first_name=first_name, streak=10,
                coach=sender, team=team["name"] if team else "",
            ),
            "as_read_by": first_name,
            "signed": sender,
        }

    def set_program_voice(self, org_id: int, name: str, title: str) -> dict[str, Any]:
        """Name the senior figure whose recognition carries extra weight."""
        with transaction(self.conn) as conn:
            conn.execute(
                "UPDATE organizations SET voice_name = ?, voice_title = ? WHERE id = ?",
                (name.strip()[:120], title.strip()[:120], org_id),
            )
        return self.program_voice(org_id)

    def program_voice(self, org_id: int) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT voice_name, voice_title FROM organizations WHERE id = ?", (org_id,)
        ).fetchone()
        return {
            "name": row["voice_name"] if row else "",
            "title": row["voice_title"] if row else "",
        }

    def _recognising_coach(self, athlete_id: int, org_id: int) -> tuple[int | None, str]:
        """Whose name goes on the message.

        The coach assigned to the athlete's team if there is one, else a
        director. A name matters more than picking the perfect person: a kid
        reading "Coach Ada noticed" does not audit the org chart.
        """
        row = self.conn.execute(
            "SELECT u.id, u.display_name FROM team_staff ts "
            "JOIN users u ON u.id = ts.user_id "
            "JOIN team_members tm ON tm.team_id = ts.team_id "
            "WHERE tm.user_id = ? ORDER BY ts.created_at LIMIT 1",
            (athlete_id,),
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT id, display_name FROM users WHERE org_id = ? AND role = 'director' "
                "AND active = 1 ORDER BY id LIMIT 1",
                (org_id,),
            ).fetchone()
        if row is None:
            return None, "Your coach"
        return int(row["id"]), row["display_name"]

    def _team_name(self, athlete_id: int) -> str:
        row = self.conn.execute(
            "SELECT t.name FROM team_members tm JOIN teams t ON t.id = tm.team_id "
            "WHERE tm.user_id = ? ORDER BY tm.joined_at DESC LIMIT 1",
            (athlete_id,),
        ).fetchone()
        return row["name"] if row else ""

    def award_recognition(
        self, athlete_id: int, sessions_before: int, today: date | None = None
    ) -> list[str]:
        """Send whatever this session just earned. Returns the milestone keys.

        Called from the submit path rather than a nightly job, because "well
        done" an hour after a driveway session lands and "well done" the next
        morning is a report.

        `today` is the day the *session* counts for, not the wall clock. A
        session trained on Sunday in a dead zone and synced on Monday earns
        Sunday's streak, the same rule the rest of scoring follows.
        """
        today = today or _now().date()
        days = sorted(set(self._streak_days(athlete_id)))
        streak = compute_streak(
            days, today, paused=absence.paused_days(self.conn, athlete_id))

        # The first day of the current run, derived from the days themselves
        # rather than counted back from today.
        #
        # Counting back from today was a real bug and a nasty one: a run's
        # start moved by a day every day it continued, so the dedupe key
        # changed, and a ten-day streak sent the same "ten days straight"
        # message again on day eleven and day twelve. A child would learn to
        # ignore the app inside a week.
        start = None
        if streak.current > 0 and days:
            start = days[-1] - timedelta(days=streak.current - 1)

        crossed = recognition.earned(
            sessions_before=sessions_before,
            streak=streak.current,
            streak_start=start,
        )
        if not crossed:
            return []

        athlete = self.conn.execute(
            "SELECT display_name, org_id FROM users WHERE id = ?", (athlete_id,)
        ).fetchone()
        if athlete is None:
            return []
        first_name = (athlete["display_name"] or "").split()[0] if athlete["display_name"] else ""
        coach_id, coach_name = self._recognising_coach(athlete_id, int(athlete["org_id"]))
        team = self._team_name(athlete_id)
        templates = {
            t["key"]: t for t in self.recognition_templates(int(athlete["org_id"]))
        }

        voice = self.program_voice(int(athlete["org_id"]))

        sent = []
        for milestone, key in crossed:
            template = templates.get(milestone.key, {})
            if not template.get("enabled", True):
                continue

            # A senior figure's name only where the program has actually named
            # one. Falling back to the coach means a program that never fills
            # this in still sends something signed by a real person, rather
            # than a message from nobody.
            wants_voice = template.get("from_voice") == recognition.Voice.VOICE
            if wants_voice and voice["name"]:
                sender = voice["name"]
                title = voice["title"]
            else:
                sender = coach_name
                title = ""

            # The athlete's language, because the message is written to them.
            # A guardian gets this copy as sent rather than a re-translation:
            # showing a parent different words from the ones their child read
            # would make one message look like two.
            body = recognition.render(
                template.get("body") or milestone.body_for(
                    "family" if self.is_family(int(athlete["org_id"])) else "program",
                    self.locale_for(athlete_id),
                ),
                first_name=first_name, streak=streak.current,
                coach=sender, team=team,
            )
            made = notifications.enqueue(
                self.conn,
                athlete_id,
                notifications.Kind.RECOGNITION,
                f"{sender} noticed" if not title else f"{sender}, {title}",
                body,
                link="/",
                dedupe_key=f"recognition:{key}",
                from_name=sender,
            )
            if made:
                sent.append(milestone.key)
        return sent

    # ------------------------------------------------------------------
    # Clips an athlete chooses to send a coach
    # ------------------------------------------------------------------

    #: Bounded hard. This is a child's video in a database, so it is a short
    #: clip or it is nothing.
    MAX_CLIP_BYTES = 12 * 1024 * 1024
    CLIP_RETENTION_DAYS = 30

    def _may_share_video(self, athlete_id: int) -> bool:
        return bool(guardians_mod.current_consents(self.conn, athlete_id).get(
            guardians_mod.Scope.COACH_VIDEO, False
        ))

    def share_clip(
        self,
        athlete_id: int,
        blob: bytes,
        *,
        session_id: int | None = None,
        drill_key: str = "",
        mime: str = "video/webm",
        note: str = "",
    ) -> dict[str, Any]:
        """Send one clip to the coaching staff.

        Two gates, both required and both checked here rather than in the
        client: a guardian has turned the consent on, and the athlete has
        picked this clip. There is deliberately no path that uploads a
        recording because a session happened.
        """
        if not self._may_share_video(athlete_id):
            raise StoreError(
                "A parent or guardian has to turn on coach video in their "
                "portal before a clip can be sent."
            )
        if not blob:
            raise StoreError("that clip is empty")
        if len(blob) > self.MAX_CLIP_BYTES:
            raise StoreError(
                f"that clip is too big — keep it under "
                f"{self.MAX_CLIP_BYTES // (1024 * 1024)}MB"
            )
        if mime not in ("video/webm", "video/mp4"):
            raise StoreError(f"unsupported clip format: {mime!r}")

        now = _now()
        expires = now + timedelta(days=self.CLIP_RETENTION_DAYS)
        with transaction(self.conn) as conn:
            cur = conn.execute(
                "INSERT INTO shared_clips(athlete_id, session_id, drill_key, mime, "
                "bytes, size_bytes, note, shared_at, expires_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (athlete_id, session_id, drill_key, mime, blob, len(blob),
                 note.strip()[:400], _iso(now), _iso(expires)),
            )
        return self.shared_clip(int(cur.lastrowid), with_bytes=False)

    def shared_clip(self, clip_id: int, with_bytes: bool = False) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM shared_clips WHERE id = ?", (clip_id,)
        ).fetchone()
        if row is None:
            raise StoreError("no clip with that id")
        out = {
            "id": int(row["id"]),
            "athlete_id": int(row["athlete_id"]),
            "session_id": row["session_id"],
            "drill_key": row["drill_key"],
            "mime": row["mime"],
            "size_bytes": int(row["size_bytes"]),
            "note": row["note"],
            "shared_at": row["shared_at"],
            "expires_at": row["expires_at"],
            "views": [
                dict(v) for v in self.conn.execute(
                    "SELECT viewer_name, viewed_at FROM shared_clip_views "
                    "WHERE clip_id = ? ORDER BY id",
                    (clip_id,),
                )
            ],
        }
        if with_bytes:
            out["bytes"] = row["bytes"]
        return out

    def shared_clips_for_athlete(self, athlete_id: int) -> list[dict[str, Any]]:
        """Video clips this athlete sent a coach.

        Named `shared_` because `clips_for_athlete` is film study's, and the
        first version of this shadowed it -- which broke the film shortlist
        silently rather than loudly, since both take an athlete and return
        clips.
        """
        return [
            self.shared_clip(int(r["id"]))
            for r in self.conn.execute(
                "SELECT id FROM shared_clips WHERE athlete_id = ? ORDER BY id DESC",
                (athlete_id,),
            )
        ]

    def shared_clips_for_org(
        self, org_id: int, athlete_ids: list[int]
    ) -> list[dict[str, Any]]:
        if not athlete_ids:
            return []
        marks = ",".join("?" for _ in athlete_ids)
        return [
            {**self.shared_clip(int(r["id"])), "display_name": r["display_name"]}
            for r in self.conn.execute(
                f"SELECT c.id, u.display_name FROM shared_clips c "
                f"JOIN users u ON u.id = c.athlete_id "
                f"WHERE c.athlete_id IN ({marks}) ORDER BY c.id DESC",
                athlete_ids,
            )
        ]

    def record_clip_view(self, clip_id: int, viewer_id: int, viewer_name: str) -> None:
        """Log that a coach watched it.

        Not optional and not sampled. A child's video being watched is exactly
        the kind of thing a parent may want to ask about later, and an audit
        trail that only sometimes records is not one.
        """
        with transaction(self.conn) as conn:
            conn.execute(
                "INSERT INTO shared_clip_views(clip_id, viewer_id, viewer_name, viewed_at) "
                "VALUES (?,?,?,?)",
                (clip_id, viewer_id, viewer_name, _iso(_now())),
            )

    def delete_shared_clip(self, clip_id: int, athlete_id: int | None = None) -> bool:
        sql = "DELETE FROM shared_clips WHERE id = ?"
        params: list[Any] = [clip_id]
        if athlete_id is not None:
            sql += " AND athlete_id = ?"
            params.append(athlete_id)
        with transaction(self.conn) as conn:
            return bool(conn.execute(sql, params).rowcount)

    def revoke_shared_clips(self, athlete_id: int) -> int:
        """Delete everything shared for this athlete, now.

        Called the moment a guardian turns the consent off. Withdrawing
        permission has to mean the video is gone, not that it stops being
        shown -- anything less makes the consent a preference rather than a
        permission.
        """
        with transaction(self.conn) as conn:
            return conn.execute(
                "DELETE FROM shared_clips WHERE athlete_id = ?", (athlete_id,)
            ).rowcount

    def drill_log(self, athlete_id: int, days: int = 30) -> dict[str, Any]:
        """Every drill this athlete has done, for a parent or a coach.

        One shape used by both, so a parent is never shown a thinner version
        of their own child's training than the coach sees.
        """
        start = (_now().date() - timedelta(days=days - 1)).isoformat()
        rows = self.conn.execute(
            "SELECT id, drill_key, status, reps_total, reps_left, reps_right, "
            "  hold_ms, duration_ms, quality_score, xp_awarded, integrity_notes, "
            "  date(COALESCE(completed_at, submitted_at)) AS day "
            "FROM sessions WHERE athlete_id = ? AND status != 'open' "
            "AND date(COALESCE(completed_at, submitted_at)) >= ? "
            "ORDER BY id DESC",
            (athlete_id, start),
        ).fetchall()

        sessions, by_drill = [], {}
        for row in rows:
            drill = DRILLS_BY_KEY.get(row["drill_key"])
            entry = {
                "session_id": int(row["id"]),
                "drill_key": row["drill_key"],
                "drill": drill.name if drill else row["drill_key"],
                "sport": drill.sport if drill else "",
                "category": drill.category.value if drill else "",
                "day": row["day"],
                "status": row["status"],
                "reps": int(row["reps_total"] or 0),
                "left": int(row["reps_left"] or 0),
                "right": int(row["reps_right"] or 0),
                "hold_s": round(int(row["hold_ms"] or 0) / 1000),
                "minutes": round(int(row["duration_ms"] or 0) / 60000, 1),
                "quality": row["quality_score"],
                "xp": int(row["xp_awarded"] or 0),
                "notes": json.loads(row["integrity_notes"] or "[]"),
            }
            sessions.append(entry)
            bucket = by_drill.setdefault(row["drill_key"], {
                "drill_key": row["drill_key"],
                "drill": entry["drill"], "sport": entry["sport"],
                "sessions": 0, "reps": 0, "minutes": 0.0, "held": 0,
            })
            bucket["sessions"] += 1
            if row["status"] == "counted":
                bucket["reps"] += entry["reps"]
                bucket["minutes"] += entry["minutes"]
            else:
                bucket["held"] += 1

        for bucket in by_drill.values():
            bucket["minutes"] = round(bucket["minutes"], 1)
        counted = [s for s in sessions if s["status"] == "counted"]
        return {
            "days": days,
            "sessions": sessions[:200],
            "by_drill": sorted(by_drill.values(), key=lambda d: -d["sessions"]),
            "totals": {
                "sessions": len(counted),
                "reps": sum(s["reps"] for s in counted),
                "minutes": round(sum(s["minutes"] for s in counted), 1),
                "days_trained": len({s["day"] for s in counted}),
                "held": sum(1 for s in sessions if s["status"] != "counted"),
            },
        }

    # ------------------------------------------------------------------
    # Families running it themselves
    # ------------------------------------------------------------------

    #: A family is a program with one household in it. Building it that way
    #: rather than as a parallel account type means every feature written for
    #: a club -- assignments, budgets, recognition, wellness, the lot --
    #: works for a family on the day it ships, with no second code path to
    #: keep in step.
    FAMILY_KIND = "family"

    def create_family(
        self, family_name: str, parent_name: str, email: str | None = None,
    ) -> dict[str, Any]:
        """Set up a household with no club behind it.

        The parent ends up wearing both hats: director of their own tiny
        program, and guardian of their own children. Those are genuinely
        different roles -- one sets training, the other consents to it -- and
        keeping them as two records rather than one blurred super-role is what
        keeps the consent checks meaningful even when the same person is on
        both sides of them.
        """
        name = (family_name or "").strip() or f"{parent_name.strip()} family"
        with transaction(self.conn) as conn:
            cur = conn.execute(
                "INSERT INTO organizations(name, sport, kind, created_at) "
                "VALUES (?,?,?,?)",
                (name[:200], "general", self.FAMILY_KIND, _iso(_now())),
            )
            org_id = int(cur.lastrowid)

        parent = self.create_user(org_id, "director", parent_name, email=email)
        team = self.create_team(org_id, "Home")
        billing_mod.start_subscription(self.conn, org_id, "family", trial=False)
        self.conn.commit()
        return {"org_id": org_id, "parent": parent, "team": team, "kind": self.FAMILY_KIND}

    def add_family_athlete(
        self,
        org_id: int,
        parent_id: int,
        display_name: str,
        *,
        birth_year: int | None = None,
        dominant_hand: str | None = None,
        join_code: str | None = None,
    ) -> dict[str, Any]:
        """Add a child, and link the parent to them as guardian in one step.

        In a club the guardian link is an invitation a coach sends and a parent
        redeems, because the two are different people. Here they are the same
        person and a code posted to yourself is theatre -- so the link is made
        directly, with participation consent recorded as given by the parent
        who just created the account.
        """
        if not self.is_family(org_id):
            raise StoreError("that program is not a family account")

        athlete = self.create_user(
            org_id, "athlete", display_name,
            birth_year=birth_year, dominant_hand=dominant_hand,
        )
        if join_code:
            self.join_team(join_code, athlete["id"])

        # Linked directly rather than through an invite code. In a club that
        # code exists because the coach and the parent are different people
        # and the code is how one proves the other; posting a code to yourself
        # is theatre.
        with transaction(self.conn) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO guardians(guardian_id, athlete_id, "
                "relationship, linked_at) VALUES (?,?,?,?)",
                (parent_id, athlete["id"], "parent", _iso(_now())),
            )
        guardians_mod.set_consent(
            self.conn, athlete["id"], parent_id,
            guardians_mod.Scope.PARTICIPATION, True, method="family_account",
        )
        return athlete

    def family_board(self, org_id: int) -> dict[str, Any]:
        """The household board: each child against their own recent self."""
        row = self.conn.execute(
            "SELECT sibling_compare FROM organizations WHERE id = ?", (org_id,)
        ).fetchone()
        return family.household(
            self.conn, org_id,
            compare_siblings=bool(row["sibling_compare"]) if row else False,
        ).to_dict()

    def set_sibling_compare(self, org_id: int, on: bool) -> dict[str, Any]:
        if not self.is_family(org_id):
            raise StoreError("side-by-side is a family setting")
        with transaction(self.conn) as conn:
            conn.execute(
                "UPDATE organizations SET sibling_compare = ? WHERE id = ?",
                (1 if on else 0, org_id),
            )
        return {"compare_siblings": on}

    def is_family(self, org_id: int) -> bool:
        row = self.conn.execute(
            "SELECT kind FROM organizations WHERE id = ?", (org_id,)
        ).fetchone()
        return bool(row and row["kind"] == self.FAMILY_KIND)

    # ------------------------------------------------------------------
    # Athletes the camera was not built for
    # ------------------------------------------------------------------

    def adaptive_profile(self, athlete_id: int) -> "adaptive.Profile":
        return adaptive.get(self.conn, athlete_id)

    def set_adaptive_profile(
        self,
        athlete_id: int,
        accommodations: list[str],
        *,
        set_by: int | None = None,
        set_by_name: str = "",
        note: str = "",
    ) -> "adaptive.Profile":
        return adaptive.set_profile(
            self.conn, athlete_id, accommodations,
            set_by=set_by, set_by_name=set_by_name, note=note,
        )

    def log_self_reported(
        self,
        athlete_id: int,
        drill_key: str,
        *,
        minutes: int,
        reps: int = 0,
        note: str = "",
        day: date | None = None,
    ) -> dict[str, Any]:
        """Record work the camera could not count.

        Gated on the accommodation, not offered to everybody: a general
        self-report button would be a way around the integrity layer for any
        athlete who wanted one. Here it exists because the alternative is an
        athlete whose training this app structurally cannot see, and a streak
        that punishes them for it.

        Marked `self_reported` for ever. It counts for turning up -- streaks,
        participation, the squad goal -- and is kept out of every statistic
        that needs a measured number, because nobody measured it.
        """
        profile = adaptive.get(self.conn, athlete_id)
        if not profile.may_self_report:
            raise StoreError(
                "self-reported sessions are not switched on for this athlete"
            )
        if drill_key not in DRILLS_BY_KEY:
            raise StoreError(f"unknown drill: {drill_key!r}")
        if minutes <= 0 or minutes > 240:
            raise StoreError("minutes must be between 1 and 240")

        day = day or _now().date()
        stamp = f"{day.isoformat()}T12:00:00+00:00"
        with transaction(self.conn) as conn:
            cur = conn.execute(
                "INSERT INTO sessions(athlete_id, drill_key, nonce, started_at, "
                "  submitted_at, completed_at, duration_ms, reps_total, status, "
                "  integrity_score, integrity_notes, self_reported) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
                (athlete_id, drill_key, f"self-{new_token()}", stamp, stamp, stamp,
                 minutes * 60_000, max(0, reps), "counted", 1.0,
                 json.dumps([
                     "Logged by the athlete because the camera could not count "
                     "this work." + (f" Note: {note.strip()[:200]}" if note.strip() else "")
                 ])),
            )
            session_id = int(cur.lastrowid)

        # XP on the same footing as any other session of that length, because
        # the point of the streak is turning up and they turned up.
        awarded = self._award_self_reported(athlete_id, session_id, drill_key, day)
        return {
            "session_id": session_id,
            "day": day.isoformat(),
            "minutes": minutes,
            "xp_awarded": awarded,
            "self_reported": True,
        }

    def _award_self_reported(
        self, athlete_id: int, session_id: int, drill_key: str, day: date
    ) -> int:
        """A flat, modest award. Deliberately not scaled by the reps claimed.

        Scaling it would put a number nobody measured on the same footing as
        one the app counted, and would hand exactly the wrong incentive to the
        one path here that is not verified.
        """
        award = CONFIG.scoring.streak_min_xp
        with transaction(self.conn) as conn:
            conn.execute(
                "INSERT INTO xp_ledger(athlete_id, session_id, amount, reason, "
                "day, created_at) VALUES (?,?,?,?,?,?)",
                (athlete_id, session_id, award,
                 f"{DRILLS_BY_KEY[drill_key].name} (logged by athlete)",
                 day.isoformat(), _iso(_now())),
            )
            conn.execute(
                "UPDATE sessions SET xp_awarded = ? WHERE id = ?",
                (award, session_id),
            )
        return award

    # ------------------------------------------------------------------
    # Language
    # ------------------------------------------------------------------

    def locale_for(self, user_id: int) -> str:
        """One person's language. Per person, never per program.

        A Spanish-speaking household inside an English-speaking club is the
        common case rather than the edge one.
        """
        row = self.conn.execute(
            "SELECT locale FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return i18n.normalize(row["locale"] if row else None)

    def set_locale(self, user_id: int, locale: str) -> str:
        chosen = i18n.normalize(locale)
        with transaction(self.conn) as conn:
            conn.execute(
                "UPDATE users SET locale = ? WHERE id = ?", (chosen, user_id)
            )
        return chosen

    # ------------------------------------------------------------------
    # Keeping a roster in step with wherever it lives
    # ------------------------------------------------------------------

    def link_roster(
        self,
        org_id: int,
        team_id: int,
        provider: str,
        token: str,
        remote_ref: str,
        actor_id: int | None = None,
    ) -> dict[str, Any]:
        """Wire a team up to its roster source.

        Auto-sync starts off. A coach sees one dry run first and agrees with
        it before anything is allowed to write -- a sync that starts changing
        a roster the moment it is connected is a sync nobody trusts, and the
        first run is exactly when a wrong team id shows up.
        """
        if provider not in roster_sync.BY_KEY:
            raise StoreError(f"unknown roster provider: {provider!r}")
        if not remote_ref.strip():
            raise StoreError(
                f"{roster_sync.BY_KEY[provider].team_field} is required"
            )
        team = self.conn.execute(
            "SELECT id FROM teams WHERE id = ? AND org_id = ?", (team_id, org_id)
        ).fetchone()
        if team is None:
            raise StoreError("no such team in this program")

        with transaction(self.conn) as conn:
            conn.execute(
                "INSERT INTO roster_links(org_id, team_id, provider, token, "
                "remote_ref, created_by, created_at) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(team_id, provider) DO UPDATE SET "
                "token = excluded.token, remote_ref = excluded.remote_ref",
                (org_id, team_id, provider, token.strip(), remote_ref.strip(),
                 actor_id, _iso(_now())),
            )
        return self.roster_link(team_id, provider)

    def roster_link(self, team_id: int, provider: str) -> dict[str, Any]:
        """One link, without its token. The token never comes back out."""
        row = self.conn.execute(
            "SELECT id, org_id, team_id, provider, remote_ref, auto_sync, "
            "  last_run_at, last_result, token != '' AS has_token "
            "FROM roster_links WHERE team_id = ? AND provider = ?",
            (team_id, provider),
        ).fetchone()
        if row is None:
            raise StoreError("that team is not linked to that provider")
        spec = roster_sync.BY_KEY[row["provider"]]
        return {
            "id": int(row["id"]),
            "team_id": int(row["team_id"]),
            "provider": row["provider"],
            "label": spec.label,
            "remote_ref": row["remote_ref"],
            "auto_sync": bool(row["auto_sync"]),
            "has_token": bool(row["has_token"]),
            "last_run_at": row["last_run_at"],
            "last_result": json.loads(row["last_result"]) if row["last_result"] else None,
            "verified": spec.verified,
            "note": spec.note,
        }

    def roster_links(self, org_id: int) -> list[dict[str, Any]]:
        return [
            {**self.roster_link(int(r["team_id"]), r["provider"]), "team_name": r["name"]}
            for r in self.conn.execute(
                "SELECT rl.team_id, rl.provider, t.name FROM roster_links rl "
                "JOIN teams t ON t.id = rl.team_id WHERE rl.org_id = ? ORDER BY t.name",
                (org_id,),
            )
        ]

    def unlink_roster(self, org_id: int, team_id: int, provider: str) -> bool:
        with transaction(self.conn) as conn:
            return bool(conn.execute(
                "DELETE FROM roster_links WHERE org_id = ? AND team_id = ? "
                "AND provider = ?",
                (org_id, team_id, provider),
            ).rowcount)

    def set_roster_auto_sync(self, org_id: int, team_id: int, provider: str, on: bool):
        with transaction(self.conn) as conn:
            conn.execute(
                "UPDATE roster_links SET auto_sync = ? WHERE org_id = ? "
                "AND team_id = ? AND provider = ?",
                (1 if on else 0, org_id, team_id, provider),
            )
        return self.roster_link(team_id, provider)

    def sync_roster(
        self,
        org_id: int,
        team_id: int,
        provider: str,
        dry_run: bool = True,
        actor_id: int | None = None,
    ) -> dict[str, Any]:
        """Fetch, compare, and -- unless this is a dry run -- apply.

        Departures are counted and reported but never applied. Somebody
        vanishing from a remote roster is the one event continuous sync adds
        that a one-off import never had, and the tempting thing to do with it
        is delete.
        """
        row = self.conn.execute(
            "SELECT token, remote_ref FROM roster_links WHERE org_id = ? "
            "AND team_id = ? AND provider = ?",
            (org_id, team_id, provider),
        ).fetchone()
        if row is None:
            raise StoreError("that team is not linked to that provider")

        spec = roster_sync.BY_KEY[provider]
        result = roster_sync.SyncResult(provider=provider, dry_run=dry_run)
        try:
            rows = spec.fetch(row["token"], row["remote_ref"])
        except roster_sync.SyncError as exc:
            result.error = str(exc)
            self._record_sync(team_id, provider, result)
            return result.to_dict()

        result.fetched = len(rows)
        if not rows:
            result.error = (
                "They returned an empty roster. Nothing has been changed — "
                "that is almost always a wrong team id rather than an empty team."
            )
            self._record_sync(team_id, provider, result)
            return result.to_dict()

        plan = self.resolve_import(org_id, roster_mod.parse(roster_sync.rows_to_csv(rows)))
        result.created = len(plan.creates)
        result.updated = len(plan.updates)
        result.unchanged = max(0, len(plan.athletes) - result.created - result.updated)
        result.warnings = [
            w for a in plan.athletes for w in a.warnings
        ][:10]

        seen = {roster_mod.match_key(a.display_name) for a in plan.athletes if a.ok}
        result.departures = roster_sync.find_departures(self.conn, team_id, seen)

        on_roster = self.conn.execute(
            "SELECT COUNT(*) AS n FROM team_members tm JOIN users u ON u.id = tm.user_id "
            "WHERE tm.team_id = ? AND u.role = 'athlete' AND u.active = 1",
            (team_id,),
        ).fetchone()["n"]
        # A wrong team id and a mass exodus look identical from here, and only
        # one of them is plausible. Refusing is recoverable; applying is not.
        if on_roster and len(result.departures) / on_roster > roster_sync.DEPARTURE_ALARM:
            result.error = (
                f"{len(result.departures)} of {on_roster} athletes are missing "
                "from their roster. That is more likely a wrong team id than a "
                "real change, so nothing has been applied."
            )
            self._record_sync(team_id, provider, result)
            return result.to_dict()

        if not dry_run:
            self.apply_import(org_id, team_id, plan, actor_id or 0)

        self._record_sync(team_id, provider, result)
        return result.to_dict()

    def _record_sync(self, team_id: int, provider: str, result) -> None:
        with transaction(self.conn) as conn:
            conn.execute(
                "UPDATE roster_links SET last_run_at = ?, last_result = ? "
                "WHERE team_id = ? AND provider = ?",
                (_iso(_now()), json.dumps(result.to_dict()), team_id, provider),
            )

    def due_roster_syncs(self, older_than_hours: int = 12) -> list[tuple[int, int, str]]:
        """Links with auto-sync on that have not run recently."""
        cutoff = _iso(_now() - timedelta(hours=older_than_hours))
        return [
            (int(r["org_id"]), int(r["team_id"]), r["provider"])
            for r in self.conn.execute(
                "SELECT org_id, team_id, provider FROM roster_links "
                "WHERE auto_sync = 1 AND (last_run_at IS NULL OR last_run_at < ?)",
                (cutoff,),
            )
        ]

    # ------------------------------------------------------------------
    # Org / team / user setup
    # ------------------------------------------------------------------

    def create_org(self, name: str, sport: str = "lacrosse") -> int:
        with transaction(self.conn) as c:
            cur = c.execute(
                "INSERT INTO organizations(name, sport, created_at) VALUES (?,?,?)",
                (name, sport, _iso(_now())),
            )
        org_id = int(cur.lastrowid)
        # New programs start on a full-capability trial rather than the free
        # plan. Hitting a paywall on your second team before the product has
        # shown anyone anything is how an evaluation ends.
        billing_mod.start_subscription(
            self.conn, org_id, billing_mod.TRIAL_PLAN, trial=True, actor="signup"
        )
        return org_id

    def create_team(self, org_id: int, name: str, season: str = "") -> dict[str, Any]:
        billing_mod.check_can_add_team(self.conn, org_id)
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

        # Growth is what billing gates. Guardians are free -- charging a club
        # per parent would price out exactly the involvement the product needs.
        if role == "athlete":
            billing_mod.check_can_add_athletes(self.conn, org_id, 1)
        elif role in ("coach", "director"):
            billing_mod.check_can_add_staff(self.conn, org_id)

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
            user_id = int(cur.lastrowid)
            c.execute(
                "INSERT OR REPLACE INTO memberships(user_id, org_id, role, created_at, active) "
                "VALUES (?,?,?,?,1)",
                (user_id, org_id, role, _iso(_now())),
            )
        return {"id": user_id, "token": token, "display_name": display_name}

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

    def authenticate(self, token: str, org_id: int | None = None) -> Principal:
        """Resolve a token to a caller acting in one program.

        A person may hold roles in several programs -- a school coach who also
        runs a club side is one human with two jobs -- so the active program is
        chosen per request, defaulting to their home org.
        """
        row = self.conn.execute(
            "SELECT id, org_id, role, display_name, dominant_hand FROM users "
            "WHERE token_hash = ? AND active = 1",
            (hash_token(token),),
        ).fetchone()
        if row is None:
            raise StoreError("invalid or inactive token")

        memberships = [
            Membership(org_id=m["org_id"], org_name=m["org_name"], role=m["role"])
            for m in self.conn.execute(
                "SELECT m.org_id, m.role, o.name AS org_name FROM memberships m "
                "JOIN organizations o ON o.id = m.org_id "
                "WHERE m.user_id = ? AND m.active = 1 ORDER BY o.name",
                (row["id"],),
            )
        ]
        if not memberships:
            # Predates memberships and the backfill has not run for this row.
            memberships = [Membership(row["org_id"], "", row["role"])]

        active = next((m for m in memberships if m.org_id == org_id), None) if org_id else None
        if org_id and active is None:
            raise StoreError("you do not have access to that program")
        if active is None:
            active = next(
                (m for m in memberships if m.org_id == row["org_id"]), memberships[0]
            )

        return Principal(
            id=row["id"],
            org_id=active.org_id,
            role=active.role,
            display_name=row["display_name"],
            dominant_hand=row["dominant_hand"],
            memberships=memberships,
            team_ids=self._team_scope(row["id"], active.org_id, active.role),
        )

    def _team_scope(self, user_id: int, org_id: int, role: str) -> list[int] | None:
        """Which teams this caller may see, or None for all of them.

        Directors see their whole program. A coach sees the teams they are
        assigned to -- because access should follow responsibility, and at a
        club with four hundred children blanket access is a safeguarding
        problem rather than a convenience.

        A coach with no assignments falls back to the whole program. That is a
        deliberate accommodation for accounts created before team assignment
        existed, not the intended end state: set OFFDAYS_STRICT_TEAM_SCOPE=1
        to make an unassigned coach see nothing instead.
        """
        if role != "coach":
            return None

        assigned = [
            r["team_id"]
            for r in self.conn.execute(
                "SELECT ts.team_id FROM team_staff ts JOIN teams t ON t.id = ts.team_id "
                "WHERE ts.user_id = ? AND t.org_id = ?",
                (user_id, org_id),
            )
        ]
        if assigned:
            return assigned
        return [] if CONFIG.strict_team_scope else None

    def assign_staff_to_team(self, user_id: int, team_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO team_staff(team_id, user_id, created_at) VALUES (?,?,?)",
            (team_id, user_id, _iso(_now())),
        )
        self.conn.commit()

    def unassign_staff_from_team(self, user_id: int, team_id: int) -> None:
        self.conn.execute(
            "DELETE FROM team_staff WHERE team_id = ? AND user_id = ?", (team_id, user_id)
        )
        self.conn.commit()

    def add_membership(self, user_id: int, org_id: int, role: str) -> None:
        """Give an existing person a role in another program."""
        if role not in ("athlete", "coach", "director", "guardian"):
            raise StoreError(f"invalid role: {role!r}")
        if role in ("coach", "director"):
            billing_mod.check_can_add_staff(self.conn, org_id)
        elif role == "athlete":
            billing_mod.check_can_add_athletes(self.conn, org_id, 1)
        self.conn.execute(
            "INSERT OR REPLACE INTO memberships(user_id, org_id, role, created_at, active) "
            "VALUES (?,?,?,?,1)",
            (user_id, org_id, role, _iso(_now())),
        )
        self.conn.commit()

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
                "gives consent in their 0FFDAYS portal."
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
        track_quality: float | None = None,
        ball_contacts: int | None = None,
        ball_travel: float | None = None,
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
                    zone=(str(r["zone"]) if r.get("zone") else None),
                    crossed=(None if r.get("crossed") is None
                             else bool(r["crossed"])),
                )
                for r in reps
            ],
            hold_ms=int(hold_ms),
            mean_confidence=float(mean_confidence),
            client_version=client_version,
        )
        # Counted before this session is written, so "your first one" is
        # recognised on the session that makes it true rather than the one
        # after it.
        sessions_before = int(self.conn.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE athlete_id = ? AND status = 'counted'",
            (athlete_id,),
        ).fetchone()["n"])

        adaptive_profile = adaptive.get(self.conn, athlete_id)
        verdict = evaluate(claim, drill)
        # An unusual movement pattern scores badly on checks written around a
        # typical one. Held for a person is a conversation; rejected is a
        # child told by software that they cheated.
        verdict = adaptive.soften_verdict(verdict, adaptive_profile)

        # Ball drills carry a second verdict. The browser did the tracking, so
        # the browser is where these numbers came from, so the browser cannot
        # be trusted with them -- the same reasoning that produced the pose
        # integrity layer, applied to a payload that is much easier to fake
        # because a contact is a timestamp rather than a whole skeleton.
        ball_review = None
        if drill.ball is not None:
            ball_review = ball_mod.review(
                drill,
                [
                    {"t_ms": r.t_ms, "hand": r.hand, "speed": getattr(r, "speed", None),
                     "part": getattr(r, "part", "")}
                    for r in claim.reps
                ],
                track_quality,
                claim.duration_ms,
                ball_contacts=ball_contacts,
                ball_travel=ball_travel,
            )
            if not ball_review.ok:
                verdict.status = "review"
            # Notes are shown either way. In confirm mode "we could not see a
            # ball" is information, not an accusation, and hiding it would
            # leave an athlete wondering why nothing happened.
            verdict.notes = list(verdict.notes) + ball_review.reasons + ball_review.notes

        hand = self._dominant_hand(athlete_id)

        # Cued drills carry a third verdict. Reps and form say how much work
        # was done and how well shaped it was; neither can reach the question
        # a goalie session actually asks, which is whether the hands got to
        # the spot somebody else picked and how long they took.
        #
        # The targets are re-derived here from the nonce rather than read off
        # the payload, so the only thing the client has any say in is where it
        # claims the hands went.
        save_report = None
        if drill.is_cued:
            save_report = goalie.analyze(
                drill,
                [{"t_ms": r.t_ms, "zone": r.zone} for r in claim.reps],
                nonce=nonce,
                duration_ms=claim.duration_ms,
                top_hand=hand,
            )

        # A stance-width drill carries the one technique fault this product can
        # establish rather than infer, so it is counted and handed straight
        # back to the athlete rather than left in the rep stream.
        footwork_report = None
        if drill.signal.kind is SignalKind.STANCE_WIDTH:
            footwork_report = footwork.analyze(
                [{"crossed": r.crossed} for r in claim.reps],
            )

        # Form quality reads the same rep stream the counting did, so it costs
        # nothing extra to collect and is the half of the signal a rep count
        # throws away.
        if adaptive_profile.scores_form:
            report = analyze_quality(
                drill,
                [
                    RepFeature(
                        t_ms=r.t_ms, hand=r.hand, confidence=r.confidence,
                        peak=r.peak, rom=r.rom, cycle_ms=r.cycle_ms,
                    )
                    for r in claim.reps
                ],
                # Suppressing the side comparison rather than filtering hands
                # out: passing no dominant hand is what "do not compare sides"
                # means to the scorer, and it keeps the per-rep data intact.
                dominant_hand=hand if adaptive_profile.compares_sides else None,
                hold_ms=claim.hold_ms,
                duration_ms=claim.duration_ms,
            )
        else:
            # Silent, not zero. A score of 34 against a range this athlete's
            # body does not have is worse than no score at all.
            report = QualityReport(
                coaching_note=(
                    "Technique scoring is off for you. Your counts, streak and "
                    "consistency all work exactly the same."
                )
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
                "INSERT INTO rep_events(session_id, t_ms, hand, confidence, peak, rom, "
                "cycle_ms, zone, crossed) VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (
                        session_id, r.t_ms,
                        r.hand if r.hand in ("left", "right") else "none",
                        r.confidence, r.peak, r.rom, r.cycle_ms, r.zone,
                        None if r.crossed is None else int(r.crossed),
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

        # Recognition fires here rather than in a nightly job: "well done" an
        # hour after a driveway session lands, and the same words the next
        # morning are a report. Only a counted session earns it -- a held one
        # has not been established as work yet.
        recognised: list[str] = []
        if verdict.status == "counted":
            recognised = self.award_recognition(
                athlete_id, sessions_before, date.fromisoformat(today),
            )

        result = {
            "session_id": session_id,
            "status": verdict.status,
            "recognition": recognised,
            "integrity_score": round(verdict.score, 3),
            "notes": verdict.notes,
            **({"ball": ball_review.to_dict()} if ball_review else {}),
            **({"saves": save_report.to_dict()} if save_report else {}),
            **({"footwork": footwork_report.to_dict()} if footwork_report else {}),
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
            # What "right" looks like for the thing that scored lowest. A
            # score without a fix is a mark out of ten, which is exactly what
            # this product is otherwise careful not to hand a twelve-year-old.
            "technique": technique.fix_for(drill.key, report.weakest)
                         if report.weakest else None,
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

    def staff_can_see_athlete(self, principal: "Principal", athlete_id: int) -> bool:
        """Whether a coach's team assignments cover this athlete.

        Checked wherever staff reach an individual athlete's data, not just on
        the roster listing: a scoped coach who can guess an id must not be able
        to read a child on another team by asking for them directly.
        """
        if principal.team_ids is None:
            owner = self.conn.execute(
                "SELECT org_id FROM users WHERE id = ?", (athlete_id,)
            ).fetchone()
            return owner is not None and owner["org_id"] == principal.org_id
        if not principal.team_ids:
            return False
        placeholders = ",".join("?" for _ in principal.team_ids)
        return self.conn.execute(
            f"SELECT 1 FROM team_members WHERE user_id = ? AND team_id IN ({placeholders})",
            (athlete_id, *principal.team_ids),
        ).fetchone() is not None

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

        streak = compute_streak(
            self._streak_days(athlete_id), _now().date(),
            paused=absence.paused_days(self.conn, athlete_id),
        )

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
            "SELECT u.id, u.display_name, u.dominant_hand, u.birth_year, o.sport "
            "FROM users u JOIN organizations o ON o.id = u.org_id WHERE u.id = ?",
            (athlete_id,),
        ).fetchone()
        if user is None:
            raise StoreError("unknown athlete")

        stats = self.athlete_stats(athlete_id)
        prog = level_progress(stats.total_xp)
        streak = compute_streak(
            self._streak_days(athlete_id), _now().date(),
            paused=absence.paused_days(self.conn, athlete_id),
        )

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
            # The client needs this to leave the athlete's own sport out of
            # the cross-sport transfer notes on every drill.
            "sport": user["sport"],
            "level": prog.level,
            "total_xp": prog.total_xp,
            "xp_into_level": prog.xp_into_level,
            "xp_for_next": prog.xp_for_next,
            "level_fraction": round(prog.fraction, 3),
            "streak": streak.current,
            "longest_streak": streak.longest,
            "streak_at_risk": streak.at_risk,
            # So the home screen can say the streak is safe rather than
            # leaving a child to wonder why it stopped counting.
            "away_note": absence.note(absence.current(self.conn, athlete_id)),
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
        # Prior injury makes a caution arrive earlier on the tissues involved.
        # It reaches here and the return-to-play flow; it deliberately does not
        # reach any coach-facing evaluation surface.
        history = injury_history.for_athlete(self.conn, athlete_id)
        return load_mod.analyze(
            self.load_history(athlete_id, CONFIG.load.chronic_days),
            today=_now().date(),
            age=age,
            tightened=history.tightening(),
            history_note=history.note(),
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
        # Wellness check-ins count too. This is the promise the whole soreness
        # feature rests on: saying "my knee hurts" must never cost a streak,
        # or athletes learn to say "fine" and the data stops meaning anything.
        return sorted(
            set(trained)
            | set(self._recovery_days(athlete_id))
            | set(self._checkin_days(athlete_id))
        )

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
    # Roster import
    # ------------------------------------------------------------------

    def resolve_import(self, org_id: int, plan: "roster_mod.ImportPlan") -> "roster_mod.ImportPlan":
        """Decide, per row, whether this is a new athlete or an existing one.

        Matched on the external id when the file carried one, otherwise on a
        normalized name within the program. Getting this right is what makes
        re-uploading a corrected file safe -- and coaches always re-upload.
        """
        existing = self.conn.execute(
            "SELECT id, display_name, external_id FROM users "
            "WHERE org_id = ? AND role = 'athlete' AND active = 1",
            (org_id,),
        ).fetchall()

        by_external = {
            r["external_id"]: r["id"] for r in existing if r["external_id"]
        }
        by_name: dict[str, list[int]] = {}
        for row in existing:
            by_name.setdefault(roster_mod.match_key(row["display_name"]), []).append(row["id"])

        for athlete in plan.athletes:
            if athlete.problems:
                continue

            if athlete.external_id and athlete.external_id in by_external:
                athlete.action = "update"
                athlete.existing_id = by_external[athlete.external_id]
                continue

            candidates = by_name.get(roster_mod.match_key(athlete.display_name), [])
            if len(candidates) == 1:
                athlete.action = "update"
                athlete.existing_id = candidates[0]
            elif len(candidates) > 1:
                # Two athletes already share this name. Guessing which one the
                # row means could overwrite the wrong child's record.
                athlete.action = "skip"
                athlete.problems.append(
                    "More than one athlete in this program has that name. "
                    "Add an ID column, or rename them, and import again."
                )
        return plan

    def apply_import(
        self,
        org_id: int,
        team_id: int,
        plan: "roster_mod.ImportPlan",
        created_by: int,
        *,
        issue_guardian_invites: bool = True,
    ) -> dict[str, Any]:
        """Create and update athletes from a resolved plan.

        Each new athlete gets a short claim code rather than a token: a bulk
        import mints hundreds of logins at once, and a token shown once on
        screen cannot be handed to two hundred kids. The coach prints the codes.
        """
        team = self.conn.execute(
            "SELECT id, org_id FROM teams WHERE id = ?", (team_id,)
        ).fetchone()
        if team is None:
            raise StoreError("unknown team")
        if team["org_id"] != org_id:
            raise StoreError("that team belongs to a different program")

        created: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        invites: list[dict[str, Any]] = []
        now = _iso(_now())

        for athlete in plan.athletes:
            if not athlete.ok:
                continue

            if athlete.action == "create":
                claim = roster_mod.new_claim_code()
                with transaction(self.conn) as c:
                    cur = c.execute(
                        "INSERT INTO users(org_id, role, display_name, email, birth_year, "
                        "dominant_hand, token_hash, created_at, external_id, "
                        "claim_code_hash, claim_expires_at, birth_year_estimated) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            org_id, "athlete", athlete.display_name, athlete.email,
                            athlete.birth_year, athlete.dominant_hand,
                            # A placeholder token nobody holds. The account is
                            # unusable until the claim code is redeemed, which
                            # is what replaces it.
                            hash_token(new_token()), now, athlete.external_id,
                            roster_mod.hash_claim(claim), roster_mod.claim_expiry(),
                            1 if athlete.birth_year_estimated else 0,
                        ),
                    )
                    athlete_id = int(cur.lastrowid)
                    c.execute(
                        "INSERT OR REPLACE INTO team_members(team_id, user_id, jersey, "
                        "position, joined_at) VALUES (?,?,?,?,?)",
                        (team_id, athlete_id, athlete.jersey, athlete.position, now),
                    )
                    _write_imported_sports(c, athlete_id, athlete.sports, now)
                created.append({
                    "athlete_id": athlete_id,
                    "display_name": athlete.display_name,
                    "jersey": athlete.jersey,
                    "claim_code": claim,
                })

            else:
                athlete_id = athlete.existing_id
                with transaction(self.conn) as c:
                    # Only overwrite fields the file actually supplied, so a
                    # partial roster does not blank out good data.
                    c.execute(
                        "UPDATE users SET "
                        "  dominant_hand = COALESCE(?, dominant_hand), "
                        "  birth_year = COALESCE(?, birth_year), "
                        "  external_id = COALESCE(?, external_id), "
                        "  email = COALESCE(?, email) "
                        "WHERE id = ?",
                        (
                            athlete.dominant_hand, athlete.birth_year,
                            athlete.external_id, athlete.email, athlete_id,
                        ),
                    )
                    c.execute(
                        "INSERT OR REPLACE INTO team_members(team_id, user_id, jersey, "
                        "position, joined_at) VALUES (?,?,?,?,?)",
                        (team_id, athlete_id, athlete.jersey, athlete.position, now),
                    )
                    _write_imported_sports(c, athlete_id, athlete.sports, now)
                updated.append({
                    "athlete_id": athlete_id,
                    "display_name": athlete.display_name,
                    "jersey": athlete.jersey,
                })

            if issue_guardian_invites and athlete.guardian_email:
                try:
                    invite = guardians_mod.create_invite(
                        self.conn, athlete_id, created_by, athlete.guardian_email
                    )
                    invites.append({
                        "athlete_id": athlete_id,
                        "athlete_name": athlete.display_name,
                        "email": athlete.guardian_email,
                        "code": invite["code"],
                    })
                except guardians_mod.GuardianError:
                    # A bad invite must not lose the athlete who was just
                    # imported successfully.
                    pass

        return {
            "created": created,
            "updated": updated,
            "guardian_invites": invites,
            "skipped": [a.to_dict() for a in plan.athletes if not a.ok],
        }

    def claim_account(self, code: str) -> dict[str, Any]:
        """Exchange a printed claim code for a login token.

        Single use: the code is cleared on redemption, so a slip picked up off
        a locker room floor after the fact is worthless.
        """
        row = self.conn.execute(
            "SELECT id, display_name, claim_expires_at FROM users "
            "WHERE claim_code_hash = ? AND active = 1",
            (roster_mod.hash_claim(code),),
        ).fetchone()

        expired = (
            row is not None
            and row["claim_expires_at"]
            and _parse(row["claim_expires_at"]) is not None
            and _parse(row["claim_expires_at"]) < _now()
        )
        if row is None or expired:
            raise StoreError(
                "That code is not valid. Ask your coach for a new one."
            )

        token = new_token()
        with transaction(self.conn) as c:
            c.execute(
                "UPDATE users SET token_hash = ?, claim_code_hash = NULL, "
                "claim_expires_at = NULL WHERE id = ?",
                (hash_token(token), row["id"]),
            )
        return {
            "athlete_id": row["id"],
            "display_name": row["display_name"],
            "token": token,
        }

    # ------------------------------------------------------------------
    # Guardian view
    # ------------------------------------------------------------------

    def guardian_summary(self, guardian_id: int) -> dict[str, Any]:
        locale = self.locale_for(guardian_id)
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
                # In the guardian's own language, not the program's.
                "consents": guardians_mod.consent_detail(
                    self.conn, athlete_id, locale),
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
