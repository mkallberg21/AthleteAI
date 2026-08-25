"""Invariants every drill in the catalog must satisfy.

These matter because adding a drill is meant to be a data change made by
someone who is not reading the counter internals. These tests are the guardrail
that makes that safe.
"""
from __future__ import annotations

import json

import pytest

from offdays.drills import ALL_DRILLS, DRILLS_BY_KEY, LANDMARKS, get_drill
from offdays.drills.base import Metric, SignalKind


@pytest.mark.parametrize("drill", ALL_DRILLS, ids=lambda d: d.key)
class TestEveryDrill:
    def test_hysteresis_thresholds_are_ordered(self, drill):
        assert drill.counter.down_threshold < drill.counter.up_threshold

    def test_refractory_window_is_sane(self, drill):
        assert 0 < drill.counter.min_rep_ms < drill.counter.max_rep_ms

    def test_signal_references_real_landmarks(self, drill):
        names = [*drill.signal.joints]
        if drill.signal.landmark:
            names.append(drill.signal.landmark)
        if drill.signal.reference:
            names.append(drill.signal.reference)
        for name in names:
            assert name in LANDMARKS, f"{drill.key} references unknown landmark {name}"

    def test_joint_angle_signals_have_three_joints(self, drill):
        if drill.signal.kind is SignalKind.JOINT_ANGLE:
            assert len(drill.signal.joints) == 3

    def test_smoothing_is_a_valid_weight(self, drill):
        assert 0.0 < drill.signal.smoothing <= 1.0

    def test_scoring_is_non_negative(self, drill):
        assert drill.scoring.xp_per_rep >= 0
        assert drill.scoring.xp_per_minute >= 0
        assert drill.scoring.daily_rep_cap > 0

    def test_rep_drills_pay_per_rep_and_hold_drills_pay_per_minute(self, drill):
        if drill.metric is Metric.REPS:
            assert drill.scoring.xp_per_rep > 0, f"{drill.key} is a rep drill worth 0 XP"
        if drill.metric is Metric.HOLD_SECONDS:
            assert drill.scoring.xp_per_minute > 0, f"{drill.key} is a hold drill worth 0 XP"

    def test_validation_envelope_is_ordered(self, drill):
        assert drill.validation.min_reps_per_second < drill.validation.max_reps_per_second

    def test_serializes_to_json_for_the_client(self, drill):
        """The browser consumes this verbatim, so it must round-trip."""
        payload = json.loads(json.dumps(drill.to_dict()))
        assert payload["key"] == drill.key
        assert payload["signal"]["kind"] == drill.signal.kind.value
        assert payload["counter"]["down_threshold"] < payload["counter"]["up_threshold"]

    def test_has_a_setup_hint(self, drill):
        """Framing is the top cause of bad counts, so every drill must say how."""
        assert drill.setup_hint.strip(), f"{drill.key} has no setup hint"

    def test_has_a_description(self, drill):
        assert drill.description.strip()


class TestCatalog:
    def test_keys_are_unique(self):
        keys = [d.key for d in ALL_DRILLS]
        assert len(keys) == len(set(keys))

    def test_names_are_unique(self):
        names = [d.name for d in ALL_DRILLS]
        assert len(names) == len(set(names))

    def test_lookup_by_key_works(self):
        assert get_drill("lax_wall_ball").name == "Wall Ball"

    def test_unknown_key_raises_a_helpful_error(self):
        with pytest.raises(KeyError, match="known drills"):
            get_drill("no_such_drill")

    def test_catalog_covers_every_training_category(self):
        categories = {d.category.value for d in ALL_DRILLS}
        assert {"skill", "strength", "speed", "agility", "conditioning"} <= categories

    def test_handedness_is_tracked_for_the_lacrosse_skill_drills(self):
        """Off-hand attribution is the core feature; it must not regress."""
        for key in ("lax_wall_ball", "lax_quick_stick"):
            assert DRILLS_BY_KEY[key].tracks_handedness
