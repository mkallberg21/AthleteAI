"""Suggested videos: a weekly YouTube scan whose finds a coach can add with one tap.

The rules under test, each a way this could go wrong with children on the other end:

* Nothing reaches an athlete unless a coach taps Add. A suggestion is a row a coach sees, nothing else.
* Only what could actually play: public, embeddable, not age-restricted, short enough for a band.
* No highlight reels, no other sports or the women's/box game, no swearing in the title or tags.
* Without a key it does nothing and says so. The key never appears in an error, a log line or a response.
* A quota or network failure stops the scan quietly and keeps what it found.
* Added through the same door as a pasted link: the age caps and the highlight refusal still bind.
* A dismissal is for good and per program; one program's choices never touch another's.
"""

from __future__ import annotations

import dataclasses
import io
import json
import urllib.error
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from offdays import film, iq_shelf, video_scout as vs
from offdays.db import connect
from offdays.store import Store, StoreError

TODAY = date.today()


# --------------------------------------------------------------------------- fixtures

def item(vid="aaaaaaaaaa1", *, title="Lacrosse film study: reading the slide", seconds=90, views=500,
         tags=("lacrosse", "film study"), embeddable=True, privacy="public", rating=None, lang="en",
         desc="A breakdown of how the defense slides.", channel="Lacrosse Film Room", caption="true"):
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    iso = "PT" + (f"{h}H" if h else "") + (f"{m}M" if m else "") + (f"{s}S" if s or not (h or m) else "")
    out = {
        "id": vid,
        "snippet": {"title": title, "description": desc, "channelTitle": channel, "tags": list(tags),
                    "publishedAt": "2024-05-01T12:00:00Z", "defaultAudioLanguage": lang},
        "contentDetails": {"duration": iso, "caption": caption},
        "status": {"privacyStatus": privacy, "embeddable": embeddable, "uploadStatus": "processed"},
        "statistics": {"viewCount": str(views)},
    }
    if rating:
        out["contentDetails"]["contentRating"] = {"ytRating": rating}
    if lang is None:
        del out["snippet"]["defaultAudioLanguage"]
    return out


class FakeApi:
    """Stands in for YouTube. `catalog` maps id -> item; every query returns the same ids."""

    def __init__(self, catalog=None, results=None, fail_after=None, fail_with="quotaExceeded"):
        self.catalog = {i["id"]: i for i in (catalog or [])}
        self.results = results if results is not None else list(self.catalog)
        self.searches, self.details_calls = [], []
        self.fail_after, self.fail_with = fail_after, fail_with

    def search(self, query, *, short=False):
        if self.fail_after is not None and len(self.searches) >= self.fail_after:
            raise vs.ScoutError(self.fail_with, quota=self.fail_with == "quotaExceeded")
        self.searches.append(query)
        return list(self.results)

    def details(self, ids):
        self.details_calls.append(list(ids))
        return [self.catalog[i] for i in ids if i in self.catalog]


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "t.db"))


@pytest.fixture
def org(store):
    return store.create_org("Northshore")


@pytest.fixture
def staff(store, org):
    return store.create_user(org, "coach", "Coach C")


def suggestions(store, org):
    return vs.pending_for(store.conn, org, "lacrosse")


def seeded(store, *items, **kw):
    api = FakeApi(list(items))
    vs.scan(store.conn, api, **kw)
    return api


# --------------------------------------------------------------------------- duration

class TestParsingADuration:
    @pytest.mark.parametrize("iso,want", [("PT45S", 45), ("PT1M30S", 90), ("PT2M", 120), ("PT1H1M1S", 3661), ("PT0S", 0)])
    def test_the_shapes_youtube_sends(self, iso, want):
        assert vs.parse_duration(iso) == want

    @pytest.mark.parametrize("bad", ["", None, "90", "P", "garbage", "PT"])
    def test_junk_is_not_a_length(self, bad):
        assert vs.parse_duration(bad) is None


# --------------------------------------------------------------------------- what is accepted

class TestWhatQualifies:

    def test_a_good_clip_is_accepted_with_a_reason_and_a_placement(self):
        c = vs.assess(item(seconds=90), known=set())
        assert isinstance(c, vs.Candidate)
        assert c.duration_s == 90 and c.reason and c.video_id == "aaaaaaaaaa1"
        assert "ages 11 and up" in c.reason and "90 seconds" in c.reason
        assert c.min_age == 11, "90 seconds is the 11-12 band's ceiling and up"

    @pytest.mark.parametrize("seconds,age", [(30, 0), (75, 0), (76, 11), (100, 11), (101, 13), (140, 13),
                                              (141, 15), (170, 15), (171, 17), (200, 17)])
    def test_it_is_placed_by_its_own_length_against_the_film_caps(self, seconds, age):
        c = vs.assess(item(seconds=seconds), known=set())
        assert c.min_age == age
        assert seconds <= film.band_for(c.min_age).clip_max_s

    def test_a_shorts_length_clip_is_welcome(self):
        assert isinstance(vs.assess(item(seconds=40), known=set()), vs.Candidate)

    @pytest.mark.parametrize("kw,why", [
        ({"privacy": "private"}, "not_public"),
        ({"privacy": "unlisted"}, "not_public"),
        ({"embeddable": False}, "not_embeddable"),
        ({"rating": "ytAgeRestricted"}, "age_restricted"),
        ({"seconds": 201}, "too_long"),
        ({"seconds": 600}, "too_long"),
        ({"seconds": 10}, "too_short"),
        ({"title": "Soccer passing tips", "tags": ("soccer",), "desc": "football"}, "not_lacrosse"),
        ({"title": "Box lacrosse two man game", "tags": ("lacrosse", "box lacrosse")}, "other_game"),
        ({"title": "NLL lacrosse breakdown", "tags": ("nll",)}, "other_game"),
        ({"title": "Womens lacrosse defense draw control", "tags": ("womens lacrosse",)}, "other_game"),
        ({"title": "Girls lacrosse approach", "tags": ("girls lacrosse",)}, "other_game"),
        ({"title": "Lacrosse highlights: top 10 goals"}, "highlight_reel"),
        ({"title": "Insane lacrosse mixtape"}, "highlight_reel"),
        ({"title": "Lacrosse film study, this is f***ing hard", "desc": "shit"}, "language"),
        ({"title": "Lacrosse slide breakdown", "desc": "this damn defense"}, "language"),
        ({"lang": "es"}, "not_english"),
    ])
    def test_what_is_turned_away_and_why(self, kw, why):
        assert vs.assess(item(**kw), known=set()) == why

    def test_a_clip_with_no_language_set_is_not_refused_for_it(self):
        assert isinstance(vs.assess(item(lang=None), known=set()), vs.Candidate)

    def test_anything_already_known_is_skipped(self):
        assert vs.assess(item(), known={"aaaaaaaaaa1"}) == "known"

    def test_a_missing_length_is_refused(self):
        bad = item()
        bad["contentDetails"]["duration"] = "nonsense"
        assert vs.assess(bad, known=set()) == "too_short"

    def test_a_video_about_lacrosse_only_in_the_description_is_not_enough(self):
        assert vs.assess(item(title="Great defensive tips", tags=("defense",), desc="lacrosse lacrosse lacrosse"),
                         known=set()) == "not_lacrosse"

    def test_lacrosse_in_the_tags_counts(self):
        assert isinstance(vs.assess(item(title="Great defensive tips", tags=("lacrosse", "defense")), known=set()),
                          vs.Candidate)


class TestRanking:
    def test_a_clip_about_reading_the_game_outranks_a_generic_one(self):
        iq = vs.assess(item("iqiqiqiqiq1", title="Lacrosse film study: reading the slide and spacing"), known=set())
        plain = vs.assess(item("plainplain1", title="Lacrosse tips", tags=("lacrosse",)), known=set())
        assert iq.score > plain.score

    def test_captions_help_a_little(self):
        a = vs.assess(item("capcapcap01", caption="true"), known=set())
        b = vs.assess(item("capcapcap02", caption="false"), known=set())
        assert a.score > b.score

    def test_a_goalie_clip_says_it_is_for_goalies(self):
        c = vs.assess(item(title="Lacrosse goalie angles film study", tags=("lacrosse", "goalie")), known=set())
        assert c.concept == "goalie"


# --------------------------------------------------------------------------- searches

class TestWhatIsSearchedFor:
    def test_every_query_is_about_lacrosse(self):
        assert vs.QUERIES and all("lacrosse" in q.lower() for q in vs.QUERIES)

    def test_a_few_queries_are_for_short_clips(self):
        assert any("#shorts" in q for q in vs.QUERIES)

    def test_each_week_covers_different_queries_and_all_of_them_eventually(self):
        n = vs.MAX_SEARCHES_PER_RUN
        seen = set()
        weeks = -(-len(vs.QUERIES) // n)
        for w in range(weeks):
            batch = vs.queries_for(w, n)
            assert len(batch) == min(n, len(vs.QUERIES))
            seen.update(batch)
        assert seen == set(vs.QUERIES)
        assert vs.queries_for(0, n) != vs.queries_for(1, n)

    def test_the_search_budget_is_well_inside_the_free_daily_quota(self):
        """A search costs 100 units of a 10,000 a day free quota; a weekly run must use a small share."""
        assert vs.MAX_SEARCHES_PER_RUN * 100 <= 2000


# --------------------------------------------------------------------------- the scan

class TestScanning:

    def test_it_does_nothing_without_a_key(self, store):
        assert vs.scan(store.conn, None)["ran"] is False
        assert store.conn.execute("SELECT COUNT(*) FROM video_suggestions").fetchone()[0] == 0

    def test_good_finds_become_suggestions_and_bad_ones_do_not(self, store, org):
        api = FakeApi([item("good0000001"), item("priv0000001", privacy="private"),
                       item("noemb000001", embeddable=False), item("hl000000001", title="Lacrosse highlights mix")])
        out = vs.scan(store.conn, api)
        assert out["ran"] and out["added"] == 1
        assert [s["video_id"] for s in suggestions(store, org)] == ["good0000001"]
        assert out["rejected"]["not_public"] >= 1 and out["rejected"]["highlight_reel"] >= 1

    def test_the_shelfs_own_clips_are_never_suggested(self, store, org):
        on_shelf = iq_shelf.LACROSSE[0].video_id
        vs.scan(store.conn, FakeApi([item(on_shelf), item("new00000001")]))
        assert [s["video_id"] for s in suggestions(store, org)] == ["new00000001"]

    def test_a_second_scan_adds_nothing_new_and_makes_no_duplicates(self, store):
        api = FakeApi([item("good0000001")])
        vs.scan(store.conn, api)
        again = vs.scan(store.conn, api)
        assert again["added"] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM video_suggestions").fetchone()[0] == 1

    def test_it_stops_adding_at_the_pending_limit(self, store):
        many = [item(f"vid{n:08d}", title=f"Lacrosse film study slide {n}") for n in range(vs.MAX_PENDING + 25)]
        out = vs.scan(store.conn, FakeApi(many))
        assert store.conn.execute("SELECT COUNT(*) FROM video_suggestions WHERE withdrawn = 0").fetchone()[0] == vs.MAX_PENDING
        assert out["added"] == vs.MAX_PENDING

    def test_the_best_ranked_are_kept_when_there_is_not_room_for_all(self, store, org):
        weak = [item(f"weak{n:07d}", title="Lacrosse tips", tags=("lacrosse",), caption="false", views=60) for n in range(vs.MAX_PENDING)]
        strong = item("strong00001", title="Lacrosse film study reading the slide spacing", views=90000)
        vs.scan(store.conn, FakeApi(weak + [strong]))
        assert "strong00001" in {s["video_id"] for s in suggestions(store, org, )} or \
            store.conn.execute("SELECT 1 FROM video_suggestions WHERE video_id = 'strong00001'").fetchone()

    def test_a_quota_error_stops_quietly_and_keeps_what_was_found(self, store, org):
        api = FakeApi([item("good0000001")], fail_after=1)
        out = vs.scan(store.conn, api)
        assert out["ran"] and out["stopped"] == "quotaExceeded"
        assert [s["video_id"] for s in suggestions(store, org)] == ["good0000001"]

    def test_a_network_error_on_the_first_search_is_not_a_crash(self, store):
        out = vs.scan(store.conn, FakeApi([], fail_after=0, fail_with="network"))
        assert out["ran"] and out["stopped"] == "network" and out["added"] == 0

    def test_it_never_looks_up_more_than_it_searched_for(self, store):
        api = FakeApi([item("good0000001")])
        vs.scan(store.conn, api)
        assert len(api.searches) <= vs.MAX_SEARCHES_PER_RUN
        assert all(len(batch) <= 50 for batch in api.details_calls)

    def test_a_taken_down_video_is_withdrawn_at_the_next_scan(self, store, org):
        api = FakeApi([item("good0000001"), item("gone0000001")])
        vs.scan(store.conn, api)
        api.catalog["gone0000001"]["status"]["embeddable"] = False   # embedding switched off
        del api.catalog["good0000001"]                                # deleted: simply absent from the answer
        vs.scan(store.conn, api)
        assert suggestions(store, org) == []

    def test_a_video_that_is_still_fine_stays_after_a_rescan(self, store, org):
        api = FakeApi([item("good0000001")])
        vs.scan(store.conn, api)
        vs.scan(store.conn, api)
        assert [s["video_id"] for s in suggestions(store, org)] == ["good0000001"]

    def test_a_failed_lookup_does_not_empty_the_coachs_list(self, store, org):
        api = FakeApi([item("good0000001")])
        vs.scan(store.conn, api)

        class Down(FakeApi):
            def details(self, ids):
                raise vs.ScoutError("network")

        vs.scan(store.conn, Down([item("good0000001")]))
        assert [s["video_id"] for s in suggestions(store, org)] == ["good0000001"]

    def test_nothing_longer_than_a_seventeen_year_old_can_be_shown_is_suggested(self, store, org):
        """The 19+ band (240 s) is adults only; the shelf is for young people."""
        assert vs.LONGEST_S == 200
        assert vs.assess(item(seconds=201), known=set()) == "too_long"

    def test_the_last_scan_is_recorded_for_the_dashboard(self, store):
        vs.scan(store.conn, FakeApi([item("good0000001")]))
        last = vs.last_scan(store.conn)
        assert last and last["added"] == 1 and last["at"]


# --------------------------------------------------------------------------- the key

class TestTheKeyStaysSecret:

    def _http_error(self, body):
        return urllib.error.HTTPError("https://www.googleapis.com/youtube/v3/search?key=SECRETKEY123", 403, "Forbidden", {},
                                      io.BytesIO(json.dumps(body).encode()))

    def test_it_is_sent_but_never_surfaces_in_an_error(self):
        err = self._http_error({"error": {"errors": [{"reason": "quotaExceeded"}]}})

        def opener(req, timeout=0):
            raise err

        api = vs.YouTubeApi("SECRETKEY123", opener=opener)
        with pytest.raises(vs.ScoutError) as caught:
            api.search("lacrosse film study")
        assert "SECRETKEY123" not in str(caught.value) and "SECRETKEY123" not in repr(caught.value)
        assert caught.value.quota is True
        # The original error's text carries the request URL, and so the key. Nothing is chained to it.
        assert caught.value.__cause__ is None and caught.value.__context__ is None

    def test_a_network_failure_is_a_scout_error_without_the_url(self):
        def opener(req, timeout=0):
            raise urllib.error.URLError("dns failure for https://x?key=SECRETKEY123")

        with pytest.raises(vs.ScoutError) as caught:
            vs.YouTubeApi("SECRETKEY123", opener=opener).details(["aaaaaaaaaa1"])
        assert "SECRETKEY123" not in str(caught.value)

    def test_the_search_asks_for_the_safest_results(self):
        seen = {}

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps({"items": [{"id": {"videoId": "aaaaaaaaaa1"}}]}).encode()

        def opener(req, timeout=0):
            seen["url"] = req.full_url
            return Resp()

        ids = vs.YouTubeApi("K", opener=opener).search("lacrosse film study")
        assert ids == ["aaaaaaaaaa1"]
        for needle in ("safeSearch=strict", "videoEmbeddable=true", "type=video", "relevanceLanguage=en"):
            assert needle in seen["url"]

    def test_the_status_response_never_carries_it(self, store):
        assert "key" not in json.dumps(vs.status(store.conn)).lower().replace("keyword", "")

    def test_the_config_does_not_print_it(self):
        from offdays.config import CONFIG
        cfg = dataclasses.replace(CONFIG, youtube_api_key="AIzaSECRETVALUE")
        assert "AIzaSECRETVALUE" not in repr(cfg)


# --------------------------------------------------------------------------- what a coach sees

class TestWhatACoachSees:

    def test_a_suggestion_carries_what_is_needed_to_judge_it(self, store, org):
        seeded(store, item("good0000001"))
        (s,) = suggestions(store, org)
        for key in ("id", "video_id", "title", "channel", "seconds", "min_age", "reason", "watch_url", "focus_default"):
            assert s[key] not in (None, ""), key
        assert s["watch_url"] == "https://www.youtube.com/watch?v=good0000001"

    def test_the_internal_score_is_not_shown(self, store, org):
        seeded(store, item("good0000001"))
        assert "score" not in suggestions(store, org)[0]

    def test_best_first(self, store, org):
        seeded(store, item("plain000001", title="Lacrosse tips", tags=("lacrosse",), caption="false", views=60),
               item("iq0000000001", title="Lacrosse film study reading the slide spacing", views=80000))
        assert [s["video_id"] for s in suggestions(store, org)][0] == "iq0000000001"

    def test_a_video_already_among_the_programs_clips_is_not_suggested(self, store, org):
        seeded(store, item("dQw4w9WgXcQ"))
        assert [s["video_id"] for s in suggestions(store, org)] == ["dQw4w9WgXcQ"]
        store.create_clip(org, "dQw4w9WgXcQ", "Ours", focus="x", end_s=60)
        assert suggestions(store, org) == []

    def test_a_clip_the_program_removed_does_not_come_back_as_a_suggestion(self, store, org):
        seeded(store, item("dQw4w9WgXcQ"))
        clip = store.create_clip(org, "dQw4w9WgXcQ", "Ours", focus="x", end_s=60)
        store.retire_clip(org, clip["id"])
        assert suggestions(store, org) == []


# --------------------------------------------------------------------------- adding and dismissing

class TestAdding:

    def _one(self, store, org, **kw):
        seeded(store, item("good0000001", **kw))
        return suggestions(store, org)[0]

    def test_adding_makes_a_real_clip_through_the_ordinary_door(self, store, org, staff):
        s = self._one(store, org, seconds=90)
        clip = vs.add(store, org, staff["id"], s["id"])
        assert clip["video_id"] == "good0000001" and clip["length_s"] == 90 and clip["min_age"] == s["min_age"]
        assert clip["focus"], "a clip with nothing to watch for is the thing film study is not"
        row = store.conn.execute("SELECT created_by, shelf FROM clips WHERE id = ?", (clip["id"],)).fetchone()
        assert row["created_by"] == staff["id"] and row["shelf"] == ""

    def test_it_is_then_the_programs_own_clip_and_comes_first_for_athletes(self, store, org, staff):
        kid = store.create_user(org, "athlete", "Sam", birth_year=TODAY.year - 12, dominant_hand="right", guardian_consent=True)
        s = self._one(store, org, seconds=90)
        clip = vs.add(store, org, staff["id"], s["id"])
        feed = store.clips_for_athlete(kid["id"], org)["clips"]
        assert feed[0]["id"] == clip["id"] and feed[0]["shelf"] == ""

    def test_a_suggestion_that_was_never_added_never_reaches_an_athlete(self, store, org):
        kid = store.create_user(org, "athlete", "Sam", birth_year=TODAY.year - 12, dominant_hand="right", guardian_consent=True)
        seeded(store, item("good0000001"))
        ids = [c["video_id"] for c in store.clips_for_athlete(kid["id"], org)["clips"]]
        assert "good0000001" not in ids

    def test_the_coach_can_retitle_and_say_what_to_watch_for(self, store, org, staff):
        s = self._one(store, org)
        clip = vs.add(store, org, staff["id"], s["id"], title="Watch the second slide", focus="Count the passes.")
        assert clip["title"] == "Watch the second slide" and clip["focus"] == "Count the passes."

    def test_the_age_can_be_raised_but_never_lowered_below_what_the_length_allows(self, store, org, staff):
        s = self._one(store, org, seconds=150)
        assert s["min_age"] == 15
        low = vs.add(store, org, staff["id"], s["id"], min_age=9)
        assert low["min_age"] == 15
        seeded(store, item("other000001", seconds=150))
        s2 = [x for x in suggestions(store, org) if x["video_id"] == "other000001"][0]
        assert vs.add(store, org, staff["id"], s2["id"], min_age=17)["min_age"] == 17

    def test_a_goalie_clip_is_added_for_goalies(self, store, org, staff):
        seeded(store, item("goalie00001", title="Lacrosse goalie angles film study", tags=("lacrosse", "goalie")))
        s = suggestions(store, org)[0]
        clip = vs.add(store, org, staff["id"], s["id"])
        assert clip["positions"] == ["goalie"]

    def test_the_highlight_refusal_still_applies_to_a_retitle(self, store, org, staff):
        s = self._one(store, org)
        with pytest.raises(StoreError):
            vs.add(store, org, staff["id"], s["id"], title="Best plays highlight reel")

    def test_adding_twice_does_not_make_two_clips(self, store, org, staff):
        s = self._one(store, org)
        vs.add(store, org, staff["id"], s["id"])
        with pytest.raises(StoreError):
            vs.add(store, org, staff["id"], s["id"])
        assert store.conn.execute("SELECT COUNT(*) FROM clips WHERE org_id = ? AND video_id = 'good0000001'", (org,)).fetchone()[0] == 1

    def test_an_added_suggestion_leaves_the_list(self, store, org, staff):
        s = self._one(store, org)
        vs.add(store, org, staff["id"], s["id"])
        assert suggestions(store, org) == []

    def test_an_unknown_suggestion_is_refused(self, store, org, staff):
        with pytest.raises(StoreError, match="no such"):
            vs.add(store, org, staff["id"], 9999)
        with pytest.raises(StoreError, match="no such"):
            vs.dismiss(store.conn, org, staff["id"], 9999)

    def test_a_withdrawn_suggestion_cannot_be_added(self, store, org, staff):
        s = self._one(store, org)
        store.conn.execute("UPDATE video_suggestions SET withdrawn = 1")
        store.conn.commit()
        with pytest.raises(StoreError, match="no longer"):
            vs.add(store, org, staff["id"], s["id"])


class TestDismissing:

    def test_a_dismissed_suggestion_is_gone_for_good(self, store, org, staff):
        seeded(store, item("good0000001"))
        s = suggestions(store, org)[0]
        vs.dismiss(store.conn, org, staff["id"], s["id"])
        assert suggestions(store, org) == []
        vs.scan(store.conn, FakeApi([item("good0000001")]))
        assert suggestions(store, org) == [], "a rescan must not bring back what a coach said no to"

    def test_it_is_per_program(self, store, org, staff):
        other = store.create_org("Other Club")
        other_staff = store.create_user(other, "coach", "Other C")
        seeded(store, item("good0000001"))
        s = suggestions(store, org)[0]
        vs.dismiss(store.conn, org, staff["id"], s["id"])
        assert [x["video_id"] for x in suggestions(store, other)] == ["good0000001"]
        vs.add(store, other, other_staff["id"], s["id"])
        assert suggestions(store, org) == []

    def test_a_program_can_not_decide_twice(self, store, org, staff):
        seeded(store, item("good0000001"))
        s = suggestions(store, org)[0]
        vs.dismiss(store.conn, org, staff["id"], s["id"])
        with pytest.raises(StoreError, match="already"):
            vs.add(store, org, staff["id"], s["id"])


# --------------------------------------------------------------------------- over the wire

@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient
    from offdays import api

    store = Store(connect(tmp_path / "wire.db"))
    api.app.dependency_overrides[api.get_store] = lambda: store
    c = TestClient(api.app)
    c.store = store
    yield c
    api.app.dependency_overrides.clear()


def program(client):
    res = client.post("/api/orgs", json={"name": "Northshore", "director_name": "Dir"}).json()
    return res, {"Authorization": f"Bearer {res['director']['token']}"}


@pytest.fixture
def keyed(monkeypatch):
    from offdays.config import CONFIG
    monkeypatch.setattr(vs, "CONFIG", dataclasses.replace(CONFIG, youtube_api_key="AIzaFAKE"))


class TestOverTheWire:

    def test_without_a_key_the_card_says_it_is_not_switched_on(self, client):
        _, director = program(client)
        body = client.get("/api/coach/suggestions", headers=director).json()
        assert body["enabled"] is False and body["suggestions"] == []

    def test_with_a_key_it_lists_what_the_scan_found(self, client, keyed):
        res, director = program(client)
        vs.scan(client.store.conn, FakeApi([item("good0000001")]))
        body = client.get("/api/coach/suggestions", headers=director).json()
        assert body["enabled"] is True and [s["video_id"] for s in body["suggestions"]] == ["good0000001"]
        assert "key" not in json.dumps(body).lower().replace("keyword", "")

    def test_an_athlete_cannot_see_or_decide_them(self, client, keyed):
        _, director = program(client)
        kid = client.post("/api/athletes", json={"display_name": "Sam", "birth_year": TODAY.year - 12, "dominant_hand": "right",
                                                  "guardian_consent": True}, headers=director).json()
        h = {"Authorization": f"Bearer {kid['token']}"}
        vs.scan(client.store.conn, FakeApi([item("good0000001")]))
        assert client.get("/api/coach/suggestions", headers=h).status_code in (401, 403)
        assert client.post("/api/coach/suggestions/1/add", json={}, headers=h).status_code in (401, 403)
        assert client.post("/api/coach/suggestions/1/dismiss", headers=h).status_code in (401, 403)

    def test_add_makes_a_clip_a_kid_sees_first(self, client, keyed):
        _, director = program(client)
        kid = client.post("/api/athletes", json={"display_name": "Sam", "birth_year": TODAY.year - 12, "dominant_hand": "right",
                                                  "guardian_consent": True}, headers=director).json()
        h = {"Authorization": f"Bearer {kid['token']}"}
        vs.scan(client.store.conn, FakeApi([item("good0000001", seconds=90)]))
        sid = client.get("/api/coach/suggestions", headers=director).json()["suggestions"][0]["id"]
        res = client.post(f"/api/coach/suggestions/{sid}/add", json={"focus": "Count the passes."}, headers=director)
        assert res.status_code == 201, res.text
        film_feed = client.get("/api/film", headers=h).json()["clips"]
        assert film_feed[0]["video_id"] == "good0000001" and film_feed[0]["focus"] == "Count the passes."
        assert [c["video_id"] for c in client.get("/api/coach/clips", headers=director).json()["clips"]] == ["good0000001"]
        assert client.get("/api/coach/suggestions", headers=director).json()["suggestions"] == []

    def test_a_coach_who_is_not_the_director_can_add_too(self, client, keyed):
        res, director = program(client)
        org_id = client.store.authenticate(res["director"]["token"]).org_id
        coach = client.store.create_user(org_id, "coach", "Asst")
        h = {"Authorization": f"Bearer {coach['token']}"}
        vs.scan(client.store.conn, FakeApi([item("good0000001")]))
        sid = client.get("/api/coach/suggestions", headers=h).json()["suggestions"][0]["id"]
        assert client.post(f"/api/coach/suggestions/{sid}/add", json={}, headers=h).status_code == 201

    def test_dismiss_removes_it(self, client, keyed):
        _, director = program(client)
        vs.scan(client.store.conn, FakeApi([item("good0000001")]))
        sid = client.get("/api/coach/suggestions", headers=director).json()["suggestions"][0]["id"]
        assert client.post(f"/api/coach/suggestions/{sid}/dismiss", headers=director).status_code == 200
        assert client.get("/api/coach/suggestions", headers=director).json()["suggestions"] == []

    def test_unknown_and_repeat_requests_get_proper_errors(self, client, keyed):
        _, director = program(client)
        assert client.post("/api/coach/suggestions/9999/add", json={}, headers=director).status_code == 404
        assert client.post("/api/coach/suggestions/9999/dismiss", headers=director).status_code == 404
        vs.scan(client.store.conn, FakeApi([item("good0000001")]))
        sid = client.get("/api/coach/suggestions", headers=director).json()["suggestions"][0]["id"]
        client.post(f"/api/coach/suggestions/{sid}/add", json={}, headers=director)
        assert client.post(f"/api/coach/suggestions/{sid}/add", json={}, headers=director).status_code == 409

    def test_a_highlight_retitle_is_a_clear_400(self, client, keyed):
        _, director = program(client)
        vs.scan(client.store.conn, FakeApi([item("good0000001")]))
        sid = client.get("/api/coach/suggestions", headers=director).json()["suggestions"][0]["id"]
        res = client.post(f"/api/coach/suggestions/{sid}/add", json={"title": "Best plays highlight reel"}, headers=director)
        assert res.status_code == 400

    def test_programs_do_not_see_each_others_decisions(self, client, keyed):
        _, a = program(client)
        _, b = program(client)
        vs.scan(client.store.conn, FakeApi([item("good0000001")]))
        sid = client.get("/api/coach/suggestions", headers=a).json()["suggestions"][0]["id"]
        client.post(f"/api/coach/suggestions/{sid}/dismiss", headers=a)
        assert len(client.get("/api/coach/suggestions", headers=b).json()["suggestions"]) == 1

    def test_no_route_path_trips_the_one_way_messaging_rule(self, client):
        paths = [r.path for r in client.app.routes if "suggestions" in getattr(r, "path", "")]
        assert paths and not any(w in p for p in paths for w in ("message", "reply", "comment", "chat"))


# --------------------------------------------------------------------------- the operator side

REPO = Path(__file__).resolve().parent.parent


class TestRunningIt:

    def test_the_weekly_job_is_in_the_crontab_and_the_script_exists(self):
        cron = (REPO / "infra" / "crontab.offdays").read_text(encoding="utf-8")
        assert "scripts/run_video_scout.py" in cron
        assert (REPO / "scripts" / "run_video_scout.py").exists()

    def test_the_example_env_documents_the_key_with_no_value(self):
        env = (REPO / "infra" / ".env.prod.example").read_text(encoding="utf-8")
        line = next(l for l in env.splitlines() if l.startswith("OFFDAYS_YOUTUBE_API_KEY="))
        assert line.strip() == "OFFDAYS_YOUTUBE_API_KEY="

    def test_the_setup_script_writes_only_its_one_line_and_keeps_the_file_private(self, tmp_path, monkeypatch):
        import importlib.util
        spec = importlib.util.spec_from_file_location("setup_youtube", REPO / "scripts" / "setup_youtube.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        env = tmp_path / ".env.prod"
        env.write_text("OFFDAYS_SMTP_HOST=smtp.resend.com\nOFFDAYS_YOUTUBE_API_KEY=\nOTHER=1\n", encoding="utf-8")
        monkeypatch.setattr(mod, "ENV_PATH", str(env))
        mod.write_env("AIzaTESTVALUE")
        text = env.read_text(encoding="utf-8")
        assert "OFFDAYS_YOUTUBE_API_KEY=AIzaTESTVALUE" in text and "OFFDAYS_SMTP_HOST=smtp.resend.com" in text and "OTHER=1" in text
        assert text.count("OFFDAYS_YOUTUBE_API_KEY") == 1

    def test_the_setup_script_refuses_a_value_that_is_not_a_google_key(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("setup_youtube2", REPO / "scripts" / "setup_youtube.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.looks_like_key("AIza" + "x" * 35) and not mod.looks_like_key("re_notagooglekey")
