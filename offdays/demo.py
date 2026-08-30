"""An animated figure showing what a drill *is*, before anyone attempts it.

The technique reference already answers "was that rep any good". It does not
answer "what is a dead bug", and a ten-year-old opening that drill for the
first time needs the second question answered first. What they get today is a
setup hint, corrective cues written for someone who already knows the shape,
and a trace -- which is a line of joint angle against time. A curve of degrees
is not an answer to what a movement looks like.

So: a small animated figure, drawn as SVG.

**Why not video.** Third-party embeds put an ad, a sidebar of recommendations
and a link out in front of a child mid-session, which is why film study
already refuses them. Filming 89 drills is a real project that stays undone,
and a video is megabytes down a phone connection in a garden. A program that
films its own can still drop one in `web/static/technique/<key>.mp4` and it is
offered alongside this -- that hook already exists and is untouched.

**Why SVG.** A few kilobytes, no codec, no network, scales to any screen, and
it animates natively. More importantly it is *generated from the same numbers
the scorer marks against*: the tempo here is the drill's own refractory
window, so the demonstration cannot drift out of agreement with the counter
the way a clip filmed once and a threshold tuned later silently do.

**What it cannot be.** The pose itself is not derivable from the drill spec.
The spec knows a dead bug is a hip angle through 66 degrees over 3 seconds; it
does not know the athlete is lying on their back. So each drill needs a short
hand-authored posture, and `coverage()` reports which ones still lack it
rather than letting the gap go quiet.

**Where this works, and where it does not.** Drawn and looked at rather than
assumed, which changed the answer twice. A squat reads immediately: an upright
body has a silhouette a child already recognises. A push-up, a plank, a
pull-up, a wall sit and a burpee are all legible. A dead bug is *not* -- two
attempts at the coordinates and it still read as an angular abstraction rather
than a person lying on their back. Floor work seen side-on gives a stick
figure nothing to be recognised by, and nudging the numbers does not fix it.

So the answer is a hybrid, and `NEEDS_FILM` below is the other half of it: the
drills where this technique fails, named with the reason, so the backlog is a
list somebody can shoot rather than a silence. `web/static/technique/<key>.mp4`
already accepts a clip and has since the technique reference shipped.

Three things the sport-specific drills added to that rule.

**Equipment is drawable, and it carries most of the meaning.** A lacrosse
figure without a stick is a person standing near a wall. With one it is
unmistakable, and the stick tells you more about the drill than the body does.
So a pose may place `stick_butt`, `stick_head` and `ball` alongside its
joints. That is what makes an implement sport possible here at all.

**Some drills legitimately share a picture.** Wall ball, strong hand, off hand
and quick stick are the same shape; the difference is which hand is on top, or
the tempo, and a two-frame drawing shows neither. They share the frames and
carry the difference in the caption, which is honest -- the athlete who does
not know what wall ball is still needs that answered, and the picture answers
it. Pretending to a distinction the drawing does not make would be worse than
sharing one.

**The failure mode has a name now.** A drawing fails when the movement happens
in the axis the view flattens. That is why a dead bug fails side-on and a
sit-up does not, and why behind-the-back wall ball is on the film list: the
stick goes *behind* the athlete, and drawn side-on it reads as a stick through
the stomach. The same rule decides `view` for every pose here: a wide base or
a lateral path wants the front, a depth of stance or a swing wants the side.
Four basketball drills changed view during the work because of it, and a
volleyball platform did -- arms held out in front are exactly what a front
view has none of.

All 89 drills are settled now: 85 drawn, and the four in `NEEDS_FILM` waiting
on a camera. That is a morning's filming rather than a project.

Two things learned by rendering it rather than reasoning about it. Figures
that floated above the ground line read as falling, so poses now rest their
contact points on it. And a foot had to be added: without a toe, a calf raise
and a pogo hop draw as the same two frames as standing still, because a
lifted heel is the entire movement.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .drills import ALL_DRILLS

#: Segments of the stick figure, as chains of named joints. Drawn as polylines
#: so a whole limb animates as one attribute rather than four.
CHAINS: tuple[tuple[str, ...], ...] = (
    ("neck", "hip"),
    ("neck", "elbow_far", "wrist_far"),
    ("neck", "elbow_near", "wrist_near"),
    ("hip", "knee_far", "ankle_far", "toe_far"),
    ("hip", "knee_near", "ankle_near", "toe_near"),
)

#: Sports whose ball is not round. Taken from the drill's sport rather than
#: set per pose, because a football is oblong in every drill it appears in and
#: a per-pose flag is a per-pose chance to forget.
OVAL_BALL_SPORTS: frozenset[str] = frozenset({"football", "rugby"})

#: Joints a pose may place but need not. A stick is the difference between a
#: figure doing something and a figure standing there, and for a sport played
#: with one it carries more of the meaning than the body does. The ball is
#: drawn only in the frames where it is in the air.
OPTIONAL_JOINTS: tuple[str, ...] = ("stick_butt", "stick_head", "ball")

#: Joints every pose must place. The head is a circle, not a chain.
#: The foot earns its place: without a toe, a calf raise and a pogo hop are
#: the same two frames as standing still, because a lifted heel is the whole
#: movement and there was nothing on screen for it to lift off.
JOINTS: tuple[str, ...] = (
    "head", "neck", "hip",
    "elbow_near", "wrist_near", "elbow_far", "wrist_far",
    "knee_near", "ankle_near", "toe_near",
    "knee_far", "ankle_far", "toe_far",
)


@dataclass(frozen=True)
class Demo:
    """A drill's demonstration: a few postures and how to read them."""

    #: Keyframes, each a full set of joint positions in a 100x100 box.
    frames: tuple[dict[str, tuple[float, float]], ...]
    #: One line naming the movement in words a child has not had to learn.
    caption: str
    #: Ground, wall or bar to draw behind the figure, for orientation.
    scenery: str = "floor"
    #: "side" fades the far limbs so a profile reads as a body rather than a
    #: tangle of identical sticks. "front" does not: facing the camera there
    #: is no far side, and dimming half of one reads as something wrong.
    view: str = "side"
    #: Play the frames forward then back, which is what a rep does.
    mirror: bool = True
    #: Seconds for one cycle. Filled from the drill's own tempo when absent.
    seconds: float | None = None


def _pose(**joints: tuple[float, float]) -> dict[str, tuple[float, float]]:
    missing = [j for j in JOINTS if j not in joints]
    if missing:
        raise ValueError(f"pose is missing {missing}")
    unknown = [j for j in joints if j not in JOINTS and j not in OPTIONAL_JOINTS]
    if unknown:
        raise ValueError(f"pose names joints that do not exist: {unknown}")
    if ("stick_butt" in joints) != ("stick_head" in joints):
        raise ValueError("a stick needs both ends")
    return dict(joints)


# ---------------------------------------------------------------------------
# Postures. Hand-authored, because the spec cannot know which way up a body is.
# Coordinates are a 100x100 box, y downwards, figure facing right.
# ---------------------------------------------------------------------------
DEMOS: dict[str, Demo] = {
    "gen_squat": Demo(
        caption='Stand tall, sit down and back as if reaching for a chair behind you, then stand all the way up.',
        frames=(
            _pose(head=(52, 13), neck=(52, 25), hip=(51, 53),
                  elbow_near=(47, 40), wrist_near=(47, 52),
                  elbow_far=(57, 40), wrist_far=(57, 52),
                  knee_near=(50, 71), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(54, 71), ankle_far=(54, 90), toe_far=(60, 90)),
            _pose(head=(45, 33), neck=(47, 44), hip=(56, 67),
                  elbow_near=(41, 53), wrist_near=(33, 49),
                  elbow_far=(50, 53), wrist_far=(42, 48),
                  knee_near=(45, 73), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(49, 73), ankle_far=(54, 90), toe_far=(60, 90)),
        ),
    ),
    "gen_squat_jump": Demo(
        caption='Dip into a quarter squat, then jump as high as you can and land soft.',
        frames=(
            _pose(head=(47, 29), neck=(48, 39), hip=(55, 63),
                  elbow_near=(53, 51), wrist_near=(59, 59),
                  elbow_far=(57, 51), wrist_far=(63, 59),
                  knee_near=(46, 73), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(50, 73), ankle_far=(54, 90), toe_far=(60, 90)),
            _pose(head=(50, 6), neck=(50, 18), hip=(50, 46),
                  elbow_near=(46, 31), wrist_near=(44, 17),
                  elbow_far=(54, 31), wrist_far=(56, 17),
                  knee_near=(49, 64), ankle_near=(49, 80), toe_near=(54, 84),
                  knee_far=(53, 64), ankle_far=(53, 80), toe_far=(58, 84)),
        ),
    ),
    "gen_tuck_jump": Demo(
        caption='Jump, and pull both knees up towards your chest before you land. Land soft and go again.',
        frames=(
            _pose(head=(49, 26), neck=(49, 36), hip=(53, 61),
                  elbow_near=(52, 49), wrist_near=(57, 57),
                  elbow_far=(56, 49), wrist_far=(61, 57),
                  knee_near=(46, 73), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(50, 73), ankle_far=(54, 90), toe_far=(60, 90)),
            _pose(head=(48, 10), neck=(48, 21), hip=(50, 47),
                  elbow_near=(40, 30), wrist_near=(38, 41),
                  elbow_far=(55, 31), wrist_far=(58, 42),
                  knee_near=(38, 38), ankle_near=(43, 54), toe_near=(49, 58),
                  knee_far=(43, 40), ankle_far=(48, 56), toe_far=(54, 60)),
        ),
    ),
    "gen_pogo": Demo(
        caption='Small fast bounces off the balls of your feet, knees almost straight. Spend as little time on the floor as you can.',
        frames=(
            _pose(head=(50, 24), neck=(50, 35), hip=(50, 62),
                  elbow_near=(46, 49), wrist_near=(46, 62),
                  elbow_far=(55, 49), wrist_far=(55, 62),
                  knee_near=(49, 78), ankle_near=(49, 88), toe_near=(55, 90),
                  knee_far=(53, 78), ankle_far=(53, 88), toe_far=(59, 90)),
            _pose(head=(50, 6), neck=(50, 17), hip=(50, 44),
                  elbow_near=(46, 31), wrist_near=(46, 44),
                  elbow_far=(55, 31), wrist_far=(55, 44),
                  knee_near=(49, 60), ankle_near=(49, 72), toe_near=(55, 77),
                  knee_far=(53, 60), ankle_far=(53, 72), toe_far=(59, 77)),
        ),
    ),
    "gen_lunge": Demo(
        caption='Step forward and drop the back knee towards the floor, then drive back to standing. Alternate legs.',
        frames=(
            _pose(head=(50, 13), neck=(50, 25), hip=(50, 53),
                  elbow_near=(46, 40), wrist_near=(46, 52),
                  elbow_far=(55, 40), wrist_far=(55, 52),
                  knee_near=(49, 71), ankle_near=(49, 90), toe_near=(55, 90),
                  knee_far=(53, 71), ankle_far=(53, 90), toe_far=(59, 90)),
            _pose(head=(49, 20), neck=(49, 32), hip=(48, 59),
                  elbow_near=(45, 46), wrist_near=(45, 58),
                  elbow_far=(53, 46), wrist_far=(53, 58),
                  knee_near=(64, 70), ankle_near=(64, 90), toe_near=(70, 90),
                  knee_far=(34, 78), ankle_far=(28, 88), toe_far=(33, 90)),
        ),
    ),
    "gen_calf_raise": Demo(
        caption='Rise all the way up onto your toes, then lower under control. Coming up half way does not count.',
        frames=(
            _pose(head=(50, 15), neck=(50, 26), hip=(50, 54),
                  elbow_near=(46, 41), wrist_near=(46, 54),
                  elbow_far=(55, 41), wrist_far=(55, 54),
                  knee_near=(49, 72), ankle_near=(49, 90), toe_near=(55, 90),
                  knee_far=(53, 72), ankle_far=(53, 90), toe_far=(59, 90)),
            _pose(head=(50, 9), neck=(50, 20), hip=(50, 48),
                  elbow_near=(46, 35), wrist_near=(46, 48),
                  elbow_far=(55, 35), wrist_far=(55, 48),
                  knee_near=(49, 66), ankle_near=(49, 84), toe_near=(55, 90),
                  knee_far=(53, 66), ankle_far=(53, 84), toe_far=(59, 90)),
        ),
    ),
    "gen_high_knees": Demo(
        caption='Run on the spot, driving each knee above hip height. Every knee that gets up there counts as one.',
        frames=(
            _pose(head=(48, 13), neck=(48, 25), hip=(49, 53),
                  elbow_near=(56, 38), wrist_near=(60, 48),
                  elbow_far=(41, 38), wrist_far=(37, 48),
                  knee_near=(60, 50), ankle_near=(60, 68), toe_near=(66, 71),
                  knee_far=(49, 71), ankle_far=(49, 90), toe_far=(55, 90)),
            _pose(head=(48, 13), neck=(48, 25), hip=(49, 53),
                  elbow_near=(41, 38), wrist_near=(37, 48),
                  elbow_far=(56, 38), wrist_far=(60, 48),
                  knee_near=(49, 71), ankle_near=(49, 90), toe_near=(55, 90),
                  knee_far=(60, 50), ankle_far=(60, 68), toe_far=(66, 71)),
        ),
    ),
    "gen_skater_bound": Demo(
        caption='Bound sideways off one leg, land on the other, and hold it still before you go back.',
        frames=(
            _pose(head=(40, 15), neck=(40, 26), hip=(43, 53),
                  elbow_near=(50, 39), wrist_near=(56, 45),
                  elbow_far=(34, 40), wrist_far=(28, 50),
                  knee_near=(40, 71), ankle_near=(38, 90), toe_near=(44, 90),
                  knee_far=(55, 66), ankle_far=(64, 77), toe_far=(69, 81)),
            _pose(head=(60, 15), neck=(60, 26), hip=(57, 53),
                  elbow_near=(50, 39), wrist_near=(44, 45),
                  elbow_far=(66, 40), wrist_far=(72, 50),
                  knee_near=(60, 71), ankle_near=(62, 90), toe_near=(68, 90),
                  knee_far=(45, 66), ankle_far=(36, 77), toe_far=(41, 81)),
        ),
    ),
    "gen_wall_sit": Demo(
        caption='Back flat on the wall, thighs level with the floor, knees above your ankles. Hold it.',
        scenery='wall',
        mirror=False,
        seconds=4.0,
        frames=(
            _pose(head=(15, 32), neck=(15, 42), hip=(14, 66),
                  elbow_near=(26, 56), wrist_near=(36, 54),
                  elbow_far=(27, 57), wrist_far=(37, 55),
                  knee_near=(40, 66), ankle_near=(40, 90), toe_near=(46, 90),
                  knee_far=(44, 67), ankle_far=(44, 90), toe_far=(50, 90)),
        ),
    ),
    "gen_dead_hang": Demo(
        caption='Hang from the bar with straight arms and let your shoulders stretch out. Hold it.',
        scenery='bar',
        mirror=False,
        seconds=4.0,
        frames=(
            _pose(head=(50, 28), neck=(50, 37), hip=(50, 60),
                  elbow_near=(47, 19), wrist_near=(45, 10),
                  elbow_far=(53, 19), wrist_far=(55, 10),
                  knee_near=(49, 72), ankle_near=(49, 84), toe_near=(54, 88),
                  knee_far=(53, 72), ankle_far=(53, 84), toe_far=(58, 88)),
        ),
    ),
    "gen_pull_up": Demo(
        caption='Hang with straight arms, pull until your nose is above the bar, then lower all the way back down.',
        scenery='bar',
        frames=(
            _pose(head=(50, 28), neck=(50, 37), hip=(50, 60),
                  elbow_near=(47, 19), wrist_near=(45, 10),
                  elbow_far=(53, 19), wrist_far=(55, 10),
                  knee_near=(49, 72), ankle_near=(49, 84), toe_near=(54, 88),
                  knee_far=(53, 72), ankle_far=(53, 84), toe_far=(58, 88)),
            _pose(head=(50, 8), neck=(50, 19), hip=(50, 44),
                  elbow_near=(38, 18), wrist_near=(45, 10),
                  elbow_far=(62, 18), wrist_far=(55, 10),
                  knee_near=(49, 58), ankle_near=(49, 72), toe_near=(54, 76),
                  knee_far=(53, 58), ankle_far=(53, 72), toe_far=(58, 76)),
        ),
    ),
    "gen_push_up": Demo(
        caption='A straight line from your head to your heels. Bend until your chest is near the floor, then press all the way up.',
        frames=(
            _pose(head=(22, 54), neck=(30, 58), hip=(58, 72),
                  elbow_near=(29, 74), wrist_near=(28, 90),
                  elbow_far=(30, 75), wrist_far=(29, 90),
                  knee_near=(74, 81), ankle_near=(88, 86), toe_near=(92, 90),
                  knee_far=(75, 82), ankle_far=(89, 87), toe_far=(93, 90)),
            _pose(head=(22, 68), neck=(30, 71), hip=(58, 80),
                  elbow_near=(43, 76), wrist_near=(28, 90),
                  elbow_far=(44, 77), wrist_far=(29, 90),
                  knee_near=(74, 85), ankle_near=(88, 86), toe_near=(92, 90),
                  knee_far=(75, 86), ankle_far=(89, 87), toe_far=(93, 90)),
        ),
    ),
    "gen_plank": Demo(
        caption='On your forearms, straight from head to heels. Hips neither sagging nor stuck up in the air. Hold it.',
        mirror=False,
        seconds=4.0,
        frames=(
            _pose(head=(24, 60), neck=(32, 64), hip=(60, 76),
                  elbow_near=(32, 90), wrist_near=(46, 90),
                  elbow_far=(33, 90), wrist_far=(47, 90),
                  knee_near=(76, 83), ankle_near=(90, 86), toe_near=(94, 90),
                  knee_far=(77, 84), ankle_far=(91, 87), toe_far=(95, 90)),
        ),
    ),
    "gen_side_plank": Demo(
        caption='On one forearm, feet stacked, body in a straight line. Lift your hip up and keep it there.',
        mirror=False,
        seconds=4.0,
        frames=(
            _pose(head=(26, 48), neck=(32, 56), hip=(54, 70),
                  elbow_near=(38, 42), wrist_near=(40, 28),
                  elbow_far=(30, 74), wrist_far=(17, 88),
                  knee_near=(70, 80), ankle_near=(85, 86), toe_near=(91, 90),
                  knee_far=(71, 81), ankle_far=(86, 87), toe_far=(92, 90)),
        ),
    ),
    "gen_mountain_climber": Demo(
        caption='Hold a push-up position and drive one knee at a time in towards your chest, quickly.',
        frames=(
            _pose(head=(22, 54), neck=(30, 58), hip=(58, 72),
                  elbow_near=(29, 74), wrist_near=(28, 90),
                  elbow_far=(30, 75), wrist_far=(29, 90),
                  knee_near=(48, 72), ankle_near=(58, 82), toe_near=(63, 85),
                  knee_far=(75, 82), ankle_far=(89, 87), toe_far=(93, 90)),
            _pose(head=(22, 54), neck=(30, 58), hip=(58, 72),
                  elbow_near=(29, 74), wrist_near=(28, 90),
                  elbow_far=(30, 75), wrist_far=(29, 90),
                  knee_near=(74, 81), ankle_near=(88, 86), toe_near=(92, 90),
                  knee_far=(49, 73), ankle_far=(59, 83), toe_far=(64, 86)),
        ),
    ),
    "gen_burpee": Demo(
        caption='Stand, drop into a push-up position, jump your feet back in, and jump up. All of that is one.',
        mirror=False,
        frames=(
            _pose(head=(50, 13), neck=(50, 25), hip=(50, 53),
                  elbow_near=(46, 40), wrist_near=(46, 52),
                  elbow_far=(55, 40), wrist_far=(55, 52),
                  knee_near=(49, 71), ankle_near=(49, 90), toe_near=(55, 90),
                  knee_far=(53, 71), ankle_far=(53, 90), toe_far=(59, 90)),
            _pose(head=(22, 54), neck=(30, 58), hip=(58, 72),
                  elbow_near=(29, 74), wrist_near=(28, 90),
                  elbow_far=(30, 75), wrist_far=(29, 90),
                  knee_near=(74, 81), ankle_near=(88, 86), toe_near=(92, 90),
                  knee_far=(75, 82), ankle_far=(89, 87), toe_far=(93, 90)),
            _pose(head=(50, 13), neck=(50, 25), hip=(50, 53),
                  elbow_near=(46, 40), wrist_near=(46, 52),
                  elbow_far=(55, 40), wrist_far=(55, 52),
                  knee_near=(49, 71), ankle_near=(49, 90), toe_near=(55, 90),
                  knee_far=(53, 71), ankle_far=(53, 90), toe_far=(59, 90)),
            _pose(head=(50, 6), neck=(50, 18), hip=(50, 46),
                  elbow_near=(46, 31), wrist_near=(44, 17),
                  elbow_far=(54, 31), wrist_far=(56, 17),
                  knee_near=(49, 64), ankle_near=(49, 80), toe_near=(54, 84),
                  knee_far=(53, 64), ankle_far=(53, 80), toe_far=(58, 84)),
        ),
    ),
    "gen_handstand_hold": Demo(
        caption='Hands on the floor, walk your feet up the wall until your body is straight and upside down. Hold it.',
        scenery='wall',
        mirror=False,
        seconds=4.0,
        frames=(
            _pose(head=(32, 74), neck=(26, 66), hip=(20, 42),
                  elbow_near=(28, 78), wrist_near=(30, 90),
                  elbow_far=(29, 79), wrist_far=(31, 90),
                  knee_near=(16, 27), ankle_near=(13, 12), toe_near=(19, 10),
                  knee_far=(17, 28), ankle_far=(14, 13), toe_far=(20, 11)),
        ),
    ),
    "gen_butt_kick": Demo(
        caption="Run on the spot snapping your heels up towards your "
                "backside, staying tall. Do not lean forward.",
        frames=(
            _pose(head=(48, 13), neck=(48, 25), hip=(49, 53),
                  elbow_near=(56, 38), wrist_near=(60, 48),
                  elbow_far=(41, 38), wrist_far=(37, 48),
                  knee_near=(50, 72), ankle_near=(42, 62), toe_near=(37, 65),
                  knee_far=(49, 71), ankle_far=(49, 90), toe_far=(55, 90)),
            _pose(head=(48, 13), neck=(48, 25), hip=(49, 53),
                  elbow_near=(41, 38), wrist_near=(37, 48),
                  elbow_far=(56, 38), wrist_far=(60, 48),
                  knee_near=(49, 71), ankle_near=(49, 90), toe_near=(55, 90),
                  knee_far=(50, 72), ankle_far=(42, 62), toe_far=(37, 65)),
        ),
    ),
    "gen_knee_drive_hold": Demo(
        caption="Hands on a wall, body in one straight line from head to "
                "heel, one knee driven up and held there.",
        scenery="wall",
        mirror=False,
        seconds=4.0,
        frames=(
            _pose(head=(30, 20), neck=(32, 31), hip=(38, 58),
                  elbow_near=(22, 32), wrist_near=(10, 30),
                  elbow_far=(23, 33), wrist_far=(11, 31),
                  knee_near=(25, 48), ankle_near=(31, 62), toe_near=(37, 65),
                  knee_far=(45, 74), ankle_far=(51, 88), toe_far=(57, 90)),
        ),
    ),
    "gen_sit_up": Demo(
        caption="Lie back with your knees bent, curl all the way up until "
                "your chest is near your thighs, then lower back down.",
        frames=(
            _pose(head=(18, 84), neck=(26, 86), hip=(52, 88),
                  elbow_near=(22, 78), wrist_near=(16, 82),
                  elbow_far=(23, 79), wrist_far=(17, 83),
                  knee_near=(66, 72), ankle_near=(74, 86), toe_near=(80, 90),
                  knee_far=(67, 73), ankle_far=(75, 87), toe_far=(81, 90)),
            _pose(head=(44, 54), neck=(43, 64), hip=(52, 88),
                  elbow_near=(36, 60), wrist_near=(40, 52),
                  elbow_far=(37, 61), wrist_far=(41, 53),
                  knee_near=(66, 72), ankle_near=(74, 86), toe_near=(80, 90),
                  knee_far=(67, 73), ankle_far=(75, 87), toe_far=(81, 90)),
        ),
    ),
    "gen_jumping_jack": Demo(
        caption="Jump your feet apart and your hands above your head at the "
                "same time, then back together.",
        view="front",
        frames=(
            _pose(head=(50, 12), neck=(50, 24), hip=(50, 52),
                  elbow_near=(44, 38), wrist_near=(42, 52),
                  elbow_far=(56, 38), wrist_far=(58, 52),
                  knee_near=(48, 71), ankle_near=(48, 90), toe_near=(43, 90),
                  knee_far=(53, 71), ankle_far=(53, 90), toe_far=(58, 90)),
            _pose(head=(50, 12), neck=(50, 24), hip=(50, 52),
                  elbow_near=(38, 30), wrist_near=(32, 16),
                  elbow_far=(62, 30), wrist_far=(68, 16),
                  knee_near=(40, 70), ankle_near=(34, 90), toe_near=(29, 90),
                  knee_far=(60, 70), ankle_far=(66, 90), toe_far=(71, 90)),
        ),
    ),
    "gen_lateral_bound": Demo(
        caption="Quick side-to-side bounds, landing on one leg each time. "
                "Smaller and faster than a skater bound.",
        view="front",
        frames=(
            _pose(head=(42, 14), neck=(42, 25), hip=(44, 52),
                  elbow_near=(49, 38), wrist_near=(54, 44),
                  elbow_far=(36, 40), wrist_far=(31, 48),
                  knee_near=(43, 70), ankle_near=(42, 90), toe_near=(37, 90),
                  knee_far=(54, 66), ankle_far=(60, 74), toe_far=(65, 77)),
            _pose(head=(58, 14), neck=(58, 25), hip=(56, 52),
                  elbow_near=(51, 38), wrist_near=(46, 44),
                  elbow_far=(64, 40), wrist_far=(69, 48),
                  knee_near=(57, 70), ankle_near=(58, 90), toe_near=(63, 90),
                  knee_far=(46, 66), ankle_far=(40, 74), toe_far=(35, 77)),
        ),
    ),
    "lax_wall_ball": Demo(
        caption='Side-on to a wall. Throw, catch what comes back, throw again — one throw and one catch is a rep.',
        scenery='wall',
        frames=(
            _pose(head=(60, 20), neck=(57, 30), hip=(56, 58),
                  elbow_near=(63, 26), wrist_near=(59, 17),
                  elbow_far=(64, 27), wrist_far=(60, 18),
                  knee_near=(54, 74), ankle_near=(54, 90), toe_near=(48, 90),
                  knee_far=(58, 74), ankle_far=(58, 90), toe_far=(52, 90),
                  stick_butt=(60, 24), stick_head=(78, 7),
                  ball=((62, 12)),),
            _pose(head=(55, 22), neck=(52, 32), hip=(55, 58),
                  elbow_near=(43, 30), wrist_near=(34, 25),
                  elbow_far=(44, 31), wrist_far=(35, 26),
                  knee_near=(52, 74), ankle_near=(53, 90), toe_near=(47, 90),
                  knee_far=(56, 74), ankle_far=(57, 90), toe_far=(51, 90),
                  stick_butt=(37, 27), stick_head=(19, 14),
                  ball=((12, 18)),),
        ),
    ),
    "lax_wall_ball_strong": Demo(
        caption='Wall ball with your strong hand on top of the stick every rep. Same picture as plain wall ball — the hand order is the drill.',
        scenery='wall',
        frames=(
            _pose(head=(60, 20), neck=(57, 30), hip=(56, 58),
                  elbow_near=(63, 26), wrist_near=(59, 17),
                  elbow_far=(64, 27), wrist_far=(60, 18),
                  knee_near=(54, 74), ankle_near=(54, 90), toe_near=(48, 90),
                  knee_far=(58, 74), ankle_far=(58, 90), toe_far=(52, 90),
                  stick_butt=(60, 24), stick_head=(78, 7),
                  ball=((62, 12)),),
            _pose(head=(55, 22), neck=(52, 32), hip=(55, 58),
                  elbow_near=(43, 30), wrist_near=(34, 25),
                  elbow_far=(44, 31), wrist_far=(35, 26),
                  knee_near=(52, 74), ankle_near=(53, 90), toe_near=(47, 90),
                  knee_far=(56, 74), ankle_far=(57, 90), toe_far=(51, 90),
                  stick_butt=(37, 27), stick_head=(19, 14),
                  ball=((12, 18)),),
        ),
    ),
    "lax_wall_ball_offhand": Demo(
        caption='Wall ball with your weaker hand on top every rep. It will feel wrong, and that is the point.',
        scenery='wall',
        frames=(
            _pose(head=(60, 20), neck=(57, 30), hip=(56, 58),
                  elbow_near=(63, 26), wrist_near=(59, 17),
                  elbow_far=(64, 27), wrist_far=(60, 18),
                  knee_near=(54, 74), ankle_near=(54, 90), toe_near=(48, 90),
                  knee_far=(58, 74), ankle_far=(58, 90), toe_far=(52, 90),
                  stick_butt=(60, 24), stick_head=(78, 7),
                  ball=((62, 12)),),
            _pose(head=(55, 22), neck=(52, 32), hip=(55, 58),
                  elbow_near=(43, 30), wrist_near=(34, 25),
                  elbow_far=(44, 31), wrist_far=(35, 26),
                  knee_near=(52, 74), ankle_near=(53, 90), toe_near=(47, 90),
                  knee_far=(56, 74), ankle_far=(57, 90), toe_far=(51, 90),
                  stick_butt=(37, 27), stick_head=(19, 14),
                  ball=((12, 18)),),
        ),
    ),
    "lax_quick_stick": Demo(
        caption='Stand closer and catch and release in one motion — no cradle, no wind-up. Faster than wall ball, same shape.',
        scenery='wall',
        frames=(
            _pose(head=(60, 20), neck=(57, 30), hip=(56, 58),
                  elbow_near=(63, 26), wrist_near=(59, 17),
                  elbow_far=(64, 27), wrist_far=(60, 18),
                  knee_near=(54, 74), ankle_near=(54, 90), toe_near=(48, 90),
                  knee_far=(58, 74), ankle_far=(58, 90), toe_far=(52, 90),
                  stick_butt=(60, 24), stick_head=(78, 7),
                  ball=((62, 12)),),
            _pose(head=(55, 22), neck=(52, 32), hip=(55, 58),
                  elbow_near=(43, 30), wrist_near=(34, 25),
                  elbow_far=(44, 31), wrist_far=(35, 26),
                  knee_near=(52, 74), ankle_near=(53, 90), toe_near=(47, 90),
                  knee_far=(56, 74), ankle_far=(57, 90), toe_far=(51, 90),
                  stick_butt=(37, 27), stick_head=(19, 14),
                  ball=((12, 18)),),
        ),
    ),
    "lax_wall_ball_one_hand": Demo(
        caption='Bottom hand off the stick. Short, controlled throws with the top hand only, standing close to the wall.',
        scenery='wall',
        frames=(
            _pose(head=(60, 20), neck=(57, 30), hip=(56, 58),
                  elbow_near=(62, 26), wrist_near=(58, 17),
                  elbow_far=(48, 40), wrist_far=(42, 50),
                  knee_near=(54, 74), ankle_near=(54, 90), toe_near=(48, 90),
                  knee_far=(58, 74), ankle_far=(58, 90), toe_far=(52, 90),
                  stick_butt=(59, 24), stick_head=(76, 9), ball=(61, 14)),
            _pose(head=(56, 22), neck=(53, 32), hip=(55, 58),
                  elbow_near=(44, 30), wrist_near=(36, 26),
                  elbow_far=(46, 42), wrist_far=(40, 52),
                  knee_near=(52, 74), ankle_near=(53, 90), toe_near=(47, 90),
                  knee_far=(56, 74), ankle_far=(57, 90), toe_far=(51, 90),
                  stick_butt=(38, 28), stick_head=(21, 16), ball=(13, 20)),
                ),
    ),
    "lax_wall_ball_cross": Demo(
        caption='Catch on one side of your head, switch hands, throw from the other. Alternate every rep.',
        scenery='wall',
        frames=(
            _pose(head=(58, 20), neck=(55, 30), hip=(56, 58),
                  elbow_near=(64, 26), wrist_near=(62, 16),
                  elbow_far=(65, 27), wrist_far=(63, 17),
                  knee_near=(54, 74), ankle_near=(54, 90), toe_near=(48, 90),
                  knee_far=(58, 74), ankle_far=(58, 90), toe_far=(52, 90),
                  stick_butt=(62, 22), stick_head=(80, 10)),
            _pose(head=(56, 20), neck=(53, 30), hip=(56, 58),
                  elbow_near=(43, 26), wrist_near=(38, 16),
                  elbow_far=(44, 27), wrist_far=(39, 17),
                  knee_near=(54, 74), ankle_near=(54, 90), toe_near=(48, 90),
                  knee_far=(58, 74), ankle_far=(58, 90), toe_far=(52, 90),
                  stick_butt=(40, 22), stick_head=(24, 10)),
        ),
    ),
    "lax_wall_ball_split": Demo(
        caption='Catch, plant your foot and split dodge, then throw from the new hand. Footwork and hands in one rep.',
        scenery='wall',
        frames=(
            _pose(head=(58, 20), neck=(55, 30), hip=(56, 58),
                  elbow_near=(63, 26), wrist_near=(59, 17),
                  elbow_far=(64, 27), wrist_far=(60, 18),
                  knee_near=(54, 74), ankle_near=(54, 90), toe_near=(48, 90),
                  knee_far=(58, 74), ankle_far=(58, 90), toe_far=(52, 90),
                  stick_butt=(60, 24), stick_head=(78, 7)),
            _pose(head=(50, 24), neck=(48, 34), hip=(54, 60),
                  elbow_near=(40, 32), wrist_near=(32, 28),
                  elbow_far=(41, 33), wrist_far=(33, 29),
                  knee_near=(40, 74), ankle_near=(34, 90), toe_near=(28, 90),
                  knee_far=(62, 74), ankle_far=(66, 90), toe_far=(72, 90),
                  stick_butt=(35, 30), stick_head=(18, 17)),
        ),
    ),
    "lax_ground_ball": Demo(
        caption='Roll the ball out in front of you, get low and scoop through it, then come up ready. Do not stab at it.',
        scenery='floor',
        frames=(
            _pose(head=(44, 42), neck=(48, 50), hip=(60, 64),
                  elbow_near=(44, 58), wrist_near=(38, 72),
                  elbow_far=(45, 59), wrist_far=(39, 73),
                  knee_near=(66, 76), ankle_near=(74, 90), toe_near=(80, 90),
                  knee_far=(58, 76), ankle_far=(50, 90), toe_far=(44, 90),
                  stick_butt=(40, 74), stick_head=(24, 86),
                  ball=((18, 88)),),
            _pose(head=(52, 20), neck=(52, 31), hip=(56, 58),
                  elbow_near=(58, 30), wrist_near=(56, 20),
                  elbow_far=(59, 31), wrist_far=(57, 21),
                  knee_near=(54, 74), ankle_near=(54, 90), toe_near=(48, 90),
                  knee_far=(58, 74), ankle_far=(58, 90), toe_far=(52, 90),
                  stick_butt=(57, 26), stick_head=(74, 10),
                  ball=((70, 14)),),
        ),
    ),
    "lax_faceoff_clamp": Demo(
        caption='Down in your stance over the ball. Clamp, rip the ball back, come up to ready, reset. Fast, not many.',
        scenery='floor',
        frames=(
            _pose(head=(40, 50), neck=(46, 56), hip=(62, 64),
                  elbow_near=(44, 64), wrist_near=(36, 76),
                  elbow_far=(45, 65), wrist_far=(37, 77),
                  knee_near=(68, 74), ankle_near=(76, 90), toe_near=(82, 90),
                  knee_far=(60, 76), ankle_far=(52, 90), toe_far=(46, 90),
                  stick_butt=(38, 78), stick_head=(20, 84),
                  ball=((28, 86)),),
            _pose(head=(50, 22), neck=(51, 33), hip=(58, 58),
                  elbow_near=(56, 32), wrist_near=(54, 22),
                  elbow_far=(57, 33), wrist_far=(55, 23),
                  knee_near=(56, 74), ankle_near=(56, 90), toe_near=(50, 90),
                  knee_far=(60, 74), ankle_far=(60, 90), toe_far=(54, 90),
                  stick_butt=(55, 28), stick_head=(72, 12),
                  ball=((66, 18)),),
        ),
    ),
    "lax_goalie_saves": Demo(
        caption='In your stance. The app calls a spot and you drive both hands and your lead foot to it, then reset. No ball, no shooter.',
        scenery='floor',
        frames=(
            _pose(head=(50, 16), neck=(50, 27), hip=(51, 54),
                  elbow_near=(58, 36), wrist_near=(62, 28),
                  elbow_far=(42, 36), wrist_far=(38, 28),
                  knee_near=(46, 70), ankle_near=(44, 90), toe_near=(38, 90),
                  knee_far=(56, 70), ankle_far=(58, 90), toe_far=(64, 90),
                  stick_butt=(60, 30), stick_head=(64, 8)),
            _pose(head=(50, 16), neck=(50, 27), hip=(51, 54),
                  elbow_near=(60, 42), wrist_near=(66, 52),
                  elbow_far=(40, 42), wrist_far=(34, 52),
                  knee_near=(46, 70), ankle_near=(42, 90), toe_near=(36, 90),
                  knee_far=(56, 70), ankle_far=(60, 90), toe_far=(66, 90),
                  stick_butt=(64, 50), stick_head=(70, 28)),
        ),
    ),
    "bkb_dribble": Demo(
        caption='Bounce the ball at about waist height, pushing it down rather than patting it. Every bounce counts, either hand.',
        frames=(
            _pose(head=(52, 20), neck=(52, 31), hip=(53, 56),
                  elbow_near=(60, 44), wrist_near=(66, 56),
                  elbow_far=(47, 44), wrist_far=(46, 57),
                  knee_near=(51, 73), ankle_near=(51, 90), toe_near=(57, 90),
                  knee_far=(55, 73), ankle_far=(55, 90), toe_far=(61, 90),
                  ball=(67, 80)),
            _pose(head=(52, 20), neck=(52, 31), hip=(53, 56),
                  elbow_near=(60, 44), wrist_near=(66, 56),
                  elbow_far=(47, 44), wrist_far=(46, 57),
                  knee_near=(51, 73), ankle_near=(51, 90), toe_near=(57, 90),
                  knee_far=(55, 73), ankle_far=(55, 90), toe_far=(61, 90),
                  ball=(67, 64)),
        ),
    ),
    "bkb_pound_low": Demo(
        caption='Wide base, chest up, ball below your knee. Drive it into the floor as hard and as fast as you can keep it.',
        view="front",
        frames=(
            _pose(head=(50, 20), neck=(50, 31), hip=(50, 54),
                  elbow_near=(60, 44), wrist_near=(64, 60),
                  elbow_far=(40, 44), wrist_far=(36, 58),
                  knee_near=(36, 68), ankle_near=(30, 90), toe_near=(25, 90),
                  knee_far=(64, 68), ankle_far=(70, 90), toe_far=(75, 90),
                  ball=(66, 78)),
            _pose(head=(50, 20), neck=(50, 31), hip=(50, 54),
                  elbow_near=(60, 44), wrist_near=(64, 60),
                  elbow_far=(40, 44), wrist_far=(36, 58),
                  knee_near=(36, 68), ankle_near=(30, 90), toe_near=(25, 90),
                  knee_far=(64, 68), ankle_far=(70, 90), toe_far=(75, 90),
                  ball=(66, 66)),
        ),
    ),
    "bkb_pound_weak": Demo(
        caption='The same hard low pound, on your weaker hand only. The other hand stays off the ball entirely.',
        view="front",
        frames=(
            _pose(head=(50, 20), neck=(50, 31), hip=(50, 54),
                  elbow_near=(60, 44), wrist_near=(64, 60),
                  elbow_far=(36, 40), wrist_far=(26, 36),
                  knee_near=(36, 68), ankle_near=(30, 90), toe_near=(25, 90),
                  knee_far=(64, 68), ankle_far=(70, 90), toe_far=(75, 90),
                  ball=(66, 78)),
            _pose(head=(50, 20), neck=(50, 31), hip=(50, 54),
                  elbow_near=(60, 44), wrist_near=(64, 60),
                  elbow_far=(36, 40), wrist_far=(26, 36),
                  knee_near=(36, 68), ankle_near=(30, 90), toe_near=(25, 90),
                  knee_far=(64, 68), ankle_far=(70, 90), toe_far=(75, 90),
                  ball=(66, 66)),
        ),
    ),
    "bkb_crossover": Demo(
        caption='Stay low and push the ball hard from one hand to the other, in front of you and below your knees.',
        view="front",
        frames=(
            _pose(head=(50, 16), neck=(50, 27), hip=(50, 52),
                  elbow_near=(60, 44), wrist_near=(65, 62),
                  elbow_far=(40, 42), wrist_far=(37, 56),
                  knee_near=(42, 68), ankle_near=(38, 90), toe_near=(33, 90),
                  knee_far=(58, 68), ankle_far=(62, 90), toe_far=(67, 90),
                  ball=(66, 74)),
            _pose(head=(50, 16), neck=(50, 27), hip=(50, 52),
                  elbow_near=(40, 44), wrist_near=(35, 62),
                  elbow_far=(60, 42), wrist_far=(63, 56),
                  knee_near=(42, 68), ankle_near=(38, 90), toe_near=(33, 90),
                  knee_far=(58, 68), ankle_far=(62, 90), toe_far=(67, 90),
                  ball=(34, 74)),
        ),
    ),
    "bkb_between_legs": Demo(
        caption='The same change of hands, but the ball goes through your legs as your foot steps forward — not while you are standing still.',
        view="front",
        frames=(
            _pose(head=(50, 16), neck=(50, 27), hip=(50, 52),
                  elbow_near=(60, 40), wrist_near=(64, 60),
                  elbow_far=(40, 42), wrist_far=(44, 62),
                  knee_near=(40, 66), ankle_near=(34, 90), toe_near=(29, 90),
                  knee_far=(60, 66), ankle_far=(66, 90), toe_far=(71, 90),
                  ball=(66, 74)),
            _pose(head=(50, 16), neck=(50, 27), hip=(50, 52),
                  elbow_near=(58, 42), wrist_near=(54, 62),
                  elbow_far=(40, 42), wrist_far=(44, 62),
                  knee_near=(40, 66), ankle_near=(34, 90), toe_near=(29, 90),
                  knee_far=(60, 66), ankle_far=(66, 90), toe_far=(71, 90),
                  ball=(50, 78)),
        ),
    ),
    "bkb_wall_pass": Demo(
        caption='Two metres off a solid wall. Step into a two-hand chest pass and catch it clean coming back.',
        scenery='wall',
        frames=(
            _pose(head=(54, 22), neck=(52, 32), hip=(54, 56),
                  elbow_near=(44, 38), wrist_near=(42, 44),
                  elbow_far=(45, 39), wrist_far=(43, 45),
                  knee_near=(52, 72), ankle_near=(52, 90), toe_near=(46, 90),
                  knee_far=(56, 72), ankle_far=(56, 90), toe_far=(50, 90),
                  ball=(40, 42)),
            _pose(head=(52, 22), neck=(50, 32), hip=(54, 56),
                  elbow_near=(38, 34), wrist_near=(28, 32),
                  elbow_far=(39, 35), wrist_far=(29, 33),
                  knee_near=(50, 72), ankle_near=(51, 90), toe_near=(45, 90),
                  knee_far=(56, 72), ankle_far=(57, 90), toe_far=(51, 90),
                  ball=(16, 30)),
        ),
    ),
    "bkb_stance": Demo(
        caption='Feet wide, chest up, hands out, and your hips genuinely down. Hold it — standing up stops the clock.',
        view="front",
        mirror=False,
        seconds=4.0,
        frames=(
            _pose(head=(50, 22), neck=(50, 33), hip=(50, 56),
                  elbow_near=(36, 44), wrist_near=(28, 52),
                  elbow_far=(64, 44), wrist_far=(72, 52),
                  knee_near=(36, 68), ankle_near=(30, 90), toe_near=(25, 90),
                  knee_far=(64, 68), ankle_far=(70, 90), toe_far=(75, 90),),
        ),
    ),
    "bkb_slide": Demo(
        caption='From your stance, push off the back foot and step out with the front, then slide the back foot in. One push is one rep.',
        view="front",
        frames=(
            _pose(head=(44, 22), neck=(44, 33), hip=(45, 56),
                  elbow_near=(32, 44), wrist_near=(25, 50),
                  elbow_far=(58, 44), wrist_far=(65, 50),
                  knee_near=(33, 68), ankle_near=(28, 90), toe_near=(23, 90),
                  knee_far=(58, 68), ankle_far=(64, 90), toe_far=(69, 90),),
            _pose(head=(56, 22), neck=(56, 33), hip=(55, 56),
                  elbow_near=(68, 44), wrist_near=(75, 50),
                  elbow_far=(42, 44), wrist_far=(35, 50),
                  knee_near=(67, 68), ankle_near=(72, 90), toe_near=(77, 90),
                  knee_far=(42, 68), ankle_far=(36, 90), toe_far=(31, 90),),
        ),
    ),
    "bkb_form_shot": Demo(
        caption='One hand under the ball, elbow in. Dip, rise, release, and hold the follow-through until the ball lands.',
        view="front",
        frames=(
            _pose(head=(44, 18), neck=(45, 29), hip=(47, 54),
                  elbow_near=(58, 45), wrist_near=(58, 33),
                  elbow_far=(37, 43), wrist_far=(48, 32),
                  knee_near=(45, 70), ankle_near=(43, 90), toe_near=(38, 90),
                  knee_far=(51, 70), ankle_far=(53, 90), toe_far=(58, 90),
                  ball=(59, 25)),
            _pose(head=(44, 18), neck=(45, 29), hip=(47, 54),
                  elbow_near=(59, 31), wrist_near=(61, 18),
                  elbow_far=(37, 45), wrist_far=(44, 39),
                  knee_near=(45, 70), ankle_near=(43, 90), toe_near=(38, 90),
                  knee_far=(51, 70), ankle_far=(53, 90), toe_far=(58, 90),
                  ball=(63, 7)),
                ),
    ),
    "soc_juggle": Demo(
        caption='Keep the ball up off your laces, either foot. Every touch counts.',
        frames=(
            _pose(head=(50, 16), neck=(50, 27), hip=(50, 53),
                  elbow_near=(58, 40), wrist_near=(64, 46),
                  elbow_far=(42, 40), wrist_far=(36, 46),
                  knee_near=(58, 66), ankle_near=(64, 74), toe_near=(70, 76),
                  knee_far=(50, 71), ankle_far=(50, 90), toe_far=(56, 90),
                  ball=(70, 66)),
            _pose(head=(50, 16), neck=(50, 27), hip=(50, 53),
                  elbow_near=(58, 40), wrist_near=(64, 46),
                  elbow_far=(42, 40), wrist_far=(36, 46),
                  knee_near=(54, 70), ankle_near=(57, 84), toe_near=(63, 86),
                  knee_far=(50, 71), ankle_far=(50, 90), toe_far=(56, 90),
                  ball=(68, 40)),
        ),
    ),
    "soc_juggle_weak": Demo(
        caption='The same juggling on your weaker foot only. Same picture — the foot is the drill.',
        frames=(
            _pose(head=(50, 16), neck=(50, 27), hip=(50, 53),
                  elbow_near=(58, 40), wrist_near=(64, 46),
                  elbow_far=(42, 40), wrist_far=(36, 46),
                  knee_near=(58, 66), ankle_near=(64, 74), toe_near=(70, 76),
                  knee_far=(50, 71), ankle_far=(50, 90), toe_far=(56, 90),
                  ball=(70, 66)),
            _pose(head=(50, 16), neck=(50, 27), hip=(50, 53),
                  elbow_near=(58, 40), wrist_near=(64, 46),
                  elbow_far=(42, 40), wrist_far=(36, 46),
                  knee_near=(54, 70), ankle_near=(57, 84), toe_near=(63, 86),
                  knee_far=(50, 71), ankle_far=(50, 90), toe_far=(56, 90),
                  ball=(68, 40)),
        ),
    ),
    "soc_juggle_alt": Demo(
        caption='Left, right, left, right, without letting it drop. It has to change feet every touch.',
        frames=(
            _pose(head=(50, 16), neck=(50, 27), hip=(50, 53),
                  elbow_near=(58, 40), wrist_near=(64, 46),
                  elbow_far=(42, 40), wrist_far=(36, 46),
                  knee_near=(58, 66), ankle_near=(64, 74), toe_near=(70, 76),
                  knee_far=(50, 71), ankle_far=(50, 90), toe_far=(56, 90),
                  ball=(70, 66)),
            _pose(head=(50, 16), neck=(50, 27), hip=(50, 53),
                  elbow_near=(58, 40), wrist_near=(64, 46),
                  elbow_far=(42, 40), wrist_far=(36, 46),
                  knee_near=(50, 71), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(58, 66), ankle_far=(64, 74), toe_far=(70, 76),
                  ball=(70, 66)),
        ),
    ),
    "soc_thigh": Demo(
        caption='Off the thigh, not the laces. Knee up to about waist height and pop it straight back up.',
        frames=(
            _pose(head=(50, 16), neck=(50, 27), hip=(50, 53),
                  elbow_near=(58, 38), wrist_near=(64, 44),
                  elbow_far=(42, 38), wrist_far=(36, 44),
                  knee_near=(62, 56), ankle_near=(64, 74), toe_near=(70, 76),
                  knee_far=(50, 71), ankle_far=(50, 90), toe_far=(56, 90),
                  ball=(62, 48)),
            _pose(head=(50, 16), neck=(50, 27), hip=(50, 53),
                  elbow_near=(58, 38), wrist_near=(64, 44),
                  elbow_far=(42, 38), wrist_far=(36, 44),
                  knee_near=(58, 62), ankle_near=(61, 78), toe_near=(67, 80),
                  knee_far=(50, 71), ankle_far=(50, 90), toe_far=(56, 90),
                  ball=(62, 24)),
        ),
    ),
    "soc_wall_pass": Demo(
        caption='Pass firmly into the wall and control what comes back. Strike it — a soft pass does not count.',
        scenery="wall",
        frames=(
            _pose(head=(54, 18), neck=(53, 29), hip=(54, 55),
                  elbow_near=(60, 40), wrist_near=(64, 50),
                  elbow_far=(46, 40), wrist_far=(42, 50),
                  knee_near=(60, 70), ankle_near=(66, 84), toe_near=(72, 86),
                  knee_far=(52, 72), ankle_far=(52, 90), toe_far=(58, 90),
                  ball=(38, 86)),
            _pose(head=(52, 18), neck=(51, 29), hip=(53, 55),
                  elbow_near=(58, 40), wrist_near=(62, 50),
                  elbow_far=(44, 40), wrist_far=(40, 50),
                  knee_near=(50, 72), ankle_near=(46, 82), toe_near=(40, 84),
                  knee_far=(56, 72), ankle_far=(58, 90), toe_far=(64, 90),
                  ball=(16, 86)),
        ),
    ),
    "soc_toe_taps": Demo(
        caption='Ball still on the ground. Tap the top of it foot to foot, as fast as you can keep it together.',
        view="front",
        frames=(
            _pose(head=(50, 16), neck=(50, 27), hip=(50, 52),
                  elbow_near=(60, 42), wrist_near=(64, 52),
                  elbow_far=(40, 42), wrist_far=(36, 52),
                  knee_near=(44, 66), ankle_near=(46, 78), toe_near=(50, 82),
                  knee_far=(60, 68), ankle_far=(62, 90), toe_far=(67, 90),
                  ball=(50, 84)),
            _pose(head=(50, 16), neck=(50, 27), hip=(50, 52),
                  elbow_near=(60, 42), wrist_near=(64, 52),
                  elbow_far=(40, 42), wrist_far=(36, 52),
                  knee_near=(40, 68), ankle_near=(38, 90), toe_near=(33, 90),
                  knee_far=(56, 66), ankle_far=(54, 78), toe_far=(50, 82),
                  ball=(50, 84)),
        ),
    ),
    "soc_shuffle": Demo(
        caption='Side-on defending stance. Shuffle across without ever crossing your feet — one push is one rep.',
        view="front",
        frames=(
            _pose(head=(44, 20), neck=(44, 31), hip=(45, 55),
                  elbow_near=(32, 42), wrist_near=(25, 48),
                  elbow_far=(58, 42), wrist_far=(65, 48),
                  knee_near=(33, 68), ankle_near=(28, 90), toe_near=(23, 90),
                  knee_far=(58, 68), ankle_far=(64, 90), toe_far=(69, 90)),
            _pose(head=(56, 20), neck=(56, 31), hip=(55, 55),
                  elbow_near=(68, 42), wrist_near=(75, 48),
                  elbow_far=(42, 42), wrist_far=(35, 48),
                  knee_near=(67, 68), ankle_near=(72, 90), toe_near=(77, 90),
                  knee_far=(42, 68), ankle_far=(36, 90), toe_far=(31, 90)),
        ),
    ),
    "ten_wall_rally": Demo(
        caption='Rally against a wall. Turn your shoulders, take the racket back, and hit through it.',
        scenery="wall",
        frames=(
            _pose(head=(56, 18), neck=(54, 29), hip=(54, 55),
                  elbow_near=(62, 36), wrist_near=(68, 42),
                  elbow_far=(50, 36), wrist_far=(46, 44),
                  knee_near=(52, 72), ankle_near=(52, 90), toe_near=(58, 90),
                  knee_far=(56, 72), ankle_far=(56, 90), toe_far=(62, 90),
                  stick_butt=(70, 44), stick_head=(86, 32),
                  ball=(32, 58)),
            _pose(head=(52, 18), neck=(51, 29), hip=(53, 55),
                  elbow_near=(46, 34), wrist_near=(38, 38),
                  elbow_far=(48, 36), wrist_far=(42, 44),
                  knee_near=(50, 72), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(54, 72), ankle_far=(54, 90), toe_far=(60, 90),
                  stick_butt=(36, 40), stick_head=(20, 28),
                  ball=(12, 40)),
        ),
    ),
    "ten_alternate": Demo(
        caption='Change wing every shot — forehand, backhand, forehand. The ball has to leave from the other side each time.',
        scenery="wall",
        frames=(
            _pose(head=(56, 18), neck=(54, 29), hip=(54, 55),
                  elbow_near=(62, 36), wrist_near=(68, 42),
                  elbow_far=(50, 36), wrist_far=(46, 44),
                  knee_near=(52, 72), ankle_near=(52, 90), toe_near=(58, 90),
                  knee_far=(56, 72), ankle_far=(56, 90), toe_far=(62, 90),
                  stick_butt=(70, 44), stick_head=(86, 32)),
            _pose(head=(52, 18), neck=(53, 29), hip=(54, 55),
                  elbow_near=(44, 34), wrist_near=(36, 30),
                  elbow_far=(46, 36), wrist_far=(40, 34),
                  knee_near=(52, 72), ankle_near=(52, 90), toe_near=(58, 90),
                  knee_far=(56, 72), ankle_far=(56, 90), toe_far=(62, 90),
                  stick_butt=(34, 30), stick_head=(18, 20)),
        ),
    ),
    "ten_one_wing": Demo(
        caption='Every ball on the same wing, recovering back to the middle between shots. Hit, recover, hit.',
        scenery="wall",
        frames=(
            _pose(head=(56, 18), neck=(54, 29), hip=(54, 55),
                  elbow_near=(62, 36), wrist_near=(68, 42),
                  elbow_far=(50, 36), wrist_far=(46, 44),
                  knee_near=(52, 72), ankle_near=(52, 90), toe_near=(58, 90),
                  knee_far=(56, 72), ankle_far=(56, 90), toe_far=(62, 90),
                  stick_butt=(70, 44), stick_head=(86, 32)),
            _pose(head=(52, 18), neck=(51, 29), hip=(52, 55),
                  elbow_near=(58, 38), wrist_near=(52, 42),
                  elbow_far=(48, 38), wrist_far=(46, 44),
                  knee_near=(48, 72), ankle_near=(46, 90), toe_near=(52, 90),
                  knee_far=(56, 72), ankle_far=(58, 90), toe_far=(64, 90),
                  stick_butt=(50, 42), stick_head=(34, 32)),
        ),
    ),
    "ten_volley": Demo(
        caption='Close to the wall, no bounce. Short punchy blocks with the racket out in front — no backswing.',
        scenery="wall",
        frames=(
            _pose(head=(54, 18), neck=(53, 29), hip=(54, 55),
                  elbow_near=(50, 36), wrist_near=(46, 42),
                  elbow_far=(51, 37), wrist_far=(47, 43),
                  knee_near=(52, 72), ankle_near=(52, 90), toe_near=(58, 90),
                  knee_far=(56, 72), ankle_far=(56, 90), toe_far=(62, 90),
                  stick_butt=(44, 42), stick_head=(30, 32),
                  ball=(22, 38)),
            _pose(head=(52, 18), neck=(51, 29), hip=(53, 55),
                  elbow_near=(46, 34), wrist_near=(40, 38),
                  elbow_far=(47, 35), wrist_far=(41, 39),
                  knee_near=(50, 72), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(54, 72), ankle_far=(54, 90), toe_far=(60, 90),
                  stick_butt=(38, 38), stick_head=(24, 28),
                  ball=(12, 32)),
        ),
    ),
    "ten_serve": Demo(
        caption='Toss up and serve into a fence or a wall. It watches your hitting arm, so a full motion counts even without a ball.',
        scenery="wall",
        frames=(
            _pose(head=(54, 20), neck=(53, 31), hip=(54, 56),
                  elbow_near=(62, 32), wrist_near=(68, 40),
                  elbow_far=(46, 26), wrist_far=(44, 14),
                  knee_near=(52, 72), ankle_near=(52, 90), toe_near=(58, 90),
                  knee_far=(56, 72), ankle_far=(56, 90), toe_far=(62, 90),
                  stick_butt=(70, 42), stick_head=(84, 54),
                  ball=(44, 8)),
            _pose(head=(52, 20), neck=(52, 31), hip=(54, 56),
                  elbow_near=(56, 20), wrist_near=(58, 9),
                  elbow_far=(44, 38), wrist_far=(40, 48),
                  knee_near=(50, 72), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(56, 72), ankle_far=(56, 90), toe_far=(62, 90),
                  stick_butt=(59, 8), stick_head=(70, 2),
                  ball=(30, 14)),
        ),
    ),
    "ten_split_step": Demo(
        caption='The small hop you land from as your opponent hits. Land wide and balanced, then push off.',
        view="front",
        frames=(
            _pose(head=(50, 14), neck=(50, 25), hip=(50, 50),
                  elbow_near=(38, 38), wrist_near=(32, 44),
                  elbow_far=(62, 38), wrist_far=(68, 44),
                  knee_near=(48, 64), ankle_near=(47, 78), toe_near=(42, 80),
                  knee_far=(52, 64), ankle_far=(53, 78), toe_far=(58, 80)),
            _pose(head=(50, 20), neck=(50, 31), hip=(50, 54),
                  elbow_near=(36, 42), wrist_near=(30, 50),
                  elbow_far=(64, 42), wrist_far=(70, 50),
                  knee_near=(40, 68), ankle_near=(34, 90), toe_near=(29, 90),
                  knee_far=(60, 68), ankle_far=(66, 90), toe_far=(71, 90)),
        ),
    ),
    "ten_recovery": Demo(
        caption='Side to side along the baseline without crossing your feet. One push is one rep.',
        view="front",
        frames=(
            _pose(head=(44, 20), neck=(44, 31), hip=(45, 55),
                  elbow_near=(32, 42), wrist_near=(25, 48),
                  elbow_far=(58, 42), wrist_far=(65, 48),
                  knee_near=(33, 68), ankle_near=(28, 90), toe_near=(23, 90),
                  knee_far=(58, 68), ankle_far=(64, 90), toe_far=(69, 90)),
            _pose(head=(56, 20), neck=(56, 31), hip=(55, 55),
                  elbow_near=(68, 42), wrist_near=(75, 48),
                  elbow_far=(42, 42), wrist_far=(35, 48),
                  knee_near=(67, 68), ankle_near=(72, 90), toe_near=(77, 90),
                  knee_far=(42, 68), ankle_far=(36, 90), toe_far=(31, 90)),
        ),
    ),
    "vb_set": Demo(
        caption='Hands above your forehead, elbows out. Push it straight up and catch nothing — every clean contact counts.',
        view="front",
        frames=(
            _pose(head=(50, 22), neck=(50, 33), hip=(50, 57),
                  elbow_near=(58, 28), wrist_near=(54, 18),
                  elbow_far=(42, 28), wrist_far=(46, 18),
                  knee_near=(48, 73), ankle_near=(47, 90), toe_near=(41, 90),
                  knee_far=(54, 73), ankle_far=(55, 90), toe_far=(61, 90),
                  ball=(50, 10)),
            _pose(head=(50, 22), neck=(50, 33), hip=(50, 57),
                  elbow_near=(56, 22), wrist_near=(53, 11),
                  elbow_far=(44, 22), wrist_far=(47, 11),
                  knee_near=(48, 73), ankle_near=(47, 90), toe_near=(41, 90),
                  knee_far=(54, 73), ankle_far=(55, 90), toe_far=(61, 90),
                  ball=(50, 2)),
        ),
    ),
    "vb_pass": Demo(
        caption='Arms straight and together to make a platform, hands below your shoulders. Bump it straight up off your forearms.',
        frames=(
            _pose(head=(52, 20), neck=(51, 31), hip=(52, 55),
                  elbow_near=(44, 42), wrist_near=(36, 52),
                  elbow_far=(45, 43), wrist_far=(37, 53),
                  knee_near=(50, 72), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(54, 72), ankle_far=(54, 90), toe_far=(60, 90),
                  ball=(33, 46)),
            _pose(head=(52, 20), neck=(51, 31), hip=(52, 55),
                  elbow_near=(45, 40), wrist_near=(37, 49),
                  elbow_far=(46, 41), wrist_far=(38, 50),
                  knee_near=(50, 72), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(54, 72), ankle_far=(54, 90), toe_far=(60, 90),
                  ball=(33, 14)),
        ),
    ),
    "vb_set_wall": Demo(
        caption='The same set, into a wall from close range. Quicker than setting to yourself, which is the whole point.',
        scenery="wall",
        frames=(
            _pose(head=(52, 22), neck=(51, 33), hip=(52, 57),
                  elbow_near=(46, 28), wrist_near=(42, 18),
                  elbow_far=(47, 29), wrist_far=(43, 19),
                  knee_near=(50, 73), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(54, 73), ankle_far=(54, 90), toe_far=(60, 90),
                  ball=(38, 14)),
            _pose(head=(52, 22), neck=(51, 33), hip=(52, 57),
                  elbow_near=(44, 26), wrist_near=(38, 20),
                  elbow_far=(45, 27), wrist_far=(39, 21),
                  knee_near=(50, 73), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(54, 73), ankle_far=(54, 90), toe_far=(60, 90),
                  ball=(16, 20)),
        ),
    ),
    "vb_serve": Demo(
        caption='Toss with one hand and strike with the other. It reads which hand hit it, so a serve is tellable from a set.',
        scenery="wall",
        frames=(
            _pose(head=(54, 20), neck=(53, 31), hip=(54, 56),
                  elbow_near=(62, 30), wrist_near=(68, 24),
                  elbow_far=(46, 26), wrist_far=(44, 14),
                  knee_near=(52, 72), ankle_near=(52, 90), toe_near=(58, 90),
                  knee_far=(56, 72), ankle_far=(56, 90), toe_far=(62, 90),
                  ball=(44, 8)),
            _pose(head=(52, 20), neck=(52, 31), hip=(54, 56),
                  elbow_near=(50, 22), wrist_near=(42, 18),
                  elbow_far=(45, 36), wrist_far=(41, 46),
                  knee_near=(50, 72), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(56, 72), ankle_far=(56, 90), toe_far=(62, 90),
                  ball=(20, 26)),
        ),
    ),
    "vb_arm_swing": Demo(
        caption='The hitting swing on its own, no ball. Draw the elbow back and high, then swing through and finish across your body.',
        frames=(
            _pose(head=(54, 20), neck=(53, 31), hip=(54, 56),
                  elbow_near=(64, 26), wrist_near=(70, 36),
                  elbow_far=(46, 34), wrist_far=(40, 44),
                  knee_near=(52, 72), ankle_near=(52, 90), toe_near=(58, 90),
                  knee_far=(56, 72), ankle_far=(56, 90), toe_far=(62, 90)),
            _pose(head=(52, 20), neck=(52, 31), hip=(54, 56),
                  elbow_near=(48, 20), wrist_near=(40, 34),
                  elbow_far=(46, 36), wrist_far=(42, 46),
                  knee_near=(50, 72), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(56, 72), ankle_far=(56, 90), toe_far=(62, 90)),
        ),
    ),
    "vb_approach": Demo(
        caption='The full approach and jump. Swing both arms back on the last step, then drive them up and go.',
        frames=(
            _pose(head=(48, 32), neck=(48, 42), hip=(54, 64),
                  elbow_near=(58, 54), wrist_near=(64, 62),
                  elbow_far=(59, 55), wrist_far=(65, 63),
                  knee_near=(44, 74), ankle_near=(48, 90), toe_near=(54, 90),
                  knee_far=(62, 74), ankle_far=(68, 90), toe_far=(74, 90)),
            _pose(head=(50, 6), neck=(50, 17), hip=(50, 45),
                  elbow_near=(46, 30), wrist_near=(44, 15),
                  elbow_far=(54, 30), wrist_far=(56, 15),
                  knee_near=(49, 63), ankle_near=(49, 79), toe_near=(54, 83),
                  knee_far=(53, 63), ankle_far=(53, 79), toe_far=(58, 83)),
        ),
    ),
    "vb_block_jump": Demo(
        caption='From a blocking stance, hands already up. Jump straight, press over the net, and land where you took off.',
        view="front",
        frames=(
            _pose(head=(50, 20), neck=(50, 31), hip=(50, 55),
                  elbow_near=(40, 34), wrist_near=(38, 22),
                  elbow_far=(60, 34), wrist_far=(62, 22),
                  knee_near=(44, 70), ankle_near=(40, 90), toe_near=(35, 90),
                  knee_far=(56, 70), ankle_far=(60, 90), toe_far=(65, 90)),
            _pose(head=(50, 8), neck=(50, 19), hip=(50, 45),
                  elbow_near=(42, 26), wrist_near=(43, 12),
                  elbow_far=(58, 26), wrist_far=(57, 12),
                  knee_near=(48, 62), ankle_near=(47, 78), toe_near=(42, 82),
                  knee_far=(52, 62), ankle_far=(53, 78), toe_far=(58, 82)),
        ),
    ),
    "bb_wall_throw": Demo(
        caption='Throw into a wall and field what comes back. Every catch counts, so keep it going.',
        scenery="wall",
        frames=(
            _pose(head=(54, 20), neck=(53, 31), hip=(54, 56),
                  elbow_near=(62, 28), wrist_near=(66, 20),
                  elbow_far=(46, 36), wrist_far=(42, 44),
                  knee_near=(52, 72), ankle_near=(52, 90), toe_near=(58, 90),
                  knee_far=(56, 72), ankle_far=(56, 90), toe_far=(62, 90),
                  ball=(68, 16)),
            _pose(head=(52, 20), neck=(51, 31), hip=(53, 56),
                  elbow_near=(48, 24), wrist_near=(38, 22),
                  elbow_far=(46, 38), wrist_far=(42, 48),
                  knee_near=(48, 72), ankle_near=(44, 90), toe_near=(38, 90),
                  knee_far=(56, 72), ankle_far=(60, 90), toe_far=(66, 90),
                  ball=(18, 26)),
        ),
    ),
    "bb_long_toss": Demo(
        caption='Back up and throw it properly — crow hop into it and use the whole arm. Fewer throws, harder ones.',
        scenery="wall",
        frames=(
            _pose(head=(56, 22), neck=(54, 33), hip=(56, 58),
                  elbow_near=(66, 30), wrist_near=(72, 22),
                  elbow_far=(46, 38), wrist_far=(40, 46),
                  knee_near=(62, 72), ankle_near=(68, 86), toe_near=(74, 88),
                  knee_far=(52, 74), ankle_far=(50, 90), toe_far=(56, 90),
                  ball=(74, 18)),
            _pose(head=(50, 20), neck=(49, 31), hip=(52, 56),
                  elbow_near=(44, 22), wrist_near=(32, 18),
                  elbow_far=(46, 40), wrist_far=(42, 50),
                  knee_near=(44, 72), ankle_near=(36, 90), toe_near=(30, 90),
                  knee_far=(58, 74), ankle_far=(64, 90), toe_far=(70, 90),
                  ball=(12, 12)),
        ),
    ),
    "bb_quick_hands": Demo(
        caption='Short, quick transfers from close range — glove to hand to release, with no wind-up at all.',
        scenery="wall",
        frames=(
            _pose(head=(53, 20), neck=(52, 31), hip=(53, 56),
                  elbow_near=(58, 32), wrist_near=(58, 22),
                  elbow_far=(48, 34), wrist_far=(46, 26),
                  knee_near=(51, 72), ankle_near=(51, 90), toe_near=(57, 90),
                  knee_far=(55, 72), ankle_far=(55, 90), toe_far=(61, 90),
                  ball=(58, 18)),
            _pose(head=(52, 20), neck=(51, 31), hip=(53, 56),
                  elbow_near=(48, 28), wrist_near=(40, 24),
                  elbow_far=(48, 34), wrist_far=(44, 28),
                  knee_near=(51, 72), ankle_near=(51, 90), toe_near=(57, 90),
                  knee_far=(55, 72), ankle_far=(55, 90), toe_far=(61, 90),
                  ball=(22, 26)),
        ),
    ),
    "bb_tee_swing": Demo(
        caption='Off a tee, the same swing every time. Hands travel out away from your body and back through the ball.',
        frames=(
            _pose(head=(54, 20), neck=(53, 31), hip=(55, 56),
                  elbow_near=(62, 36), wrist_near=(64, 26),
                  elbow_far=(60, 37), wrist_far=(62, 27),
                  knee_near=(50, 72), ankle_near=(48, 90), toe_near=(42, 90),
                  knee_far=(60, 72), ankle_far=(64, 90), toe_far=(70, 90),
                  stick_butt=(64, 24), stick_head=(80, 10),
                  ball=(38, 62)),
            _pose(head=(50, 20), neck=(50, 31), hip=(52, 56),
                  elbow_near=(44, 34), wrist_near=(36, 30),
                  elbow_far=(45, 35), wrist_far=(37, 31),
                  knee_near=(46, 72), ankle_near=(42, 90), toe_near=(36, 90),
                  knee_far=(58, 72), ankle_far=(64, 90), toe_far=(70, 90),
                  stick_butt=(34, 30), stick_head=(18, 22),
                  ball=(24, 50)),
        ),
    ),
    "bb_fielding": Demo(
        caption='Down into fielding position and back up, over and over. No ball needed — this is the footwork.',
        frames=(
            _pose(head=(46, 44), neck=(50, 52), hip=(60, 64),
                  elbow_near=(48, 60), wrist_near=(42, 74),
                  elbow_far=(49, 61), wrist_far=(43, 75),
                  knee_near=(68, 74), ankle_near=(76, 90), toe_near=(82, 90),
                  knee_far=(56, 76), ankle_far=(48, 90), toe_far=(42, 90)),
            _pose(head=(52, 18), neck=(52, 29), hip=(54, 56),
                  elbow_near=(58, 40), wrist_near=(60, 52),
                  elbow_far=(48, 40), wrist_far=(46, 52),
                  knee_near=(52, 72), ankle_near=(52, 90), toe_near=(58, 90),
                  knee_far=(56, 72), ankle_far=(56, 90), toe_far=(62, 90)),
        ),
    ),
    "bb_catcher_stance": Demo(
        caption='Down in the crouch with your hips low and your chest up. Hold it — standing up stops the clock.',
        mirror=False,
        seconds=4.0,
        view="front",
        frames=(
            _pose(head=(50, 38), neck=(50, 48), hip=(50, 66),
                  elbow_near=(36, 56), wrist_near=(32, 46),
                  elbow_far=(64, 56), wrist_far=(68, 52),
                  knee_near=(32, 66), ankle_near=(36, 86), toe_near=(30, 90),
                  knee_far=(68, 66), ankle_far=(64, 86), toe_far=(70, 90)),
        ),
    ),
    "hoc_stickhandle": Demo(
        caption='Puck or ball side to side in front of you, quick and clean. One trip across your body is one rep.',
        view="front",
        frames=(
            _pose(head=(50, 18), neck=(50, 29), hip=(50, 54),
                  elbow_near=(58, 40), wrist_near=(62, 52),
                  elbow_far=(42, 40), wrist_far=(46, 50),
                  knee_near=(44, 70), ankle_near=(40, 90), toe_near=(35, 90),
                  knee_far=(56, 70), ankle_far=(60, 90), toe_far=(65, 90),
                  stick_butt=(62, 54), stick_head=(72, 74),
                  ball=(72, 78)),
            _pose(head=(50, 18), neck=(50, 29), hip=(50, 54),
                  elbow_near=(42, 40), wrist_near=(38, 52),
                  elbow_far=(58, 40), wrist_far=(54, 50),
                  knee_near=(44, 70), ankle_near=(40, 90), toe_near=(35, 90),
                  knee_far=(56, 70), ankle_far=(60, 90), toe_far=(65, 90),
                  stick_butt=(38, 54), stick_head=(28, 74),
                  ball=(28, 78)),
        ),
    ),
    "hoc_wide_handles": Demo(
        caption='The same handle pushed right out to each side — full extension one way, full extension the other.',
        view="front",
        frames=(
            _pose(head=(50, 18), neck=(50, 29), hip=(50, 54),
                  elbow_near=(62, 38), wrist_near=(72, 48),
                  elbow_far=(40, 40), wrist_far=(44, 50),
                  knee_near=(44, 70), ankle_near=(40, 90), toe_near=(35, 90),
                  knee_far=(56, 70), ankle_far=(60, 90), toe_far=(65, 90),
                  stick_butt=(74, 50), stick_head=(88, 72),
                  ball=(88, 78)),
            _pose(head=(50, 18), neck=(50, 29), hip=(50, 54),
                  elbow_near=(38, 38), wrist_near=(28, 48),
                  elbow_far=(60, 40), wrist_far=(56, 50),
                  knee_near=(44, 70), ankle_near=(40, 90), toe_near=(35, 90),
                  knee_far=(56, 70), ankle_far=(60, 90), toe_far=(65, 90),
                  stick_butt=(26, 50), stick_head=(12, 72),
                  ball=(12, 78)),
        ),
    ),
    "hoc_shot": Demo(
        caption='Sweep the puck from behind your back foot right through to the front, and follow through where you want it to go.',
        frames=(
            _pose(head=(56, 22), neck=(54, 33), hip=(56, 58),
                  elbow_near=(64, 42), wrist_near=(70, 54),
                  elbow_far=(60, 44), wrist_far=(66, 56),
                  knee_near=(60, 74), ankle_near=(66, 88), toe_near=(72, 90),
                  knee_far=(52, 74), ankle_far=(52, 90), toe_far=(58, 90),
                  stick_butt=(72, 56), stick_head=(86, 78),
                  ball=(84, 84)),
            _pose(head=(50, 22), neck=(49, 33), hip=(52, 58),
                  elbow_near=(42, 40), wrist_near=(34, 48),
                  elbow_far=(44, 42), wrist_far=(36, 50),
                  knee_near=(44, 74), ankle_near=(38, 90), toe_near=(32, 90),
                  knee_far=(58, 74), ankle_far=(64, 90), toe_far=(70, 90),
                  stick_butt=(32, 50), stick_head=(16, 70),
                  ball=(14, 76)),
        ),
    ),
    "hoc_butterfly": Demo(
        caption='Drop into the butterfly and get back up to your skates again. It measures how far your hips actually travel.',
        view="front",
        frames=(
            _pose(head=(50, 18), neck=(50, 29), hip=(50, 54),
                  elbow_near=(38, 42), wrist_near=(30, 50),
                  elbow_far=(62, 42), wrist_far=(70, 50),
                  knee_near=(40, 70), ankle_near=(34, 90), toe_near=(29, 90),
                  knee_far=(60, 70), ankle_far=(66, 90), toe_far=(71, 90)),
            _pose(head=(50, 38), neck=(50, 49), hip=(50, 68),
                  elbow_near=(38, 58), wrist_near=(30, 64),
                  elbow_far=(62, 58), wrist_far=(70, 64),
                  knee_near=(32, 80), ankle_near=(20, 88), toe_near=(15, 90),
                  knee_far=(68, 80), ankle_far=(80, 88), toe_far=(85, 90)),
        ),
    ),
    "hoc_shuffle": Demo(
        caption='Slide across the top of the zone without ever turning your hips. One push is one rep.',
        view="front",
        frames=(
            _pose(head=(44, 20), neck=(44, 31), hip=(45, 55),
                  elbow_near=(32, 42), wrist_near=(25, 48),
                  elbow_far=(58, 42), wrist_far=(65, 48),
                  knee_near=(33, 68), ankle_near=(28, 90), toe_near=(23, 90),
                  knee_far=(58, 68), ankle_far=(64, 90), toe_far=(69, 90)),
            _pose(head=(56, 20), neck=(56, 31), hip=(55, 55),
                  elbow_near=(68, 42), wrist_near=(75, 48),
                  elbow_far=(42, 42), wrist_far=(35, 48),
                  knee_near=(67, 68), ankle_near=(72, 90), toe_near=(77, 90),
                  knee_far=(42, 68), ankle_far=(36, 90), toe_far=(31, 90)),
        ),
    ),
    "hoc_stance": Demo(
        caption='Knees bent, chest up, weight on the balls of your feet. Hold it — standing up stops the clock.',
        frames=(
            _pose(head=(46, 26), neck=(48, 36), hip=(56, 58),
                  elbow_near=(42, 46), wrist_near=(34, 52),
                  elbow_far=(43, 47), wrist_far=(35, 53),
                  knee_near=(46, 70), ankle_near=(46, 88), toe_near=(52, 90),
                  knee_far=(64, 70), ankle_far=(66, 88), toe_far=(72, 90),
                  stick_butt=(32, 54), stick_head=(14, 74)),
        ),
    ),
    "fb_wall_throw": Demo(
        caption='Ordinary throws into a wall or net at the distance you actually play at. Full motion, every time.',
        scenery="wall",
        frames=(
            _pose(head=(56, 20), neck=(54, 31), hip=(56, 56),
                  elbow_near=(66, 28), wrist_near=(72, 20),
                  elbow_far=(46, 36), wrist_far=(40, 44),
                  knee_near=(60, 72), ankle_near=(66, 88), toe_near=(72, 90),
                  knee_far=(52, 74), ankle_far=(52, 90), toe_far=(58, 90),
                  ball=(74, 16)),
            _pose(head=(50, 20), neck=(49, 31), hip=(52, 56),
                  elbow_near=(44, 22), wrist_near=(32, 18),
                  elbow_far=(46, 38), wrist_far=(42, 48),
                  knee_near=(44, 72), ankle_near=(36, 90), toe_near=(30, 90),
                  knee_far=(58, 74), ankle_far=(64, 90), toe_far=(70, 90),
                  ball=(14, 14)),
        ),
    ),
    "fb_quick_release": Demo(
        caption='Short, fast throws with a compact arm action — the ball is gone before your front foot lands.',
        scenery="wall",
        frames=(
            _pose(head=(53, 20), neck=(52, 31), hip=(53, 56),
                  elbow_near=(58, 30), wrist_near=(58, 20),
                  elbow_far=(48, 34), wrist_far=(46, 26),
                  knee_near=(51, 72), ankle_near=(51, 90), toe_near=(57, 90),
                  knee_far=(55, 72), ankle_far=(55, 90), toe_far=(61, 90),
                  ball=(58, 16)),
            _pose(head=(52, 20), neck=(51, 31), hip=(53, 56),
                  elbow_near=(48, 26), wrist_near=(40, 22),
                  elbow_far=(48, 34), wrist_far=(44, 28),
                  knee_near=(51, 72), ankle_near=(51, 90), toe_near=(57, 90),
                  knee_far=(55, 72), ankle_far=(55, 90), toe_far=(61, 90),
                  ball=(24, 24)),
        ),
    ),
    "fb_deep_ball": Demo(
        caption='Fewer throws, all of them hard. Full drop, full turn, everything into it — these cost the arm more.',
        scenery="wall",
        frames=(
            _pose(head=(58, 22), neck=(56, 33), hip=(58, 58),
                  elbow_near=(68, 30), wrist_near=(76, 20),
                  elbow_far=(46, 38), wrist_far=(38, 46),
                  knee_near=(64, 72), ankle_near=(72, 88), toe_near=(78, 90),
                  knee_far=(52, 74), ankle_far=(50, 90), toe_far=(56, 90),
                  ball=(78, 14)),
            _pose(head=(48, 20), neck=(47, 31), hip=(50, 56),
                  elbow_near=(40, 20), wrist_near=(26, 14),
                  elbow_far=(44, 38), wrist_far=(40, 50),
                  knee_near=(40, 72), ankle_near=(30, 90), toe_near=(24, 90),
                  knee_far=(58, 74), ankle_far=(66, 90), toe_far=(72, 90),
                  ball=(8, 8)),
        ),
    ),
    "fb_kick": Demo(
        caption='The full leg swing, with or without a ball. Plant, swing through, and let the follow-through finish high.',
        frames=(
            _pose(head=(48, 18), neck=(48, 29), hip=(48, 55),
                  elbow_near=(56, 40), wrist_near=(62, 48),
                  elbow_far=(40, 40), wrist_far=(34, 48),
                  knee_near=(40, 72), ankle_near=(34, 88), toe_near=(28, 90),
                  knee_far=(50, 72), ankle_far=(50, 90), toe_far=(56, 90),
                  ball=(62, 86)),
            _pose(head=(50, 18), neck=(50, 29), hip=(52, 55),
                  elbow_near=(58, 38), wrist_near=(64, 44),
                  elbow_far=(42, 38), wrist_far=(36, 46),
                  knee_near=(66, 44), ankle_near=(76, 32), toe_near=(82, 28),
                  knee_far=(50, 72), ankle_far=(50, 90), toe_far=(56, 90),
                  ball=(84, 20)),
        ),
    ),
    "fb_shuffle": Demo(
        caption="Slide across without turning your hips — a back mirroring a receiver, or a tackle's kick-slide.",
        view="front",
        frames=(
            _pose(head=(44, 20), neck=(44, 31), hip=(45, 55),
                  elbow_near=(32, 42), wrist_near=(25, 48),
                  elbow_far=(58, 42), wrist_far=(65, 48),
                  knee_near=(33, 68), ankle_near=(28, 90), toe_near=(23, 90),
                  knee_far=(58, 68), ankle_far=(64, 90), toe_far=(69, 90)),
            _pose(head=(56, 20), neck=(56, 31), hip=(55, 55),
                  elbow_near=(68, 42), wrist_near=(75, 48),
                  elbow_far=(42, 42), wrist_far=(35, 48),
                  knee_near=(67, 68), ankle_near=(72, 90), toe_near=(77, 90),
                  knee_far=(42, 68), ankle_far=(36, 90), toe_far=(31, 90)),
        ),
    ),
    "rug_wall_pass": Demo(
        caption='Pass into the wall, catch it, and pass it back the other way. Your hands have to cross your body each time.',
        scenery="wall",
        frames=(
            _pose(head=(52, 20), neck=(51, 31), hip=(52, 56),
                  elbow_near=(60, 36), wrist_near=(66, 42),
                  elbow_far=(56, 37), wrist_far=(62, 43),
                  knee_near=(50, 72), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(54, 72), ankle_far=(54, 90), toe_far=(60, 90),
                  ball=(68, 44)),
            _pose(head=(52, 20), neck=(51, 31), hip=(52, 56),
                  elbow_near=(44, 34), wrist_near=(34, 32),
                  elbow_far=(45, 35), wrist_far=(35, 33),
                  knee_near=(50, 72), ankle_near=(50, 90), toe_near=(56, 90),
                  knee_far=(54, 72), ankle_far=(54, 90), toe_far=(60, 90),
                  ball=(16, 30)),
        ),
    ),
    "rug_quick_hands": Demo(
        caption='Catch and pass in one movement, close to the wall, both directions. One trip across your body is one rep.',
        view="front",
        frames=(
            _pose(head=(50, 18), neck=(50, 29), hip=(50, 54),
                  elbow_near=(60, 38), wrist_near=(66, 44),
                  elbow_far=(42, 38), wrist_far=(48, 44),
                  knee_near=(44, 70), ankle_near=(40, 90), toe_near=(35, 90),
                  knee_far=(56, 70), ankle_far=(60, 90), toe_far=(65, 90),
                  ball=(70, 46)),
            _pose(head=(50, 18), neck=(50, 29), hip=(50, 54),
                  elbow_near=(40, 38), wrist_near=(34, 44),
                  elbow_far=(58, 38), wrist_far=(52, 44),
                  knee_near=(44, 70), ankle_near=(40, 90), toe_near=(35, 90),
                  knee_far=(56, 70), ankle_far=(60, 90), toe_far=(65, 90),
                  ball=(30, 46)),
        ),
    ),
    "rug_spin_pass": Demo(
        caption='The long one. Hands start behind your back hip and finish pointing straight at the target.',
        view="front",
        frames=(
            _pose(head=(50, 18), neck=(50, 29), hip=(52, 54),
                  elbow_near=(64, 44), wrist_near=(72, 54),
                  elbow_far=(60, 45), wrist_far=(68, 55),
                  knee_near=(44, 70), ankle_near=(40, 90), toe_near=(35, 90),
                  knee_far=(58, 70), ankle_far=(64, 90), toe_far=(69, 90),
                  ball=(74, 58)),
            _pose(head=(50, 18), neck=(50, 29), hip=(48, 54),
                  elbow_near=(38, 36), wrist_near=(26, 30),
                  elbow_far=(40, 37), wrist_far=(28, 31),
                  knee_near=(44, 70), ankle_near=(40, 90), toe_near=(35, 90),
                  knee_far=(56, 70), ankle_far=(60, 90), toe_far=(65, 90),
                  ball=(14, 26)),
        ),
    ),
    "swm_streamline": Demo(
        caption='Arms locked overhead, one hand over the other, ears squeezed between your biceps, body in one straight line. Hold it.',
        view="front",
        mirror=False,
        seconds=4.0,
        frames=(
            _pose(head=(50, 26), neck=(50, 36), hip=(50, 58),
                  elbow_near=(46, 26), wrist_near=(49, 12),
                  elbow_far=(54, 26), wrist_far=(51, 13),
                  knee_near=(50, 74), ankle_near=(50, 90), toe_near=(45, 90),
                  knee_far=(52, 74), ankle_far=(52, 90), toe_far=(57, 90)),
        ),
    ),
    "swm_pull": Demo(
        caption='Bands anchored high and bent forward at the hips. Pull from '
                'full reach all the way through to your hip.',
        frames=(
            _pose(head=(34, 40), neck=(41, 45), hip=(58, 55),
                  elbow_near=(36, 33), wrist_near=(26, 23),
                  elbow_far=(37, 34), wrist_far=(27, 24),
                  knee_near=(62, 72), ankle_near=(58, 90), toe_near=(52, 90),
                  knee_far=(64, 73), ankle_far=(60, 90), toe_far=(54, 90)),
            _pose(head=(34, 40), neck=(41, 45), hip=(58, 55),
                  elbow_near=(44, 44), wrist_near=(56, 54),
                  elbow_far=(45, 45), wrist_far=(57, 55),
                  knee_near=(62, 72), ankle_near=(58, 90), toe_near=(52, 90),
                  knee_far=(64, 73), ankle_far=(60, 90), toe_far=(54, 90)),
        ),
    ),
    "sb_windmill": Demo(
        caption='The full underhand circle, with or without a ball. Half a circle does not count — take it all the way round.',
        frames=(
            _pose(head=(52, 20), neck=(52, 31), hip=(52, 56),
                  elbow_near=(58, 20), wrist_near=(60, 8),
                  elbow_far=(46, 38), wrist_far=(42, 48),
                  knee_near=(48, 72), ankle_near=(44, 90), toe_near=(38, 90),
                  knee_far=(56, 72), ankle_far=(60, 90), toe_far=(66, 90),
                  ball=(62, 4)),
            _pose(head=(52, 20), neck=(52, 31), hip=(52, 56),
                  elbow_near=(58, 44), wrist_near=(56, 58),
                  elbow_far=(46, 38), wrist_far=(42, 48),
                  knee_near=(44, 72), ankle_near=(36, 90), toe_near=(30, 90),
                  knee_far=(58, 72), ankle_far=(64, 90), toe_far=(70, 90),
                  ball=(54, 64)),
        ),
    ),
}

#: Drills a drawn figure cannot teach, and why. Kept as data next to the
#: poses so the two halves of the answer stay in one place, and so a drill
#: can never quietly end up with neither a demonstration nor a plan for one.
NEEDS_FILM: dict[str, str] = {
    "gen_dead_bug": "Supine, seen side-on. Two attempts at the drawing and it "
                    "still reads as an abstraction rather than a body.",
    "gen_glute_bridge": "Supine. The lift is real but the starting shape is "
                        "the same ambiguous horizontal line as a dead bug.",
    "gen_hollow_hold": "Supine, and the whole point is a subtle curve of the "
                       "lower back that a stick figure has no way to show.",
    "lax_wall_ball_btb": "The stick goes *behind* the athlete, which is the "
                         "one direction a side-on view flattens to nothing. "
                         "Drawn, it reads as a stick through the stomach.",
}

DRILLS_BY_KEY = {d.key: d for d in ALL_DRILLS}


#: No demonstration cycles faster than this, however fast the drill is. Below
#: it the figure is a blur and teaches nothing.
MIN_LEGIBLE_SECONDS = 1.2


def seconds_for(drill_key: str) -> float:
    """One cycle, at the tempo the scorer actually rewards.

    The midpoint of the drill's scored tempo band -- the same expression the
    technique trace uses, so the figure and the trace beside it move at one
    speed, and both move at the speed the counter pays for. A demonstration
    that ran at its own pace would be teaching a rep that scores badly, which
    is the exact failure a filmed clip has and this is meant not to.

    A test asserts the two stay equal for every drill that has both.
    """
    demo = DEMOS[drill_key]
    if demo.seconds is not None:
        return demo.seconds
    drill = DRILLS_BY_KEY[drill_key]
    if drill.quality is None:
        # Some drills have no scored tempo band to borrow -- the ball-contact
        # ones, where the app counts bounces and does not grade form, so there
        # is nothing to fit a band to. The refractory window stands in.
        #
        # The 1.2s floor is a legibility decision, not a clamp that happened.
        # A dribble is countable at 140ms and drawn at that speed it is a
        # blur; a demonstration is a diagram of a movement, not a recording of
        # one, and the caption carries the fact that it should be fast.
        return max(MIN_LEGIBLE_SECONDS, drill.counter.min_rep_ms * 1.5 / 1000)
    return (drill.quality.tempo_min_ms + drill.quality.tempo_max_ms) // 2 / 1000


def _points(pose: dict[str, tuple[float, float]], chain: tuple[str, ...]) -> str:
    return " ".join(f"{pose[j][0]:.1f},{pose[j][1]:.1f}" for j in chain)


#: The ground sits at y=90 and poses rest their contact points on it. Figures
#: that floated above the line read as falling rather than holding, which was
#: the first thing anyone noticed about the earlier drafts.
FLOOR = 90.0

SCENERY = {
    "floor": '<line x1="4" y1="90" x2="96" y2="90" class="ground"/>',
    "wall": '<line x1="8" y1="6" x2="8" y2="90" class="ground"/>'
            '<line x1="4" y1="90" x2="96" y2="90" class="ground"/>',
    "bar": '<line x1="16" y1="10" x2="84" y2="10" class="ground"/>'
           '<line x1="4" y1="90" x2="96" y2="90" class="ground"/>',
    "none": "",
}


def svg(drill_key: str) -> str:
    """The demonstration as a self-contained animated SVG.

    Animated with SMIL rather than CSS because the thing that has to move is a
    polyline's `points`, which CSS cannot address. No script, so it is safe to
    inline or to serve to an <img>.
    """
    demo = DEMOS[drill_key]
    frames = list(demo.frames)
    if demo.mirror and len(frames) > 1:
        frames = frames + frames[-2::-1]
    else:
        frames = frames + [frames[0]] if len(frames) > 1 else frames

    dur = f"{seconds_for(drill_key):.2f}s"
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" '
        'role="img" aria-label="' + demo.caption.replace('"', "") + '">',
        "<style>"
        ".fig{fill:none;stroke:#008BFD;stroke-width:3.4;stroke-linecap:round;"
        "stroke-linejoin:round}"
        ".head{fill:#008BFD}"
        ".ground{stroke:#4A5A6B;stroke-width:1.4;stroke-linecap:round;"
        "opacity:.55}"
        # The stick is drawn heavier than a limb and in the ink colour: it is
        # equipment, not part of the athlete, and a figure whose stick is the
        # same weight as its arms reads as having three arms.
        ".stick{fill:none;stroke:#0B1B2B;stroke-width:2.6;stroke-linecap:round}"
        ".ball{fill:#F0A64A}"
        "</style>",
        SCENERY.get(demo.scenery, ""),
    ]

    # The far-side limbs are drawn first and faded, so a side-on figure reads
    # as a body rather than a tangle of identical sticks.
    for chain in CHAINS:
        far = demo.view == "side" and any(j.endswith("_far") for j in chain)
        values = ";".join(_points(f, chain) for f in frames)
        fade = ' opacity=".42"' if far else ""
        parts.append(
            f'<polyline class="fig"{fade} '
            f'points="{_points(frames[0], chain)}">'
            f'<animate attributeName="points" dur="{dur}" '
            f'repeatCount="indefinite" values="{values}"/></polyline>')

    # The stick, when the sport has one. Drawn before the head so the head
    # sits on top of it rather than under it.
    if all("stick_butt" in f for f in frames):
        values = ";".join(
            f"{f['stick_butt'][0]:.1f},{f['stick_butt'][1]:.1f} "
            f"{f['stick_head'][0]:.1f},{f['stick_head'][1]:.1f}"
            for f in frames)
        b, h = frames[0]["stick_butt"], frames[0]["stick_head"]
        parts.append(
            f'<polyline class="stick" points="{b[0]:.1f},{b[1]:.1f} '
            f'{h[0]:.1f},{h[1]:.1f}">'
            f'<animate attributeName="points" dur="{dur}" '
            f'repeatCount="indefinite" values="{values}"/></polyline>')

    if all("ball" in f for f in frames):
        b0 = frames[0]["ball"]
        if DRILLS_BY_KEY[drill_key].sport in OVAL_BALL_SPORTS:
            # An oblong ball is translated as a group rather than moved by its
            # own centre, so the tilt stays put instead of swinging the ball
            # around a fixed point as it travels.
            path = ";".join(f"{f['ball'][0]:.1f},{f['ball'][1]:.1f}"
                            for f in frames)
            parts.append(
                f'<g transform="translate({b0[0]:.1f},{b0[1]:.1f})">'
                f'<animateTransform attributeName="transform" type="translate" '
                f'dur="{dur}" repeatCount="indefinite" values="{path}"/>'
                f'<ellipse class="ball" cx="0" cy="0" rx="4.3" ry="2.5" '
                f'transform="rotate(-28)"/></g>')
        else:
            bx = ";".join(f"{f['ball'][0]:.1f}" for f in frames)
            by = ";".join(f"{f['ball'][1]:.1f}" for f in frames)
            parts.append(
                f'<circle class="ball" cx="{b0[0]:.1f}" cy="{b0[1]:.1f}" r="2.6">'
                f'<animate attributeName="cx" dur="{dur}" '
                f'repeatCount="indefinite" values="{bx}"/>'
                f'<animate attributeName="cy" dur="{dur}" '
                f'repeatCount="indefinite" values="{by}"/></circle>')

    cx = ";".join(f"{f['head'][0]:.1f}" for f in frames)
    cy = ";".join(f"{f['head'][1]:.1f}" for f in frames)
    h = frames[0]["head"]
    parts.append(
        f'<circle class="head" cx="{h[0]:.1f}" cy="{h[1]:.1f}" r="5.6">'
        f'<animate attributeName="cx" dur="{dur}" repeatCount="indefinite" '
        f'values="{cx}"/>'
        f'<animate attributeName="cy" dur="{dur}" repeatCount="indefinite" '
        f'values="{cy}"/></circle>')
    parts.append("</svg>")
    return "".join(parts)


def has_demo(drill_key: str) -> bool:
    return drill_key in DEMOS


def coverage() -> dict[str, object]:
    """Which drills can show a beginner what the movement is.

    Reported the same way technique coverage is, because a partially answered
    "what is this exercise" is exactly the kind of gap that goes quiet. The
    three counts are deliberately separate: a drill that is drawn, a drill
    waiting on a camera, and a drill nobody has decided about yet are three
    different states and only the last one is a problem.
    """
    drawn = [d.key for d in ALL_DRILLS if d.key in DEMOS]
    filmed = [d.key for d in ALL_DRILLS if d.key in NEEDS_FILM]
    undecided = [d.key for d in ALL_DRILLS
                 if d.key not in DEMOS and d.key not in NEEDS_FILM]
    return {
        "drills": len(ALL_DRILLS),
        "with_demo": len(drawn),
        "needs_film": filmed,
        "undecided": undecided,
        "without_demo": filmed + undecided,
    }
