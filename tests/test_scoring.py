"""Scoring, levelling, streak, and badge behaviour."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from offdays.drills import get_drill
from offdays.integrity import IntegrityResult
from offdays.scoring import (
    AthleteStats,
    compute_streak,
    earned_badges,
    level_for_xp,
    level_progress,
    score_session,
    xp_for_level,
)


def counted(reps_total: int, left: int = 0, right: int = 0) -> IntegrityResult:
    return IntegrityResult(
        score=1.0, status="counted", reps_total=reps_total,
        reps_left=left, reps_right=right,
    )


class TestLevels:
    def test_level_one_starts_at_zero(self):
        assert xp_for_level(1) == 0
        assert level_for_xp(0) == 1

    def test_levels_are_strictly_increasing(self):
        thresholds = [xp_for_level(n) for n in range(1, 40)]
        assert thresholds == sorted(thresholds)
        assert len(set(thresholds)) == len(thresholds)

    def test_level_curve_is_superlinear(self):
        """Each level must cost more than the one before it."""
        gaps = [xp_for_level(n + 1) - xp_for_level(n) for n in range(1, 25)]
        assert all(b > a for a, b in zip(gaps, gaps[1:]))

    def test_level_for_xp_is_inverse_of_xp_for_level(self):
        for n in range(1, 30):
            assert level_for_xp(xp_for_level(n)) == n
            assert level_for_xp(xp_for_level(n) - 1) == n - 1 or n == 1

    def test_progress_fraction_bounded(self):
        for xp in (0, 1, 299, 300, 5_000, 100_000):
            frac = level_progress(xp).fraction
            assert 0.0 <= frac <= 1.0


class TestSessionScoring:
    def test_rejected_session_earns_nothing(self):
        drill = get_drill("lax_wall_ball")
        verdict = IntegrityResult(score=0.1, status="rejected", reps_total=500)
        assert score_session(drill, verdict).total == 0

    def test_review_session_earns_nothing_until_approved(self):
        drill = get_drill("lax_wall_ball")
        verdict = IntegrityResult(score=0.5, status="review", reps_total=200)
        assert score_session(drill, verdict).total == 0

    def test_offhand_reps_pay_more_than_dominant(self):
        drill = get_drill("lax_wall_ball")
        righty_offhand = score_session(drill, counted(100, left=100), dominant_hand="right")
        righty_dominant = score_session(drill, counted(100, right=100), dominant_hand="right")
        assert righty_offhand.total > righty_dominant.total

    def test_offhand_is_relative_to_the_athletes_dominant_hand(self):
        """A lefty must be credited for right-handed work, not left."""
        drill = get_drill("lax_wall_ball")
        lefty = score_session(drill, counted(100, right=100), dominant_hand="left")
        righty = score_session(drill, counted(100, right=100), dominant_hand="right")
        assert lefty.offhand_bonus > 0
        assert righty.offhand_bonus == 0

    def test_balanced_session_earns_the_balance_bonus(self):
        drill = get_drill("lax_wall_ball")
        balanced = score_session(drill, counted(100, left=50, right=50), dominant_hand="right")
        lopsided = score_session(drill, counted(100, left=2, right=98), dominant_hand="right")
        assert balanced.balance_bonus > 0
        assert lopsided.balance_bonus == 0

    def test_diminishing_returns_within_a_session(self):
        """Doubling reps must not double XP once past the threshold."""
        drill = get_drill("lax_wall_ball")
        at = drill.scoring.diminishing_after_reps
        base = score_session(drill, counted(at)).base
        double = score_session(drill, counted(at * 2)).base
        assert double < base * 2

    def test_daily_cap_is_enforced(self):
        from offdays.config import CONFIG

        drill = get_drill("lax_wall_ball")
        spent = CONFIG.scoring.daily_xp_cap - 10
        result = score_session(drill, counted(500), xp_already_today=spent)
        assert result.total == 10

    def test_daily_cap_never_produces_negative_xp(self):
        from offdays.config import CONFIG

        drill = get_drill("lax_wall_ball")
        result = score_session(drill, counted(500), xp_already_today=CONFIG.scoring.daily_xp_cap * 2)
        assert result.total == 0

    def test_hold_drill_scores_on_time_not_reps(self):
        plank = get_drill("gen_plank")
        result = score_session(plank, counted(0), hold_ms=120_000)
        assert result.total > 0

    def test_breakdown_lines_sum_to_total(self):
        """The athlete-facing itemization must actually add up."""
        drill = get_drill("lax_wall_ball")
        result = score_session(drill, counted(100, left=45, right=55), dominant_hand="right")
        assert sum(amount for _, amount in result.lines) == result.total


class TestStreaks:
    def test_no_days_is_no_streak(self):
        state = compute_streak([], date(2026, 8, 23))
        assert state.current == 0 and state.longest == 0

    def test_consecutive_days_accumulate(self):
        today = date(2026, 8, 23)
        days = [today - timedelta(days=i) for i in range(10)]
        assert compute_streak(days, today).current == 10

    def test_one_missed_day_is_forgiven(self):
        """A single gap must freeze the streak, not reset it."""
        today = date(2026, 8, 23)
        days = [today - timedelta(days=i) for i in (0, 1, 3, 4, 5)]
        assert compute_streak(days, today).current == 5

    def test_two_missed_days_breaks_the_streak(self):
        today = date(2026, 8, 23)
        days = [today - timedelta(days=i) for i in (4, 5, 6)]
        assert compute_streak(days, today).current == 0

    def test_longest_survives_a_broken_streak(self):
        today = date(2026, 8, 23)
        days = [today - timedelta(days=i) for i in (20, 21, 22, 23, 24, 0)]
        state = compute_streak(days, today)
        assert state.current == 1
        assert state.longest >= 5

    def test_at_risk_flags_a_grace_day_in_use(self):
        today = date(2026, 8, 23)
        days = [today - timedelta(days=i) for i in (1, 2, 3)]
        assert compute_streak(days, today).at_risk is True

    def test_duplicate_days_do_not_inflate_a_streak(self):
        today = date(2026, 8, 23)
        days = [today] * 10
        assert compute_streak(days, today).current == 1


class TestBadges:
    def test_badge_award_is_idempotent(self):
        stats = AthleteStats(session_count=1, wall_ball_reps=150, total_xp=200)
        assert earned_badges(stats) == earned_badges(stats)

    def test_thresholds_gate_correctly(self):
        assert "wall_100" not in earned_badges(AthleteStats(wall_ball_reps=99))
        assert "wall_100" in earned_badges(AthleteStats(wall_ball_reps=100))

    def test_higher_tiers_include_lower_ones(self):
        earned = earned_badges(AthleteStats(wall_ball_reps=10_000))
        assert {"wall_100", "wall_1000", "wall_10000"} <= set(earned)

    def test_empty_stats_earn_nothing(self):
        assert earned_badges(AthleteStats()) == []
