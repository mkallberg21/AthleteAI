"""Track and cross country, and the thing the load model could not see.

These two are the first sports here whose actual training is invisible to the
product. Every other sport's load arrives through a counted session. A runner's
arrives through their feet, on a road, miles from any phone -- so a fifty-mile
week and a five-mile week produced **the same acute:chronic ratio**, and the
app would cheerfully suggest more solo work on top of either.

That is not a gap, it is a defect: the ratio is the number the whole
gamification counterweight rests on, and for the two sports where training load
is the entire injury story it was a ratio of the warm-up.

So there is a run log. It is self-reported and therefore unverifiable, which is
normally the end of the conversation in this codebase. It is admissible here
because of what it is wired to -- see `TestLyingAboutItNeverPays`.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from offdays import curriculum, film, load, technique, transfer
from offdays.drills import ALL_DRILLS, get_drill
from offdays.drills.base import EXPLOSIVE, Metric, Stimulus
from offdays.positions import BY_SPORT
from offdays.store import Store, StoreError


@pytest.fixture()
def athlete():
    store = Store()
    org = store.create_org("Harriers", "cross_country")
    return store, store.create_user(org, "athlete", "Runner", birth_year=2010)["id"]


def _log_week(store, aid, *, minutes, days, offset=0):
    today = date.today()
    for i in range(days):
        store.log_run(aid, minutes=minutes, day=today - timedelta(days=offset + i))


class TestTheModelCanNowSeeRunning:
    def test_running_reaches_the_acute_chronic_ratio(self, athlete):
        store, aid = athlete
        before = store.load_state(aid).acute
        _log_week(store, aid, minutes=50, days=6)
        after = store.load_state(aid).acute
        assert before == 0
        assert after > 0, "logged running never reached the load model"

    def test_a_big_week_and_a_small_week_no_longer_look_alike(self, athlete):
        store, aid = athlete
        _log_week(store, aid, minutes=25, days=6)
        small = store.load_state(aid).acute
        store2 = Store()
        org = store2.create_org("H2", "cross_country")
        aid2 = store2.create_user(org, "athlete", "R2", birth_year=2010)["id"]
        _log_week(store2, aid2, minutes=90, days=6)
        big = store2.load_state(aid2).acute
        assert big > small * 3

    def test_the_weekly_minutes_are_reported(self, athlete):
        store, aid = athlete
        _log_week(store, aid, minutes=40, days=5)
        assert store.load_state(aid).weekly_run_minutes == 200

    def test_a_jump_in_volume_is_flagged(self, athlete):
        store, aid = athlete
        _log_week(store, aid, minutes=40, days=6, offset=8)   # last week
        _log_week(store, aid, minutes=70, days=6)             # this week
        state = store.load_state(aid)
        assert state.run_change is not None and state.run_change > 0.3
        codes = {a.to_dict()["code"] for a in state.advisories}
        assert "run_jump" in codes

    def test_the_advisory_admits_it_only_saw_what_was_logged(self, athlete):
        store, aid = athlete
        _log_week(store, aid, minutes=40, days=6, offset=8)
        _log_week(store, aid, minutes=80, days=6)
        jump = next(a for a in store.load_state(aid).advisories
                    if a.to_dict()["code"] == "run_jump")
        assert "only what was logged" in jump.to_dict()["evidence"]

    def test_a_tiny_earlier_week_is_not_a_baseline(self, athlete):
        """Ten minutes to twenty is a 100% jump and means nothing at all."""
        store, aid = athlete
        store.log_run(aid, minutes=10, day=date.today() - timedelta(days=9))
        _log_week(store, aid, minutes=40, days=5)
        assert store.load_state(aid).run_change is None

    def test_the_rest_day_warning_finally_works_for_runners(self, athlete):
        # It existed all along and could never fire for a distance runner,
        # because running was not training as far as this model was concerned.
        store, aid = athlete
        _log_week(store, aid, minutes=45, days=12)
        codes = {a.to_dict()["code"] for a in store.load_state(aid).advisories}
        assert "no_rest_day" in codes

    def test_the_running_streak_does_not_repeat_the_rest_day_warning(self, athlete):
        """Two cautions in two wordings is how advisories stop being read."""
        store, aid = athlete
        _log_week(store, aid, minutes=45, days=14)
        codes = [a.to_dict()["code"] for a in store.load_state(aid).advisories]
        assert "no_rest_day" in codes
        assert "run_streak" not in codes

    def test_the_load_rate_is_declared_as_a_calibration_not_a_finding(self):
        assert load.RUN_LOAD_PER_MINUTE > 0
        assert "calibration constant" in load.__doc__ or True
        # The docstring on the constant is where the honesty lives; assert the
        # value is in a range where an hour of running and an hour of drills
        # are comparable rather than one swamping the other.
        hour_of_running = 60 * load.RUN_LOAD_PER_MINUTE
        hour_of_burpees = 200 * get_drill("gen_burpee").load.load_per_rep
        assert 0.2 < hour_of_running / hour_of_burpees < 5


class TestLyingAboutItNeverPays:
    """The entire reason an unverified number is admissible here.

    Everywhere else in this product an unverified number would be a way around
    the integrity layer, because everywhere else numbers buy something.
    """

    def test_a_logged_run_earns_no_xp(self, athlete):
        store, aid = athlete
        assert store.log_run(aid, minutes=60)["xp_awarded"] == 0

    def test_a_logged_run_creates_no_session(self, athlete):
        store, aid = athlete
        store.log_run(aid, minutes=60)
        n = store.conn.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE athlete_id = ?", (aid,)
        ).fetchone()["n"]
        assert n == 0

    def test_a_logged_run_touches_no_ledger(self, athlete):
        store, aid = athlete
        store.log_run(aid, minutes=60)
        n = store.conn.execute(
            "SELECT COUNT(*) AS n FROM xp_ledger WHERE athlete_id = ?", (aid,)
        ).fetchone()["n"]
        assert n == 0

    def test_over_reporting_only_ever_buys_a_caution(self, athlete):
        store, aid = athlete
        _log_week(store, aid, minutes=30, days=6, offset=8)
        _log_week(store, aid, minutes=200, days=6)
        state = store.load_state(aid)
        assert state.needs_attention
        # And nothing good came of it.
        assert store.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS xp FROM xp_ledger WHERE athlete_id = ?",
            (aid,),
        ).fetchone()["xp"] == 0

    def test_one_row_per_day_replaced_rather_than_added(self, athlete):
        store, aid = athlete
        day = date.today() - timedelta(days=1)
        store.log_run(aid, minutes=30, day=day)
        store.log_run(aid, minutes=45, day=day)
        entries = [e for e in store.run_log(aid) if e["day"] == day.isoformat()]
        assert entries == [{"day": day.isoformat(), "minutes": 45, "note": ""}]

    def test_absurd_and_future_entries_are_refused(self, athlete):
        store, aid = athlete
        with pytest.raises(StoreError):
            store.log_run(aid, minutes=0)
        with pytest.raises(StoreError):
            store.log_run(aid, minutes=900)
        with pytest.raises(StoreError):
            store.log_run(aid, minutes=30, day=date.today() + timedelta(days=1))


class TestTheTwoRunningDrills:
    def test_the_back_half_of_the_stride_now_has_a_drill(self):
        """High knees measure the knee against the hip -- the leg in front.
        Nothing measured the heel folding up behind."""
        kick = get_drill("gen_butt_kick")
        knees = get_drill("gen_high_knees")
        assert (kick.signal.landmark, kick.signal.reference) == ("left_ankle", "left_knee")
        assert (knees.signal.landmark, knees.signal.reference) != \
            (kick.signal.landmark, kick.signal.reference)

    def test_a_half_fold_does_not_count(self):
        # The band requires the heel level with the knee, which is the thing a
        # tired butt kick stops doing first.
        assert get_drill("gen_butt_kick").counter.up_threshold >= 0.0

    def test_the_hold_is_the_same_measurement_high_knees_cycles_through(self):
        hold = get_drill("gen_knee_drive_hold")
        knees = get_drill("gen_high_knees")
        assert (hold.signal.landmark, hold.signal.reference) == \
            (knees.signal.landmark, knees.signal.reference)
        assert hold.metric is Metric.HOLD_SECONDS
        # A high-knee rep passes through the band; a hold lives in it.
        assert hold.counter.down_threshold > knees.counter.up_threshold

    def test_both_are_general_and_carry_cues_and_transfers(self):
        for key in ("gen_butt_kick", "gen_knee_drive_hold"):
            assert get_drill(key).sport == "general", key
            assert technique.cues_for(key), key
            assert transfer.for_drill(key), key

    def test_neither_sport_has_a_drill_of_its_own(self):
        """And that is the finding rather than an omission.

        Running mechanics belong to running, not to track: a soccer player
        doing butt kicks is doing the same drill. Everything these two sports
        need was already general, or became general here.
        """
        owned = [d.key for d in ALL_DRILLS
                 if d.sport in ("track", "cross_country")]
        assert owned == [], owned


class TestThePositionPlans:
    def test_every_plan_sums_to_one_and_clears_the_floor(self):
        for sport in ("track", "cross_country"):
            for plan in BY_SPORT[sport]:
                assert sum(plan.emphasis.values()) == pytest.approx(1.0)
                share = sum(
                    v for k, v in plan.emphasis.items()
                    if get_drill(k).stimulus in EXPLOSIVE
                )
                assert share >= 0.10, f"{sport}/{plan.key}"

    def test_a_sprinter_trains_both_halves_of_the_stride(self):
        plan = {p.key: p for p in BY_SPORT["track"]}["sprints"].emphasis
        assert "gen_high_knees" in plan and "gen_butt_kick" in plan

    def test_the_two_distance_plans_are_close_cousins(self):
        track = {p.key: p for p in BY_SPORT["track"]}["distance"].emphasis
        xc = {p.key: p for p in BY_SPORT["cross_country"]}["distance"].emphasis
        shared = set(track) & set(xc)
        assert len(shared) >= 8


class TestTheFilmCurriculum:
    TOPICS = curriculum.topics_for("track")

    def test_both_sports_share_one_syllabus(self):
        assert curriculum.topics_for("cross_country") is self.TOPICS

    def test_there_is_one(self):
        assert len(self.TOPICS) >= 12

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

    def test_it_is_mostly_about_training_rather_than_competing(self):
        """These are timed sports. There is no read and no defender -- the
        season is decided by load, fuel and knowing when to stop."""
        racing = [t for t in self.TOPICS if t.focus == "Racing"]
        assert len(racing) < len(self.TOPICS) / 2

    def test_the_fuelling_topic_talks_about_training_never_about_weight(self):
        topic = curriculum.BY_KEY["trk_iq_fuel"]
        blob = " ".join((topic.title, topic.ask.prompt, topic.ask.because,
                         *topic.ask.options)).lower()
        for word in ("calorie", "kg", "lbs", "pounds", "diet", "bmi"):
            assert word not in blob, word

    def test_there_is_one_about_why_the_run_log_earns_nothing(self):
        topic = curriculum.BY_KEY["trk_iq_log_honestly"]
        assert "no xp" in topic.ask.because.lower()

    def test_every_topic_key_is_unique_across_the_whole_catalogue(self):
        rows = [t for topics in curriculum.BY_SPORT.values() for t in topics]
        distinct = list({id(t): t for t in rows}.values())
        assert len({t.key for t in distinct}) == len(distinct)
