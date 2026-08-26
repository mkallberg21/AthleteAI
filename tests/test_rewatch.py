"""Second looks, and the rules that keep them from becoming an accusation.

Three properties get tested hardest, because each one is a way this feature
could quietly do the opposite of what it is for.

A second look must never be worth XP -- the moment it pays, the cheapest points
in the product are replaying yesterday's clip with the sound on.

A second look must never be *blocked* -- an athlete who wants to re-check the
slide package the night before a game and is told they have hit their daily
cap has been failed by the one feature meant to help them.

And what a coach sees must be about the clip, not about the child. The same
rows sorted the other way are a list of who is behind.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from offdays import film, rewatch
from offdays.db import connect
from offdays.store import Store, StoreError


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "t.db"))


@pytest.fixture
def program(store):
    org_id = store.create_org("Northshore LC")
    director = store.create_user(org_id, "director", "Dir Smith")
    athletes = [
        store.create_user(
            org_id, "athlete", name, birth_year=2011,
            dominant_hand="right", guardian_consent=True,
        )
        for name in ("Jordan P.", "Sam R.", "Alex T.")
    ]
    clip = store.create_clip(
        org_id, "https://youtu.be/aaaaaaaaaaa",
        "Sliding and recovery",
        focus="Team defence",
        end_s=150,
        question={
            "prompt": "Where does the slide come from?",
            "options": ["The crease", "The wing", "Nowhere"],
            "answer": 0,
            "because": "The crease defender is closest to the ball.",
        },
        created_by=director["id"],
    )
    return {"org_id": org_id, "director": director,
            "athletes": athletes, "clip": clip}


def beat_through(store, athlete_id, clip_id, day):
    """Drive a clip to a credited watch through the real heartbeat path."""
    from datetime import datetime, time, timezone

    started = store.start_watch(athlete_id, clip_id, day)
    watch_id = started["watch_id"]
    clock = datetime.combine(day, time(9, 0), tzinfo=timezone.utc)
    store.conn.execute(
        "UPDATE clip_watches SET last_beat_at = ? WHERE id = ?",
        (clock.isoformat(), watch_id),
    )
    store.conn.commit()
    result = {}
    for second in range(10, 160, 10):
        clock = clock.replace(second=0) + timedelta(seconds=second)
        result = store.record_beat(
            athlete_id, watch_id, float(second), now=clock,
        )
    return result


def watch_fully(store, athlete_id, clip_id, day, *, answer=None):
    """Drive a clip to a full, credited watch on `day`."""
    started = store.start_watch(athlete_id, clip_id, day)
    watch_id = started["watch_id"]
    store.conn.execute(
        "UPDATE clip_watches SET watched_s=?, audible_s=?, focused_s=?, "
        "seen_json=?, verdict=? WHERE id=?",
        (150.0, 150.0, 150.0,
         __import__("json").dumps(list(range(150))), film.Verdict.WATCHED, watch_id),
    )
    store.conn.commit()
    if answer is not None:
        store.answer_clip(athlete_id, watch_id, answer)
    return started


class TestAnAthleteCanAlwaysGoBack:
    def test_a_watched_clip_is_offered_again_rather_than_hidden(self, store, program):
        athlete = program["athletes"][0]
        clip = program["clip"]
        today = date.today()
        watch_fully(store, athlete["id"], clip["id"], today)

        feed = store.clips_for_athlete(athlete["id"], program["org_id"], day=today)
        assert [c["id"] for c in feed["clips"]] == []
        assert [c["id"] for c in feed["again"]] == [clip["id"]]

    def test_starting_it_again_counts_a_second_look(self, store, program):
        athlete = program["athletes"][0]
        clip = program["clip"]
        today = date.today()
        watch_fully(store, athlete["id"], clip["id"], today)

        again = store.start_watch(athlete["id"], clip["id"], today)
        assert again["resumed"] is True
        assert again["looks"] == 2
        assert rewatch.for_athlete(store.conn, athlete["id"], clip["id"]) == 2

    def test_a_half_finished_clip_resumes_rather_than_counting_a_new_look(
        self, store, program
    ):
        # Coming back to something you stopped halfway is not a second look at
        # it, and counting it as one would report a dropped connection to a
        # coach as diligence.
        athlete = program["athletes"][0]
        clip = program["clip"]
        today = date.today()
        store.start_watch(athlete["id"], clip["id"], today)
        again = store.start_watch(athlete["id"], clip["id"], today)
        assert again["looks"] == 1

    def test_looks_accumulate_across_days(self, store, program):
        athlete = program["athletes"][0]
        clip = program["clip"]
        today = date.today()
        watch_fully(store, athlete["id"], clip["id"], today - timedelta(days=2))
        watch_fully(store, athlete["id"], clip["id"], today)
        assert rewatch.for_athlete(store.conn, athlete["id"], clip["id"]) == 2

    def test_a_second_look_is_never_blocked_by_the_daily_cap(self, store, program):
        athlete = program["athletes"][0]
        clip = program["clip"]
        today = date.today()
        watch_fully(store, athlete["id"], clip["id"], today)

        # Spend the day's allowance outright.
        store.conn.execute(
            "UPDATE clip_watches SET watched_s = ? WHERE athlete_id = ?",
            (film.BANDS[-1].daily_minutes * 60 * 4, athlete["id"]),
        )
        store.conn.commit()
        assert store.film_day(athlete["id"], today).spent

        # And still let them re-check something they have already seen.
        again = store.start_watch(athlete["id"], clip["id"], today)
        assert again["looks"] == 2

    def test_the_cap_still_blocks_something_new(self, store, program):
        # The burnout guard has to survive this feature, or the feature ate it.
        athlete = program["athletes"][0]
        other = store.create_clip(
            program["org_id"], "https://youtu.be/bbbbbbbbbbb",
            "Clearing against a ten-man ride", end_s=150,
            created_by=program["director"]["id"],
        )
        today = date.today()
        watch_fully(store, athlete["id"], program["clip"]["id"], today)
        store.conn.execute(
            "UPDATE clip_watches SET watched_s = ? WHERE athlete_id = ?",
            (film.BANDS[-1].daily_minutes * 60 * 4, athlete["id"]),
        )
        store.conn.commit()
        with pytest.raises(StoreError):
            store.start_watch(athlete["id"], other["id"], today)

    def test_a_second_pass_cannot_manufacture_coverage(self, store, program):
        # Restarting must not reset the watch state, or an athlete could
        # scrub through twice and have it read as two honest viewings.
        athlete = program["athletes"][0]
        clip = program["clip"]
        today = date.today()
        watch_fully(store, athlete["id"], clip["id"], today)
        before = store.conn.execute(
            "SELECT watched_s, seen_json FROM clip_watches WHERE athlete_id = ?",
            (athlete["id"],),
        ).fetchone()
        store.start_watch(athlete["id"], clip["id"], today)
        after = store.conn.execute(
            "SELECT watched_s, seen_json FROM clip_watches WHERE athlete_id = ?",
            (athlete["id"],),
        ).fetchone()
        assert after["watched_s"] == before["watched_s"]
        assert after["seen_json"] == before["seen_json"]


class TestItSitsOutsideTheEconomy:
    def test_a_clip_pays_once_ever_not_once_a_day(self, store, program):
        # Driven through record_beat rather than the private award helper,
        # because it is record_beat that writes the row this guard reads --
        # testing the helper alone would pass against a guard that never fires
        # in production.
        athlete = program["athletes"][0]
        clip = program["clip"]
        today = date.today()

        first = beat_through(store, athlete["id"], clip["id"], today - timedelta(days=1))
        assert first["xp_awarded"] == film.XP_PER_WATCH

        second = beat_through(store, athlete["id"], clip["id"], today)
        assert second["xp_awarded"] == 0

    def test_a_different_clip_still_pays(self, store, program):
        # The guard has to be per clip, not "you have had film XP before".
        athlete = program["athletes"][0]
        other = store.create_clip(
            program["org_id"], "https://youtu.be/ccccccccccc",
            "Reading the ride", end_s=150,
            created_by=program["director"]["id"],
        )
        today = date.today()
        beat_through(store, athlete["id"], program["clip"]["id"], today)
        assert beat_through(store, athlete["id"], other["id"], today)["xp_awarded"] > 0

    def test_a_second_look_costs_nothing_either(self, store, program):
        athlete = program["athletes"][0]
        clip = program["clip"]
        today = date.today()
        watch_fully(store, athlete["id"], clip["id"], today)
        before = store.athlete_profile(athlete["id"])["total_xp"]
        for _ in range(5):
            store.start_watch(athlete["id"], clip["id"], today)
        assert store.athlete_profile(athlete["id"])["total_xp"] == before


class TestTheAthleteIsTold:
    def test_the_feed_carries_the_notice(self, store, program):
        feed = store.clips_for_athlete(
            program["athletes"][0]["id"], program["org_id"],
        )
        assert feed["rewatch_notice"] == rewatch.NOTICE

    def test_starting_a_watch_carries_it_too(self, store, program):
        started = store.start_watch(
            program["athletes"][0]["id"], program["clip"]["id"], date.today(),
        )
        assert started["rewatch_notice"] == rewatch.NOTICE

    def test_the_notice_actually_says_the_coach_can_see_it(self):
        assert "coach can see" in rewatch.NOTICE

    def test_the_notice_says_rewatching_is_encouraged_not_tolerated(self):
        assert "as many times as you want" in rewatch.NOTICE

    def test_there_is_a_spanish_version(self):
        assert "entrenador" in rewatch.NOTICE_ES
        assert len(rewatch.NOTICE_ES) > 80


class TestWhatACoachSees:
    def _squad_rewatches(self, store, program, count=3, answers=None):
        today = date.today()
        for i, athlete in enumerate(program["athletes"][:count]):
            answer = None if answers is None else answers[i]
            watch_fully(store, athlete["id"], program["clip"]["id"], today,
                        answer=answer)
            store.start_watch(athlete["id"], program["clip"]["id"], today)
        return [a["id"] for a in program["athletes"]]

    def test_a_single_view_is_not_reported(self, store, program):
        athlete = program["athletes"][0]
        watch_fully(store, athlete["id"], program["clip"]["id"], date.today())
        assert store.second_looks([athlete["id"]])["clips"] == []

    def test_a_second_look_is(self, store, program):
        ids = self._squad_rewatches(store, program, count=1)
        clips = store.second_looks(ids)["clips"]
        assert len(clips) == 1
        assert clips[0]["title"] == "Sliding and recovery"
        assert clips[0]["count"] == 1

    def test_it_groups_by_clip_not_by_athlete(self, store, program):
        ids = self._squad_rewatches(store, program, count=3)
        clips = store.second_looks(ids)["clips"]
        assert len(clips) == 1
        assert clips[0]["count"] == 3
        assert {a["athlete_name"] for a in clips[0]["athletes"]} == {
            "Jordan P.", "Sam R.", "Alex T."
        }

    def test_a_squad_wide_second_look_reads_as_a_practice_plan(self, store, program):
        ids = self._squad_rewatches(store, program, count=3)
        note = store.second_looks(ids)["clips"][0]["note"]
        assert "five minutes on at the next practice" in note

    def test_a_clip_people_came_back_to_and_still_missed_is_flagged(
        self, store, program
    ):
        # The one number here that points at the material rather than the kids.
        ids = self._squad_rewatches(store, program, count=3, answers=[1, 1, 0])
        clip = store.second_looks(ids)["clips"][0]
        assert clip["unsettled"] == 2
        assert "walking through on the field" in clip["note"]

    def test_getting_it_right_after_going_back_counts_as_settled(
        self, store, program
    ):
        athlete = program["athletes"][0]
        today = date.today()
        first = watch_fully(store, athlete["id"], program["clip"]["id"], today)
        store.answer_clip(athlete["id"], first["watch_id"], 1)     # wrong
        store.start_watch(athlete["id"], program["clip"]["id"], today)
        store.answer_clip(athlete["id"], first["watch_id"], 0)     # then right
        clip = store.second_looks([athlete["id"]])["clips"][0]
        assert clip["athletes"][0]["settled"] is True
        assert clip["unsettled"] == 0

    def test_a_clip_with_no_question_is_unsettled_rather_than_wrong(
        self, store, program
    ):
        # None and False are different: "never asked" must not be counted as
        # "got it wrong".
        plain = store.create_clip(
            program["org_id"], "https://youtu.be/ddddddddddd",
            "Off-ball footwork", end_s=150,
            created_by=program["director"]["id"],
        )
        athlete = program["athletes"][0]
        today = date.today()
        watch_fully(store, athlete["id"], plain["id"], today)
        store.start_watch(athlete["id"], plain["id"], today)
        clip = store.second_looks([athlete["id"]])["clips"][0]
        assert clip["athletes"][0]["settled"] is None
        assert clip["unsettled"] == 0

    def test_the_response_says_how_to_read_it(self, store, program):
        ids = self._squad_rewatches(store, program, count=3)
        how = store.second_looks(ids)["how_to_read"]
        assert "not a list of who is struggling" in how

    def test_nothing_in_it_calls_an_athlete_behind(self, store, program):
        # Checked against the notes and phrases a coach actually reads next to
        # a name. `how_to_read` is excluded because it contains these words on
        # purpose, in the sentence saying this is not that.
        ids = self._squad_rewatches(store, program, count=3, answers=[1, 1, 1])
        report = store.second_looks(ids)
        text = " ".join(
            [c["note"] for c in report["clips"]]
            + [a["phrase"] for c in report["clips"] for a in c["athletes"]]
        ).lower()
        for word in ("struggling", "weak", "failed", "poor", "behind", "slow"):
            assert word not in text, word

    def test_the_disclaimer_is_the_only_place_those_words_appear(self, store, program):
        ids = self._squad_rewatches(store, program, count=3)
        assert "struggling" in store.second_looks(ids)["how_to_read"]

    def test_a_third_look_reads_differently_from_a_second(self, store, program):
        athlete = program["athletes"][0]
        today = date.today()
        watch_fully(store, athlete["id"], program["clip"]["id"], today)
        store.start_watch(athlete["id"], program["clip"]["id"], today)
        assert store.second_looks([athlete["id"]])["clips"][0]["athletes"][0]["phrase"] \
            == "took a second look"
        store.start_watch(athlete["id"], program["clip"]["id"], today)
        assert store.second_looks([athlete["id"]])["clips"][0]["athletes"][0]["phrase"] \
            == "kept going back to it"

    def test_the_window_excludes_old_looks(self, store, program):
        athlete = program["athletes"][0]
        old = date.today() - timedelta(days=90)
        watch_fully(store, athlete["id"], program["clip"]["id"], old)
        store.start_watch(athlete["id"], program["clip"]["id"], old)
        assert store.second_looks([athlete["id"]], days=28)["clips"] == []
        assert store.second_looks([athlete["id"]], days=180)["clips"] != []

    def test_no_athletes_is_not_an_error(self, store):
        assert store.second_looks([])["clips"] == []
        assert rewatch.for_clips(None, []) == []


class TestTheShelfStaysIQClips:
    @pytest.mark.parametrize("title", [
        "Top 10 Sick Lacrosse Goals",
        "2024 Season Highlights",
        "Best of Lyle Thompson",
        "Lacrosse Mixtape Vol 3",
        "Nasty Shots Compilation",
    ])
    def test_a_highlight_reel_is_refused(self, store, program, title):
        with pytest.raises(StoreError) as caught:
            store.create_clip(
                program["org_id"], "https://youtu.be/eeeeeeeeeee",
                title, end_s=150, created_by=program["director"]["id"],
            )
        assert "highlight reel" in str(caught.value)

    def test_the_refusal_says_what_to_cut_instead(self, store, program):
        with pytest.raises(StoreError) as caught:
            store.create_clip(
                program["org_id"], "https://youtu.be/eeeeeeeeeee",
                "Top 10 Goals", end_s=150,
                created_by=program["director"]["id"],
            )
        assert "should show a decision" in str(caught.value)

    @pytest.mark.parametrize("title", [
        "Top of the fan spacing",
        "Sliding and recovery",
        "Reading the slide package",
        "Best angle to take on a ground ball",
        "Where the crease defender starts",
    ])
    def test_real_lacrosse_titles_are_not_eaten_by_the_filter(
        self, store, program, title
    ):
        # A filter that blocks "top of the fan" is a filter coaches route
        # around, and then it protects nothing at all.
        clip = store.create_clip(
            program["org_id"], "https://youtu.be/eeeeeeeeeee",
            title, end_s=150, created_by=program["director"]["id"],
        )
        assert clip["title"] == title

    def test_the_guidance_says_the_shot_is_the_wrong_clip(self):
        assert "the interesting part is the shot" in film.WHAT_TO_CUT

    def test_the_markers_are_phrases_not_bare_words(self):
        # Single common words would eat legitimate lacrosse vocabulary.
        for marker in film.HIGHLIGHT_MARKERS:
            assert len(marker) >= 4, marker
