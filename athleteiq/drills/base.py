"""Declarative drill specifications.

The whole point of this module is that adding a new exercise is a *data* change,
not a code change. A drill declares:

  * which one-dimensional signal to derive from the pose landmarks,
  * the hysteresis thresholds that turn that signal into rep counts,
  * how the rep is scored,
  * what makes a submitted session plausible.

The same spec is consumed twice: the browser uses it to count reps on-device,
and the server uses it to re-validate whatever the browser claims. Both read the
identical JSON, so the two can never drift apart.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Metric(str, Enum):
    """What the drill fundamentally measures."""

    REPS = "reps"          # wall ball, push-ups, squats
    HOLD_SECONDS = "hold"  # plank, wall sit
    DURATION = "duration"  # jog, jump rope -- time under work


class Category(str, Enum):
    SKILL = "skill"
    STRENGTH = "strength"
    SPEED = "speed"
    AGILITY = "agility"
    CONDITIONING = "conditioning"


class SignalKind(str, Enum):
    """How to collapse 33 pose landmarks into one number per frame."""

    # Interior angle at `joints[1]`, formed by joints[0]-joints[1]-joints[2].
    # Degrees. Used for push-ups (elbow), squats (knee), etc.
    JOINT_ANGLE = "joint_angle"

    # Vertical offset of `landmark` above `reference`, normalized by torso
    # length so it is scale- and distance-invariant. Positive means higher.
    RELATIVE_HEIGHT = "relative_height"

    # Signed vertical position of the athlete's hip midpoint, normalized by
    # torso length. Used for jumps and general body-height drills.
    BODY_HEIGHT = "body_height"

    # Purpose-built lacrosse wall-ball cycle detector. Tracks the top hand on
    # the stick through cock -> release -> catch. Needs bespoke logic because
    # a single threshold crossing cannot distinguish a throw from a catch.
    WALL_BALL_CYCLE = "wall_ball_cycle"


# MediaPipe Pose landmark names, indexed as the model emits them. Kept here so
# drill specs reference readable names and the client maps them to indices.
LANDMARKS = (
    "nose", "left_eye_inner", "left_eye", "left_eye_outer", "right_eye_inner",
    "right_eye", "right_eye_outer", "left_ear", "right_ear", "mouth_left",
    "mouth_right", "left_shoulder", "right_shoulder", "left_elbow",
    "right_elbow", "left_wrist", "right_wrist", "left_pinky", "right_pinky",
    "left_index", "right_index", "left_thumb", "right_thumb", "left_hip",
    "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle",
    "left_heel", "right_heel", "left_foot_index", "right_foot_index",
)


@dataclass(frozen=True)
class SignalSpec:
    kind: SignalKind
    joints: tuple[str, ...] = ()
    landmark: str | None = None
    reference: str | None = None

    # Exponential smoothing applied to the raw signal before thresholding.
    # Pose landmarks are jittery; without this every drill double-counts.
    smoothing: float = 0.35

    def __post_init__(self) -> None:
        if self.kind is SignalKind.JOINT_ANGLE and len(self.joints) != 3:
            raise ValueError(
                f"joint_angle needs exactly 3 joints, got {len(self.joints)}"
            )
        if self.kind is SignalKind.RELATIVE_HEIGHT and not (
            self.landmark and self.reference
        ):
            raise ValueError("relative_height needs both landmark and reference")
        for name in (*self.joints, self.landmark, self.reference):
            if name is not None and name not in LANDMARKS:
                raise ValueError(f"unknown pose landmark: {name!r}")


@dataclass(frozen=True)
class CounterSpec:
    """Turns the signal into reps via a two-threshold state machine.

    Hysteresis (two thresholds rather than one) is what stops a signal hovering
    at the boundary from spraying dozens of phantom reps.
    """

    # The signal must fall to/below this to arm a rep...
    down_threshold: float
    # ...and then rise to/above this to complete it.
    up_threshold: float

    # Refractory period. Nobody does a legitimate push-up in 250ms.
    min_rep_ms: int = 400

    # A rep taking longer than this is a pause, not a rep, and resets state.
    max_rep_ms: int = 10_000

    # True when the signal *rises* to complete a rep (push-up: elbow angle
    # bottoms out, then extends). False inverts the machine.
    rising_completes: bool = True

    def __post_init__(self) -> None:
        if self.down_threshold >= self.up_threshold:
            raise ValueError(
                "down_threshold must be below up_threshold for hysteresis to "
                f"work (got {self.down_threshold} >= {self.up_threshold})"
            )
        if self.min_rep_ms >= self.max_rep_ms:
            raise ValueError("min_rep_ms must be below max_rep_ms")


@dataclass(frozen=True)
class ScoringSpec:
    xp_per_rep: float = 1.0
    xp_per_minute: float = 0.0

    # Per-drill share of the global daily cap, so one drill cannot eat an
    # athlete's whole day.
    daily_rep_cap: int = 1_000

    # Reps beyond this in a single session earn XP at a reduced rate. Rewards
    # showing up daily over one heroic Sunday.
    diminishing_after_reps: int = 300
    diminishing_rate: float = 0.35


@dataclass(frozen=True)
class QualitySpec:
    """What a *well executed* rep of this drill looks like.

    Counting reps is the easy half of the pose data. This is the half a coach
    cannot get from a stopwatch: whether the reps were any good, whether they
    stayed good, and whether the weak side looks like the strong one.

    Every threshold is expressed in the same units as the drill's signal, so a
    degree-based drill and a torso-normalized one both work without special
    cases.
    """

    # Range of motion a fully-executed rep produces. A half rep reads as a
    # fraction of this.
    target_rom: float

    # Rep-to-rep variability of that range. Below `consistency_target` the
    # movement is repeatable; at or above `consistency_ceiling` it is erratic.
    # Between them the score slides linearly.
    consistency_target: float = 0.14
    consistency_ceiling: float = 0.45

    # Controlled tempo band, in milliseconds per rep.
    tempo_min_ms: int = 500
    tempo_max_ms: int = 3_000

    # Component weights. Validated to sum to 1 so a drill cannot silently
    # under- or over-count part of its own score.
    w_consistency: float = 0.35
    w_depth: float = 0.35
    w_tempo: float = 0.10
    w_endurance: float = 0.20

    # Below this many reps there is not enough signal to say anything
    # trustworthy, and a confident-looking score from six reps is worse than
    # no score at all.
    min_reps: int = 8

    def __post_init__(self) -> None:
        if self.target_rom <= 0:
            raise ValueError("target_rom must be positive")
        if self.consistency_target >= self.consistency_ceiling:
            raise ValueError("consistency_target must be below consistency_ceiling")
        if self.tempo_min_ms >= self.tempo_max_ms:
            raise ValueError("tempo_min_ms must be below tempo_max_ms")
        total = self.w_consistency + self.w_depth + self.w_tempo + self.w_endurance
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"quality weights must sum to 1.0, got {total}")


@dataclass(frozen=True)
class ValidationSpec:
    """Plausibility envelope, enforced server-side."""

    # Reps per second. A wall-ball rep faster than ~3/s is not physically
    # possible with a real ball and stick.
    max_reps_per_second: float = 3.0
    min_reps_per_second: float = 0.02

    min_reps: int = 5
    min_duration_ms: int = 10_000


@dataclass(frozen=True)
class DrillSpec:
    key: str
    name: str
    sport: str
    category: Category
    metric: Metric
    description: str
    signal: SignalSpec
    counter: CounterSpec
    scoring: ScoringSpec = field(default_factory=ScoringSpec)
    validation: ValidationSpec = field(default_factory=ValidationSpec)
    # Absent for drills where per-rep form cannot be read from pose alone.
    quality: QualitySpec | None = None

    # Whether left/right attribution is meaningful. True for wall ball and
    # single-arm lifts; false for squats.
    tracks_handedness: bool = False

    # Short coaching cue shown on the capture screen while recording.
    setup_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form, shipped verbatim to the browser."""
        data = asdict(self)
        data["category"] = self.category.value
        data["metric"] = self.metric.value
        data["signal"]["kind"] = self.signal.kind.value
        data["signal"]["joints"] = list(self.signal.joints)
        return data

    @property
    def scores_quality(self) -> bool:
        return self.quality is not None
