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

WINDOW_DAYS: dict[str, int | None] = {
    "week": 7,
    "month": 30,
    "season": 181,
    "all": None,
}

QUALITY_MIN_SESSIONS = 3


def window_start(window: Window, today: date | None = None) -> str:
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


def _display_name(row: Any) -> str:
    """Per-program display: full name or initial+jersey for unconsented minors."""
    # row is a tuple: (athlete_id, display_name, birth_year, guardian_consent_at, dominant_hand, jersey, value, team_name)
    birth_year = row[2]
    consented = row[3]
    name = row[1]
    if birth_year is None or consented:
        return name
    age = datetime.now(timezone.utc).year - int(birth_year)
    if age > CONFIG.minor_age_ceiling:
        return name
    initial = name.strip()[:1].upper() or "?"
    jersey = row[5] if row[5] else None
    return f"{initial}. (#{jersey})" if jersey else f"Athlete {initial}."


def _sport_display_name(row: Any) -> str:
    """Sport-wide display: first_name + last_initial, no consent gating."""
    name = row[1].strip()
    parts = name.split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1][0].upper()}."
    return name


def _scope_clause(team_id: int | None, org_id: int) -> tuple[str, list[Any]]:
    if team_id is not None:
        return (
            "JOIN team_members tm ON tm.user_id = u.id AND tm.team_id = ?",
            [team_id],
        )
    return ("LEFT JOIN team_members tm ON tm.user_id = u.id", [])


def _build_leaderboard_query(
    board: Board,
    window: Window,
    sport_filter: str | None = None,
    org_id: int | None = None,
    team_id: int | None = None,
    age_group: str | None = None,
) -> tuple[str, list[Any]]:
    """Build the SQL query and params for a leaderboard.

    Returns (sql, params). The caller adds the GROUP BY, ORDER BY, and LIMIT.
    """
    start = window_start(window)
    if team_id is not None:
        join_clause = "JOIN team_members tm ON tm.user_id = u.id AND tm.team_id = ?"
        scope_params: list[Any] = [team_id]
    elif age_group is not None:
        # Every team sharing the cohort, which is the whole point: a parent
        # asking why their child is on one squad and not the other is asking
        # about a comparison that crosses the team boundary.
        join_clause = (
            "JOIN team_members tm ON tm.user_id = u.id "
            "JOIN teams tg ON tg.id = tm.team_id AND tg.age_group = ?"
        )
        scope_params = [age_group]
    else:
        join_clause = "LEFT JOIN team_members tm ON tm.user_id = u.id"
        scope_params = []

    # --- value subquery ---
    if board in ("xp", "streak"):
        value_sql = (
            "COALESCE((SELECT SUM(x.amount) FROM xp_ledger x "
            "  WHERE x.athlete_id = u.id AND x.day >= ?), 0) AS value"
        )
        value_params: list[Any] = [start]

    elif board == "reps":
        value_sql = (
            "COALESCE((SELECT SUM(s.reps_total) FROM sessions s "
            "  WHERE s.athlete_id = u.id AND s.status = 'counted' "
            "  AND s.self_reported = 0 "
            "  AND date(s.submitted_at) >= ?), 0) AS value"
        )
        value_params = [start]

    elif board == "offhand":
        value_sql = (
            "COALESCE((SELECT SUM(CASE WHEN u.dominant_hand = 'left' "
            "    THEN s.reps_right ELSE s.reps_left END) "
            "  FROM sessions s WHERE s.athlete_id = u.id AND s.status = 'counted' "
            "  AND date(s.submitted_at) >= ?), 0) AS value"
        )
        value_params = [start]

    elif board == "quality":
        value_sql = (
            "COALESCE((SELECT CAST(ROUND(AVG(s.quality_score)) AS INTEGER) "
            "  FROM sessions s WHERE s.athlete_id = u.id AND s.status = 'counted' "
            "  AND s.quality_score IS NOT NULL "
            "  AND date(COALESCE(s.completed_at, s.submitted_at)) >= ? "
            "  HAVING COUNT(*) >= ?), 0) AS value"
        )
        value_params = [start, QUALITY_MIN_SESSIONS]

    elif board == "improvement":
        span_days = WINDOW_DAYS.get(window)
        if span_days is None:
            prev_start = start
        else:
            prev_start = (date.fromisoformat(start) - timedelta(days=span_days)).isoformat()
        value_sql = (
            "(COALESCE((SELECT SUM(x.amount) FROM xp_ledger x "
            "   WHERE x.athlete_id = u.id AND x.day >= ?), 0) "
            " - COALESCE((SELECT SUM(x.amount) FROM xp_ledger x "
            "   WHERE x.athlete_id = u.id AND x.day >= ? AND x.day < ?), 0)) AS value"
        )
        value_params = [start, prev_start, start]

    else:
        raise ValueError(f"unknown board: {board!r}")

    # --- WHERE clause ---
    if sport_filter is not None:
        where_clause = (
            "WHERE u.role = 'athlete' AND u.active = 1 "
            "AND u.id IN (SELECT athlete_id FROM athlete_sports WHERE sport = ?)"
        )
        where_params: list[Any] = [sport_filter]
    else:
        where_clause = "WHERE u.org_id = ? AND u.role = 'athlete' AND u.active = 1"
        where_params = [org_id]

    # --- build full SQL ---
    if board == "quality":
        sql = (
            "SELECT u.id AS athlete_id, u.display_name, u.birth_year, "
            "u.guardian_consent_at, u.dominant_hand, tm.jersey, "
            + value_sql + ", "
            "COALESCE(t.name, 'Unassigned') AS team_name "
            "FROM users u " + join_clause + " "
            "LEFT JOIN teams t ON t.id = tm.team_id "
            + where_clause
        )
        params = scope_params + value_params + where_params
    else:
        sql = (
            "SELECT u.id AS athlete_id, u.display_name, u.birth_year, "
            "u.guardian_consent_at, u.dominant_hand, tm.jersey, "
            + value_sql + ", "
            "COALESCE(t.name, 'Unassigned') AS team_name "
            "FROM users u " + join_clause + " "
            "LEFT JOIN teams t ON t.id = tm.team_id "
            + where_clause
        )
        params = value_params + scope_params + where_params

    return sql, params


def _fetch_leader_rows(
    conn: sqlite3.Connection,
    rows: list[Any],
    board: Board,
    limit: int | None,
    display_fn,
) -> list[dict[str, Any]]:
    """Convert raw SQL rows to leaderboard dicts.

    Rows are tuples: (athlete_id, display_name, birth_year, guardian_consent_at,
                      dominant_hand, jersey, value, team_name)
    """
    results: list[LeaderRow] = []
    for row in rows:
        athlete_id = row[0]
        value = int(row[6])
        team_name = row[7]

        total_xp = int(
            conn.execute(
                "SELECT COALESCE(SUM(amount),0) AS t FROM xp_ledger WHERE athlete_id=?",
                (athlete_id,),
            ).fetchone()[0]
        )

        detail = ""
        if board == "streak":
            day_rows = conn.execute(
                "SELECT day FROM xp_ledger WHERE athlete_id=? GROUP BY day "
                "HAVING SUM(amount) >= ? ORDER BY day",
                (athlete_id, CONFIG.scoring.streak_min_xp),
            ).fetchall()
            days = [date.fromisoformat(r[0]) for r in day_rows]
            streak = compute_streak(days, datetime.now(timezone.utc).date())
            value = streak.current
            detail = "at risk today" if streak.at_risk else ""

        results.append(
            LeaderRow(
                rank=0,
                athlete_id=athlete_id,
                display_name=display_fn(row),
                value=value,
                level=level_for_xp(total_xp),
                team_name=team_name,
                detail=detail,
            )
        )

    if board == "streak":
        results.sort(key=lambda r: (-r.value, r.display_name))
        if limit is not None:
            results = results[:limit]

    if board == "quality":
        results = [r for r in results if r.value > 0]

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
    sql, params = _build_leaderboard_query(board, window, org_id=org_id, team_id=team_id)
    sql += " GROUP BY u.id ORDER BY value DESC, u.display_name ASC LIMIT ?"
    params.append(limit * 3 if board == "streak" else limit)
    rows = conn.execute(sql, params).fetchall()
    return _fetch_leader_rows(conn, rows, board, limit, _display_name)


def age_group_of(conn: sqlite3.Connection, athlete_id: int) -> str | None:
    """The cohort an athlete's team sits in, or None if it has no cohort set."""
    row = conn.execute(
        "SELECT t.age_group FROM team_members tm JOIN teams t ON t.id = tm.team_id "
        "WHERE tm.user_id = ? AND t.age_group <> '' LIMIT 1",
        (athlete_id,),
    ).fetchone()
    return row[0] if row else None


def age_group_teams(conn: sqlite3.Connection, org_id: int, age_group: str) -> list[str]:
    """Team names sharing a cohort, so a caller can say who is being compared."""
    rows = conn.execute(
        "SELECT name FROM teams WHERE org_id = ? AND age_group = ? ORDER BY name",
        (org_id, age_group),
    ).fetchall()
    return [r[0] for r in rows]


def leaderboard_age_group(
    conn: sqlite3.Connection,
    org_id: int,
    age_group: str,
    *,
    board: Board = "xp",
    window: Window = "week",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Rank one birth-year cohort across every team it is split into.

    A club that splits a cohort by ability creates the question this board
    answers: a parent on the second squad wants to know what the first squad
    is doing that their child is not. A team-only board cannot answer it,
    because the people they are being measured against are not on it.

    The same consent gate applies as anywhere else -- a child whose guardian
    has not agreed to their name appearing shows as an initial. The board is
    still legible that way, because the parent reading it is looking for where
    their own child sits, and their own child they can always identify.

    `limit` defaults to no limit, because a cut-off here would answer the
    parent's question wrongly. The join already bounds this to one birth year
    at one club, and the rows a cut-off would drop are the low ones -- the
    children who did the least. A parent asking why their child is on the
    second squad needs to see the bottom of this list as much as the top, and
    a child who trained little should not be hidden by their own inactivity.
    """
    sql, params = _build_leaderboard_query(
        board, window, org_id=org_id, age_group=age_group
    )
    sql += " GROUP BY u.id ORDER BY value DESC, u.display_name ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit * 3 if board == "streak" else limit)
    rows = conn.execute(sql, params).fetchall()
    # The streak board re-sorts in Python and slices to `limit`; None there
    # means the same thing it means here.
    return _fetch_leader_rows(conn, rows, board, limit, _display_name)


def leaderboard_sport_wide(
    conn: sqlite3.Connection,
    sport: str,
    *,
    board: Board = "xp",
    window: Window = "week",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Rank athletes across every program for one sport.

    Used by the sport= query param on /api/leaderboard. Filtering is by sport
    rather than org_id, and display names use first_name + last_initial.
    """
    sql, params = _build_leaderboard_query(board, window, sport_filter=sport)
    sql += " GROUP BY u.id ORDER BY value DESC, u.display_name ASC LIMIT ?"
    params.append(limit * 3 if board == "streak" else limit)
    rows = conn.execute(sql, params).fetchall()
    return _fetch_leader_rows(conn, rows, board, limit, _sport_display_name)


def team_standings(conn: sqlite3.Connection, org_id: int, window: Window = "week") -> list[dict[str, Any]]:
    """Team-vs-team board, ranked by XP *per active athlete*."""
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
        standings.append({
            "team_id": r["team_id"],
            "team_name": r["team_name"],
            "roster": roster,
            "active": int(r["active"]),
            "total_xp": total,
            "xp_per_athlete": round(total / roster, 1) if roster else 0.0,
            "participation": round(int(r["active"]) / roster, 3) if roster else 0.0,
        })
    standings.sort(key=lambda s: (-s["xp_per_athlete"], s["team_name"]))
    for i, s in enumerate(standings, start=1):
        s["rank"] = i
    return standings


def coach_roster(
    conn: sqlite3.Connection,
    org_id: int,
    team_id: int | None = None,
    window: Window = "week",
    scope: tuple[str, list[Any]] | None = None,
) -> list[dict[str, Any]]:
    """The coach's working view: who is training, who has gone quiet."""
    start = window_start(window)
    join, scope_params = _scope_clause(team_id, org_id)
    scope_sql, staff_scope_params = scope or ("", [])

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
        {scope_sql}
        GROUP BY u.id
        ORDER BY window_xp DESC, u.display_name
        """,
        (start, start, start, start, start, org_id, *scope_params, *staff_scope_params),
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
        # The exact complement: both halves come from the same denominator, so
        # reps the camera could not attribute to a side are left out of both
        # rather than quietly inflating one of them.
        strong_share = (round(1 - offhand_share, 3)
                        if offhand_share is not None else None)

        out.append({
            "athlete_id": r["athlete_id"],
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
            "strong_share": strong_share,
            "quality": int(r["quality"]) if r["quality"] is not None else None,
            "load": None,
            "pending_review": int(r["pending_review"]),
            "flags": _flags(
                int(r["window_sessions"]), days_since, offhand_share,
                int(r["quality"]) if r["quality"] is not None else None,
            ),
        })
    return out


def attach_load(
    athletes: list[dict[str, Any]], states: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fold workload into an already-built roster."""
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
    if quality is not None and quality < 55 and window_sessions >= 2:
        flags.append("form_slipping")
    return flags
