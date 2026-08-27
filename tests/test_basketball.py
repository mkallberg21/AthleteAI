"""Basketball, built to the depth lacrosse has.

The reason this file exists separately is the lesson the wall-ball family
taught: a catalogue that pays more for a fancier name than the app can verify
is worse than a catalogue with fewer drills. Basketball was built after that
lesson rather than before it, so every variant here either differs in something
checkable -- the hands alternate, the hands do not, the tempo has a floor a slow
dribble cannot clear -- or is marked unverifiable and paid the plain rate.

These tests are the thing that keeps that true as the catalogue grows.
"""

from __future__ import annotations

import random

import pytest

from offdays import ball as ball_mod
from offdays import curriculum, film, technique, transfer
from offdays.drills import ALL_DRILLS, get_drill
from offdays.drills.base import Metric
from offdays.positions import ALL_POSITIONS

BKB = [d for d in ALL_DRILLS if d.sport == "basketball"]
BKB_KEYS = [d.key for d in BKB]


class TestTheDrillSet:
    def test_there_are_enough_to_be_a_programme(self):
        # Lacrosse has eleven. Below about six a "sport" is a token drill and a
        # position plan made of push-ups.
        assert len(BKB) >= 6, BKB_KEYS

    def test_it_covers_more_than_one_kind_of_work(self):
        # All-ball-handling would leave a plan that is really one drill with
        # six names, which is the shape of the problem this was built to avoid.
        assert {d.metric for d in BKB} >= {Metric.REPS, Metric.HOLD_SECONDS}

    @pytest.mark.parametrize("drill", BKB, ids=BKB_KEYS)
    def test_every_drill_serializes_for_the_browser(self, drill):
        import json
        json.dumps(drill.to_dict())

    @pytest.mark.parametrize("drill", BKB, ids=BKB_KEYS)
    def test_every_drill_has_cues_and_transfers(self, drill):
        assert technique.cues_for(drill.key), drill.key
        assert transfer.for_drill(drill.key), drill.key


class TestOneBallShared:
    """Same discipline lacrosse got: a basketball is a basketball."""

    def test_every_ball_drill_uses_the_same_ball(self):
        balls = [d.ball for d in BKB if d.ball]
        assert len(balls) >= 5
        for ball in balls:
            assert ball.diameter_cm == 23.0
            assert ball.colour == "basketball"
            assert ball.detector == "vision"

    def test_the_size_prior_is_what_makes_the_detector_work(self):
        # A drifted diameter silently stops the detector's strongest filter
        # from matching, and nothing else in the system would notice.
        sizes = {d.ball.diameter_cm for d in BKB if d.ball}
        assert sizes == {23.0}, sizes


class TestPayingOnlyForWhatIsChecked:
    def _pose_pairs(self):
        pose = [d for d in BKB
                if d.metric is not Metric.HOLD_SECONDS
                and not (d.ball and d.ball.counts)]
        return pose

    def test_the_one_unverifiable_pattern_pays_the_plain_rate(self):
        # Between-the-legs asks the hands to do exactly what a crossover asks.
        # The legs are the difference and the camera has no view of them.
        legs = get_drill("bkb_between_legs")
        cross = get_drill("bkb_crossover")
        assert not legs.pattern_verified
        assert legs.scoring.xp_per_rep <= cross.scoring.xp_per_rep

    def test_the_variants_that_earn_more_ask_something_checkable(self):
        for key in ("bkb_crossover", "bkb_pound_weak"):
            drill = get_drill(key)
            plain = get_drill("bkb_dribble")
            assert drill.scoring.xp_per_rep > plain.scoring.xp_per_rep, key
            # ...and the thing that justifies it.
            assert drill.ball.alternation != "any", key
            assert drill.ball.attribute_side, key

    def test_the_low_pound_earns_its_premium_from_a_speed_floor(self):
        # Nothing about the ball distinguishes a low pound from an ordinary
        # dribble. The rate floor does, and it is the only thing that does.
        low = get_drill("bkb_pound_low")
        plain = get_drill("bkb_dribble")
        assert low.scoring.xp_per_rep > plain.scoring.xp_per_rep
        assert low.validation.min_reps_per_second > plain.validation.min_reps_per_second
        assert low.validation.min_reps_per_second >= 1.0

    def test_the_wall_pass_is_separated_by_the_contact_itself(self):
        # The one drill needing no inference at all: the ball comes off the
        # hands rather than the floor.
        assert get_drill("bkb_wall_pass").ball.contact == "body"
        for key in ("bkb_dribble", "bkb_crossover", "bkb_pound_low"):
            assert get_drill(key).ball.contact == "ground", key


class TestTheAlternationCheck:
    """The check that makes a crossover honestly worth more than a dribble."""

    def _review(self, key, hands):
        """A plausible session, so this isolates the alternation check.

        Perfectly even 200ms gaps trip two unrelated guards -- the rate ceiling
        and the too-regular-to-be-real check -- which would make these tests
        pass or fail for reasons that have nothing to do with the hands.
        """
        drill = get_drill(key)
        rng = random.Random(7)
        t, reps = 0, []
        for hand in hands:
            t += 380 + rng.randint(-70, 70)
            reps.append({"t_ms": t, "hand": hand})
        return ball_mod.review(drill, reps, track_quality=0.9, duration_ms=t + 400)

    def test_a_real_crossover_passes_quietly(self):
        result = self._review("bkb_crossover", ["left", "right"] * 12)
        assert not any("changed hands" in n for n in result.notes)

    def test_dribbling_on_one_hand_under_a_crossover_is_called_out(self):
        result = self._review("bkb_crossover", ["right"] * 24)
        assert any("changed hands" in n for n in result.notes)

    def test_it_is_a_note_and_never_a_refusal(self):
        # An athlete who meant to cross over and mostly did not has still done
        # real work. Telling them beats throwing the session away.
        result = self._review("bkb_crossover", ["right"] * 24)
        assert result.ok
        assert not result.hold

    def test_a_weak_hand_pound_that_swaps_hands_is_called_out(self):
        result = self._review("bkb_pound_weak", ["left", "right"] * 12)
        assert any("changed hands" in n for n in result.notes)

    def test_a_real_one_handed_pound_passes_quietly(self):
        result = self._review("bkb_pound_weak", ["left"] * 24)
        assert not any("changed hands" in n for n in result.notes)

    def test_a_short_session_says_nothing_either_way(self):
        # Six bounces say nothing about whether somebody crossed over.
        result = self._review("bkb_crossover", ["right"] * 6)
        assert not any("changed hands" in n for n in result.notes)

    def test_a_plain_dribble_is_never_told_how_to_use_its_hands(self):
        result = self._review("bkb_dribble", ["right"] * 24)
        assert not any("changed hands" in n for n in result.notes)

    def test_an_alternation_rule_needs_hands_to_check(self):
        from offdays.drills.base import BallSpec
        with pytest.raises(ValueError):
            BallSpec(alternation="alternating", attribute_side=False)

    def test_an_unknown_rule_is_refused(self):
        from offdays.drills.base import BallSpec
        with pytest.raises(ValueError):
            BallSpec(alternation="sometimes", attribute_side=True)


class TestThePositionPlans:
    def _bkb(self):
        return [p for p in ALL_POSITIONS if p.sport == "basketball"]

    def test_every_plan_leads_on_basketball(self):
        by = {d.key: d for d in ALL_DRILLS}
        for pos in self._bkb():
            own = sum(v for k, v in pos.emphasis.items()
                      if by[k].sport == "basketball")
            assert own >= 0.30, (pos.key, own)

    def test_the_guard_is_mostly_ball_handling(self):
        guard = next(p for p in self._bkb() if p.key == "guard")
        by = {d.key: d for d in ALL_DRILLS}
        own = sum(v for k, v in guard.emphasis.items() if by[k].sport == "basketball")
        assert own >= 0.60, own

    def test_every_plan_includes_the_weak_hand(self):
        # The one drill here the app can genuinely confirm, and the hand
        # nobody practises.
        for pos in self._bkb():
            assert pos.emphasis.get("bkb_pound_weak", 0) > 0, pos.key

    def test_weak_hand_parity_is_compared(self):
        for pos in self._bkb():
            assert pos.offhand_matters, pos.key

    def test_every_plan_still_sums_to_one(self):
        for pos in self._bkb():
            assert abs(sum(pos.emphasis.values()) - 1.0) < 1e-9, pos.key


class TestTheFilmCurriculum:
    TOPICS = curriculum.topics_for("basketball")

    def test_there_is_one(self):
        assert len(self.TOPICS) >= 12

    def test_every_topic_fits_inside_its_own_age_ceiling(self):
        # A clip over the ceiling is filtered out and the athlete never sees
        # it, so this is a real constraint rather than a style note.
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
        # The whole reason this file has none: a plausible-looking id that
        # turns out dead looks like a full shelf.
        blob = " ".join(t.find + t.title for t in self.TOPICS).lower()
        for banned in ("youtu.be", "youtube.com", "watch?v="):
            assert banned not in blob

    def test_no_topic_reads_like_a_highlight_reel(self):
        for topic in self.TOPICS:
            assert film.looks_like_highlights(topic.title) is None, topic.key

    def test_it_covers_both_ends_of_the_floor(self):
        focuses = {t.focus for t in self.TOPICS}
        assert "Team defence" in focuses
        assert focuses & {"Two-man game", "Passing", "Transition"}

    def test_the_big_gets_something_of_their_own(self):
        assert any("post" in t.positions and len(t.positions) < 3
                   for t in self.TOPICS)

    def test_topic_keys_are_unique_across_every_sport(self):
        keys = [t.key for ts in curriculum.BY_SPORT.values() for t in ts]
        assert len(keys) == len(set(keys))


class TestASportWithNoCurriculumSaysSo:
    def test_it_returns_empty_rather_than_erroring(self):
        assert curriculum.topics_for("hockey") == ()

    def test_the_note_explains_what_is_missing(self):
        note = curriculum.catalogue("hockey")["note"]
        assert "no film curriculum for hockey yet" in note
