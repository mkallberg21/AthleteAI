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
    colour="white",
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

SOC_JUGGLE = DrillSpec(
    key="soc_juggle",
    name="Juggling",
    sport="soccer",
    category=Category.SKILL,
    metric=Metric.REPS,
    description="Keep it up. Counts every touch, and which foot took it.",
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=200, max_rep_ms=6_000,
    ),
    ball=BallSpec(
        required=True,
        contact="body",
        parts=("left_ankle", "right_ankle", "left_knee", "right_knee", "nose"),
        min_gap_ms=200,
        min_speed=0.22,
        attribute_side=True,
        detector="vision",
        colour="white",
        diameter_cm=20.5,
    ),
    scoring=ScoringSpec(xp_per_rep=0.9, daily_rep_cap=600, diminishing_after_reps=200),
    validation=ValidationSpec(max_reps_per_second=3.0, min_reps=6),
    setup_hint="Prop the phone up anywhere it can see you and the ball. Any angle.",
    quality=None,
    load=LoadSpec(load_per_rep=0.3, load_per_minute=1.6, tissue=Tissue.LOWER_BODY),
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
    colour="basketball",
    diameter_cm=23.0,
)


BKB_DRIBBLE = DrillSpec(
    key="bkb_dribble",
    name="Dribbling",
    sport="basketball",
    category=Category.SKILL,
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

BKB_STANCE = DrillSpec(
    key="bkb_stance",
    name="Defensive Stance",
    sport="basketball",
    category=Category.CONDITIONING,
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


VB_SET = DrillSpec(
    key="vb_set",
    name="Setting",
    sport="volleyball",
    category=Category.SKILL,
    metric=Metric.REPS,
    description="Set it straight up, over and over. Counts every clean contact.",
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=350, max_rep_ms=6_000,
    ),
    ball=BallSpec(
        required=True,
        contact="body",
        parts=("left_wrist", "right_wrist", "nose"),
        min_gap_ms=350,
        min_speed=0.28,
        attribute_side=False,
        detector="vision",
        colour="white",
        diameter_cm=21.0,
    ),
    scoring=ScoringSpec(xp_per_rep=1.0, daily_rep_cap=500, diminishing_after_reps=180),
    validation=ValidationSpec(max_reps_per_second=2.0, min_reps=6),
    setup_hint="Prop the phone up so it can see you and the top of the ball's flight.",
    quality=None,
    load=LoadSpec(load_per_rep=0.3, load_per_minute=1.4, tissue=Tissue.UPPER_BODY),
)

BB_WALL_THROW = DrillSpec(
    key="bb_wall_throw",
    name="Wall Throws",
    sport="baseball",
    category=Category.SKILL,
    metric=Metric.REPS,
    description="Throw and field off a wall. Counts every catch.",
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=500, max_rep_ms=8_000,
    ),
    ball=BallSpec(
        required=True,
        contact="body",
        parts=("left_wrist", "right_wrist"),
        min_gap_ms=500,
        min_speed=0.35,
        attribute_side=True,
        detector="vision",
        colour="white",
        diameter_cm=7.4,
    ),
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

TEN_WALL_RALLY = DrillSpec(
    key="ten_wall_rally",
    name="Wall Rally",
    sport="tennis",
    category=Category.SKILL,
    metric=Metric.REPS,
    description="Rally against a wall. Counts every shot you hit.",
    signal=SignalSpec(kind=SignalKind.BODY_HEIGHT, smoothing=0.4),
    counter=CounterSpec(
        down_threshold=0.0, up_threshold=1.0, min_rep_ms=350, max_rep_ms=6_000,
    ),
    ball=BallSpec(
        required=True,
        contact="body",
        parts=("left_wrist", "right_wrist"),
        min_gap_ms=350,
        # A tennis ball comes off the strings fast, which makes the impulse
        # obvious -- and lets the floor bounce in between be ignored.
        min_speed=0.45,
        attribute_side=True,
        detector="vision",
        colour="optic",
        diameter_cm=6.7,
    ),
    scoring=ScoringSpec(xp_per_rep=0.8, daily_rep_cap=700, diminishing_after_reps=250),
    validation=ValidationSpec(max_reps_per_second=2.5, min_reps=8),
    setup_hint="Prop the phone up behind or beside you. It just needs to see the ball.",
    quality=None,
    load=LoadSpec(load_per_rep=0.5, load_per_minute=1.8, tissue=Tissue.UPPER_BODY),
    tracks_handedness=True,
)


ALL_DRILLS: tuple[DrillSpec, ...] = (
    SOC_JUGGLE,
    BKB_DRIBBLE,
    BKB_CROSSOVER,
    BKB_BETWEEN_LEGS,
    BKB_POUND_WEAK,
    BKB_POUND_LOW,
    BKB_WALL_PASS,
    BKB_STANCE,
    VB_SET,
    BB_WALL_THROW,
    TEN_WALL_RALLY,
    GEN_LUNGE,
    GEN_GLUTE_BRIDGE,
    GEN_MOUNTAIN_CLIMBER,
    GEN_TUCK_JUMP,
    GEN_DEAD_BUG,
    GEN_WALL_SIT,
    GEN_HOLLOW_HOLD,
    GEN_SIDE_PLANK,
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
