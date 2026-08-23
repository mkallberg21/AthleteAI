"""The drill catalog.

Adding an exercise means appending a `DrillSpec` here. Nothing else in the
codebase needs to change: the API serves it, the browser counts it, the scorer
scores it, and the leaderboard ranks it.

Threshold values are starting points calibrated against typical phone framing
(athlete 6-12 feet from the camera, full body in frame). They are the numbers
most worth revisiting once real footage exists.

`target_rom` on each QualitySpec is *measured*, not guessed: the calibration
harness drives the counter with a synthetic textbook rep and records the range
of motion it actually reports. That figure is lower than the movement's true
excursion, because a rep is finalized when the next one arms, so a theoretical
value would mark every honest rep short.
"""

from __future__ import annotations

from .base import (
    Category,
    CounterSpec,
    DrillSpec,
    Metric,
    QualitySpec,
    ScoringSpec,
    SignalKind,
    SignalSpec,
    ValidationSpec,
)

# --------------------------------------------------------------------------
# Lacrosse
# --------------------------------------------------------------------------

WALL_BALL = DrillSpec(
    key="lax_wall_ball",
    name="Wall Ball",
    sport="lacrosse",
    category=Category.SKILL,
    metric=Metric.REPS,
    description=(
        "Throw and catch against a wall. Counts each throw-catch cycle and "
        "attributes it to the hand on top of the stick, so off-hand work is "
        "credited separately."
    ),
    signal=SignalSpec(
        kind=SignalKind.WALL_BALL_CYCLE,
        # The cycle detector reads both wrists and both shoulders; naming them
        # here documents the dependency and lets the client validate coverage
        # before it starts counting.
        joints=("left_wrist", "right_wrist", "left_shoulder", "right_shoulder"),
        smoothing=0.30,
    ),
    counter=CounterSpec(
        # Normalized top-hand height above the shoulder line, in torso lengths.
        # The stick drops below the shoulder to receive, then rises past it to
        # throw.
        down_threshold=-0.05,
        up_threshold=0.18,
        min_rep_ms=450,
        max_rep_ms=6_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(
        xp_per_rep=1.0,
        daily_rep_cap=800,
        diminishing_after_reps=250,
        diminishing_rate=0.35,
    ),
    validation=ValidationSpec(
        max_reps_per_second=3.0,
        min_reps_per_second=0.10,
        min_reps=10,
        min_duration_ms=15_000,
    ),
    tracks_handedness=True,
    setup_hint=(
        "Stand side-on to the phone, 8-10 feet back, full body and stick head "
        "in frame. Both feet visible."
    ),
    quality=QualitySpec(
        # Top hand travels from roughly a hand's width below the shoulder line
        # to well above it on a committed throw.
        target_rom=0.47,
        tempo_min_ms=550,
        tempo_max_ms=2_200,
        # Consistency is weighted heaviest here: a repeatable release is what
        # makes a pass accurate, and it is the thing wall ball is *for*.
        w_consistency=0.40,
        w_depth=0.25,
        w_tempo=0.15,
        w_endurance=0.20,
        min_reps=12,
    ),
)

QUICK_STICK = DrillSpec(
    key="lax_quick_stick",
    name="Quick Stick",
    sport="lacrosse",
    category=Category.SKILL,
    metric=Metric.REPS,
    description=(
        "Catch and release in one motion, no cradle. Same cycle detector as "
        "wall ball with a tighter refractory window, so only genuinely fast "
        "releases count."
    ),
    signal=SignalSpec(
        kind=SignalKind.WALL_BALL_CYCLE,
        joints=("left_wrist", "right_wrist", "left_shoulder", "right_shoulder"),
        smoothing=0.25,
    ),
    counter=CounterSpec(
        down_threshold=0.0,
        up_threshold=0.15,
        min_rep_ms=280,
        max_rep_ms=2_500,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.4, daily_rep_cap=500, diminishing_after_reps=150),
    validation=ValidationSpec(
        max_reps_per_second=4.0, min_reps_per_second=0.25, min_reps=10
    ),
    tracks_handedness=True,
    setup_hint="Closer to the wall than wall ball. No cradle -- catch and go.",
    quality=QualitySpec(
        target_rom=0.28,
        consistency_target=0.18,
        tempo_min_ms=280,
        tempo_max_ms=1_200,
        w_consistency=0.40,
        w_depth=0.20,
        w_tempo=0.25,
        w_endurance=0.15,
        min_reps=12,
    ),
)

# --------------------------------------------------------------------------
# Strength
# --------------------------------------------------------------------------

PUSH_UP = DrillSpec(
    key="gen_push_up",
    name="Push-Ups",
    sport="general",
    category=Category.STRENGTH,
    metric=Metric.REPS,
    description="Elbow angle cycles from locked out, to below 90 degrees, back to locked out.",
    signal=SignalSpec(
        kind=SignalKind.JOINT_ANGLE,
        joints=("left_shoulder", "left_elbow", "left_wrist"),
        smoothing=0.35,
    ),
    counter=CounterSpec(
        down_threshold=95.0,   # chest down
        up_threshold=155.0,    # arms extended
        min_rep_ms=600,
        max_rep_ms=8_000,
    ),
    scoring=ScoringSpec(xp_per_rep=1.2, daily_rep_cap=400, diminishing_after_reps=100),
    validation=ValidationSpec(max_reps_per_second=1.8, min_reps=5),
    setup_hint="Phone on the ground, side-on, 6-8 feet away. Whole body in frame.",
    quality=QualitySpec(
        # Elbow sweeping from about 70 degrees at the bottom to lockout.
        target_rom=94.0,
        tempo_min_ms=800,
        tempo_max_ms=4_000,
        # Depth carries the most weight: a half push-up is the classic way to
        # inflate a rep count.
        w_consistency=0.25,
        w_depth=0.45,
        w_tempo=0.10,
        w_endurance=0.20,
    ),
)

SQUAT = DrillSpec(
    key="gen_squat",
    name="Bodyweight Squats",
    sport="general",
    category=Category.STRENGTH,
    metric=Metric.REPS,
    description="Knee angle cycles from standing, through parallel or below, back to standing.",
    signal=SignalSpec(
        kind=SignalKind.JOINT_ANGLE,
        joints=("left_hip", "left_knee", "left_ankle"),
        smoothing=0.35,
    ),
    counter=CounterSpec(
        down_threshold=100.0,
        up_threshold=160.0,
        min_rep_ms=700,
        max_rep_ms=8_000,
    ),
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=500, diminishing_after_reps=150),
    validation=ValidationSpec(max_reps_per_second=1.5, min_reps=5),
    setup_hint="Side-on to the phone so the knee bend is visible.",
    quality=QualitySpec(
        target_rom=78.0,
        tempo_min_ms=900,
        tempo_max_ms=4_500,
        w_consistency=0.25,
        w_depth=0.45,
        w_tempo=0.10,
        w_endurance=0.20,
    ),
)

SIT_UP = DrillSpec(
    key="gen_sit_up",
    name="Sit-Ups",
    sport="general",
    category=Category.STRENGTH,
    metric=Metric.REPS,
    description="Hip angle closes as the torso comes up, opens on the way back down.",
    signal=SignalSpec(
        kind=SignalKind.JOINT_ANGLE,
        joints=("left_shoulder", "left_hip", "left_knee"),
        smoothing=0.35,
    ),
    counter=CounterSpec(
        down_threshold=70.0,    # torso up, hip closed
        up_threshold=125.0,     # torso back down
        min_rep_ms=600,
        max_rep_ms=8_000,
        rising_completes=False,  # the rep completes at the top of the crunch
    ),
    scoring=ScoringSpec(xp_per_rep=0.8, daily_rep_cap=600, diminishing_after_reps=200),
    validation=ValidationSpec(max_reps_per_second=2.0, min_reps=5),
    setup_hint="Phone on the ground, side-on, level with your hips.",
    quality=QualitySpec(
        target_rom=72.0,
        tempo_min_ms=700,
        tempo_max_ms=3_500,
        w_consistency=0.30,
        w_depth=0.35,
        w_tempo=0.10,
        w_endurance=0.25,
    ),
)

PULL_UP = DrillSpec(
    key="gen_pull_up",
    name="Pull-Ups",
    sport="general",
    category=Category.STRENGTH,
    metric=Metric.REPS,
    description="Nose rises past the wrist line at the top of each rep.",
    signal=SignalSpec(
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="nose",
        reference="left_wrist",
        smoothing=0.30,
    ),
    counter=CounterSpec(
        down_threshold=-0.30,   # hanging, head well below hands
        up_threshold=-0.02,     # chin at hand level
        min_rep_ms=800,
        max_rep_ms=12_000,
    ),
    scoring=ScoringSpec(xp_per_rep=4.0, daily_rep_cap=120, diminishing_after_reps=40),
    validation=ValidationSpec(max_reps_per_second=1.0, min_reps=3, min_duration_ms=8_000),
    setup_hint="Phone facing you head-on, far enough back to keep the bar in frame.",
    quality=QualitySpec(
        target_rom=0.36,
        consistency_target=0.18,
        tempo_min_ms=1_000,
        tempo_max_ms=6_000,
        # Endurance weighted high: pull-up form degrades faster than any other
        # drill here, and the last two reps are usually the worst.
        w_consistency=0.20,
        w_depth=0.40,
        w_tempo=0.05,
        w_endurance=0.35,
        min_reps=5,
    ),
)

# --------------------------------------------------------------------------
# Speed / agility / conditioning
# --------------------------------------------------------------------------

JUMPING_JACK = DrillSpec(
    key="gen_jumping_jack",
    name="Jumping Jacks",
    sport="general",
    category=Category.CONDITIONING,
    metric=Metric.REPS,
    description="Wrists travel above the shoulder line and back down each rep.",
    signal=SignalSpec(
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="left_wrist",
        reference="left_shoulder",
        smoothing=0.30,
    ),
    counter=CounterSpec(
        down_threshold=-0.25,
        up_threshold=0.20,
        min_rep_ms=350,
        max_rep_ms=4_000,
    ),
    scoring=ScoringSpec(xp_per_rep=0.4, daily_rep_cap=1_000, diminishing_after_reps=300),
    validation=ValidationSpec(max_reps_per_second=3.5, min_reps=10),
    setup_hint="Head-on to the phone, full body in frame.",
    quality=QualitySpec(
        target_rom=0.56,
        consistency_target=0.18,
        tempo_min_ms=400,
        tempo_max_ms=1_500,
        w_consistency=0.30,
        w_depth=0.35,
        w_tempo=0.15,
        w_endurance=0.20,
    ),
)

HIGH_KNEES = DrillSpec(
    key="gen_high_knees",
    name="High Knees",
    sport="general",
    category=Category.SPEED,
    metric=Metric.REPS,
    description="Each knee drive above hip height counts as one rep.",
    signal=SignalSpec(
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="left_knee",
        reference="left_hip",
        smoothing=0.22,
    ),
    counter=CounterSpec(
        down_threshold=-0.35,
        up_threshold=-0.05,
        min_rep_ms=200,
        max_rep_ms=2_000,
    ),
    scoring=ScoringSpec(xp_per_rep=0.25, daily_rep_cap=1_500, diminishing_after_reps=400),
    validation=ValidationSpec(max_reps_per_second=5.0, min_reps=20),
    setup_hint="Head-on, 8 feet back. Drive the knee above the hip.",
    quality=QualitySpec(
        target_rom=0.38,
        consistency_target=0.20,
        tempo_min_ms=200,
        tempo_max_ms=900,
        # Knee height is the whole drill -- a shuffle with low knees is not
        # this exercise.
        w_consistency=0.25,
        w_depth=0.45,
        w_tempo=0.15,
        w_endurance=0.15,
        min_reps=20,
    ),
)

BURPEE = DrillSpec(
    key="gen_burpee",
    name="Burpees",
    sport="general",
    category=Category.CONDITIONING,
    metric=Metric.REPS,
    description="Hip height drops to the floor and returns to standing each rep.",
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.40),
    counter=CounterSpec(
        down_threshold=0.25,
        up_threshold=0.75,
        min_rep_ms=1_200,
        max_rep_ms=15_000,
    ),
    scoring=ScoringSpec(xp_per_rep=2.5, daily_rep_cap=200, diminishing_after_reps=60),
    validation=ValidationSpec(max_reps_per_second=0.9, min_reps=5),
    setup_hint="Side-on, far enough back to stay in frame standing and prone.",
    quality=QualitySpec(
        target_rom=0.74,
        consistency_target=0.18,
        tempo_min_ms=1_500,
        tempo_max_ms=8_000,
        w_consistency=0.25,
        w_depth=0.35,
        w_tempo=0.10,
        w_endurance=0.30,
        min_reps=5,
    ),
)

SQUAT_JUMP = DrillSpec(
    key="gen_squat_jump",
    name="Squat Jumps",
    sport="general",
    category=Category.SPEED,
    metric=Metric.REPS,
    description="Explosive jump out of a squat. Counts each full extension.",
    # Smoothing deliberately light. An exponential filter attenuates a fast
    # oscillation, and at 0.20 a one-second jump cycle lost ~27% of its
    # amplitude -- enough that the signal never fell back far enough to re-arm
    # and the drill counted one rep in twenty-four. Explosive drills need the
    # amplitude preserved; hysteresis and the refractory window handle jitter.
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.45),
    counter=CounterSpec(
        down_threshold=0.45,
        up_threshold=0.95,
        min_rep_ms=500,
        max_rep_ms=5_000,
    ),
    scoring=ScoringSpec(xp_per_rep=1.8, daily_rep_cap=250, diminishing_after_reps=80),
    validation=ValidationSpec(max_reps_per_second=1.8, min_reps=5),
    setup_hint="Side-on, full body in frame at the top of the jump.",
    quality=QualitySpec(
        target_rom=0.63,
        tempo_min_ms=600,
        tempo_max_ms=3_000,
        # Power drills live or die on whether the last jumps match the first.
        w_consistency=0.25,
        w_depth=0.35,
        w_tempo=0.10,
        w_endurance=0.30,
    ),
)

LATERAL_BOUND = DrillSpec(
    key="gen_lateral_bound",
    name="Lateral Bounds",
    sport="general",
    category=Category.AGILITY,
    metric=Metric.REPS,
    description=(
        "Side-to-side skater bounds. Counts each single-leg landing, tracked "
        "per side so imbalance shows up."
    ),
    signal=SignalSpec(
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="left_ankle",
        reference="right_ankle",
        smoothing=0.22,
    ),
    counter=CounterSpec(
        down_threshold=-0.12,
        up_threshold=0.12,
        min_rep_ms=300,
        max_rep_ms=4_000,
    ),
    scoring=ScoringSpec(xp_per_rep=0.9, daily_rep_cap=400, diminishing_after_reps=120),
    validation=ValidationSpec(max_reps_per_second=3.0, min_reps=10),
    tracks_handedness=True,  # reported as left/right *legs* for this drill
    setup_hint="Head-on to the phone with room to bound both directions.",
    quality=QualitySpec(
        target_rom=0.31,
        consistency_target=0.20,
        tempo_min_ms=350,
        tempo_max_ms=1_800,
        w_consistency=0.35,
        w_depth=0.30,
        w_tempo=0.15,
        w_endurance=0.20,
        min_reps=12,
    ),
)

PLANK = DrillSpec(
    key="gen_plank",
    name="Plank Hold",
    sport="general",
    category=Category.STRENGTH,
    metric=Metric.HOLD_SECONDS,
    description=(
        "Timed hold. The clock only runs while the body stays within a "
        "straight-line tolerance, so sagging pauses it."
    ),
    signal=SignalSpec(
        kind=SignalKind.JOINT_ANGLE,
        joints=("left_shoulder", "left_hip", "left_ankle"),
        smoothing=0.40,
    ),
    counter=CounterSpec(
        # For hold drills the thresholds define the *valid* band rather than a
        # rep cycle: the hold counts while the body line stays above
        # down_threshold degrees.
        down_threshold=155.0,
        up_threshold=200.0,
        min_rep_ms=1_000,
        max_rep_ms=600_000,
    ),
    scoring=ScoringSpec(xp_per_rep=0.0, xp_per_minute=30.0, daily_rep_cap=1),
    validation=ValidationSpec(
        max_reps_per_second=1.0, min_reps=0, min_duration_ms=20_000
    ),
    setup_hint="Side-on, phone on the ground. Shoulders, hips and ankles in frame.",
    quality=QualitySpec(
        # Hold drills score on time genuinely spent in position rather than
        # range of motion, so target_rom is nominal.
        target_rom=1.0,
    ),
)


ALL_DRILLS: tuple[DrillSpec, ...] = (
    WALL_BALL,
    QUICK_STICK,
    PUSH_UP,
    SQUAT,
    SIT_UP,
    PULL_UP,
    JUMPING_JACK,
    HIGH_KNEES,
    BURPEE,
    SQUAT_JUMP,
    LATERAL_BOUND,
    PLANK,
)

DRILLS_BY_KEY: dict[str, DrillSpec] = {d.key: d for d in ALL_DRILLS}


def get_drill(key: str) -> DrillSpec:
    """Look up a drill, raising a clear error for an unknown key."""
    try:
        return DRILLS_BY_KEY[key]
    except KeyError:
        raise KeyError(
            f"unknown drill {key!r}; known drills: {sorted(DRILLS_BY_KEY)}"
        ) from None
