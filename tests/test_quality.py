"""Form quality analysis.

The engine is fed synthetic sessions with known form characteristics -- a
deliberately shallow one, one that collapses under fatigue, one with a weak
off-hand -- and asserted to recover what was built in. That is the only way to
test a scorer without a camera and a lacrosse stick.

The false-positive tests carry as much weight as the detection ones. Telling a
14-year-old to fix an off-hand problem they do not have is worse than saying
nothing at all.
"""
from __future__ import annotations

import random

import pytest

from athleteiq.drills import get_drill
from athleteiq.quality import (
    RepFeature,
    analyze,
    offhand_deficit_threshold,
)


def build(
    n: int = 80,
    rom_mean: float = 0.47,
    rom_cv: float = 0.07,
    cycle_ms: int = 900,
    decay: float = 1.0,
    offhand_penalty: float = 0.0,
    seed: int = 1,
    handed: bool = True,
) -> list[RepFeature]:
    """A synthetic session with the requested form characteristics."""
    rng = random.Random(seed)
    t = 0
    reps = []
    for i in range(n):
        frac = i / max(1, n - 1)
        hand = ("left" if i % 2 else "right") if handed else "none"
        rom = rom_mean * (1.0 - (1.0 - decay) * frac) * (1 + rng.gauss(0, rom_cv))
        if hand == "left":
            rom *= 1 - offhand_penalty
        t += max(120, int(rng.gauss(cycle_ms, cycle_ms * 0.2)))
        reps.append(
            RepFeature(
                t_ms=t, hand=hand, confidence=0.9,
                peak=rom * 0.7, rom=max(0.01, rom),
                cycle_ms=max(80, int(rng.gauss(cycle_ms, cycle_ms * 0.18))),
            )
        )
    return reps


@pytest.fixture
def wall_ball():
    return get_drill("lax_wall_ball")


class TestScoring:
    def test_a_textbook_session_scores_near_perfect(self, wall_ball):
        report = analyze(wall_ball, build(rom_cv=0.05), dominant_hand="right")
        assert report.score >= 92

    def test_shallow_reps_are_penalised_on_depth(self, wall_ball):
        report = analyze(wall_ball, build(rom_mean=0.24), dominant_hand="right")
        depth = next(c for c in report.components if c.key == "depth")
        assert depth.score < 0.4
        assert report.score < 75

    def test_erratic_reps_are_penalised_on_consistency(self, wall_ball):
        report = analyze(wall_ball, build(rom_cv=0.40), dominant_hand="right")
        consistency = next(c for c in report.components if c.key == "consistency")
        assert consistency.score < 0.75

    def test_form_collapsing_is_penalised_on_endurance(self, wall_ball):
        report = analyze(wall_ball, build(decay=0.60), dominant_hand="right")
        endurance = next(c for c in report.components if c.key == "endurance")
        assert endurance.score < 0.3
        assert report.rom_retention < 0.75

    def test_rushing_is_penalised_on_tempo(self, wall_ball):
        report = analyze(wall_ball, build(cycle_ms=300), dominant_hand="right")
        tempo = next(c for c in report.components if c.key == "tempo")
        assert tempo.score < 0.6

    def test_one_bad_component_cannot_hide_behind_three_good_ones(self, wall_ball):
        """Geometric aggregation: a session of half reps must not score well."""
        good = analyze(wall_ball, build(rom_cv=0.05), dominant_hand="right").score
        shallow = analyze(wall_ball, build(rom_mean=0.22), dominant_hand="right").score
        assert good - shallow >= 25

    def test_score_is_bounded(self, wall_ball):
        for kwargs in (
            {"rom_cv": 0.9}, {"rom_mean": 0.01}, {"decay": 0.05},
            {"cycle_ms": 60}, {"cycle_ms": 20_000},
        ):
            report = analyze(wall_ball, build(**kwargs), dominant_hand="right")
            assert 0 <= report.score <= 100

    def test_a_short_session_is_not_scored(self, wall_ball):
        """A confident-looking score from six reps is worse than no score."""
        report = analyze(wall_ball, build(n=5), dominant_hand="right")
        assert report.score is None
        assert "clean reps" in report.coaching_note

    def test_reps_without_shape_data_are_not_scored(self, wall_ball):
        """An older client reports no range of motion; that must not read as zero."""
        reps = [RepFeature(t_ms=i * 900, hand="right") for i in range(60)]
        report = analyze(wall_ball, reps, dominant_hand="right")
        assert report.score is None
        assert report.measurable_reps == 0

    def test_a_drill_without_a_quality_spec_returns_no_score(self):
        from athleteiq.drills.catalog import WALL_BALL
        from dataclasses import replace

        drill = replace(WALL_BALL, quality=None)
        assert analyze(drill, build()).score is None


class TestOffHandDetection:
    @pytest.mark.parametrize("penalty", [0.20, 0.30, 0.45])
    def test_a_real_deficit_is_reported(self, wall_ball, penalty):
        report = analyze(wall_ball, build(offhand_penalty=penalty), dominant_hand="right")
        assert report.offhand_rom_ratio < 1 - penalty * 0.6
        assert "less range" in report.coaching_note

    @pytest.mark.parametrize("seed", range(6))
    def test_a_clean_session_never_invents_a_deficit(self, wall_ball, seed):
        """The false-positive case matters more than the detection case."""
        report = analyze(wall_ball, build(seed=seed), dominant_hand="right")
        assert "less range" not in report.coaching_note

    @pytest.mark.parametrize("seed", range(6))
    def test_a_noisy_session_does_not_invent_a_deficit(self, wall_ball, seed):
        """Two hands differ by chance when every rep varies wildly."""
        report = analyze(wall_ball, build(rom_cv=0.35, seed=seed), dominant_hand="right")
        assert "less range" not in report.coaching_note

    def test_a_large_deficit_survives_a_noisy_session(self, wall_ball):
        report = analyze(
            wall_ball, build(rom_cv=0.30, offhand_penalty=0.40), dominant_hand="right"
        )
        assert "less range" in report.coaching_note

    def test_the_deficit_is_measured_against_the_dominant_hand(self, wall_ball):
        """A lefty and a righty doing identical work get opposite readings."""
        reps = build(offhand_penalty=0.35)
        righty = analyze(wall_ball, reps, dominant_hand="right")
        lefty = analyze(wall_ball, reps, dominant_hand="left")
        assert righty.offhand_rom_ratio < 0.8    # left is weaker, and left is off-hand
        assert lefty.offhand_rom_ratio > 1.2     # left is weaker, but left is dominant

    def test_the_noise_threshold_scales_and_is_bounded(self):
        assert offhand_deficit_threshold(None) == pytest.approx(0.08)
        assert offhand_deficit_threshold(0.0) == pytest.approx(0.08)
        assert offhand_deficit_threshold(0.06) == pytest.approx(0.12)
        # Capped, so a very jittery session still surfaces a large real gap.
        assert offhand_deficit_threshold(5.0) == pytest.approx(0.25)

    def test_per_hand_scores_need_enough_reps_on_each_side(self, wall_ball):
        """All-right-handed work must not produce a phantom left-hand score."""
        reps = build(n=60)
        for rep in reps:
            rep.hand = "right"
        report = analyze(wall_ball, reps, dominant_hand="right")
        assert "left" not in report.per_hand


class TestHoldDrills:
    def test_a_steady_hold_scores_high(self):
        plank = get_drill("gen_plank")
        report = analyze(plank, [], hold_ms=118_000, duration_ms=120_000)
        assert report.score >= 95

    def test_a_sagging_hold_scores_low(self):
        plank = get_drill("gen_plank")
        report = analyze(plank, [], hold_ms=40_000, duration_ms=120_000)
        assert report.score <= 25
        assert "plank" in report.coaching_note.lower()

    def test_a_hold_with_no_duration_is_not_scored(self):
        plank = get_drill("gen_plank")
        assert analyze(plank, [], hold_ms=0, duration_ms=0).score is None


class TestCoachingNote:
    def test_the_note_names_the_weakest_component(self, wall_ball):
        report = analyze(wall_ball, build(rom_mean=0.22), dominant_hand="right")
        assert "range" in report.coaching_note.lower()

    def test_a_clean_session_gets_praise_not_a_correction(self, wall_ball):
        report = analyze(wall_ball, build(rom_cv=0.04), dominant_hand="right")
        assert "Clean session" in report.coaching_note

    def test_the_off_hand_gap_outranks_other_feedback(self, wall_ball):
        """It is the thing the product exists to surface."""
        report = analyze(
            wall_ball, build(offhand_penalty=0.40, cycle_ms=320), dominant_hand="right"
        )
        assert "less range" in report.coaching_note

    def test_every_session_gets_exactly_one_note(self, wall_ball):
        """A wall of feedback gets skimmed."""
        for kwargs in ({}, {"rom_cv": 0.4}, {"decay": 0.5}, {"offhand_penalty": 0.4}):
            note = analyze(wall_ball, build(**kwargs), dominant_hand="right").coaching_note
            assert note and note.count(".") <= 3


class TestSerialization:
    def test_the_report_is_json_safe(self, wall_ball):
        import json

        report = analyze(wall_ball, build(offhand_penalty=0.3), dominant_hand="right")
        payload = json.loads(json.dumps(report.to_dict()))
        assert payload["score"] == report.score
        assert len(payload["components"]) == 4
        assert payload["offhand_rom_ratio"] is not None
