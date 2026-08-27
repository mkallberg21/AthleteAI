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


class TestNoDrillOutEarnsOneItCannotBeToldApartFrom:
    """The catalogue must not pay for a name the app cannot verify.

    Several drills share one signal and one set of thresholds that nest inside
    each other -- the whole wall-ball family reads as the top hand rising above
    the shoulder line and coming back, whether the rep was a plain wall ball, a
    split dodge or a behind-the-back. That is not a tuning problem: with one
    camera and no stick in the model, the information is not in the frame, and
    no future work puts it there.

    What made it a defect rather than a caveat was the reward. While the fancier
    patterns paid more per rep, the highest-earning thing an athlete could do was
    pick the fanciest name in the menu and then do the easy movement -- and they
    would not even be cheating, because the app told them it counted.

    So the rule is: if doing drill X necessarily satisfies drill Y's thresholds,
    Y must not pay more than X. Differentiation has to come from something
    actually measured -- which hand was on top, and how well the reps were
    shaped.
    """

    def _pose_counted(self):
        # Hold drills score time, and count-mode ball drills never feed the pose
        # counter at all -- their reps come from ball contacts, so their pose
        # thresholds decide nothing.
        return [
            d for d in ALL_DRILLS
            if d.metric is not Metric.HOLD_SECONDS
            and not (d.ball is not None and d.ball.counts)
        ]

    def _signal_of(self, drill):
        s = drill.signal
        return (s.kind, s.joints, s.landmark, s.reference)

    def _subsumes(self, outer, inner):
        """Whether every rep of `outer` also fires `inner`."""
        return (inner.counter.down_threshold >= outer.counter.down_threshold
                and inner.counter.up_threshold <= outer.counter.up_threshold)

    def test_a_drill_never_out_earns_one_that_subsumes_it(self):
        drills = self._pose_counted()
        offences = []
        for outer in drills:
            for inner in drills:
                if inner is outer:
                    continue
                if self._signal_of(inner) != self._signal_of(outer):
                    continue
                if not self._subsumes(outer, inner):
                    continue
                if inner.scoring.xp_per_rep > outer.scoring.xp_per_rep:
                    offences.append(
                        f"{inner.key} pays {inner.scoring.xp_per_rep} but fires on "
                        f"any {outer.key} rep ({outer.scoring.xp_per_rep})"
                    )
        assert offences == [], "; ".join(offences)

    def test_an_unverifiable_pattern_never_out_earns_a_verifiable_one(self):
        # Belt and braces on the same idea, in case thresholds are retuned so
        # they no longer nest: a pattern the app cannot confirm must never be
        # the best-paying thing on its own signal.
        by_signal = {}
        for drill in self._pose_counted():
            by_signal.setdefault(self._signal_of(drill), []).append(drill)
        for family in by_signal.values():
            if len(family) < 2:
                continue
            best_verified = max(
                (d.scoring.xp_per_rep for d in family if d.pattern_verified),
                default=None,
            )
            if best_verified is None:
                continue
            for drill in family:
                if not drill.pattern_verified:
                    assert drill.scoring.xp_per_rep <= best_verified, drill.key

    def test_the_wall_ball_family_all_pays_the_same(self):
        family = [d for d in ALL_DRILLS
                  if d.signal.kind is SignalKind.WALL_BALL_CYCLE]
        assert len(family) >= 8
        rates = {d.scoring.xp_per_rep for d in family}
        assert rates == {1.0}, f"wall ball rates drifted apart: {rates}"

    def test_the_unverifiable_patterns_are_marked_as_such(self):
        # If one of these ever becomes genuinely detectable, this test is the
        # thing that has to be edited deliberately rather than drifting.
        unverified = {d.key for d in ALL_DRILLS if not d.pattern_verified}
        assert unverified == {
            "lax_wall_ball_one_hand", "lax_wall_ball_cross",
            "lax_wall_ball_btb", "lax_wall_ball_split", "gen_lunge",
        }, unverified

    def test_the_off_hand_premium_survives_and_is_measured(self):
        # The premium moved from the drill's name to the hand actually on top,
        # which is the one thing here the camera really does see. It must still
        # exist, or levelling the base rates quietly deleted the incentive to do
        # the hardest work in the routine.
        from offdays.config import CONFIG
        assert CONFIG.scoring.offhand_bonus_multiplier > 1.0
        for drill in ALL_DRILLS:
            if drill.signal.kind is SignalKind.WALL_BALL_CYCLE:
                assert drill.tracks_handedness, drill.key
