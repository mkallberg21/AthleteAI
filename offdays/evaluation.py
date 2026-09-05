"""The artifact a coach takes into tryouts.

Coaches will use this data at selection whether or not anybody designs for it.
The realistic choice is not between "this gets used at tryouts" and "it does
not" -- it is between shipping something deliberate and leaving a coach to
screenshot a leaderboard, which is the worst possible version: ranked by
volume, with a child's name at the bottom of it.

So this exists to *control what gets weighted*.

**Volume is not in it.** Not reps, not XP, not minutes, not session counts.
Volume mostly measures opportunity: a child with a garage, a wall, and a
parent who drives them will out-rep a child sharing a bedroom in a flat, and
neither of those facts is about the athlete. Every figure here is either "did
they turn up" or "did they get better", both of which a child controls.

**It is not sorted.** Alphabetical, always. Sorting is ranking -- a list
ordered by form score is read top-down as best-to-worst no matter what the
header says, and a composite score is a ranking with one column.

**Nobody's injury history is in it.** A coach can see what an athlete is
carrying today, because that changes today's session. What they cannot have is
a record of past injuries at the moment they are deciding who to cut; a child
who learns that reporting pain costs them a place stops reporting pain.

That creates the one genuinely hard problem here, and it is worth naming: an
athlete who missed six weeks injured has terrible participation and the coach
cannot be told why. Hiding it makes them look lazy. Showing it leaks the thing
above. The answer is neither -- **weeks an athlete was told not to train, or
was away with permission, come out of their denominator**. The rate is fair,
and the reason stays private.
"""
from __future__ import annotations

import csv
import io
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import absence as absence_mod
from . import wellness as wellness_mod

#: Below this many scored sessions a form trend is noise, and printing one
#: next to a child's name at a tryout would be worse than printing nothing.
MIN_SAMPLES_FOR_TREND = 6

#: Movement smaller than this is not improvement, it is measurement.
TREND_RESOLUTION = 4


class Trend:
    IMPROVING = "improving"
    STEADY = "steady"
    SLIPPING = "slipping"
    UNKNOWN = "not enough data"


@dataclass
class Row:
    """One athlete. Deliberately without a total."""

    athlete_id: int
    display_name: str
    #: Weeks in the window where they trained at least once, over weeks they
    #: were actually available. Availability, not the raw window -- see the
    #: module docstring.
    weeks_active: int = 0
    weeks_available: int = 0
    form_now: int | None = None
    form_change: int | None = None
    trend: str = Trend.UNKNOWN
    samples: int = 0

    @property
    def participation(self) -> float | None:
        if not self.weeks_available:
            return None
        return self.weeks_active / self.weeks_available

    def to_dict(self) -> dict[str, Any]:
        return {
            "athlete_id": self.athlete_id,
            "display_name": self.display_name,
            "weeks_active": self.weeks_active,
            "weeks_available": self.weeks_available,
            "participation": (round(self.participation, 3)
                              if self.participation is not None else None),
            "form_now": self.form_now,
            "form_change": self.form_change,
            "trend": self.trend,
            # `samples` is deliberately not published. It is kept for the
            # trend logic and nothing renders it, but "12 weeks trained, 0
            # scored sessions" is a signature -- and the one thing it
            # signatures is an athlete whose accommodations a selector must
            # not learn about. A shown trend already implies enough samples.
        }


#: Printed at the top of every export, and carried in the payload. A caveat
#: that lives only in documentation is a caveat nobody reads at a tryout.
PREAMBLE = (
    "What this is: how often each athlete turned up, and whether their "
    "technique improved. Both are things an athlete controls.\n"
    "What this is not: it is not a ranking, and not a measure of volume. "
    "Reps, XP and minutes are deliberately absent, because they mostly measure "
    "opportunity, meaning a garage, a wall, and a lift to practice, rather than "
    "the athlete.\n"
    "Participation is measured against weeks each athlete was available, so "
    "somebody who was injured or away is not penalised for it. The reason is "
    "not shown, and past injuries are not in this document at all.\n"
    "A blank form score means our analysis had no reading for that athlete. "
    "That happens for several reasons: the camera could not see the movement "
    "clearly, or technique scoring is switched off because our analysis does "
    "not fit how they train. It is not a judgement about the athlete and it "
    "is not a gap in their effort. Do not read it as one, and do not ask us "
    "which reason applies to which athlete.\n"
    "This is one input among many. It does not know how a child plays."
)


def _weeks(start: date, end: date) -> list[tuple[date, date]]:
    out, cursor = [], start
    while cursor <= end:
        week_end = min(cursor + timedelta(days=6), end)
        out.append((cursor, week_end))
        cursor = week_end + timedelta(days=1)
    return out


def _unavailable_days(
    conn: sqlite3.Connection, athlete_id: int, start: date, end: date
) -> set[date]:
    """Days the athlete was told not to train, or was away with permission.

    Not returned to any caller and not exposed -- it exists only to shrink a
    denominator. The coach sees a fair rate and never learns the reason.
    """
    out = set(absence_mod.paused_days(conn, athlete_id))

    # Days inside a return-to-play ramp.
    for row in conn.execute(
        "SELECT started_on, completed_on FROM return_plans WHERE athlete_id = ?",
        (athlete_id,),
    ):
        try:
            began = date.fromisoformat(row["started_on"])
        except (TypeError, ValueError):
            continue
        finished = end
        if row["completed_on"]:
            try:
                finished = date.fromisoformat(row["completed_on"])
            except ValueError:
                pass
        day = max(began, start)
        while day <= min(finished, end):
            out.add(day)
            day += timedelta(days=1)

    # Days an open report was holding them back.
    for row in conn.execute(
        "SELECT reported_on, resolved_on, severity FROM discomfort_reports "
        "WHERE athlete_id = ?",
        (athlete_id,),
    ):
        if row["severity"] not in (
            wellness_mod.Severity.HURTS, wellness_mod.Severity.SORE
        ):
            continue
        try:
            began = date.fromisoformat(row["reported_on"])
        except (TypeError, ValueError):
            continue
        finished = min(
            end,
            date.fromisoformat(row["resolved_on"]) if row["resolved_on"]
            else began + timedelta(days=wellness_mod.STALE_AFTER_DAYS),
        )
        day = max(began, start)
        while day <= finished:
            out.add(day)
            day += timedelta(days=1)

    return out


def _trend(change: int | None, samples: int) -> str:
    if samples < MIN_SAMPLES_FOR_TREND or change is None:
        return Trend.UNKNOWN
    if change >= TREND_RESOLUTION:
        return Trend.IMPROVING
    if change <= -TREND_RESOLUTION:
        return Trend.SLIPPING
    return Trend.STEADY


def _row_for(
    conn: sqlite3.Connection, athlete_id: int, name: str, start: date, end: date
) -> Row:
    row = Row(athlete_id=athlete_id, display_name=name)

    trained = {
        date.fromisoformat(r["day"])
        for r in conn.execute(
            "SELECT DISTINCT date(submitted_at) AS day FROM sessions "
            "WHERE athlete_id = ? AND status = 'counted' "
            "AND date(submitted_at) BETWEEN ? AND ?",
            (athlete_id, start.isoformat(), end.isoformat()),
        )
    }
    unavailable = _unavailable_days(conn, athlete_id, start, end)

    for week_start, week_end in _weeks(start, end):
        days = {
            week_start + timedelta(days=i)
            for i in range((week_end - week_start).days + 1)
        }
        # A week the athlete was out for most of is not a week they skipped.
        if len(days & unavailable) > len(days) / 2:
            continue
        row.weeks_available += 1
        if days & trained:
            row.weeks_active += 1

    scores = [
        int(r["quality_score"])
        for r in conn.execute(
            "SELECT quality_score FROM sessions WHERE athlete_id = ? "
            "AND status = 'counted' AND quality_score IS NOT NULL "
            "AND date(submitted_at) BETWEEN ? AND ? ORDER BY submitted_at",
            (athlete_id, start.isoformat(), end.isoformat()),
        )
    ]
    row.samples = len(scores)
    if scores:
        half = max(1, len(scores) // 2)
        later = scores[-half:]
        row.form_now = round(sum(later) / len(later))
        if len(scores) >= MIN_SAMPLES_FOR_TREND:
            earlier = scores[:half]
            row.form_change = row.form_now - round(sum(earlier) / len(earlier))
    row.trend = _trend(row.form_change, row.samples)
    return row


@dataclass
class Export:
    team_id: int | None
    team_name: str
    start: str
    end: str
    rows: list[Row] = field(default_factory=list)
    preamble: str = PREAMBLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "team_name": self.team_name,
            "start": self.start,
            "end": self.end,
            "preamble": self.preamble,
            "athletes": [r.to_dict() for r in self.rows],
        }

    def to_csv(self) -> str:
        """CSV, because a coach will put this in a spreadsheet regardless.

        The preamble rides along as comment lines. A caveat that lives only in
        the web page is a caveat that does not survive the export, and the
        export is the thing that reaches the selection meeting.
        """
        out = io.StringIO()
        for line in self.preamble.split("\n"):
            out.write(f"# {line}\n")
        out.write(f"# Window: {self.start} to {self.end}\n")
        out.write("# Sorted alphabetically. This is not a ranking.\n")

        writer = csv.writer(out)
        writer.writerow([
            "Athlete", "Weeks trained", "Weeks available", "Participation",
            "Form score", "Form change", "Trend",
        ])
        for row in self.rows:
            writer.writerow([
                row.display_name,
                row.weeks_active,
                row.weeks_available,
                f"{row.participation:.0%}" if row.participation is not None else "",
                row.form_now if row.form_now is not None else "",
                f"{row.form_change:+d}" if row.form_change is not None else "",
                row.trend,
            ])
        return out.getvalue()


def build(
    conn: sqlite3.Connection,
    org_id: int,
    team_id: int | None = None,
    *,
    weeks: int = 12,
    today: date | None = None,
    scope: list[int] | None = None,
) -> Export:
    """The export for a squad over a window."""
    today = today or datetime.now(timezone.utc).date()
    start = today - timedelta(weeks=weeks) + timedelta(days=1)

    sql = (
        "SELECT DISTINCT u.id, u.display_name FROM users u "
        "JOIN team_members tm ON tm.user_id = u.id "
        "WHERE u.org_id = ? AND u.role = 'athlete' AND u.active = 1"
    )
    params: list[Any] = [org_id]
    if team_id is not None:
        sql += " AND tm.team_id = ?"
        params.append(team_id)
    elif scope:
        sql += f" AND tm.team_id IN ({','.join('?' for _ in scope)})"
        params.extend(scope)

    name = ""
    if team_id is not None:
        row = conn.execute(
            "SELECT name FROM teams WHERE id = ?", (team_id,)
        ).fetchone()
        name = row["name"] if row else ""

    export = Export(
        team_id=team_id, team_name=name,
        start=start.isoformat(), end=today.isoformat(),
    )
    export.rows = [
        _row_for(conn, int(r["id"]), r["display_name"] or "", start, today)
        for r in conn.execute(sql, params)
    ]
    # Alphabetical, always. Sorting by anything measured turns the document
    # into the ranking it says it is not.
    export.rows.sort(key=lambda r: (r.display_name or "").lower())
    return export
