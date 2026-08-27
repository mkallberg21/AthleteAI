"""Baseball and softball, built to the depth lacrosse has.

The sport where the load model matters most and had the least to say. Youth
throwing volume is the most-studied injury risk anywhere in this catalogue, and
the model carried only a week-on-week spike check -- blind to the athlete who
throws a lot every week and always has, which is the pattern that actually hurts
arms.

The two sports share almost everything and diverge at exactly one place: a
softball pitcher throws underhand in a full arm circle, which is a different
motion with a different injury profile and gets its own drill and its own plan.
"""

from __future__ import annotations

import pytest

from offdays import curriculum, film, load, technique, transfer
from offdays.drills import ALL_DRILLS, get_drill
from offdays.drills.base import Metric
from offdays.positions import ALL_POSITIONS

DIAMOND = [d for d in ALL_DRILLS if d.sport in ("baseball", "softball")]
DIAMOND_KEYS = [d.key for d in DIAMOND]


class TestTheDrillSet:
    def test_there_are_enough_to_be_a_programme(self):
        assert len(DIAMOND) >= 6, DIAMOND_KEYS

    def test_it_covers_hitting_fielding_and_throwing(self):
        # A catalogue of throwing drills for the sport whose main risk is
        # throwing volume would be the worst possible shape.
        assert {"bb_tee_swing", "bb_fielding", "bb_wall_throw"} <= set(DIAMOND_KEYS)

    def test_softball_has_its_own_pitching_motion(self):
        windmill = get_drill("sb_windmill")
        assert windmill.sport == "softball"
        assert windmill.load.tissue.value == "throwing"

    @pytest.mark.parametrize("drill", DIAMOND, ids=DIAMOND_KEYS)
    def test_every_drill_has_cues_and_transfers(self, drill):
        assert technique.cues_for(drill.key), drill.key
        assert transfer.for_drill(drill.key), drill.key

    @pytest.mark.parametrize("drill", DIAMOND, ids=DIAMOND_KEYS)
    def test_every_drill_serializes(self, drill):
        import json
        json.dumps(drill.to_dict())


class TestTheArmLedger:
    """What goes on the throwing axis, and what deliberately does not."""

    def test_throwing_drills_are_on_it(self):
        for key in ("bb_wall_throw", "bb_long_toss", "bb_quick_hands", "sb_windmill"):
            assert get_drill(key).load.throws_per_rep > 0, key
            assert get_drill(key).load.tissue.value == "throwing", key

    def test_a_long_toss_costs_more_than_a_wall_throw(self):
        # Each one is a harder throw and the arm knows it. Counting them
        # one-for-one would understate the day.
        assert (get_drill("bb_long_toss").load.throws_per_rep
                > get_drill("bb_wall_throw").load.throws_per_rep)

    def test_a_quick_transfer_costs_less_than_a_full_throw(self):
        # Short and submaximal, but still overhead and still repeated -- so it
        # belongs on the ledger at a reduced rate rather than at none.
        quick = get_drill("bb_quick_hands").load.throws_per_rep
        assert 0 < quick < get_drill("bb_wall_throw").load.throws_per_rep

    def test_hitting_and_fielding_are_not_throwing(self):
        # Putting a swing on the arm's ledger would make an afternoon of
        # hitting read as an afternoon of throwing and hide the real number.
        for key in ("bb_tee_swing", "bb_fielding", "bb_catcher_stance"):
            assert get_drill(key).load.throws_per_rep == 0.0, key

    def test_the_windmill_counts_even_though_it_is_underhand(self):
        # Different mechanism, same principle: a repeated maximal throw from a
        # growing arm, performed more often than anything else on the field.
        assert get_drill("sb_windmill").load.throws_per_rep == 1.0


class TestTheDailyThrowingCeiling:
    """The absolute ceiling the load model did not have.

    The spike check is blind to an athlete who throws a lot every week and
    always has. That is the pattern that hurts young arms, and a relative
    measure calls it normal.
    """

    def test_it_scales_with_age(self):
        ceilings = [load.throw_ceiling(a) for a in (8, 10, 12, 14, 16, 18)]
        assert ceilings == sorted(ceilings)
        assert len(set(ceilings)) == len(ceilings)

    def test_an_unknown_age_gets_no_ceiling_rather_than_a_guess(self):
        # Too low and it nags a seventeen-year-old; too high and it says
        # nothing to the eleven-year-old it exists for.
        assert load.throw_ceiling(None) is None

    def test_an_adult_gets_the_top_of_the_table(self):
        assert load.throw_ceiling(30) == load.THROW_CEILING_BY_AGE[-1][1]

    def test_the_youngest_ceiling_is_meaningfully_low(self):
        assert load.throw_ceiling(8) <= 75

    def test_it_sits_above_published_pitch_guidance_deliberately(self):
        # Those numbers are pitches in a game, maximal effort from a mound,
        # counted by an adult with a clicker. A driveway wall throw is not a
        # pitch, and pretending otherwise would make the advisory cry wolf.
        assert load.throw_ceiling(12) > 85


class TestTheCeilingAdvisory:
    def _state(self, age, throws):
        from datetime import date, timedelta
        today = date.today()
        days = [load.DayLoad(day=today - timedelta(days=i)) for i in range(6, -1, -1)]
        days[-1].throws = throws
        days[-1].load = float(throws)
        days[-1].sessions = 1
        state = load.LoadState()
        state.throws_today = throws
        state.throw_ceiling = load.throw_ceiling(age)
        load._add_advisories(state, load.CONFIG.load, age, days)
        return state

    def _codes(self, state):
        return {a.code for a in state.advisories}

    def test_a_normal_day_says_nothing_about_the_ceiling(self):
        assert not {"throw_ceiling", "throw_ceiling_near"} & self._codes(self._state(12, 30))

    def test_approaching_it_is_said_before_it_is_reached(self):
        assert "throw_ceiling_near" in self._codes(self._state(12, 90))

    def test_going_over_it_is_a_warning(self):
        state = self._state(12, 130)
        assert "throw_ceiling" in self._codes(state)
        assert any(a.level == "warning" for a in state.advisories)

    def test_an_unknown_age_produces_no_ceiling_advisory(self):
        assert not {"throw_ceiling", "throw_ceiling_near"} & self._codes(self._state(None, 300))

    def test_the_advisory_admits_it_only_saw_some_of_the_throws(self):
        # A pitcher who threw eighty in a game and fifty in the garden is at a
        # hundred and thirty, and this knows about fifty. Saying so is the
        # difference between a useful number and a false reassurance.
        state = self._state(12, 130)
        note = next(a for a in state.advisories if a.code == "throw_ceiling")
        assert "not games" in note.evidence

    def test_it_never_blocks_anything(self):
        # An advisory, like everything else in this model. It is a prompt to a
        # coach and a parent, never a refusal to record a session.
        state = self._state(10, 400)
        assert state.advisories
        for advisory in state.advisories:
            assert advisory.level in ("info", "caution", "warning")


class TestThePositionPlans:
    def _plans(self, sport):
        return [p for p in ALL_POSITIONS if p.sport == sport]

    def test_the_two_sports_share_everything_except_the_mound(self):
        bb = {p.key: p.emphasis for p in self._plans("baseball")}
        sb = {p.key: p.emphasis for p in self._plans("softball")}
        assert set(bb) == set(sb)
        differing = [k for k in bb if bb[k] != sb[k]]
        assert differing == ["pitcher"], differing

    def test_the_softball_pitcher_gets_the_windmill(self):
        sb = next(p for p in self._plans("softball") if p.key == "pitcher")
        assert sb.emphasis.get("sb_windmill", 0) > 0
        assert max(sb.emphasis.items(), key=lambda kv: kv[1])[0] == "sb_windmill"

    def test_the_baseball_pitcher_does_not(self):
        bb = next(p for p in self._plans("baseball") if p.key == "pitcher")
        assert "sb_windmill" not in bb.emphasis

    def test_the_pitcher_is_the_least_sport_specific_plan_on_purpose(self):
        # The one position where a low own-sport share is correct. A pitcher's
        # solo hours should be legs, hips and core -- the throwing is what the
        # rest of their week is already full of.
        by = {d.key: d for d in ALL_DRILLS}
        shares = {}
        for pos in self._plans("baseball"):
            shares[pos.key] = sum(
                v for k, v in pos.emphasis.items()
                if by[k].sport in ("baseball", "softball")
            )
        assert shares["pitcher"] == min(shares.values())

    def test_no_plan_makes_throwing_the_main_event(self):
        by = {d.key: d for d in ALL_DRILLS}
        for sport in ("baseball", "softball"):
            for pos in self._plans(sport):
                throwing = sum(
                    v for k, v in pos.emphasis.items()
                    if by[k].load.throws_per_rep > 0
                )
                assert throwing <= 0.30, (sport, pos.key, throwing)

    def test_every_plan_sums_to_one(self):
        for sport in ("baseball", "softball"):
            for pos in self._plans(sport):
                assert abs(sum(pos.emphasis.values()) - 1.0) < 1e-9, pos.key


class TestTheFilmCurriculum:
    TOPICS = curriculum.topics_for("baseball")

    def test_both_sports_share_one_syllabus(self):
        assert curriculum.topics_for("softball") is self.TOPICS

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

    def test_no_topic_ships_a_video_id(self):
        blob = " ".join(t.find + t.title for t in self.TOPICS).lower()
        for banned in ("youtu.be", "youtube.com", "watch?v="):
            assert banned not in blob

    def test_no_topic_reads_like_a_highlight_reel(self):
        for topic in self.TOPICS:
            assert film.looks_like_highlights(topic.title) is None, topic.key

    def test_there_is_one_about_knowing_when_to_stop(self):
        # The sport whose defining risk is volume should have a topic about
        # recognising it, and it should be aimed at every position rather than
        # only at pitchers.
        arm = [t for t in self.TOPICS if t.focus == "Staying healthy"]
        assert arm
        assert len(arm[0].positions) == 4

    def test_keys_stay_unique_across_every_sport(self):
        keys = [t.key for ts in curriculum.BY_SPORT.values() for t in ts]
        # Baseball and softball share one tuple, so count distinct syllabuses.
        seen = {id(ts): ts for ts in curriculum.BY_SPORT.values()}
        keys = [t.key for ts in seen.values() for t in ts]
        assert len(keys) == len(set(keys))

    def test_seven_sports_now_have_one(self):
        assert set(curriculum.BY_SPORT) >= {
            "lacrosse", "basketball", "volleyball", "soccer", "tennis",
            "baseball", "softball",
        }
