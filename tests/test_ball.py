"""Server-side checks on ball-tracked sessions.

The browser does the tracking, so the browser is where the numbers come from,
so the browser cannot be trusted with them. A ball payload is easier to fake
than a pose one -- a contact is a timestamp and a speed, not a skeleton.
"""

import pytest

from athleteiq import ball as B
from athleteiq.drills.catalog import ALL_DRILLS, DRILLS_BY_KEY

JUGGLE = DRILLS_BY_KEY["soc_juggle"]
DRIBBLE = DRILLS_BY_KEY["bkb_dribble"]
SQUAT = DRILLS_BY_KEY["gen_squat"]


def contacts(n=30, gap=900, jitter=(0, 70, 40), hand=None, speed=1.2):
    return [
        {
            "t_ms": i * gap + jitter[i % len(jitter)],
            "hand": hand if hand else ("left" if i % 2 else "right"),
            "speed": speed,
            "part": "left_ankle",
        }
        for i in range(n)
    ]


class TestABallDrillNeedsABall:

    def test_a_clean_session_passes(self):
        result = B.review(JUGGLE, contacts(), track_quality=0.62, duration_ms=28_000)
        assert result.ok and not result.hold

    def test_a_session_that_never_saw_the_ball_is_held(self):
        result = B.review(JUGGLE, contacts(), track_quality=0.05, duration_ms=28_000)
        assert not result.ok and result.hold
        assert "5%" in result.reasons[0]

    def test_a_session_under_the_drills_own_floor_is_held(self):
        assert JUGGLE.ball.min_track_quality == 0.35
        result = B.review(JUGGLE, contacts(), track_quality=0.28, duration_ms=28_000)
        assert not result.ok
        assert "35%" in result.reasons[0]

    def test_a_missing_quality_figure_is_itself_a_reason(self):
        """A real client always knows this number, so its absence means the
        payload did not come from one."""
        result = B.review(JUGGLE, contacts(), track_quality=None, duration_ms=28_000)
        assert not result.ok and result.hold

    def test_pose_drills_are_untouched(self):
        assert B.review(SQUAT, contacts(), track_quality=None, duration_ms=28_000).ok


class TestPhysicallyImplausiblePayloads:

    def test_contacts_faster_than_the_refractory_window_are_impossible(self):
        """A real client enforces the gap itself, so a payload below it was not
        produced by one."""
        fast = [{"t_ms": i * 40, "hand": "left", "speed": 1.2} for i in range(30)]
        result = B.review(JUGGLE, fast, track_quality=0.7, duration_ms=2_000)
        assert not result.ok
        assert any("faster than this drill allows" in r for r in result.reasons)

    def test_more_touches_than_the_ball_can_come_back_from(self):
        many = [{"t_ms": i * 200, "hand": "left", "speed": 1.2} for i in range(200)]
        result = B.review(JUGGLE, many, track_quality=0.7, duration_ms=40_000)
        assert not result.ok
        assert any("come back" in r for r in result.reasons)

    def test_metronomic_timing_is_a_generator_not_a_child(self):
        even = [{"t_ms": i * 900, "hand": "left", "speed": 1.2} for i in range(30)]
        result = B.review(JUGGLE, even, track_quality=0.7, duration_ms=28_000)
        assert not result.ok
        assert any("evenly spaced" in r for r in result.reasons)

    def test_natural_timing_passes(self):
        result = B.review(JUGGLE, contacts(), track_quality=0.7, duration_ms=28_000)
        assert result.ok

    def test_a_perfectly_even_left_right_split_is_refused(self):
        """Not what a child juggling in a garden produces. What a loop
        produces."""
        even = [
            {"t_ms": i * 900 + (i % 3) * 60,
             "hand": "left" if i % 2 else "right", "speed": 1.2}
            for i in range(80)
        ]
        result = B.review(JUGGLE, even, track_quality=0.7, duration_ms=74_000)
        assert not result.ok
        assert any("too exact" in r for r in result.reasons)

    def test_a_natural_lopsided_split_passes(self):
        lopsided = [
            {"t_ms": i * 900 + (i % 3) * 60,
             "hand": "left" if i % 5 else "right", "speed": 1.2}
            for i in range(80)
        ]
        assert B.review(lopsided and JUGGLE, lopsided, 0.7, 74_000).ok

    def test_a_short_session_is_not_judged_on_its_split(self):
        """Ten contacts landing evenly is chance, not evidence."""
        short = [
            {"t_ms": i * 900 + (i % 3) * 60,
             "hand": "left" if i % 2 else "right", "speed": 1.2}
            for i in range(10)
        ]
        assert B.review(JUGGLE, short, 0.7, 9_000).ok


class TestTheCatalogIsConsistent:

    def test_every_ball_drill_requires_the_ball(self):
        for drill in ALL_DRILLS:
            if drill.ball is not None:
                assert drill.ball.required, drill.key
                assert drill.needs_ball, drill.key

    def test_ball_drills_declare_who_can_touch_it(self):
        for drill in ALL_DRILLS:
            if drill.ball is None:
                continue
            assert drill.ball.parts, drill.key
            assert 0 < drill.ball.min_track_quality <= 1, drill.key
            assert drill.ball.contact in ("body", "ground"), drill.key

    def test_no_pose_drill_accidentally_gained_a_ball_spec(self):
        posey = {"gen_squat", "gen_push_up", "gen_plank", "lax_wall_ball"}
        for key in posey:
            assert DRILLS_BY_KEY[key].ball is None, key

    def test_ball_drills_carry_no_form_score(self):
        """Range of motion is a pose idea. A contact has none, and claiming a
        form score from one would be inventing a number."""
        for drill in ALL_DRILLS:
            if drill.ball is not None:
                assert drill.quality is None, drill.key


class TestSummary:

    def test_it_reports_what_a_coach_would_ask(self):
        out = B.summarise(contacts(n=12))
        assert out["contacts"] == 12
        assert out["median_speed"] == 1.2
        assert out["parts"] == {"left_ankle": 12}

    def test_an_empty_session_does_not_divide_by_zero(self):
        assert B.summarise([])["median_speed"] == 0.0
