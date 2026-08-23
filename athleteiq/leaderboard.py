"""Leaderboards and coach roster rollups.

Two design choices worth stating, because both are about what the numbers do to
a 14-year-old rather than what is easiest to query:

  * **Windowed by default.** An all-time board freezes on whoever started
    first; a seven-day board resets every week and stays winnable. All-time is
    available, but weekly is the default view.
  * **Multiple boards, not one.** Ranking only by total XP crowns whoever has
    the most free time. Off-hand reps, consistency (streak), and improvement
    give a different athlete the top slot on each, which is the point.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from .config import CONFIG
from .scoring import compute_streak, level_for_xp

Window = Literal["week", "month", "season", "all"]
Board = Literal["xp", "offhand", "streak", "reps", "improvement", "quality"]


# Length of each window in days. `all` is unbounded, hence None -- which is
# also why "improvement over all time" has no meaningful previous window.
WINDOW_DAYS: dict[str, int | None] = {
    "week": 7,
    "month": 30,
    "season": 181,
    "all": None,
}


# Sessions required before an athlete is ranked on form. Without a floor, one
# tidy session beats a month of consistent work, which is the opposite of what
# the board is for.
QUALITY_MIN_SESSIONS = 3


def window_start(window: Window, today: date | None = None) -> str:
    """Inclusive start day (YYYY-MM-DD) for a leaderboard window."""
    today = today or datetime.now(timezone.utc).date()
    days = WINDOW_DAYS.get(window)
    if days is None:
        return "0001-01-01"
    return (today - timedelta(days=days - 1)).isoformat()


@dataclass
class LeaderRow:
    rank: int
    athlete_id: int
    display_name: str
    value: int
    level: int
    team_name: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "athlete_id": self.athlete_id,
            "display_name": self.display_name,
            "value": self.value,
            "level": self.level,
            "team_name": self.team_name,
            "detail": self.detail,
        }


def _display_name(row: sqlite3.Row) -> str:
    """Withhold a minor's name from shared boards without recorded consent.

    They still appear and still compete -- the ranking is not the problem, the
    identifiability is. An initial-and-jersey handle keeps the accountability
    the leaderboard exists for while keeping an unconsented minor's full name
    off a screen their teammates' parents can see.
    """
    birth_year = row["birth_year"]
    consented = row["guardian_consent_at"]
    name = row["display_name"]
    if birth_year is None or consented:
        return name

    age = datetime.now(timezone.utc).year - int(birth_year)
    if age > CONFIG.minor_age_ceiling:
        return name

    initial = name.strip()[:1].upper() or "?"
    jersey = row["jersey"] if "jersey" in row.keys() and row["jersey"] else None
    return f"{initial}. (#{jersey})" if jersey else f"Athlete {initial}."


def _scope_clause(team_id: int | None, org_id: int) -> tuple[str, list[Any]]:
    if team_id is not None:
        return (
            "JOIN team_members tm ON tm.user_id = u.id AND tm.team_id = ?",
            [team_id],
        )
    return ("LEFT JOIN team_members tm ON tm.user_id = u.id", [])


def leaderboard(
    conn: sqlite3.Connection,
    org_id: int,
    *,
    board: Board = "xp",
    window: Window = "week",
    team_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Rank athletes in a program (or one team) on the given board."""
    start = window_start(window)
    join, scope_params = _scope_clause(team_id, org_id)

    base_select = (
        "SELECT u.id AS athlete_id, u.display_name, u.birth_year, u.guardian_consent_at, "
        "u.dominant_hand, tm.jersey, "
        "COALESCE(t.name, 'Unassigned') AS team_name, "
    )
    base_from = (
        f"FROM users u {join} "
        "LEFT JOIN teams t ON t.id = tm.team_id "
        "WHERE u.org_id = ? AND u.role = 'athlete' AND u.active = 1 "
    )

    if board in ("xp", "streak"):
        sql = (
            base_select
            + "COALESCE((SELECT SUM(x.amount) FROM xp_ledger x "
            "  WHERE x.athlete_id = u.id AND x.day >= ?), 0) AS value "
            + base_from
        )
        params = [start, org_id, *scope_params]

    elif board == "reps":
        sql = (
            base_select
            + "COALESCE((SELECT SUM(s.reps_total) FROM sessions s "
            "  WHERE s.athlete_id = u.id AND s.status = 'counted' "
            "  AND date(s.submitted_at) >= ?), 0) AS value "
            + base_from
        )
        params = [start, org_id, *scope_params]

    elif board == "offhand":
        # Off-hand depends on the athlete's dominant hand, so the column is
        # chosen per row rather than fixed in the query.
        sql = (
            base_select
            + "COALESCE((SELECT SUM(CASE WHEN u.dominant_hand = 'left' "
            "    THEN s.reps_right ELSE s.reps_left END) "
            "  FROM sessions s WHERE s.athlete_id = u.id AND s.status = 'counted' "
            "  AND date(s.submitted_at) >= ?), 0) AS value "
            + base_from
        )
        params = [start, org_id, *scope_params]

    elif board == "quality":
        # Mean form score over the window, for athletes with enough sessions
        # to have earned a place on it.
        sql = (
            base_select
            + "COALESCE((SELECT CAST(ROUND(AVG(s.quality_score)) AS INTEGER) "
            "  FROM sessions s WHERE s.athlete_id = u.id AND s.status = 'counted' "
            "  AND s.quality_score IS NOT NULL "
            "  AND date(COALESCE(s.completed_at, s.submitted_at)) >= ? "
            "  HAVING COUNT(*) >= ?), 0) AS value "
            + base_from
        )
        params = [start, QUALITY_MIN_SESSIONS, org_id, *scope_params]

    elif board == "improvement":
        # This window's XP minus the previous equal-length window's. Rewards
        # the athlete who went from nothing to something, which is the one a
        # total-XP board never surfaces.
        span_days = WINDOW_DAYS.get(window)
        if span_days is None:
            # All-time has no earlier window to improve on. Subtracting an
            # empty range degrades this board to total XP rather than
            # overflowing off the start of the calendar.
            prev_start = start
        else:
            prev_start = (date.fromisoformat(start) - timedelta(days=span_days)).isoformat()
        sql = (
            base_select
            + "(COALESCE((SELECT SUM(x.amount) FROM xp_ledger x "
            "   WHERE x.athlete_id = u.id AND x.day >= ?), 0) "
            " - COALESCE((SELECT SUM(x.amount) FROM xp_ledger x "
            "   WHERE x.athlete_id = u.id AND x.day >= ? AND x.day < ?), 0)) AS value "
            + base_from
        )
        params = [start, prev_start, start, org_id, *scope_params]
    else:
        raise ValueError(f"unknown board: {board!r}")

    sql += " GROUP BY u.id ORDER BY value DESC, u.display_name ASC LIMIT ?"
    params.append(limit * 3 if board == "streak" else limit)

    rows = conn.execute(sql, params).fetchall()

    results: list[LeaderRow] = []
    for row in rows:
        total_xp = int(
            conn.execute(
                "SELECT COALESCE(SUM(amount),0) AS t FROM xp_ledger WHERE athlete_id=?",
                (row["athlete_id"],),
            ).fetchone()["t"]
        )
        value = int(row["value"])
        detail = ""

        if board == "streak":
            days = [
                date.fromisoformat(r["day"])
                for r in conn.execute(
                    "SELECT day FROM xp_ledger WHERE athlete_id=? GROUP BY day "
                    "HAVING SUM(amount) >= ? ORDER BY day",
                    (row["athlete_id"], CONFIG.scoring.streak_min_xp),
                )
            ]
            streak = compute_streak(days, datetime.now(timezone.utc).date())
            value = streak.current
            detail = "at risk today" if streak.at_risk else ""

        results.append(
            LeaderRow(
                rank=0,
                athlete_id=row["athlete_id"],
                display_name=_display_name(row),
                value=value,
                level=level_for_xp(total_xp),
                team_name=row["team_name"],
                detail=detail,
            )
        )

    if board == "streak":
        results.sort(key=lambda r: (-r.value, r.display_name))
        results = results[:limit]

    if board == "quality":
        # A zero here means "not enough sessions to rank", not "terrible form".
        # Showing it as a score would be both wrong and discouraging.
        results = [r for r in results if r.value > 0]

    # Competition ranking: equal values share a rank, and the next distinct
    # value skips accordingly (1,2,2,4).
    prev_value: int | None = None
    prev_rank = 0
    for i, r in enumerate(results, start=1):
        if prev_value is not None and r.value == prev_value:
            r.rank = prev_rank
        else:
            r.rank = i
            prev_rank = i
            prev_value = r.value

    return [r.to_dict() for r in results]


def team_standings(conn: sqlite3.Connection, org_id: int, window: Window = "week") -> list[dict[str, Any]]:
    """Team-vs-team board, ranked by XP *per active athlete*.

    Total XP would just rank teams by roster size. Per-athlete average is the
    number that actually says which team is putting in the work, and it gives a
    small squad a real shot at beating a big one.
    """
    start = window_start(window)
    rows = conn.execute(
        """
        SELECT t.id AS team_id, t.name AS team_name,
               COUNT(DISTINCT tm.user_id) AS roster,
               COUNT(DISTINCT CASE WHEN x.amount > 0 THEN x.athlete_id END) AS active,
               COALESCE(SUM(x.amount), 0) AS total_xp
        FROM teams t
        LEFT JOIN team_members tm ON tm.team_id = t.id
        LEFT JOIN users u ON u.id = tm.user_id AND u.role = 'athlete' AND u.active = 1
        LEFT JOIN xp_ledger x ON x.athlete_id = u.id AND x.day >= ?
        WHERE t.org_id = ?
        GROUP BY t.id
        """,
        (start, org_id),
    ).fetchall()

    standings = []
    for r in rows:
        roster = int(r["roster"])
        total = int(r["total_xp"])
        standings.append(
            {
                "team_id": r["team_id"],
                "team_name": r["team_name"],
                "roster": roster,
                "active": int(r["active"]),
                "total_xp": total,
                "xp_per_athlete": round(total / roster, 1) if roster else 0.0,
                "participation": round(int(r["active"]) / roster, 3) if roster else 0.0,
            }
        )
    standings.sort(key=lambda s: (-s["xp_per_athlete"], s["team_name"]))
    for i, s in enumerate(standings, start=1):
        s["rank"] = i
    return standings


def coach_roster(
    conn: sqlite3.Connection,
    org_id: int,
    team_id: int | None = None,
    window: Window = "week",
) -> list[dict[str, Any]]:
    """The coach's working view: who is training, who has gone quiet.

    Deliberately carries no video and no imagery -- only counts, recency, and
    balance. A coach should be able to run this in front of a parent.
    """
    start = window_start(window)
    join, scope_params = _scope_clause(team_id, org_id)

    rows = conn.execute(
        f"""
        SELECT u.id AS athlete_id, u.display_name, u.dominant_hand,
               u.birth_year, u.guardian_consent_at, tm.jersey, tm.position,
               COALESCE(t.name, 'Unassigned') AS team_name,
               COALESCE((SELECT SUM(x.amount) FROM xp_ledger x
                         WHERE x.athlete_id = u.id AND x.day >= ?), 0) AS window_xp,
               COALESCE((SELECT SUM(x.amount) FROM xp_ledger x
                         WHERE x.athlete_id = u.id), 0) AS total_xp,
               (SELECT COUNT(*) FROM sessions s
                WHERE s.athlete_id = u.id AND s.status = 'counted'
                AND date(s.submitted_at) >= ?) AS window_sessions,
               (SELECT MAX(s.submitted_at) FROM sessions s
                WHERE s.athlete_id = u.id AND s.status = 'counted') AS last_session,
               COALESCE((SELECT SUM(s.reps_left) FROM sessions s
                         WHERE s.athlete_id = u.id AND s.status='counted'
                         AND date(s.submitted_at) >= ?), 0) AS left_reps,
               COALESCE((SELECT SUM(s.reps_right) FROM sessions s
                         WHERE s.athlete_id = u.id AND s.status='counted'
                         AND date(s.submitted_at) >= ?), 0) AS right_reps,
               (SELECT COUNT(*) FROM sessions s
                WHERE s.athlete_id = u.id AND s.status = 'review') AS pending_review,
               (SELECT CAST(ROUND(AVG(s.quality_score)) AS INTEGER) FROM sessions s
                WHERE s.athlete_id = u.id AND s.status = 'counted'
                AND s.quality_score IS NOT NULL
                AND date(COALESCE(s.completed_at, s.submitted_at)) >= ?) AS quality
        FROM users u {join}
        LEFT JOIN teams t ON t.id = tm.team_id
        WHERE u.org_id = ? AND u.role = 'athlete' AND u.active = 1
        GROUP BY u.id
        ORDER BY window_xp DESC, u.display_name
        """,
        (start, start, start, start, start, org_id, *scope_params),
    ).fetchall()

    today = datetime.now(timezone.utc).date()
    out = []
    for r in rows:
        last = r["last_session"]
        days_since = None
        if last:
            try:
                days_since = (today - datetime.fromisoformat(last).date()).days
            except ValueError:
                days_since = None

        left, right = int(r["left_reps"]), int(r["right_reps"])
        sided = left + right
        offhand = left if (r["dominant_hand"] or "right") == "right" else right
        offhand_share = round(offhand / sided, 3) if sided else None

        out.append(
            {
                "athlete_id": r["athlete_id"],
                # The coach is entitled to the real name -- they are the
                # responsible adult. Only shared leaderboards get the handle.
                "display_name": r["display_name"],
                "jersey": r["jersey"],
                "position": r["position"],
                "team_name": r["team_name"],
                "dominant_hand": r["dominant_hand"],
                "window_xp": int(r["window_xp"]),
                "level": level_for_xp(int(r["total_xp"])),
                "window_sessions": int(r["window_sessions"]),
                "last_session": last,
                "days_since_session": days_since,
                "offhand_share": offhand_share,
                "quality": int(r["quality"]) if r["quality"] is not None else None,
                # Attached by `attach_load`; the roster query stays pure SQL.
                "load": None,
                "pending_review": int(r["pending_review"]),
                # Flags are what makes this actionable rather than another
                # table to read: they say who to text tonight.
                "flags": _flags(
                    int(r["window_sessions"]), days_since, offhand_share,
                    int(r["quality"]) if r["quality"] is not None else None,
                ),
            }
        )
    return out


def attach_load(
    athletes: list[dict[str, Any]], states: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fold workload into an already-built roster.

    Kept separate because load analysis needs a month of per-day history per
    athlete -- expressing that in the roster query would turn one readable
    statement into an unreadable one for no gain.
    """
    for athlete in athletes:
        state = states.get(athlete["athlete_id"])
        if not state:
            continue
        athlete["load"] = state
        if state.get("zone") == "high":
            athlete["flags"].append("load_spike")
        if state.get("rest_recommended"):
            athlete["flags"].append("needs_rest")
    return athletes


def _flags(
    window_sessions: int,
    days_since: int | None,
    offhand_share: float | None,
    quality: int | None = None,
) -> list[str]:
    flags: list[str] = []
    if days_since is None:
        flags.append("never_trained")
    elif days_since >= 10:
        flags.append("inactive_10d")
    elif days_since >= 5:
        flags.append("quiet_5d")
    if window_sessions == 0 and days_since is not None:
        flags.append("no_sessions_this_week")
    if offhand_share is not None and offhand_share < 0.20:
        flags.append("neglecting_offhand")
    # Volume without form is the pattern worth catching: an athlete grinding
    # out sloppy reps is banking fatigue rather than skill.
    if quality is not None and quality < 55 and window_sessions >= 2:
        flags.append("form_slipping")
    return flags
