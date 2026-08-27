"""Training load monitoring and overuse protection.

Why this exists, stated plainly: everything else in this codebase rewards
volume. XP scales with reps, leaderboards rank on totals, and streaks reward
training every single day. Those mechanics work -- which is the problem, because
the thing they are good at driving is exactly the thing that causes overuse
injury in young athletes. A product that gamifies youth training volume without
a counterweight is not neutral; it is a risk factor.

What is measured
----------------
* **Acute:chronic workload ratio.** This week's load against the trailing
  four-week average. A sharp spike is the pattern most associated with injury.
* **Throwing volume**, tracked separately. Youth baseball has decades of
  evidence behind pitch counts; lacrosse involves the same repetitive overhead
  motion and essentially nobody counts it.
* **Consecutive days without rest**, against the standard youth guidance of at
  least one full rest day per week.
* **Monotony** -- training the same amount every single day, with no hard/easy
  variation, which is associated with worse outcomes than the raw total.

Honesty about the evidence
--------------------------
The acute:chronic ratio is a useful heuristic, not settled science. The
rolling-average form used here has been criticised in the literature on
methodological grounds (spurious correlation, arbitrary thresholds, sensitivity
to the chosen windows). It is deliberately used to *raise a question with a
coach*, never to diagnose anything or to lock an athlete out of training.

Every threshold here is a reasoned starting point, and the module reports what
it actually saw rather than implying more precision than it has. It also only
ever sees work logged in this app -- team practices, games, and other sports are
invisible to it, so a quiet reading is not evidence that an athlete is fresh.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .config import CONFIG, LoadConfig
from .drills import DRILLS_BY_KEY


class Zone:
    """Where an athlete's workload ratio sits."""

    UNKNOWN = "unknown"      # not enough history to say anything
    DETRAINING = "detraining"
    BUILDING = "building"
    OPTIMAL = "optimal"
    ELEVATED = "elevated"
    HIGH = "high"


ZONE_LABELS = {
    Zone.UNKNOWN: "Not enough history",
    Zone.DETRAINING: "Dropping off",
    Zone.BUILDING: "Building",
    Zone.OPTIMAL: "Steady",
    Zone.ELEVATED: "Ramping up fast",
    Zone.HIGH: "Sharp spike",
}


@dataclass
class Advisory:
    """One thing worth a coach's attention. Never a diagnosis."""

    level: str      # 'info' | 'caution' | 'warning'
    code: str
    message: str
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "evidence": self.evidence,
        }


#: Daily throwing ceilings by age, in throws this app has actually seen.
#:
#: Shaped by published youth pitch-count guidance, and *shaped by* is the load-
#: bearing phrase. Those numbers are pitches in a game, counted by an adult with
#: a clicker, and they are as low as they are because a pitch is maximal effort
#: from a mound. A wall throw in a driveway is not a pitch.
#:
#: So these sit above the pitch guidance rather than at it. What is borrowed is
#: the shape of the thing -- that a ceiling exists at all, and that it scales
#: with age -- rather than any specific number, and nothing here should be
#: quoted as though it were the published guidance.
#:
#: The honest caveat rides on every advisory this produces: the app can only
#: count throws it saw. A pitcher who threw eighty in a game on Saturday and
#: then does fifty in the garden is at a hundred and thirty, and this knows
#: about fifty of them.
THROW_CEILING_BY_AGE: tuple[tuple[int, int], ...] = (
    (8, 60), (10, 90), (12, 105), (14, 120), (16, 135), (18, 150),
)

#: Above this share of the ceiling, say something before it is reached rather
#: than after.
THROW_CEILING_WARN = 0.80


def throw_ceiling(age: int | None) -> int | None:
    """The day's throwing ceiling for an athlete of this age.

    None when the age is unknown. A guessed ceiling would be worse than none:
    too low and it nags a seventeen-year-old, too high and it says nothing to
    the eleven-year-old it exists for.
    """
    if age is None:
        return None
    for limit, ceiling in THROW_CEILING_BY_AGE:
        if age <= limit:
            return ceiling
    return THROW_CEILING_BY_AGE[-1][1]


@dataclass
class DayLoad:
    day: date
    load: float = 0.0
    throws: int = 0
    sessions: int = 0


@dataclass
class LoadState:
    acute: float = 0.0
    chronic: float = 0.0
    acwr: float | None = None
    zone: str = Zone.UNKNOWN
    history_days: int = 0
    #: Per-tissue thresholds tightened by prior injury, and the sentence the
    #: athlete reads about it. Empty for almost everybody. See
    #: injury_history.py -- this reaches the athlete's own screen and the
    #: return-to-play flow, and deliberately not a coach's evaluation surface.
    tightened: dict[str, float] = field(default_factory=dict)
    history_note: str = ""

    weekly_throws: int = 0
    throw_change: float | None = None
    #: Throws the app saw today, and the ceiling for this athlete's age.
    #: The ceiling is None when the age is unknown, which is common enough
    #: that nothing downstream may assume it.
    throws_today: int = 0
    throw_ceiling: int | None = None

    consecutive_days: int = 0
    days_since_training: int | None = None
    rest_recommended: bool = False

    monotony: float | None = None
    advisories: list[Advisory] = field(default_factory=list)

    @property
    def needs_attention(self) -> bool:
        return any(a.level in ("caution", "warning") for a in self.advisories)

    @property
    def highest_level(self) -> str | None:
        for level in ("warning", "caution", "info"):
            if any(a.level == level for a in self.advisories):
                return level
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "acute": round(self.acute, 1),
            "chronic": round(self.chronic, 1),
            "acwr": round(self.acwr, 2) if self.acwr is not None else None,
            "zone": self.zone,
            "zone_label": ZONE_LABELS.get(self.zone, self.zone),
            "history_days": self.history_days,
            "tightened": self.tightened,
            "history_note": self.history_note,
            "weekly_throws": self.weekly_throws,
            "throws_today": self.throws_today,
            "throw_ceiling": self.throw_ceiling,
            "throw_change": round(self.throw_change, 2) if self.throw_change is not None else None,
            "consecutive_days": self.consecutive_days,
            "days_since_training": self.days_since_training,
            "rest_recommended": self.rest_recommended,
            "monotony": round(self.monotony, 2) if self.monotony is not None else None,
            "advisories": [a.to_dict() for a in self.advisories],
            "needs_attention": self.needs_attention,
        }


def session_load(drill_key: str, reps: int, hold_ms: int = 0) -> tuple[float, int]:
    """Load units and throw count for one session."""
    drill = DRILLS_BY_KEY.get(drill_key)
    if drill is None:
        return 0.0, 0
    spec = drill.load
    load = reps * spec.load_per_rep + (hold_ms / 60_000.0) * spec.load_per_minute
    throws = int(round(reps * spec.throws_per_rep))
    return load, throws


def _series(days: list[DayLoad], start: date, end: date) -> list[DayLoad]:
    """Dense day-by-day series, with rest days present as explicit zeros.

    The zeros matter: a rest day is data, and a sparse series would make an
    athlete who trained three times look identical to one who trained daily.
    """
    by_day = {d.day: d for d in days}
    out = []
    current = start
    while current <= end:
        out.append(by_day.get(current, DayLoad(day=current)))
        current += timedelta(days=1)
    return out


def analyze(
    days: list[DayLoad],
    *,
    today: date,
    age: int | None = None,
    config: LoadConfig | None = None,
    tightened: dict[str, float] | None = None,
    history_note: str = "",
) -> LoadState:
    """Assess an athlete's recent workload. Never raises.

    `tightened` comes from prior injury and makes a caution arrive earlier on
    the tissues involved. It never blocks anything and never reduces a budget
    -- it moves the point at which this app raises a question, which is the
    only thing a prediction like that has any business doing to a child.
    """
    cfg = config or CONFIG.load
    state = LoadState()
    state.tightened = dict(tightened or {})
    state.history_note = history_note

    if not days:
        state.advisories.append(
            Advisory("info", "no_history", "No training logged yet.")
        )
        return state

    trained_days = [d for d in days if d.load > 0]
    if not trained_days:
        return state

    first = min(d.day for d in trained_days)
    state.history_days = (today - first).days + 1

    window = _series(days, today - timedelta(days=cfg.chronic_days - 1), today)
    acute_window = window[-cfg.acute_days:]

    state.acute = sum(d.load for d in acute_window)

    # Chronic is a weekly equivalent, averaged over the days the athlete has
    # actually been training rather than the full 28-day window.
    #
    # Padding with pre-history zeros deflates the baseline and inflates the
    # ratio: three weeks of perfectly consistent training scored 1.33 and
    # tripped an "elevated" warning purely because the athlete had not existed
    # for the first seven days of the window. That false alarm would fire for
    # every new athlete in weeks three and four -- exactly when they are
    # forming the habit and least able to tell a real signal from noise.
    chronic_span = max(cfg.acute_days, min(cfg.chronic_days, state.history_days))
    state.chronic = sum(d.load for d in window) / (chronic_span / cfg.acute_days)

    state.weekly_throws = sum(d.throws for d in acute_window)
    state.throws_today = sum(
        d.throws for d in acute_window if d.day == max(x.day for x in acute_window)
    ) if acute_window else 0

    # --- Ratio, only where there is enough history to mean anything ---
    if state.history_days >= cfg.min_history_days and state.chronic > 0:
        state.acwr = state.acute / state.chronic
        state.zone = _zone(state.acwr, cfg)
    else:
        state.zone = Zone.UNKNOWN
        if state.acute > 0:
            state.advisories.append(
                Advisory(
                    "info",
                    "building_baseline",
                    "Still building a baseline -- workload comparisons start after "
                    f"{cfg.min_history_days} days of history.",
                    f"{state.history_days} days logged so far.",
                )
            )

    # --- Rest days ---
    #
    # Counted as the run ending on the athlete's most recent training day, not
    # the run ending today. Someone who trained six days straight and has not
    # trained yet this morning has still earned a rest day; measuring back from
    # today would read that as a streak of zero.
    trailing_idx = len(window) - 1
    while trailing_idx >= 0 and window[trailing_idx].load <= 0:
        trailing_idx -= 1

    if trailing_idx >= 0:
        state.days_since_training = (today - window[trailing_idx].day).days
        run = 0
        for day in reversed(window[: trailing_idx + 1]):
            if day.load > 0:
                run += 1
            else:
                break
        state.consecutive_days = run

    # Only suggest rest while the run is still live. Once they have already
    # been off for a couple of days, telling them to rest is noise.
    state.rest_recommended = (
        state.consecutive_days >= cfg.rest_day_after
        and state.days_since_training is not None
        and state.days_since_training <= 1
    )

    # --- Monotony: same load every day, with no hard/easy variation ---
    loads = [d.load for d in acute_window]
    if len([x for x in loads if x > 0]) >= 4:
        spread = statistics.pstdev(loads)
        mean = statistics.fmean(loads)
        if spread > 0:
            state.monotony = mean / spread
        elif mean > 0:
            # Identical load every single day is the *most* monotonous week
            # possible, not an unmeasurable one. Dividing by a zero spread
            # would silently drop exactly the case worth flagging.
            state.monotony = cfg.monotony_ceiling

    # --- Throwing volume trend ---
    if len(window) >= cfg.acute_days * 2:
        previous = sum(d.throws for d in window[-cfg.acute_days * 2: -cfg.acute_days])
        if previous >= cfg.throw_trend_min_baseline:
            state.throw_change = (state.weekly_throws - previous) / previous

    state.throw_ceiling = throw_ceiling(age)
    _add_advisories(state, cfg, age, acute_window)
    return state


def _zone(acwr: float, cfg: LoadConfig) -> str:
    if acwr < cfg.detraining_below:
        return Zone.DETRAINING
    if acwr < cfg.optimal_low:
        return Zone.BUILDING
    if acwr <= cfg.optimal_high:
        return Zone.OPTIMAL
    if acwr <= cfg.elevated_high:
        return Zone.ELEVATED
    return Zone.HIGH


def _tissue_tightening(state: LoadState, *tissues: str) -> float:
    """The largest tightening that applies to any of these tissues."""
    return max((state.tightened.get(t, 0.0) for t in tissues), default=0.0)


def _add_advisories(
    state: LoadState, cfg: LoadConfig, age: int | None, acute_window: list[DayLoad]
) -> None:
    """Turn the numbers into things a coach can act on."""

    # Prior injury pulls the *elevated* line down on the tissues involved, so
    # an athlete who has been here before gets the question a little sooner.
    # The HIGH line is left alone deliberately: it is already the point at
    # which this app says ease off, and moving it would mean a child with a
    # history gets told to stop on a week their teammate is told is fine.
    whole = _tissue_tightening(state, "whole_body", "lower_body", "core")
    elevated_low = cfg.optimal_high * (1.0 - whole)
    if (whole and state.zone == Zone.OPTIMAL and state.acwr is not None
            and state.acwr >= elevated_low):
        state.advisories.append(
            Advisory(
                "caution",
                "history_ramp",
                "This week is a bigger step up than usual, and you have come "
                "back from something before. Worth an easier day rather than "
                "another hard one.",
                f"Workload ratio {state.acwr:.2f}.",
            )
        )

    if state.zone == Zone.HIGH:
        state.advisories.append(
            Advisory(
                "warning",
                "load_spike",
                "This week's training is a sharp jump on the last month. That "
                "pattern is the one most associated with overuse injury -- worth "
                "easing off for a few days.",
                f"Workload ratio {state.acwr:.2f} (steady range "
                f"{cfg.optimal_low:.1f}-{cfg.optimal_high:.1f}).",
            )
        )
    elif state.zone == Zone.ELEVATED:
        state.advisories.append(
            Advisory(
                "caution",
                "load_elevated",
                "Training is ramping up faster than usual. Fine for a week, "
                "worth watching if it keeps climbing.",
                f"Workload ratio {state.acwr:.2f}.",
            )
        )

    history_rest_after = cfg.rest_day_after
    if whole:
        history_rest_after = max(3, round(cfg.rest_day_after * (1.0 - whole)))
        if (not state.rest_recommended
                and state.consecutive_days >= history_rest_after):
            state.advisories.append(
                Advisory(
                    "caution",
                    "history_rest",
                    f"{state.consecutive_days} days in a row. Given what you "
                    "have come back from, a day off now is worth more than "
                    "another session.",
                    "Rest days are when adaptation actually happens.",
                )
            )

    if state.rest_recommended:
        state.advisories.append(
            Advisory(
                "caution" if state.consecutive_days < cfg.rest_day_urgent else "warning",
                "no_rest_day",
                f"{state.consecutive_days} days in a row without a rest day. "
                "Standard youth guidance is at least one full day off per week.",
                "Rest days are when adaptation actually happens.",
            )
        )

    # An absolute ceiling, not just a week-on-week change. The spike check below
    # is blind to an athlete who throws a lot every week and always has -- which
    # is exactly the pattern that hurts a young arm, and exactly the pattern a
    # relative measure calls normal.
    if state.throw_ceiling and state.throws_today:
        share = state.throws_today / state.throw_ceiling
        seen = (
            f"{state.throws_today} of about {state.throw_ceiling} for this age "
            "-- and only counting throws the app saw, not games or practice."
        )
        if share >= 1.0:
            state.advisories.append(
                Advisory(
                    "warning",
                    "throw_ceiling",
                    "That is a full day's throwing for a growing arm. Whatever "
                    "else is planned today, this part is done.",
                    seen,
                )
            )
        elif share >= THROW_CEILING_WARN:
            state.advisories.append(
                Advisory(
                    "caution",
                    "throw_ceiling_near",
                    "Close to a full day's throwing. Worth stopping here rather "
                    "than finding out tomorrow.",
                    seen,
                )
            )

    if state.throw_change is not None and state.throw_change >= cfg.throw_spike_change:
        state.advisories.append(
            Advisory(
                "caution",
                "throw_spike",
                f"Throwing volume is up {state.throw_change:.0%} on last week. "
                "Young shoulders and elbows tolerate gradual increases far "
                "better than sudden ones.",
                f"{state.weekly_throws} throws this week.",
            )
        )

    if state.monotony is not None and state.monotony >= cfg.monotony_threshold:
        state.advisories.append(
            Advisory(
                "info",
                "monotony",
                "Every day looks the same. Mixing hard days with genuinely easy "
                "ones tends to produce better results than a flat grind.",
                f"Monotony {state.monotony:.1f}.",
            )
        )

    # Age-based volume guidance. Deliberately worded as a prompt to check the
    # athlete's *total* week, because this app only sees the work logged in it
    # -- team practices, games, and other sports are all invisible here.
    if age is not None and age <= CONFIG.minor_age_ceiling:
        hours = sum(d.sessions for d in acute_window) * cfg.assumed_session_hours
        if hours >= age * cfg.age_hours_warn_fraction:
            state.advisories.append(
                Advisory(
                    "info",
                    "age_volume",
                    "A common youth guideline is to keep weekly organised "
                    f"training hours at or under an athlete's age ({age}). This "
                    "app only sees self-directed work, so the real total is "
                    "higher -- worth a look at the whole week.",
                    f"About {hours:.1f}h logged here this week.",
                )
            )

    if state.zone == Zone.DETRAINING:
        # Not a safety issue, but the coach wants to know, and an athlete
        # returning from a layoff is the one most likely to spike next week.
        state.advisories.append(
            Advisory(
                "info",
                "detraining",
                "Training has dropped well below this athlete's usual level. "
                "Build back gradually rather than picking up where they left off.",
                f"Workload ratio {state.acwr:.2f}." if state.acwr is not None else "",
            )
        )

    if not state.advisories and state.zone == Zone.OPTIMAL:
        state.advisories.append(
            Advisory("info", "steady", "Workload is steady and well inside the usual range.")
        )
