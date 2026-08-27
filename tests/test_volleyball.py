"""Volleyball, built to the depth lacrosse has.

Volleyball is unusually good for this catalogue, because its three basic skills
contact the ball in three different places: a set above the head, a forearm pass
below the shoulders, a hit off one hand overhead. Two of those are separated by
the hands gate and the third by hand attribution -- so every drill that pays
more than the baseline has earned it on something checkable rather than on a
name.

The exception is `vb_set_wall`, which is marked unverifiable and paid the
baseline. It is here to prove the guard works rather than to be got away with.
"""

from __future__ import annotations

import pytest

from offdays import curriculum, film, technique, transfer
from offdays.drills import ALL_DRILLS, get_drill
from offdays.drills.base import Metric, SignalKind
from offdays.positions import ALL_POSITIONS

VB = [d for d in ALL_DRILLS if d.sport == "volleyball"]
VB_KEYS = [d.key for d in VB]


class TestTheDrillSet:
    def test_there_are_enough_to_be_a_programme(self):
        assert len(VB) >= 6, VB_KEYS

    def test_it_covers_the_three_basic_skills(self):
        # Pass, set and hit. A volleyball programme without all three is a
        # setting drill with company.
        assert {"vb_pass", "vb_set", "vb_serve"} <= set(VB_KEYS)

    def test_it_covers_jumping_as_well_as_ball_work(self):
        # Volleyball is a jumping sport, and the jumping is where it hurts
        # people. A ball-only catalogue would miss the half that matters.
        jumps = [d for d in VB if d.ball is None]
        assert len(jumps) >= 3, [d.key for d in jumps]

    @pytest.mark.parametrize("drill", VB, ids=VB_KEYS)
    def test_every_drill_has_cues_and_transfers(self, drill):
        assert technique.cues_for(drill.key), drill.key
        assert transfer.for_drill(drill.key), drill.key

    @pytest.mark.parametrize("drill", VB, ids=VB_KEYS)
    def test_every_drill_serializes(self, drill):
        import json
        json.dumps(drill.to_dict())


class TestOneBallShared:
    def test_every_ball_drill_uses_the_same_ball(self):
        balls = [d.ball for d in VB if d.ball]
        assert len(balls) >= 4
        for ball in balls:
            assert ball.diameter_cm == 21.0
            assert ball.detector == "vision"


class TestTheHandsGate:
    """What makes a set and a forearm pass tellable apart.

    Without it they are the same event to the detector -- the wrist is the
    nearest listed part either way -- and the catalogue would be paying for a
    name again.
    """

    def test_a_set_requires_the_hands_above_the_shoulders(self):
        assert get_drill("vb_set").ball.hands == "above_shoulders"

    def test_a_pass_requires_them_below(self):
        assert get_drill("vb_pass").ball.hands == "below_shoulders"

    def test_the_two_gates_are_mutually_exclusive(self):
        # The whole point: no single contact can satisfy both, so a rep counts
        # for one skill or the other and never for both.
        a = get_drill("vb_set").ball.hands
        b = get_drill("vb_pass").ball.hands
        assert {a, b} == {"above_shoulders", "below_shoulders"}

    def test_an_unknown_gate_is_refused(self):
        from offdays.drills.base import BallSpec
        with pytest.raises(ValueError):
            BallSpec(hands="somewhere")

    def test_the_gate_reaches_the_browser(self):
        assert get_drill("vb_set").to_dict()["ball"]["hands"] == "above_shoulders"


class TestPayingOnlyForWhatIsChecked:
    def test_the_serve_earns_its_premium_on_three_checkable_things(self):
        serve = get_drill("vb_serve")
        base = get_drill("vb_set")
        assert serve.scoring.xp_per_rep > base.scoring.xp_per_rep
        assert serve.ball.hands == "above_shoulders"
        assert serve.ball.attribute_side
        assert serve.ball.alternation == "same_hand"

    def test_wall_setting_is_marked_unverifiable_and_paid_the_baseline(self):
        wall = get_drill("vb_set_wall")
        assert not wall.pattern_verified
        assert wall.scoring.xp_per_rep <= get_drill("vb_set").scoring.xp_per_rep

    def test_wall_setting_still_has_one_thing_that_separates_it(self):
        # A rate floor. Wall setting is quick by nature, and a slow rally
        # against a wall is just setting to yourself.
        wall = get_drill("vb_set_wall")
        assert wall.validation.min_reps_per_second > get_drill("vb_set").validation.min_reps_per_second

    def test_the_arm_swing_pays_the_same_as_the_basketball_shot(self):
        # Both are one-armed overhead extensions and the elbow angle cannot
        # tell them apart. The signal generalises across the sports, and so
        # does the ambiguity -- paying one more would be paying for a name.
        assert (get_drill("vb_arm_swing").scoring.xp_per_rep
                == get_drill("bkb_form_shot").scoring.xp_per_rep)


class TestTheLoadModelTellsTheTruth:
    """Volleyball is where this model has the most to say.

    A serve and an arm swing are the same overhead mechanism a pitch count
    exists to watch, and the approach jump is the landing volume behind
    jumper's knee -- the two injuries this sport hands teenagers.
    """

    def test_serving_and_swinging_count_as_throwing(self):
        for key in ("vb_serve", "vb_arm_swing"):
            assert get_drill(key).load.throws_per_rep == 1.0, key
            assert get_drill(key).load.tissue.value == "throwing", key

    def test_nothing_else_in_the_sport_does(self):
        for drill in VB:
            if drill.key in ("vb_serve", "vb_arm_swing"):
                continue
            assert drill.load.throws_per_rep == 0.0, drill.key

    def test_the_approach_jump_is_the_heaviest_landing_in_the_catalogue(self):
        # Heaviest *landing*, not heaviest rep -- a pull-up costs more and is
        # an upper-body cost. What matters here is that nothing else lands
        # harder, because landing volume is what jumper's knee is made of.
        approach = get_drill("vb_approach")
        assert approach.load.tissue.value == "lower_body"
        others = [
            d.load.load_per_rep for d in ALL_DRILLS
            if d.key != "vb_approach" and d.load.tissue.value == "lower_body"
        ]
        assert approach.load.load_per_rep > max(others), max(others)

    def test_the_jumping_drills_are_capped_tightly(self):
        # Landing volume is the thing to limit, and a daily cap is the only
        # place the catalogue can say so.
        for key in ("vb_approach", "vb_block_jump"):
            assert get_drill(key).scoring.daily_rep_cap <= 200, key


class TestThePositionPlans:
    def _vb(self):
        return [p for p in ALL_POSITIONS if p.sport == "volleyball"]

    def test_every_plan_leads_on_volleyball(self):
        by = {d.key: d for d in ALL_DRILLS}
        for pos in self._vb():
            own = sum(v for k, v in pos.emphasis.items()
                      if by[k].sport == "volleyball")
            assert own >= 0.40, (pos.key, own)

    def test_everybody_passes_and_everybody_serves(self):
        for pos in self._vb():
            assert pos.emphasis.get("vb_pass", 0) > 0, pos.key
            assert pos.emphasis.get("vb_serve", 0) > 0, pos.key

    def test_the_libero_leads_on_passing(self):
        libero = next(p for p in self._vb() if p.key == "libero")
        top = max(libero.emphasis.items(), key=lambda kv: kv[1])
        assert top[0] == "vb_pass", top

    def test_the_libero_never_hits(self):
        # The one position that does not attack, so prescribing an approach or
        # an arm swing would be prescribing somebody else's practice.
        libero = next(p for p in self._vb() if p.key == "libero")
        assert "vb_approach" not in libero.emphasis
        assert "vb_arm_swing" not in libero.emphasis

    def test_the_middle_leads_on_blocking(self):
        middle = next(p for p in self._vb() if p.key == "middle")
        top = max(middle.emphasis.items(), key=lambda kv: kv[1])
        assert top[0] == "vb_block_jump", top

    def test_serving_stays_modest_everywhere(self):
        # It is the one action in this sport on the throwing axis. A plan that
        # made it the main event would be a plan that hurts shoulders.
        for pos in self._vb():
            assert pos.emphasis.get("vb_serve", 0) <= 0.12, pos.key

    def test_every_plan_sums_to_one(self):
        for pos in self._vb():
            assert abs(sum(pos.emphasis.values()) - 1.0) < 1e-9, pos.key


class TestTheFilmCurriculum:
    TOPICS = curriculum.topics_for("volleyball")

    def test_there_is_one(self):
        assert len(self.TOPICS) >= 12

    def test_every_topic_fits_its_age_ceiling(self):
        for topic in self.TOPICS:
            band = film.band_for(topic.min_age)
            assert topic.target_s <= band.clip_max_s, (topic.key, topic.target_s)

    def test_the_youngest_band_gets_something(self):
        assert [t for t in self.TOPICS if t.min_age == 0]

    def test_every_topic_carries_a_question_with_its_reasoning(self):
        for topic in self.TOPICS:
            assert topic.ask.prompt.endswith("?"), topic.key
            assert len(topic.ask.options) >= 3, topic.key
            assert 0 <= topic.ask.answer < len(topic.ask.options), topic.key
            assert len(topic.ask.because) > 40, topic.key

    def test_every_topic_says_what_footage_to_find(self):
        for topic in self.TOPICS:
            assert len(topic.find) > 40, topic.key

    def test_no_topic_ships_a_video_id(self):
        blob = " ".join(t.find + t.title for t in self.TOPICS).lower()
        for banned in ("youtu.be", "youtube.com", "watch?v="):
            assert banned not in blob

    def test_no_topic_reads_like_a_highlight_reel(self):
        for topic in self.TOPICS:
            assert film.looks_like_highlights(topic.title) is None, topic.key

    def test_it_covers_both_sides_of_the_net(self):
        focuses = {t.focus for t in self.TOPICS}
        assert focuses & {"Blocking", "Team defence"}
        assert focuses & {"Team offence", "Attacking", "Serving"}

    def test_the_back_row_gets_something_of_its_own(self):
        assert any(len(t.positions) < 4 for t in self.TOPICS)

    def test_keys_stay_unique_across_every_sport(self):
        keys = [t.key for ts in curriculum.BY_SPORT.values() for t in ts]
        assert len(keys) == len(set(keys))

    def test_three_sports_now_have_one(self):
        assert set(curriculum.BY_SPORT) >= {"lacrosse", "basketball", "volleyball"}
