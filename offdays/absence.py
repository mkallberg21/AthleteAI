"""Holidays, tournaments, and the difference between pausing and forgiving.

Streaks already forgive one missed day, which covers a bad week. They do not
cover a family holiday, a tournament weekend away, or a school trip -- and
those are predictable, which makes losing a streak to one a churn moment the
product walked into with its eyes open.

The word that matters is **pause**. There are two ways to build this and only
one of them is honest.

The easy way is to count absence days as active days. Then a fortnight away
turns a seven-day streak into twenty-one, the number stops describing anything
the child did, and a streak nobody believes is a streak nobody protects.

So instead the days are **removed from the timeline**. The gap either side
closes up, and the athlete comes back to exactly the streak they earned. They
do not gain; they just do not lose.

**Set by a parent or a coach, never by the athlete.** A child who can declare
their own absence has a button that undoes a missed day, and a streak with an
undo button is not a streak. It is also the wrong conversation to put a
twelve-year-old in charge of: whether the family is away is a fact an adult
knows.

**Bounded, and not retroactive by much.** A window that can start six months
back is a way to repair any gap in history, which is the undo button again
wearing a hat. A few days of grace covers the parent who set off on Saturday
and remembered on Monday.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any


class AbsenceError(Exception):
    pass


#: Longer than this is not a pause, it is a season off -- and a streak that
#: survives a two-month gap is not describing a habit any more.
MAX_DAYS = 30

#: How far back a window may start. Enough for the parent who left on Saturday
#: and remembered on Monday; not enough to repair an arbitrary gap in history.
MAX_BACKDATE_DAYS = 7

#: How far ahead one may be booked. A year out is not a plan, it is a way to
#: switch streaks off permanently.
MAX_LEAD_DAYS = 365


def _today(today: date | None = None) -> date:
    return today or datetime.now(timezone.utc).date()


@dataclass
class Absence:
    id: int
    athlete_id: int
    starts_on: date
    ends_on: date
    reason: str = ""
    set_by_name: str = ""

    @property
    def days(self) -> int:
        return (self.ends_on - self.starts_on).days + 1

    def covers(self, day: date) -> bool:
        return self.starts_on <= day <= self.ends_on

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "athlete_id": self.athlete_id,
            "starts_on": self.starts_on.isoformat(),
            "ends_on": self.ends_on.isoformat(),
            "days": self.days,
            "reason": self.reason,
            "set_by_name": self.set_by_name,
        }


def _row(row: sqlite3.Row) -> Absence:
    return Absence(
        id=int(row["id"]), athlete_id=int(row["athlete_id"]),
        starts_on=date.fromisoformat(row["starts_on"]),
        ends_on=date.fromisoformat(row["ends_on"]),
        reason=row["reason"] or "", set_by_name=row["set_by_name"] or "",
    )


def schedule(
    conn: sqlite3.Connection,
    athlete_id: int,
    starts_on: str,
    ends_on: str,
    *,
    set_by: int | None = None,
    set_by_name: str = "",
    reason: str = "",
    today: date | None = None,
) -> Absence:
    """Book a window. Validated so it stays a pause rather than an undo."""
    today = _today(today)
    try:
        start = date.fromisoformat(starts_on)
        end = date.fromisoformat(ends_on)
    except ValueError as exc:
        raise AbsenceError(f"dates must be YYYY-MM-DD: {exc}") from None

    if end < start:
        raise AbsenceError("an absence cannot end before it starts")
    if (end - start).days + 1 > MAX_DAYS:
        raise AbsenceError(
            f"{(end - start).days + 1} days is longer than a pause, and "
            f"{MAX_DAYS} is the most this will hold a streak across"
        )
    if (today - start).days > MAX_BACKDATE_DAYS:
        raise AbsenceError(
            f"an absence can only start up to {MAX_BACKDATE_DAYS} days ago, and "
            "this is for a trip, not for repairing an old gap"
        )
    if (start - today).days > MAX_LEAD_DAYS:
        raise AbsenceError("that is too far ahead to plan an absence")

    cur = conn.execute(
        "INSERT INTO planned_absences(athlete_id, starts_on, ends_on, reason, "
        "  set_by, set_by_name, created_at) VALUES (?,?,?,?,?,?,?)",
        (athlete_id, start.isoformat(), end.isoformat(), reason.strip()[:200],
         set_by, set_by_name.strip()[:80],
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return Absence(
        id=int(cur.lastrowid), athlete_id=athlete_id, starts_on=start,
        ends_on=end, reason=reason.strip()[:200], set_by_name=set_by_name,
    )


def cancel(conn: sqlite3.Connection, absence_id: int, athlete_id: int) -> bool:
    with conn:
        return bool(conn.execute(
            "DELETE FROM planned_absences WHERE id = ? AND athlete_id = ?",
            (absence_id, athlete_id),
        ).rowcount)


def for_athlete(
    conn: sqlite3.Connection, athlete_id: int, upcoming_only: bool = False,
    today: date | None = None,
) -> list[Absence]:
    sql = "SELECT * FROM planned_absences WHERE athlete_id = ?"
    params: list[Any] = [athlete_id]
    if upcoming_only:
        sql += " AND ends_on >= ?"
        params.append(_today(today).isoformat())
    sql += " ORDER BY starts_on"
    return [_row(r) for r in conn.execute(sql, params)]


def paused_days(conn: sqlite3.Connection, athlete_id: int) -> set[date]:
    """Every day covered by an absence, flattened.

    A set rather than a list of windows: overlapping bookings (a coach set the
    tournament, a parent set the same weekend) must count once, not twice.
    """
    out: set[date] = set()
    for absence in for_athlete(conn, athlete_id):
        day = absence.starts_on
        while day <= absence.ends_on:
            out.add(day)
            day += timedelta(days=1)
    return out


def current(
    conn: sqlite3.Connection, athlete_id: int, today: date | None = None
) -> Absence | None:
    today = _today(today)
    for absence in for_athlete(conn, athlete_id):
        if absence.covers(today):
            return absence
    return None


def note(absence: Absence | None) -> str:
    """What an athlete reads while they are away.

    Says the streak is safe and asks for nothing. A nudge to train through a
    holiday is the exact message this feature exists to stop sending.
    """
    if absence is None:
        return ""
    reason = f" ({absence.reason})" if absence.reason else ""
    return (
        f"You are down as away until {absence.ends_on.isoformat()}{reason}. "
        "Your streak is paused, not broken. Pick it back up when you are home."
    )
