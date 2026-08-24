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

    def test_count_mode_drills_require_the_ball(self):
        for drill in ALL_DRILLS:
            if drill.ball is not None and drill.ball.counts:
                assert drill.ball.required, drill.key
                assert drill.needs_ball, drill.key

    def test_confirm_mode_drills_never_require_it(self):
        """Confirm mode exists precisely because not seeing the ball proves
        nothing. A required flag there would punish a detector's blind spot."""
        for drill in ALL_DRILLS:
            if drill.ball is not None and drill.ball.confirms:
                assert not drill.ball.required, drill.key
                assert not drill.needs_ball, drill.key

    def test_ball_drills_declare_who_can_touch_it(self):
        for drill in ALL_DRILLS:
            if drill.ball is None:
                continue
            assert drill.ball.parts, drill.key
            assert 0 < drill.ball.min_track_quality <= 1, drill.key
            assert drill.ball.contact in ("body", "ground"), drill.key

    def test_no_bodyweight_drill_gained_a_ball_spec(self):
        for key in ("gen_squat", "gen_push_up", "gen_plank", "gen_lunge"):
            assert DRILLS_BY_KEY[key].ball is None, key

    def test_wall_ball_confirms_rather_than_counts(self):
        """Replacing its counter would break every athlete's history for no
        gain: the pose signal already works. The ball's job here is to catch
        the one thing pose cannot see, which is that there was no ball."""
        drill = DRILLS_BY_KEY["lax_wall_ball"]
        assert drill.confirms_ball
        assert not drill.needs_ball
        assert drill.signal.kind.value == "wall_ball_cycle", "still pose-counted"

    def test_count_mode_drills_carry_no_form_score(self):
        """Range of motion is a pose idea. A contact has none, and claiming a
        form score from one would be inventing a number."""
        for drill in ALL_DRILLS:
            if drill.ball is not None and drill.ball.counts:
                assert drill.quality is None, drill.key

    def test_confirm_mode_keeps_its_form_score(self):
        """The pose signal is still there and still worth scoring."""
        assert DRILLS_BY_KEY["lax_wall_ball"].quality is not None


class TestSummary:

    def test_it_reports_what_a_coach_would_ask(self):
        out = B.summarise(contacts(n=12))
        assert out["contacts"] == 12
        assert out["median_speed"] == 1.2
        assert out["parts"] == {"left_ankle": 12}

    def test_an_empty_session_does_not_divide_by_zero(self):
        assert B.summarise([])["median_speed"] == 0.0


class TestConfirmingWallBall:
    """Asymmetric on purpose: not seeing a ball proves nothing, seeing one
    clearly and watching it never leave a hand proves a lot."""

    WALL_BALL = DRILLS_BY_KEY["lax_wall_ball"]

    def throws(self, n=40):
        return [{"t_ms": i * 1200, "hand": "left" if i % 2 else "right"} for i in range(n)]

    def test_an_older_client_counts_exactly_as_before(self):
        """Ball tracking must not break a client that predates it, or an
        offline session queued before the update."""
        result = B.review(
            self.WALL_BALL, self.throws(), track_quality=None, duration_ms=48_000,
        )
        assert result.ok and not result.hold and not result.notes

    def test_a_ball_the_detector_cannot_see_costs_nothing(self):
        """A lacrosse ball is outside COCO's vocabulary. Marking a child down
        for that would be punishing them for a model's blind spot."""
        result = B.review(
            self.WALL_BALL, self.throws(), track_quality=0.04,
            duration_ms=48_000, ball_contacts=0,
        )
        assert result.ok and not result.hold
        assert any("does not count against" in n for n in result.notes)

    def test_a_confirmed_session_passes_quietly(self):
        result = B.review(
            self.WALL_BALL, self.throws(), track_quality=0.55,
            duration_ms=48_000, ball_contacts=34,
        )
        assert result.ok and not result.hold

    def test_waving_a_ball_around_is_caught_by_travel(self):
        """The case contact counting cannot see.

        An arm whipping through a throwing motion with the ball still in it
        produces the same impulse beside the same wrist as a real release --
        measured at twelve contacts for twelve fake throws, identical to the
        real session. What it cannot fake is the ball leaving the hand.
        """
        result = B.review(
            self.WALL_BALL, self.throws(), track_quality=0.63,
            duration_ms=48_000, ball_contacts=12, ball_travel=0.0,
        )
        assert not result.ok and result.hold
        assert "never travelled away from your hands" in result.reasons[0]

    def test_a_real_session_travels_and_passes(self):
        result = B.review(
            self.WALL_BALL, self.throws(), track_quality=0.50,
            duration_ms=48_000, ball_contacts=12, ball_travel=0.45,
        )
        assert result.ok and not result.hold

    def test_travel_is_not_judged_when_the_client_does_not_report_it(self):
        """An older client sends no travel figure, and silence is not evidence."""
        result = B.review(
            self.WALL_BALL, self.throws(), track_quality=0.50,
            duration_ms=48_000, ball_contacts=12, ball_travel=None,
        )
        assert result.ok

    def test_shadow_throwing_with_the_ball_in_shot_is_caught(self):
        """The exact hole this closes: forty throwing motions, a ball tracked
        clearly the whole time, and it never once left a hand."""
        result = B.review(
            self.WALL_BALL, self.throws(), track_quality=0.62,
            duration_ms=48_000, ball_contacts=1,
        )
        assert not result.ok and result.hold
        assert "only 2%" in result.reasons[0]

    def test_a_short_session_is_never_judged_this_way(self):
        """Eight throws where the detector happened to miss is noise."""
        result = B.review(
            self.WALL_BALL, self.throws(8), track_quality=0.55,
            duration_ms=10_000, ball_contacts=0,
        )
        assert result.ok

    def test_a_client_that_reports_quality_but_no_contacts_is_not_accused(self):
        result = B.review(
            self.WALL_BALL, self.throws(), track_quality=0.55,
            duration_ms=48_000, ball_contacts=None,
        )
        assert result.ok

    def test_confirm_mode_never_applies_the_count_mode_rules(self):
        """Metronomic timing and even splits are count-mode checks. Wall ball
        reps come from pose, which has its own integrity layer for that."""
        even = [{"t_ms": i * 1200, "hand": "left"} for i in range(40)]
        result = B.review(
            self.WALL_BALL, even, track_quality=0.55,
            duration_ms=48_000, ball_contacts=30,
        )
        assert result.ok
