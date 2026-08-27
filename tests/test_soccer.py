"""Soccer, built to the depth lacrosse has.

The first sport here played with the feet, and most of the machinery transfers
unchanged: `attribute_side` reads which foot took the ball exactly as it reads
which hand, so the alternation rules written for basketball make a weak-foot
drill and an alternating drill genuinely verifiable.

What did not transfer is heading, and that is a decision rather than a gap --
see `TestHeadingIsNotCounted`.
"""

from __future__ import annotations

import pytest

from offdays import curriculum, film, technique, transfer
from offdays.drills import ALL_DRILLS, get_drill
from offdays.drills.base import Metric
from offdays.positions import ALL_POSITIONS

SOC = [d for d in ALL_DRILLS if d.sport == "soccer"]
SOC_KEYS = [d.key for d in SOC]


class TestTheDrillSet:
    def test_there_are_enough_to_be_a_programme(self):
        assert len(SOC) >= 6, SOC_KEYS

    def test_it_covers_more_than_juggling(self):
        # Juggling is the easy thing to build and the least like the game.
        # A catalogue of six juggling variants would be one drill with six
        # names, which is the shape of the problem all this was built to avoid.
        assert {"soc_wall_pass", "soc_toe_taps", "soc_shuffle"} <= set(SOC_KEYS)

    @pytest.mark.parametrize("drill", SOC, ids=SOC_KEYS)
    def test_every_drill_has_cues_and_transfers(self, drill):
        assert technique.cues_for(drill.key), drill.key
        assert transfer.for_drill(drill.key), drill.key

    @pytest.mark.parametrize("drill", SOC, ids=SOC_KEYS)
    def test_every_drill_serializes(self, drill):
        import json
        json.dumps(drill.to_dict())

    def test_every_ball_drill_uses_the_same_ball(self):
        for drill in SOC:
            if drill.ball:
                assert drill.ball.diameter_cm == 20.5, drill.key
                assert drill.ball.detector == "vision", drill.key


class TestHeadingIsNotCounted:
    """The head was in the juggling parts list, and should not have been.

    A child heading a ball in a garden was being counted and paid for it, with
    no age floor anywhere and no separate volume. Youth football bans heading
    below about eleven and limits it for years after, and this product's whole
    argument for the throwing axis is that repetitive volume nobody counts is
    what hurts children.

    A header now simply does not register. The touch is not punished and
    nothing is said about it -- it earns nothing, which is the most a juggling
    drill should have to say about heading.
    """

    def test_no_soccer_drill_counts_a_head_touch(self):
        for drill in SOC:
            if drill.ball:
                assert "nose" not in drill.ball.parts, drill.key

    def test_there_is_no_heading_drill(self):
        # Not an oversight. Building one would mean an app encouraging a
        # twelve-year-old towards heading volume, which is the exact thing the
        # load model exists to argue against.
        for drill in SOC:
            assert "head" not in drill.name.lower(), drill.key
            assert "header" not in drill.description.lower(), drill.key

    def test_juggling_still_counts_feet_and_thighs(self):
        parts = set(get_drill("soc_juggle").ball.parts)
        assert {"left_ankle", "right_ankle", "left_knee", "right_knee"} <= parts


class TestPayingOnlyForWhatIsChecked:
    def test_the_weak_foot_drill_earns_its_premium(self):
        weak = get_drill("soc_juggle_weak")
        plain = get_drill("soc_juggle")
        assert weak.scoring.xp_per_rep > plain.scoring.xp_per_rep
        assert weak.ball.alternation == "same_hand"
        assert weak.ball.attribute_side

    def test_the_alternating_drill_earns_its_premium(self):
        alt = get_drill("soc_juggle_alt")
        assert alt.scoring.xp_per_rep > get_drill("soc_juggle").scoring.xp_per_rep
        assert alt.ball.alternation == "alternating"

    def test_thigh_juggling_is_separated_by_contact_location(self):
        # Only the knees are listed, so a ball off the laces is nowhere near a
        # listed part and simply is not a contact for this drill.
        assert set(get_drill("soc_thigh").ball.parts) == {"left_knee", "right_knee"}

    def test_wall_passing_is_separated_by_a_speed_floor(self):
        # Nothing else distinguishes a pass from a juggling touch -- both are
        # the ball coming off a foot -- and a struck pass leaves the boot far
        # faster than a touch that is only keeping it up.
        assert get_drill("soc_wall_pass").ball.min_speed > get_drill("soc_juggle").ball.min_speed * 2

    def test_toe_taps_are_separated_by_a_rate_floor(self):
        taps = get_drill("soc_toe_taps")
        assert taps.validation.min_reps_per_second >= 2.0
        assert taps.validation.min_reps_per_second > get_drill("soc_juggle").validation.min_reps_per_second

    def test_the_shuffle_pays_exactly_what_the_basketball_slide_pays(self):
        # It is the same movement measured the same way, and the app cannot
        # tell a defender jockeying a winger from a guard sliding. Paying
        # differently would be paying for the sport's name.
        assert (get_drill("soc_shuffle").scoring.xp_per_rep
                == get_drill("bkb_slide").scoring.xp_per_rep)

    def test_nothing_in_soccer_is_marked_unverifiable(self):
        # Every drill here differs in something checkable: which foot, whether
        # the feet alternate, where the contact was, how hard, or how fast.
        for drill in SOC:
            assert drill.pattern_verified, drill.key


class TestThePositionPlans:
    def _soc(self):
        return [p for p in ALL_POSITIONS if p.sport == "soccer"]

    def test_every_plan_leads_on_soccer(self):
        by = {d.key: d for d in ALL_DRILLS}
        for pos in self._soc():
            own = sum(v for k, v in pos.emphasis.items() if by[k].sport == "soccer")
            assert own >= 0.40, (pos.key, own)

    def test_every_outfield_plan_includes_the_weak_foot(self):
        # The one thing the app can genuinely confirm, and the foot nobody
        # practises is the foot a defender shows you.
        for pos in self._soc():
            if pos.key == "goalkeeper":
                continue
            assert pos.emphasis.get("soc_juggle_weak", 0) > 0, pos.key

    def test_the_defender_leads_on_defending(self):
        d = next(p for p in self._soc() if p.key == "defender")
        assert max(d.emphasis.items(), key=lambda kv: kv[1])[0] == "soc_shuffle"

    def test_the_keeper_does_not_get_a_defending_shuffle(self):
        # The one position that does not defend by jockeying a winger.
        keeper = next(p for p in self._soc() if p.key == "goalkeeper")
        assert "soc_shuffle" not in keeper.emphasis

    def test_the_keeper_still_gets_real_footwork(self):
        # Distribution is half a modern keeper's job, so a plan of nothing but
        # jumps would be the old mistake in a new place.
        keeper = next(p for p in self._soc() if p.key == "goalkeeper")
        assert keeper.emphasis.get("soc_wall_pass", 0) >= 0.10

    def test_every_plan_sums_to_one(self):
        for pos in self._soc():
            assert abs(sum(pos.emphasis.values()) - 1.0) < 1e-9, pos.key


class TestTheFilmCurriculum:
    TOPICS = curriculum.topics_for("soccer")

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

    def test_it_covers_both_halves_of_the_game(self):
        focuses = {t.focus for t in self.TOPICS}
        assert focuses & {"Defending", "Team defence"}
        assert focuses & {"Team offence", "Attacking", "First touch"}

    def test_no_topic_is_about_heading(self):
        blob = " ".join(t.title + t.focus + t.find for t in self.TOPICS).lower()
        assert "header" not in blob
        assert "heading" not in blob

    def test_keys_stay_unique_across_every_sport(self):
        keys = [t.key for ts in curriculum.BY_SPORT.values() for t in ts]
        assert len(keys) == len(set(keys))

    def test_four_sports_now_have_one(self):
        assert set(curriculum.BY_SPORT) >= {
            "lacrosse", "basketball", "volleyball", "soccer",
        }
