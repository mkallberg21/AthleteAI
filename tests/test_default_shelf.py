"""The default Lacrosse IQ shelf: what a player watches until a program adds its own, and how it repeats.

The rules under test, each one a way this feature could quietly go wrong:

* A program that adds nothing still gets a working shelf -- and a sport with no shelf gets nothing.
* A program's own clips always come first; the shelf only fills the room they leave.
* Age caps bind exactly as for any clip: a nine-year-old never gets a clip longer than 75 seconds,
  and an athlete of unknown age is treated as 11-12, the conservative band used everywhere else.
* It comes round again: a watched clip is due after 14 days (7 after a missed question), so a kid does
  not watch it once and forget it -- and a second look never earns XP and is never blocked.
* The director can turn it off; a coach can hide a clip; both stay put across refreshes.
* A video that will not play is taken out of that kid's day without costing them an allowance slot,
  and out of the program after three different kids hit it.
* Default clips never flood or alter a coach's own lists.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from offdays import film, iq_shelf, curriculum
from offdays.db import connect
from offdays.store import Store, StoreError

TODAY = date.today()


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "t.db"))


@pytest.fixture
def org(store):
    return store.create_org("Northshore")


def kid(store, org, name="Sam", age=12, position=None, **kw):
    user = store.create_user(
        org, "athlete", name, birth_year=TODAY.year - age, dominant_hand="right",
        guardian_consent=True, **kw,
    )
    if position:
        team = store.create_team(org, f"Team {name}")
        store.join_team(team["join_code"], user["id"], position=position)
    return user


def offered(store, athlete, org, day=None):
    return store.clips_for_athlete(athlete["id"], org, day=day)


def watch_through(store, athlete, clip, day=None, answer=None):
    """Play a clip to the end, one heartbeat a second, the way test_film does."""
    day = day or TODAY
    started = store.start_watch(athlete["id"], clip["id"], day=day)
    now = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).replace(hour=12)
    length = int(clip["end_s"] - clip["start_s"])
    for sec in range(1, length + 1):
        store.record_beat(athlete["id"], started["watch_id"], float(sec), now=now + timedelta(seconds=sec))
    if answer is not None:
        store.answer_clip(athlete["id"], started["watch_id"], answer)
    return started["watch_id"]


# ---------------------------------------------------------------------------
# The shelf's own data
# ---------------------------------------------------------------------------

class TestTheShelfItself:

    def test_it_is_robust_enough_to_rotate(self):
        """Seventy clips or so: enough that a nine-year-old and a seventeen-year-old each have weeks of new material."""
        assert len(iq_shelf.LACROSSE) >= 60
        under_11 = [c for c in iq_shelf.LACROSSE if c.min_age <= 10]
        teens = [c for c in iq_shelf.LACROSSE if c.min_age <= 15]
        assert len(under_11) >= 12 and len(teens) >= 40

    def test_no_id_is_listed_twice_and_every_id_is_a_real_shape(self):
        ids = [c.video_id for c in iq_shelf.LACROSSE]
        assert len(ids) == len(set(ids))
        for vid in ids:
            assert film.parse_youtube_id(vid) == vid, vid

    @pytest.mark.parametrize("clip", iq_shelf.LACROSSE, ids=lambda c: c.video_id)
    def test_every_clip_fits_the_band_of_the_youngest_player_it_is_shown_to(self, clip):
        band = film.band_for(clip.min_age)
        assert 0 < clip.end_s <= band.clip_max_s, (
            f"{clip.video_id} runs {clip.end_s}s but a {clip.min_age}-year-old is held to {band.clip_max_s}s"
        )

    @pytest.mark.parametrize("clip", iq_shelf.LACROSSE, ids=lambda c: c.video_id)
    def test_every_clip_says_whose_it_is_and_what_to_watch_for(self, clip):
        assert clip.credit and clip.title
        assert len(clip.focus) > 20

    def test_nothing_is_a_highlight_reel(self):
        for clip in iq_shelf.LACROSSE:
            assert film.looks_like_highlights(clip.title) is None, clip.title

    def test_the_youngest_get_a_mix_of_basics_and_reading_the_game(self):
        young = [c for c in iq_shelf.LACROSSE if c.min_age <= 10]
        basics = [c for c in young if c.fundamental]
        iq = [c for c in young if not c.fundamental]
        assert len(basics) >= 4 and len(iq) >= 4, "a beginner shelf is basics AND some reading of the game"

    def test_basics_stop_at_twelve_so_a_teenager_is_not_shown_how_to_catch(self):
        for clip in iq_shelf.LACROSSE:
            if clip.fundamental:
                assert clip.max_age <= iq_shelf.FUNDAMENTAL_MAX_AGE

    def test_both_kinds_of_clip_are_there(self):
        kinds = {c.kind for c in iq_shelf.LACROSSE}
        assert kinds == {"FILM", "TEACH"}
        assert sum(1 for c in iq_shelf.LACROSSE if c.kind == "FILM") >= 20

    def test_goalie_clips_say_so(self):
        goalie = [c for c in iq_shelf.LACROSSE if c.concept == "goalie"]
        assert goalie and all(c.positions == ("goalie",) for c in goalie)

    def test_a_clip_that_names_a_topic_carries_that_topics_question(self):
        asked = [c for c in iq_shelf.LACROSSE if c.topic]
        assert len(asked) >= 5
        for clip in asked:
            topic = curriculum.BY_KEY[clip.topic]
            assert clip.question["prompt"] == topic.ask.prompt
            assert 0 <= clip.question["answer"] < len(clip.question["options"])

    def test_the_curriculum_gained_beginner_topics_with_real_questions(self):
        basics = [t for t in curriculum.topics_for("lacrosse") if t.key.startswith("lax_fund_")]
        assert len(basics) >= 3
        for t in basics:
            assert t.min_age == 0 and t.max_age <= 12 and t.target_s <= 75
            assert t.ask.because and 0 <= t.ask.answer < len(t.ask.options)

    def test_the_version_changes_when_the_content_does(self):
        assert len(iq_shelf.VERSION) == 10


# ---------------------------------------------------------------------------
# Who sees what
# ---------------------------------------------------------------------------

class TestWhatAPlayerSees:

    def test_a_program_that_added_nothing_still_has_a_shelf(self, store, org):
        sam = kid(store, org, age=12)
        feed = offered(store, sam, org)
        assert feed["clips"], "an empty shelf is exactly what this feature exists to prevent"
        assert all(c["shelf"] == "default" for c in feed["clips"])

    def test_the_first_look_copies_the_shelf_in_and_a_second_one_adds_nothing(self, store, org):
        sam = kid(store, org)
        offered(store, sam, org)
        n = store.conn.execute("SELECT COUNT(*) FROM clips WHERE org_id = ? AND shelf = 'default'", (org,)).fetchone()[0]
        assert n == len(iq_shelf.LACROSSE)
        offered(store, sam, org)
        assert store.conn.execute("SELECT COUNT(*) FROM clips WHERE org_id = ?", (org,)).fetchone()[0] == n

    def test_a_nine_year_old_is_never_offered_more_than_seventy_five_seconds(self, store, org):
        nine = kid(store, org, "Nine", age=9)
        for c in offered(store, nine, org)["clips"]:
            assert c["length_s"] <= 75 and c["min_age"] <= 9

    def test_a_seventeen_year_old_gets_the_deeper_clips(self, store, org):
        senior = kid(store, org, "Senior", age=17)
        clips = offered(store, senior, org)["clips"]
        assert clips and all(c["length_s"] <= 200 for c in clips)
        assert all(c["min_age"] >= 15 for c in clips), "a seventeen-year-old gets their own level first, not the nine-year-old clips"

    def test_a_teenager_is_not_shown_the_beginner_basics(self, store, org):
        teen = kid(store, org, "Teen", age=15)
        basics = {c.video_id for c in iq_shelf.LACROSSE if c.fundamental}
        assert not [c for c in offered(store, teen, org)["clips"] if c["video_id"] in basics]

    def test_an_athlete_of_unknown_age_is_treated_as_eleven_to_twelve(self, store, org):
        """The same conservative default used everywhere else a limit depends on age."""
        unknown = store.create_user(org, "athlete", "NoYear", dominant_hand="right", guardian_consent=True)
        for c in offered(store, unknown, org)["clips"]:
            assert c["length_s"] <= film.DEFAULT_BAND.clip_max_s
            assert c["min_age"] <= 12

    def test_goalie_clips_go_to_goalies_only(self, store, org):
        field = kid(store, org, "Field", age=14, position="attack")
        keeper = kid(store, org, "Keeper", age=14, position="goalie")
        goalie_ids = {c.video_id for c in iq_shelf.LACROSSE if c.positions}
        assert not [c for c in offered(store, field, org)["clips"] if c["video_id"] in goalie_ids]
        assert [c for c in offered(store, keeper, org)["clips"] if c["video_id"] in goalie_ids]

    def test_a_clip_for_the_beginners_is_not_offered_to_the_unknown_age_athlete_if_it_runs_long(self, store, org):
        unknown = store.create_user(org, "athlete", "NoYear2", dominant_hand="right", guardian_consent=True)
        assert all(c["length_s"] <= 100 for c in offered(store, unknown, org)["clips"])

    def test_the_players_day_is_still_the_same_size(self, store, org):
        """Shelf clips use the same allowance as any clip, so a default shelf cannot make film into homework."""
        nine = kid(store, org, "Nine", age=9)
        first = offered(store, nine, org)
        assert first["day"]["band"]["daily_clips"] == 2
        for _ in range(2):
            clip = offered(store, nine, org)["clips"][0]
            watch_through(store, nine, clip)
        after = offered(store, nine, org)
        assert after["day"]["spent"] is True
        assert after["clips"] == [], "a grid they cannot watch is an invitation to find them somewhere else"

    def test_every_clip_is_shown_with_whose_it_is(self, store, org):
        sam = kid(store, org)
        assert all(c["credit"] for c in offered(store, sam, org)["clips"])


class TestAProgramsOwnClipsComeFirst:

    def _own(self, store, org, title="Our slide package", end_s=60):
        return store.create_clip(org, "dQw4w9WgXcQ", title, focus="Watch the crease.", start_s=0, end_s=end_s)

    def test_own_clips_lead_the_list(self, store, org):
        sam = kid(store, org, age=12)
        mine = self._own(store, org)
        feed = offered(store, sam, org)
        assert feed["clips"][0]["id"] == mine["id"]
        assert feed["clips"][0].get("shelf", "") == ""

    def test_the_shelf_fills_only_the_room_they_leave(self, store, org):
        sam = kid(store, org, age=12)
        for n in range(12):
            self._own(store, org, title=f"Ours {n}")
        feed = offered(store, sam, org)
        assert len(feed["clips"]) == 12
        assert all(c.get("shelf", "") == "" for c in feed["clips"])

    def test_turning_the_shelf_off_leaves_only_the_programs_own(self, store, org):
        sam = kid(store, org, age=12)
        mine = self._own(store, org)
        store.conn.execute("UPDATE organizations SET default_shelf = 0 WHERE id = ?", (org,))
        store.conn.commit()
        assert [c["id"] for c in offered(store, sam, org)["clips"]] == [mine["id"]]

    def test_turning_it_off_with_no_clips_of_their_own_leaves_the_shelf_empty(self, store, org):
        sam = kid(store, org, age=12)
        store.conn.execute("UPDATE organizations SET default_shelf = 0 WHERE id = ?", (org,))
        store.conn.commit()
        assert offered(store, sam, org)["clips"] == []

    def test_a_sport_with_no_shelf_gets_nothing_and_nothing_breaks(self, store):
        hockey = store.create_org("Rink Rats", sport="hockey")
        sam = kid(store, hockey, age=12)
        assert offered(store, sam, hockey)["clips"] == []
        assert iq_shelf.available(store.conn, hockey) is False

    def test_programs_are_independent(self, store, org):
        other = store.create_org("Other Club")
        a, b = kid(store, org, "A"), kid(store, other, "B")
        offered(store, a, org)
        offered(store, b, other)
        store.conn.execute("UPDATE organizations SET default_shelf = 0 WHERE id = ?", (org,))
        store.conn.commit()
        assert offered(store, a, org)["clips"] == []
        assert offered(store, b, other)["clips"]


# ---------------------------------------------------------------------------
# It comes round again
# ---------------------------------------------------------------------------

def clip(id_, *, fundamental=False, min_age=0, max_age=200):
    return film.Clip(id=id_, org_id=1, provider="youtube", video_id=f"v{id_:010d}", title=f"c{id_}",
                     focus="", end_s=60, min_age=min_age, max_age=12 if fundamental else max_age)


class TestRepetition:
    """`pick` is pure, so the schedule is tested without a database or a clock."""

    def test_new_clips_come_before_repeats(self):
        a, b, c = clip(1), clip(2), clip(3)
        history = {1: ((TODAY - timedelta(days=30)).isoformat(), False)}
        got = [x[0].id for x in iq_shelf.pick([a, b, c], history, today=TODAY, room=3)]
        assert got == [2, 3, 1]

    def test_a_clip_seen_this_week_is_not_offered_again_yet(self):
        a = clip(1)
        history = {1: ((TODAY - timedelta(days=3)).isoformat(), False)}
        assert iq_shelf.pick([a], history, today=TODAY, room=3) == []

    def test_it_is_due_after_fourteen_days_and_not_before(self):
        a = clip(1)
        just_before = {1: ((TODAY - timedelta(days=iq_shelf.REVISIT_AFTER_DAYS - 1)).isoformat(), False)}
        on_the_day = {1: ((TODAY - timedelta(days=iq_shelf.REVISIT_AFTER_DAYS)).isoformat(), False)}
        assert iq_shelf.pick([a], just_before, today=TODAY, room=3) == []
        assert [x[0].id for x in iq_shelf.pick([a], on_the_day, today=TODAY, room=3)] == [1]

    def test_a_missed_question_brings_it_back_in_a_week(self):
        a = clip(1)
        week_ago = {1: ((TODAY - timedelta(days=iq_shelf.MISSED_REVISIT_AFTER_DAYS)).isoformat(), True)}
        same_age_but_got_it = {1: ((TODAY - timedelta(days=iq_shelf.MISSED_REVISIT_AFTER_DAYS)).isoformat(), False)}
        assert [x[0].id for x in iq_shelf.pick([a], week_ago, today=TODAY, room=3)] == [1]
        assert iq_shelf.pick([a], same_age_but_got_it, today=TODAY, room=3) == []

    def test_the_one_seen_longest_ago_comes_back_first(self):
        a, b = clip(1), clip(2)
        history = {1: ((TODAY - timedelta(days=20)).isoformat(), False),
                   2: ((TODAY - timedelta(days=40)).isoformat(), False)}
        assert [x[0].id for x in iq_shelf.pick([a, b], history, today=TODAY, room=3)] == [2, 1]

    def test_it_reports_how_long_since_a_repeat_was_last_seen(self):
        a = clip(1)
        history = {1: ((TODAY - timedelta(days=21)).isoformat(), False)}
        (_, days), = iq_shelf.pick([a], history, today=TODAY, room=3)
        assert days == 21
        (_, days_new), = iq_shelf.pick([clip(2)], {}, today=TODAY, room=3)
        assert days_new is None

    def test_room_is_respected(self):
        assert len(iq_shelf.pick([clip(i) for i in range(1, 9)], {}, today=TODAY, room=3)) == 3
        assert iq_shelf.pick([clip(1)], {}, today=TODAY, room=0) == []

    def test_the_young_alternate_basics_and_reading_the_game(self):
        basics = [clip(i, fundamental=True) for i in (1, 2, 3)]
        iq = [clip(i) for i in (4, 5, 6)]
        got = [x[0] for x in iq_shelf.pick(basics + iq, {}, today=TODAY, room=6, young=True)]
        kinds = [iq_shelf.is_fundamental(c) for c in got]
        assert kinds == [True, False, True, False, True, False]

    def test_older_players_are_not_reordered_by_kind(self):
        basics = [clip(i, fundamental=True) for i in (1, 2)]
        iq = [clip(i) for i in (3, 4)]
        assert [x[0].id for x in iq_shelf.pick(basics + iq, {}, today=TODAY, room=4, young=False)] == [1, 2, 3, 4]

    def test_new_clips_nearest_the_players_own_age_come_first(self):
        easy, middle, deep = clip(1, min_age=9), clip(2, min_age=13), clip(3, min_age=17)
        got = [x[0].id for x in iq_shelf.pick([easy, middle, deep], {}, today=TODAY, room=3, age=17)]
        assert got == [3, 2, 1]
        got = [x[0].id for x in iq_shelf.pick([easy, middle], {}, today=TODAY, room=3, age=14)]
        assert got == [2, 1]

    def test_a_clip_for_the_players_position_leads_even_if_it_is_written_for_younger_players(self):
        field = [clip(i, min_age=13) for i in (1, 2, 3, 4)]
        keeper = film.Clip(id=9, org_id=1, provider="youtube", video_id="v0000000009", title="g", focus="",
                           end_s=60, min_age=9, positions=("goalie",))
        got = [x[0].id for x in iq_shelf.pick(field + [keeper], {}, today=TODAY, room=4, age=14)]
        assert got[0] == 9

    def test_the_shelfs_own_order_breaks_ties(self):
        a, b, c = clip(1, min_age=11), clip(2, min_age=11), clip(3, min_age=11)
        assert [x[0].id for x in iq_shelf.pick([a, b, c], {}, today=TODAY, room=3, age=13)] == [1, 2, 3]


class TestRepetitionThroughTheStore:

    def _shelf_clips(self, store, org):
        return [dict(r) for r in store.conn.execute(
            "SELECT * FROM clips WHERE org_id = ? AND shelf = 'default' ORDER BY id", (org,))]

    def test_a_clip_watched_today_is_offered_back_as_a_second_look_not_a_new_one(self, store, org):
        sam = kid(store, org, age=12)
        first = offered(store, sam, org)["clips"][0]
        watch_through(store, sam, first)
        feed = offered(store, sam, org)
        assert first["id"] not in [c["id"] for c in feed["clips"]]
        assert first["id"] in [c["id"] for c in feed["again"]]

    def test_watched_two_weeks_ago_it_comes_round_again(self, store, org):
        sam = kid(store, org, age=12)
        feed = offered(store, sam, org)
        target = feed["clips"][0]
        long_ago = TODAY - timedelta(days=iq_shelf.REVISIT_AFTER_DAYS + 1)
        watch_through(store, sam, target, day=long_ago)
        # make everything else already-seen so only the repeat can be offered
        for c in self._shelf_clips(store, org):
            if c["id"] != target["id"]:
                store.conn.execute(
                    "INSERT OR IGNORE INTO clip_watches(athlete_id, clip_id, day, started_at, last_beat_at, verdict, looks) "
                    "VALUES (?,?,?,?,?, 'watched', 1)",
                    (sam["id"], c["id"], (TODAY - timedelta(days=2)).isoformat(), "x", "x"),
                )
        store.conn.commit()
        again = offered(store, sam, org)["clips"]
        assert [c["id"] for c in again] == [target["id"]]
        assert again[0]["days_since"] >= iq_shelf.REVISIT_AFTER_DAYS

    def test_one_seen_last_week_is_not_pushed_again(self, store, org):
        sam = kid(store, org, age=12)
        target = offered(store, sam, org)["clips"][0]
        watch_through(store, sam, target, day=TODAY - timedelta(days=5))
        assert target["id"] not in [c["id"] for c in offered(store, sam, org)["clips"]]

    def test_a_missed_answer_brings_the_clip_back_sooner(self, store, org):
        sam = kid(store, org, age=12)
        target = next(c for c in offered(store, sam, org)["clips"] if c.get("question"))
        wrong = (target["question"]["options"] and 0)
        # find a wrong choice for it
        real = next(x for x in iq_shelf.LACROSSE if x.video_id == target["video_id"]).question["answer"]
        wrong = 0 if real != 0 else 1
        eight_days_ago = TODAY - timedelta(days=iq_shelf.MISSED_REVISIT_AFTER_DAYS + 1)
        watch_through(store, sam, target, day=eight_days_ago, answer=wrong)
        for c in self._shelf_clips(store, org):
            if c["id"] != target["id"]:
                store.conn.execute(
                    "INSERT OR IGNORE INTO clip_watches(athlete_id, clip_id, day, started_at, last_beat_at, verdict, looks) "
                    "VALUES (?,?,?,?,?, 'watched', 1)",
                    (sam["id"], c["id"], (TODAY - timedelta(days=2)).isoformat(), "x", "x"),
                )
        store.conn.commit()
        assert [c["id"] for c in offered(store, sam, org)["clips"]] == [target["id"]]

    def test_a_second_look_is_never_worth_xp(self, store, org):
        sam = kid(store, org, age=12)
        target = offered(store, sam, org)["clips"][0]
        watch_through(store, sam, target, day=TODAY - timedelta(days=20))
        before = store.athlete_stats(sam["id"]).total_xp
        started = store.start_watch(sam["id"], target["id"], day=TODAY)
        now = datetime.now(timezone.utc)
        out = None
        for sec in range(1, int(target["end_s"] - target["start_s"]) + 1):
            out = store.record_beat(sam["id"], started["watch_id"], float(sec), now=now + timedelta(seconds=sec))
        assert out["xp_awarded"] == 0
        assert store.athlete_stats(sam["id"]).total_xp == before

    def test_every_clip_is_eventually_seen_before_any_repeats(self, store, org):
        """New material first: a kid works through the whole shelf for their age before a repeat shows up."""
        sam = kid(store, org, age=12)
        eligible = [c for c in iq_shelf.LACROSSE if c.min_age <= 12 and c.end_s <= 100 and not c.positions]
        seen = set()
        for offset in range(60, 0, -1):
            day = TODAY - timedelta(days=offset)
            feed = offered(store, sam, org, day=day)
            if not feed["clips"]:
                continue
            pick = feed["clips"][0]
            assert pick["video_id"] not in seen or len(seen) >= len(eligible), "a repeat before the shelf was used up"
            seen.add(pick["video_id"])
            watch_through(store, sam, pick, day=day)
        assert len(seen) >= min(len(eligible), 12)


# ---------------------------------------------------------------------------
# The coach's side
# ---------------------------------------------------------------------------

class TestTheCoachSide:

    def test_default_clips_do_not_flood_the_coachs_own_coverage_list(self, store, org):
        sam = kid(store, org)
        store.create_clip(org, "dQw4w9WgXcQ", "Ours", focus="x", end_s=60)
        offered(store, sam, org)
        cov = store.clip_coverage(org, [sam["id"]])
        assert [c["title"] for c in cov["clips"]] == ["Ours"]

    def test_the_summary_lists_the_whole_shelf_with_a_preview_link(self, store, org):
        sam = kid(store, org)
        s = iq_shelf.summary(store.conn, org, [sam["id"]])
        assert s["available"] and s["on"] and s["total"] == len(iq_shelf.LACROSSE)
        assert all(c["watch_url"].startswith("https://www.youtube.com/watch?v=") for c in s["clips"])
        assert all(c["credit"] and c["seconds"] > 0 for c in s["clips"])

    def test_the_summary_says_there_is_no_shelf_for_another_sport(self, store):
        hockey = store.create_org("Rink Rats", sport="hockey")
        s = iq_shelf.summary(store.conn, hockey, [])
        assert s["available"] is False and "no default shelf" in s["note"]

    def test_it_counts_who_has_watched_without_naming_anyone(self, store, org):
        a, b = kid(store, org, "A"), kid(store, org, "B")
        watch_through(store, a, offered(store, a, org)["clips"][0])
        s = iq_shelf.summary(store.conn, org, [a["id"], b["id"]])
        assert s["athletes_watching"] == 1
        assert "athletes" not in s or not isinstance(s.get("athletes"), list)

    def test_a_hidden_clip_is_not_offered_and_stays_hidden_after_a_refresh(self, store, org):
        sam = kid(store, org, age=12)
        target = offered(store, sam, org)["clips"][0]
        assert store.set_shelf_clip_hidden(org, target["id"], True) is True
        assert target["id"] not in [c["id"] for c in offered(store, sam, org)["clips"]]
        # a new release of the shelf re-syncs titles and lengths but must not un-hide it
        store.conn.execute("DELETE FROM meta WHERE key = ?", (f"iq_shelf:{org}",))
        store.conn.commit()
        assert target["id"] not in [c["id"] for c in offered(store, sam, org)["clips"]]
        assert store.set_shelf_clip_hidden(org, target["id"], False) is True
        assert target["id"] in [c["id"] for c in offered(store, sam, org)["clips"]]

    def test_a_coach_cannot_hide_another_programs_clip(self, store, org):
        other = store.create_org("Other")
        b = kid(store, other, "B")
        theirs = offered(store, b, other)["clips"][0]
        assert store.set_shelf_clip_hidden(org, theirs["id"], True) is False
        assert theirs["id"] in [c["id"] for c in offered(store, b, other)["clips"]]

    def test_only_a_default_clip_can_be_hidden_this_way(self, store, org):
        own = store.create_clip(org, "dQw4w9WgXcQ", "Ours", focus="x", end_s=60)
        assert store.set_shelf_clip_hidden(org, own["id"], True) is False

    def test_a_refresh_after_a_new_release_updates_without_duplicating(self, store, org):
        sam = kid(store, org)
        offered(store, sam, org)
        store.conn.execute("UPDATE clips SET title = 'stale' WHERE org_id = ? AND shelf = 'default'", (org,))
        store.conn.execute("DELETE FROM meta WHERE key = ?", (f"iq_shelf:{org}",))
        store.conn.commit()
        offered(store, sam, org)
        rows = store.conn.execute("SELECT title FROM clips WHERE org_id = ? AND shelf = 'default'", (org,)).fetchall()
        assert len(rows) == len(iq_shelf.LACROSSE)
        assert "stale" not in {r["title"] for r in rows}

    def test_the_athletes_first_checklist_offers_film_even_before_anyone_added_a_clip(self, store, org):
        from offdays import onboarding
        sam = kid(store, org)
        steps = onboarding.athlete_progress(store.conn, sam["id"])["steps"]
        assert "film" in [step["key"] for step in steps]
        store.conn.execute("UPDATE organizations SET default_shelf = 0 WHERE id = ?", (org,))
        store.conn.commit()
        steps = onboarding.athlete_progress(store.conn, sam["id"])["steps"]
        assert "film" not in [step["key"] for step in steps], "no shelf and no clips: nothing to tell a kid to watch"


# ---------------------------------------------------------------------------
# A video that will not play
# ---------------------------------------------------------------------------

class TestADeadVideo:

    def _start(self, store, org, age=12):
        sam = kid(store, org, age=age)
        target = offered(store, sam, org)["clips"][0]
        started = store.start_watch(sam["id"], target["id"])
        return sam, target, started["watch_id"]

    def test_reporting_it_gives_the_kid_their_slot_back(self, store, org):
        sam, target, watch = self._start(store, org)
        assert store.film_day(sam["id"]).clips == 1
        store.report_unplayable(sam["id"], watch)
        assert store.film_day(sam["id"]).clips == 0, "a dead link must not eat one of two daily clips"

    def test_it_is_not_offered_to_that_kid_again(self, store, org):
        sam, target, watch = self._start(store, org)
        store.report_unplayable(sam["id"], watch)
        assert target["id"] not in [c["id"] for c in offered(store, sam, org)["clips"]]

    def test_one_kid_reporting_it_repeatedly_counts_once(self, store, org):
        """Five days in a row is five watch rows but one child: it must not read as five complaints."""
        sam, target, _ = self._start(store, org)
        for back in range(1, 6):
            w = store.start_watch(sam["id"], target["id"], day=TODAY - timedelta(days=back))["watch_id"]
            store.report_unplayable(sam["id"], w)
        n = store.conn.execute("SELECT unavailable_n FROM clips WHERE id = ?", (target["id"],)).fetchone()[0]
        assert n == 1
        fresh = kid(store, org, "Fresh", age=12)
        assert target["id"] in [c["id"] for c in offered(store, fresh, org)["clips"]], \
            "one child's retries must not take a clip away from everyone else"

    def test_three_different_kids_take_it_off_the_program(self, store, org):
        first = kid(store, org, "K0", age=12)
        target = offered(store, first, org)["clips"][0]
        for i in range(iq_shelf.UNAVAILABLE_LIMIT):
            k = first if i == 0 else kid(store, org, f"K{i}", age=12)
            w = store.start_watch(k["id"], target["id"])["watch_id"]
            store.report_unplayable(k["id"], w)
        fresh = kid(store, org, "Fresh", age=12)
        assert target["id"] not in [c["id"] for c in offered(store, fresh, org)["clips"]]
        summary = iq_shelf.summary(store.conn, org, [])
        row = next(c for c in summary["clips"] if c["id"] == target["id"])
        assert row["unavailable"] == iq_shelf.UNAVAILABLE_LIMIT

    def test_two_kids_are_not_enough(self, store, org):
        first = kid(store, org, "K0", age=12)
        target = offered(store, first, org)["clips"][0]
        for i in range(iq_shelf.UNAVAILABLE_LIMIT - 1):
            k = first if i == 0 else kid(store, org, f"K{i}", age=12)
            w = store.start_watch(k["id"], target["id"])["watch_id"]
            store.report_unplayable(k["id"], w)
        fresh = kid(store, org, "Fresh", age=12)
        assert target["id"] in [c["id"] for c in offered(store, fresh, org)["clips"]]

    def test_restoring_a_clip_clears_the_complaints(self, store, org):
        first = kid(store, org, "K0", age=12)
        target = offered(store, first, org)["clips"][0]
        for i in range(iq_shelf.UNAVAILABLE_LIMIT):
            k = first if i == 0 else kid(store, org, f"K{i}", age=12)
            w = store.start_watch(k["id"], target["id"])["watch_id"]
            store.report_unplayable(k["id"], w)
        store.set_shelf_clip_hidden(org, target["id"], False)
        fresh = kid(store, org, "Fresh", age=12)
        assert target["id"] in [c["id"] for c in offered(store, fresh, org)["clips"]]

    def test_a_kid_cannot_report_someone_elses_watch(self, store, org):
        a = kid(store, org, "A", age=12)
        b = kid(store, org, "B", age=12)
        target = offered(store, a, org)["clips"][0]
        w = store.start_watch(a["id"], target["id"])["watch_id"]
        with pytest.raises(StoreError):
            store.report_unplayable(b["id"], w)

    def test_a_watch_with_real_progress_is_kept_when_reported(self, store, org):
        """If they got through most of it, the clip played; do not delete real watching."""
        sam, target, watch = self._start(store, org)
        store.record_beat(sam["id"], watch, 20.0, now=datetime.now(timezone.utc) + timedelta(seconds=20))
        store.report_unplayable(sam["id"], watch)
        assert store.conn.execute("SELECT COUNT(*) FROM clip_watches WHERE id = ?", (watch,)).fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Over the wire
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient
    from offdays import api

    store = Store(connect(tmp_path / "wire.db"))
    api.app.dependency_overrides[api.get_store] = lambda: store
    test_client = TestClient(api.app)
    test_client.store = store
    yield test_client
    api.app.dependency_overrides.clear()


def program(client):
    res = client.post("/api/orgs", json={"name": "Northshore", "director_name": "Dir"}).json()
    director = {"Authorization": f"Bearer {res['director']['token']}"}
    return res, director


def make_athlete(client, director, name="Sam", age=12):
    res = client.post("/api/athletes", json={"display_name": name, "birth_year": TODAY.year - age, "dominant_hand": "right",
                                              "guardian_consent": True}, headers=director)
    assert res.status_code in (200, 201), res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


class TestOverTheWire:

    def test_a_new_program_gives_its_athletes_a_shelf_with_no_setup(self, client):
        _, director = program(client)
        sam = make_athlete(client, director)
        body = client.get("/api/film", headers=sam).json()
        assert body["clips"] and body["clips"][0]["credit"]

    def test_the_answer_is_not_sent_with_the_clip(self, client):
        _, director = program(client)
        sam = make_athlete(client, director)
        for c in client.get("/api/film", headers=sam).json()["clips"]:
            if c.get("question"):
                assert "answer" not in c["question"] and "because" not in c["question"]

    def test_a_coach_sees_the_shelf_and_the_switch(self, client):
        _, director = program(client)
        body = client.get("/api/coach/shelf", headers=director).json()
        assert body["available"] and body["on"] and body["total"] == len(iq_shelf.LACROSSE)

    def test_only_a_director_can_switch_it_off(self, client):
        res, director = program(client)
        store = client.store
        org_id = store.authenticate(res["director"]["token"]).org_id
        coach = store.create_user(org_id, "coach", "Asst")
        asst = {"Authorization": f"Bearer {coach['token']}"}
        assert client.put("/api/org/shelf", json={"on": False}, headers=asst).status_code == 403
        assert client.put("/api/org/shelf", json={"on": False}, headers=director).status_code == 200
        assert client.get("/api/coach/shelf", headers=director).json()["on"] is False

    def test_off_means_the_athlete_sees_nothing_from_it(self, client):
        _, director = program(client)
        sam = make_athlete(client, director)
        client.put("/api/org/shelf", json={"on": False}, headers=director)
        assert client.get("/api/film", headers=sam).json()["clips"] == []

    def test_a_coach_can_hide_and_restore_a_clip(self, client):
        _, director = program(client)
        sam = make_athlete(client, director)
        target = client.get("/api/film", headers=sam).json()["clips"][0]
        assert client.put(f"/api/coach/shelf/clips/{target['id']}", json={"hidden": True}, headers=director).status_code == 200
        assert target["id"] not in [c["id"] for c in client.get("/api/film", headers=sam).json()["clips"]]
        assert client.put(f"/api/coach/shelf/clips/{target['id']}", json={"hidden": False}, headers=director).status_code == 200
        assert target["id"] in [c["id"] for c in client.get("/api/film", headers=sam).json()["clips"]]

    def test_an_athlete_cannot_reach_the_coach_routes(self, client):
        _, director = program(client)
        sam = make_athlete(client, director)
        assert client.get("/api/coach/shelf", headers=sam).status_code in (401, 403)
        assert client.put("/api/org/shelf", json={"on": False}, headers=sam).status_code in (401, 403)

    def test_the_players_report_route_works_and_returns_the_slot(self, client):
        _, director = program(client)
        sam = make_athlete(client, director)
        target = client.get("/api/film", headers=sam).json()["clips"][0]
        watch = client.post(f"/api/film/{target['id']}/start", headers=sam).json()["watch_id"]
        res = client.post(f"/api/film/watches/{watch}/unavailable", headers=sam)
        assert res.status_code == 200
        after = client.get("/api/film", headers=sam).json()
        assert after["day"]["clips"] == 0 and target["id"] not in [c["id"] for c in after["clips"]]

    def test_the_coachs_own_clip_list_is_not_flooded(self, client):
        _, director = program(client)
        sam = make_athlete(client, director)
        client.get("/api/film", headers=sam)           # copies the shelf in
        assert client.get("/api/coach/clips", headers=director).json()["clips"] == []

    def test_a_coach_cannot_delete_a_default_clip_through_the_ordinary_route_and_lose_the_restore(self, client):
        """The ordinary delete still works (it is how a coach hides one), and the shelf summary still lists it as hidden."""
        _, director = program(client)
        sam = make_athlete(client, director)
        target = client.get("/api/film", headers=sam).json()["clips"][0]
        client.delete(f"/api/coach/clips/{target['id']}", headers=director)
        row = next(c for c in client.get("/api/coach/shelf", headers=director).json()["clips"] if c["id"] == target["id"])
        assert row["hidden"] is True
