"""Tennis, built to the depth lacrosse has.

The one sport here where the ball never touches the athlete. It comes off a
racket head roughly sixty centimetres beyond the hand, and the detector
attributes the contact to the nearest wrist -- so what these drills really
measure is "the ball left from near this hand".

That is enough to tell one wing from the other, and not enough to tell which is
which. Nothing here claims to, and the drill that depends on it says so in its
own description.
"""

from __future__ import annotations

import pytest

from offdays import curriculum, film, technique, transfer
from offdays.drills import ALL_DRILLS, get_drill
from offdays.drills.base import Metric, SignalKind
from offdays.positions import ALL_POSITIONS

TEN = [d for d in ALL_DRILLS if d.sport == "tennis"]
TEN_KEYS = [d.key for d in TEN]


class TestTheDrillSet:
    def test_there_are_enough_to_be_a_programme(self):
        assert len(TEN) >= 6, TEN_KEYS

    def test_it_covers_movement_as_well_as_ball_striking(self):
        # A tennis point is mostly running. A catalogue of nothing but wall
        # rallies would be the sport's least demanding half.
        movement = [d for d in TEN if d.ball is None]
        assert len(movement) >= 2, [d.key for d in movement]

    @pytest.mark.parametrize("drill", TEN, ids=TEN_KEYS)
    def test_every_drill_has_cues_and_transfers(self, drill):
        assert technique.cues_for(drill.key), drill.key
        assert transfer.for_drill(drill.key), drill.key

    @pytest.mark.parametrize("drill", TEN, ids=TEN_KEYS)
    def test_every_drill_serializes(self, drill):
        import json
        json.dumps(drill.to_dict())

    def test_every_ball_drill_uses_the_same_ball(self):
        for drill in TEN:
            if drill.ball:
                assert drill.ball.diameter_cm == 6.7, drill.key
                assert drill.ball.colour == "optic", drill.key


class TestItDoesNotClaimToKnowTheWing:
    """The limit that shapes the whole sport's build.

    A forehand and a backhand are struck on opposite sides of the body, so hand
    attribution can tell that the wing *changed*. It cannot tell which wing
    either one was -- a right-hander's backhand and a left-hander's forehand
    look identical from the front.
    """

    def test_the_one_wing_drill_admits_it_cannot_tell_which(self):
        text = get_drill("ten_one_wing").description.lower()
        assert "cannot tell a forehand from a backhand" in text

    def test_it_puts_the_choice_of_wing_on_the_athlete(self):
        text = get_drill("ten_one_wing").description.lower()
        assert "yours to decide" in text

    def test_no_drill_name_claims_a_wing(self):
        for drill in TEN:
            assert "forehand" not in drill.name.lower(), drill.key
            assert "backhand" not in drill.name.lower(), drill.key


class TestPayingOnlyForWhatIsChecked:
    def test_alternating_wings_earns_its_premium(self):
        alt = get_drill("ten_alternate")
        assert alt.scoring.xp_per_rep > get_drill("ten_wall_rally").scoring.xp_per_rep
        assert alt.ball.alternation == "alternating"
        assert alt.ball.attribute_side

    def test_one_wing_earns_its_premium(self):
        one = get_drill("ten_one_wing")
        assert one.scoring.xp_per_rep > get_drill("ten_wall_rally").scoring.xp_per_rep
        assert one.ball.alternation == "same_hand"

    def test_volleys_are_separated_by_a_rate_floor(self):
        # Standing back and rallying cannot reach this rate, and standing close
        # and blocking cannot avoid it.
        volley = get_drill("ten_volley")
        assert volley.validation.min_reps_per_second >= 1.2
        assert volley.ball.min_gap_ms < get_drill("ten_wall_rally").ball.min_gap_ms

    def test_the_serve_is_separated_by_using_a_different_signal_entirely(self):
        assert get_drill("ten_serve").signal.kind is SignalKind.SHOOTING_ARM
        assert get_drill("ten_wall_rally").signal.kind is SignalKind.BODY_HEIGHT

    def test_the_recovery_pays_what_the_other_two_shuffles_pay(self):
        # Identical movement, identical measurement. The app cannot tell a
        # player recovering across a baseline from a guard sliding or a
        # defender jockeying, so it must not pay differently for the name.
        rate = get_drill("ten_recovery").scoring.xp_per_rep
        assert rate == get_drill("bkb_slide").scoring.xp_per_rep
        assert rate == get_drill("soc_shuffle").scoring.xp_per_rep

    def test_nothing_in_tennis_is_marked_unverifiable(self):
        for drill in TEN:
            assert drill.pattern_verified, drill.key


class TestTheServeIsAThrow:
    """Tennis's one action on the throwing axis.

    It is the same overhead chain a pitch count exists to watch, and a serving
    shoulder at fifteen gets hurt exactly the way a pitching one does.
    """

    def test_the_serve_carries_throwing_load(self):
        serve = get_drill("ten_serve")
        assert serve.load.throws_per_rep == 1.0
        assert serve.load.tissue.value == "throwing"

    def test_nothing_else_in_tennis_does(self):
        for drill in TEN:
            if drill.key == "ten_serve":
                continue
            assert drill.load.throws_per_rep == 0.0, drill.key

    def test_it_is_capped_tightly(self):
        assert get_drill("ten_serve").scoring.daily_rep_cap <= 200

    def test_no_plan_makes_serving_the_main_event(self):
        for pos in [p for p in ALL_POSITIONS if p.sport == "tennis"]:
            assert pos.emphasis.get("ten_serve", 0) <= 0.12, pos.key


class TestThePositionPlans:
    def _ten(self):
        return [p for p in ALL_POSITIONS if p.sport == "tennis"]

    def test_both_plans_lead_on_tennis(self):
        by = {d.key: d for d in ALL_DRILLS}
        for pos in self._ten():
            own = sum(v for k, v in pos.emphasis.items() if by[k].sport == "tennis")
            assert own >= 0.50, (pos.key, own)

    def test_the_two_positions_are_genuinely_different(self):
        # Two positions is few enough that identical plans would make the
        # distinction meaningless.
        singles, doubles = (next(p for p in self._ten() if p.key == k)
                            for k in ("singles", "doubles"))
        assert singles.emphasis != doubles.emphasis
        assert (doubles.emphasis["ten_volley"]
                > singles.emphasis.get("ten_volley", 0) * 2)

    def test_the_doubles_player_leads_on_volleys(self):
        doubles = next(p for p in self._ten() if p.key == "doubles")
        assert max(doubles.emphasis.items(), key=lambda kv: kv[1])[0] == "ten_volley"

    def test_both_get_the_split_step(self):
        # The one movement that precedes every shot either of them will hit.
        for pos in self._ten():
            assert pos.emphasis.get("ten_split_step", 0) > 0, pos.key

    def test_every_plan_sums_to_one(self):
        for pos in self._ten():
            assert abs(sum(pos.emphasis.values()) - 1.0) < 1e-9, pos.key


class TestTheFilmCurriculum:
    TOPICS = curriculum.topics_for("tennis")

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

    def test_it_covers_the_things_that_have_no_teammates(self):
        # The only sport here played alone, so the syllabus has something the
        # others do not need: what your own body language is telling the other
        # end, and how to think about a scoreline.
        focuses = {t.focus for t in self.TOPICS}
        assert "Competing" in focuses
        assert "Patterns" in focuses

    def test_the_doubles_player_gets_something_of_their_own(self):
        assert any(t.positions == ("doubles",) for t in self.TOPICS)

    def test_keys_stay_unique_across_every_sport(self):
        keys = [t.key for ts in curriculum.BY_SPORT.values() for t in ts]
        assert len(keys) == len(set(keys))

    def test_five_sports_now_have_one(self):
        assert set(curriculum.BY_SPORT) >= {
            "lacrosse", "basketball", "volleyball", "soccer", "tennis",
        }
