"""Age-appropriate training budgets, and benchmarks that live inside them.

A benchmark that only ever says "you are at the 40th percentile" has exactly one
implied instruction: do more. For a twelve-year-old who already trains four days
a week, has homework, and has not seen their friends outside practice in a
month, that instruction is wrong -- and a product that can only ever say it is
not a training tool, it is a pressure machine.

So the order is deliberately inverted here. **The first number an athlete sees
is how much time is right for their age**, and where they sit inside it. Only
once they are meaningfully short of that budget does the app suggest more. Once
they are inside it, the comparison switches from *how much* to *how well* --
because at that point more volume is not the improvement available to them, and
saying otherwise would be a lie with a cost.

And the app is willing to say **stop**. An athlete over their budget is told so
plainly, with the reason: rest is part of training, and being twelve is a
full-time job that this is only a small part of.

On where the numbers come from
------------------------------
There is no validated study of self-directed skill work for youth athletes, and
pretending otherwise would be worse than admitting it. These budgets are
synthesised from guidance that does exist -- the widely used heuristic that
weekly organised sport hours should not exceed an athlete's age in years, and
the paediatric sports-medicine consensus on rest days and seasonal breaks --
then deliberately set at the conservative end, because the cost of a child doing
slightly too little unstructured skill work is nothing, and the cost of too much
is an overuse injury at fourteen.

They are a starting point a program can change (`ATHLETEIQ_BUDGET_SCALE`), not a
clinical prescription, and the app says so where an athlete can see it.
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .config import CONFIG

# Below this many peers a percentile is neither meaningful nor anonymous, and
# is not shown at all.
MIN_PEER_GROUP = 8


@dataclass(frozen=True)
class AgeBand:
    """What a week of self-directed training should look like at this age.

    `weekly_min` is the point below which a nudge is useful. `weekly_target` is
    a good week. `weekly_max` is where the app stops encouraging and starts
    saying enough -- not a hard limit, since it cannot see the rest of a
    child's life, but the point at which more is not the improvement on offer.
    """

    label: str
    min_age: int
    max_age: int
    weekly_min: int          # minutes
    weekly_target: int
    weekly_max: int
    session_max: int         # minutes in any one sitting
    days_target: int         # days per week
    days_max: int
    note: str

    def contains(self, age: int) -> bool:
        return self.min_age <= age <= self.max_age

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "min_age": self.min_age,
            "max_age": self.max_age,
            "weekly_min": self.weekly_min,
            "weekly_target": self.weekly_target,
            "weekly_max": self.weekly_max,
            "session_max": self.session_max,
            "days_target": self.days_target,
            "days_max": self.days_max,
            "note": self.note,
        }


# Minutes per week of *self-directed* work, on top of team practice -- not a
# total training budget. The youngest bands are short on purpose: at that age
# unstructured play develops more than repetition does, and the evidence on
# early specialisation is not ambiguous.
AGE_BANDS: tuple[AgeBand, ...] = (
    AgeBand(
        label="Under 11", min_age=0, max_age=10,
        weekly_min=15, weekly_target=30, weekly_max=60,
        session_max=15, days_target=2, days_max=3,
        note=(
            "Short and fun beats long and serious at this age. Messing about "
            "with a ball counts for more than a structured session."
        ),
    ),
    AgeBand(
        label="11-12", min_age=11, max_age=12,
        weekly_min=20, weekly_target=45, weekly_max=90,
        session_max=20, days_target=3, days_max=4,
        note="A few short sessions a week is plenty. Keep other sports in the mix.",
    ),
    AgeBand(
        label="13-14", min_age=13, max_age=14,
        weekly_min=30, weekly_target=75, weekly_max=135,
        session_max=30, days_target=3, days_max=5,
        note="Enough to build a real habit without it taking over the week.",
    ),
    AgeBand(
        label="15-16", min_age=15, max_age=16,
        weekly_min=45, weekly_target=110, weekly_max=180,
        session_max=40, days_target=4, days_max=5,
        note="More is possible now, but rest days still matter as much as reps.",
    ),
    AgeBand(
        label="17-18", min_age=17, max_age=18,
        weekly_min=60, weekly_target=140, weekly_max=225,
        session_max=45, days_target=4, days_max=6,
        note="Close to adult volumes, with school still the bigger commitment.",
    ),
    AgeBand(
        label="19 and over", min_age=19, max_age=200,
        weekly_min=60, weekly_target=150, weekly_max=300,
        session_max=60, days_target=4, days_max=6,
        note="Adult athlete. Judge it against your own schedule.",
    ),
)

# Used when an athlete's age is unknown or was only estimated from a grade.
# The most conservative band, on the same principle as treating an unknown age
# as a minor everywhere else.
DEFAULT_BAND = AGE_BANDS[1]


class Status:
    BUILDING = "building"    # short of the budget; a nudge helps
    GOOD = "good"            # inside it
    FULL = "full"            # at the top of it; quality, not quantity
    OVER = "over"            # past it; the app says so
    UNKNOWN = "unknown"      # nothing logged yet


def band_for(age: int | None, estimated: bool = False) -> AgeBand:
    """The budget for an athlete's age, defaulting conservatively."""
    if age is None or estimated:
        return DEFAULT_BAND
    for band in AGE_BANDS:
        if band.contains(age):
            return band
    return AGE_BANDS[-1]


def scaled(band: AgeBand) -> AgeBand:
    """Apply a program's own adjustment to the published budget.

    A club whose season genuinely runs harder can raise this, and one working
    with beginners can lower it -- but they have to choose it, rather than the
    app quietly assuming their athletes can take more.
    """
    scale = CONFIG.budget_scale
    if scale == 1.0:
        return band
    return AgeBand(
        label=band.label, min_age=band.min_age, max_age=band.max_age,
        weekly_min=round(band.weekly_min * scale),
        weekly_target=round(band.weekly_target * scale),
        weekly_max=round(band.weekly_max * scale),
        session_max=round(band.session_max * scale),
        days_target=band.days_target, days_max=band.days_max, note=band.note,
    )


# ---------------------------------------------------------------------------
# Measuring a week
# ---------------------------------------------------------------------------

@dataclass
class WeekOfTraining:
    minutes: float = 0.0
    days: int = 0
    sessions: int = 0
    longest_session_minutes: float = 0.0


def week_of_training(
    conn: sqlite3.Connection, athlete_id: int, today: date | None = None
) -> WeekOfTraining:
    today = today or datetime.now(timezone.utc).date()
    start = (today - timedelta(days=6)).isoformat()

    rows = conn.execute(
        "SELECT duration_ms, date(COALESCE(completed_at, submitted_at)) AS day "
        "FROM sessions WHERE athlete_id = ? AND status = 'counted' "
        "AND date(COALESCE(completed_at, submitted_at)) BETWEEN ? AND ?",
        (athlete_id, start, today.isoformat()),
    ).fetchall()

    week = WeekOfTraining()
    days = set()
    for row in rows:
        minutes = int(row["duration_ms"]) / 60_000.0
        week.minutes += minutes
        week.sessions += 1
        week.longest_session_minutes = max(week.longest_session_minutes, minutes)
        if row["day"]:
            days.add(row["day"])
    week.days = len(days)
    return week


@dataclass
class TimeBudget:
    band: AgeBand
    week: WeekOfTraining
    status: str
    headline: str
    detail: str
    fraction: float = 0.0          # of the target, for a progress bar
    over_by_minutes: float = 0.0

    @property
    def is_enough(self) -> bool:
        return self.status in (Status.GOOD, Status.FULL, Status.OVER)

    def to_dict(self) -> dict[str, Any]:
        return {
            "band": self.band.to_dict(),
            "minutes": round(self.week.minutes),
            "days": self.week.days,
            "sessions": self.week.sessions,
            "longest_session_minutes": round(self.week.longest_session_minutes),
            "status": self.status,
            "headline": self.headline,
            "detail": self.detail,
            "fraction": round(self.fraction, 3),
            "over_by_minutes": round(self.over_by_minutes),
            "is_enough": self.is_enough,
        }


def _s(n: int) -> str:
    """Plural suffix. 'over 1 days' is the tell that nobody read the copy."""
    return "" if n == 1 else "s"


_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def _words(n: int) -> str:
    return _WORDS.get(n, str(n))


def assess_time(
    band: AgeBand, week: WeekOfTraining, first_name: str = ""
) -> TimeBudget:
    """Where an athlete sits against their budget, and what to say about it.

    The wording carries as much of this feature as the arithmetic does. It has
    to be able to say *stop* without sounding like a telling-off, and *that is
    enough* without sounding like a shrug.
    """
    minutes = week.minutes
    fraction = minutes / band.weekly_target if band.weekly_target else 0.0
    # The name goes in the detail, never the headline: "Jordan are building"
    # is the grammar bug that comes free with interpolating a name into a
    # sentence whose verb was written for "you".
    greeting = f"{first_name}, " if first_name else ""

    if week.sessions == 0:
        return TimeBudget(
            band=band, week=week, status=Status.UNKNOWN,
            headline="Nothing logged this week",
            detail=(
                f"About {band.weekly_target} minutes across {band.days_target} days "
                f"is a good week at your age. That is {_words(band.days_target)} short "
                f"session{_s(band.days_target)} of about {band.weekly_target // band.days_target} "
                "minutes, not an evening job."
            ),
            fraction=0.0,
        )

    if minutes > band.weekly_max:
        return TimeBudget(
            band=band, week=week, status=Status.OVER,
            headline="That is more than enough for this week",
            detail=(
                f"{round(minutes)} minutes is past the {band.weekly_max} that suits "
                f"your age. Take a couple of days off — rest is when the work "
                "actually turns into progress, and there is more to being your age "
                "than this."
            ),
            fraction=min(2.0, fraction),
            over_by_minutes=minutes - band.weekly_max,
        )

    if minutes >= band.weekly_target:
        return TimeBudget(
            band=band, week=week, status=Status.FULL,
            headline="You have done enough this week",
            detail=(
                f"{round(minutes)} minutes over {week.days} day{_s(week.days)} is a "
                "full week for "
                "your age. Anything else is a bonus, not a requirement — go and do "
                "something else."
            ),
            fraction=min(1.5, fraction),
        )

    if minutes >= band.weekly_min:
        remaining = max(0, band.weekly_target - minutes)
        return TimeBudget(
            band=band, week=week, status=Status.GOOD,
            headline="Right where you should be",
            detail=(
                f"{round(minutes)} minutes so far. Another {round(remaining)} would "
                f"round the week out, but this is already a solid week."
            ),
            fraction=fraction,
        )

    remaining = max(0, band.weekly_target - minutes)
    # A session sized the way this band's own week is sized, not half the
    # ceiling: at the ceiling the count drifts above days_target and the app
    # ends up asking a twelve-year-old for four sessions in a three-day week.
    typical = max(1, band.weekly_target // band.days_target)
    sessions_left = min(band.days_target, max(1, round(remaining / typical)))
    more = f"{sessions_left} more short session{_s(sessions_left)}"
    counted = (
        f"{greeting}that's {round(minutes)} minutes this week"
        if greeting else f"{round(minutes)} minutes this week"
    )
    return TimeBudget(
        band=band, week=week, status=Status.BUILDING,
        headline="Building the habit",
        detail=f"{counted}. {more} gets you to a good week for your age.",
        fraction=fraction,
    )


# ---------------------------------------------------------------------------
# Peer comparison
# ---------------------------------------------------------------------------

def _peers(
    conn: sqlite3.Connection, org_id: int, band: AgeBand, position: str | None
) -> list[int]:
    """Athletes in the same age band, optionally the same position.

    Compared within a band rather than against the whole program: telling a
    twelve-year-old they rank below the seventeen-year-olds is information
    about their birthday, not their training.
    """
    sql = (
        "SELECT DISTINCT u.id, u.birth_year FROM users u "
        "LEFT JOIN team_members tm ON tm.user_id = u.id "
        "WHERE u.org_id = ? AND u.role = 'athlete' AND u.active = 1"
    )
    params: list[Any] = [org_id]
    if position:
        sql += " AND tm.position = ?"
        params.append(position)

    year = datetime.now(timezone.utc).year
    peers = []
    for row in conn.execute(sql, params):
        if row["birth_year"] is None:
            continue
        if band.contains(year - int(row["birth_year"])):
            peers.append(row["id"])
    return peers


def _percentile(value: float, population: list[float]) -> int | None:
    if len(population) < MIN_PEER_GROUP:
        return None
    below = sum(1 for other in population if other < value)
    same = sum(1 for other in population if other == value)
    return round(((below + 0.5 * same) / len(population)) * 100)


@dataclass
class PeerComparison:
    metric: str
    label: str
    percentile: int | None
    peer_count: int
    value: float
    median: float
    blurb: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "label": self.label,
            "percentile": self.percentile,
            "peer_count": self.peer_count,
            "value": round(self.value, 1),
            "median": round(self.median, 1),
            "blurb": self.blurb,
        }


def compare_to_peers(
    conn: sqlite3.Connection,
    athlete_id: int,
    org_id: int,
    band: AgeBand,
    budget: TimeBudget,
    position: str | None = None,
    today: date | None = None,
) -> list[PeerComparison]:
    """How this athlete compares to others their age.

    What is compared depends on whether they have done enough. An athlete short
    of their budget sees consistency, because turning up is the thing available
    to them. An athlete already inside it sees **quality and off-hand work
    only** -- never volume, because "you are behind on reps" is precisely the
    wrong thing to tell someone who has already done a full week for their age.
    """
    today = today or datetime.now(timezone.utc).date()
    start = (today - timedelta(days=27)).isoformat()
    peers = _peers(conn, org_id, band, position)
    if len(peers) < MIN_PEER_GROUP:
        return []

    placeholders = ",".join("?" for _ in peers)

    def gather(sql: str) -> dict[int, float]:
        return {
            row["athlete_id"]: float(row["value"] or 0)
            for row in conn.execute(sql, (*peers, start))
        }

    quality = gather(
        f"SELECT athlete_id, AVG(quality_score) AS value FROM sessions "
        f"WHERE athlete_id IN ({placeholders}) AND status = 'counted' "
        f"AND quality_score IS NOT NULL "
        f"AND date(COALESCE(completed_at, submitted_at)) >= ? GROUP BY athlete_id"
    )
    offhand = gather(
        f"SELECT athlete_id, "
        f"  CASE WHEN SUM(reps_left + reps_right) > 0 "
        f"    THEN SUM(reps_left) * 1.0 / SUM(reps_left + reps_right) ELSE 0 END AS value "
        f"FROM sessions WHERE athlete_id IN ({placeholders}) AND status = 'counted' "
        f"AND date(COALESCE(completed_at, submitted_at)) >= ? GROUP BY athlete_id"
    )
    consistency = gather(
        f"SELECT athlete_id, COUNT(DISTINCT date(COALESCE(completed_at, submitted_at))) AS value "
        f"FROM sessions WHERE athlete_id IN ({placeholders}) AND status = 'counted' "
        f"AND date(COALESCE(completed_at, submitted_at)) >= ? GROUP BY athlete_id"
    )

    out: list[PeerComparison] = []

    def add(metric: str, label: str, data: dict[int, float], blurb: str, scale=1.0):
        population = [v * scale for v in data.values()]
        if len(population) < MIN_PEER_GROUP:
            return
        mine = data.get(athlete_id, 0.0) * scale
        out.append(PeerComparison(
            metric=metric, label=label,
            percentile=_percentile(mine, population),
            peer_count=len(population), value=mine,
            median=statistics.median(population) if population else 0.0,
            blurb=blurb,
        ))

    if quality:
        add("quality", "Form score", quality,
            "How well you move, compared with others your age.")
    if offhand:
        add("offhand", "Weak-hand share", offhand,
            "The hard half of the work, and the one worth being ahead on.", scale=100)

    # Consistency is offered to an athlete still building, where turning up is
    # the available improvement -- and withheld from one already at their
    # budget, where it would just read as "do more".
    if consistency and budget.status in (Status.UNKNOWN, Status.BUILDING):
        add("consistency", "Days trained (4 weeks)", consistency,
            "Turning up regularly, not for long.")

    return out


# ---------------------------------------------------------------------------
# The whole picture
# ---------------------------------------------------------------------------

def report(
    conn: sqlite3.Connection,
    athlete_id: int,
    today: date | None = None,
) -> dict[str, Any]:
    """An athlete's time budget first, then how they compare inside it."""
    row = conn.execute(
        "SELECT id, org_id, display_name, birth_year, birth_year_estimated "
        "FROM users WHERE id = ?",
        (athlete_id,),
    ).fetchone()
    if row is None:
        return {}

    today = today or datetime.now(timezone.utc).date()
    age = None
    if row["birth_year"]:
        age = today.year - int(row["birth_year"])

    band = scaled(band_for(age, bool(row["birth_year_estimated"])))
    week = week_of_training(conn, athlete_id, today)
    first_name = (row["display_name"] or "").split()[0] if row["display_name"] else ""
    budget = assess_time(band, week, first_name)

    position = conn.execute(
        "SELECT position FROM team_members WHERE user_id = ? AND position != '' LIMIT 1",
        (athlete_id,),
    ).fetchone()

    comparisons = compare_to_peers(
        conn, athlete_id, row["org_id"], band, budget,
        position["position"] if position else None, today,
    )

    advisories: list[str] = []
    if week.longest_session_minutes > band.session_max:
        advisories.append(
            f"One session ran {round(week.longest_session_minutes)} minutes. "
            f"Around {band.session_max} is plenty in one go at your age — "
            "shorter and more often beats one long grind."
        )
    if week.days > band.days_max:
        advisories.append(
            f"{week.days} days out of seven. Two days off a week is not slacking, "
            "it is how the work sticks."
        )
    if age is not None and age <= 12 and week.minutes > band.weekly_target:
        advisories.append(
            "At your age the biggest gains come from playing other sports and "
            "messing about, not from more reps of this one."
        )

    return {
        "athlete_id": athlete_id,
        "age": age,
        "age_estimated": bool(row["birth_year_estimated"]),
        "budget": budget.to_dict(),
        "comparisons": [c.to_dict() for c in comparisons],
        "position": position["position"] if position else None,
        "advisories": advisories,
        "disclaimer": (
            "These are starting points, not medical advice. They come from "
            "general youth-sport guidance and your program can adjust them."
        ),
    }


def program_summary(
    conn: sqlite3.Connection,
    athlete_ids: list[int],
    today: date | None = None,
) -> dict[str, Any]:
    """How a squad sits against their budgets.

    Reports the athletes doing *too much* as prominently as those doing too
    little. A coach dashboard that only ever surfaces the quiet ones teaches
    everyone to push, which is the failure this whole module exists to avoid.
    """
    today = today or datetime.now(timezone.utc).date()
    counts = {s: 0 for s in (Status.UNKNOWN, Status.BUILDING, Status.GOOD, Status.FULL, Status.OVER)}
    over: list[dict[str, Any]] = []
    year = today.year

    for athlete_id in athlete_ids:
        row = conn.execute(
            "SELECT display_name, birth_year, birth_year_estimated FROM users WHERE id = ?",
            (athlete_id,),
        ).fetchone()
        if row is None:
            continue
        age = year - int(row["birth_year"]) if row["birth_year"] else None
        band = scaled(band_for(age, bool(row["birth_year_estimated"])))
        budget = assess_time(band, week_of_training(conn, athlete_id, today))
        counts[budget.status] += 1
        if budget.status == Status.OVER:
            over.append({
                "athlete_id": athlete_id,
                "display_name": row["display_name"],
                "minutes": round(budget.week.minutes),
                "weekly_max": band.weekly_max,
                "band": band.label,
            })

    over.sort(key=lambda a: -a["minutes"])
    return {"counts": counts, "over_budget": over, "roster": len(athlete_ids)}
