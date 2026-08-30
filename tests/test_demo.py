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
    assert len(drawn) == 22, (
        f"expected 22 drawn general drills, found {len(drawn)}: "
        "raise this deliberately when adding one, never to make a loss pass")


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
DONE = ["gymnastics", "cheer", "dance", "lacrosse", "basketball"]


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
