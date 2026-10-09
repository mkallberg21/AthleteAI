"""XP, levels, streaks, and badges.

Design intent, since gamification aimed at 12-18 year olds can easily reward the
wrong behavior:

  * **Diminishing returns within a session.** One three-hour Sunday should not
    beat six honest twenty-minute days. Skill acquisition works the same way.
  * **A hard daily cap.** Without it the leaderboard measures free time and
    quietly encourages overuse injury.
  * **Off-hand work pays a premium.** In lacrosse the weak hand is the thing
    every young player avoids and every coach wants. Paying more for it points
    the incentive at the hard thing rather than the comfortable one.
  * **Streaks forgive one missed day.** Games, travel, and exams should not
    erase six weeks of work; an unforgiving streak makes athletes quit after
    the first break.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import CONFIG, ScoringConfig
from .drills import DrillSpec, Metric
from .integrity import IntegrityResult


# --------------------------------------------------------------------------
# Levels
# --------------------------------------------------------------------------

def xp_for_level(level: int, config: ScoringConfig | None = None) -> int:
    """Cumulative XP required to reach `level`. Level 1 starts at zero."""
    cfg = config or CONFIG.scoring
    if level <= 1:
        return 0
    return int(cfg.level_base * (level - 1) ** cfg.level_exponent)


def level_for_xp(total_xp: int, config: ScoringConfig | None = None) -> int:
    """Highest level fully earned by `total_xp`."""
    cfg = config or CONFIG.scoring
    level = 1
    # Levels grow superlinearly, so this terminates quickly even for large XP.
    while xp_for_level(level + 1, cfg) <= total_xp:
        level += 1
        if level > 500:  # defensive ceiling
            break
    return level


@dataclass
class LevelProgress:
    level: int
    total_xp: int
    xp_into_level: int
    xp_for_next: int

    @property
    def fraction(self) -> float:
        if self.xp_for_next <= 0:
            return 1.0
        return min(1.0, self.xp_into_level / self.xp_for_next)


def level_progress(total_xp: int, config: ScoringConfig | None = None) -> LevelProgress:
    cfg = config or CONFIG.scoring
    level = level_for_xp(total_xp, cfg)
    floor_xp = xp_for_level(level, cfg)
    next_xp = xp_for_level(level + 1, cfg)
    return LevelProgress(
        level=level,
        total_xp=total_xp,
        xp_into_level=total_xp - floor_xp,
        xp_for_next=max(0, next_xp - floor_xp),
    )


# --------------------------------------------------------------------------
# Session XP
# --------------------------------------------------------------------------

@dataclass
class XpBreakdown:
    """Itemized XP for one session, so the athlete sees *why* they earned it."""

    base: int = 0
    offhand_bonus: int = 0
    balance_bonus: int = 0
    quality_bonus: int = 0
    capped_by_daily_limit: int = 0
    lines: list[tuple[str, int]] = field(default_factory=list)

    @property
    def total(self) -> int:
        raw = self.base + self.offhand_bonus + self.balance_bonus + self.quality_bonus
        return max(0, raw - self.capped_by_daily_limit)


def _diminished_reps(reps: int, drill: DrillSpec) -> float:
    """Effective rep count after within-session diminishing returns."""
    spec = drill.scoring
    capped = min(reps, spec.daily_rep_cap)
    if capped <= spec.diminishing_after_reps:
        return float(capped)
    excess = capped - spec.diminishing_after_reps
    return spec.diminishing_after_reps + excess * spec.diminishing_rate


# --------------------------------------------------------------------------
# The daily rep cap
# --------------------------------------------------------------------------
#
# The daily XP cap stops one day's XP from running away. It does nothing for
# the rep boards, badges, parent reports and roster rollups, which all sum
# `sessions.reps_total` -- so a half-hour of wall ball still put 1,800 reps on
# the team board next to teammates' 300. The fix is at the source: what the
# camera saw is kept as `reps_seen`, and `reps_total` becomes what counts
# toward the day, so every place that sums reps honours the cap without
# knowing it exists.
#
# The budget is per drill and per pool of same-work drills (see
# ScoringSpec.cap_pool), spent in submission order. The athlete sees both
# numbers and why they differ.

@dataclass(frozen=True)
class RepCredit:
    """What a session's reps count for, after the day's rep budget."""

    seen_total: int
    seen_left: int
    seen_right: int
    total: int
    left: int
    right: int
    cap: int                 # the budget that bound, if one did
    cap_scope: str | None    # 'drill' | 'pool' | None when nothing bound

    @property
    def capped(self) -> bool:
        return self.total < self.seen_total

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "seen": self.seen_total, "credited": self.total,
            "cap": self.cap, "scope": self.cap_scope,
        }


def pool_members(drill: DrillSpec, catalog: tuple[DrillSpec, ...]) -> tuple[DrillSpec, ...]:
    """Every drill sharing this drill's daily rep budget, itself included."""
    pool = drill.scoring.cap_pool
    if pool is None:
        return (drill,)
    return tuple(d for d in catalog if d.scoring.cap_pool == pool)


def pool_cap(drill: DrillSpec, catalog: tuple[DrillSpec, ...]) -> int:
    """The pool's daily budget: the largest cap among its members."""
    return max(d.scoring.daily_rep_cap for d in pool_members(drill, catalog))


# Catch-and-throw pace by age, in reps per minute, for a drill whose day is
# budgeted in minutes (ScoringSpec.daily_cap_minutes). Bands match
# benchmarks.AGE_BANDS. An unknown or estimated age takes the 11-12 figure,
# the same conservative default used everywhere else a child's age is unsure.
#
# These are coaching estimates of a steady wall-ball rhythm, not measurements:
# a ten-year-old at about a rep every two seconds, a high-schooler at one a
# second. To be checked against the club's own footage and adjusted here.
REPS_PER_MINUTE_BY_AGE: tuple[tuple[int, int], ...] = (
    (10, 30),    # under 11
    (12, 36),    # 11-12
    (14, 44),    # 13-14
    (16, 52),    # 15-16
    (18, 60),    # 17-18
    (200, 60),   # 19 and over
)
_DEFAULT_PACE = 36


def pace_for_age(age: int | None, estimated: bool = False) -> int:
    """Reps per minute a steady athlete of this age keeps up."""
    if age is None or estimated:
        return _DEFAULT_PACE
    for max_age, pace in REPS_PER_MINUTE_BY_AGE:
        if age <= max_age:
            return pace
    return REPS_PER_MINUTE_BY_AGE[-1][1]


#: The age an unknown or estimated birth year is treated as for an age table:
#: the top of the 11-12 band, the same conservative default as pace_for_age.
_DEFAULT_TABLE_AGE = 12


def age_ceiling(drill: DrillSpec, age: int | None, estimated: bool = False) -> int | None:
    """The age-table row for this athlete, or None when the drill has no table."""
    spec = drill.scoring
    if spec.daily_cap_by_age is None:
        return None
    a = _DEFAULT_TABLE_AGE if age is None or estimated else age
    for max_age, cap in spec.daily_cap_by_age:
        if a <= max_age:
            return min(spec.daily_rep_cap, cap)
    return min(spec.daily_rep_cap, spec.daily_cap_by_age[-1][1])


def daily_cap_for(
    drill: DrillSpec, age: int | None, estimated: bool = False, *, chosen: int | None = None,
) -> int:
    """This drill's daily rep budget for an athlete of this age.

    A drill budgeted in minutes gets minutes x pace. A drill with an age table
    gets its row -- or, when the program's director `chose` a number for it,
    that number, still never above the age row: the director picks the target
    and the age ceiling stays automatic. Neither ever exceeds the drill's own
    daily_rep_cap. Any other drill gets daily_rep_cap as before.
    """
    spec = drill.scoring
    ceiling = age_ceiling(drill, age, estimated)
    if ceiling is not None:
        return min(ceiling, chosen) if chosen and chosen > 0 else ceiling
    if spec.daily_cap_minutes is None:
        return spec.daily_rep_cap
    return min(spec.daily_rep_cap, int(round(spec.daily_cap_minutes * pace_for_age(age, estimated))))


def credit_reps(
    integrity: IntegrityResult,
    drill: DrillSpec,
    *,
    drill_reps_today: int,
    pool_reps_today: int,
    pool_budget: int,
    drill_cap: int | None = None,
) -> RepCredit:
    """How many of this session's reps count toward the day.

    `drill_reps_today` and `pool_reps_today` are reps already credited today
    on this drill and on its pool; both counts include this drill's reps, so
    the pool number is never smaller. `drill_cap` is the athlete's budget on
    this drill (daily_cap_for), defaulting to the spec's flat cap. Hands are
    scaled together so the weak-side share is unchanged by the cap -- a
    capped session is still as balanced as it was.
    """
    seen = integrity.reps_total
    cap_today = drill.scoring.daily_rep_cap if drill_cap is None else drill_cap
    drill_room = max(0, cap_today - drill_reps_today)
    pool_room = max(0, pool_budget - pool_reps_today)
    room = min(drill_room, pool_room)
    total = min(seen, room)
    if total >= seen:
        cap, scope = 0, None
    elif drill_room <= pool_room:
        cap, scope = cap_today, "drill"
    else:
        cap, scope = pool_budget, "pool"
    share = total / seen if seen else 0.0
    left = int(round(integrity.reps_left * share))
    right = int(round(integrity.reps_right * share))
    # Rounding can push the sides a rep over the total; take it from the
    # larger side, never below zero.
    if left + right > total:
        if left >= right:
            left -= (left + right) - total
        else:
            right -= (left + right) - total
    return RepCredit(
        seen_total=seen, seen_left=integrity.reps_left, seen_right=integrity.reps_right,
        total=total, left=max(0, left), right=max(0, right), cap=cap, cap_scope=scope,
    )


def score_session(
    drill: DrillSpec,
    integrity: IntegrityResult,
    *,
    hold_ms: int = 0,
    dominant_hand: str | None = "right",
    xp_already_today: int = 0,
    quality_score: int | None = None,
    config: ScoringConfig | None = None,
) -> XpBreakdown:
    """Compute XP for one submitted session.

    A session that failed integrity earns nothing; a session held for review
    earns nothing *yet* and is credited if a coach approves it.
    """
    cfg = config or CONFIG.scoring
    breakdown = XpBreakdown()

    if integrity.status != "counted":
        breakdown.lines.append((f"Session {integrity.status} -- no XP awarded", 0))
        return breakdown

    spec = drill.scoring

    if drill.metric is Metric.HOLD_SECONDS:
        minutes = hold_ms / 60_000.0
        breakdown.base = int(round(minutes * spec.xp_per_minute))
        breakdown.lines.append(
            (f"{minutes:.1f} min hold x {spec.xp_per_minute:g}/min", breakdown.base)
        )
    else:
        effective = _diminished_reps(integrity.reps_total, drill)
        breakdown.base = int(round(effective * spec.xp_per_rep))
        label = f"{integrity.reps_total} reps x {spec.xp_per_rep:g}"
        if effective < integrity.reps_total:
            label += f" (past {spec.diminishing_after_reps}, reduced rate)"
        breakdown.lines.append((label, breakdown.base))

    # Off-hand premium. `dominant_hand` comes from the athlete's profile, so a
    # left-handed player is credited for right-handed work and vice versa.
    if drill.tracks_handedness and dominant_hand in ("left", "right"):
        offhand_reps = (
            integrity.reps_left if dominant_hand == "right" else integrity.reps_right
        )
        if offhand_reps > 0:
            bonus_rate = spec.xp_per_rep * (cfg.offhand_bonus_multiplier - 1.0)
            # Diminishing returns apply proportionally to the off-hand share too,
            # otherwise the bonus becomes a loophole around the session cap.
            share = offhand_reps / max(1, integrity.reps_total)
            effective_offhand = _diminished_reps(integrity.reps_total, drill) * share
            breakdown.offhand_bonus = int(round(effective_offhand * bonus_rate))
            breakdown.lines.append(
                (f"Weak-side bonus ({offhand_reps} reps)", breakdown.offhand_bonus)
            )

        # Balance bonus: the weaker side carried a real share of the work.
        total_sided = integrity.reps_left + integrity.reps_right
        if total_sided >= 20:
            weaker = min(integrity.reps_left, integrity.reps_right)
            if weaker / total_sided >= cfg.balance_threshold:
                breakdown.balance_bonus = cfg.balance_bonus_xp
                breakdown.lines.append(
                    (
                        f"Balanced session ({weaker / total_sided:.0%} weak side)",
                        cfg.balance_bonus_xp,
                    )
                )

    # Form quality bonus. Strictly additive -- see ScoringConfig for why this
    # never subtracts.
    if quality_score is not None:
        earned = breakdown.base + breakdown.offhand_bonus
        if quality_score >= cfg.quality_excellent:
            breakdown.quality_bonus = int(round(earned * cfg.quality_excellent_bonus))
            breakdown.lines.append(
                (f"Excellent form ({quality_score}/100)", breakdown.quality_bonus)
            )
        elif quality_score >= cfg.quality_good:
            breakdown.quality_bonus = int(round(earned * cfg.quality_good_bonus))
            breakdown.lines.append(
                (f"Good form ({quality_score}/100)", breakdown.quality_bonus)
            )

    # Daily cap, applied last so the athlete sees what they would have earned.
    raw = (
        breakdown.base
        + breakdown.offhand_bonus
        + breakdown.balance_bonus
        + breakdown.quality_bonus
    )
    remaining = max(0, cfg.daily_xp_cap - xp_already_today)
    if raw > remaining:
        breakdown.capped_by_daily_limit = raw - remaining
        breakdown.lines.append(
            (
                f"Daily cap reached ({cfg.daily_xp_cap} XP/day)",
                -breakdown.capped_by_daily_limit,
            )
        )

    return breakdown


# --------------------------------------------------------------------------
# Streaks
# --------------------------------------------------------------------------

@dataclass
class StreakState:
    current: int
    longest: int
    last_active: date | None
    at_risk: bool  # a grace day is being spent right now


def compute_streak(
    active_days: list[date],
    today: date,
    config: ScoringConfig | None = None,
    paused: set[date] | None = None,
) -> StreakState:
    """Derive streak state from the sorted set of days the athlete trained.

    A gap of one day is forgiven (the streak holds but is flagged `at_risk`).
    A gap of two or more days breaks it.

    `paused` days -- a holiday, a tournament weekend -- are *removed from the
    timeline* rather than counted as training. The gap either side closes up
    and the athlete comes back to the streak they earned. Crediting them
    instead would turn a fortnight away into twenty-one days of streak, and a
    number that describes nothing the child did is one nobody protects.
    """
    cfg = config or CONFIG.scoring
    if not active_days:
        return StreakState(current=0, longest=0, last_active=None, at_risk=False)

    days = sorted(set(active_days))
    max_gap = cfg.streak_grace_days + 1
    paused = paused or set()

    def gap(earlier: date, later: date) -> int:
        """Days between two dates, not counting ones spent away."""
        span = (later - earlier).days
        if not paused or span <= 1:
            return span
        away = sum(
            1 for i in range(1, span)
            if (earlier + timedelta(days=i)) in paused
        )
        return span - away

    # Longest run anywhere in history.
    longest = run = 1
    for prev, cur in zip(days, days[1:]):
        if gap(prev, cur) <= max_gap:
            run += 1
            longest = max(longest, run)
        else:
            run = 1

    last = days[-1]
    since_last = gap(last, today)

    if since_last > max_gap:
        return StreakState(current=0, longest=longest, last_active=last, at_risk=False)

    # Walk backwards from the most recent active day.
    current = 1
    for prev, cur in zip(reversed(days[:-1]), reversed(days[1:])):
        if gap(prev, cur) <= max_gap:
            current += 1
        else:
            break

    return StreakState(
        current=current,
        longest=max(longest, current),
        last_active=last,
        # Never "at risk" on a day the athlete is down as away. The warning
        # exists to say *train today or lose it*, and telling a child that on
        # a family holiday is the exact nag this pause was built to stop.
        at_risk=since_last >= 1 and today not in paused,
    )


# --------------------------------------------------------------------------
# Badges
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class BadgeSpec:
    key: str
    name: str
    description: str
    tier: str  # 'bronze' | 'silver' | 'gold'


BADGES: tuple[BadgeSpec, ...] = (
    BadgeSpec("first_session", "First Rep", "Logged your first session.", "bronze"),
    # Counted on the athlete's own sport's skill drills, whatever those are.
    # These used to count lacrosse wall ball and nothing else, which made three
    # of the fourteen badges permanently unreachable for every other sport in
    # the library: a soccer player could see them and never earn one. The keys
    # are unchanged so awards already made stay awarded.
    BadgeSpec("wall_100", "Century", "100 lifetime reps on your sport's own drills.", "bronze"),
    BadgeSpec("wall_1000", "Four Digits", "1,000 lifetime reps on your sport's own drills.", "silver"),
    BadgeSpec("wall_10000", "Ten Thousand", "10,000 lifetime reps on your sport's own drills.", "gold"),
    BadgeSpec("streak_7", "Week Strong", "Trained 7 days in a row.", "bronze"),
    BadgeSpec("streak_30", "Month Strong", "Trained 30 days in a row.", "silver"),
    BadgeSpec("streak_100", "Relentless", "Trained 100 days in a row.", "gold"),
    BadgeSpec(
        "ambidextrous",
        "Both Hands",
        "Ten sessions where the {weaker} carried 40%+ of the reps.",
        "silver",
    ),
    BadgeSpec(
        "offhand_1000",
        "Weak Side No More",
        "1,000 lifetime {label} reps.",
        "gold",
    ),
    BadgeSpec("early_bird", "Before School", "Ten sessions completed before 8am.", "silver"),
    BadgeSpec("all_rounder", "Complete Player", "Logged 5 different drills.", "bronze"),
    BadgeSpec("level_10", "Double Digits", "Reached level 10.", "silver"),
    BadgeSpec("level_25", "Elite", "Reached level 25.", "gold"),
)

BADGES_BY_KEY = {b.key: b for b in BADGES}


@dataclass
class AthleteStats:
    """Everything the badge rules need, gathered once."""

    total_xp: int = 0
    session_count: int = 0
    skill_reps: int = 0
    offhand_reps: int = 0
    balanced_sessions: int = 0
    early_sessions: int = 0
    distinct_drills: int = 0
    current_streak: int = 0
    longest_streak: int = 0


def earned_badges(stats: AthleteStats) -> list[str]:
    """Badge keys the athlete currently qualifies for.

    Pure and idempotent: callers diff this against what is already stored and
    award the difference, so re-running it never double-awards.
    """
    level = level_for_xp(stats.total_xp)
    checks: list[tuple[str, bool]] = [
        ("first_session", stats.session_count >= 1),
        ("wall_100", stats.skill_reps >= 100),
        ("wall_1000", stats.skill_reps >= 1_000),
        ("wall_10000", stats.skill_reps >= 10_000),
        ("streak_7", stats.longest_streak >= 7),
        ("streak_30", stats.longest_streak >= 30),
        ("streak_100", stats.longest_streak >= 100),
        ("ambidextrous", stats.balanced_sessions >= 10),
        ("offhand_1000", stats.offhand_reps >= 1_000),
        ("early_bird", stats.early_sessions >= 10),
        ("all_rounder", stats.distinct_drills >= 5),
        ("level_10", level >= 10),
        ("level_25", level >= 25),
    ]
    return [key for key, ok in checks if ok]
