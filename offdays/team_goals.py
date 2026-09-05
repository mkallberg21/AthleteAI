"""A number a squad chases together.

Every other board in this product ranks individuals. The household board
already demonstrates the better pattern for a group that should not be ranked
-- one shared number, chased collaboratively -- and the weekly digest already
leads on participation for the same reason: it is the only metric here whose
marginal contributor is the athlete you actually want to reach.

This brings that into the app, and the shape is the whole design.

**Contribution is binary and capped.** A goal is a count of *athletes* who
each clear a small personal bar -- three days, say -- inside a window. The
committed athlete doing six sessions contributes exactly what the quiet one
doing three does. The only way the number moves is somebody new turning up.

A goal denominated in reps or XP would do the precise opposite. It would let
one athlete carry the squad, which teaches everyone else they are not needed,
and it would make the quiet athlete visibly the shortfall -- a worse object
than the leaderboard it replaced, because a leaderboard at least does not
frame a child as the reason their team failed.

**Nobody is ever named.** Not who is in, not who is not, not a count of who is
not. An athlete sees their own status and the squad total; a coach sees the
squad total. The names a coach needs for a nudge are already on their roster
behind a login, where they are a working tool rather than a broadcast.

**An athlete who cannot train is out of the denominator**, not counted as
missing. Someone on a hold or mid return-to-play is not a shortfall, and a
goal that treats them as one is asking their squad to want them back before
they are ready.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any


class GoalError(Exception):
    pass


#: A bar higher than this stops being "a small personal bar" and starts being
#: a volume target with extra steps.
MAX_PER_ATHLETE_DAYS = 6
MAX_PER_ATHLETE_SESSIONS = 14

#: Windows shorter than this cannot be chased and longer than this cannot be
#: felt. A fortnight is the outer edge of a thing a squad remembers.
MIN_DAYS = 3
MAX_DAYS = 28


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Goal:
    id: int
    org_id: int
    team_id: int
    title: str
    target_athletes: int
    per_athlete_days: int
    per_athlete_sessions: int
    starts_on: str
    ends_on: str
    active: bool = True

    #: Filled by `progress`. Counts only -- never a list of people.
    counted: int = 0
    eligible: int = 0
    excused: int = 0

    @property
    def met(self) -> bool:
        return self.counted >= self.target_athletes

    @property
    def fraction(self) -> float:
        return min(1.0, self.counted / self.target_athletes) if self.target_athletes else 0.0

    def bar_text(self) -> str:
        """The personal bar, in the words an athlete would use."""
        parts = []
        if self.per_athlete_days:
            parts.append(
                f"{self.per_athlete_days} day{'' if self.per_athlete_days == 1 else 's'}")
        if self.per_athlete_sessions:
            parts.append(
                f"{self.per_athlete_sessions} session"
                f"{'' if self.per_athlete_sessions == 1 else 's'}")
        return " and ".join(parts) or "a session"

    def headline(self) -> str:
        """What the squad reads. Never a shortfall, never a name.

        A goal that is not going to be met says how far the squad got, because
        "we got 14 of 20" is a fact a team can do something with and "6 people
        let us down" is not a fact at all -- it is an accusation with a number
        attached.
        """
        if self.met:
            return f"Done. {self.counted} of you got there."
        if self.counted == 0:
            return f"Nobody has got there yet. {self.bar_text()} puts you in."
        return f"{self.counted} of {self.target_athletes} so far."

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "title": self.title,
            "target_athletes": self.target_athletes,
            "per_athlete_days": self.per_athlete_days,
            "per_athlete_sessions": self.per_athlete_sessions,
            "starts_on": self.starts_on,
            "ends_on": self.ends_on,
            "active": self.active,
            "counted": self.counted,
            "eligible": self.eligible,
            "excused": self.excused,
            "target_met": self.met,
            "fraction": round(self.fraction, 3),
            "bar": self.bar_text(),
            "headline": self.headline(),
        }


def _row_to_goal(row: sqlite3.Row) -> Goal:
    return Goal(
        id=int(row["id"]), org_id=int(row["org_id"]), team_id=int(row["team_id"]),
        title=row["title"], target_athletes=int(row["target_athletes"]),
        per_athlete_days=int(row["per_athlete_days"]),
        per_athlete_sessions=int(row["per_athlete_sessions"]),
        starts_on=row["starts_on"], ends_on=row["ends_on"],
        active=bool(row["active"]),
    )


def create(
    conn: sqlite3.Connection,
    *,
    org_id: int,
    team_id: int,
    created_by: int,
    title: str,
    target_athletes: int,
    starts_on: str,
    ends_on: str,
    per_athlete_days: int = 0,
    per_athlete_sessions: int = 0,
) -> int:
    """Set a goal, validating it is the kind of goal this is meant to be."""
    try:
        start = date.fromisoformat(starts_on)
        end = date.fromisoformat(ends_on)
    except ValueError as exc:
        raise GoalError(f"dates must be YYYY-MM-DD: {exc}") from None
    if end < start:
        raise GoalError("a goal cannot end before it starts")
    span = (end - start).days + 1
    if not MIN_DAYS <= span <= MAX_DAYS:
        raise GoalError(
            f"a goal window has to be between {MIN_DAYS} and {MAX_DAYS} days"
        )

    if not per_athlete_days and not per_athlete_sessions:
        raise GoalError("set a personal bar: days trained, sessions, or both")
    if per_athlete_days > MAX_PER_ATHLETE_DAYS:
        raise GoalError(
            f"{per_athlete_days} days is more of a volume target than a bar to "
            f"clear. {MAX_PER_ATHLETE_DAYS} is the most this will take"
        )
    if per_athlete_sessions > MAX_PER_ATHLETE_SESSIONS:
        raise GoalError(
            f"{per_athlete_sessions} sessions is more of a volume target than a "
            f"bar to clear. {MAX_PER_ATHLETE_SESSIONS} is the most this will take"
        )
    if per_athlete_days > span:
        raise GoalError(
            f"{per_athlete_days} days cannot be trained inside a {span}-day window"
        )
    if target_athletes < 1:
        raise GoalError("a goal needs at least one athlete in it")

    # The team has to be this program's. `can_see_team` at the edge governs
    # which of *their own* teams a coach may touch and says nothing about
    # another program's, so without this a director could set goals on a
    # stranger's squad.
    if conn.execute(
        "SELECT 1 FROM teams WHERE id = ? AND org_id = ?", (team_id, org_id)
    ).fetchone() is None:
        raise GoalError("no such team in this program")

    roster = conn.execute(
        "SELECT COUNT(*) AS n FROM team_members tm JOIN users u ON u.id = tm.user_id "
        "WHERE tm.team_id = ? AND u.role = 'athlete' AND u.active = 1",
        (team_id,),
    ).fetchone()["n"]
    if roster and target_athletes > roster:
        raise GoalError(
            f"there are only {roster} athletes on this team, so {target_athletes} "
            "cannot get there"
        )

    cur = conn.execute(
        "INSERT INTO team_goals(org_id, team_id, created_by, title, "
        "  target_athletes, per_athlete_days, per_athlete_sessions, "
        "  starts_on, ends_on, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (org_id, team_id, created_by, title.strip() or "Team goal",
         target_athletes, per_athlete_days, per_athlete_sessions,
         starts_on, ends_on, _now().isoformat()),
    )
    conn.commit()
    return int(cur.lastrowid)


def _excused(conn: sqlite3.Connection, athlete_id: int, today: date) -> bool:
    """Whether this athlete is being asked not to train right now.

    Same rule as the pre-practice card. Someone on a hold or mid-ramp is not a
    shortfall, and counting them as one asks their squad to want them back
    before they are ready.
    """
    from . import wellness as wellness_mod

    row = conn.execute(
        "SELECT 1 FROM return_plans WHERE athlete_id = ? AND completed_on IS NULL "
        "AND date(stage_started_on) >= ?",
        (athlete_id, (today - timedelta(days=60)).isoformat()),
    ).fetchone()
    if row is not None:
        return True

    stale = (today - timedelta(days=wellness_mod.STALE_AFTER_DAYS)).isoformat()
    open_reports = conn.execute(
        "SELECT severity FROM discomfort_reports WHERE athlete_id = ? "
        "AND resolved_on IS NULL AND reported_on >= ?",
        (athlete_id, stale),
    ).fetchall()
    return any(
        r["severity"] in (wellness_mod.Severity.HURTS, wellness_mod.Severity.SORE)
        for r in open_reports
    )


def progress(conn: sqlite3.Connection, goal: Goal, today: date | None = None) -> Goal:
    """Fill in the counts. Counts only -- this never returns who.

    Returning names would make every caller a place the rule could be broken,
    and the rule is the feature.
    """
    today = today or _now().date()
    end = min(today.isoformat(), goal.ends_on)

    rows = conn.execute(
        "SELECT u.id AS athlete_id, "
        "  COUNT(DISTINCT date(s.submitted_at)) AS days, "
        "  COUNT(s.id) AS sessions "
        "FROM team_members tm "
        "JOIN users u ON u.id = tm.user_id "
        "LEFT JOIN sessions s ON s.athlete_id = u.id AND s.status = 'counted' "
        "  AND date(s.submitted_at) BETWEEN ? AND ? "
        "WHERE tm.team_id = ? AND u.role = 'athlete' AND u.active = 1 "
        "GROUP BY u.id",
        (goal.starts_on, end, goal.team_id),
    ).fetchall()

    counted = eligible = excused = 0
    for row in rows:
        if _excused(conn, int(row["athlete_id"]), today):
            excused += 1
            continue
        eligible += 1
        if (int(row["days"]) >= goal.per_athlete_days
                and int(row["sessions"]) >= goal.per_athlete_sessions):
            counted += 1

    goal.counted, goal.eligible, goal.excused = counted, eligible, excused
    return goal


def get(conn: sqlite3.Connection, goal_id: int, today: date | None = None) -> Goal | None:
    row = conn.execute("SELECT * FROM team_goals WHERE id = ?", (goal_id,)).fetchone()
    return progress(conn, _row_to_goal(row), today) if row else None


def for_team(
    conn: sqlite3.Connection,
    team_id: int,
    today: date | None = None,
    include_finished: bool = False,
) -> list[Goal]:
    today = today or _now().date()
    sql = "SELECT * FROM team_goals WHERE team_id = ? AND active = 1"
    params: list[Any] = [team_id]
    if not include_finished:
        sql += " AND ends_on >= ?"
        params.append(today.isoformat())
    sql += " ORDER BY ends_on ASC"
    return [progress(conn, _row_to_goal(r), today) for r in conn.execute(sql, params)]


def for_org(
    conn: sqlite3.Connection, org_id: int, today: date | None = None
) -> list[Goal]:
    today = today or _now().date()
    return [
        progress(conn, _row_to_goal(r), today)
        for r in conn.execute(
            "SELECT * FROM team_goals WHERE org_id = ? AND active = 1 "
            "AND ends_on >= ? ORDER BY ends_on ASC",
            (org_id, today.isoformat()),
        )
    ]


def close(conn: sqlite3.Connection, goal_id: int) -> None:
    conn.execute("UPDATE team_goals SET active = 0 WHERE id = ?", (goal_id,))
    conn.commit()


@dataclass
class MyStanding:
    """One athlete's own view of a goal. Theirs only -- never a teammate's."""

    goal: Goal
    days: int = 0
    sessions: int = 0
    counted: bool = False
    excused: bool = False

    def note(self) -> str:
        """What this athlete reads.

        The near-miss case is the one that matters: "one more day and you are
        in" is a small, achievable, non-judgemental ask, and it is aimed at
        exactly the athlete a participation goal exists to reach.
        """
        if self.excused:
            return (
                "You are resting, so you are not counted either way. The squad "
                "goal is not waiting on you."
            )
        if self.counted:
            return "You are in. Anything else this week is for you, not the count."

        needed_days = max(0, self.goal.per_athlete_days - self.days)
        needed_sessions = max(0, self.goal.per_athlete_sessions - self.sessions)
        if needed_days == 1 and needed_sessions <= 1:
            return "One more day and you are in."
        parts = []
        if needed_days:
            parts.append(f"{needed_days} more day{'' if needed_days == 1 else 's'}")
        if needed_sessions:
            parts.append(
                f"{needed_sessions} more session{'' if needed_sessions == 1 else 's'}")
        return f"{' and '.join(parts)} and you are in." if parts else "You are in."

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.goal.to_dict(),
            "my_days": self.days,
            "my_sessions": self.sessions,
            "i_count": self.counted,
            "i_am_excused": self.excused,
            "my_note": self.note(),
        }


def standing(
    conn: sqlite3.Connection, goal: Goal, athlete_id: int, today: date | None = None
) -> MyStanding:
    today = today or _now().date()
    end = min(today.isoformat(), goal.ends_on)
    row = conn.execute(
        "SELECT COUNT(DISTINCT date(submitted_at)) AS days, COUNT(*) AS sessions "
        "FROM sessions WHERE athlete_id = ? AND status = 'counted' "
        "AND date(submitted_at) BETWEEN ? AND ?",
        (athlete_id, goal.starts_on, end),
    ).fetchone()

    mine = MyStanding(
        goal=goal, days=int(row["days"]), sessions=int(row["sessions"]),
        excused=_excused(conn, athlete_id, today),
    )
    mine.counted = (
        not mine.excused
        and mine.days >= goal.per_athlete_days
        and mine.sessions >= goal.per_athlete_sessions
    )
    return mine


def for_athlete(
    conn: sqlite3.Connection, athlete_id: int, today: date | None = None
) -> list[MyStanding]:
    """Live goals for every team this athlete is on."""
    today = today or _now().date()
    rows = conn.execute(
        "SELECT g.* FROM team_goals g "
        "JOIN team_members tm ON tm.team_id = g.team_id "
        "WHERE tm.user_id = ? AND g.active = 1 AND g.ends_on >= ? "
        "AND g.starts_on <= ? ORDER BY g.ends_on ASC",
        (athlete_id, today.isoformat(), today.isoformat()),
    ).fetchall()
    return [
        standing(conn, progress(conn, _row_to_goal(r), today), athlete_id, today)
        for r in rows
    ]
