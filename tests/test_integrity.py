"""Plausibility checking of submitted sessions.

The client counts reps and the client is controlled by the athlete, so these
tests are the real security boundary: they check that a fabricated payload is
caught while an honest one passes untouched.
"""
from __future__ import annotations

import random

import pytest

from athleteiq.drills import get_drill
from athleteiq.integrity import RepEvent, SessionClaim, evaluate


def realistic_reps(count: int, mean_gap_ms: float = 900, jitter: float = 190, seed: int = 11):
    """A rep stream with the natural timing variance a human produces."""
    rng = random.Random(seed)
    t = 0
    reps = []
    for i in range(count):
        t += max(120, int(rng.gauss(mean_gap_ms, jitter)))
        reps.append(RepEvent(t_ms=t, hand="left" if i % 2 else "right", confidence=0.87))
    return reps


@pytest.fixture
def wall_ball():
    return get_drill("lax_wall_ball")


class TestHonestSessions:
    def test_a_normal_session_counts_cleanly(self, wall_ball):
        reps = realistic_reps(120)
        claim = SessionClaim("lax_wall_ball", reps[-1].t_ms + 800, reps, mean_confidence=0.87)
        result = evaluate(claim, wall_ball)
        assert result.status == "counted"
        assert result.score > 0.9
        assert result.reps_total == 120

    def test_hand_attribution_is_preserved(self, wall_ball):
        reps = realistic_reps(100)
        claim = SessionClaim("lax_wall_ball", reps[-1].t_ms + 500, reps, mean_confidence=0.9)
        result = evaluate(claim, wall_ball)
        assert result.reps_left == 50 and result.reps_right == 50

    @pytest.mark.parametrize("count", [20, 60, 150, 400])
    def test_a_range_of_honest_volumes_all_count(self, wall_ball, count):
        reps = realistic_reps(count)
        claim = SessionClaim("lax_wall_ball", reps[-1].t_ms + 600, reps, mean_confidence=0.86)
        assert evaluate(claim, wall_ball).status == "counted"


class TestFabricatedSessions:
    def test_perfectly_regular_timing_is_flagged(self, wall_ball):
        """A metronomic stream is the signature of a generated payload."""
        reps = [RepEvent(t_ms=i * 800, hand="right", confidence=0.9) for i in range(1, 100)]
        claim = SessionClaim("lax_wall_ball", 100 * 800, reps, mean_confidence=0.9)
        result = evaluate(claim, wall_ball)
        assert result.status in ("review", "rejected")
        assert any("even" in n for n in result.notes)

    def test_physically_impossible_rate_is_rejected(self, wall_ball):
        reps = realistic_reps(500, mean_gap_ms=40, jitter=8)
        claim = SessionClaim("lax_wall_ball", 20_000, reps, mean_confidence=0.9)
        result = evaluate(claim, wall_ball)
        assert result.status == "rejected"

    def test_reps_after_the_session_ended_are_rejected(self, wall_ball):
        reps = realistic_reps(50)
        reps.append(RepEvent(t_ms=10_000_000, hand="right", confidence=0.9))
        claim = SessionClaim("lax_wall_ball", reps[0].t_ms + 30_000, reps, mean_confidence=0.9)
        assert evaluate(claim, wall_ball).status == "rejected"

    def test_negative_timestamps_are_rejected(self, wall_ball):
        claim = SessionClaim(
            "lax_wall_ball", 60_000, [RepEvent(t_ms=-5, hand="right")], mean_confidence=0.9
        )
        assert evaluate(claim, wall_ball).status == "rejected"

    def test_zero_duration_is_rejected(self, wall_ball):
        claim = SessionClaim("lax_wall_ball", 0, realistic_reps(50), mean_confidence=0.9)
        assert evaluate(claim, wall_ball).status == "rejected"

    def test_claimed_hold_longer_than_the_session_is_rejected(self):
        plank = get_drill("gen_plank")
        claim = SessionClaim("gen_plank", 30_000, [], hold_ms=600_000, mean_confidence=0.9)
        assert evaluate(claim, plank).status == "rejected"


class TestQualityDegradation:
    @pytest.mark.parametrize(
        "confidence,expected",
        [
            (0.90, "counted"),   # well framed
            (0.55, "counted"),   # exactly at the floor
            (0.50, "counted"),   # marginal, still trusted
            (0.45, "counted"),   # borderline -- an athlete should not lose this
            (0.40, "review"),    # too little of the body visible to trust
            (0.20, "review"),    # unusable
        ],
    )
    def test_confidence_curve_holds_only_genuinely_unusable_sessions(
        self, wall_ball, confidence, expected
    ):
        """Framing has to be badly wrong before a kid's work gets held.

        This curve is the difference between 'refilm that one' and a teammate
        being told their real work does not count.
        """
        reps = realistic_reps(120)
        claim = SessionClaim(
            "lax_wall_ball", reps[-1].t_ms + 700, reps, mean_confidence=confidence
        )
        assert evaluate(claim, wall_ball).status == expected

    def test_low_pose_confidence_costs_score(self, wall_ball):
        reps = realistic_reps(100)
        good = SessionClaim("lax_wall_ball", reps[-1].t_ms + 500, reps, mean_confidence=0.9)
        poor = SessionClaim("lax_wall_ball", reps[-1].t_ms + 500, reps, mean_confidence=0.25)
        assert evaluate(poor, wall_ball).score < evaluate(good, wall_ball).score

    def test_too_few_reps_is_penalised(self, wall_ball):
        reps = realistic_reps(3)
        claim = SessionClaim("lax_wall_ball", 20_000, reps, mean_confidence=0.9)
        result = evaluate(claim, wall_ball)
        assert result.status != "counted"

    def test_a_session_shorter_than_the_minimum_is_penalised(self, wall_ball):
        reps = realistic_reps(20, mean_gap_ms=200, jitter=60)
        claim = SessionClaim("lax_wall_ball", 5_000, reps, mean_confidence=0.9)
        assert evaluate(claim, wall_ball).status != "counted"

    def test_every_penalty_carries_an_explanation(self, wall_ball):
        """A held session must always tell the coach why."""
        reps = [RepEvent(t_ms=i * 800, hand="right", confidence=0.4) for i in range(1, 60)]
        claim = SessionClaim("lax_wall_ball", 60 * 800, reps, mean_confidence=0.3)
        result = evaluate(claim, wall_ball)
        assert result.status != "counted"
        assert result.notes and all(isinstance(n, str) and n for n in result.notes)

    def test_score_is_always_within_bounds(self, wall_ball):
        """No combination of penalties may push the score outside 0..1."""
        cases = [
            SessionClaim("lax_wall_ball", 1, [], mean_confidence=0.0),
            SessionClaim("lax_wall_ball", 10**9, realistic_reps(5), mean_confidence=0.0),
            SessionClaim("lax_wall_ball", 60_000, realistic_reps(1000, 5, 1), mean_confidence=0.01),
        ]
        for claim in cases:
            assert 0.0 <= evaluate(claim, wall_ball).score <= 1.0
