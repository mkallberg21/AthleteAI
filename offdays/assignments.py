"""Coach-assigned work and compliance tracking.

This is what separates a program from a logbook. An athlete left to their own
devices trains what they enjoy, which is their strong hand; an assignment is a
stated expectation, and the dashboard shows who met it.

Compliance is *derived*, never stored. A session counted toward an assignment
is simply one that matches the drill and falls inside the window, so a session
that is later rejected or approved in review automatically stops or starts
counting. Storing progress would mean two sources of truth that drift.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from .drills import DRILLS_BY_KEY


class AssignmentError(Exception):
    """An assignment that cannot be created as specified."""


@dataclass
class Progress:
    """One athlete's standing against one assignment."""

    athlete_id: int
    display_name: str
    sessions_done: int = 0
    reps_done: int = 0
    offhand_reps: int = 0
    offhand_share: float | None = None
    last_session: str | None = None

    # Per-target completion. A target of 0 means "not required", and an
    # unrequired target is trivially met.
    reps_met: bool = False
    sessions_met: bool = False
    offhand_met: bool = False

    @property
    def complete(self) -> bool:
        return self.reps_met and self.sessions_met and self.offhand_met

    def to_dict(self) -> dict[str, Any]:
        return {
            "athlete_id": self.athlete_id,
            "display_name": self.display_name,
            "sessions_done": self.sessions_done,
            "reps_done": self.reps_done,
            "offhand_reps": self.offhand_reps,
            "offhand_share": self.offhand_share,
            "last_session": self.last_session,
            "reps_met": self.reps_met,
            "sessions_met": self.sessions_met,
            "offhand_met": self.offhand_met,
            "complete": self.complete,
        }


@dataclass
class Assignment:
    id: int
    team_id: int
    team_name: str
    drill_key: str
    drill_name: str
    title: str
    notes: str
    target_reps: int
    target_sessions: int
    min_offhand: float
    starts_on: str
    due_on: str
    active: bool
    athlete_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "team_name": self.team_name,
            "drill_key": self.drill_key,
            "drill_name": self.drill_name,
            "title": self.title,
            "notes": self.notes,
            "target_reps": self.target_reps,
            "target_sessions": self.target_sessions,
            "min_offhand": self.min_offhand,
            "starts_on": self.starts_on,
            "due_on": self.due_on,
            "active": self.active,
            "scoped_to_athletes": bool(self.athlete_ids),
        }

    def days_remaining(self, today: date | None = None) -> int:
        today = today or datetime.now(timezone.utc).date()
        return (date.fromisoformat(self.due_on) - today).days

    def is_open(self, today: date | None = None) -> bool:
        today = today or datetime.now(timezone.utc).date()
        return (
            self.active
            and date.fromisoformat(self.starts_on) <= today <= date.fromisoformat(self.due_on)
        )


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create(
    conn: sqlite3.Connection,
    *,
    org_id: int,
    team_id: int,
    created_by: int,
    drill_key: str,
    title: str,
    starts_on: str,
    due_on: str,
    target_reps: int = 0,
    target_sessions: int = 0,
    min_offhand: float = 0.0,
    notes: str = "",
    athlete_ids: list[int] | None = None,
) -> int:
    """Create an assignment, validating it is actually achievable."""
    if drill_key not in DRILLS_BY_KEY:
        raise AssignmentError(f"unknown drill: {drill_key!r}")

    try:
        start = date.fromisoformat(starts_on)
        due = date.fromisoformat(due_on)
    except ValueError as exc:
        raise AssignmentError(f"dates must be YYYY-MM-DD: {exc}") from None
    if due < start:
        raise AssignmentError("due date falls before the start date")

    if target_reps < 0 or target_sessions < 0:
        raise AssignmentError("targets cannot be negative")
    if not 0.0 <= min_offhand <= 1.0:
        raise AssignmentError("min_offhand must be between 0 and 1")
    if target_reps == 0 and target_sessions == 0 and min_offhand == 0.0:
        raise AssignmentError(
            "an assignment needs at least one target (reps, sessions, or off-hand share)"
        )

    drill = DRILLS_BY_KEY[drill_key]
    if min_offhand > 0 and not drill.tracks_handedness:
        raise AssignmentError(
            f"{drill.name} does not track handedness, so an off-hand target is meaningless"
        )

    team = conn.execute(
        "SELECT org_id FROM teams WHERE id = ?", (team_id,)
    ).fetchone()
    if team is None:
        raise AssignmentError("unknown team")
    if team["org_id"] != org_id:
        raise AssignmentError("that team belongs to a different program")

    cur = conn.execute(
        "INSERT INTO assignments(org_id, team_id, created_by, drill_key, title, notes, "
        "target_reps, target_sessions, min_offhand, starts_on, due_on, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            org_id, team_id, created_by, drill_key, title, notes,
            target_reps, target_sessions, min_offhand, starts_on, due_on, _iso_now(),
        ),
    )
    assignment_id = int(cur.lastrowid)

    for athlete_id in athlete_ids or []:
        conn.execute(
            "INSERT OR IGNORE INTO assignment_athletes(assignment_id, athlete_id) VALUES (?,?)",
            (assignment_id, athlete_id),
        )
    conn.commit()
    return assignment_id


def _row_to_assignment(row: sqlite3.Row, athlete_ids: list[int]) -> Assignment:
    drill = DRILLS_BY_KEY.get(row["drill_key"])
    return Assignment(
        id=row["id"],
        team_id=row["team_id"],
        team_name=row["team_name"] if "team_name" in row.keys() else "",
        drill_key=row["drill_key"],
        drill_name=drill.name if drill else row["drill_key"],
        title=row["title"],
        notes=row["notes"],
        target_reps=row["target_reps"],
        target_sessions=row["target_sessions"],
        min_offhand=row["min_offhand"],
        starts_on=row["starts_on"],
        due_on=row["due_on"],
        active=bool(row["active"]),
        athlete_ids=athlete_ids,
    )


def _athlete_ids(conn: sqlite3.Connection, assignment_id: int) -> list[int]:
    return [
        r["athlete_id"]
        for r in conn.execute(
            "SELECT athlete_id FROM assignment_athletes WHERE assignment_id = ?",
            (assignment_id,),
        )
    ]


def get(conn: sqlite3.Connection, assignment_id: int) -> Assignment | None:
    row = conn.execute(
        "SELECT a.*, t.name AS team_name FROM assignments a "
        "JOIN teams t ON t.id = a.team_id WHERE a.id = ?",
        (assignment_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_assignment(row, _athlete_ids(conn, assignment_id))


def list_for_org(
    conn: sqlite3.Connection,
    org_id: int,
    *,
    team_id: int | None = None,
    include_inactive: bool = False,
) -> list[Assignment]:
    sql = (
        "SELECT a.*, t.name AS team_name FROM assignments a "
        "JOIN teams t ON t.id = a.team_id WHERE a.org_id = ?"
    )
    params: list[Any] = [org_id]
    if team_id is not None:
        sql += " AND a.team_id = ?"
        params.append(team_id)
    if not include_inactive:
        sql += " AND a.active = 1"
    sql += " ORDER BY a.due_on ASC, a.id DESC"
    return [
        _row_to_assignment(r, _athlete_ids(conn, r["id"]))
        for r in conn.execute(sql, params)
    ]


def roster_for(conn: sqlite3.Connection, assignment: Assignment) -> list[sqlite3.Row]:
    """The athletes an assignment applies to."""
    if assignment.athlete_ids:
        placeholders = ",".join("?" for _ in assignment.athlete_ids)
        return conn.execute(
            f"SELECT id, display_name, dominant_hand FROM users "
            f"WHERE id IN ({placeholders}) AND active = 1",
            assignment.athlete_ids,
        ).fetchall()
    return conn.execute(
        "SELECT u.id, u.display_name, u.dominant_hand FROM users u "
        "JOIN team_members tm ON tm.user_id = u.id "
        "WHERE tm.team_id = ? AND u.role = 'athlete' AND u.active = 1 "
        "ORDER BY u.display_name",
        (assignment.team_id,),
    ).fetchall()


def progress_for_athlete(
    conn: sqlite3.Connection,
    assignment: Assignment,
    athlete_id: int,
    display_name: str = "",
    dominant_hand: str | None = None,
) -> Progress:
    """Compute one athlete's standing, derived entirely from counted sessions.

    Only sessions whose *effective* completion date falls inside the window
    count. That date prefers the device-reported completion time so a session
    trained on the last day of the window but synced afterward still counts.
    """
    hand = dominant_hand or "right"
    offhand_col = "reps_left" if hand == "right" else "reps_right"

    row = conn.execute(
        f"""
        SELECT COUNT(*) AS n,
               COALESCE(SUM(reps_total), 0) AS reps,
               COALESCE(SUM({offhand_col}), 0) AS offhand,
               COALESCE(SUM(reps_left + reps_right), 0) AS sided,
               MAX(COALESCE(completed_at, submitted_at)) AS last
        FROM sessions
        WHERE athlete_id = ?
          AND drill_key = ?
          AND status = 'counted'
          AND date(COALESCE(completed_at, submitted_at)) BETWEEN ? AND ?
        """,
        (athlete_id, assignment.drill_key, assignment.starts_on, assignment.due_on),
    ).fetchone()

    sided = int(row["sided"])
    offhand = int(row["offhand"])
    share = (offhand / sided) if sided else None

    progress = Progress(
        athlete_id=athlete_id,
        display_name=display_name,
        sessions_done=int(row["n"]),
        reps_done=int(row["reps"]),
        offhand_reps=offhand,
        offhand_share=round(share, 3) if share is not None else None,
        last_session=row["last"],
    )
    # A target of zero is not a requirement, so it is met by definition.
    progress.reps_met = progress.reps_done >= assignment.target_reps
    progress.sessions_met = progress.sessions_done >= assignment.target_sessions
    progress.offhand_met = (
        assignment.min_offhand <= 0.0
        or (share is not None and share >= assignment.min_offhand)
    )
    return progress


def compliance(conn: sqlite3.Connection, assignment: Assignment) -> list[Progress]:
    """Every applicable athlete's standing, worst first.

    Worst-first because the coach opens this to find who needs a nudge, not to
    admire whoever already finished.
    """
    rows = roster_for(conn, assignment)
    out = [
        progress_for_athlete(
            conn, assignment, r["id"], r["display_name"], r["dominant_hand"]
        )
        for r in rows
    ]
    out.sort(key=lambda p: (p.complete, p.reps_done, p.sessions_done))
    return out


def for_athlete(
    conn: sqlite3.Connection,
    athlete_id: int,
    *,
    only_open: bool = True,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Assignments applying to one athlete, each with their own progress.

    This drives the athlete's home screen, so it leads with what was asked of
    them rather than a drill picker.
    """
    today = today or datetime.now(timezone.utc).date()
    user = conn.execute(
        "SELECT dominant_hand FROM users WHERE id = ?", (athlete_id,)
    ).fetchone()
    hand = user["dominant_hand"] if user else None

    rows = conn.execute(
        """
        SELECT a.*, t.name AS team_name
        FROM assignments a
        JOIN teams t ON t.id = a.team_id
        JOIN team_members tm ON tm.team_id = a.team_id AND tm.user_id = ?
        WHERE a.active = 1
        ORDER BY a.due_on ASC
        """,
        (athlete_id,),
    ).fetchall()

    out = []
    for row in rows:
        assignment = _row_to_assignment(row, _athlete_ids(conn, row["id"]))
        # A scoped assignment only applies to the athletes named on it.
        if assignment.athlete_ids and athlete_id not in assignment.athlete_ids:
            continue
        if only_open and not assignment.is_open(today):
            continue
        progress = progress_for_athlete(conn, assignment, athlete_id, dominant_hand=hand)
        out.append(
            {
                **assignment.to_dict(),
                "days_remaining": assignment.days_remaining(today),
                "progress": progress.to_dict(),
            }
        )
    return out


def deactivate(conn: sqlite3.Connection, assignment_id: int) -> None:
    conn.execute("UPDATE assignments SET active = 0 WHERE id = ?", (assignment_id,))
    conn.commit()
