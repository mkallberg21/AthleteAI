"""The animated movement demonstrations.

Unwired by design -- see the module docstring. These tests hold the parts that
are settled, so the mechanism does not rot while the poses are being decided.
"""
import re

import pytest

from offdays import demo, technique
from offdays.drills import ALL_DRILLS
from offdays.positions import BY_SPORT


def test_every_pose_places_every_joint():
    for key, spec in demo.DEMOS.items():
        for i, frame in enumerate(spec.frames):
            missing = [j for j in demo.JOINTS if j not in frame]
            assert not missing, f"{key} frame {i} is missing {missing}"


def test_every_chain_only_names_real_joints():
    for chain in demo.CHAINS:
        for joint in chain:
            assert joint in demo.JOINTS, joint


def test_a_demo_runs_at_the_tempo_the_scorer_rewards():
    """The whole argument for generating this rather than filming it.

    A clip shot once and a threshold tuned later disagree silently, and the
    athlete pays for it. Where the scorer has a tempo band, the demonstration
    reads the same number, so the two cannot drift apart.
    """
    checked = 0
    for key, spec in demo.DEMOS.items():
        if spec.seconds is not None:
            continue  # an explicit override, for holds with no rep cycle
        trace = (technique.reference(key) or {}).get("trace")
        if not trace:
            continue  # no scored band to agree with -- covered below
        assert demo.seconds_for(key) == pytest.approx(trace["tempo_ms"] / 1000)
        checked += 1
    assert checked > 20, "the agreement is barely being tested"


def test_a_drill_with_no_scored_tempo_still_gets_a_legible_one():
    """The ball-contact drills have no quality spec -- the app counts bounces
    and does not grade form, so there is no band to fit. They fall back to the
    refractory window with a legibility floor, because a dribble is countable
    at 140ms and drawn at that speed it is a blur."""
    without = [k for k, spec in demo.DEMOS.items()
               if spec.seconds is None
               and not (technique.reference(k) or {}).get("trace")]
    assert without, "expected some drills with no scored tempo"
    for key in without:
        assert demo.seconds_for(key) >= demo.MIN_LEGIBLE_SECONDS, key


def test_the_svg_is_inert():
    """It is served to children and may be inlined, so it carries no script."""
    for key in demo.DEMOS:
        svg = demo.svg(key)
        assert svg.startswith("<svg") and svg.endswith("</svg>")
        assert "<script" not in svg.lower()
        assert "onload" not in svg.lower()
        # The xmlns is a namespace identifier, not something fetched. Any
        # other URL would be: an external reference in an offline drill view.
        rest = svg.replace('xmlns="http://www.w3.org/2000/svg"', "")
        assert "http" not in rest, key


def test_a_demo_is_small_enough_to_inline():
    # The point of SVG over video. If one of these ever approaches a clip's
    # weight the argument for generating it has gone.
    for key in demo.DEMOS:
        assert len(demo.svg(key)) < 8_000, key


def test_every_demo_names_a_real_drill():
    keys = {d.key for d in ALL_DRILLS}
    for key in demo.DEMOS:
        assert key in keys, key


def test_a_mirrored_demo_returns_to_where_it_started():
    """A rep ends where it began, or the loop jumps."""
    for key, spec in demo.DEMOS.items():
        if not (spec.mirror and len(spec.frames) > 1):
            continue
        values = re.search(r'values="([^"]+)"', demo.svg(key)).group(1)
        frames = values.split(";")
        assert frames[0] == frames[-1], key


def test_coverage_accounts_for_every_drill():
    got = demo.coverage()
    assert got["drills"] == len(ALL_DRILLS)
    assert got["with_demo"] + len(got["without_demo"]) == got["drills"]
    assert len(got["needs_film"]) + len(got["undecided"]) == len(got["without_demo"])


def test_a_drill_is_drawn_or_filmed_but_never_both():
    """The two halves of the hybrid must not disagree about a drill."""
    both = set(demo.DEMOS) & set(demo.NEEDS_FILM)
    assert not both, both


def test_the_film_backlog_says_why():
    """A bare list of keys becomes noise nobody acts on."""
    for key, reason in demo.NEEDS_FILM.items():
        assert len(reason) > 40, f"{key}: {reason!r}"
        assert key in {d.key for d in ALL_DRILLS}, key


def test_the_whole_shared_library_is_accounted_for():
    """Every general drill is drawn or on the list to be filmed.

    The shared athleticism library is the widest reach in the product: every
    sport draws on it, so one missing pose is missing from sixteen sports at
    once. This exists because a pose really was silently deleted while an
    adjacent one was being edited, and nothing failed.
    """
    general = [d.key for d in ALL_DRILLS if d.sport == "general"]
    assert general, "no shared library to check"
    stranded = sorted(k for k in general
                      if k not in demo.DEMOS and k not in demo.NEEDS_FILM)
    assert not stranded, f"shared library drills with no answer: {stranded}"


def test_no_pose_was_lost_from_the_shared_library():
    """A count, so a deletion fails loudly rather than shrinking quietly."""
    drawn = [d.key for d in ALL_DRILLS
             if d.sport == "general" and d.key in demo.DEMOS]
    assert len(drawn) == 27, (
        f"expected 27 drawn general drills, found {len(drawn)}: "
        "raise this deliberately when adding one, never to make a loss pass")


def test_the_whole_catalog_is_drawn_but_for_a_named_few():
    """A count, so a silent loss fails instead of shrinking quietly."""
    assert len(demo.DEMOS) == 90
    assert len(demo.NEEDS_FILM) == 8


def test_a_stick_sport_actually_draws_a_stick():
    """A lacrosse figure without one is a person standing near a wall."""
    for key in (k for k in demo.DEMOS if k.startswith("lax_")):
        for i, frame in enumerate(demo.DEMOS[key].frames):
            assert "stick_butt" in frame, f"{key} frame {i} has no stick"


def test_drills_that_share_a_picture_do_not_share_a_caption():
    """Sharing frames is allowed -- wall ball and its hand-order variants are
    genuinely the same shape. Sharing the words as well would leave an athlete
    with no way to tell which drill they had opened."""
    seen: dict[tuple, str] = {}
    for key, spec in demo.DEMOS.items():
        signature = tuple(tuple(sorted(f.items())) for f in spec.frames)
        if signature in seen:
            assert spec.caption != demo.DEMOS[seen[signature]].caption, (
                f"{key} and {seen[signature]} share frames and caption")
        else:
            seen[signature] = key


def test_an_optional_joint_is_never_half_placed():
    for key, spec in demo.DEMOS.items():
        for frame in spec.frames:
            assert ("stick_butt" in frame) == ("stick_head" in frame), key


#: Sports worked through so far. A sport joins this list when every drill in
#: it is either drawn or on the film list, and it never leaves -- which is the
#: point, because the way this regresses is a new drill landing in a finished
#: sport with nobody noticing.
#: Every sport with position plans. A sport joins when all its drills are
#: drawn or on the film list and never leaves -- the way this regresses is a
#: new drill landing in a finished sport with nobody noticing. The shared
#: library is not here because it has its own test above.
DONE = sorted(BY_SPORT)


@pytest.mark.parametrize("sport", DONE)
def test_a_finished_sport_has_an_answer_for_every_drill(sport):
    """Every drill a plan in this sport uses is drawn or listed for filming.

    The conditioning sports were first because they have no sport-specific
    drills at all, so an athlete meeting a strange exercise name there has
    nothing else to fall back on.
    """
    used = {k for p in BY_SPORT[sport] for k in p.emphasis}
    used |= {d.key for d in ALL_DRILLS if d.sport == sport}
    stranded = sorted(used - set(demo.DEMOS) - set(demo.NEEDS_FILM))
    assert not stranded, f"{sport} has drills with no demo and no plan: {stranded}"


def _contrast(a: str, b: str) -> float:
    def lum(h):
        h = h.lstrip("#")
        ch = []
        for i in (0, 2, 4):
            v = int(h[i:i + 2], 16) / 255
            ch.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


#: The two grounds a demonstration is seen on: the app's dark card, and a
#: white page for anything printed or reviewed.
GROUNDS = ("#0B1B2B", "#FFFFFF")


def test_a_filmstrip_holds_still_and_shows_every_frame():
    """Print cannot animate. A single frame of a squat is a photograph of
    somebody standing up, so the page gets the keyframes in a row instead."""
    for key, spec in demo.DEMOS.items():
        strip = demo.filmstrip(key)
        assert "<animate" not in strip, f"{key}'s strip animates"
        assert "<script" not in strip
        width = int(re.search(r'viewBox="0 0 (\d+) 100"', strip).group(1))
        assert width == 100 * len(spec.frames), key


def test_both_renderings_share_one_palette():
    """Two copies of the palette is how the stick came to be a colour that
    vanished against the ground it was shown on."""
    for key in ("hoc_shot", "gen_squat", "fb_kick"):
        assert demo.STYLE in demo.svg(key)
        assert demo.STYLE in demo.filmstrip(key)


def test_the_equipment_is_visible_on_both_grounds():
    """The stick was the brand ink until that met the app's dark surface,
    where ink on ink is 1.0:1 and a hockey player was holding nothing."""
    stroke = re.search(r"\.stick\{[^}]*stroke:(#[0-9A-Fa-f]{6})",
                       demo.svg("hoc_shot")).group(1)
    for ground in GROUNDS:
        assert _contrast(stroke, ground) >= 3.0, (
            f"the stick is {_contrast(stroke, ground):.2f}:1 on {ground}")


def test_every_ball_is_visible_on_both_grounds():
    """A white ball needs an edge on a pale page and a puck needs one on the
    dark card. One outline serves both, and it has to actually serve both."""
    outline = re.search(r"\.ball\{[^}]*stroke:(#[0-9A-Fa-f]{6})",
                        demo.svg("hoc_shot")).group(1)
    for key in demo.DEMOS:
        drill = demo.DRILLS_BY_KEY[key]
        if not all("ball" in f for f in demo.DEMOS[key].frames):
            continue
        fill = demo.ball_fill(key)
        for ground in GROUNDS:
            assert max(_contrast(fill, ground), _contrast(outline, ground)) >= 3.0, (
                f"{key}'s ball disappears on {ground}")


def test_every_ball_colour_a_drill_names_has_a_fill():
    """A new preset added to the catalog must not fall through to a default."""
    for drill in ALL_DRILLS:
        if drill.ball is None or drill.key not in demo.DEMOS:
            continue
        assert drill.ball.colour in demo.BALL_FILL, drill.ball.colour
    for sport in demo.BALL_FILL_BY_SPORT:
        assert sport in {d.sport for d in ALL_DRILLS}, sport


def test_an_oblong_ball_is_drawn_oblong():
    """A football and a rugby ball are not round, and a diagram that says they
    are is teaching something false about the only object in the picture."""
    sport = {d.key: d.sport for d in ALL_DRILLS}
    for key, spec in demo.DEMOS.items():
        if not all("ball" in f for f in spec.frames):
            continue
        svg = demo.svg(key)
        if sport[key] in demo.OVAL_BALL_SPORTS:
            assert "<ellipse" in svg, f"{key} draws a round ball"
        else:
            assert "<ellipse" not in svg, f"{key} draws an oblong ball"


def test_the_oval_sports_are_the_ones_with_oval_balls():
    assert demo.OVAL_BALL_SPORTS == {"football", "rugby"}
    known = {d.sport for d in ALL_DRILLS}
    assert demo.OVAL_BALL_SPORTS <= known, "names a sport that does not exist"


def test_a_rep_drill_moves_and_a_hold_does_not():
    """The shape of a demo has to match the shape of the drill.

    A drill counted in reps drawn as a single frame is a still photograph of
    an exercise, which teaches the position and not the movement -- dryland
    pulls shipped that way for exactly as long as it took to render them. A
    hold drawn with two frames teaches the opposite lie.
    """
    metric = {d.key: d.metric.name for d in ALL_DRILLS}
    for key, spec in demo.DEMOS.items():
        if metric[key] == "HOLD_SECONDS":
            assert len(spec.frames) == 1, f"{key} is a hold but animates"
        else:
            assert len(spec.frames) > 1, f"{key} is counted in reps but is a still"


def test_every_drill_in_the_product_is_accounted_for():
    """The finish line. Every drill is drawn or named for filming."""
    stranded = sorted(d.key for d in ALL_DRILLS
                      if d.key not in demo.DEMOS and d.key not in demo.NEEDS_FILM)
    assert not stranded, f"{len(stranded)} drills with no answer: {stranded}"


def test_a_front_view_never_fades_half_the_body():
    """The fade gives a profile depth. Facing the camera there is no far side,
    and dimming half a body reads as something being wrong with it."""
    for key, spec in demo.DEMOS.items():
        assert spec.view in ("side", "front"), f"{key} has view {spec.view!r}"


def test_a_demo_reaches_the_athlete_before_the_drill():
    """It is served with the reference, not behind a second request.

    The thing it answers -- what even is this exercise -- is needed before
    anything else on that screen can be acted on.
    """
    for key in list(demo.DEMOS)[:3]:
        ref = technique.reference(key)
        assert ref, key
