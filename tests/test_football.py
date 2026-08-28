"""Football, and the model it walks straight into.

The diamond build gave the load model an age-scaled daily throwing ceiling
because youth pitching volume is the most-studied injury risk in this
catalogue. A quarterback throws more in a week than most pitchers do, into an
off season that does not exist, and nobody counts any of it. Nothing new had to
be built for that -- the ceiling was already there, and football simply is the
population it was waiting for.

Two things this sport does NOT get, both deliberately:

**No ball spec.** A football is not a sphere. The vision detector finds a ball
by fitting a circle of a known diameter, so an oblong seen from an angle it
cannot predict is not a hard case -- it is the wrong shape of problem. These
count from the body and claim nothing else.

**No get-off drill.** A lineman's start is horizontal explosion and the camera
measures vertical hip travel, which is a squat jump with a different name. It
is absent rather than approximated.
"""

from __future__ import annotations

import pytest

from offdays import curriculum, film, load, technique, transfer
from offdays.drills import ALL_DRILLS, get_drill
from offdays.drills.base import SignalKind, Tissue
from offdays.positions import BY_SPORT

FOOTBALL = [d for d in ALL_DRILLS if d.sport == "football"]
KEYS = [d.key for d in FOOTBALL]
PASSING = ["fb_quick_release", "fb_wall_throw", "fb_deep_ball"]


class TestTheDrillSet:
    def test_there_are_enough_to_be_a_programme(self):
        assert len(FOOTBALL) >= 5, KEYS

    def test_it_covers_passing_kicking_and_footwork(self):
        assert set(PASSING) <= set(KEYS)
        assert "fb_kick" in KEYS
        assert "fb_shuffle" in KEYS

    @pytest.mark.parametrize("drill", FOOTBALL, ids=lambda d: d.key)
    def test_every_drill_has_cues_and_transfers(self, drill):
        assert technique.cues_for(drill.key), drill.key
        assert transfer.for_drill(drill.key), drill.key

    def test_no_drill_claims_to_have_seen_the_ball(self):
        # A football is oblong. The detector fits circles of a known diameter,
        # so this is not a hard case for it -- it is the wrong kind of problem.
        assert [d.key for d in FOOTBALL if d.ball is not None] == []

    def test_there_is_no_get_off_drill(self):
        # Absent rather than approximated. A lineman's start is horizontal and
        # the camera measures vertical hip travel; a drill for it would be a
        # squat jump wearing a football name.
        assert not [d for d in FOOTBALL if d.signal.kind is SignalKind.BODY_HEIGHT]


class TestTheArmLedger:
    """The reason this sport was worth building."""

    def test_every_passing_drill_is_on_it(self):
        for key in PASSING:
            drill = get_drill(key)
            assert drill.load.tissue is Tissue.THROWING, key
            assert drill.load.throws_per_rep > 0, key

    def test_a_deep_ball_costs_the_arm_more_than_an_ordinary_throw(self):
        assert (get_drill("fb_deep_ball").load.throws_per_rep
                > get_drill("fb_wall_throw").load.throws_per_rep)

    def test_a_quick_release_costs_less_than_a_full_throw(self):
        # Short and submaximal, but still overhead and still repeated, so it
        # goes on the ledger at a reduced rate rather than at none.
        quick = get_drill("fb_quick_release").load.throws_per_rep
        full = get_drill("fb_wall_throw").load.throws_per_rep
        assert 0 < quick < full

    def test_kicking_and_footwork_are_not_throwing(self):
        for key in ("fb_kick", "fb_shuffle"):
            assert get_drill(key).load.throws_per_rep == 0.0

    def test_a_quarterback_hits_the_same_ceiling_a_pitcher_does(self):
        """No new model. The ceiling was built for the diamond and applies here
        by the same rule -- which is a judgement about two different throwing
        motions rather than evidence about either, and the advisory that rides
        on it already says it only counts throws the app saw."""
        assert load.throw_ceiling(13) == 120
        assert load.throw_ceiling(17) > load.throw_ceiling(11)
        assert load.throw_ceiling(None) is None

    def test_a_full_session_of_deep_balls_registers_against_the_day(self):
        drill = get_drill("fb_deep_ball")
        # The cap alone is more than half a thirteen-year-old's whole day.
        thrown = drill.scoring.daily_rep_cap * drill.load.throws_per_rep
        assert thrown > load.throw_ceiling(13) * 0.5


class TestThePassingBandsNestAndPayInOrder:
    def test_the_bands_are_contained_one_inside_the_next(self):
        ordered = sorted((get_drill(k) for k in PASSING),
                         key=lambda d: d.counter.up_threshold)
        for inner, outer in zip(ordered, ordered[1:]):
            assert outer.counter.down_threshold <= inner.counter.down_threshold
            assert outer.counter.up_threshold >= inner.counter.up_threshold

    def test_a_wider_throw_pays_more_and_costs_more(self):
        ordered = sorted((get_drill(k) for k in PASSING),
                         key=lambda d: d.counter.up_threshold)
        for inner, outer in zip(ordered, ordered[1:]):
            assert outer.scoring.xp_per_rep > inner.scoring.xp_per_rep
            assert outer.load.throws_per_rep > inner.load.throws_per_rep

    def test_a_quick_release_is_verified_by_a_rate_floor(self):
        # The check that makes the cheapest drill honest rather than merely
        # cheap: a full throw cannot be repeated at this rate.
        quick = get_drill("fb_quick_release")
        assert quick.validation.min_reps_per_second > 0.3
        assert (quick.validation.min_reps_per_second
                > get_drill("fb_wall_throw").validation.max_reps_per_second)


class TestTheKickingSwing:
    def test_it_reads_the_kicking_foot_against_its_own_hip(self):
        drill = get_drill("fb_kick")
        assert drill.signal.kind is SignalKind.RELATIVE_HEIGHT
        assert (drill.signal.landmark, drill.signal.reference) \
            == ("right_ankle", "right_hip")

    def test_no_other_drill_measures_a_foot_against_a_hip(self):
        others = [
            d.key for d in ALL_DRILLS if d.key != "fb_kick"
            and (d.signal.landmark, d.signal.reference) == ("right_ankle", "right_hip")
        ]
        assert others == [], others

    def test_the_band_requires_the_foot_to_finish_above_the_hip(self):
        # What makes a full swing unmistakable. Standing puts the ankle well
        # below the hip; only a real follow-through takes it above.
        drill = get_drill("fb_kick")
        assert drill.counter.down_threshold < -0.9
        assert drill.counter.up_threshold > 0.4

    def test_a_kicker_carries_real_load_even_though_nothing_is_thrown(self):
        drill = get_drill("fb_kick")
        assert drill.load.tissue is Tissue.LOWER_BODY
        assert drill.load.load_per_rep >= 1.0


class TestThePositionPlans:
    PLANS = BY_SPORT["football"]

    def test_the_specialist_finally_exists(self):
        # The only group on the roster whose whole practice is solo and
        # repetitive -- which is exactly the athlete this product is for -- and
        # they had no plan at all.
        keys = {p.key for p in self.PLANS}
        assert "specialist" in keys

    def test_every_plan_sums_to_one(self):
        for plan in self.PLANS:
            assert sum(plan.emphasis.values()) == pytest.approx(1.0)

    def test_the_quarterback_leads_with_ordinary_throws_not_deep_ones(self):
        qb = {p.key: p for p in self.PLANS}["quarterback"].emphasis
        assert qb["fb_wall_throw"] > qb["fb_deep_ball"]
        assert qb["fb_quick_release"] > qb["fb_deep_ball"]

    def test_the_specialist_leads_with_the_swing(self):
        plan = {p.key: p for p in self.PLANS}["specialist"].emphasis
        assert max(plan, key=plan.get) == "fb_kick"

    def test_the_line_gets_the_slide_rather_than_nothing(self):
        # A tackle's kick-slide and a defensive back's mirror are the same feet
        # doing the same job, and the camera could not tell them apart even if
        # two drills were wanted. So there is one, and the linemen use it.
        plan = {p.key: p for p in self.PLANS}["line"].emphasis
        assert plan.get("fb_shuffle", 0) > 0

    def test_nobody_but_the_quarterback_is_given_throwing_volume(self):
        for plan in self.PLANS:
            if plan.key == "quarterback":
                continue
            assert not set(plan.emphasis) & set(PASSING), plan.key

    def test_every_alias_resolves_to_one_position(self):
        seen: dict[str, str] = {}
        for plan in self.PLANS:
            for alias in plan.aliases:
                assert alias not in seen, f"{alias}: {seen[alias]} and {plan.key}"
                seen[alias] = plan.key


class TestTheFilmCurriculum:
    TOPICS = curriculum.topics_for("football")

    def test_there_is_one(self):
        assert len(self.TOPICS) >= 10

    def test_every_topic_fits_its_age_ceiling(self):
        for topic in self.TOPICS:
            cap = film.band_for(topic.min_age).clip_max_s
            assert topic.target_s <= cap, f"{topic.key}: {topic.target_s} > {cap}"

    def test_every_topic_carries_a_question_with_its_reasoning(self):
        for topic in self.TOPICS:
            assert topic.ask.because, topic.key
            assert 0 <= topic.ask.answer < len(topic.ask.options), topic.key

    def test_no_topic_ships_a_video_id(self):
        blob = " ".join(t.find + t.title for t in self.TOPICS).lower()
        for banned in ("youtu.be", "youtube.com", "watch?v="):
            assert banned not in blob

    def test_no_topic_reads_like_a_highlight_reel(self):
        for topic in self.TOPICS:
            assert film.looks_like_highlights(topic.title) is None, topic.key

    def test_the_head_is_taught_first_and_taught_to_everybody(self):
        """This sport's defining risk, and the reason the syllabus leans the way
        it does. Not held back to the oldest band: the age players start
        tackling is the age this has to have been said."""
        safety = [t for t in self.TOPICS if t.focus == "Staying safe"]
        assert len(safety) >= 4, [t.key for t in self.TOPICS]
        assert min(t.min_age for t in safety) == 0
        # And at least one that every position sees, not only the tacklers.
        assert any(len(t.positions) >= 6 for t in safety)

    def test_the_specialist_is_taught_something_of_their_own(self):
        assert [t for t in self.TOPICS if t.positions == ("specialist",)]

    def test_there_is_one_about_the_throws_nobody_counts(self):
        topic = curriculum.BY_KEY["fb_iq_arm_count"]
        assert "count" in topic.ask.because.lower()

    def test_every_topic_key_is_unique_across_the_whole_catalogue(self):
        rows = [t for topics in curriculum.BY_SPORT.values() for t in topics]
        # Sports deliberately share syllabus objects, so count distinct topics
        # rather than distinct sports.
        distinct = {id(t): t for t in rows}.values()
        assert len({t.key for t in distinct}) == len(list(distinct))
