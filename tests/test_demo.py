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
    athlete pays for it. These two read the same number, so they cannot.
    """
    for key, spec in demo.DEMOS.items():
        if spec.seconds is not None:
            continue  # an explicit override, for holds with no rep cycle
        trace = (technique.reference(key) or {}).get("trace")
        assert trace, f"{key} has a demo but no technique trace"
        assert demo.seconds_for(key) == pytest.approx(trace["tempo_ms"] / 1000)


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


@pytest.mark.parametrize("sport", ["gymnastics", "cheer", "dance"])
def test_conditioning_sports_have_an_answer_for_every_drill(sport):
    """The sports that lean entirely on the shared library.

    They have no sport-specific drills at all, so an athlete meeting a
    strange exercise name has nothing else to fall back on. Every drill in
    their plans is either drawn or on the list to be filmed -- never neither.
    """
    used = {k for p in BY_SPORT[sport] for k in p.emphasis}
    stranded = sorted(used - set(demo.DEMOS) - set(demo.NEEDS_FILM))
    assert not stranded, f"{sport} has drills with no demo and no plan: {stranded}"


def test_a_demo_reaches_the_athlete_before_the_drill():
    """It is served with the reference, not behind a second request.

    The thing it answers -- what even is this exercise -- is needed before
    anything else on that screen can be acted on.
    """
    for key in list(demo.DEMOS)[:3]:
        ref = technique.reference(key)
        assert ref, key
