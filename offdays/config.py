"""Central configuration for 0FFDAYS.

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
    daily_xp_cap: int = _env_int("OFFDAYS_DAILY_XP_CAP", 600)

    # A session must clear this to count toward a streak day.
    streak_min_xp: int = 25

    # Grace period: missing a single day does not reset a streak, it freezes
    # it. Two consecutive missed days breaks it. Young athletes have games,
    # travel, and school -- an all-or-nothing streak punishes the wrong thing.
    streak_grace_days: int = 1

    # Off-hand work is the single highest-leverage habit in lacrosse and the
    # thing athletes avoid most, so it is paid at a premium.
    #
    # 2.4 rather than the 1.5 this used to be, and the change is a restoration
    # rather than an inflation. The old top rate for an off-hand rep was 2.4 --
    # but it was reached as 1.6 base on a drill called "Off Hand" times this
    # 1.5, and that 1.6 base was paid on every rep of that drill whether the
    # weak hand was on top or not. The app cannot see which wall-ball pattern
    # was chosen, so the base rates were levelled; had this stayed at 1.5 the
    # levelling would have quietly halved the premium on the one habit the
    # product most wants to buy.
    #
    # Moving the whole premium here makes it strictly better targeted. It is
    # paid per rep on the hand actually detected on top, which is measured
    # rather than selected from a menu, so it now lands on off-hand reps
    # wherever they happen instead of only inside one drill -- and it lands on
    # none of the strong-hand reps that used to collect it by association.
    #
    # The daily XP cap bounds the total either way, so this changes what a day
    # rewards rather than how much a day can earn.
    offhand_bonus_multiplier: float = 2.4

    # Balanced-session bonus: awarded when the weaker hand carries at least
    # this share of the session's reps.
    balance_threshold: float = 0.40
    balance_bonus_xp: int = 40

    # Level curve: total XP needed to reach level N is
    # level_base * (N - 1) ** level_exponent, so level 1 starts at zero.
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
class LoadConfig:
    """Overuse-protection thresholds.

    The acute:chronic ratio is a heuristic, not settled science -- the
    rolling-average form used here has been criticised on methodological
    grounds. These numbers exist to raise a question with a coach, never to
    diagnose an athlete or block them from training.
    """

    acute_days: int = 7
    chronic_days: int = 28

    # Below this much history the ratio compares a week against almost nothing
    # and produces alarming numbers for an athlete who simply just started.
    min_history_days: int = 14

    detraining_below: float = 0.60
    optimal_low: float = 0.80
    optimal_high: float = 1.30
    elevated_high: float = 1.50

    # Consecutive training days before a rest day is suggested, and before the
    # suggestion is escalated.
    rest_day_after: int = 6
    rest_day_urgent: int = 10

    # Week-on-week throwing increase worth flagging, and the baseline below
    # which a percentage change is just noise.
    throw_spike_change: float = 0.50
    throw_trend_min_baseline: int = 150

    # Mean daily load divided by its spread. High values mean no hard/easy
    # variation at all.
    monotony_threshold: float = 2.0
    # Reported when every day carries identical load, where the usual formula
    # would divide by zero.
    monotony_ceiling: float = 99.0

    # Rough hours per logged session, used only for the age-based guideline.
    # Crude on purpose: the app cannot see how long a driveway session really
    # ran, and the advisory says so.
    assumed_session_hours: float = 0.4
    age_hours_warn_fraction: float = 0.7

    # A recovery day still counts toward a streak when the athlete is carrying
    # high load. Without this the streak mechanic actively punishes resting,
    # which makes the gamification a risk factor rather than a motivator.
    recovery_day_protects_streak: bool = True
    # Consecutive training days before a recovery day can be claimed. Without a
    # floor this is just a button that keeps a streak alive without training.
    recovery_min_streak: int = 3


@dataclass(frozen=True)
class Config:
    db_path: Path = field(
        default_factory=lambda: Path(
            os.environ.get("OFFDAYS_DB_PATH", _BASE.parent / "data" / "offdays.db")
        )
    )
    static_dir: Path = field(default_factory=lambda: _BASE / "web" / "static")

    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    integrity: IntegrityConfig = field(default_factory=IntegrityConfig)
    load: LoadConfig = field(default_factory=LoadConfig)

    # Retention for per-rep timing rows. The aggregate session record is kept
    # indefinitely; the granular event stream is only needed for integrity
    # review and is pruned after this window.
    rep_event_retention_days: int = _env_int("OFFDAYS_REP_RETENTION_DAYS", 45)

    # Minimum age handling. Athletes at or under this age require a recorded
    # guardian consent before their name appears on any shared leaderboard.
    minor_age_ceiling: int = 17

    # Multiplier on the published age-appropriate training budgets. A program
    # can raise or lower them, but has to choose to -- the app never quietly
    # assumes an athlete can take more than the guidance suggests.
    budget_scale: float = field(
        default_factory=lambda: float(os.environ.get("OFFDAYS_BUDGET_SCALE", "1") or 1)
    )

    # When true, a coach with no team assignments sees nothing rather than the
    # whole program. Off by default so accounts created before team assignment
    # existed keep working on upgrade; new deployments should turn it on.
    strict_team_scope: bool = field(
        default_factory=lambda: os.environ.get("OFFDAYS_STRICT_TEAM_SCOPE", "") == "1"
    )

    # Web Push (VAPID). Absent these, notifications still generate and appear
    # in the in-app feed -- only the phone-level push is skipped, so nothing
    # about the product depends on a third-party service being configured.
    vapid_public_key: str = field(
        default_factory=lambda: os.environ.get("OFFDAYS_VAPID_PUBLIC_KEY", "")
    )
    vapid_private_key: str = field(
        default_factory=lambda: os.environ.get("OFFDAYS_VAPID_PRIVATE_KEY", "")
    )
    vapid_email: str = field(
        default_factory=lambda: os.environ.get("OFFDAYS_VAPID_EMAIL", "coach@example.com")
    )

    # SMTP for the weekly digest. Absent these the digest is still computed and
    # readable in the app -- only the send is skipped, so nothing about the
    # feature depends on a mail provider being configured.
    smtp_host: str = field(default_factory=lambda: os.environ.get("OFFDAYS_SMTP_HOST", ""))
    smtp_port: int = field(
        default_factory=lambda: _env_int("OFFDAYS_SMTP_PORT", 587)
    )
    smtp_user: str = field(default_factory=lambda: os.environ.get("OFFDAYS_SMTP_USER", ""))
    smtp_password: str = field(
        default_factory=lambda: os.environ.get("OFFDAYS_SMTP_PASSWORD", "")
    )
    smtp_from: str = field(
        default_factory=lambda: os.environ.get("OFFDAYS_SMTP_FROM", "0FFDAYS <no-reply@example.com>")
    )
    # Base URL used for the dashboard link inside the email.
    app_base_url: str = field(
        default_factory=lambda: os.environ.get("OFFDAYS_BASE_URL", "")
    )
    # Signs unsubscribe links. Unset means links are forgeable, not broken --
    # a development default rather than a production one.
    secret_key: str = field(default_factory=lambda: os.environ.get("OFFDAYS_SECRET", ""))

    # Per-provider webhook secrets. An empty secret means that provider's
    # endpoint is disabled -- absent configuration must never mean "trust
    # anything", since this endpoint takes instructions from the public
    # internet about whose mail to stop.
    # SNS topics whose messages will be accepted. A valid AWS signature only
    # proves the sender has an AWS account -- anyone can create a topic and
    # have Amazon sign for it legitimately -- so this allowlist is what makes
    # SES verification mean anything. Empty disables the endpoint.
    sns_topic_arns: tuple = field(
        default_factory=lambda: tuple(
            arn.strip()
            for arn in os.environ.get("OFFDAYS_SNS_TOPIC_ARNS", "").split(",")
            if arn.strip()
        )
    )
    # Chain validation for SNS signing certificates. On by default: without it
    # the only thing establishing the certificate's provenance is the TLS
    # connection it arrived over.
    sns_verify_chain: bool = field(
        default_factory=lambda: os.environ.get("OFFDAYS_SNS_VERIFY_CHAIN", "1") != "0"
    )
    # Optional PEM bundle of trust anchors. Empty reads the system store.
    sns_ca_bundle: str = field(
        default_factory=lambda: os.environ.get("OFFDAYS_SNS_CA_BUNDLE", "")
    )
    # Check the signing certificate against OCSP, falling back to a CRL.
    # Answers are cached for an hour, so this is roughly one network round trip
    # per hour rather than one per webhook.
    sns_check_revocation: bool = field(
        default_factory=lambda: os.environ.get("OFFDAYS_SNS_CHECK_REVOCATION", "1") != "0"
    )
    # What to do when revocation cannot be established. Soft-fail by default:
    # a responder outage should not stop bounce processing, and the primary
    # controls -- allowlisted topic, pinned chain -- do not depend on this one.
    # Set to 1 to refuse anything that cannot be cleared.
    sns_revocation_strict: bool = field(
        default_factory=lambda: os.environ.get("OFFDAYS_SNS_REVOCATION_STRICT", "") == "1"
    )

    # Restrict anchors to Amazon's roots rather than every CA on the machine.
    # A host trusts ~150 roots; trusting all of them to vouch for an AWS
    # signing certificate makes the pinning pointless.
    sns_pin_amazon_roots: bool = field(
        default_factory=lambda: os.environ.get("OFFDAYS_SNS_PIN_AMAZON", "1") != "0"
    )

    # Whether to auto-confirm an SNS subscription for an allowlisted topic.
    sns_auto_confirm: bool = field(
        default_factory=lambda: os.environ.get("OFFDAYS_SNS_AUTO_CONFIRM", "1") != "0"
    )

    webhook_secrets: dict = field(
        default_factory=lambda: {
            provider: os.environ.get(f"OFFDAYS_WEBHOOK_SECRET_{provider.upper()}", "")
            for provider in ("sendgrid", "postmark", "mailgun", "ses", "generic")
        }
    )

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host)


CONFIG = Config()
