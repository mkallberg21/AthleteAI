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
                (f"Off-hand bonus ({offhand_reps} reps)", breakdown.offhand_bonus)
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
) -> StreakState:
    """Derive streak state from the sorted set of days the athlete trained.

    A gap of one day is forgiven (the streak holds but is flagged `at_risk`).
    A gap of two or more days breaks it.
    """
    cfg = config or CONFIG.scoring
    if not active_days:
        return StreakState(current=0, longest=0, last_active=None, at_risk=False)

    days = sorted(set(active_days))
    max_gap = cfg.streak_grace_days + 1

    # Longest run anywhere in history.
    longest = run = 1
    for prev, cur in zip(days, days[1:]):
        if (cur - prev).days <= max_gap:
            run += 1
            longest = max(longest, run)
        else:
            run = 1

    last = days[-1]
    since_last = (today - last).days

    if since_last > max_gap:
        return StreakState(current=0, longest=longest, last_active=last, at_risk=False)

    # Walk backwards from the most recent active day.
    current = 1
    for prev, cur in zip(reversed(days[:-1]), reversed(days[1:])):
        if (cur - prev).days <= max_gap:
            current += 1
        else:
            break

    return StreakState(
        current=current,
        longest=max(longest, current),
        last_active=last,
        at_risk=since_last >= 1,
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
    BadgeSpec("wall_100", "Century", "100 lifetime wall ball reps.", "bronze"),
    BadgeSpec("wall_1000", "Four Digits", "1,000 lifetime wall ball reps.", "silver"),
    BadgeSpec("wall_10000", "Ten Thousand", "10,000 lifetime wall ball reps.", "gold"),
    BadgeSpec("streak_7", "Week Strong", "Trained 7 days in a row.", "bronze"),
    BadgeSpec("streak_30", "Month Strong", "Trained 30 days in a row.", "silver"),
    BadgeSpec("streak_100", "Relentless", "Trained 100 days in a row.", "gold"),
    BadgeSpec(
        "ambidextrous",
        "Both Hands",
        "Ten sessions where the weak hand carried 40%+ of the reps.",
        "silver",
    ),
    BadgeSpec(
        "offhand_1000",
        "Weak Side No More",
        "1,000 lifetime off-hand reps.",
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
    wall_ball_reps: int = 0
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
        ("wall_100", stats.wall_ball_reps >= 100),
        ("wall_1000", stats.wall_ball_reps >= 1_000),
        ("wall_10000", stats.wall_ball_reps >= 10_000),
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
