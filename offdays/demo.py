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
assumed, which changed the answer. A squat reads immediately: an upright body
has a silhouette a child already recognises, and standing-to-squatting is
unmistakable. A push-up and a plank are legible. A dead bug is *not* -- two
attempts at the coordinates, and it still reads as an angular abstraction
rather than a person lying on their back. Floor work seen side-on gives a
two-joint stick figure nothing to be recognised by, and no amount of nudging
the numbers fixes that.

So this is deliberately not wired into capture: it is a proven mechanism with
an unproven half. Upright, silhouette-legible movements -- squats, lunges,
jumps, presses, holds -- are worth drawing this way. Supine floor work, and
anything needing rotation, grip or a piece of equipment for context, wants a
real filmed clip, and `web/static/technique/<key>.mp4` already accepts one.

A known flaw in every pose here: the figure floats above the ground line
instead of resting on it. Contact points -- a back, a pair of hands, a pair of
heels -- should touch. That is worth fixing before any of this ships.
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
    ("hip", "knee_far", "ankle_far"),
    ("hip", "knee_near", "ankle_near"),
)

#: Joints every pose must place. The head is a circle, not a chain.
JOINTS: tuple[str, ...] = (
    "head", "neck", "hip",
    "elbow_near", "wrist_near", "elbow_far", "wrist_far",
    "knee_near", "ankle_near", "knee_far", "ankle_far",
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
    "gen_dead_bug": Demo(
        caption="Lie on your back. Reach one arm back past your head and the "
                "opposite leg long and low, keeping your lower back flat.",
        scenery="floor",
        frames=(
            # Tabletop. Back and hips on the floor, thighs vertical, shins
            # level, both arms straight up. The starting shape of every rep.
            _pose(head=(27, 70), neck=(37, 74), hip=(63, 77),
                  elbow_near=(37, 62), wrist_near=(37, 50),
                  elbow_far=(39, 63), wrist_far=(39, 51),
                  knee_near=(63, 61), ankle_near=(77, 59),
                  knee_far=(65, 62), ankle_far=(79, 60)),
            # Near arm reaches back past the head, far leg reaches long and
            # low. Opposite limbs -- the other arm and knee hold tabletop,
            # which is what makes it a dead bug and not a stretch.
            _pose(head=(27, 70), neck=(37, 74), hip=(63, 77),
                  elbow_near=(27, 64), wrist_near=(15, 62),
                  elbow_far=(39, 63), wrist_far=(39, 51),
                  knee_near=(63, 61), ankle_near=(77, 59),
                  knee_far=(76, 72), ankle_far=(92, 77)),
        ),
    ),
    "gen_squat": Demo(
        caption="Stand tall, sit down between your heels, stand back up.",
        scenery="floor",
        frames=(
            _pose(head=(50, 12), neck=(50, 22), hip=(50, 48),
                  elbow_near=(44, 34), wrist_near=(44, 46),
                  elbow_far=(56, 34), wrist_far=(56, 46),
                  knee_near=(48, 66), ankle_near=(48, 86),
                  knee_far=(53, 66), ankle_far=(53, 86)),
            _pose(head=(50, 30), neck=(50, 40), hip=(52, 64),
                  elbow_near=(42, 48), wrist_near=(36, 40),
                  elbow_far=(58, 48), wrist_far=(64, 40),
                  knee_near=(40, 70), ankle_near=(48, 86),
                  knee_far=(45, 70), ankle_far=(53, 86)),
        ),
    ),
    "gen_push_up": Demo(
        caption="Straight line from head to heels. Bend until your chest is "
                "near the floor, press back up.",
        scenery="floor",
        frames=(
            _pose(head=(20, 44), neck=(28, 48), hip=(56, 56),
                  elbow_near=(28, 62), wrist_near=(28, 76),
                  elbow_far=(29, 62), wrist_far=(29, 76),
                  knee_near=(72, 64), ankle_near=(88, 74),
                  knee_far=(73, 65), ankle_far=(89, 75)),
            _pose(head=(20, 62), neck=(28, 64), hip=(56, 68),
                  elbow_near=(40, 62), wrist_near=(28, 76),
                  elbow_far=(41, 63), wrist_far=(29, 76),
                  knee_near=(72, 72), ankle_near=(88, 78),
                  knee_far=(73, 73), ankle_far=(89, 79)),
        ),
    ),
    "gen_plank": Demo(
        caption="Hold it. Straight from head to heels, hips neither sagging "
                "nor stuck up in the air.",
        scenery="floor",
        mirror=False,
        seconds=4.0,
        frames=(
            _pose(head=(18, 52), neck=(26, 56), hip=(56, 64),
                  elbow_near=(26, 76), wrist_near=(36, 76),
                  elbow_far=(27, 77), wrist_far=(37, 77),
                  knee_near=(72, 71), ankle_near=(88, 78),
                  knee_far=(73, 72), ankle_far=(89, 79)),
        ),
    ),
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


SCENERY = {
    "floor": '<line x1="4" y1="92" x2="96" y2="92" class="ground"/>',
    "wall": '<line x1="6" y1="6" x2="6" y2="94" class="ground"/>'
            '<line x1="4" y1="92" x2="96" y2="92" class="ground"/>',
    "bar": '<line x1="14" y1="10" x2="86" y2="10" class="ground"/>',
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
    "what is this exercise" is exactly the kind of gap that goes quiet.
    """
    without = [d.key for d in ALL_DRILLS if d.key not in DEMOS]
    return {
        "drills": len(ALL_DRILLS),
        "with_demo": len(ALL_DRILLS) - len(without),
        "without_demo": without,
    }
