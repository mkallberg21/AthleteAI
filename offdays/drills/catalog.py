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

from dataclasses import replace

from .base import (
    CueSpec,
    BallSpec,
    Category,
    LoadSpec,
    CounterSpec,
    DrillSpec,
    Metric,
    QualitySpec,
    Stimulus,
    ScoringSpec,
    Tissue,
    SignalKind,
    SignalSpec,
    ValidationSpec,
)

# --------------------------------------------------------------------------
# Lacrosse
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Lacrosse
# --------------------------------------------------------------------------

#: Every lacrosse drill uses the same ball, so it is described once here
#: rather than repeated per drill. A men's and women's lacrosse ball are both
#: 6.2-6.5cm and always white, orange or yellow at this level -- the detector
#: takes white as the hard case and the rest come free, because a coloured
#: ball against a wall is easier than a white one.
#:
#: Always `confirm` and never `required`. A lacrosse ball is the smallest and
#: fastest object in this catalogue and the detector's weakest subject, so
#: failing to see one is at least as likely to be our blind spot as the
#: athlete's honesty. Requiring it would punish children for a model's limit.
#: What it can still do is catch the opposite case: a session where the ball
#: was tracked clearly and never once left a hand.
LACROSSE_BALL = BallSpec(
    mode="confirm",
    required=False,
    contact="body",
    parts=("left_wrist", "right_wrist"),
    min_gap_ms=400,
    min_speed=0.40,
    attribute_side=False,
    min_track_quality=0.30,
    # The purpose-built detector rather than the general model: a lacrosse
    # ball is not in the general model's vocabulary, and this one runs every
    # frame instead of every fourth, which matters at this speed.
    detector="vision",
    # White is still the common case and stays first, but these are sold in
    # yellow and neon lime too and a club buys whichever was in stock. Naming
    # only white meant a child with a lime ball got a drill that corroborated
    # nothing and never said why.
    colours=("white", "yellow", "lime"),
    diameter_cm=6.35,
)

#: Same ball, shorter gate. Quick stick and one-handed reps come faster than
#: the 400ms the standard window assumes, and a gate longer than the rep it is
#: policing would throw away every second contact.
LACROSSE_BALL_FAST = replace(LACROSSE_BALL, min_gap_ms=250)

WALL_BALL = DrillSpec(
    key="lax_wall_ball",
    name="Wall Ball",
    sport="lacrosse",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
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
    ball=LACROSSE_BALL,
    setup_hint=(
        "Prop the phone up so it can see you and the wall. Side-on reads hands "
        "best, but any angle counts."
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
    load=LoadSpec(
        # Low mechanical load per rep, but every rep is an overhead throw and
        # throwing volume is the thing that hurts young shoulders and elbows.
        load_per_rep=0.35,
        throws_per_rep=1.0,
        tissue=Tissue.THROWING,
    ),
)

QUICK_STICK = DrillSpec(
    key="lax_quick_stick",
    name="Quick Stick",
    sport="lacrosse",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
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
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=500, diminishing_after_reps=150),
    validation=ValidationSpec(
        max_reps_per_second=4.0, min_reps_per_second=0.25, min_reps=10
    ),
    tracks_handedness=True,
    ball=LACROSSE_BALL_FAST,
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
    load=LoadSpec(load_per_rep=0.30, throws_per_rep=1.0, tissue=Tissue.THROWING),
)

# --------------------------------------------------------------------------
# The wall ball routine
#
# A real wall ball routine is a named sequence of patterns, not one exercise
# repeated. These are the patterns a coach calls out, each shipped as its own
# drill so an athlete can be assigned "off hand only, 100" rather than "wall
# ball" and hope.
#
# **The detector does not recognise which pattern is being thrown.** It reads
# top-hand height above the shoulder line and counts cycles; it cannot see
# whether the ball went behind a back. The athlete picks the pattern, exactly
# as they pick squats over lunges, and what each spec below encodes is the
# *shape a good rep of that pattern has* -- its range, its tempo, and which
# hand should be on top. That is what makes the form score mean something
# different for one-handed than for a full two-handed throw, and it is the
# honest limit of what pose can offer here.
# --------------------------------------------------------------------------

WALL_BALL_STRONG = DrillSpec(
    key="lax_wall_ball_strong",
    name="Wall Ball - Strong Hand",
    sport="lacrosse",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Every rep with your dominant hand on top, full throwing motion. The "
        "baseline pattern the rest of the routine is measured against."
    ),
    signal=SignalSpec(
        kind=SignalKind.WALL_BALL_CYCLE,
        joints=("left_wrist", "right_wrist", "left_shoulder", "right_shoulder"),
        smoothing=0.30,
    ),
    counter=CounterSpec(
        down_threshold=-0.05, up_threshold=0.18,
        min_rep_ms=450, max_rep_ms=6_000, rising_completes=True,
    ),
    scoring=ScoringSpec(
        xp_per_rep=1.0, daily_rep_cap=600,
        diminishing_after_reps=200, diminishing_rate=0.35,
    ),
    validation=ValidationSpec(
        max_reps_per_second=3.0, min_reps_per_second=0.10,
        min_reps=10, min_duration_ms=15_000,
    ),
    tracks_handedness=True,
    ball=LACROSSE_BALL,
    setup_hint="Side-on to the phone. Dominant hand on top every rep.",
    quality=QualitySpec(
        target_rom=0.47, tempo_min_ms=550, tempo_max_ms=2_200,
        w_consistency=0.40, w_depth=0.25, w_tempo=0.15, w_endurance=0.20,
        min_reps=12,
    ),
    load=LoadSpec(load_per_rep=0.35, throws_per_rep=1.0, tissue=Tissue.THROWING),
)

WALL_BALL_OFFHAND = DrillSpec(
    key="lax_wall_ball_offhand",
    name="Wall Ball - Off Hand",
    sport="lacrosse",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        'Every rep with your weaker hand on top. The hardest pattern in the routine and the one that changes a player fastest -- and the one pattern the camera really can check, because it can see which hand is on top. Off-hand reps are paid at a premium wherever you do them.'
    ),
    signal=SignalSpec(
        kind=SignalKind.WALL_BALL_CYCLE,
        joints=("left_wrist", "right_wrist", "left_shoulder", "right_shoulder"),
        smoothing=0.30,
    ),
    counter=CounterSpec(
        down_threshold=-0.05, up_threshold=0.18,
        min_rep_ms=450, max_rep_ms=7_000, rising_completes=True,
    ),
    # Worth more per rep, because it is harder and it is the single thing this
    # product most wants a young player to do. Nothing else in the catalogue
    # is paid above 1.4.
    scoring=ScoringSpec(
        xp_per_rep=1.0, daily_rep_cap=500,
        diminishing_after_reps=200, diminishing_rate=0.35,
    ),
    validation=ValidationSpec(
        max_reps_per_second=3.0, min_reps_per_second=0.08,
        min_reps=10, min_duration_ms=15_000,
    ),
    tracks_handedness=True,
    ball=LACROSSE_BALL,
    setup_hint="Weak hand on top. It will feel wrong; that is the point.",
    quality=QualitySpec(
        # Deliberately the same target as the strong hand. Scoring a shorter
        # motion as acceptable here would teach a permanently shorter off-hand
        # throw, which is the exact habit this drill exists to break.
        target_rom=0.47,
        # Wider consistency band: an off hand is genuinely more variable early
        # on, and marking that as failure would just make the drill miserable.
        consistency_target=0.20,
        tempo_min_ms=600, tempo_max_ms=2_800,
        w_consistency=0.30, w_depth=0.35, w_tempo=0.10, w_endurance=0.25,
        min_reps=12,
    ),
    load=LoadSpec(load_per_rep=0.35, throws_per_rep=1.0, tissue=Tissue.THROWING),
)

WALL_BALL_ONE_HAND = DrillSpec(
    key="lax_wall_ball_one_hand",
    name="Wall Ball - One Handed",
    sport="lacrosse",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        'Bottom hand off the stick. Short, controlled throws that build the top-hand strength a one-handed catch in traffic needs. The app counts your reps but cannot see whether the bottom hand was off -- that one is on you, and it earns the same as any other wall ball.'
    ),
    signal=SignalSpec(
        kind=SignalKind.WALL_BALL_CYCLE,
        joints=("left_wrist", "right_wrist", "left_shoulder", "right_shoulder"),
        smoothing=0.25,
    ),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=0.14,
        min_rep_ms=320, max_rep_ms=3_000, rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=350, diminishing_after_reps=120),
    validation=ValidationSpec(
        max_reps_per_second=3.5, min_reps_per_second=0.15, min_reps=10
    ),
    # One camera and no stick: the hands travel the same path as a plain
    # wall ball, so the app counts the reps honestly and cannot confirm
    # the pattern. It pays the plain rate for exactly that reason.
    pattern_verified=False,
    tracks_handedness=True,
    ball=LACROSSE_BALL_FAST,
    setup_hint="One hand only, close to the wall. Short and controlled.",
    quality=QualitySpec(
        # A one-handed throw is a shorter motion by design, so the target is
        # lower rather than the athlete being marked down for the pattern.
        target_rom=0.32,
        tempo_min_ms=400, tempo_max_ms=1_800,
        w_consistency=0.45, w_depth=0.20, w_tempo=0.20, w_endurance=0.15,
        min_reps=12,
    ),
    # Lighter per rep than a full throw, but it is still an overhead motion on
    # a young shoulder and it counts toward throwing volume.
    load=LoadSpec(load_per_rep=0.25, throws_per_rep=1.0, tissue=Tissue.THROWING),
)

WALL_BALL_CROSS = DrillSpec(
    key="lax_wall_ball_cross",
    name="Wall Ball - Cross Handed",
    sport="lacrosse",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        'Catch on one side, switch hands, throw from the other. Builds the hand exchange a dodge actually needs. The app counts your reps but cannot see the switch, so this earns the same as any other wall ball.'
    ),
    signal=SignalSpec(
        kind=SignalKind.WALL_BALL_CYCLE,
        joints=("left_wrist", "right_wrist", "left_shoulder", "right_shoulder"),
        smoothing=0.30,
    ),
    counter=CounterSpec(
        down_threshold=-0.05, up_threshold=0.16,
        min_rep_ms=550, max_rep_ms=7_000, rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=400, diminishing_after_reps=150),
    validation=ValidationSpec(
        max_reps_per_second=2.5, min_reps_per_second=0.08, min_reps=10
    ),
    # One camera and no stick: the hands travel the same path as a plain
    # wall ball, so the app counts the reps honestly and cannot confirm
    # the pattern. It pays the plain rate for exactly that reason.
    pattern_verified=False,
    tracks_handedness=True,
    ball=LACROSSE_BALL,
    setup_hint="Catch one side, switch, throw the other. Alternate every rep.",
    quality=QualitySpec(
        target_rom=0.44,
        tempo_min_ms=600, tempo_max_ms=2_600,
        # Both hands are used by design, so an even split is the goal rather
        # than a warning -- the off-hand share is read as balance here.
        w_consistency=0.35, w_depth=0.25, w_tempo=0.15, w_endurance=0.25,
        min_reps=12,
    ),
    load=LoadSpec(load_per_rep=0.35, throws_per_rep=1.0, tissue=Tissue.THROWING),
)

WALL_BALL_BTB = DrillSpec(
    key="lax_wall_ball_btb",
    name="Wall Ball - Behind the Back",
    sport="lacrosse",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        'Catch, wrap behind the back, release. Showy, but it is real hand control and it is how a player learns where the head is without looking. The app counts your reps but cannot see behind you, so this earns the same as any other wall ball.'
    ),
    signal=SignalSpec(
        kind=SignalKind.WALL_BALL_CYCLE,
        joints=("left_wrist", "right_wrist", "left_shoulder", "right_shoulder"),
        smoothing=0.30,
    ),
    counter=CounterSpec(
        down_threshold=-0.02, up_threshold=0.13,
        min_rep_ms=500, max_rep_ms=6_000, rising_completes=True,
    ),
    # A lower cap than the rest of the routine on purpose. This is a garnish,
    # and a child grinding 600 behind-the-back reps is not building a lacrosse
    # player.
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=200, diminishing_after_reps=80),
    validation=ValidationSpec(
        max_reps_per_second=2.5, min_reps_per_second=0.06, min_reps=8
    ),
    # One camera and no stick: the hands travel the same path as a plain
    # wall ball, so the app counts the reps honestly and cannot confirm
    # the pattern. It pays the plain rate for exactly that reason.
    pattern_verified=False,
    tracks_handedness=True,
    ball=LACROSSE_BALL,
    setup_hint="Wrap behind the back and release. Slow is fine.",
    quality=QualitySpec(
        # The hand never gets as high behind the back, so the target reflects
        # the pattern rather than marking every rep short.
        target_rom=0.36,
        consistency_target=0.22,
        tempo_min_ms=700, tempo_max_ms=3_200,
        w_consistency=0.40, w_depth=0.20, w_tempo=0.15, w_endurance=0.25,
        min_reps=10,
    ),
    load=LoadSpec(load_per_rep=0.30, throws_per_rep=1.0, tissue=Tissue.THROWING),
)

WALL_BALL_SPLIT = DrillSpec(
    key="lax_wall_ball_split",
    name="Wall Ball - Split Dodge",
    sport="lacrosse",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        'Catch, split dodge, throw from the new hand. Footwork and hands in one rep, which is how they happen in a game. The app counts the hands and cannot see the split, so this earns the same as any other wall ball.'
    ),
    signal=SignalSpec(
        kind=SignalKind.WALL_BALL_CYCLE,
        joints=("left_wrist", "right_wrist", "left_shoulder", "right_shoulder"),
        smoothing=0.32,
    ),
    counter=CounterSpec(
        down_threshold=-0.05, up_threshold=0.18,
        min_rep_ms=700,
        # Long, because the dodge happens between the catch and the throw and
        # a rep that takes four seconds is a rep done properly, not a pause.
        max_rep_ms=9_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=300, diminishing_after_reps=120),
    validation=ValidationSpec(
        max_reps_per_second=1.6, min_reps_per_second=0.05, min_reps=8
    ),
    # One camera and no stick: the hands travel the same path as a plain
    # wall ball, so the app counts the reps honestly and cannot confirm
    # the pattern. It pays the plain rate for exactly that reason.
    pattern_verified=False,
    tracks_handedness=True,
    ball=LACROSSE_BALL,
    setup_hint="Catch, plant, split, throw from the other hand. Sell the dodge.",
    quality=QualitySpec(
        target_rom=0.46,
        consistency_target=0.20,
        tempo_min_ms=900, tempo_max_ms=4_500,
        w_consistency=0.30, w_depth=0.30, w_tempo=0.15, w_endurance=0.25,
        min_reps=10,
    ),
    # Legs are doing real work here as well as the shoulder, so it carries
    # more load per rep than a standing throw.
    load=LoadSpec(load_per_rep=0.70, throws_per_rep=1.0, tissue=Tissue.THROWING),
)

GROUND_BALL = DrillSpec(
    key="lax_ground_ball",
    name="Ground Balls",
    sport="lacrosse",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Roll the ball out, scoop through it, come up ready. The most "
        "repeated skill in the sport after passing, and the one that decides "
        "most youth games."
    ),
    signal=SignalSpec(
        # Whole-body height, not a joint angle: a scoop is the body dropping
        # over the ball and driving back up, and the hands are busy holding a
        # stick the camera cannot see anyway.
        kind=SignalKind.BODY_HEIGHT,
        joints=(),
        smoothing=0.30,
    ),
    counter=CounterSpec(
        down_threshold=0.30, up_threshold=0.80,
        # Nobody scoops properly in under a second. A faster cycle is a bend,
        # not a ground ball.
        min_rep_ms=900, max_rep_ms=8_000, rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.5, daily_rep_cap=300, diminishing_after_reps=100),
    validation=ValidationSpec(
        max_reps_per_second=1.2, min_reps_per_second=0.05,
        min_reps=8, min_duration_ms=20_000,
    ),
    tracks_handedness=True,
    ball=LACROSSE_BALL,
    setup_hint=(
        "Roll the ball a few feet, scoop through it and come up. Phone side-on "
        "so it can see you get low."
    ),
    quality=QualitySpec(
        # Getting low is the whole skill. A shallow bend is the single most
        # common fault and the one this score should be about.
        target_rom=0.68,
        tempo_min_ms=1_100, tempo_max_ms=5_000,
        w_consistency=0.25, w_depth=0.45, w_tempo=0.10, w_endurance=0.20,
        min_reps=8,
    ),
    load=LoadSpec(
        load_per_rep=1.4,
        # No overhead throw, so this must not inflate throwing volume -- the
        # thing that hurts young shoulders. It is a legs-and-back drill.
        throws_per_rep=0.0,
        tissue=Tissue.LOWER_BODY,
    ),
)


FACEOFF_CLAMP = DrillSpec(
    key="lax_faceoff_clamp",
    name="Face-Off Clamp",
    sport="lacrosse",
    category=Category.SPEED,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "From the down stance: clamp, rip the ball back, come up to ready, "
        "reset. Repeated for speed rather than volume -- a face-off is won in "
        "the first half second and lost in the next two."
    ),
    signal=SignalSpec(
        # Top wrist against the hip on the same side. In the stance the hands
        # are near the ground, well below the hip; the rip and recovery brings
        # them back up. That vertical travel is the part of a clamp pose can
        # actually see.
        #
        # What it CANNOT see is the clamp itself, which is a wrist rotation
        # around a stick the camera does not know exists. This drill measures
        # how fast and how repeatably the hands move, not whether the ball was
        # trapped -- and the description, the cues and the README all say so
        # rather than letting a FOGO assume otherwise.
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="right_wrist",
        reference="right_hip",
        # Light smoothing: this is a fast movement and smoothing it hard would
        # flatten exactly the snap being measured.
        smoothing=0.20,
    ),
    counter=CounterSpec(
        down_threshold=-0.32,
        up_threshold=-0.08,
        # Explosive by nature. A clamp slower than this is a rehearsal, not a
        # rep, but the floor still has to allow a genuinely quick one.
        min_rep_ms=260,
        max_rep_ms=3_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.4, daily_rep_cap=250, diminishing_after_reps=100),
    validation=ValidationSpec(
        max_reps_per_second=3.5, min_reps_per_second=0.15,
        min_reps=10, min_duration_ms=20_000,
    ),
    tracks_handedness=True,
    ball=LACROSSE_BALL_FAST,
    setup_hint=(
        "Down in your stance with a ball. Phone side-on and low so it can see "
        "your hands. Clamp, rip, up, reset."
    ),
    quality=QualitySpec(
        target_rom=0.24,
        # Tighter than most drills: a clamp that varies is a clamp that loses.
        consistency_target=0.12,
        tempo_min_ms=260,
        tempo_max_ms=1_200,
        # The only drill in the catalogue where tempo outweighs range. Everything
        # else here is about doing a movement fully; this one is about doing it
        # before the other kid does.
        w_consistency=0.35,
        w_depth=0.20,
        w_tempo=0.35,
        w_endurance=0.10,
        min_reps=12,
    ),
    load=LoadSpec(
        load_per_rep=1.0,
        # Nothing goes overhead, so this must not touch throwing volume. It is
        # a crouched, explosive whole-body movement.
        throws_per_rep=0.0,
        tissue=Tissue.WHOLE_BODY,
    ),
)


GOALIE_SAVES = DrillSpec(
    key="lax_goalie_saves",
    name="Goalie Save Positions",
    sport="lacrosse",
    category=Category.SPEED,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        'The app calls a spot -- high, hip, low, either side, or five hole -- and you drive BOTH hands and your lead foot to it, then reset. Reaching with one arm does not count: the app measures your hands together, so a one-armed stab moves the measurement half as far and never registers as a save. There is no ball and no shooter -- this trains the path to the spot, not reading a shot, and it is not a save percentage.'
    ),
    signal=SignalSpec(
        # The one drill in the catalogue where the athlete is sent somewhere
        # different every rep, which breaks every height signal here: a high
        # save moves the hands up and a low save moves them down, so no single
        # threshold pair can count both.
        #
        # What every save has in common is that the hands leave the ready
        # position and come back. Measured as reach -- distance from the chest
        # -- that is a clean oscillation whichever direction the save went, and
        # the *direction* is recovered separately by classifying where the
        # hands were at full extension.
        kind=SignalKind.SAVE_REACH,
        # By far the lightest smoothing in the catalogue, and the reason is
        # that this drill measures *when* rather than only *how much*. Every
        # other drill can afford a filter that lags a few frames, because a rep
        # counted 120ms late is still one rep. Here the timestamp is the
        # measurement, so at 0.35 the filter's own lag would be a fifth of the
        # reaction being reported -- and it would land on every rep in the same
        # direction, which makes it a bias rather than noise.
        #
        # Reach is a distance across a whole torso length, so it tolerates the
        # jitter this lets through far better than a single-joint angle would.
        smoothing=0.55,
    ),
    counter=CounterSpec(
        # Ready position sits around 0.5 torso lengths from the chest with the
        # elbows bent; a committed save to a corner puts the hands out past
        # 1.2. The firing line sits below full extension deliberately: it marks
        # the point the save was committed to, which is both what a shooter
        # reacts to and what stays comparable between a long reach and a short
        # one.
        down_threshold=0.70,
        up_threshold=0.95,
        # A save is fast. Below this the hands never really left ready.
        min_rep_ms=320,
        # Shorter than the cue period, so a rep can never straddle two cues.
        max_rep_ms=2_200,
        rising_completes=True,
    ),
    cues=CueSpec(
        # Every cell except the two the camera cannot honestly separate: a
        # chest-high or hip-high ball straight at the goalie needs the hands to
        # come forward rather than sideways, and forward is the one direction a
        # single phone camera reads worst. Both stay *observable*, so drifting
        # to the middle instead of driving to a corner is still reported -- it
        # is simply never asked for.
        zones=(
            "high_left", "high_right",
            "mid_left", "mid_right",
            "low_left", "low_right", "low_centre",
        ),
        lead_in_ms=4_000,
        period_ms=2_400,
        show_ms=900,
        # Roughly what a well-drilled youth goalie manages from ready to
        # extended. Used to describe, never to grade.
        quick_ms=700,
        late_ms=1_600,
    ),
    scoring=ScoringSpec(xp_per_rep=1.5, daily_rep_cap=200, diminishing_after_reps=80),
    validation=ValidationSpec(
        # Cues arrive every 2.4s, so a genuine session cannot exceed roughly
        # 0.42 reps/s of *answers*. The ceiling allows for resets and fidgets
        # between cues without letting a machine-gun claim through.
        max_reps_per_second=1.5,
        min_reps_per_second=0.05,
        min_reps=10,
        # lead-in plus the fourteen cues the breakdown needs.
        min_duration_ms=40_000,
    ),
    tracks_handedness=True,
    setup_hint=(
        "Stand in your stance in the goal or against a wall, phone straight in "
        "front of you at hip height, far enough back that your whole body and "
        "both hands stay in frame. Face the phone square -- turned sideways it "
        "cannot tell your left from your right. Two hands on the stick the "
        "whole time. Wait for the first call."
    ),
    quality=QualitySpec(
        # Ready to full extension and back, measured on the near-raw signal
        # this drill uses -- so the span is close to the real one rather than
        # the flattened version a heavier filter would leave.
        target_rom=0.75,
        consistency_target=0.16,
        tempo_min_ms=320,
        tempo_max_ms=1_600,
        # Tempo is weighted up because arriving late is the failure mode here,
        # but not as far as the face-off clamp: a goalie who gets there fast
        # with the hands half-extended has not made the save.
        w_consistency=0.30,
        w_depth=0.30,
        w_tempo=0.25,
        w_endurance=0.15,
        min_reps=12,
    ),
    load=LoadSpec(
        load_per_rep=0.9,
        # Explosive and whole-body, and nothing goes overhead -- this must not
        # touch throwing volume. A goalie's shoulder problem is not a throwing
        # problem.
        throws_per_rep=0.0,
        tissue=Tissue.WHOLE_BODY,
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
    stimulus=Stimulus.STRENGTH,
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
    load=LoadSpec(load_per_rep=1.2, tissue=Tissue.UPPER_BODY),
)

SQUAT = DrillSpec(
    key="gen_squat",
    name="Bodyweight Squats",
    sport="general",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
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
    load=LoadSpec(load_per_rep=1.0, tissue=Tissue.LOWER_BODY),
)

SIT_UP = DrillSpec(
    key="gen_sit_up",
    name="Sit-Ups",
    sport="general",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
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
    load=LoadSpec(load_per_rep=0.6, tissue=Tissue.CORE),
)

PULL_UP = DrillSpec(
    key="gen_pull_up",
    name="Pull-Ups",
    sport="general",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
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
    load=LoadSpec(load_per_rep=3.0, tissue=Tissue.UPPER_BODY),
)

# --------------------------------------------------------------------------
# Speed / agility / conditioning
# --------------------------------------------------------------------------

JUMPING_JACK = DrillSpec(
    key="gen_jumping_jack",
    name="Jumping Jacks",
    sport="general",
    category=Category.CONDITIONING,
    stimulus=Stimulus.ENDURANCE,
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
    load=LoadSpec(load_per_rep=0.25, tissue=Tissue.WHOLE_BODY),
)

HIGH_KNEES = DrillSpec(
    key="gen_high_knees",
    name="High Knees",
    sport="general",
    category=Category.SPEED,
    stimulus=Stimulus.QUICKNESS,
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
    load=LoadSpec(load_per_rep=0.20, tissue=Tissue.LOWER_BODY),
)

BURPEE = DrillSpec(
    key="gen_burpee",
    name="Burpees",
    sport="general",
    category=Category.CONDITIONING,
    stimulus=Stimulus.ENDURANCE,
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
    load=LoadSpec(load_per_rep=2.5, tissue=Tissue.WHOLE_BODY),
)

SQUAT_JUMP = DrillSpec(
    key="gen_squat_jump",
    name="Squat Jumps",
    sport="general",
    category=Category.SPEED,
    stimulus=Stimulus.POWER,
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
    load=LoadSpec(
        # Plyometrics are the highest impact-per-rep work here, and the drill
        # most worth capping when an athlete is already in a heavy week.
        load_per_rep=2.2,
        tissue=Tissue.LOWER_BODY,
    ),
)

LATERAL_BOUND = DrillSpec(
    key="gen_lateral_bound",
    name="Lateral Bounds",
    sport="general",
    category=Category.AGILITY,
    stimulus=Stimulus.POWER,
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
    load=LoadSpec(load_per_rep=1.4, tissue=Tissue.LOWER_BODY),
)

PLANK = DrillSpec(
    key="gen_plank",
    name="Plank Hold",
    sport="general",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
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
    load=LoadSpec(load_per_rep=0.0, load_per_minute=6.0, tissue=Tissue.CORE),
)


# ---------------------------------------------------------------------------
# Broader bodyweight work
#
# Added when the product went multi-sport. Every one of these is a bodyweight
# movement with an unambiguous pose signal -- which is exactly why the list
# does not contain dribbling, juggling, serving or shooting. Those need the
# ball tracked, not the body, and a drill that miscounts is worse than one that
# does not exist. Sport-specific *skill* work is coached through film and
# assignments instead.
# ---------------------------------------------------------------------------

GEN_LUNGE = DrillSpec(
    key="gen_lunge",
    name="Alternating Lunges",
    sport="general",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
    metric=Metric.REPS,
    description="Step forward, knee down, drive back. Counts each leg.",
    signal=SignalSpec(
        kind=SignalKind.JOINT_ANGLE,
        joints=("left_hip", "left_knee", "left_ankle"),
        smoothing=0.35,
    ),
    counter=CounterSpec(
        down_threshold=105.0,
        up_threshold=158.0,
        min_rep_ms=600,
        max_rep_ms=6_000,
    ),
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=400, diminishing_after_reps=140),
    validation=ValidationSpec(max_reps_per_second=1.4, min_reps=6),
    setup_hint="Side-on, hips and both knees in frame.",
    # Same knee-angle signal as the squat, and a lunge's trace sits inside a
    # squat's -- so the app cannot tell which one was done and must not pay
    # more for saying 'lunge'.
    pattern_verified=False,
    quality=QualitySpec(
        target_rom=72.0,
        tempo_min_ms=700,
        tempo_max_ms=3_500,
        w_consistency=0.30, w_depth=0.40, w_tempo=0.10, w_endurance=0.20,
    ),
    load=LoadSpec(load_per_rep=1.2, tissue=Tissue.LOWER_BODY),
)

GEN_GLUTE_BRIDGE = DrillSpec(
    key="gen_glute_bridge",
    name="Glute Bridges",
    sport="general",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
    metric=Metric.REPS,
    description="Hips up until shoulders, hips and knees line up. Counts each lift.",
    signal=SignalSpec(
        kind=SignalKind.JOINT_ANGLE,
        joints=("left_shoulder", "left_hip", "left_knee"),
        smoothing=0.35,
    ),
    counter=CounterSpec(
        down_threshold=118.0,
        up_threshold=163.0,
        min_rep_ms=600,
        max_rep_ms=6_000,
    ),
    scoring=ScoringSpec(xp_per_rep=0.9, daily_rep_cap=400, diminishing_after_reps=150),
    validation=ValidationSpec(max_reps_per_second=1.5, min_reps=6),
    setup_hint="Side-on, lying down, knees bent and hips in frame.",
    quality=QualitySpec(
        target_rom=58.0,
        tempo_min_ms=700,
        tempo_max_ms=3_500,
        w_consistency=0.30, w_depth=0.40, w_tempo=0.10, w_endurance=0.20,
    ),
    load=LoadSpec(load_per_rep=0.8, tissue=Tissue.LOWER_BODY),
)

GEN_MOUNTAIN_CLIMBER = DrillSpec(
    key="gen_mountain_climber",
    name="Mountain Climbers",
    sport="general",
    category=Category.CONDITIONING,
    stimulus=Stimulus.QUICKNESS,
    metric=Metric.REPS,
    description="Knees driving to the chest from a plank. Counts each drive.",
    signal=SignalSpec(
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="left_knee",
        reference="left_hip",
        # Fast oscillation, so smoothing stays light for the same reason squat
        # jumps needed it: a heavy filter eats the amplitude and the signal
        # never falls back far enough to re-arm.
        smoothing=0.45,
    ),
    counter=CounterSpec(
        down_threshold=-0.05,
        up_threshold=0.28,
        min_rep_ms=260,
        max_rep_ms=3_000,
    ),
    scoring=ScoringSpec(xp_per_rep=0.5, daily_rep_cap=600, diminishing_after_reps=200),
    validation=ValidationSpec(max_reps_per_second=3.5, min_reps=10),
    setup_hint="Side-on in a plank, hips and knees in frame.",
    quality=QualitySpec(
        # 0.40 rather than the 0.33 first guessed: the calibration harness
        # measures a textbook knee drive at ~0.42, and a target below what a
        # perfect rep scores would hand out full depth for a half rep.
        target_rom=0.40,
        tempo_min_ms=280,
        tempo_max_ms=1_600,
        w_consistency=0.35, w_depth=0.30, w_tempo=0.10, w_endurance=0.25,
    ),
    load=LoadSpec(load_per_rep=0.5, load_per_minute=2.0, tissue=Tissue.WHOLE_BODY),
)

GEN_TUCK_JUMP = DrillSpec(
    key="gen_tuck_jump",
    name="Tuck Jumps",
    sport="general",
    category=Category.SPEED,
    stimulus=Stimulus.POWER,
    metric=Metric.REPS,
    description="Jump and pull both knees up. Counts each landing.",
    # Same light smoothing as squat jumps, and for the same reason.
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.45),
    counter=CounterSpec(
        down_threshold=0.42,
        up_threshold=1.00,
        min_rep_ms=450,
        max_rep_ms=4_000,
    ),
    scoring=ScoringSpec(xp_per_rep=2.0, daily_rep_cap=200, diminishing_after_reps=60),
    validation=ValidationSpec(max_reps_per_second=2.0, min_reps=5),
    setup_hint="Side-on, full body in frame at the top of the jump.",
    quality=QualitySpec(
        target_rom=0.68,
        tempo_min_ms=550,
        tempo_max_ms=2_500,
        w_consistency=0.25, w_depth=0.35, w_tempo=0.10, w_endurance=0.30,
    ),
    load=LoadSpec(
        # The highest impact per rep in the catalog alongside squat jumps.
        load_per_rep=2.4,
        tissue=Tissue.LOWER_BODY,
    ),
)

GEN_DEAD_BUG = DrillSpec(
    key="gen_dead_bug",
    name="Dead Bugs",
    sport="general",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
    metric=Metric.REPS,
    description="Opposite arm and leg out, slow and controlled. Counts each extension.",
    signal=SignalSpec(
        kind=SignalKind.JOINT_ANGLE,
        joints=("left_shoulder", "left_hip", "left_knee"),
        smoothing=0.30,
    ),
    counter=CounterSpec(
        down_threshold=105.0,
        up_threshold=158.0,
        min_rep_ms=900,
        max_rep_ms=8_000,
    ),
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=300, diminishing_after_reps=120),
    validation=ValidationSpec(max_reps_per_second=1.0, min_reps=6),
    setup_hint="Side-on, lying on your back with hips and knees in frame.",
    quality=QualitySpec(
        target_rom=66.0,
        # Rushing this one is the whole failure mode, so the tempo window is
        # deliberately slow and the consistency weight high.
        tempo_min_ms=1_000,
        tempo_max_ms=5_000,
        w_consistency=0.40, w_depth=0.30, w_tempo=0.15, w_endurance=0.15,
    ),
    load=LoadSpec(load_per_rep=0.6, tissue=Tissue.CORE),
)

GEN_WALL_SIT = DrillSpec(
    key="gen_wall_sit",
    name="Wall Sit",
    sport="general",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
    metric=Metric.HOLD_SECONDS,
    description=(
        "Timed hold against a wall. The clock runs while the knees stay near "
        "a right angle, so sliding up pauses it."
    ),
    signal=SignalSpec(
        kind=SignalKind.JOINT_ANGLE,
        joints=("left_hip", "left_knee", "left_ankle"),
        smoothing=0.40,
    ),
    counter=CounterSpec(
        # Hold drills use the thresholds as a valid band rather than a rep
        # cycle: the clock runs while the knee angle sits inside it.
        down_threshold=70.0,
        up_threshold=125.0,
        min_rep_ms=1_000,
        max_rep_ms=600_000,
    ),
    scoring=ScoringSpec(xp_per_rep=0.0, xp_per_minute=26.0),
    validation=ValidationSpec(min_reps=0),
    setup_hint="Side-on, back against a wall, hips and knees in frame.",
    quality=QualitySpec(
        target_rom=1.0,
        tempo_min_ms=1_000,
        tempo_max_ms=600_000,
        w_consistency=0.30, w_depth=0.40, w_tempo=0.0, w_endurance=0.30,
    ),
    load=LoadSpec(load_per_rep=0.0, load_per_minute=7.0, tissue=Tissue.LOWER_BODY),
)

GEN_HOLLOW_HOLD = DrillSpec(
    key="gen_hollow_hold",
    name="Hollow Hold",
    sport="general",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
    metric=Metric.HOLD_SECONDS,
    description=(
        "Timed hold on your back, shoulders and legs off the floor. The clock "
        "stops when your feet or shoulders drop."
    ),
    signal=SignalSpec(
        kind=SignalKind.JOINT_ANGLE,
        joints=("left_shoulder", "left_hip", "left_knee"),
        smoothing=0.40,
    ),
    counter=CounterSpec(
        down_threshold=118.0,
        up_threshold=168.0,
        min_rep_ms=1_000,
        max_rep_ms=600_000,
    ),
    scoring=ScoringSpec(xp_per_rep=0.0, xp_per_minute=30.0),
    validation=ValidationSpec(min_reps=0),
    setup_hint="Side-on, lying on your back with your whole body in frame.",
    quality=QualitySpec(
        target_rom=1.0,
        tempo_min_ms=1_000,
        tempo_max_ms=600_000,
        w_consistency=0.30, w_depth=0.40, w_tempo=0.0, w_endurance=0.30,
    ),
    load=LoadSpec(load_per_rep=0.0, load_per_minute=6.0, tissue=Tissue.CORE),
)

GEN_SIDE_PLANK = DrillSpec(
    key="gen_side_plank",
    name="Side Plank",
    sport="general",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
    metric=Metric.HOLD_SECONDS,
    description=(
        "Timed hold on one forearm. The clock runs while your hips stay up "
        "in a straight line."
    ),
    signal=SignalSpec(
        kind=SignalKind.JOINT_ANGLE,
        joints=("left_shoulder", "left_hip", "left_ankle"),
        smoothing=0.40,
    ),
    counter=CounterSpec(
        down_threshold=155.0,
        up_threshold=200.0,
        min_rep_ms=1_000,
        max_rep_ms=600_000,
    ),
    scoring=ScoringSpec(xp_per_rep=0.0, xp_per_minute=28.0),
    validation=ValidationSpec(min_reps=0),
    setup_hint="Facing the camera, on one forearm, whole body in frame.",
    quality=QualitySpec(
        target_rom=1.0,
        tempo_min_ms=1_000,
        tempo_max_ms=600_000,
        w_consistency=0.30, w_depth=0.40, w_tempo=0.0, w_endurance=0.30,
    ),
    load=LoadSpec(load_per_rep=0.0, load_per_minute=5.5, tissue=Tissue.CORE),
)


# ---------------------------------------------------------------------------
# Ball drills
#
# The first drills in this catalog that read the ball rather than the body.
# Everything here would count a kid standing still if the ball were not
# required, so `required=True` is doing real work: below the track-quality
# floor these refuse rather than degrade.
#
# The `parts` lists are what separates one drill from another. A ball bouncing
# at ankle height is a juggle if a foot is next to it and a dribble if nothing
# is, which is why the contact classifier checks landmarks before the floor.
# ---------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Soccer
#
# The first sport here played with the feet, and the machinery transfers almost
# unchanged: `attribute_side` reads which foot took the ball exactly as it reads
# which hand, so the alternation rules built for basketball make a weak-foot
# drill and an alternating drill genuinely verifiable.
#
# What does not transfer is heading, and that is a decision rather than a gap.
# See the note on the parts list below.
# --------------------------------------------------------------------------
# The three qualities the general catalogue had no way to train
#
# These are `gen_` drills rather than sport drills, and they were found by
# building the judged sports -- gymnastics, cheer and dance -- whose plans were
# made entirely of the eighteen movements above. Nothing was wrong with those
# plans. What was wrong was the shelf they were picked from: eighteen movements
# that between them never once measured an ankle, never went overhead, and
# never asked an athlete to hang.
#
# All three sit in the general catalogue because none of them belong to a
# sport. A calf raise is the launching mechanism for every jump in this
# product.
# --------------------------------------------------------------------------
# The two explosive qualities the general catalogue could not train
#
# Audited rather than guessed. With every drill labelled by what it actually
# develops, the general shelf turned out to hold exactly three power drills --
# a squat jump, a tuck jump and a lateral bound -- and nothing at all for
# reactive quickness. Ten position plans across seven sports contained no power
# or quickness work whatsoever.
#
# These are the two missing qualities that a phone can genuinely verify.
# Several others cannot be, and are deliberately absent rather than
# approximated: a broad jump is horizontal distance the camera cannot measure,
# a split jump is a squat jump the camera cannot tell apart, and an explosive
# push-up is distinguished from an ordinary one by airtime that a side-on view
# does not see.
# --------------------------------------------------------------------------
# Running mechanics
#
# Two drills, and the smallest sport-facing addition in the catalogue, because
# the honest finding for track and cross country is that their solo work was
# almost entirely built already: high knees, pogo hops, calf raises, lunges,
# glute bridges, skater bounds and single-leg strength all arrived through
# other sports. What was genuinely missing was the back half of the running
# cycle and the position a sprinter holds while producing it.
#
# The rest of what these two sports need is not a drill at all. See the run log
# in store.py -- the load model could not see running, which for these athletes
# is the only thing that hurts them.
# --------------------------------------------------------------------------

GEN_BUTT_KICK = DrillSpec(
    key="gen_butt_kick",
    name="Butt Kicks",
    sport="general",
    category=Category.SPEED,
    stimulus=Stimulus.QUICKNESS,
    metric=Metric.REPS,
    description=(
        "Heels snapping up towards your backside, quickly, staying tall. The "
        "front half of a running stride has a drill and the back half did not "
        "-- this is the back half."
    ),
    signal=SignalSpec(
        # The heel against the knee on the same leg. High knees measure the
        # knee against the hip, which is the recovery of the leg in FRONT; this
        # measures the heel folding up behind, which nothing else here sees.
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="left_ankle",
        reference="left_knee",
        smoothing=0.55,
    ),
    counter=CounterSpec(
        # Standing puts the ankle roughly two thirds of a torso below the knee;
        # a real butt kick brings it up level with it or higher.
        down_threshold=-0.45,
        up_threshold=0.05,
        min_rep_ms=180,
        max_rep_ms=1_500,
        rising_completes=True,
    ),
    scoring=ScoringSpec(
        xp_per_rep=0.3,
        daily_rep_cap=700,
        diminishing_after_reps=300,
        diminishing_rate=0.35,
    ),
    validation=ValidationSpec(
        max_reps_per_second=5.0, min_reps_per_second=1.20,
        min_reps=30, min_duration_ms=15_000,
    ),
    setup_hint=(
        "Phone side-on at about knee height so it can see your heel come up "
        "behind you. Square to you it cannot see the fold at all."
    ),
    quality=QualitySpec(
        # Measured, not guessed. Standing puts the ankle about 0.68 torso
        # lengths below the knee and a real fold takes it slightly above, so a
        # textbook rep covers 0.8. The 0.55 I first wrote would have paid full
        # depth for a fold that stopped at mid-calf -- which is exactly what a
        # tired butt kick turns into.
        target_rom=0.80,
        consistency_target=0.10,
        consistency_ceiling=0.30,
        tempo_min_ms=180,
        tempo_max_ms=700,
        # Tempo and range together: a slow butt kick is a hamstring stretch.
        w_consistency=0.25,
        w_depth=0.30,
        w_tempo=0.30,
        w_endurance=0.15,
        min_reps=30,
    ),
    load=LoadSpec(load_per_rep=0.08, throws_per_rep=0.0, tissue=Tissue.LOWER_BODY),
    tracks_handedness=False,
)

GEN_KNEE_DRIVE_HOLD = DrillSpec(
    key="gen_knee_drive_hold",
    name="Knee Drive Hold",
    sport="general",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
    metric=Metric.HOLD_SECONDS,
    description=(
        "Hands on a wall, body in a straight line, one knee driven up and "
        "held there. The clock runs only while the knee is actually up -- "
        "letting it drift down stops it."
    ),
    signal=SignalSpec(
        # The driven knee against its own hip. The same measurement high knees
        # cycles through, held still instead: sprint position is a shape you
        # have to be strong enough to hold, and holding it is the drill.
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="left_knee",
        reference="left_hip",
        smoothing=0.35,
    ),
    counter=CounterSpec(
        # Above the hip and not so high that the athlete is sitting down into
        # it. A high-knee rep passes through this band; a hold lives in it.
        down_threshold=0.06,
        up_threshold=0.48,
        min_rep_ms=400,
        max_rep_ms=60_000,
    ),
    scoring=ScoringSpec(xp_per_rep=0.0, xp_per_minute=32.0, daily_rep_cap=1_000),
    validation=ValidationSpec(
        max_reps_per_second=1.0, min_reps=0, min_duration_ms=15_000,
    ),
    setup_hint=(
        "Phone side-on, far enough back to see your whole body and the wall. "
        "Lean in until you are a straight line from your ankle to your head, "
        "then drive one knee up and keep it there."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.0, load_per_minute=3.0, tissue=Tissue.LOWER_BODY),
    tracks_handedness=False,
)


# --------------------------------------------------------------------------

GEN_POGO = DrillSpec(
    key="gen_pogo",
    name="Pogo Hops",
    sport="general",
    category=Category.SPEED,
    # The one quality nothing here trained. Not power -- a pogo is deliberately
    # a small jump -- but how fast the ground can be left again, which is what
    # a first step and a change of direction are made of.
    stimulus=Stimulus.QUICKNESS,
    metric=Metric.REPS,
    description=(
        "Fast, small bounces off the balls of your feet, knees almost "
        "straight. Not jumps for height -- the point is how little time you "
        "spend on the floor. Slow down and it stops counting them."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.60),
    counter=CounterSpec(
        # A deliberately tiny band high up: the hips barely dip, which is what
        # separates this from every other jump in the catalogue.
        down_threshold=0.90,
        up_threshold=1.02,
        min_rep_ms=180,
        max_rep_ms=1_200,
        rising_completes=True,
    ),
    scoring=ScoringSpec(
        xp_per_rep=0.6,
        daily_rep_cap=800,
        diminishing_after_reps=300,
        diminishing_rate=0.35,
    ),
    validation=ValidationSpec(
        max_reps_per_second=5.0,
        # The verification, and the whole drill. Nothing else in the catalogue
        # can be sustained at this rate -- a tennis split step caps out at 2.0
        # a second and a squat jump at 1.8 -- so a session that holds it was
        # bouncing rather than jumping.
        min_reps_per_second=2.20,
        min_reps=40,
        min_duration_ms=15_000,
    ),
    setup_hint=(
        "Phone side-on at about hip height. Stay tall, stay on the balls of "
        "your feet, and think about pushing the floor away rather than about "
        "how high you get."
    ),
    quality=QualitySpec(
        target_rom=0.20,
        consistency_target=0.04,
        consistency_ceiling=0.12,
        tempo_min_ms=180,
        tempo_max_ms=500,
        # Tempo carries this one. A pogo done slowly is a small squat jump.
        w_consistency=0.30,
        w_depth=0.10,
        w_tempo=0.40,
        w_endurance=0.20,
        min_reps=40,
    ),
    load=LoadSpec(load_per_rep=0.10, throws_per_rep=0.0, tissue=Tissue.LOWER_BODY),
    tracks_handedness=False,
)

GEN_SKATER_BOUND = DrillSpec(
    key="gen_skater_bound",
    name="Skater Bounds",
    sport="general",
    category=Category.AGILITY,
    stimulus=Stimulus.POWER,
    metric=Metric.REPS,
    description=(
        "Bound sideways off one leg, land on the other, and hold it still "
        "before you go back. Distance, then balance. It measures how far apart "
        "your feet get, so a little hop from side to side does not count."
    ),
    signal=SignalSpec(
        # The same ankle-against-ankle measurement a lateral bound uses, opened
        # right up. A quick bound cannot reach these thresholds, so the two are
        # told apart by how far the athlete actually went.
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="left_ankle",
        reference="right_ankle",
        smoothing=0.45,
    ),
    counter=CounterSpec(
        down_threshold=-0.30,
        up_threshold=0.30,
        min_rep_ms=700,
        max_rep_ms=6_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.7, daily_rep_cap=200, diminishing_after_reps=90),
    validation=ValidationSpec(
        max_reps_per_second=1.4, min_reps_per_second=0.08,
        min_reps=12, min_duration_ms=25_000,
    ),
    setup_hint=(
        "Phone square in front of you with room either side. Land on one leg "
        "and stop dead before the next one -- the pause is the half of this "
        "that protects your knees."
    ),
    quality=QualitySpec(
        target_rom=0.75,
        consistency_target=0.14,
        tempo_min_ms=700,
        tempo_max_ms=3_000,
        # Distance is the point, and the landing is why the tempo matters.
        w_consistency=0.20,
        w_depth=0.40,
        w_tempo=0.20,
        w_endurance=0.20,
        min_reps=12,
    ),
    load=LoadSpec(load_per_rep=1.5, throws_per_rep=0.0, tissue=Tissue.LOWER_BODY),
    # Which leg took off, so an athlete who can only bound one way shows up.
    tracks_handedness=True,
)


# --------------------------------------------------------------------------

GEN_CALF_RAISE = DrillSpec(
    key="gen_calf_raise",
    name="Calf Raises",
    sport="general",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
    metric=Metric.REPS,
    description=(
        "Up onto the balls of your feet, all the way, and down under control. "
        "It watches your heel against your toes, so coming up half way does "
        "not count -- which is what almost everybody does when they stop "
        "paying attention."
    ),
    signal=SignalSpec(
        # The heel against the toe of the same foot. The first measurement in
        # this catalogue that looks below the knee: eighteen general movements
        # and every sport drill went past the ankle without ever measuring it,
        # in a product whose most common landing is on one.
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="left_heel",
        reference="left_foot_index",
        # Light. The excursion is small to begin with and a heavy filter eats
        # it, which is exactly how the squat-jump bug happened.
        smoothing=0.55,
    ),
    counter=CounterSpec(
        # Flat on the floor the heel sits a fraction above the toe landmark;
        # at the top of a real raise it is most of a hand's width higher.
        down_threshold=0.03,
        up_threshold=0.13,
        min_rep_ms=600,
        max_rep_ms=6_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(
        xp_per_rep=0.45,
        daily_rep_cap=600,
        diminishing_after_reps=200,
        diminishing_rate=0.35,
    ),
    validation=ValidationSpec(
        max_reps_per_second=2.0, min_reps_per_second=0.10,
        min_reps=15, min_duration_ms=20_000,
    ),
    setup_hint=(
        "Phone low and close, side-on to one foot -- ankle height, a couple of "
        "feet away. This is the smallest movement in the app and the only one "
        "where framing decides whether it can be counted at all. Fingertips on "
        "a wall for balance is fine."
    ),
    quality=QualitySpec(
        target_rom=0.13,
        consistency_target=0.02,
        consistency_ceiling=0.06,
        tempo_min_ms=600,
        tempo_max_ms=3_000,
        # Depth carries this one. Half a calf raise trains the half of the
        # range nobody was short of.
        w_consistency=0.20,
        w_depth=0.45,
        w_tempo=0.10,
        w_endurance=0.25,
        min_reps=15,
    ),
    load=LoadSpec(load_per_rep=0.15, throws_per_rep=0.0, tissue=Tissue.LOWER_BODY),
    tracks_handedness=False,
)

GEN_HANDSTAND_HOLD = DrillSpec(
    key="gen_handstand_hold",
    name="Wall Handstand",
    sport="general",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
    metric=Metric.HOLD_SECONDS,
    description=(
        "Feet up the wall, arms locked, and stay there. The clock only runs "
        "while you are actually upside down, so walking your feet back down "
        "the wall stops it."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.35),
    counter=CounterSpec(
        # The only negative band in the catalogue, and the reason this drill
        # needed no new signal: hip height is measured against the feet, so
        # putting the feet above the hips simply makes it negative. Nothing
        # else here ever goes below zero, so an inverted hold is unmistakable
        # rather than merely different.
        down_threshold=-2.40,
        up_threshold=-0.90,
        min_rep_ms=400,
        max_rep_ms=60_000,
    ),
    # The highest rate per minute anywhere, because it is the shortest hold
    # anywhere. Thirty honest seconds is a good set.
    scoring=ScoringSpec(xp_per_rep=0.0, xp_per_minute=55.0, daily_rep_cap=1_000),
    validation=ValidationSpec(
        max_reps_per_second=1.0, min_reps=0, min_duration_ms=10_000,
    ),
    setup_hint=(
        "Phone side-on, far enough back to see your feet and your hands at "
        "once. Clear the space behind you, hands about shoulder width, and "
        "come down the way you went up rather than falling out of it."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.0, load_per_minute=6.5, tissue=Tissue.UPPER_BODY),
    tracks_handedness=False,
)

GEN_DEAD_HANG = DrillSpec(
    key="gen_dead_hang",
    name="Dead Hang",
    sport="general",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
    metric=Metric.HOLD_SECONDS,
    description=(
        "Hang from a bar with your arms straight and stay there. The clock "
        "runs while you are hanging -- pull yourself up and it stops, because "
        "that is a different exercise and this one is about the grip."
    ),
    signal=SignalSpec(
        # The same head-against-hands measurement a pull-up counts on, held
        # still instead of cycled. The bands do not overlap: a pull-up finishes
        # where this drill has already stopped counting.
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="nose",
        reference="left_wrist",
        smoothing=0.35,
    ),
    counter=CounterSpec(
        # The top of this band is exactly where a pull-up arms. Set a shade
        # higher it overlapped the bottom of a pull-up, so the first fraction
        # of every rep of a different, harder exercise quietly banked hang
        # time as well.
        down_threshold=-0.55, up_threshold=-0.30, min_rep_ms=400, max_rep_ms=60_000,
    ),
    scoring=ScoringSpec(xp_per_rep=0.0, xp_per_minute=40.0, daily_rep_cap=1_000),
    validation=ValidationSpec(
        max_reps_per_second=1.0, min_reps=0, min_duration_ms=10_000,
    ),
    setup_hint=(
        "Phone side-on so it can see your head and your hands. Anything you "
        "can hang from that will hold you -- a bar, a beam, a set of monkey "
        "bars. Shoulders active rather than sagging."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.0, load_per_minute=5.0, tissue=Tissue.UPPER_BODY),
    tracks_handedness=False,
)


# --------------------------------------------------------------------------

SOCCER = BallSpec(
    required=True,
    contact="body",
    parts=("left_ankle", "right_ankle", "left_knee", "right_knee"),
    min_gap_ms=200,
    min_speed=0.22,
    attribute_side=True,
    detector="vision",
    colours=("white",),
    diameter_cm=20.5,
)


SOC_JUGGLE = DrillSpec(
    key="soc_juggle",
    name="Juggling",
    sport="soccer",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description="Keep it up. Counts every touch, and which foot took it.",
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=200, max_rep_ms=6_000,
    ),
    ball=BallSpec(
        required=True,
        contact="body",
        # Feet and thighs, and deliberately not the head.
        #
        # The head was in this list, which meant a child heading the ball in a
        # garden was counted and paid for it, with no age floor and no separate
        # volume anywhere. Youth football bans heading below about eleven and
        # limits it for years after, on concussion grounds -- and this app's
        # whole argument for the throwing axis is that repetitive volume nobody
        # counts is the thing that hurts children.
        #
        # A header now simply does not register. The touch is not punished and
        # nothing is said about it; it just earns nothing, which is the most
        # this drill should have to say about heading.
        parts=("left_ankle", "right_ankle", "left_knee", "right_knee"),
        min_gap_ms=200,
        min_speed=0.22,
        attribute_side=True,
        detector="vision",
        colours=("white",),
        diameter_cm=20.5,
    ),
    scoring=ScoringSpec(xp_per_rep=0.9, daily_rep_cap=600, diminishing_after_reps=200),
    validation=ValidationSpec(max_reps_per_second=3.0, min_reps=6),
    setup_hint="Prop the phone up anywhere it can see you and the ball. Any angle.",
    quality=None,
    load=LoadSpec(load_per_rep=0.3, load_per_minute=1.6, tissue=Tissue.LOWER_BODY),
    tracks_handedness=True,
)

SOC_JUGGLE_WEAK = DrillSpec(
    key="soc_juggle_weak",
    name="Weak-Foot Juggling",
    sport="soccer",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Weak foot only, for as long as you can keep it up. The app reads "
        "which foot took every touch, so this is one of the few things here it "
        "can genuinely confirm -- and weak-side touches are paid at a premium "
        "wherever you do them."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=220, max_rep_ms=6_000,
    ),
    # The same rule the weak-hand pound uses, reading a foot instead of a hand.
    ball=replace(SOCCER, alternation="same_hand", min_gap_ms=220),
    scoring=ScoringSpec(xp_per_rep=1.4, daily_rep_cap=400, diminishing_after_reps=150),
    validation=ValidationSpec(max_reps_per_second=3.0, min_reps=8),
    setup_hint=(
        "Weak foot only -- if the other one touches it, start the count again. "
        "Phone low enough to see your feet and the ball."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.3, load_per_minute=1.6, tissue=Tissue.LOWER_BODY),
    tracks_handedness=True,
)

SOC_JUGGLE_ALT = DrillSpec(
    key="soc_juggle_alt",
    name="Alternating Juggling",
    sport="soccer",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Left, right, left, right, without letting it drop. The app checks the "
        "ball really is changing feet -- if it settles onto your strong side it "
        "counts as ordinary juggling, and says so."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=240, max_rep_ms=6_000,
    ),
    ball=replace(SOCCER, alternation="alternating", min_gap_ms=240),
    scoring=ScoringSpec(xp_per_rep=1.3, daily_rep_cap=400, diminishing_after_reps=150),
    validation=ValidationSpec(max_reps_per_second=2.8, min_reps=12),
    setup_hint=(
        "Every other touch on the other foot. Small touches, knee height, and "
        "stay on the balls of your feet."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.3, load_per_minute=1.6, tissue=Tissue.LOWER_BODY),
    tracks_handedness=True,
)

SOC_THIGH = DrillSpec(
    key="soc_thigh",
    name="Thigh Juggling",
    sport="soccer",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Off the thigh, not the foot. Only thigh touches register -- a ball "
        "played off your laces is too far from your knee for this drill to see "
        "it, so it counts nothing."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=350, max_rep_ms=6_000,
    ),
    # Contact location is the whole discrimination, the same principle the
    # volleyball hands gate uses: a foot touch is nowhere near the knee, so it
    # simply is not a contact as far as this drill is concerned.
    ball=replace(
        SOCCER, parts=("left_knee", "right_knee"), min_gap_ms=350, min_speed=0.18,
    ),
    scoring=ScoringSpec(xp_per_rep=1.2, daily_rep_cap=300, diminishing_after_reps=120),
    validation=ValidationSpec(max_reps_per_second=2.0, min_reps=8),
    setup_hint=(
        "Thigh flat and level, knee up to about waist height. Phone side-on so "
        "it can see your thigh meet the ball."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.35, load_per_minute=1.5, tissue=Tissue.LOWER_BODY),
    tracks_handedness=True,
)

SOC_WALL_PASS = DrillSpec(
    key="soc_wall_pass",
    name="Wall Passing",
    sport="soccer",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Pass firmly into a wall and control the return, over and over. This "
        "one has a strike-speed floor rather than a ceiling -- a soft touch "
        "does not clear it, which is how the app knows it was a pass and not a "
        "juggle."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=500, max_rep_ms=8_000,
    ),
    # The speed floor is the verification. Nothing else separates a pass from a
    # juggling touch -- both are the ball coming off a foot -- and a struck pass
    # leaves the boot far faster than a touch that is only keeping it up.
    ball=replace(
        SOCCER, parts=("left_ankle", "right_ankle"),
        min_gap_ms=500, min_speed=0.60,
    ),
    scoring=ScoringSpec(xp_per_rep=1.3, daily_rep_cap=300, diminishing_after_reps=140),
    validation=ValidationSpec(max_reps_per_second=1.6, min_reps=10, min_duration_ms=20_000),
    setup_hint=(
        "Find a wall nobody parks a car behind. Two or three metres back, phone "
        "side-on. Strike it properly -- a pass you would actually make in a game."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.5, load_per_minute=1.4, tissue=Tissue.LOWER_BODY),
    tracks_handedness=True,
)

SOC_TOE_TAPS = DrillSpec(
    key="soc_toe_taps",
    name="Toe Taps",
    sport="soccer",
    category=Category.SPEED,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Ball still on the ground, tapping the top of it foot to foot as fast "
        "as you can hold it together. There is a speed floor here: a slow tap "
        "is standing on a ball, and it does not count."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=110, max_rep_ms=2_000,
    ),
    ball=replace(
        SOCCER, parts=("left_ankle", "right_ankle"),
        alternation="alternating", min_gap_ms=110, min_speed=0.10,
    ),
    scoring=ScoringSpec(xp_per_rep=0.4, daily_rep_cap=900, diminishing_after_reps=350),
    validation=ValidationSpec(
        max_reps_per_second=7.0,
        # The floor is what separates this from standing over a ball. Nobody
        # taps this fast by accident.
        min_reps_per_second=2.0,
        min_reps=30, min_duration_ms=15_000,
    ),
    setup_hint=(
        "Ball still, phone low and in front. Stay on your toes and keep your "
        "chest up -- if you are looking down at it, slow down."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.08, load_per_minute=2.2, tissue=Tissue.LOWER_BODY),
    tracks_handedness=True,
)

SOC_SHUFFLE = DrillSpec(
    key="soc_shuffle",
    name="Defending Shuffle",
    sport="soccer",
    category=Category.AGILITY,
    stimulus=Stimulus.QUICKNESS,
    metric=Metric.REPS,
    description=(
        "Side-on defending stance, shuffling across without crossing your feet. "
        "One rep is one push. It measures how far apart your feet get, and it "
        "can see when they cross -- which is the moment a winger goes past you."
    ),
    signal=SignalSpec(kind=SignalKind.STANCE_WIDTH, smoothing=0.45),
    counter=CounterSpec(
        # Deliberately identical to the basketball slide. It is the same
        # movement measured the same way, and the app cannot tell a defender
        # jockeying a winger from a guard sliding -- so it must not pay
        # differently for the sport's name.
        down_threshold=1.30,
        up_threshold=1.80,
        min_rep_ms=280,
        max_rep_ms=3_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=300, diminishing_after_reps=140),
    validation=ValidationSpec(
        max_reps_per_second=3.0, min_reps_per_second=0.15,
        min_reps=10, min_duration_ms=20_000,
    ),
    setup_hint=(
        "Phone square in front of you, far enough back to see both feet. Stay "
        "side-on, do not cross your feet, and do not dive in."
    ),
    quality=QualitySpec(
        target_rom=0.70,
        consistency_target=0.18,
        tempo_min_ms=280,
        tempo_max_ms=1_400,
        w_consistency=0.30,
        w_depth=0.35,
        w_tempo=0.20,
        w_endurance=0.15,
        min_reps=12,
    ),
    load=LoadSpec(load_per_rep=1.1, throws_per_rep=0.0, tissue=Tissue.LOWER_BODY),
    tracks_handedness=True,
)


# --------------------------------------------------------------------------
# Basketball
#
# The ball is the detector's easiest subject in the whole catalogue -- 23cm and
# orange against a driveway -- which is why this sport can afford `count` mode
# where lacrosse could not. The bounce is the rep.
#
# Every variant below differs from a plain dribble in something the app can
# actually check: the hands alternate, or they do not, or the tempo has a floor
# a slow dribble cannot clear. That is the lesson from the wall-ball family
# applied before the mistake rather than after it -- the one pattern here that
# is genuinely indistinguishable is marked `pattern_verified=False` and paid the
# plain rate.
# --------------------------------------------------------------------------

BASKETBALL = BallSpec(
    required=True,
    # The floor, not the hand: the bounce is the crisp, unambiguous event, and
    # the hand is read from whichever wrist is nearest at the time.
    contact="ground",
    parts=("left_wrist", "right_wrist"),
    min_gap_ms=150,
    min_speed=0.30,
    attribute_side=True,
    detector="vision",
    colours=("basketball",),
    diameter_cm=23.0,
)


BKB_DRIBBLE = DrillSpec(
    key="bkb_dribble",
    name="Dribbling",
    sport="basketball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description="Counts every bounce, and which hand is on it.",
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=140, max_rep_ms=4_000,
    ),
    ball=BASKETBALL,
    scoring=ScoringSpec(xp_per_rep=0.4, daily_rep_cap=900, diminishing_after_reps=300),
    validation=ValidationSpec(max_reps_per_second=5.0, min_reps=10),
    setup_hint="Prop the phone up so it can see your hands and the floor. Any angle.",
    quality=None,
    load=LoadSpec(load_per_rep=0.15, load_per_minute=1.4, tissue=Tissue.WHOLE_BODY),
    tracks_handedness=True,
)


BKB_CROSSOVER = DrillSpec(
    key="bkb_crossover",
    name="Crossover",
    sport="basketball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Push the ball hard from one hand to the other, low and in front of "
        "you, over and over. The app checks the ball actually keeps changing "
        "hands -- if it stays on your strong hand it counts as dribbling, and "
        "says so."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=170, max_rep_ms=4_000,
    ),
    # The one thing hand attribution can genuinely establish, so this is the
    # one variant that has earned the right to pay more than a plain dribble.
    ball=replace(BASKETBALL, alternation="alternating", min_gap_ms=170),
    scoring=ScoringSpec(xp_per_rep=0.7, daily_rep_cap=600, diminishing_after_reps=250),
    validation=ValidationSpec(max_reps_per_second=4.0, min_reps=12),
    setup_hint=(
        "Phone where it can see the floor in front of your feet. Stay low and "
        "keep the ball below your knees -- a high crossover is a stolen ball."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.2, load_per_minute=1.6, tissue=Tissue.WHOLE_BODY),
    tracks_handedness=True,
)

BKB_BETWEEN_LEGS = DrillSpec(
    key="bkb_between_legs",
    name="Between the Legs",
    sport="basketball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Same change of hands, through your legs instead of in front. The app "
        "counts the bounces and sees the hands swap, but it cannot see whether "
        "the ball went through your legs -- so this earns the same as a "
        "crossover."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=200, max_rep_ms=4_000,
    ),
    ball=replace(BASKETBALL, alternation="alternating", min_gap_ms=200),
    # Deliberately identical to the crossover. The hands do a checkable thing;
    # the legs do not, and the wall-ball family is what happens when a
    # catalogue pays for the half it cannot see.
    pattern_verified=False,
    scoring=ScoringSpec(xp_per_rep=0.7, daily_rep_cap=500, diminishing_after_reps=200),
    validation=ValidationSpec(max_reps_per_second=3.5, min_reps=12),
    setup_hint=(
        "Phone low and square to you. Step into it -- the ball goes through as "
        "your foot comes forward, not while you are standing still."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.25, load_per_minute=1.7, tissue=Tissue.WHOLE_BODY),
    tracks_handedness=True,
)

BKB_POUND_WEAK = DrillSpec(
    key="bkb_pound_weak",
    name="Weak-Hand Pound",
    sport="basketball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Hard, low dribbles on your weak hand only, for as long as you can "
        "stand it. The app reads which hand is on the ball, so this is one of "
        "the few things here it can genuinely confirm -- and weak-hand reps "
        "are paid at a premium wherever you do them."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=130, max_rep_ms=3_000,
    ),
    ball=replace(BASKETBALL, alternation="same_hand", min_gap_ms=130),
    scoring=ScoringSpec(xp_per_rep=0.7, daily_rep_cap=500, diminishing_after_reps=200),
    validation=ValidationSpec(
        max_reps_per_second=5.5,
        # A pound dribble is hard and fast by definition. This floor is what
        # separates it from standing there patting the ball.
        min_reps_per_second=0.8,
        min_reps=15,
    ),
    setup_hint=(
        "Weak hand only. Knees bent, ball below your knee, and pound it -- if "
        "it is coming back above your waist you are patting it, not pounding."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.2, load_per_minute=1.8, tissue=Tissue.WHOLE_BODY),
    tracks_handedness=True,
)

BKB_POUND_LOW = DrillSpec(
    key="bkb_pound_low",
    name="Low Pound",
    sport="basketball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Both hands, ball below the knee, as hard and as fast as you can keep "
        "it. This one has a speed floor rather than a ceiling: a slow dribble "
        "does not clear it, which is how the app knows it was a pound."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=120, max_rep_ms=2_500,
    ),
    ball=replace(BASKETBALL, min_gap_ms=120),
    scoring=ScoringSpec(xp_per_rep=0.6, daily_rep_cap=700, diminishing_after_reps=300),
    validation=ValidationSpec(
        max_reps_per_second=6.0,
        # The floor is the whole verification. Nothing else here distinguishes
        # a low pound from an ordinary dribble, and a rate this high is not
        # something a standing dribble reaches.
        min_reps_per_second=1.2,
        min_reps=20,
    ),
    setup_hint=(
        "Phone low so it can see the ball at knee height. Wide base, chest up, "
        "and drive it into the floor."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.2, load_per_minute=2.0, tissue=Tissue.WHOLE_BODY),
    tracks_handedness=True,
)

BKB_WALL_PASS = DrillSpec(
    key="bkb_wall_pass",
    name="Wall Passes",
    sport="basketball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Two-hand chest pass into a wall and catch it clean. The only drill "
        "here the app can tell apart from dribbling without ambiguity: the "
        "ball comes off your hands rather than off the floor."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=350, max_rep_ms=5_000,
    ),
    # Contact off the body rather than the ground, which is a different event
    # entirely and needs no inference to separate.
    ball=replace(
        BASKETBALL, contact="body", min_gap_ms=350, min_speed=0.45,
        attribute_side=False,
    ),
    scoring=ScoringSpec(xp_per_rep=0.9, daily_rep_cap=400, diminishing_after_reps=180),
    validation=ValidationSpec(max_reps_per_second=2.5, min_reps=10),
    setup_hint=(
        "Stand about two metres off a solid wall, phone side-on. Step into "
        "each pass. Do not use a garage door somebody parks a car behind."
    ),
    quality=None,
    load=LoadSpec(
        load_per_rep=0.4, load_per_minute=1.2,
        # Chest passes are a push, not an overhead throw, so this does not
        # touch the throwing axis a shoulder advisory reads.
        throws_per_rep=0.0, tissue=Tissue.UPPER_BODY,
    ),
    tracks_handedness=False,
)



BKB_FORM_SHOT = DrillSpec(
    key="bkb_form_shot",
    name="Form Shooting",
    sport="basketball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "One hand, close to a wall or straight up to yourself. Dip, rise, "
        "release, hold the follow-through. It counts your shots and watches "
        "one thing: whether your elbow stayed under the ball. It has no idea "
        "whether anything went in -- there is no hoop in this drill and the "
        "app cannot see one."
    ),
    signal=SignalSpec(
        # Picks the shooting arm per frame rather than naming a side, because a
        # left-handed shooter with both arms visible would otherwise be measured
        # on the arm that is not shooting -- and handedness cannot live in a
        # spec that every athlete shares.
        kind=SignalKind.SHOOTING_ARM,
        smoothing=0.30,
    ),
    counter=CounterSpec(
        # Elbow flexed into the dip, then extended through release. A shooting
        # pocket sits near 60 degrees; a released arm is nearly straight.
        down_threshold=95.0,
        up_threshold=155.0,
        min_rep_ms=600,
        max_rep_ms=6_000,
        rising_completes=True,
    ),
    # Confirm, never count. The pose finds the shot; the ball's job is only to
    # establish there was one, and a missed detection is a note rather than a
    # refusal -- the same rule every lacrosse drill follows.
    ball=replace(
        BASKETBALL, mode="confirm", required=False, contact="body",
        min_gap_ms=600, min_speed=0.35, attribute_side=False,
        min_track_quality=0.30,
    ),
    scoring=ScoringSpec(xp_per_rep=1.2, daily_rep_cap=250, diminishing_after_reps=120),
    validation=ValidationSpec(
        max_reps_per_second=1.5, min_reps_per_second=0.05,
        min_reps=10, min_duration_ms=30_000,
    ),
    setup_hint=(
        "Phone square in front of you at chest height, close enough to see "
        "your shooting elbow clearly. Turned sideways it cannot tell an elbow "
        "under the ball from one flared out. One hand only -- the guide hand "
        "comes off."
    ),
    quality=QualitySpec(
        # Dip to release, in degrees of elbow extension.
        target_rom=85.0,
        # The tightest consistency target in the catalogue, and deliberately so:
        # form shooting is not about range or effort, it is about doing the
        # identical thing every time.
        consistency_target=0.10,
        consistency_ceiling=0.35,
        tempo_min_ms=600,
        tempo_max_ms=2_500,
        w_consistency=0.45,
        w_depth=0.25,
        w_tempo=0.15,
        w_endurance=0.15,
        min_reps=12,
    ),
    load=LoadSpec(
        load_per_rep=0.5,
        # A shot is an overhead push, not a throw. It does not belong on the
        # axis a pitch count reads, and putting it there would make an evening
        # of form shooting look like an evening of throwing.
        throws_per_rep=0.0,
        tissue=Tissue.UPPER_BODY,
    ),
    # Records which hand shot, which is how a left-handed shooter shows up as
    # left rather than as an anomaly.
    tracks_handedness=True,
)

BKB_SLIDE = DrillSpec(
    key="bkb_slide",
    name="Defensive Slides",
    sport="basketball",
    category=Category.AGILITY,
    stimulus=Stimulus.QUICKNESS,
    metric=Metric.REPS,
    description=(
        "Push off the back foot, step out with the front, then slide the back "
        "foot in. One rep is one push. The app measures how far apart your "
        "feet are, so a step that never really goes anywhere does not count -- "
        "and it can see when your feet cross, which is the one thing that "
        "makes a slide stop working."
    ),
    signal=SignalSpec(
        # The first horizontal signal in the catalogue, and the reason this
        # drill can exist at all. Everything else measures a height or an
        # angle, which is why the most common footwork in the sport had no
        # drill anywhere.
        kind=SignalKind.STANCE_WIDTH,
        # Light: the push is quick, and a heavy filter would flatten the step
        # out of it.
        smoothing=0.45,
    ),
    counter=CounterSpec(
        # A defensive stance is already wider than the shoulders -- around 1.3
        # torso lengths at the feet -- and a real slide step takes it past 1.8
        # before the trail foot catches up.
        down_threshold=1.30,
        up_threshold=1.80,
        min_rep_ms=280,
        max_rep_ms=3_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=300, diminishing_after_reps=140),
    validation=ValidationSpec(
        max_reps_per_second=3.0, min_reps_per_second=0.15,
        min_reps=10, min_duration_ms=20_000,
    ),
    setup_hint=(
        "Phone square in front of you, far enough back to see both feet. Get "
        "in your stance and slide -- push off the back foot, do not hop, and "
        "never let your feet cross."
    ),
    quality=QualitySpec(
        # Ready stance to full extension and back, in torso lengths at the feet.
        target_rom=0.70,
        consistency_target=0.18,
        tempo_min_ms=280,
        tempo_max_ms=1_400,
        w_consistency=0.30,
        w_depth=0.35,
        w_tempo=0.20,
        w_endurance=0.15,
        min_reps=12,
    ),
    load=LoadSpec(
        load_per_rep=1.1,
        # Nothing overhead, so this must not touch throwing volume.
        throws_per_rep=0.0,
        tissue=Tissue.LOWER_BODY,
    ),
    # Which foot led the step, so a squad that can only slide one way shows up.
    tracks_handedness=True,
)

BKB_STANCE = DrillSpec(
    key="bkb_stance",
    name="Defensive Stance",
    sport="basketball",
    category=Category.CONDITIONING,
    stimulus=Stimulus.STRENGTH,
    metric=Metric.HOLD_SECONDS,
    description=(
        "Sit in a real defensive stance and stay there. The clock only runs "
        "while your hips are actually down -- stand up and it stops, which is "
        "the entire point of the drill."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.35),
    # A hold drill scores time inside a band rather than counting a cycle.
    # Above 0.78 the athlete has stood up; below 0.52 they have sat down on
    # their heels, which is a different exercise and not this one.
    counter=CounterSpec(
        down_threshold=0.52, up_threshold=0.78, min_rep_ms=400, max_rep_ms=60_000,
    ),
    scoring=ScoringSpec(xp_per_rep=0.0, xp_per_minute=26.0, daily_rep_cap=1_000),
    validation=ValidationSpec(
        max_reps_per_second=1.0, min_reps=0, min_duration_ms=20_000,
    ),
    setup_hint=(
        "Phone side-on at about knee height so it can see how low you really "
        "are. Feet wide, chest up, hands out. No leaning on anything."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.0, load_per_minute=3.4, tissue=Tissue.LOWER_BODY),
    tracks_handedness=False,
)


# --------------------------------------------------------------------------
# Volleyball
#
# Unusually good for this catalogue, because the three basic skills contact the
# ball in three different places: a set above the head, a forearm pass below the
# shoulders, a hit off one hand overhead. Two of those are separated by the
# hands gate and the third by hand attribution, so every drill that pays more
# than the baseline has earned it on something checkable rather than on a name.
# --------------------------------------------------------------------------

VOLLEYBALL = BallSpec(
    required=True,
    contact="body",
    parts=("left_wrist", "right_wrist", "nose"),
    min_gap_ms=350,
    min_speed=0.28,
    attribute_side=False,
    detector="vision",
    colours=("white",),
    diameter_cm=21.0,
)


VB_SET = DrillSpec(
    key="vb_set",
    name="Setting",
    sport="volleyball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description="Set it straight up, over and over. Counts every clean contact.",
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=350, max_rep_ms=6_000,
    ),
    # Above the shoulders, which is what makes this a set and not a pass.
    ball=replace(VOLLEYBALL, hands="above_shoulders"),
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=500, diminishing_after_reps=180),
    validation=ValidationSpec(max_reps_per_second=2.0, min_reps=6),
    setup_hint="Prop the phone up so it can see you and the top of the ball's flight.",
    quality=None,
    load=LoadSpec(load_per_rep=0.3, load_per_minute=1.4, tissue=Tissue.UPPER_BODY),
)

VB_PASS = DrillSpec(
    key="vb_pass",
    name="Forearm Passing",
    sport="volleyball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Bump the ball straight up off your platform, over and over. The app "
        "checks your hands are below your shoulders -- a pass played up at "
        "head height is a set, and it counts as one."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=400, max_rep_ms=6_000,
    ),
    # The other side of the gate from the set. Between them they cover the two
    # skills that are otherwise the same event to the detector.
    ball=replace(
        VOLLEYBALL, hands="below_shoulders",
        parts=("left_elbow", "right_elbow", "left_wrist", "right_wrist"),
        min_gap_ms=400,
    ),
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=500, diminishing_after_reps=180),
    validation=ValidationSpec(max_reps_per_second=2.5, min_reps=10),
    setup_hint=(
        "Phone square in front of you so it can see your arms and the ball. "
        "Platform flat, thumbs together, and move your feet rather than "
        "swinging your arms."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.3, load_per_minute=1.5, tissue=Tissue.UPPER_BODY),
    tracks_handedness=False,
)

VB_SERVE = DrillSpec(
    key="vb_serve",
    name="Serving",
    sport="volleyball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Toss and serve into a wall, one hand, over and over. The app reads "
        "which hand struck it, so a serve is genuinely tellable from a set -- "
        "and it has no idea whether the ball would have gone in."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=1_200, max_rep_ms=12_000,
    ),
    # One hand, above the shoulders, and the same hand every time. All three
    # are checkable, which is why this one earns more than a set.
    ball=replace(
        VOLLEYBALL, hands="above_shoulders", attribute_side=True,
        alternation="same_hand", min_gap_ms=1_200, min_speed=0.45,
    ),
    scoring=ScoringSpec(xp_per_rep=1.6, daily_rep_cap=200, diminishing_after_reps=90),
    validation=ValidationSpec(max_reps_per_second=0.8, min_reps=8, min_duration_ms=30_000),
    setup_hint=(
        "Find a wall nobody parks a car behind and stand well back. Phone "
        "side-on so it sees your toss and your hitting arm. Same toss every "
        "time -- that is the whole serve."
    ),
    quality=None,
    load=LoadSpec(
        load_per_rep=1.0, load_per_minute=0.6,
        # A serve is the one volleyball action that genuinely belongs on the
        # throwing axis. It is the same overhead mechanism a pitch count exists
        # to watch, and a serving shoulder gets hurt the same way.
        throws_per_rep=1.0, tissue=Tissue.THROWING,
    ),
    tracks_handedness=True,
)

VB_ARM_SWING = DrillSpec(
    key="vb_arm_swing",
    name="Arm Swing",
    sport="volleyball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "The hitting swing on its own, no ball needed. Draw the elbow back and "
        "high, then swing through and finish. It watches your hitting arm and "
        "counts full swings -- a lazy half swing does not register."
    ),
    signal=SignalSpec(
        # The same signal the basketball shot uses, and for the same reason: it
        # picks the swinging arm out of the frame rather than naming a side, so
        # a left-handed hitter is measured on the arm that is actually working.
        kind=SignalKind.SHOOTING_ARM,
        smoothing=0.28,
    ),
    counter=CounterSpec(
        # Elbow drawn back and flexed, then extended through contact.
        down_threshold=90.0,
        up_threshold=158.0,
        min_rep_ms=500,
        max_rep_ms=5_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.2, daily_rep_cap=300, diminishing_after_reps=140),
    # Deliberately the same rate as the basketball form shot. Both are one
    # armed overhead extensions and the elbow angle cannot tell them apart --
    # the signal generalises across the two sports, and so does the ambiguity.
    # Paying one more than the other would be paying for the sport's name.
    validation=ValidationSpec(
        max_reps_per_second=1.8, min_reps_per_second=0.05,
        min_reps=12, min_duration_ms=25_000,
    ),
    setup_hint=(
        "Phone square in front of you, far enough back to see your whole arm. "
        "Turned sideways it cannot tell a high elbow from a dropped one. No "
        "ball -- this is the swing on its own."
    ),
    quality=QualitySpec(
        target_rom=80.0,
        # A hitter's swing has to be the same every time before it can be fast,
        # so consistency carries the most weight here.
        consistency_target=0.12,
        consistency_ceiling=0.38,
        tempo_min_ms=500,
        tempo_max_ms=2_200,
        w_consistency=0.40,
        w_depth=0.30,
        w_tempo=0.15,
        w_endurance=0.15,
        min_reps=12,
    ),
    load=LoadSpec(
        load_per_rep=0.6,
        # Overhead and repeated, so it belongs on the throwing axis even
        # without a ball. A hundred swings is a hundred swings to a shoulder.
        throws_per_rep=1.0, tissue=Tissue.THROWING,
    ),
    tracks_handedness=True,
)

VB_APPROACH = DrillSpec(
    key="vb_approach",
    name="Approach Jump",
    sport="volleyball",
    category=Category.SPEED,
    stimulus=Stimulus.POWER,
    metric=Metric.REPS,
    description=(
        "The full approach and jump, landing balanced. Counts each jump from "
        "how far your hips travel, so a hop off two feet does not read as an "
        "approach."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.35),
    counter=CounterSpec(
        # Deeper and higher than a squat jump: the approach loads further down
        # and the jump goes further up, and the band has to sit outside the
        # general jump drills or the two would count each other.
        down_threshold=0.38,
        up_threshold=1.12,
        min_rep_ms=900,
        max_rep_ms=8_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=2.2, daily_rep_cap=120, diminishing_after_reps=60),
    validation=ValidationSpec(
        max_reps_per_second=1.0, min_reps_per_second=0.03,
        min_reps=8, min_duration_ms=30_000,
    ),
    setup_hint=(
        "You need a few metres of run-up and a clear landing. Phone side-on "
        "at hip height. Land on two feet, bend your knees, and stop -- the "
        "landing is the part that keeps you playing."
    ),
    quality=QualitySpec(
        target_rom=0.72,
        consistency_target=0.16,
        tempo_min_ms=900,
        tempo_max_ms=4_000,
        w_consistency=0.25,
        w_depth=0.35,
        w_tempo=0.10,
        w_endurance=0.30,
        min_reps=8,
    ),
    load=LoadSpec(
        # The heaviest landing in the catalogue, above a tuck jump, because a
        # maximal jump off a run-up comes down from higher than a standing one.
        # Jumper's knee is the injury this sport hands teenagers, and a hundred
        # approach jumps in a driveway is a real week's landing volume.
        load_per_rep=2.6,
        throws_per_rep=0.0, tissue=Tissue.LOWER_BODY,
    ),
    tracks_handedness=False,
)

VB_BLOCK_JUMP = DrillSpec(
    key="vb_block_jump",
    name="Block Jump",
    sport="volleyball",
    category=Category.SPEED,
    stimulus=Stimulus.POWER,
    metric=Metric.REPS,
    description=(
        "From a blocking stance: hands up, jump straight, press over, land "
        "where you took off. No approach and no swing -- this one is about "
        "getting up quickly from standing and coming down under control."
    ),
    signal=SignalSpec(
        # Wrists against the shoulder line rather than hip height, because a
        # block is judged on the hands getting up rather than the feet leaving
        # the floor -- and that also keeps it clear of every jump drill in the
        # catalogue, which all read the hips.
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="right_wrist",
        reference="right_shoulder",
        smoothing=0.30,
    ),
    counter=CounterSpec(
        down_threshold=0.20,
        up_threshold=0.62,
        min_rep_ms=700,
        max_rep_ms=6_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.5, daily_rep_cap=180, diminishing_after_reps=90),
    validation=ValidationSpec(
        max_reps_per_second=1.5, min_reps_per_second=0.04,
        min_reps=10, min_duration_ms=25_000,
    ),
    setup_hint=(
        "Phone square in front of you so it can see both hands. Start with "
        "your hands already up at your shoulders -- a block that starts from "
        "your waist is a block that arrives late."
    ),
    quality=QualitySpec(
        target_rom=0.46,
        consistency_target=0.15,
        tempo_min_ms=700,
        tempo_max_ms=3_000,
        w_consistency=0.30,
        w_depth=0.35,
        w_tempo=0.15,
        w_endurance=0.20,
        min_reps=10,
    ),
    load=LoadSpec(load_per_rep=1.6, throws_per_rep=0.0, tissue=Tissue.LOWER_BODY),
    tracks_handedness=False,
)

VB_SET_WALL = DrillSpec(
    key="vb_set_wall",
    name="Wall Setting",
    sport="volleyball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Set against a wall from close range, quick and repeated. Faster than "
        "setting to yourself, which is the point. The app counts the contacts "
        "and cannot tell a wall from the ceiling, so this earns the same as "
        "any other set."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=280, max_rep_ms=4_000,
    ),
    ball=replace(VOLLEYBALL, hands="above_shoulders", min_gap_ms=280),
    # Hands above the shoulders and a ball off them: identical to a set in
    # everything the camera can reach. Only the wall differs, and there is no
    # wall in the skeleton.
    pattern_verified=False,
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=400, diminishing_after_reps=160),
    validation=ValidationSpec(
        max_reps_per_second=3.5,
        # The one thing that does separate it: wall setting is quick, and a
        # slow rally against a wall is just setting to yourself.
        min_reps_per_second=0.6,
        min_reps=15,
    ),
    setup_hint=(
        "Stand a metre off a wall with the phone side-on. Hands above your "
        "forehead the whole time -- if they drop, you are passing."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.3, load_per_minute=1.8, tissue=Tissue.UPPER_BODY),
    tracks_handedness=False,
)


# --------------------------------------------------------------------------
# Baseball and softball
#
# The sport where the load model matters most and where it had the least to say.
# Youth throwing volume is the single most-studied injury risk in this catalogue
# and the model only had a week-on-week spike check -- blind to the athlete who
# throws a lot every week and always has, which is the pattern that actually
# hurts arms. `load.throw_ceiling` is the answer, and every throwing drill below
# feeds it.
#
# The two sports share almost everything and diverge at exactly one place: a
# softball pitcher throws underhand in a full arm circle, which is a different
# motion with a different injury profile, and gets its own drill.
# --------------------------------------------------------------------------

#: Sports whose plans legitimately draw on another sport's drills.
#:
#: A softball player throws, fields and hits with the same motions a baseball
#: player does, so five of the six diamond drills are keyed `bb_` and shared
#: rather than duplicated under a second prefix. Only the windmill is softball's
#: alone, because it is the one motion the two sports genuinely do not share.
#:
#: Declared rather than inferred from key prefixes, so a guard asking "does this
#: position prescribe any of its own sport's work" gets a true answer instead of
#: one that depends on how a drill happens to be named.
SHARES_DRILLS_WITH: dict[str, str] = {"softball": "baseball"}


def drill_sports(sport: str) -> frozenset[str]:
    """Every sport whose drills count as this sport's own work."""
    shared = SHARES_DRILLS_WITH.get(sport)
    return frozenset({sport} if shared is None else {sport, shared})


BASEBALL_BALL = BallSpec(
    required=True,
    contact="body",
    parts=("left_wrist", "right_wrist"),
    min_gap_ms=500,
    min_speed=0.35,
    attribute_side=True,
    detector="vision",
    colours=("white",),
    # A baseball. Softball's is larger, but every drill sharing this spec is
    # one both sports do with a baseball-sized ball -- the windmill, which is
    # the genuinely softball-specific motion, is counted from the arm and needs
    # no ball at all.
    diameter_cm=7.4,
)


BB_WALL_THROW = DrillSpec(
    key="bb_wall_throw",
    name="Wall Throws",
    sport="baseball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description="Throw and field off a wall. Counts every catch.",
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=500, max_rep_ms=8_000,
    ),
    ball=BASEBALL_BALL,
    scoring=ScoringSpec(xp_per_rep=1.2, daily_rep_cap=400, diminishing_after_reps=150),
    validation=ValidationSpec(max_reps_per_second=1.6, min_reps=6),
    setup_hint="Prop the phone up so it can see you and the wall. Any angle.",
    quality=None,
    load=LoadSpec(
        load_per_rep=1.0,
        # Throwing volume is the number this whole load model was built to
        # watch, and it is the reason a young arm gets hurt.
        throws_per_rep=1.0,
        tissue=Tissue.THROWING,
    ),
    tracks_handedness=True,
)

BB_LONG_TOSS = DrillSpec(
    key="bb_long_toss",
    name="Long Toss",
    sport="baseball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Back up and throw it properly, with a crow hop and a full arm. Fewer "
        "throws, harder ones. Every rep counts as a throw against the day's "
        "arm total, which is the number worth watching in this sport."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=2_500, max_rep_ms=20_000,
    ),
    # A long toss leaves the hand far faster than a catch-play throw, and the
    # gap between them is much longer. Both are checkable, which is what lets
    # this pay more than a wall throw.
    ball=replace(BASEBALL_BALL, min_gap_ms=2_500, min_speed=0.70),
    scoring=ScoringSpec(xp_per_rep=2.0, daily_rep_cap=80, diminishing_after_reps=40),
    validation=ValidationSpec(
        max_reps_per_second=0.4, min_reps=8, min_duration_ms=60_000,
    ),
    setup_hint=(
        "Somewhere with room and a partner or a net. Phone side-on. Crow hop "
        "into every one -- if you are throwing flat-footed, come in closer."
    ),
    quality=None,
    load=LoadSpec(
        load_per_rep=1.6,
        # Each of these is a harder throw than a wall throw, and the arm knows
        # it. Counting them one-for-one would understate the day.
        throws_per_rep=1.5, tissue=Tissue.THROWING,
    ),
    tracks_handedness=True,
)

BB_QUICK_HANDS = DrillSpec(
    key="bb_quick_hands",
    name="Quick Hands",
    sport="baseball",
    category=Category.SPEED,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Short, quick transfers into the wall from close range -- glove to "
        "hand to release. There is a speed floor here: a long toss cannot be "
        "done this fast, which is how the app knows these were transfers."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=700, max_rep_ms=5_000,
    ),
    ball=replace(BASEBALL_BALL, min_gap_ms=700, min_speed=0.40),
    scoring=ScoringSpec(xp_per_rep=0.9, daily_rep_cap=250, diminishing_after_reps=120),
    validation=ValidationSpec(
        max_reps_per_second=1.6,
        # The verification. A proper throw cannot be repeated at this rate.
        min_reps_per_second=0.45,
        min_reps=20, min_duration_ms=30_000,
    ),
    setup_hint=(
        "Close to the wall, phone side-on. Short arm action -- this is about "
        "the transfer, not the throw. Feet moving the whole time."
    ),
    quality=None,
    load=LoadSpec(
        load_per_rep=0.5,
        # Short and submaximal, but still overhead and still repeated, so it
        # belongs on the arm's ledger at a reduced rate rather than at none.
        throws_per_rep=0.4, tissue=Tissue.THROWING,
    ),
    tracks_handedness=True,
)

BB_TEE_SWING = DrillSpec(
    key="bb_tee_swing",
    name="Tee Swings",
    sport="baseball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Off a tee, same swing every time. It reads your hands travelling out "
        "from your body and back, so a full swing counts and a half-hearted "
        "one does not. It has no idea where the ball went."
    ),
    signal=SignalSpec(
        # The same signal the goalie save uses, which is not as odd as it
        # sounds: it measures how far the hands, TOGETHER, are from the chest.
        # A bat is held in two hands, so a swing is exactly that -- loaded back
        # near the shoulder, extended through the zone, and round.
        kind=SignalKind.SAVE_REACH,
        smoothing=0.35,
    ),
    counter=CounterSpec(
        # A batter's load is hands back at the rear shoulder, which is further
        # from the chest than a goalie's ready position -- not closer, which is
        # what 0.55 assumed. The subsumption guard caught it: at 0.55 this band
        # swallowed the goalie save's whole range, so a bat swing fired that
        # drill's thresholds and the app could not tell the two apart on reach
        # alone. Corrected upward to what a load actually is, which also puts
        # the two bands genuinely clear of one another.
        down_threshold=0.72,
        up_threshold=1.25,
        min_rep_ms=1_500,
        max_rep_ms=15_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.4, daily_rep_cap=200, diminishing_after_reps=100),
    validation=ValidationSpec(
        max_reps_per_second=0.7, min_reps_per_second=0.02,
        min_reps=10, min_duration_ms=30_000,
    ),
    setup_hint=(
        "Phone square in front of you, far enough back to see your hands "
        "through the whole swing. Same tee height every rep -- moving it "
        "around teaches you nothing."
    ),
    quality=QualitySpec(
        target_rom=0.65,
        # A swing has to be repeatable before it is worth making it violent.
        consistency_target=0.12,
        consistency_ceiling=0.38,
        tempo_min_ms=1_500,
        tempo_max_ms=6_000,
        w_consistency=0.40,
        w_depth=0.30,
        w_tempo=0.10,
        w_endurance=0.20,
        min_reps=10,
    ),
    load=LoadSpec(
        load_per_rep=0.8,
        # A swing is rotation, not an overhead throw. Putting it on the arm's
        # ledger would make an afternoon of hitting read as an afternoon of
        # throwing and hide the number that matters.
        throws_per_rep=0.0, tissue=Tissue.CORE,
    ),
    tracks_handedness=False,
)

BB_FIELDING = DrillSpec(
    key="bb_fielding",
    name="Fielding Reps",
    sport="baseball",
    category=Category.AGILITY,
    stimulus=Stimulus.QUICKNESS,
    metric=Metric.REPS,
    description=(
        "Down into fielding position and back up, over and over -- the "
        "footwork with no ball needed. It counts how far your hips travel, so "
        "bending at the waist does not register as getting down."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.35),
    counter=CounterSpec(
        # Lower than a squat jump's band and nowhere near a burpee's floor: a
        # fielding position is deep but the athlete never leaves the ground,
        # so the top of the cycle is standing rather than airborne.
        down_threshold=0.42,
        up_threshold=0.88,
        min_rep_ms=900,
        max_rep_ms=8_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=250, diminishing_after_reps=120),
    validation=ValidationSpec(
        max_reps_per_second=1.2, min_reps_per_second=0.05,
        min_reps=12, min_duration_ms=25_000,
    ),
    setup_hint=(
        "Phone side-on at hip height. Get your hips down and your hands out in "
        "front -- if your back is rounding, you are bending instead of "
        "getting down."
    ),
    quality=QualitySpec(
        # Measured at this drill's own tempo. It read 0.44 when the calibration
        # harness drove every drill at one rep a second regardless of its
        # refractory window -- which for a fielding rep is faster than the
        # movement is, and the smoothing filter clipped the excursion. Driven
        # inside its own band the same textbook rep measures 0.55, and the low
        # figure had been quietly marking honest reps as deeper than full.
        target_rom=0.55,
        consistency_target=0.16,
        tempo_min_ms=900,
        tempo_max_ms=3_500,
        w_consistency=0.25,
        w_depth=0.40,
        w_tempo=0.10,
        w_endurance=0.25,
        min_reps=12,
    ),
    load=LoadSpec(load_per_rep=0.9, throws_per_rep=0.0, tissue=Tissue.LOWER_BODY),
    tracks_handedness=False,
)

SB_WINDMILL = DrillSpec(
    key="sb_windmill",
    name="Windmill Pitching",
    sport="softball",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "The full underhand circle, with or without a ball. It follows your "
        "pitching hand all the way round, so a half circle does not count. "
        "Every rep goes on the day's arm total -- this is the highest-volume "
        "motion in the sport and the one nobody counts."
    ),
    signal=SignalSpec(
        # The pitching hand relative to the shoulder line. A windmill takes it
        # from below the hip, up over the head and back down, which is by far
        # the largest vertical excursion of any drill here -- and what makes it
        # unmistakable rather than merely different.
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="right_wrist",
        reference="right_shoulder",
        smoothing=0.25,
    ),
    counter=CounterSpec(
        # From well below the shoulder at release to well above it at the top.
        down_threshold=-0.75,
        up_threshold=0.55,
        min_rep_ms=900,
        max_rep_ms=8_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.8, daily_rep_cap=120, diminishing_after_reps=60),
    validation=ValidationSpec(
        max_reps_per_second=1.2, min_reps_per_second=0.04,
        min_reps=10, min_duration_ms=30_000,
    ),
    setup_hint=(
        "Phone side-on so it can see the whole circle -- square to you it "
        "cannot tell a full circle from a half one. Same stride every pitch."
    ),
    quality=QualitySpec(
        # Hand at the hip on release to fully overhead at the top: about a
        # torso below the shoulder to nearly a torso above it. 1.30 was a
        # guess that undershot the real arc, and the sweep caught it.
        target_rom=1.60,
        consistency_target=0.10,
        consistency_ceiling=0.34,
        tempo_min_ms=900,
        tempo_max_ms=3_500,
        w_consistency=0.40,
        w_depth=0.30,
        w_tempo=0.15,
        w_endurance=0.15,
        min_reps=10,
    ),
    load=LoadSpec(
        load_per_rep=1.4,
        # Underhand rather than overhead, and the shoulder loads differently --
        # but it is still a repeated maximal throw from a growing arm, and the
        # one thing a windmill pitcher does more than anything else. It goes on
        # the same ledger, because the ledger exists to count exactly this.
        throws_per_rep=1.0, tissue=Tissue.THROWING,
    ),
    tracks_handedness=True,
)

BB_CATCHER_STANCE = DrillSpec(
    key="bb_catcher_stance",
    name="Catcher's Stance",
    sport="baseball",
    category=Category.CONDITIONING,
    stimulus=Stimulus.STRENGTH,
    metric=Metric.HOLD_SECONDS,
    description=(
        "Down in the crouch and stay there. The clock only runs while your "
        "hips are actually low -- stand up and it stops, which is the whole "
        "point of a drill for a position that spends two hours down."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.35),
    counter=CounterSpec(
        down_threshold=0.30, up_threshold=0.62, min_rep_ms=400, max_rep_ms=60_000,
    ),
    scoring=ScoringSpec(xp_per_rep=0.0, xp_per_minute=28.0, daily_rep_cap=1_000),
    validation=ValidationSpec(
        max_reps_per_second=1.0, min_reps=0, min_duration_ms=20_000,
    ),
    setup_hint=(
        "Phone side-on at about knee height so it can see how low you really "
        "are. Heels down if you can, chest up, and do not lean on anything."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.0, load_per_minute=3.2, tissue=Tissue.LOWER_BODY),
    tracks_handedness=False,
)


# --------------------------------------------------------------------------
# Tennis
#
# The one sport here where the ball never touches the athlete. It comes off a
# racket head roughly sixty centimetres beyond the hand, and the detector
# attributes the contact to the nearest wrist -- so what these drills really
# measure is "the ball left from near this hand". That is enough to tell a
# forehand wing from a backhand one, and not enough to tell which is which, so
# nothing below claims to.
# --------------------------------------------------------------------------

TENNIS = BallSpec(
    required=True,
    contact="body",
    parts=("left_wrist", "right_wrist"),
    min_gap_ms=350,
    min_speed=0.45,
    attribute_side=True,
    detector="vision",
    colours=("optic",),
    diameter_cm=6.7,
)


TEN_WALL_RALLY = DrillSpec(
    key="ten_wall_rally",
    name="Wall Rally",
    sport="tennis",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description="Rally against a wall. Counts every shot you hit.",
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=350, max_rep_ms=6_000,
    ),
    # A tennis ball comes off the strings fast, which makes the impulse obvious
    # -- and lets the floor bounce in between be ignored.
    ball=TENNIS,
    scoring=ScoringSpec(xp_per_rep=0.8, daily_rep_cap=700, diminishing_after_reps=250),
    validation=ValidationSpec(max_reps_per_second=2.5, min_reps=8),
    setup_hint="Prop the phone up behind or beside you. It just needs to see the ball.",
    quality=None,
    load=LoadSpec(load_per_rep=0.5, load_per_minute=1.8, tissue=Tissue.UPPER_BODY),
    tracks_handedness=True,
)

TEN_ALTERNATE = DrillSpec(
    key="ten_alternate",
    name="Alternating Wings",
    sport="tennis",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Rally against the wall changing wing every shot -- forehand, "
        "backhand, forehand. The app checks the ball really is leaving from "
        "alternate sides of you; if you settle onto one wing it counts as an "
        "ordinary rally and says so."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=450, max_rep_ms=6_000,
    ),
    ball=replace(TENNIS, alternation="alternating", min_gap_ms=450),
    scoring=ScoringSpec(xp_per_rep=1.3, daily_rep_cap=400, diminishing_after_reps=180),
    validation=ValidationSpec(max_reps_per_second=2.0, min_reps=12),
    setup_hint=(
        "Stand further off the wall than feels comfortable so you have time to "
        "turn. Phone square to you -- from the side it cannot tell which wing "
        "the ball came off."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.6, load_per_minute=1.9, tissue=Tissue.UPPER_BODY),
    tracks_handedness=True,
)

TEN_ONE_WING = DrillSpec(
    key="ten_one_wing",
    name="One Wing",
    sport="tennis",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Every ball on the same wing, recovering to the middle between shots. "
        "The app checks the ball keeps leaving from the same side of you -- it "
        "cannot tell a forehand from a backhand, so which wing you pick is "
        "yours to decide and worth making the weaker one."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=450, max_rep_ms=6_000,
    ),
    ball=replace(TENNIS, alternation="same_hand", min_gap_ms=450),
    scoring=ScoringSpec(xp_per_rep=1.2, daily_rep_cap=400, diminishing_after_reps=180),
    validation=ValidationSpec(max_reps_per_second=2.0, min_reps=12),
    setup_hint=(
        "Pick a wing and stay on it. Recover to the middle after every ball -- "
        "standing still on one side is a different, much easier drill."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.6, load_per_minute=1.9, tissue=Tissue.UPPER_BODY),
    tracks_handedness=True,
)

TEN_VOLLEY = DrillSpec(
    key="ten_volley",
    name="Wall Volleys",
    sport="tennis",
    category=Category.SPEED,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Close to the wall, no bounce, short punchy blocks. This one has a "
        "speed floor rather than a ceiling: a groundstroke rally cannot be "
        "sustained this fast, which is how the app knows these were volleys."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=200, max_rep_ms=3_000,
    ),
    ball=replace(TENNIS, min_gap_ms=200, min_speed=0.35),
    scoring=ScoringSpec(xp_per_rep=1.1, daily_rep_cap=500, diminishing_after_reps=200),
    validation=ValidationSpec(
        max_reps_per_second=5.0,
        # The whole verification. Standing back and rallying cannot reach this
        # rate, and standing close and blocking cannot avoid it.
        min_reps_per_second=1.3,
        min_reps=20, min_duration_ms=15_000,
    ),
    setup_hint=(
        "Two metres off the wall, racket up in front of you. Short blocks, no "
        "backswing -- if you are taking one, you are too far back."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.3, load_per_minute=2.0, tissue=Tissue.UPPER_BODY),
    tracks_handedness=True,
)

TEN_SERVE = DrillSpec(
    key="ten_serve",
    name="Serve Motion",
    sport="tennis",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Toss and serve into a fence or a wall. It watches your hitting arm "
        "rather than the ball, so it counts full service motions and not "
        "half-hearted ones -- and it has no idea whether the serve would have "
        "gone in."
    ),
    signal=SignalSpec(
        # The same signal the basketball shot and the volleyball swing use, for
        # the same reason: it picks the hitting arm out of the frame rather
        # than naming a side, so a left-handed server is measured on the arm
        # that is actually serving.
        kind=SignalKind.SHOOTING_ARM,
        smoothing=0.28,
    ),
    counter=CounterSpec(
        # Racket dropped behind the back, then driven up through contact.
        down_threshold=85.0,
        up_threshold=162.0,
        min_rep_ms=1_200,
        max_rep_ms=12_000,
        rising_completes=True,
    ),
    # Confirm, never count: the arm finds the serve and the ball's only job is
    # to establish there was one.
    ball=replace(
        TENNIS, mode="confirm", required=False, min_gap_ms=1_200,
        min_speed=0.5, attribute_side=False, min_track_quality=0.28,
    ),
    scoring=ScoringSpec(xp_per_rep=1.8, daily_rep_cap=150, diminishing_after_reps=70),
    validation=ValidationSpec(
        max_reps_per_second=0.8, min_reps_per_second=0.03,
        min_reps=8, min_duration_ms=30_000,
    ),
    setup_hint=(
        "Somewhere you can hit into safely, phone square to you and far enough "
        "back to see your whole arm. Same toss every time -- everything after "
        "it is just repeating."
    ),
    quality=QualitySpec(
        # Measured at this drill's own tempo rather than at one rep a second,
        # which is faster than anybody serves. See bb_fielding above -- the
        # same harness fix moved both, and for the same reason.
        target_rom=94.0,
        # A serve has to be repeatable before it is worth making it fast, so
        # consistency carries the most weight.
        consistency_target=0.11,
        consistency_ceiling=0.36,
        tempo_min_ms=1_200,
        tempo_max_ms=4_000,
        w_consistency=0.40,
        w_depth=0.30,
        w_tempo=0.15,
        w_endurance=0.15,
        min_reps=10,
    ),
    load=LoadSpec(
        load_per_rep=1.2,
        # The serve is tennis's throwing action. It is the same overhead chain
        # a pitch count exists to watch, and a serving shoulder at fifteen gets
        # hurt exactly the way a pitching one does.
        throws_per_rep=1.0, tissue=Tissue.THROWING,
    ),
    tracks_handedness=True,
)

TEN_SPLIT_STEP = DrillSpec(
    key="ten_split_step",
    name="Split Steps",
    sport="tennis",
    category=Category.SPEED,
    stimulus=Stimulus.QUICKNESS,
    metric=Metric.REPS,
    description=(
        "The small hop you land from just as your opponent hits. Land wide and "
        "balanced, then push off. It counts the hop, so a step that never "
        "leaves the ground does not register."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.32),
    counter=CounterSpec(
        # A split step is a small hop from an already-low stance, so it lives
        # high and narrow -- well clear of every jump drill in the catalogue,
        # which all start from standing and go much further.
        down_threshold=0.86,
        up_threshold=1.04,
        min_rep_ms=500,
        max_rep_ms=4_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=0.7, daily_rep_cap=400, diminishing_after_reps=180),
    validation=ValidationSpec(
        max_reps_per_second=2.0, min_reps_per_second=0.15,
        min_reps=15, min_duration_ms=20_000,
    ),
    setup_hint=(
        "Phone side-on at hip height. Small hop, land with your feet wider "
        "than your shoulders, and push off straight away. If you are landing "
        "narrow you cannot go anywhere."
    ),
    quality=QualitySpec(
        # The counter band spans 0.18 and a real hop overshoots it slightly, so a
        # textbook rep covers about this much. 0.16 was guesswork and the
        # calibration sweep caught it.
        target_rom=0.20,
        consistency_target=0.16,
        tempo_min_ms=500,
        tempo_max_ms=2_500,
        w_consistency=0.35,
        w_depth=0.25,
        w_tempo=0.20,
        w_endurance=0.20,
        min_reps=15,
    ),
    load=LoadSpec(load_per_rep=0.5, throws_per_rep=0.0, tissue=Tissue.LOWER_BODY),
    tracks_handedness=False,
)

TEN_RECOVERY = DrillSpec(
    key="ten_recovery",
    name="Recovery Shuffle",
    sport="tennis",
    category=Category.AGILITY,
    stimulus=Stimulus.QUICKNESS,
    metric=Metric.REPS,
    description=(
        "Side to side along the baseline without crossing your feet. One rep "
        "is one push. It measures how far apart your feet get, and it can see "
        "when they cross -- which is the moment you stop being able to change "
        "direction."
    ),
    signal=SignalSpec(kind=SignalKind.STANCE_WIDTH, smoothing=0.45),
    counter=CounterSpec(
        # Identical to the basketball slide and the soccer shuffle. It is the
        # same movement measured the same way, and the app cannot tell a player
        # recovering across a baseline from a guard sliding -- so it must not
        # pay differently for the sport's name.
        down_threshold=1.30,
        up_threshold=1.80,
        min_rep_ms=280,
        max_rep_ms=3_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=300, diminishing_after_reps=140),
    validation=ValidationSpec(
        max_reps_per_second=3.0, min_reps_per_second=0.15,
        min_reps=10, min_duration_ms=20_000,
    ),
    setup_hint=(
        "Phone square in front of you, far enough back to see both feet. Stay "
        "low, shuffle, and never cross your feet."
    ),
    quality=QualitySpec(
        target_rom=0.70,
        consistency_target=0.18,
        tempo_min_ms=280,
        tempo_max_ms=1_400,
        w_consistency=0.30,
        w_depth=0.35,
        w_tempo=0.20,
        w_endurance=0.15,
        min_reps=12,
    ),
    load=LoadSpec(load_per_rep=1.1, throws_per_rep=0.0, tissue=Tissue.LOWER_BODY),
    tracks_handedness=True,
)



# --------------------------------------------------------------------------
# Hockey
#
# The sport where the thing being trained happens somewhere the phone cannot
# go. Nobody props a phone on the boards and skates a drill past it, so every
# drill here is off-ice work -- which is not a compromise, it is what a hockey
# player's driveway hour actually is: a shooting pad, a stickhandling ball,
# and legs.
#
# **There is no puck spec anywhere in this section, and that is deliberate.**
# A puck is black, matte and usually on a dark surface. The vision detector
# works in normalised chroma, and black has no chroma at all -- it is not a
# colour, it is an absence of light. A black preset would match every shadow,
# every dark shoe and every gap under a garage door, and a detector that fires
# on shadows is worse than no detector, because it produces confident wrong
# numbers instead of honest silence. So these drills count from the body only,
# and nothing here claims a puck was ever seen.
#
# What replaces the ball check is the sweep signal's sign. A rep arms on one
# side of the body and fires on the other, so the three stick drills below are
# separated from each other by how far across the body the hands actually
# travelled -- a narrow handle physically cannot fire the wide one's
# thresholds -- and each pays more than the one it contains.
# --------------------------------------------------------------------------

HOC_STICKHANDLE = DrillSpec(
    key="hoc_stickhandle",
    name="Stickhandling",
    sport="hockey",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Ball or puck side to side in front of you, as quick as you can keep "
        "it clean. One rep is one trip across your body and back. It reads "
        "your hands, not the puck -- so it counts the handle, and it has no "
        "idea whether the puck stayed on the blade."
    ),
    signal=SignalSpec(
        # The first horizontal hand measurement in the catalogue. Stickhandling
        # moves the hands almost purely sideways, so every height and angle
        # signal here reads it as an athlete standing still -- which is why the
        # defining skill of the sport had no drill anywhere.
        kind=SignalKind.HAND_SWEEP,
        # Light, because this is the fastest oscillation in the catalogue.
        # Tight handles run past three cycles a second, which is seven or eight
        # frames a cycle at 30fps, and a heavy filter simply erases them.
        smoothing=0.60,
    ),
    counter=CounterSpec(
        # Tight handles: the hands stay close to the middle of the chest and
        # the puck does the travelling. Narrow on purpose -- this is the band
        # the other two stick drills contain rather than the other way round.
        down_threshold=-0.18,
        up_threshold=0.18,
        min_rep_ms=220,
        max_rep_ms=2_500,
        rising_completes=True,
    ),
    scoring=ScoringSpec(
        xp_per_rep=1.0,
        daily_rep_cap=900,
        diminishing_after_reps=300,
        diminishing_rate=0.35,
    ),
    validation=ValidationSpec(
        max_reps_per_second=4.5,
        # The verification, and the reason this pays a full point. A wide
        # handle or a shot cannot be repeated at this rate, so a session that
        # sustains it was the drill it says it was.
        min_reps_per_second=0.90,
        min_reps=30,
        min_duration_ms=20_000,
    ),
    setup_hint=(
        "Phone square in front of you at about chest height, far enough back "
        "to see both hands the whole way across. It needs to see you from the "
        "front -- side-on it cannot tell forehand from backhand at all."
    ),
    quality=QualitySpec(
        target_rom=0.48,
        # Handles are about repeatability before they are about width.
        consistency_target=0.12,
        consistency_ceiling=0.36,
        tempo_min_ms=220,
        tempo_max_ms=900,
        w_consistency=0.40,
        w_depth=0.20,
        w_tempo=0.20,
        w_endurance=0.20,
        min_reps=25,
    ),
    load=LoadSpec(
        load_per_rep=0.12,
        load_per_minute=1.2,
        # Nothing here goes overhead. A hockey player's arm risk is not a
        # thrower's, and putting stick work on the throwing ledger would make
        # the one number that ledger exists to protect meaningless.
        throws_per_rep=0.0,
        tissue=Tissue.UPPER_BODY,
    ),
    tracks_handedness=False,
)

HOC_WIDE_HANDLES = DrillSpec(
    key="hoc_wide_handles",
    name="Wide Handles",
    sport="hockey",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "The same handle, pushed right out to each side -- full extension one "
        "way, full extension the other. Slower and much wider than tight "
        "handles, and the app can tell the difference, because a narrow handle "
        "never reaches these thresholds."
    ),
    signal=SignalSpec(kind=SignalKind.HAND_SWEEP, smoothing=0.50),
    counter=CounterSpec(
        # Hands out past the shoulder on each side. Contains the tight handle's
        # band, which is why it has to pay more than one -- see the subsumption
        # guard in tests/test_drills.py.
        down_threshold=-0.42,
        up_threshold=0.42,
        min_rep_ms=500,
        max_rep_ms=5_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.3, daily_rep_cap=400, diminishing_after_reps=180),
    validation=ValidationSpec(
        max_reps_per_second=2.0, min_reps_per_second=0.20,
        min_reps=15, min_duration_ms=25_000,
    ),
    setup_hint=(
        "Same setup as tight handles, but stand back further -- your hands go "
        "a long way out and the app only counts what it can see."
    ),
    quality=QualitySpec(
        target_rom=1.10,
        consistency_target=0.16,
        consistency_ceiling=0.45,
        tempo_min_ms=500,
        tempo_max_ms=2_200,
        # Width is the whole point of this one, so depth carries the weight
        # that consistency carries in the tight version.
        w_consistency=0.25,
        w_depth=0.40,
        w_tempo=0.15,
        w_endurance=0.20,
        min_reps=15,
    ),
    load=LoadSpec(
        load_per_rep=0.30, load_per_minute=1.4,
        throws_per_rep=0.0, tissue=Tissue.UPPER_BODY,
    ),
    tracks_handedness=False,
)

HOC_SHOT = DrillSpec(
    key="hoc_shot",
    name="Wrist Shots",
    sport="hockey",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Off a pad into a net. It follows your hands sweeping the puck from "
        "behind your back foot right through to the follow-through, so a full "
        "shot counts and a flick of the wrists does not. It cannot see the "
        "puck and does not know where it went -- what it knows is that your "
        "hands travelled the whole way."
    ),
    signal=SignalSpec(kind=SignalKind.HAND_SWEEP, smoothing=0.40),
    counter=CounterSpec(
        # The widest band on this signal: loaded behind the back foot, through
        # the release, out to a high follow-through across the body. Contains
        # both handle drills, so it pays more than either.
        down_threshold=-0.62,
        up_threshold=0.62,
        min_rep_ms=1_400,
        max_rep_ms=12_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.4, daily_rep_cap=150, diminishing_after_reps=80),
    validation=ValidationSpec(
        max_reps_per_second=0.8, min_reps_per_second=0.03,
        min_reps=10, min_duration_ms=30_000,
    ),
    setup_hint=(
        "Phone in front of you, past the net and off to the side you are "
        "facing, high enough to see your hands finish. Same spot on the pad "
        "every shot -- moving around teaches you nothing."
    ),
    quality=QualitySpec(
        target_rom=1.60,
        consistency_target=0.12,
        consistency_ceiling=0.40,
        tempo_min_ms=1_400,
        tempo_max_ms=6_000,
        w_consistency=0.40,
        w_depth=0.30,
        w_tempo=0.10,
        w_endurance=0.20,
        min_reps=10,
    ),
    load=LoadSpec(
        load_per_rep=0.9,
        # A shot is rotation through the hips and core, not an overhead throw.
        # Deliberately off the arm's ledger for the same reason a bat swing is.
        throws_per_rep=0.0,
        tissue=Tissue.CORE,
    ),
    tracks_handedness=False,
)

HOC_BUTTERFLY = DrillSpec(
    key="hoc_butterfly",
    name="Butterfly Recoveries",
    sport="hockey",
    category=Category.AGILITY,
    stimulus=Stimulus.POWER,
    metric=Metric.REPS,
    description=(
        "Down into the butterfly and back up to your skates, over and over. "
        "It measures how far your hips travel, so dropping to a knee does not "
        "register as getting down -- and getting back up is half the rep."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.35),
    counter=CounterSpec(
        # Hips nearly to the floor and back to standing. The floor of this band
        # deliberately sits just above a burpee's, so a set of burpees does not
        # fire it -- a burpee is worth more per rep and the two must not be
        # interchangeable.
        down_threshold=0.28,
        up_threshold=0.92,
        min_rep_ms=1_000,
        max_rep_ms=9_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.7, daily_rep_cap=150, diminishing_after_reps=70),
    validation=ValidationSpec(
        max_reps_per_second=1.0, min_reps_per_second=0.04,
        min_reps=10, min_duration_ms=25_000,
    ),
    setup_hint=(
        "Phone side-on at about knee height, on a soft floor. Pads if you have "
        "them. This is the drop and the recovery -- the app cannot see whether "
        "you sealed, only how far you went and how fast you got back."
    ),
    quality=QualitySpec(
        target_rom=0.62,
        consistency_target=0.14,
        tempo_min_ms=1_000,
        tempo_max_ms=4_000,
        # Getting back up is what a goalie runs out of, so endurance is
        # weighted harder here than anywhere else in this section.
        w_consistency=0.20,
        w_depth=0.30,
        w_tempo=0.15,
        w_endurance=0.35,
        min_reps=10,
    ),
    load=LoadSpec(load_per_rep=1.6, throws_per_rep=0.0, tissue=Tissue.LOWER_BODY),
    tracks_handedness=False,
)

HOC_SHUFFLE = DrillSpec(
    key="hoc_shuffle",
    name="Zone Slides",
    sport="hockey",
    category=Category.AGILITY,
    stimulus=Stimulus.QUICKNESS,
    metric=Metric.REPS,
    description=(
        "Slide across the top of the zone without ever turning your hips. One "
        "rep is one push. It measures how far apart your feet are, so a step "
        "that goes nowhere does not count -- and it can see when your feet "
        "cross, which off the ice is the exact moment you stop being able to "
        "change direction."
    ),
    signal=SignalSpec(kind=SignalKind.STANCE_WIDTH, smoothing=0.45),
    counter=CounterSpec(
        # Identical to the basketball slide, the soccer shuffle and the tennis
        # recovery step, because it is identical work: the same feet, the same
        # width, the same crossing error. Four sports on one measurement, all
        # paying the same, is the honest outcome rather than a coincidence.
        down_threshold=1.30,
        up_threshold=1.80,
        min_rep_ms=280,
        max_rep_ms=3_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=300, diminishing_after_reps=140),
    validation=ValidationSpec(
        max_reps_per_second=3.0, min_reps_per_second=0.15,
        min_reps=10, min_duration_ms=20_000,
    ),
    setup_hint=(
        "Phone square in front of you, far enough back to see both feet. Stay "
        "low, push off the outside foot, and never let them cross."
    ),
    quality=QualitySpec(
        target_rom=0.70,
        consistency_target=0.18,
        tempo_min_ms=280,
        tempo_max_ms=1_400,
        w_consistency=0.30,
        w_depth=0.35,
        w_tempo=0.20,
        w_endurance=0.15,
        min_reps=12,
    ),
    load=LoadSpec(load_per_rep=1.1, throws_per_rep=0.0, tissue=Tissue.LOWER_BODY),
    tracks_handedness=True,
)

HOC_STANCE = DrillSpec(
    key="hoc_stance",
    name="Skater's Stance",
    sport="hockey",
    category=Category.CONDITIONING,
    stimulus=Stimulus.STRENGTH,
    metric=Metric.HOLD_SECONDS,
    description=(
        "Knees bent, chest up, weight on the balls of your feet -- and stay "
        "there. The clock only runs while your hips are actually down. Stand "
        "up out of it and it stops, which is the whole drill."
    ),
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.35),
    counter=CounterSpec(
        # Lower than a basketball defensive stance and higher than a catcher's
        # crouch. A skating stance is a deep knee bend with the chest forward,
        # not a sit -- below 0.45 the athlete has dropped onto their heels,
        # which is a squat hold and a different exercise.
        down_threshold=0.45, up_threshold=0.72, min_rep_ms=400, max_rep_ms=60_000,
    ),
    scoring=ScoringSpec(xp_per_rep=0.0, xp_per_minute=30.0, daily_rep_cap=1_000),
    validation=ValidationSpec(
        max_reps_per_second=1.0, min_reps=0, min_duration_ms=20_000,
    ),
    setup_hint=(
        "Phone side-on at about knee height so it can see how low you really "
        "are. Chest up, back flat, and nothing to lean on."
    ),
    quality=None,
    load=LoadSpec(load_per_rep=0.0, load_per_minute=3.6, tissue=Tissue.LOWER_BODY),
    tracks_handedness=False,
)


# --------------------------------------------------------------------------
# Football
#
# The sport that walks straight into a model built for a different one. The
# diamond build gave the load model an age-scaled daily throwing ceiling
# because youth pitching volume is the most-studied injury risk in this
# catalogue. A quarterback throws more in a week than most pitchers, into an
# off season that does not exist, and nobody counts any of it.
#
# **No ball spec anywhere in this sport, and for a different reason than
# hockey's.** A football is not a sphere. The vision detector finds a ball by
# fitting a circle of a known diameter, so an oblong brown object seen from an
# angle it never predicts is not a hard case for it -- it is the wrong shape of
# problem entirely. So these count from the body, and nothing claims otherwise.
#
# What is missing here is missing honestly. A lineman's get-off is horizontal
# explosion and the camera measures vertical hip travel, which is a squat jump
# with a different name; a backpedal and a hip flip need a depth the phone does
# not have. Those are not in the catalogue rather than being approximated.
# --------------------------------------------------------------------------

#: All three passing drills read the throwing hand against the shoulder on the
#: same side, and are separated from each other by how much of the arm action
#: the athlete actually used -- a quick release physically cannot reach a deep
#: ball's thresholds. Each pays more than the band it contains, and each costs
#: the arm more, which is the part that matters.
FB_THROW_SIGNAL = SignalSpec(
    kind=SignalKind.RELATIVE_HEIGHT,
    landmark="right_wrist",
    reference="right_shoulder",
    smoothing=0.40,
)

FB_QUICK_RELEASE = DrillSpec(
    key="fb_quick_release",
    name="Quick Release",
    sport="football",
    category=Category.SPEED,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Short, fast throws with a compact arm action -- ball out before the "
        "front foot lands. There is a speed floor here: a full throw cannot be "
        "repeated this quickly, which is how the app knows these were quick "
        "ones."
    ),
    signal=FB_THROW_SIGNAL,
    counter=CounterSpec(
        # The narrowest of the three. The hand barely drops below the shoulder
        # before it comes back through.
        down_threshold=-0.10,
        up_threshold=0.40,
        min_rep_ms=700,
        max_rep_ms=5_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=0.8, daily_rep_cap=250, diminishing_after_reps=120),
    validation=ValidationSpec(
        max_reps_per_second=1.6,
        # The verification, and it has to clear the FULL throw's ceiling rather
        # than the deep ball's. At 0.40 a session of ordinary throws satisfied
        # this floor -- and because a quick release costs the arm half what a
        # throw does, mislabelling would have halved what the day's throwing
        # total ever saw. In this sport that is the one exploit that matters.
        min_reps_per_second=1.00,
        min_reps=20, min_duration_ms=30_000,
    ),
    setup_hint=(
        "Phone side-on so it can see your throwing arm through the whole "
        "motion. Close to the wall or the net -- this is the release, not the "
        "throw."
    ),
    quality=None,
    load=LoadSpec(
        load_per_rep=0.5,
        # Submaximal and short, but still overhead and still repeated, so it
        # belongs on the arm's ledger at a reduced rate rather than at none.
        throws_per_rep=0.5, tissue=Tissue.THROWING,
    ),
    tracks_handedness=True,
)

FB_WALL_THROW = DrillSpec(
    key="fb_wall_throw",
    # Not "Wall Throws" -- baseball already has that name, and two drills with
    # one name is two drills a coach cannot tell apart in a menu.
    name="Pocket Throws",
    sport="football",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Ordinary throws into a wall or a net, at the distance you actually "
        "play at. It follows your throwing hand, so a full motion counts and a "
        "flick does not. Every rep goes on the day's arm total."
    ),
    signal=FB_THROW_SIGNAL,
    counter=CounterSpec(
        down_threshold=-0.18,
        up_threshold=0.48,
        min_rep_ms=1_200,
        max_rep_ms=10_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.3, daily_rep_cap=200, diminishing_after_reps=100),
    validation=ValidationSpec(
        max_reps_per_second=0.9, min_reps_per_second=0.05,
        min_reps=12, min_duration_ms=30_000,
    ),
    setup_hint=(
        "Phone side-on, far enough back to see your arm from the load to the "
        "follow-through. Same footwork every rep."
    ),
    quality=QualitySpec(
        target_rom=0.70,
        # A throw has to be repeatable before it is worth making it hard.
        consistency_target=0.10,
        consistency_ceiling=0.34,
        tempo_min_ms=1_200,
        tempo_max_ms=5_000,
        w_consistency=0.40,
        w_depth=0.25,
        w_tempo=0.15,
        w_endurance=0.20,
        min_reps=12,
    ),
    load=LoadSpec(load_per_rep=1.0, throws_per_rep=1.0, tissue=Tissue.THROWING),
    tracks_handedness=True,
)

FB_DEEP_BALL = DrillSpec(
    key="fb_deep_ball",
    name="Deep Balls",
    sport="football",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Fewer throws, all of them hard. Full drop, full turn, everything into "
        "it. Each one costs the arm more than a normal throw and the app "
        "counts it that way -- which is the whole reason to keep the number "
        "small."
    ),
    signal=FB_THROW_SIGNAL,
    counter=CounterSpec(
        # The widest of the three: the hand drops further into the load and
        # finishes higher across the body.
        down_threshold=-0.28,
        up_threshold=0.58,
        min_rep_ms=2_500,
        max_rep_ms=20_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=2.0, daily_rep_cap=60, diminishing_after_reps=30),
    validation=ValidationSpec(
        max_reps_per_second=0.35, min_reps_per_second=0.02,
        min_reps=6, min_duration_ms=60_000,
    ),
    setup_hint=(
        "Somewhere with real room, phone side-on. If you are throwing these "
        "flat-footed you are throwing with your arm, and that is exactly what "
        "the day's total is trying to protect."
    ),
    quality=None,
    load=LoadSpec(
        load_per_rep=1.8,
        # Each of these is a harder throw than a catch-play one, and the arm
        # knows it. Counting them one-for-one would understate the day.
        throws_per_rep=1.5, tissue=Tissue.THROWING,
    ),
    tracks_handedness=True,
)

FB_KICK = DrillSpec(
    key="fb_kick",
    name="Kicking Swings",
    sport="football",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "The full leg swing, with or without a ball. It follows your kicking "
        "foot from the ground to the top of the follow-through, so a half "
        "swing does not count. A punt is a punt in either code, so rugby "
        "kickers use this drill too -- it is the highest-volume thing anybody "
        "on either field does alone, and until now nothing counted it."
    ),
    signal=SignalSpec(
        # The kicking foot against the hip on the same side. By far the largest
        # excursion of any leg measurement here -- a punt finishes with the
        # ankle above the hip, which nothing else in the catalogue ever does.
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="right_ankle",
        reference="right_hip",
        smoothing=0.35,
    ),
    counter=CounterSpec(
        down_threshold=-1.10,
        up_threshold=0.55,
        min_rep_ms=1_500,
        max_rep_ms=15_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.6, daily_rep_cap=120, diminishing_after_reps=60),
    validation=ValidationSpec(
        max_reps_per_second=0.6, min_reps_per_second=0.02,
        min_reps=10, min_duration_ms=30_000,
    ),
    setup_hint=(
        "Phone side-on to your kicking leg, far enough back to see the whole "
        "swing. Same approach every rep -- changing it teaches you nothing."
    ),
    quality=QualitySpec(
        # Measured, not guessed -- and the guess was badly low. Standing puts
        # the kicking ankle about 1.4 torso lengths below the hip and a punt
        # finishes nearly a torso above it, so a textbook swing covers 2.3.
        # At 1.55 every honest rep would have scored full depth with a third of
        # the swing missing, which is exactly the half a young kicker skips.
        target_rom=2.30,
        consistency_target=0.12,
        consistency_ceiling=0.38,
        tempo_min_ms=1_500,
        tempo_max_ms=6_000,
        w_consistency=0.40,
        w_depth=0.30,
        w_tempo=0.10,
        w_endurance=0.20,
        min_reps=10,
    ),
    load=LoadSpec(
        load_per_rep=1.5,
        # Nothing overhead, so this stays off the arm's ledger -- but a young
        # kicker's hip and groin take a beating that nobody counts either, and
        # the per-rep load says so.
        throws_per_rep=0.0, tissue=Tissue.LOWER_BODY,
    ),
    tracks_handedness=True,
)

FB_SHUFFLE = DrillSpec(
    key="fb_shuffle",
    name="Mirror Slides",
    sport="football",
    category=Category.AGILITY,
    stimulus=Stimulus.QUICKNESS,
    metric=Metric.REPS,
    description=(
        "Slide across without turning your hips -- a defensive back mirroring "
        "a receiver, or a tackle's kick-slide in pass protection. They are the "
        "same feet doing the same job, so they are one drill. One rep is one "
        "push, and it can see when your feet cross, which is the moment "
        "somebody gets past you."
    ),
    signal=SignalSpec(kind=SignalKind.STANCE_WIDTH, smoothing=0.45),
    counter=CounterSpec(
        # The fifth sport on this one band. Basketball's slide, soccer's
        # shuffle, tennis's recovery step, hockey's zone slide and this are the
        # same feet doing the same work, and they all pay the same.
        down_threshold=1.30,
        up_threshold=1.80,
        min_rep_ms=280,
        max_rep_ms=3_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=300, diminishing_after_reps=140),
    validation=ValidationSpec(
        max_reps_per_second=3.0, min_reps_per_second=0.15,
        min_reps=10, min_duration_ms=20_000,
    ),
    setup_hint=(
        "Phone square in front of you, far enough back to see both feet. Stay "
        "low, push off the outside foot, and never let them cross."
    ),
    quality=QualitySpec(
        target_rom=0.70,
        consistency_target=0.18,
        tempo_min_ms=280,
        tempo_max_ms=1_400,
        w_consistency=0.30,
        w_depth=0.35,
        w_tempo=0.20,
        w_endurance=0.15,
        min_reps=12,
    ),
    load=LoadSpec(load_per_rep=1.1, throws_per_rep=0.0, tissue=Tissue.LOWER_BODY),
    tracks_handedness=True,
)


# --------------------------------------------------------------------------
# Rugby
#
# The sport where most of the game is unavailable to a solo camera, and saying
# so is most of the work. Tackling, rucking, scrummaging and lineout lifting
# all need at least one other person, and none of them should be practised
# alone by a fourteen-year-old in a garden. What is left is passing, kicking
# and conditioning -- which happens to be exactly what a rugby player's hour at
# home has always been.
#
# **Passing reads on the hockey sweep signal, and means something different on
# it.** A hockey player's short side is their backhand, which they will have
# for life. A rugby player is required to pass off both hands from anywhere,
# so a short side is a gap the sport finds inside one game. Same number,
# different conclusion -- which is why `sweep.py` reports the asymmetry and
# names neither side.
#
# The three drills below extend a ladder that now runs across two sports and
# six drills on one measurement. Every band contains the one below it, so every
# rate has to rise with it: there is no way to earn more by doing less.
# --------------------------------------------------------------------------

RUG_QUICK_HANDS = DrillSpec(
    key="rug_quick_hands",
    # Not "Quick Hands" -- baseball has that. A pop is what a rugby coach calls
    # a short ball anyway, so the sport's own word is also the unique one.
    name="Pop Passing",
    sport="rugby",
    category=Category.SPEED,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Catch and pass in one movement, close to the wall, both directions. "
        "One rep is one trip across your body. There is a speed floor here: a "
        "long pass cannot be repeated this fast, which is how the app knows "
        "these were quick ones."
    ),
    signal=SignalSpec(
        # The same measurement a stickhandle runs on: the hands crossing the
        # middle of the chest. A pass is that crossing done once and released.
        kind=SignalKind.HAND_SWEEP,
        smoothing=0.55,
    ),
    counter=CounterSpec(
        # The hands stay in tight. Narrow on purpose -- this is the band the
        # other two contain rather than the other way round.
        down_threshold=-0.22,
        up_threshold=0.22,
        min_rep_ms=350,
        max_rep_ms=3_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(
        xp_per_rep=1.1,
        daily_rep_cap=500,
        diminishing_after_reps=220,
        diminishing_rate=0.35,
    ),
    validation=ValidationSpec(
        max_reps_per_second=3.0,
        # The verification. A full pass cannot be repeated at this rate.
        min_reps_per_second=0.70,
        min_reps=25,
        min_duration_ms=25_000,
    ),
    setup_hint=(
        "Phone square in front of you at chest height. It has to see you from "
        "the front -- side-on it cannot tell a pass left from a pass right at "
        "all, and this drill is entirely about the difference."
    ),
    quality=QualitySpec(
        target_rom=0.55,
        consistency_target=0.12,
        consistency_ceiling=0.36,
        tempo_min_ms=350,
        tempo_max_ms=1_400,
        w_consistency=0.40,
        w_depth=0.20,
        w_tempo=0.20,
        w_endurance=0.20,
        min_reps=25,
    ),
    load=LoadSpec(
        load_per_rep=0.15,
        load_per_minute=1.2,
        # A rugby pass is a chest-height push, not an overhead throw. Putting
        # it on the arm's ledger would fill the one number that ledger exists
        # to protect with work that does not threaten it.
        throws_per_rep=0.0,
        tissue=Tissue.UPPER_BODY,
    ),
    tracks_handedness=False,
)

RUG_WALL_PASS = DrillSpec(
    key="rug_wall_pass",
    # Not "Wall Passing" -- soccer has that.
    name="Catch and Pass",
    sport="rugby",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "Pass into a wall, catch it, pass it back the other way. A rep only "
        "counts if your hands actually cross your body, so passing off your "
        "good side all session does not register as passing."
    ),
    signal=SignalSpec(kind=SignalKind.HAND_SWEEP, smoothing=0.50),
    counter=CounterSpec(
        down_threshold=-0.38,
        up_threshold=0.38,
        min_rep_ms=600,
        max_rep_ms=6_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.2, daily_rep_cap=400, diminishing_after_reps=180),
    validation=ValidationSpec(
        max_reps_per_second=1.6, min_reps_per_second=0.15,
        min_reps=15, min_duration_ms=30_000,
    ),
    setup_hint=(
        "Phone square in front of you, far enough back to see both hands the "
        "whole way across. Stand further off the wall than feels necessary."
    ),
    quality=QualitySpec(
        target_rom=0.98,
        consistency_target=0.14,
        consistency_ceiling=0.42,
        tempo_min_ms=600,
        tempo_max_ms=2_500,
        w_consistency=0.35,
        w_depth=0.30,
        w_tempo=0.15,
        w_endurance=0.20,
        min_reps=15,
    ),
    load=LoadSpec(
        load_per_rep=0.30, load_per_minute=1.3,
        throws_per_rep=0.0, tissue=Tissue.UPPER_BODY,
    ),
    tracks_handedness=False,
)

RUG_SPIN_PASS = DrillSpec(
    key="rug_spin_pass",
    name="Spin Passing",
    sport="rugby",
    category=Category.SKILL,
    stimulus=Stimulus.SKILL,
    metric=Metric.REPS,
    description=(
        "The long one, off both hands. Hands start behind your back hip and "
        "finish pointing at the target, which is the widest sweep in the "
        "sport -- and the app can tell it from a short pass, because a short "
        "pass never gets there."
    ),
    signal=SignalSpec(kind=SignalKind.HAND_SWEEP, smoothing=0.45),
    counter=CounterSpec(
        down_threshold=-0.58,
        up_threshold=0.58,
        min_rep_ms=1_100,
        max_rep_ms=9_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.35, daily_rep_cap=250, diminishing_after_reps=110),
    validation=ValidationSpec(
        max_reps_per_second=0.9, min_reps_per_second=0.05,
        min_reps=12, min_duration_ms=30_000,
    ),
    setup_hint=(
        "Room to throw it properly, phone square in front of you. If the pass "
        "is not travelling you are doing the short drill with a longer name."
    ),
    quality=QualitySpec(
        target_rom=1.50,
        consistency_target=0.14,
        consistency_ceiling=0.44,
        tempo_min_ms=1_100,
        tempo_max_ms=4_000,
        # Width is what makes a spin pass a spin pass.
        w_consistency=0.30,
        w_depth=0.35,
        w_tempo=0.15,
        w_endurance=0.20,
        min_reps=12,
    ),
    load=LoadSpec(
        load_per_rep=0.45, load_per_minute=1.2,
        throws_per_rep=0.0, tissue=Tissue.UPPER_BODY,
    ),
    tracks_handedness=False,
)


# --------------------------------------------------------------------------
# Swimming
#
# The only sport here where the athlete is somewhere the phone cannot follow,
# and the only one whose drills are therefore ALL dryland by definition rather
# than by compromise. That is not a workaround -- a swimmer's dryland hour is a
# real and separately coached part of the sport, and it is the part that
# decides whether their shoulders survive the yardage.
#
# Nothing here counts a stroke, a length or a turn, and nothing pretends to.
# What the pool volume itself does is reach the load model through the training
# log, which is where swimming's actual injury risk lives.
# --------------------------------------------------------------------------

SWM_STREAMLINE = DrillSpec(
    key="swm_streamline",
    name="Streamline Hold",
    sport="swimming",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
    metric=Metric.HOLD_SECONDS,
    description=(
        "Arms locked overhead, one hand over the other, ears squeezed between "
        "your biceps, body in one straight line. The clock runs only while "
        "your hands are actually up -- letting them drift forward stops it."
    ),
    signal=SignalSpec(
        # The hands against the shoulder line. This is the one position the
        # whole sport is built around: every push-off, every turn and every
        # start passes through it, and until now nothing in the catalogue
        # measured an arm held overhead at all.
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="left_wrist",
        reference="left_shoulder",
        smoothing=0.35,
    ),
    counter=CounterSpec(
        # Wrists well above the shoulder line. A jumping jack passes through
        # the bottom of this on the way up; a streamline lives at the top of
        # it, which is why the floor sits above where a jack ever reaches.
        down_threshold=0.55,
        up_threshold=1.15,
        min_rep_ms=400,
        max_rep_ms=60_000,
    ),
    scoring=ScoringSpec(xp_per_rep=0.0, xp_per_minute=30.0, daily_rep_cap=1_000),
    validation=ValidationSpec(
        max_reps_per_second=1.0, min_reps=0, min_duration_ms=15_000,
    ),
    setup_hint=(
        "Phone side-on, far enough back to see your hands and your hips at "
        "once. Standing is fine. If your ribs are flaring out at the front you "
        "are arching rather than streamlining."
    ),
    quality=None,
    load=LoadSpec(
        load_per_rep=0.0,
        load_per_minute=3.0,
        throws_per_rep=0.0,
        # The same shoulder a throwing sport loads, reached a different way.
        # It goes on the tissue axis so a swimmer with a shoulder history gets
        # an earlier caution -- and NOT on the throw count, because that
        # ceiling is derived from pitch guidance and holding a position is not
        # a pitch.
        tissue=Tissue.THROWING,
    ),
    tracks_handedness=False,
)

SWM_PULL = DrillSpec(
    key="swm_pull",
    name="Dryland Pulls",
    sport="swimming",
    category=Category.STRENGTH,
    stimulus=Stimulus.STRENGTH,
    metric=Metric.REPS,
    description=(
        "Bands anchored high, bent forward, and pull from full reach through "
        "to your hip. It follows your hand the whole way, so a half pull does "
        "not count -- and a half pull is what everybody does once the set gets "
        "long."
    ),
    signal=SignalSpec(
        kind=SignalKind.RELATIVE_HEIGHT,
        landmark="right_wrist",
        reference="right_shoulder",
        smoothing=0.40,
    ),
    counter=CounterSpec(
        # Hand at the hip through to full extension in front of the shoulder.
        # Sits inside a softball windmill's band, which is why it pays less
        # than one -- see the subsumption guard.
        down_threshold=-0.60,
        up_threshold=0.40,
        min_rep_ms=900,
        max_rep_ms=8_000,
        rising_completes=True,
    ),
    scoring=ScoringSpec(xp_per_rep=1.2, daily_rep_cap=300, diminishing_after_reps=140),
    validation=ValidationSpec(
        max_reps_per_second=1.2, min_reps_per_second=0.06,
        min_reps=15, min_duration_ms=30_000,
    ),
    setup_hint=(
        "Phone side-on to the arm you are pulling with, far enough back to see "
        "it from full reach to your hip. Hinge at the hips so your back is "
        "flat -- standing upright turns this into a different exercise."
    ),
    quality=QualitySpec(
        # Measured. Hinged forward, the hand starts about half a torso above
        # the shoulder line and finishes about 0.7 below it at the hip, so a
        # full pull covers roughly 1.15. The 0.90 I first wrote would have paid
        # full depth for a pull that stopped at the ribs.
        target_rom=1.15,
        consistency_target=0.12,
        consistency_ceiling=0.38,
        tempo_min_ms=900,
        tempo_max_ms=3_500,
        # Depth is the point. The back half of the pull is the half that
        # disappears when a swimmer gets tired, in the water and out of it.
        w_consistency=0.25,
        w_depth=0.40,
        w_tempo=0.15,
        w_endurance=0.20,
        min_reps=15,
    ),
    load=LoadSpec(
        load_per_rep=0.7,
        # Same reasoning as the streamline: the right tissue, and deliberately
        # not the pitch-derived throw count.
        throws_per_rep=0.0,
        tissue=Tissue.THROWING,
    ),
    tracks_handedness=True,
)


ALL_DRILLS: tuple[DrillSpec, ...] = (
    SOC_JUGGLE,
    SOC_JUGGLE_WEAK,
    SOC_JUGGLE_ALT,
    SOC_THIGH,
    SOC_WALL_PASS,
    SOC_TOE_TAPS,
    SOC_SHUFFLE,
    BKB_DRIBBLE,
    BKB_CROSSOVER,
    BKB_BETWEEN_LEGS,
    BKB_POUND_WEAK,
    BKB_POUND_LOW,
    BKB_WALL_PASS,
    BKB_STANCE,
    BKB_SLIDE,
    BKB_FORM_SHOT,
    VB_SET,
    VB_PASS,
    VB_SET_WALL,
    VB_SERVE,
    VB_ARM_SWING,
    VB_APPROACH,
    VB_BLOCK_JUMP,
    BB_WALL_THROW,
    BB_LONG_TOSS,
    BB_QUICK_HANDS,
    BB_TEE_SWING,
    BB_FIELDING,
    BB_CATCHER_STANCE,
    SB_WINDMILL,
    TEN_WALL_RALLY,
    TEN_ALTERNATE,
    TEN_ONE_WING,
    TEN_VOLLEY,
    TEN_SERVE,
    TEN_SPLIT_STEP,
    TEN_RECOVERY,
    HOC_STICKHANDLE,
    HOC_WIDE_HANDLES,
    HOC_SHOT,
    HOC_BUTTERFLY,
    HOC_SHUFFLE,
    HOC_STANCE,
    FB_QUICK_RELEASE,
    FB_WALL_THROW,
    FB_DEEP_BALL,
    FB_KICK,
    FB_SHUFFLE,
    RUG_QUICK_HANDS,
    RUG_WALL_PASS,
    RUG_SPIN_PASS,
    SWM_STREAMLINE,
    SWM_PULL,
    GEN_LUNGE,
    GEN_GLUTE_BRIDGE,
    GEN_MOUNTAIN_CLIMBER,
    GEN_TUCK_JUMP,
    GEN_DEAD_BUG,
    GEN_WALL_SIT,
    GEN_HOLLOW_HOLD,
    GEN_SIDE_PLANK,
    GEN_BUTT_KICK,
    GEN_KNEE_DRIVE_HOLD,
    GEN_POGO,
    GEN_SKATER_BOUND,
    GEN_CALF_RAISE,
    GEN_HANDSTAND_HOLD,
    GEN_DEAD_HANG,
    WALL_BALL,
    QUICK_STICK,
    WALL_BALL_STRONG,
    WALL_BALL_OFFHAND,
    WALL_BALL_ONE_HAND,
    WALL_BALL_CROSS,
    WALL_BALL_BTB,
    WALL_BALL_SPLIT,
    GROUND_BALL,
    FACEOFF_CLAMP,
    GOALIE_SAVES,
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
