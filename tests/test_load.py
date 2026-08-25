"""Training load monitoring and overuse protection.

The tests that matter most here are the ones asserting the system stays quiet:
a false alarm about a load spike trains coaches to ignore the whole feature, and
the athlete it wrongly benches is the one who was training properly.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from offdays.config import CONFIG
from offdays.load import DayLoad, Zone, analyze, session_load

TODAY = date(2026, 8, 23)


def series(pattern: list[float], throws_per_load: float = 3.0) -> list[DayLoad]:
    """Daily loads, oldest first, ending today."""
    n = len(pattern)
    return [
        DayLoad(
            day=TODAY - timedelta(days=n - 1 - i),
            load=value,
            throws=int(value * throws_per_load),
            sessions=1 if value > 0 else 0,
        )
        for i, value in enumerate(pattern)
    ]


STEADY = [40, 40, 0, 45, 40, 0, 42] * 6


class TestSessionLoad:
    def test_load_differs_by_drill(self):
        """200 wall balls and 200 burpees are not the same week's work."""
        wall, _ = session_load("lax_wall_ball", 200)
        burpee, _ = session_load("gen_burpee", 200)
        assert burpee > wall * 3

    def test_only_throwing_drills_count_throws(self):
        assert session_load("lax_wall_ball", 100)[1] == 100
        assert session_load("gen_squat", 100)[1] == 0

    def test_hold_drills_load_by_time(self):
        assert session_load("gen_plank", 0, hold_ms=180_000)[0] > 0

    def test_an_unknown_drill_contributes_nothing(self):
        assert session_load("not_a_drill", 500) == (0.0, 0)


class TestWorkloadRatio:
    def test_steady_training_sits_in_the_optimal_zone(self):
        state = analyze(series(STEADY), today=TODAY)
        assert state.zone == Zone.OPTIMAL
        assert 0.8 <= state.acwr <= 1.3

    def test_a_sharp_spike_is_flagged(self):
        pattern = [20, 20, 0, 22, 20, 0, 21] * 5 + [90, 95, 85, 100, 90, 95, 88]
        state = analyze(series(pattern), today=TODAY)
        assert state.zone == Zone.HIGH
        assert any(a.code == "load_spike" for a in state.advisories)
        assert any(a.level == "warning" for a in state.advisories)

    def test_returning_from_a_layoff_is_flagged(self):
        """The classic re-injury pattern: picking up where you left off."""
        pattern = [50, 55, 0, 52, 50, 0, 48] * 2 + [0] * 14 + [55, 60, 0, 58, 55, 0, 52]
        state = analyze(series(pattern), today=TODAY)
        assert state.zone in (Zone.ELEVATED, Zone.HIGH)

    def test_tapering_off_is_reported_without_alarm(self):
        pattern = [60, 60, 0, 65, 60, 0, 62] * 5 + [10, 0, 0, 12, 0, 0, 8]
        state = analyze(series(pattern), today=TODAY)
        assert state.zone == Zone.DETRAINING
        assert all(a.level == "info" for a in state.advisories)

    def test_a_new_athlete_gets_no_ratio_at_all(self):
        """Comparing a first week against nothing produces alarming nonsense."""
        state = analyze(series([40, 45, 0, 42, 40]), today=TODAY)
        assert state.acwr is None
        assert state.zone == Zone.UNKNOWN
        assert any(a.code == "building_baseline" for a in state.advisories)
        assert all(a.level == "info" for a in state.advisories)

    def test_no_history_is_handled(self):
        state = analyze([], today=TODAY)
        assert state.acwr is None
        assert not state.needs_attention

    @pytest.mark.parametrize("weeks", [3, 4, 6, 10])
    def test_consistent_training_never_raises_an_alarm(self, weeks):
        """The false-positive case: a false alarm teaches coaches to ignore this."""
        state = analyze(series([40, 40, 0, 45, 40, 0, 42] * weeks), today=TODAY)
        assert not state.needs_attention


class TestRestDays:
    def test_consecutive_days_are_counted_to_the_last_training_day(self):
        """Not having trained yet today must not read as a streak of zero."""
        state = analyze(series([30] * 8 + [0]), today=TODAY)
        assert state.consecutive_days == 8
        assert state.days_since_training == 1

    def test_a_long_run_without_rest_is_flagged(self):
        state = analyze(series([30] * 20), today=TODAY)
        assert state.rest_recommended
        assert any(a.code == "no_rest_day" for a in state.advisories)

    def test_a_very_long_run_escalates_to_a_warning(self):
        state = analyze(series([30] * 30), today=TODAY)
        rest = next(a for a in state.advisories if a.code == "no_rest_day")
        assert rest.level == "warning"

    def test_normal_training_with_rest_days_is_not_flagged(self):
        state = analyze(series(STEADY), today=TODAY)
        assert not state.rest_recommended

    def test_rest_is_not_suggested_to_someone_already_resting(self):
        """They stopped a week ago; telling them to rest is noise."""
        state = analyze(series([30] * 14 + [0] * 7), today=TODAY)
        assert not state.rest_recommended
        assert state.days_since_training == 7


class TestMonotony:
    def test_identical_load_every_day_is_flagged(self):
        """Zero variance is maximum monotony, not an unmeasurable one."""
        state = analyze(series([40] * 28), today=TODAY)
        assert state.monotony is not None
        assert any(a.code == "monotony" for a in state.advisories)

    def test_hard_easy_variation_is_not_flagged(self):
        state = analyze(series(STEADY), today=TODAY)
        assert not any(a.code == "monotony" for a in state.advisories)


class TestThrowingVolume:
    def test_a_throwing_spike_is_flagged(self):
        pattern = [20] * 21 + [90] * 7
        state = analyze(series(pattern), today=TODAY)
        assert state.weekly_throws > 0
        assert any(a.code == "throw_spike" for a in state.advisories)

    def test_a_small_baseline_does_not_produce_a_percentage_alarm(self):
        """Going from 3 throws to 9 is not a 200% danger signal."""
        pattern = [0] * 21 + [1, 0, 0, 1, 0, 0, 2]
        state = analyze(series(pattern), today=TODAY)
        assert not any(a.code == "throw_spike" for a in state.advisories)


class TestAdvisories:
    def test_advisories_are_never_diagnoses(self):
        """Wording matters: this is a prompt to a coach, not a medical claim."""
        pattern = [20] * 21 + [95] * 7
        state = analyze(series(pattern), today=TODAY, age=13)
        banned = ("injured", "injury risk of", "diagnos", "must not", "forbidden")
        for advisory in state.advisories:
            lowered = advisory.message.lower()
            assert not any(word in lowered for word in banned), advisory.message

    def test_every_advisory_carries_a_message(self):
        for pattern in ([40] * 28, [20] * 21 + [95] * 7, [30] * 20, []):
            for advisory in analyze(series(pattern), today=TODAY).advisories:
                assert advisory.message.strip()
                assert advisory.level in ("info", "caution", "warning")

    def test_the_age_guideline_admits_what_it_cannot_see(self):
        state = analyze(series([40] * 28), today=TODAY, age=13)
        note = next((a for a in state.advisories if a.code == "age_volume"), None)
        if note is not None:
            assert "only sees" in note.message

    def test_the_state_serializes(self):
        import json

        state = analyze(series([20] * 21 + [95] * 7), today=TODAY, age=14)
        payload = json.loads(json.dumps(state.to_dict()))
        assert payload["zone"] == state.zone
        assert len(payload["advisories"]) == len(state.advisories)


class TestConfigSanity:
    def test_the_optimal_band_is_ordered(self):
        cfg = CONFIG.load
        assert cfg.detraining_below < cfg.optimal_low < cfg.optimal_high < cfg.elevated_high

    def test_rest_thresholds_are_ordered(self):
        assert CONFIG.load.rest_day_after < CONFIG.load.rest_day_urgent

    def test_the_acute_window_is_shorter_than_the_chronic_one(self):
        assert CONFIG.load.acute_days < CONFIG.load.chronic_days
