"""Swimming, which is entirely dryland because the athlete is in water.

The last sport, and the only one where the training happens somewhere the phone
structurally cannot go. That is not a compromise to apologise for: a swimmer's
dryland hour is a separately coached part of the sport, and it is the part that
decides whether their shoulders survive the yardage.

Nothing here counts a stroke, a length or a turn. The yardage itself reaches the
load model through the training log -- which running needed first, and which
swimming needed for a different tissue. An hour on a road loads bone; an hour in
water loads none at all and loads a shoulder instead, so the two carry different
rates and raise different cautions.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from offdays import curriculum, film, load, technique, transfer
from offdays.drills import ALL_DRILLS, get_drill
from offdays.drills.base import Metric, Stimulus, Tissue
from offdays.positions import BY_SPORT
from offdays.store import Store, StoreError

SWIMMING = [d for d in ALL_DRILLS if d.sport == "swimming"]


@pytest.fixture()
def athlete():
    store = Store()
    org = store.create_org("Sharks", "swimming")
    return store, store.create_user(org, "athlete", "Swimmer", birth_year=2010)["id"]


class TestEveryDrillIsDryland:
    def test_there_are_some(self):
        assert {d.key for d in SWIMMING} == {"swm_streamline", "swm_pull"}

    @pytest.mark.parametrize("drill", SWIMMING, ids=lambda d: d.key)
    def test_it_has_cues_and_transfers(self, drill):
        assert technique.cues_for(drill.key), drill.key
        assert transfer.for_drill(drill.key), drill.key

    def test_nothing_claims_to_count_swimming(self):
        """A phone cannot see a stroke, a length or a turn, and no drill here
        pretends otherwise."""
        for drill in SWIMMING:
            blob = (drill.name + " " + drill.description).lower()
            for word in ("stroke count", "length", "lap", "turn", "yard"):
                assert word not in blob, f"{drill.key}: {word}"

    def test_neither_drill_carries_a_ball_or_a_pool(self):
        for drill in SWIMMING:
            assert drill.ball is None, drill.key


class TestTheShoulderIsOnTheRightAxis:
    """A nuanced split, and worth pinning.

    Both drills load the same shoulder a throwing sport loads, so they sit on
    the throwing TISSUE -- which is what makes a prior shoulder injury tighten
    the caution for a swimmer. Neither adds to the throw COUNT, because that
    ceiling is derived from pitch guidance and a band pull is not a pitch.
    """

    @pytest.mark.parametrize("key", ["swm_streamline", "swm_pull"])
    def test_the_tissue_is_the_shoulder(self, key):
        assert get_drill(key).load.tissue is Tissue.THROWING

    @pytest.mark.parametrize("key", ["swm_streamline", "swm_pull"])
    def test_but_neither_counts_as_a_throw(self, key):
        assert get_drill(key).load.throws_per_rep == 0.0

    def test_a_swimmer_never_trips_the_pitch_derived_ceiling(self, athlete):
        store, aid = athlete
        state = store.load_state(aid)
        assert state.throws_today == 0
        assert not [a for a in state.advisories
                    if a.to_dict()["code"].startswith("throw")]


class TestTheStreamline:
    def test_it_is_the_first_drill_to_measure_an_arm_held_overhead(self):
        drill = get_drill("swm_streamline")
        assert drill.metric is Metric.HOLD_SECONDS
        others = [
            d.key for d in ALL_DRILLS
            if d.key != drill.key
            and d.metric is Metric.HOLD_SECONDS
            and (d.signal.landmark, d.signal.reference)
            == (drill.signal.landmark, drill.signal.reference)
        ]
        assert others == [], others

    def test_a_jumping_jack_never_reaches_the_band(self):
        """The two share a measurement. A jack passes through the bottom of a
        streamline on its way up; a streamline lives above where a jack ever
        gets, so the clock cannot be started by waving."""
        streamline = get_drill("swm_streamline")
        jack = get_drill("gen_jumping_jack")
        assert (streamline.signal.landmark, streamline.signal.reference) \
            == (jack.signal.landmark, jack.signal.reference)
        assert streamline.counter.down_threshold > jack.counter.up_threshold


class TestTheDrylandPull:
    def test_it_sits_inside_a_windmill_and_pays_less(self):
        # Same measurement, and the windmill's band contains it -- so the
        # subsumption guard requires this to be the cheaper of the two.
        pull = get_drill("swm_pull")
        windmill = get_drill("sb_windmill")
        assert (pull.signal.landmark, pull.signal.reference) \
            == (windmill.signal.landmark, windmill.signal.reference)
        assert windmill.counter.down_threshold <= pull.counter.down_threshold
        assert windmill.counter.up_threshold >= pull.counter.up_threshold
        assert pull.scoring.xp_per_rep < windmill.scoring.xp_per_rep

    def test_depth_carries_the_form_score(self):
        # The back half of the pull is the half that disappears when a swimmer
        # gets tired, in the water and out of it.
        q = get_drill("swm_pull").quality
        assert q.w_depth == max(q.w_depth, q.w_consistency, q.w_tempo, q.w_endurance)

    def test_it_records_which_arm(self):
        assert get_drill("swm_pull").tracks_handedness


class TestPoolTimeReachesTheLoadModel:
    def test_swimming_is_its_own_activity_with_its_own_rate(self):
        assert set(load.LOGGED_ACTIVITIES) >= {"run", "swim"}
        # Below running deliberately: an hour in water carries no bodyweight
        # and loads no bone, which is what the running figure is calibrated
        # against.
        assert load.LOAD_PER_MINUTE["swim"] < load.LOAD_PER_MINUTE["run"]

    def test_logged_pool_time_reaches_the_ratio(self, athlete):
        store, aid = athlete
        before = store.load_state(aid).acute
        today = date.today()
        for i in range(6):
            store.log_training(aid, minutes=90, activity="swim",
                               day=today - timedelta(days=i))
        after = store.load_state(aid)
        assert before == 0 and after.acute > 0
        assert after.weekly_swim_minutes == 540

    def test_a_jump_in_pool_time_is_flagged_as_a_shoulder_problem(self, athlete):
        store, aid = athlete
        today = date.today()
        for i in range(6):
            store.log_training(aid, minutes=60, activity="swim",
                               day=today - timedelta(days=8 + i))
        for i in range(6):
            store.log_training(aid, minutes=100, activity="swim",
                               day=today - timedelta(days=i))
        state = store.load_state(aid)
        jump = next(a for a in state.advisories
                    if a.to_dict()["code"] == "swim_jump")
        assert "shoulder" in jump.to_dict()["message"]
        assert "only what was logged" in jump.to_dict()["evidence"]

    def test_swimming_does_not_raise_the_bone_advisory(self, athlete):
        # The running caution talks about bone, which an hour in the water
        # does not load at all. Using one message for both would have been the
        # kind of confidently wrong sentence this product keeps refusing.
        store, aid = athlete
        today = date.today()
        for i in range(6):
            store.log_training(aid, minutes=40, activity="swim",
                               day=today - timedelta(days=8 + i))
        for i in range(6):
            store.log_training(aid, minutes=90, activity="swim",
                               day=today - timedelta(days=i))
        codes = {a.to_dict()["code"] for a in store.load_state(aid).advisories}
        assert "swim_jump" in codes and "run_jump" not in codes

    def test_the_two_activities_are_counted_separately(self, athlete):
        store, aid = athlete
        day = date.today()
        store.log_training(aid, minutes=40, activity="run", day=day)
        store.log_training(aid, minutes=70, activity="swim", day=day)
        state = store.load_state(aid)
        assert state.weekly_run_minutes == 40
        assert state.weekly_swim_minutes == 70

    def test_an_unknown_activity_is_refused_rather_than_silently_dropped(self, athlete):
        # A free-text activity would be accepted and then contribute nothing,
        # which is the worst of both.
        store, aid = athlete
        with pytest.raises(StoreError):
            store.log_training(aid, minutes=30, activity="cycling")

    def test_pool_time_still_earns_nothing(self, athlete):
        store, aid = athlete
        assert store.log_training(aid, minutes=120, activity="swim")["xp_awarded"] == 0
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE athlete_id = ?", (aid,)
        ).fetchone()["n"] == 0

    def test_one_row_per_day_per_activity(self, athlete):
        store, aid = athlete
        day = date.today() - timedelta(days=1)
        store.log_training(aid, minutes=30, activity="swim", day=day)
        store.log_training(aid, minutes=95, activity="swim", day=day)
        store.log_training(aid, minutes=20, activity="run", day=day)
        rows = [e for e in store.training_log(aid) if e["day"] == day.isoformat()]
        assert sorted((r["activity"], r["minutes"]) for r in rows) \
            == [("run", 20), ("swim", 95)]


class TestThePositionPlans:
    PLANS = BY_SPORT["swimming"]

    def test_every_plan_sums_to_one(self):
        for plan in self.PLANS:
            assert sum(plan.emphasis.values()) == pytest.approx(1.0)

    def test_every_plan_has_both_dryland_drills(self):
        for plan in self.PLANS:
            assert "swm_pull" in plan.emphasis, plan.key
            assert "swm_streamline" in plan.emphasis, plan.key

    def test_the_stroke_swimmer_leads_with_the_streamline(self):
        # A butterflyer and a backstroker pass through that position more
        # times a session than anybody, and it is what their shoulders
        # complain about first.
        plan = {p.key: p for p in self.PLANS}["stroke"].emphasis
        assert max(plan, key=plan.get) == "swm_streamline"

    def test_the_sprinter_keeps_the_most_leg_power(self):
        by_key = {p.key: p.emphasis for p in self.PLANS}
        assert by_key["sprint"]["gen_squat_jump"] > by_key["distance"]["gen_squat_jump"]


class TestTheFilmCurriculum:
    TOPICS = curriculum.topics_for("swimming")

    def test_there_is_one(self):
        assert len(self.TOPICS) >= 10

    def test_every_sport_a_program_can_pick_now_has_a_syllabus(self):
        """The sixteen that ship with position plans, which is what a program
        chooses at signup.

        `sports.CATALOG` is a longer list -- it is the vocabulary for what else
        an athlete plays, so a golfer or a wrestler can be recorded on a
        multi-sport profile. Those are not sports this product is built for,
        and claiming a syllabus for them would be the wrong boast.
        """
        from offdays.positions import BY_SPORT as PLANNED
        missing = [k for k in PLANNED if not curriculum.topics_for(k)]
        assert missing == [], missing
        assert len(PLANNED) == 16

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

    def test_nothing_here_teaches_a_stroke(self):
        """A pool deck job, done by somebody who can see the athlete under the
        water. A phone in a garden has no business in it."""
        for topic in self.TOPICS:
            assert "catch" not in topic.title.lower()
            assert "technique" not in topic.title.lower()

    def test_the_shoulder_is_taught_at_the_youngest_band(self):
        topic = curriculum.BY_KEY["swm_iq_shoulder_ache"]
        assert topic.min_age == 0
        assert "tell an adult" in topic.ask.options[topic.ask.answer].lower()

    def test_the_pull_buoy_topic_names_the_trap(self):
        topic = curriculum.BY_KEY["swm_iq_pull_buoy"]
        assert "shoulders more work" in topic.ask.options[topic.ask.answer]

    def test_the_fuelling_topic_talks_about_training_never_about_weight(self):
        topic = curriculum.BY_KEY["swm_iq_fuel"]
        blob = " ".join((topic.title, topic.ask.prompt, topic.ask.because,
                         *topic.ask.options)).lower()
        for word in ("calorie", "kg", "lbs", "pounds", "diet", "bmi"):
            assert word not in blob, word

    def test_every_topic_key_is_unique_across_the_whole_catalogue(self):
        rows = [t for topics in curriculum.BY_SPORT.values() for t in topics]
        distinct = list({id(t): t for t in rows}.values())
        assert len({t.key for t in distinct}) == len(distinct)
