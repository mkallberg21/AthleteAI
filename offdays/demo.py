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
    #: Play the frames forward then back, which is what a rep does.
    mirror: bool = True
    #: Seconds for one cycle. Filled from the drill's own tempo when absent.
    seconds: float | None = None


def _pose(**joints: tuple[float, float]) -> dict[str, tuple[float, float]]:
    missing = [j for j in JOINTS if j not in joints]
    if missing:
        raise ValueError(f"pose is missing {missing}")
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
}

DRILLS_BY_KEY = {d.key: d for d in ALL_DRILLS}


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
        # No scored tempo band to borrow, so fall back to the refractory
        # window, which at least cannot be faster than a countable rep.
        return max(1.2, drill.counter.min_rep_ms * 1.5 / 1000)
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
        "</style>",
        SCENERY.get(demo.scenery, ""),
    ]

    # The far-side limbs are drawn first and faded, so a side-on figure reads
    # as a body rather than a tangle of identical sticks.
    for chain in CHAINS:
        far = any(j.endswith("_far") for j in chain)
        values = ";".join(_points(f, chain) for f in frames)
        fade = ' opacity=".42"' if far else ""
        parts.append(
            f'<polyline class="fig"{fade} '
            f'points="{_points(frames[0], chain)}">'
            f'<animate attributeName="points" dur="{dur}" '
            f'repeatCount="indefinite" values="{values}"/></polyline>')

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
