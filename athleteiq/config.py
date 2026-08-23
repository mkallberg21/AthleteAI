"""Central configuration for AthleteIQ.

Everything tunable lives here so drills, scoring curves, and integrity limits
can be adjusted without hunting through the codebase.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_BASE = Path(__file__).resolve().parent


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True)
class ScoringConfig:
    """Gamification tuning."""

    # Hard ceiling on XP a single athlete can bank in one day. Without this,
    # the leaderboard rewards whoever has the most free time rather than
    # whoever is training well, and it invites grinding injuries.
    daily_xp_cap: int = _env_int("ATHLETEIQ_DAILY_XP_CAP", 600)

    # A session must clear this to count toward a streak day.
    streak_min_xp: int = 25

    # Grace period: missing a single day does not reset a streak, it freezes
    # it. Two consecutive missed days breaks it. Young athletes have games,
    # travel, and school -- an all-or-nothing streak punishes the wrong thing.
    streak_grace_days: int = 1

    # Off-hand work is the single highest-leverage habit in lacrosse and the
    # thing athletes avoid most, so it is paid at a premium.
    offhand_bonus_multiplier: float = 1.5

    # Balanced-session bonus: awarded when the weaker hand carries at least
    # this share of the session's reps.
    balance_threshold: float = 0.40
    balance_bonus_xp: int = 40

    # Level curve: XP needed for level N is level_base * N ** level_exponent.
    level_base: int = 300
    level_exponent: float = 1.45

    # Form quality pays a bonus and never a penalty.
    #
    # Docking XP for poor form would punish hardest exactly the athlete who
    # most needs to improve, and a 13-year-old who loses points for a bad rep
    # stops filming. Rewarding good form points at the same behaviour without
    # taking anything away from anyone.
    quality_good: int = 70
    quality_excellent: int = 85
    quality_good_bonus: float = 0.08
    quality_excellent_bonus: float = 0.15


@dataclass(frozen=True)
class IntegrityConfig:
    """Anti-cheat / plausibility limits applied server-side.

    The client is untrusted. It can be modified by any athlete willing to open
    developer tools, so every number it reports is re-checked here.
    """

    # Pose landmark confidence below this starts costing the session score.
    min_mean_confidence: float = 0.55

    # How hard a confidence shortfall is punished, and the ceiling on that
    # penalty. Tuned so a marginal session (0.45) still counts but a genuinely
    # unusable one (0.40 or below) is held for a coach to look at.
    confidence_penalty_slope: float = 4.0
    max_confidence_penalty: float = 0.65

    # Sessions shorter than this are almost always accidental taps.
    min_duration_ms: int = 10_000

    # A single session longer than this is either a forgotten timer or a
    # phone left propped against a wall.
    max_duration_ms: int = 45 * 60 * 1000

    # Coefficient of variation of rep-to-rep intervals. A human throwing a
    # ball against a wall has natural jitter; a scripted event stream is
    # suspiciously metronomic.
    min_cadence_cv: float = 0.03

    # Above this, the "reps" are more likely to be detector noise than a
    # consistent drill.
    max_cadence_cv: float = 1.10

    # Same idea applied to the shape of each rep. Identical range of motion on
    # every rep is a generated payload, not an athlete -- and it matters more
    # than it used to, since these values drive the form score.
    min_rom_cv: float = 0.012

    # Sessions scoring at or below this are held for coach review instead of
    # silently hitting the leaderboard.
    review_threshold: float = 0.55

    # Sessions at or below this earn no XP at all.
    reject_threshold: float = 0.30


@dataclass(frozen=True)
class Config:
    db_path: Path = field(
        default_factory=lambda: Path(
            os.environ.get("ATHLETEIQ_DB_PATH", _BASE.parent / "data" / "athleteiq.db")
        )
    )
    static_dir: Path = field(default_factory=lambda: _BASE / "web" / "static")

    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    integrity: IntegrityConfig = field(default_factory=IntegrityConfig)

    # Retention for per-rep timing rows. The aggregate session record is kept
    # indefinitely; the granular event stream is only needed for integrity
    # review and is pruned after this window.
    rep_event_retention_days: int = _env_int("ATHLETEIQ_REP_RETENTION_DAYS", 45)

    # Minimum age handling. Athletes at or under this age require a recorded
    # guardian consent before their name appears on any shared leaderboard.
    minor_age_ceiling: int = 17

    # Web Push (VAPID). Absent these, notifications still generate and appear
    # in the in-app feed -- only the phone-level push is skipped, so nothing
    # about the product depends on a third-party service being configured.
    vapid_public_key: str = field(
        default_factory=lambda: os.environ.get("ATHLETEIQ_VAPID_PUBLIC_KEY", "")
    )
    vapid_private_key: str = field(
        default_factory=lambda: os.environ.get("ATHLETEIQ_VAPID_PRIVATE_KEY", "")
    )
    vapid_email: str = field(
        default_factory=lambda: os.environ.get("ATHLETEIQ_VAPID_EMAIL", "coach@example.com")
    )


CONFIG = Config()
