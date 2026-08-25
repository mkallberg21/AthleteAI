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

They are a starting point a program can change (`OFFDAYS_BUDGET_SCALE`), not a
clinical prescription, and the app says so where an athlete can see it.
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import positions
from . import season
from . import sports
from . import transfer
from .config import CONFIG
from .drills.catalog import DRILLS_BY_KEY

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


def _rescaled(band: AgeBand, scale: float) -> AgeBand:
    """Scale the volume figures of a band, leaving the day counts alone.

    Days per week are a rhythm, not a quantity: an athlete on a lighter budget
    should still spread it over the same number of short sessions rather than
    compress it into one. `session_max` is left alone for the same reason --
    it is a ceiling on any single sitting, and lowering it here would flag
    ordinary sessions as too long for a kid who simply plays other sports.
    """
    if scale == 1.0:
        return band
    return AgeBand(
        label=band.label, min_age=band.min_age, max_age=band.max_age,
        weekly_min=round(band.weekly_min * scale),
        weekly_target=round(band.weekly_target * scale),
        weekly_max=round(band.weekly_max * scale),
        session_max=band.session_max,
        days_target=band.days_target, days_max=band.days_max, note=band.note,
    )


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
    #: Where the program is in its year. Carried so a screen can explain why
    #: this week's number differs from last month's, rather than leaving an
    #: athlete to conclude the app moved the goalposts on them.
    phase: "season.Phase | None" = None

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
            "phase": self.phase.to_dict() if self.phase else None,
        }


def _s(n: int) -> str:
    """Plural suffix. 'over 1 days' is the tell that nobody read the copy."""
    return "" if n == 1 else "s"


_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def _words(n: int) -> str:
    return _WORDS.get(n, str(n))


def assess_time(
    band: AgeBand,
    week: WeekOfTraining,
    first_name: str = "",
    phase: "season.Phase | None" = None,
) -> TimeBudget:
    """Where an athlete sits against their budget, and what to say about it.

    The wording carries as much of this feature as the arithmetic does. It has
    to be able to say *stop* without sounding like a telling-off, and *that is
    enough* without sounding like a shrug.

    During a post-season break it must also be able to say *nothing* -- the
    two branches that would otherwise encourage more work go quiet. Scaling
    the budget down and then nudging a child to fill it anyway would give away
    the entire point of having a break.
    """
    minutes = week.minutes
    fraction = minutes / band.weekly_target if band.weekly_target else 0.0
    # The name goes in the detail, never the headline: "Jordan are building"
    # is the grammar bug that comes free with interpolating a name into a
    # sentence whose verb was written for "you".
    greeting = f"{first_name}, " if first_name else ""

    resting = phase is not None and phase.key == "postseason"

    if week.sessions == 0:
        # A blank week during the break is the plan working, not a lapse, and
        # this is the screen where saying otherwise would do the damage.
        if resting:
            return TimeBudget(
                band=band, week=week, status=Status.FULL,
                headline="Enjoy the break",
                detail=(
                    "Nothing logged, and that is fine right now — the rest "
                    "between seasons is what lets you come back fresh. Pick it "
                    "up when pre-season starts."
                ),
                fraction=0.0, phase=phase,
            )
        return TimeBudget(
            band=band, week=week, status=Status.UNKNOWN,
            headline="Nothing logged this week",
            detail=(
                f"About {band.weekly_target} minutes across {band.days_target} days "
                f"is a good week at your age. That is {_words(band.days_target)} short "
                f"session{_s(band.days_target)} of about {band.weekly_target // band.days_target} "
                "minutes, not an evening job."
            ),
            fraction=0.0, phase=phase,
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
            over_by_minutes=minutes - band.weekly_max, phase=phase,
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
            fraction=min(1.5, fraction), phase=phase,
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
            fraction=fraction, phase=phase,
        )

    if resting:
        # Under target during the break. Under target *is* the target.
        return TimeBudget(
            band=band, week=week, status=Status.GOOD,
            headline="Ticking over nicely",
            detail=(
                f"{round(minutes)} minutes during the break is plenty. There is "
                "nothing to catch up on — this is the part of the year where "
                "doing less is the training."
            ),
            fraction=fraction, phase=phase,
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
        fraction=fraction, phase=phase,
    )


# ---------------------------------------------------------------------------
# Peer comparison
# ---------------------------------------------------------------------------

def _band_members(
    conn: sqlite3.Connection, org_id: int, band: AgeBand
) -> list[tuple[int, str | None]]:
    """Every athlete in the band, with their raw position string.

    Positions are normalised in Python rather than filtered in SQL, because
    the column is free text: `WHERE position = 'midfield'` misses the row
    that says "Middie", which is most of them.
    """
    year = datetime.now(timezone.utc).year
    rows = conn.execute(
        "SELECT u.id, u.birth_year, ("
        "  SELECT tm.position FROM team_members tm WHERE tm.user_id = u.id "
        "  AND tm.position IS NOT NULL AND tm.position != '' "
        "  ORDER BY tm.joined_at DESC LIMIT 1"
        ") AS position "
        "FROM users u WHERE u.org_id = ? AND u.role = 'athlete' AND u.active = 1",
        (org_id,),
    )
    out = []
    for row in rows:
        if row["birth_year"] is None:
            continue
        if band.contains(year - int(row["birth_year"])):
            out.append((row["id"], row["position"]))
    return out


@dataclass(frozen=True)
class PeerPool:
    """Who an athlete is being compared with, and how hard we had to look."""

    athletes: list[int]
    scope: str            # 'position' | 'group' | 'band'
    label: str            # reads after "compared with N ..."
    position: positions.Position | None

    @property
    def enough(self) -> bool:
        return len(self.athletes) >= MIN_PEER_GROUP

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "label": self.label,
            "count": len(self.athletes),
            "position": self.position.key if self.position else None,
        }


def build_pool(
    conn: sqlite3.Connection,
    org_id: int,
    band: AgeBand,
    position: positions.Position | None,
    sport: str = "lacrosse",
) -> PeerPool:
    """Widen the comparison group until it is big enough to mean anything.

    Position, then position family, then simply the age band. A team has
    three goalies, not eight, so a pool that only ever tried the narrowest
    option would return nothing for exactly the athletes whose position is
    most distinctive. Each step records which one it settled on, so the
    athlete is told they are being measured against midfielders their age
    rather than left to assume it.
    """
    members = _band_members(conn, org_id, band)
    resolved = [
        (athlete_id, positions.normalize(raw, sport))
        for athlete_id, raw in members
    ]

    if position is not None:
        same = [aid for aid, pos in resolved if pos is not None and pos.key == position.key]
        if len(same) >= MIN_PEER_GROUP:
            return PeerPool(same, "position", f"{position.plural.lower()} your age", position)

        family = [
            aid for aid, pos in resolved
            if pos is not None and pos.group == position.group
        ]
        if len(family) >= MIN_PEER_GROUP:
            label = positions.GROUP_LABELS.get(position.group, "athletes")
            return PeerPool(family, "group", f"{label} your age", position)

    everyone = [aid for aid, _ in resolved]
    return PeerPool(everyone, "band", "athletes your age", position)


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
    pool_scope: str = "band"
    pool_label: str = "athletes your age"

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "label": self.label,
            "percentile": self.percentile,
            "peer_count": self.peer_count,
            "value": round(self.value, 1),
            "median": round(self.median, 1),
            "blurb": self.blurb,
            "pool_scope": self.pool_scope,
            "pool_label": self.pool_label,
            # "compared with 11 midfielders your age" -- the comparison is
            # only honest if the athlete can see who it was against.
            "against": f"{self.peer_count} {self.pool_label}",
        }


def compare_to_peers(
    conn: sqlite3.Connection,
    athlete_id: int,
    org_id: int,
    band: AgeBand,
    budget: TimeBudget,
    position: positions.Position | None = None,
    today: date | None = None,
    sport: str = "lacrosse",
    pool: PeerPool | None = None,
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
    # Accepts a pre-built pool so a caller that already needed to know the
    # pool (to report it) does not resolve every athlete in the band twice
    # and risk the two answers drifting apart.
    pool = pool or build_pool(conn, org_id, band, position, sport)
    if not pool.enough:
        return []
    peers = pool.athletes

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
            pool_scope=pool.scope, pool_label=pool.label,
        ))

    if quality:
        add("quality", "Form score", quality,
            "How well you move, compared with others your age.")
    # Weak-hand parity is a goal for field players and not for a goalie,
    # whose stick work is two-handed save mechanics. Ranking a goalie on
    # left/right balance would score them on something they are not trying
    # to build, and worse, would make them chase it.
    if offhand and (position is None or position.offhand_matters):
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
# Training mix: the half of position benchmarking that needs no peers
# ---------------------------------------------------------------------------

#: Below this there is not enough of a week to have a shape worth commenting on.
MIX_MIN_MINUTES = 25.0
MIX_MIN_SESSIONS = 3
#: A gap smaller than this is inside the noise of one extra session.
MIX_GAP = 0.10


@dataclass
class MixSlice:
    drill_key: str
    label: str
    minutes: float
    actual: float
    target: float
    #: Which other sports this drill pays off in. Carried on the slice rather
    #: than fetched separately by the client so the "it is not just lacrosse"
    #: argument is never one failed request away from disappearing.
    transfers: list[dict[str, str]] = field(default_factory=list)

    @property
    def delta(self) -> float:
        return self.actual - self.target

    def to_dict(self) -> dict[str, Any]:
        return {
            "drill_key": self.drill_key,
            "label": self.label,
            "minutes": round(self.minutes, 1),
            "actual": round(self.actual, 3),
            "target": round(self.target, 3),
            "delta": round(self.delta, 3),
            "transfers": self.transfers,
        }


def training_mix(
    conn: sqlite3.Connection,
    athlete_id: int,
    position: positions.Position | None,
    today: date | None = None,
    days: int = 28,
    suppress_suggestions: bool = False,
    home_sport: str | None = None,
    plays: list[str] | None = None,
) -> dict[str, Any]:
    """How an athlete divides their solo time, against what their position needs.

    This is the position benchmark that works on a team of one. It needs no
    peer group, no minimum squad size and no program scale: a goalie spending
    every session on wall ball is worth telling, whether or not another goalie
    has ever logged anything.

    Every suggestion is a **swap**, never an addition. "Also do lateral
    bounds" quietly raises the weekly total that `assess_time` just finished
    capping, so the copy trades one drill against another and the tests
    assert that no suggestion contains the word "add" or "more".
    """
    today = today or datetime.now(timezone.utc).date()
    start = (today - timedelta(days=days - 1)).isoformat()
    position = position or positions.GENERIC
    target = positions.emphasis_for(position)

    rows = conn.execute(
        "SELECT drill_key, SUM(duration_ms) / 60000.0 AS minutes, COUNT(*) AS n "
        "FROM sessions WHERE athlete_id = ? AND status = 'counted' "
        "AND date(COALESCE(completed_at, submitted_at)) >= ? GROUP BY drill_key",
        (athlete_id, start),
    ).fetchall()

    by_drill = {r["drill_key"]: float(r["minutes"] or 0) for r in rows}
    total = sum(by_drill.values())
    sessions = sum(int(r["n"]) for r in rows)

    keys = sorted(set(by_drill) | set(target))
    slices = [
        MixSlice(
            drill_key=key,
            label=DRILLS_BY_KEY[key].name if key in DRILLS_BY_KEY else key,
            minutes=by_drill.get(key, 0.0),
            actual=(by_drill.get(key, 0.0) / total) if total else 0.0,
            target=target.get(key, 0.0),
            transfers=[
                t.to_dict() for t in transfer.for_drill(key, home_sport, plays=plays)
            ],
        )
        for key in keys
    ]
    slices.sort(key=lambda s: (-s.target, -s.actual))

    ready = total >= MIX_MIN_MINUTES and sessions >= MIX_MIN_SESSIONS
    suggestions: list[str] = []
    if ready and not suppress_suggestions:
        over = sorted((s for s in slices if s.delta > MIX_GAP),
                      key=lambda s: -s.delta)
        under = sorted((s for s in slices if s.delta < -MIX_GAP),
                       key=lambda s: s.delta)
        for short in under[:2]:
            if not over:
                break
            heavy = over[0]
            # Worded to survive the test that bans "add", "more" and "extra".
            # "Would do more for you" is benign in intent and still the wrong
            # verb to put in front of a twelve-year-old reading a training app.
            #
            # The reason changes with who is reading. An athlete old enough for
            # position work is told what their position leans on. A younger one
            # is told which *other sports* the drill pays off in, because that
            # is the honest argument for why they are not doing position work
            # yet -- and it is the argument they will repeat to a parent.
            cross = transfer.blurb(short.drill_key, home_sport, limit=3, plays=plays)
            if position.key == positions.GENERIC.key and cross:
                reason = cross.replace("This one pays off", "it pays off")
            else:
                reason = f"it is what {position.plural.lower()} lean on"
            suggestions.append(
                f"Swap some of your {heavy.label.lower()} time for "
                f"{short.label.lower()}. Same minutes, and {reason}"
                f"{'' if reason.endswith('.') else '.'}"
            )
    return {
        "position": position.to_dict(),
        "focus": position.focus,
        "window_days": days,
        "minutes": round(total, 1),
        "sessions": sessions,
        "ready": ready,
        "slices": [s.to_dict() for s in slices if s.target > 0 or s.minutes > 0],
        "suggestions": suggestions,
    }


# ---------------------------------------------------------------------------
# The whole picture
# ---------------------------------------------------------------------------

def sport_profile(conn: sqlite3.Connection, athlete_id: int) -> sports.Profile:
    """What else this athlete plays, scored for how single-sport their year is."""
    rows = conn.execute(
        "SELECT sport, seasons, is_primary FROM athlete_sports WHERE athlete_id = ?",
        (athlete_id,),
    ).fetchall()
    played = []
    for row in rows:
        sport = sports.BY_KEY.get(row["sport"])
        if sport is None:
            continue
        played.append(sports.Participation(
            sport=sport,
            seasons=tuple(s for s in (row["seasons"] or "").split(",") if s),
            is_primary=bool(row["is_primary"]),
        ))
    return sports.assess(played)


def _specialisation_note(
    position: positions.Position | None,
    age: int | None,
    min_age: int,
    specialising: bool,
    profile: sports.Profile | None = None,
    program_min_age: int | None = None,
) -> dict[str, Any] | None:
    """Why a young athlete is not getting position-specific work.

    Silence here would read as an oversight, or worse, as the app not knowing
    what position they play -- and a twelve-year-old who thinks the app has
    forgotten they are a goalie will go and do goalie work anyway. So the
    position is named back to them, and the reason is given in terms of what
    they gain rather than what they are being denied.

    When the line has moved for this particular athlete, say so and say why.
    An unexplained difference between two kids on the same team is the kind of
    thing that gets compared in a group chat and read as the app being broken.
    """
    if position is None or specialising:
        return None

    label = position.label.lower()
    moved = program_min_age is not None and min_age != program_min_age
    reason = ""
    if profile is not None and profile.known and moved:
        if min_age > program_min_age:
            others = "" if profile.sport_count > 1 else " and nothing else"
            reason = (
                f" You have {profile.primary.sport.label} down for most of the "
                f"year{others}, so we are giving the all-round work a bit longer "
                "than usual — that is the part that protects you."
            )
        else:
            played = _names([p.sport.label for p in profile.participations])
            reason = (
                f" You already play {played}, which is exactly the all-round "
                "base we would be building anyway, so this starts earlier for "
                "you than for most."
            )

    return {
        "position": position.label,
        "min_age": min_age,
        "program_min_age": program_min_age,
        "moved": moved,
        "headline": f"You are down as {label}, and your coach knows it",
        "detail": (
            f"Your training plan is the all-round one until you are {min_age}. "
            "The best players your age are the ones who can run, jump, land and "
            "change direction — that is what turns into being good at "
            f"{label} later, and it is worth more right now than practising one "
            f"job.{reason}"
        ),
    }


def _names(items: list[str]) -> str:
    """Join a list the way a person would say it, not the way a loop emits it."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _sport_advisories(profile: sports.Profile, age: int | None) -> list[str]:
    """Things worth saying about the shape of an athlete's year.

    Kept separate from the budget advisories because these are not about this
    week. They are about a pattern that takes a season to form and a season to
    fix, and they are addressed to a reader who can act on it.
    """
    out: list[str] = []
    if not profile.known:
        return out

    if profile.level == sports.Level.HIGH:
        out.append(
            f"{profile.primary.sport.label} is most of your year. The strongest "
            "thing you could do for it is a season of something else — a "
            "different sport builds parts of you this one never asks for, and "
            "it is the single best protection against getting hurt."
        )
    elif profile.sport_count == 1 and age is not None and age <= 14:
        out.append(
            f"{profile.primary.sport.label} is the only sport you have down. "
            "At your age, playing a second one is not a distraction from this "
            "— it is one of the better things you can do for it."
        )

    if profile.sport_count >= 2:
        played = _names([p.sport.label for p in profile.participations])
        out.append(
            f"You play {played}. That already counts as training, so what you "
            "do here does not need to be as long — the weekly number below has "
            "been trimmed to match."
        )
    return out


def report(
    conn: sqlite3.Connection,
    athlete_id: int,
    today: date | None = None,
) -> dict[str, Any]:
    """An athlete's time budget first, then how they compare inside it."""
    row = conn.execute(
        "SELECT u.id, u.org_id, u.display_name, u.birth_year, "
        "       u.birth_year_estimated, o.sport, o.position_emphasis_min_age, "
        "       o.season_phase "
        "FROM users u JOIN organizations o ON o.id = u.org_id WHERE u.id = ?",
        (athlete_id,),
    ).fetchone()
    if row is None:
        return {}

    today = today or datetime.now(timezone.utc).date()
    age = None
    if row["birth_year"]:
        age = today.year - int(row["birth_year"])

    profile = sport_profile(conn, athlete_id)
    band = scaled(band_for(age, bool(row["birth_year_estimated"])))
    # A kid playing three sports is already moving plenty, and none of that
    # week shows up here. Expecting the same solo volume from them as from a
    # single-sport athlete overstates what is left to give.
    band = _rescaled(band, sports.budget_scale(profile))
    # Last, and on top of the others: where the program is in its year. In
    # season this pulls the figure *down*, because the child is already at
    # three practices a week and none of that is counted here.
    phase = season.get(row["season_phase"])
    band = _rescaled(band, phase.scale)
    week = week_of_training(conn, athlete_id, today)
    first_name = (row["display_name"] or "").split()[0] if row["display_name"] else ""
    budget = assess_time(band, week, first_name, phase)

    # Most recent membership wins: an athlete who moved up a team mid-season
    # is playing where they play now, not where the older row says.
    sport = row["sport"] or "lacrosse"
    raw_position = conn.execute(
        "SELECT position FROM team_members WHERE user_id = ? AND position != '' "
        "ORDER BY joined_at DESC LIMIT 1",
        (athlete_id,),
    ).fetchone()
    raw_position = raw_position["position"] if raw_position else None
    position = positions.normalize(raw_position, sport)

    # Below the program's threshold the position stays on the jersey and off
    # the training plan. Position is still recorded, still shown, still on the
    # roster -- it just does not narrow what this athlete practises or who
    # they are measured against, because narrowing both at twelve is exactly
    # the specialisation the age bands exist to slow down.
    program_min_age = row["position_emphasis_min_age"]
    program_min_age = 15 if program_min_age is None else int(program_min_age)
    # The program sets the baseline; the athlete's own sport mix moves it a
    # bounded amount either side. Real variety already supplies the broad base
    # the delay was protecting; single-sport and year-round is the case the
    # delay is actually for.
    min_age = sports.effective_min_age(program_min_age, profile)
    specialising = position is not None and age is not None and age >= min_age
    applied = position if specialising else None

    pool = build_pool(conn, row["org_id"], band, applied, sport)
    comparisons = compare_to_peers(
        conn, athlete_id, row["org_id"], band, budget, applied, today, sport,
        pool=pool,
    )

    # An athlete past their ceiling gets one message, and it is "stop". Mix
    # advice alongside it -- however well framed as a swap -- reads as a
    # second task and blunts the first.
    mix = training_mix(
        conn, athlete_id, applied, today,
        suppress_suggestions=budget.status == Status.OVER,
        home_sport=sport,
        plays=[p.sport.label for p in profile.participations],
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
        "position": position.to_dict() if position else None,
        "position_raw": raw_position,
        "specialising": specialising,
        "specialisation": _specialisation_note(
            position, age, min_age, specialising, profile, program_min_age
        ),
        "sports": profile.to_dict(),
        "sport_advisories": _sport_advisories(profile, age),
        "peer_pool": pool.to_dict(),
        "mix": mix,
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
    sport: str = "lacrosse",
    phase: "season.Phase | None" = None,
) -> dict[str, Any]:
    """How a squad sits against their budgets.

    Reports the athletes doing *too much* as prominently as those doing too
    little. A coach dashboard that only ever surfaces the quiet ones teaches
    everyone to push, which is the failure this whole module exists to avoid.

    Also returns the squad's position breakdown and, deliberately, the
    position strings that did not resolve. An unrecognised position is not
    cosmetic: it drops that athlete out of every position comparison and out
    of their own drill-mix guidance, so a coach needs to see the typo.
    """
    today = today or datetime.now(timezone.utc).date()
    phase = phase or season.DEFAULT
    by_position: dict[str, int] = {}
    raw_positions: list[str] = []
    specialisation_counts: dict[str, int] = {}
    single_sport: list[dict[str, Any]] = []
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
        raw = conn.execute(
            "SELECT position FROM team_members WHERE user_id = ? AND position != '' "
            "ORDER BY joined_at DESC LIMIT 1",
            (athlete_id,),
        ).fetchone()
        raw = raw["position"] if raw else None
        athlete_profile = sport_profile(conn, athlete_id)
        specialisation_counts[athlete_profile.level] = (
            specialisation_counts.get(athlete_profile.level, 0) + 1
        )
        if athlete_profile.level == sports.Level.HIGH:
            single_sport.append({
                "athlete_id": athlete_id,
                "display_name": row["display_name"],
                "sport": athlete_profile.primary.sport.label,
                "months": athlete_profile.primary.months,
            })
        if raw:
            raw_positions.append(raw)
        resolved = positions.normalize(raw, sport)
        key = resolved.key if resolved else ("unrecognised" if raw else "none")
        by_position[key] = by_position.get(key, 0) + 1

        age = year - int(row["birth_year"]) if row["birth_year"] else None
        band = scaled(band_for(age, bool(row["birth_year_estimated"])))
        # The same season scale the athlete's own screen applies. Without it a
        # coach counts "over budget" against a different number than the one
        # the child was shown, and the two screens quietly disagree.
        band = _rescaled(band, phase.scale) if phase else band
        budget = assess_time(
            band, week_of_training(conn, athlete_id, today), phase=phase)
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
    known = {p.key: p.label for p in positions.for_sport(sport)}
    return {
        "counts": counts,
        "over_budget": over,
        "roster": len(athlete_ids),
        "phase": phase.to_dict(),
        "positions": [
            {"key": key, "label": known.get(key, key.title()), "count": n}
            for key, n in sorted(by_position.items(), key=lambda kv: -kv[1])
        ],
        "unrecognised_positions": positions.unrecognised(raw_positions, sport),
        "specialisation": specialisation_counts,
        # Named, unlike the budget lists, because this is not a this-week
        # nudge -- it is a conversation a coach has once, with a family, about
        # a pattern that took a season to form.
        "single_sport": sorted(single_sport, key=lambda a: -a["months"]),
    }
