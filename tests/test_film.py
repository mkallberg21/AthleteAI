"""Film study: attention, not playback, and a hard cap on minutes."""

from datetime import date, datetime, timedelta, timezone

import pytest

from athleteiq import film as F
from athleteiq.db import connect
from athleteiq.store import Store, StoreError

TODAY = date.today()


def watch(length_s, *, muted=False, hidden=False, rate=1.0, step=0.5, stop_at=None):
    """Play a clip through, one heartbeat at a time."""
    state = F.WatchState(length_s=length_s)
    position = 0.0
    limit = stop_at if stop_at is not None else length_s
    while position < limit:
        position = min(limit, position + step * rate)
        F.apply_beat(state, position, step, muted=muted, hidden=hidden, rate=rate)
    return state


class TestParsingWhateverACoachPasted:

    @pytest.mark.parametrize("raw", [
        "dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?t=30&v=dQw4w9WgXcQ&feature=share",
        "https://youtu.be/dQw4w9WgXcQ?t=12",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "  https://youtu.be/dQw4w9WgXcQ  ",
    ])
    def test_every_shape_a_coach_actually_pastes(self, raw):
        assert F.parse_youtube_id(raw) == "dQw4w9WgXcQ"

    @pytest.mark.parametrize("raw", ["", "not a link", "https://example.com/x", "abc"])
    def test_junk_is_refused(self, raw):
        assert F.parse_youtube_id(raw) is None

    def test_the_embed_uses_the_privacy_enhanced_host(self):
        url = F.embed_url("youtube", "dQw4w9WgXcQ", 12, 72)
        assert url.startswith("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?")
        assert "start=12" in url and "end=72" in url
        # No grid of unrelated recommendations after a clip aimed at a child.
        assert "rel=0" in url


class TestWatchingIsNotPlaying:
    """The user asked for the athletes who take the time to listen to the
    whole thing. These are the ways of not doing that."""

    def test_a_clip_watched_properly_counts(self):
        state = watch(90)
        assert state.coverage == 1.0
        assert F.assess(state) == F.Verdict.WATCHED

    def test_a_muted_clip_does_not(self):
        """The coaching is in the audio. A silent clip is a moving picture."""
        assert F.assess(watch(90, muted=True)) == F.Verdict.BACKGROUND

    def test_a_backgrounded_tab_does_not(self):
        assert F.assess(watch(90, hidden=True)) == F.Verdict.BACKGROUND

    def test_racing_through_it_does_not(self):
        assert F.assess(watch(90, rate=2.0)) == F.Verdict.SKIMMED

    def test_a_normal_slightly_quick_watch_still_counts(self):
        """1.25x is how people watch things. The line is above it, not below."""
        assert F.assess(watch(90, rate=1.25)) == F.Verdict.WATCHED

    def test_stopping_early_is_partial(self):
        assert F.assess(watch(90, stop_at=40)) == F.Verdict.PARTIAL

    def test_scrubbing_to_the_end_earns_nothing(self):
        state = F.WatchState(length_s=90)
        F.apply_beat(state, 88.0, 1.0)
        assert state.watched_s == 0.0
        assert state.seeks == 1
        assert F.assess(state) == F.Verdict.PARTIAL

    def test_rewatching_the_opening_is_not_watching_the_clip(self):
        """Coverage counts distinct seconds, so a loop of the first ten does
        not add up to the whole thing."""
        state = F.WatchState(length_s=90)
        for _ in range(20):
            state.position_s = 0.0
            for _ in range(20):
                F.apply_beat(state, state.position_s + 0.5, 0.5)
        assert state.watched_s > 90, "plenty of playback"
        assert state.coverage < 0.2, "and almost none of the clip"
        assert F.assess(state) == F.Verdict.PARTIAL

    def test_a_suspended_tab_is_not_credited_for_the_gap(self):
        """A phone locked for ten minutes is not ten minutes of film study."""
        state = F.WatchState(length_s=600)
        F.apply_beat(state, 300.0, 600.0)
        assert state.watched_s <= F.MAX_BEAT_GAP_S * F.PACING_TOLERANCE


class TestTheDailyAllowanceIsSmall:

    @pytest.mark.parametrize("age,cap", [(9, 4), (12, 6), (14, 9), (16, 12), (18, 15)])
    def test_it_scales_with_age_and_stays_in_single_or_low_double_digits(self, age, cap):
        assert F.band_for(age).daily_minutes == cap

    def test_the_youngest_get_the_shortest_clips(self):
        assert F.band_for(9).clip_max_s < F.band_for(18).clip_max_s
        assert F.band_for(9).clip_max_s <= 90

    def test_an_unknown_age_gets_a_conservative_allowance(self):
        assert F.band_for(None) is F.DEFAULT_BAND
        assert F.band_for(15, estimated=True) is F.DEFAULT_BAND

    def test_it_says_enough_rather_than_going_quiet(self):
        state = F.DayState(F.band_for(12), minutes=6, clips=3)
        assert state.spent
        assert "not an evening" in state.message()

    def test_nothing_here_encourages_more(self):
        banned = ("keep going", "more clips", "beat", "rank", "top")
        for clips in (0, 1, 3):
            state = F.DayState(F.band_for(12), minutes=clips * 2, clips=clips)
            for word in banned:
                assert word not in state.message().lower()


class TestThroughTheStore:

    @pytest.fixture
    def store(self, tmp_path):
        return Store(connect(tmp_path / "t.db"))

    @pytest.fixture
    def org(self, store):
        return store.create_org("Northshore")

    @pytest.fixture
    def athlete(self, store, org):
        return store.create_user(
            org, "athlete", "Sam", birth_year=TODAY.year - 12, dominant_hand="right",
        )

    def _clip(self, store, org, **kw):
        body = {"start_s": 0, "end_s": 60, "focus": "Watch the crease defender."}
        body.update(kw)
        return store.create_clip(org, "dQw4w9WgXcQ", body.pop("title", "Sliding early"), **body)

    def _play(self, store, athlete_id, clip, seconds=60, **kw):
        started = store.start_watch(athlete_id, clip["id"])
        now = datetime.now(timezone.utc)
        position, out = 0.0, None
        while position < seconds:
            position = min(seconds, position + 1.0)
            now += timedelta(seconds=1)
            out = store.record_beat(athlete_id, started["watch_id"], position, now=now, **kw)
        return started["watch_id"], out

    def test_a_watched_clip_earns_a_little_xp(self, store, org, athlete):
        clip = self._clip(store, org)
        _, out = self._play(store, athlete["id"], clip)
        assert out["verdict"] == "watched"
        assert out["xp_awarded"] == F.XP_PER_WATCH

    def test_a_backgrounded_one_earns_none(self, store, org, athlete):
        clip = self._clip(store, org)
        _, out = self._play(store, athlete["id"], clip, muted=True)
        assert out["verdict"] == "background"
        assert out["xp_awarded"] == 0

    def test_film_xp_is_capped_well_below_a_training_day(self, store, org, athlete):
        """A kid must not be able to out-earn training by watching video."""
        from athleteiq.config import CONFIG
        assert F.XP_DAILY_CAP < CONFIG.scoring.daily_xp_cap / 4

    def test_film_keeps_its_own_streak(self, store, org, athlete):
        self._play(store, athlete["id"], self._clip(store, org))
        assert store.film_history(athlete["id"])["streak"] == 1

    def test_film_alone_does_not_hold_the_training_streak(self, store, org, athlete):
        """Otherwise a streak can be maintained from the sofa, which is the
        opposite of what the streak is for."""
        self._play(store, athlete["id"], self._clip(store, org))
        assert TODAY not in store._streak_days(athlete["id"])

    def test_a_backgrounded_clip_does_not_hold_the_film_streak_either(
        self, store, org, athlete,
    ):
        self._play(store, athlete["id"], self._clip(store, org), muted=True)
        assert store.film_history(athlete["id"])["streak"] == 0

    def test_the_day_stops_offering_clips_once_it_is_spent(self, store, org, athlete):
        for n in range(6):
            self._play(store, athlete["id"], self._clip(store, org, title=f"C{n}"))
            shortlist = store.clips_for_athlete(athlete["id"], org)
            if shortlist["day"]["spent"]:
                assert shortlist["clips"] == [], "a grid they cannot watch is an invitation"
                return
        pytest.fail("the daily cap never engaged")

    def test_a_clip_already_started_can_always_be_finished(self, store, org, athlete):
        """Stopping a kid halfway through is worse than a minute over."""
        clips = [self._clip(store, org, title=f"C{n}") for n in range(4)]
        started = store.start_watch(athlete["id"], clips[0]["id"])
        for clip in clips[1:]:
            try:
                store.start_watch(athlete["id"], clip["id"])
            except StoreError:
                break
        assert store.start_watch(athlete["id"], clips[0]["id"]) == {
            "watch_id": started["watch_id"], "resumed": True,
        }

    def test_clips_too_long_for_a_band_are_not_offered_to_it(self, store, org, athlete):
        self._clip(store, org, title="Long one", end_s=160)
        assert store.clips_for_athlete(athlete["id"], org)["clips"] == []

    def test_a_ten_minute_clip_cannot_be_curated_at_all(self, store, org):
        with pytest.raises(StoreError, match="capped at"):
            self._clip(store, org, end_s=600)

    def test_a_bad_link_is_refused(self, store, org):
        with pytest.raises(StoreError, match="YouTube link"):
            store.create_clip(org, "https://example.com/video", "Nope")

    def test_the_answer_is_never_sent_to_the_athlete_in_advance(self, store, org, athlete):
        clip = self._clip(store, org, question={
            "prompt": "When did the slide start?",
            "options": ["On the dodge", "A step early", "Too late"],
            "answer": 1, "because": "The help defender reads the hips.",
        })
        offered = store.clips_for_athlete(athlete["id"], org)["clips"][0]
        assert "answer" not in offered["question"]
        assert "because" not in offered["question"]

    def test_getting_it_wrong_costs_nothing(self, store, org, athlete):
        clip = self._clip(store, org, question={
            "prompt": "When?", "options": ["a", "b"], "answer": 1, "because": "Because.",
        })
        watch_id, out = self._play(store, athlete["id"], clip)
        before = store.athlete_stats(athlete["id"]).total_xp
        result = store.answer_clip(athlete["id"], watch_id, 0)
        assert result["correct"] is False
        assert result["because"] == "Because."
        assert store.athlete_stats(athlete["id"]).total_xp == before

    def test_the_coach_view_reports_completions_not_minutes(self, store, org, athlete):
        clip = self._clip(store, org)
        self._play(store, athlete["id"], clip)
        row = store.team_film([athlete["id"]])["athletes"][0]
        assert row["clips_watched"] == 1 and row["days_with_film"] == 1
        assert "minutes" not in row, "minutes are not a thing to rank kids by"

    def test_a_background_watch_shows_as_started_but_not_watched(self, store, org, athlete):
        self._play(store, athlete["id"], self._clip(store, org), muted=True)
        row = store.team_film([athlete["id"]])["athletes"][0]
        assert row["clips_started"] == 1 and row["clips_watched"] == 0
