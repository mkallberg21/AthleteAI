"""Server-side plausibility checking for submitted sessions.

The counting happens in the athlete's browser, which means the athlete controls
it. Anyone willing to open developer tools can post any number they like. This
module is the counterweight: it treats every submission as a claim and scores
how much that claim looks like a real human doing a real drill.

It deliberately does *not* try to be a fraud oracle. It produces a score and a
set of human-readable notes, and borderline sessions land in a coach review
queue rather than being silently thrown away. A false accusation against a
14-year-old who actually did the work is far more damaging than a few inflated
reps reaching a leaderboard.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .config import CONFIG, IntegrityConfig
from .drills import DrillSpec, Metric


@dataclass
class RepEvent:
    """One detected rep, as reported by the client."""

    t_ms: int
    hand: str = "none"       # 'left' | 'right' | 'none'
    confidence: float = 0.0  # mean pose landmark visibility over the rep


@dataclass
class SessionClaim:
    """What the client says happened."""

    drill_key: str
    duration_ms: int
    reps: list[RepEvent] = field(default_factory=list)
    hold_ms: int = 0
    mean_confidence: float = 0.0
    client_version: str = ""


@dataclass
class IntegrityResult:
    score: float                     # 0.0 (implausible) .. 1.0 (clean)
    status: str                      # 'counted' | 'review' | 'rejected'
    notes: list[str] = field(default_factory=list)
    cadence_cv: float = 0.0
    reps_total: int = 0
    reps_left: int = 0
    reps_right: int = 0

    @property
    def counts(self) -> bool:
        return self.status == "counted"


def _cadence_cv(reps: list[RepEvent]) -> float:
    """Coefficient of variation of rep-to-rep intervals.

    Real athletes are irregular. A perfectly even interval stream is the
    signature of a generated payload, and a wildly uneven one is the signature
    of a detector firing on noise. Both are worth flagging, in opposite
    directions.
    """
    if len(reps) < 3:
        return 0.0
    gaps = [
        b.t_ms - a.t_ms
        for a, b in zip(reps, reps[1:])
        if b.t_ms > a.t_ms
    ]
    if len(gaps) < 2:
        return 0.0
    mean = statistics.fmean(gaps)
    if mean <= 0:
        return 0.0
    return statistics.pstdev(gaps) / mean


def evaluate(
    claim: SessionClaim,
    drill: DrillSpec,
    config: IntegrityConfig | None = None,
) -> IntegrityResult:
    """Score a submitted session for plausibility.

    Returns an `IntegrityResult`. Penalties are additive against a starting
    score of 1.0, and each one carries a note explaining itself so a coach
    reviewing the queue sees *why* something was held.
    """
    cfg = config or CONFIG.integrity
    notes: list[str] = []
    score = 1.0

    reps = sorted(claim.reps, key=lambda r: r.t_ms)
    reps_total = len(reps)
    reps_left = sum(1 for r in reps if r.hand == "left")
    reps_right = sum(1 for r in reps if r.hand == "right")
    cv = _cadence_cv(reps)

    result = IntegrityResult(
        score=0.0,
        status="rejected",
        notes=notes,
        cadence_cv=cv,
        reps_total=reps_total,
        reps_left=reps_left,
        reps_right=reps_right,
    )

    # --- Structural checks: these are contradictions, not judgment calls. ---

    if claim.duration_ms <= 0:
        notes.append("Session reported a non-positive duration.")
        return result

    if any(r.t_ms < 0 for r in reps):
        notes.append("Session contained reps at negative timestamps.")
        return result

    # A rep timestamped after the session ended cannot have happened. Allow a
    # small tolerance for the gap between the last rep and the stop tap.
    overrun = [r for r in reps if r.t_ms > claim.duration_ms + 2_000]
    if overrun:
        notes.append(
            f"{len(overrun)} rep(s) timestamped after the session ended."
        )
        return result

    # --- Envelope checks: real but recoverable problems. ---

    if claim.duration_ms < max(cfg.min_duration_ms, drill.validation.min_duration_ms):
        notes.append(
            f"Session lasted {claim.duration_ms / 1000:.0f}s, below the "
            f"{drill.validation.min_duration_ms / 1000:.0f}s minimum for "
            f"{drill.name}."
        )
        score -= 0.50

    if claim.duration_ms > cfg.max_duration_ms:
        notes.append(
            f"Session ran {claim.duration_ms / 60000:.0f} minutes, past the "
            f"{cfg.max_duration_ms / 60000:.0f}-minute ceiling -- likely a "
            "timer left running."
        )
        score -= 0.35

    seconds = claim.duration_ms / 1000.0

    if drill.metric is Metric.REPS:
        if reps_total < drill.validation.min_reps:
            notes.append(
                f"Only {reps_total} rep(s) detected; {drill.name} needs at "
                f"least {drill.validation.min_reps} to count."
            )
            score -= 0.45

        rate = reps_total / seconds if seconds > 0 else 0.0
        if rate > drill.validation.max_reps_per_second:
            notes.append(
                f"{rate:.1f} reps/sec exceeds the physical ceiling of "
                f"{drill.validation.max_reps_per_second:.1f} for {drill.name}."
            )
            score -= 0.60
        elif rate < drill.validation.min_reps_per_second and reps_total > 0:
            notes.append(
                f"{rate:.2f} reps/sec is unusually slow for {drill.name}; the "
                "detector may have missed reps."
            )
            score -= 0.15

        # Cadence regularity, only meaningful with enough reps to measure.
        if reps_total >= 8:
            if cv < cfg.min_cadence_cv:
                notes.append(
                    f"Rep timing is near-perfectly even (variation {cv:.3f}), "
                    "which real movement rarely is."
                )
                score -= 0.55
            elif cv > cfg.max_cadence_cv:
                notes.append(
                    f"Rep timing is highly erratic (variation {cv:.2f}); this "
                    "often means the detector fired on background motion."
                )
                score -= 0.25

    elif drill.metric is Metric.HOLD_SECONDS:
        if claim.hold_ms > claim.duration_ms + 2_000:
            notes.append("Reported hold time exceeds the session length.")
            return result
        if claim.hold_ms < drill.validation.min_duration_ms:
            notes.append(
                f"Hold of {claim.hold_ms / 1000:.0f}s is below the "
                f"{drill.validation.min_duration_ms / 1000:.0f}s minimum."
            )
            score -= 0.40

    # --- Pose quality ---

    if claim.mean_confidence < cfg.min_mean_confidence:
        notes.append(
            f"Average pose confidence {claim.mean_confidence:.2f} is below "
            f"{cfg.min_mean_confidence:.2f} -- framing or lighting likely cut "
            "the athlete out of frame."
        )
        # Steep on purpose. Confidence is the share of the drill's required
        # landmarks the model could actually see, so counts derived from a
        # low-confidence session are not merely noisier -- they are unreliable.
        # A shallow penalty here lets genuinely unusable sessions onto the
        # leaderboard, which is worse than making an athlete refilm.
        #   0.50 -> counted, 0.45 -> counted (marginal), 0.40 and below -> review
        deficit = cfg.min_mean_confidence - claim.mean_confidence
        score -= min(cfg.max_confidence_penalty, deficit * cfg.confidence_penalty_slope)

    # --- Handedness consistency ---

    if drill.tracks_handedness and reps_total > 0:
        attributed = reps_left + reps_right
        unattributed = reps_total - attributed
        if unattributed / reps_total > 0.35:
            notes.append(
                f"{unattributed} of {reps_total} reps could not be attributed "
                "to a side; the athlete may be out of frame."
            )
            score -= 0.20

    score = max(0.0, min(1.0, score))
    result.score = score

    if score <= cfg.reject_threshold:
        result.status = "rejected"
    elif score <= cfg.review_threshold:
        result.status = "review"
    else:
        result.status = "counted"
        if not notes:
            notes.append("No integrity concerns.")

    return result
