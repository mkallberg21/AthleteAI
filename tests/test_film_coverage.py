"""Who has watched each clip, and who has not.

`team_film` answers "how many clips has each athlete finished". The question a
coach actually has before practice is the other one: "I want to talk about the
man-down slide -- has everyone seen it?". Nothing answered that, so this does.

The film module refuses to rank children by minutes, and this view is the one
most likely to turn into a ranking by accident, so most of what is pinned here
is the shape of the output rather than its contents.
"""
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays.db import connect
from offdays.store import Store


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "test.db"))
    yield TestClient(api_module.app)
    api_module._store = None


@pytest.fixture
def club(client):
    org = client.post(
        "/api/orgs", json={"name": "Northshore LC", "director_name": "Dir"}
    ).json()
    director = {"Authorization": f"Bearer {org['director']['token']}"}
    team = client.post(
        "/api/teams", json={"name": "2031 Red", "season": "2026"}, headers=director
    ).json()
    athletes = []
    for name in ("Zoe A.", "Adam B.", "Mia C."):
        a = client.post(
            "/api/athletes",
            json={"display_name": name, "birth_year": 2011, "dominant_hand": "right",
                  "guardian_consent": True, "join_code": team["join_code"]},
            headers=director,
        ).json()
        a["headers"] = {"Authorization": f"Bearer {a['token']}"}
        athletes.append(a)
    clip = client.post(
        "/api/coach/clips",
        json={"video": "https://clips.example.invalid/slide", "provider": "link",
              "title": "Sliding from the crease", "focus": "Watch the first slide.",
              "end_s": 100},
        headers=director,
    ).json()
    return {"org": org, "director": director, "team": team,
            "athletes": athletes, "clip": clip}


def _watch(store, athlete_id, clip_id, verdict, looks=1):
    import json as _json
    from datetime import date
    store.conn.execute(
        "INSERT INTO clip_watches(athlete_id, clip_id, day, watched_s, seen_json,"
        " verdict, looks, started_at, last_beat_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (athlete_id, clip_id, date.today().isoformat(), 90.0,
         _json.dumps(list(range(90))), verdict, looks, "2026-01-01", "2026-01-01"),
    )
    store.conn.commit()


class TestCoverage:
    def test_it_says_who_has_watched_and_who_has_not(self, client, club):
        store = api_module._store
        clip_id = club["clip"]["id"]
        _watch(store, club["athletes"][0]["id"], clip_id, "watched")
        _watch(store, club["athletes"][1]["id"], clip_id, "partial")

        body = client.get("/api/coach/film/coverage", headers=club["director"]).json()
        clip = body["clips"][0]
        assert [a["display_name"] for a in clip["watched"]] == ["Zoe A."]
        assert [a["display_name"] for a in clip["started"]] == ["Adam B."]
        assert [a["display_name"] for a in clip["not_yet"]] == ["Mia C."]
        assert clip["watched_count"] == 1
        assert body["roster_count"] == 3

    def test_names_are_alphabetical_never_ordered_by_how_much_was_watched(
        self, client, club
    ):
        """Ordering a bucket by minutes would make it a ranking of children."""
        store = api_module._store
        for a in club["athletes"]:
            _watch(store, a["id"], club["clip"]["id"], "watched")
        clip = client.get(
            "/api/coach/film/coverage", headers=club["director"]
        ).json()["clips"][0]
        names = [a["display_name"] for a in clip["watched"]]
        assert names == sorted(names, key=str.lower), names

    def test_a_clip_nobody_opened_lists_the_whole_squad_as_not_yet(self, client, club):
        clip = client.get(
            "/api/coach/film/coverage", headers=club["director"]
        ).json()["clips"][0]
        assert clip["watched"] == [] and clip["started"] == []
        assert len(clip["not_yet"]) == 3

    def test_watching_it_properly_once_is_not_undone_by_a_later_partial(
        self, client, club
    ):
        """An athlete who finished a clip on Monday and reopened it briefly on
        Tuesday has still watched it."""
        store = api_module._store
        athlete = club["athletes"][0]["id"]
        clip_id = club["clip"]["id"]
        store.conn.execute(
            "INSERT INTO clip_watches(athlete_id, clip_id, day, verdict,"
            " started_at, last_beat_at) VALUES (?,?,?,?,?,?)",
            (athlete, clip_id, "2026-01-01", "watched", "x", "x"),
        )
        store.conn.execute(
            "INSERT INTO clip_watches(athlete_id, clip_id, day, verdict,"
            " started_at, last_beat_at) VALUES (?,?,?,?,?,?)",
            (athlete, clip_id, "2026-01-02", "partial", "x", "x"),
        )
        store.conn.commit()
        clip = store.clip_coverage(
            club["org"]["org_id"], [athlete], days=100000,
        )["clips"][0]
        assert [a["display_name"] for a in clip["watched"]] == ["Zoe A."]
        assert clip["started"] == []

    def test_question_results_are_per_clip_and_never_per_athlete(self, client, club):
        """Whether the point landed is worth knowing. Who got it wrong turns
        one comprehension question into a grade book."""
        store = api_module._store
        _watch(store, club["athletes"][0]["id"], club["clip"]["id"], "watched")
        clip = client.get(
            "/api/coach/film/coverage", headers=club["director"]
        ).json()["clips"][0]
        assert "answered_right" in clip and "answered_count" in clip
        for bucket in ("watched", "started", "not_yet"):
            for person in clip[bucket]:
                assert "answer_ok" not in person, person
                assert "answered" not in person, person

    def test_the_response_says_how_to_read_it(self, client, club):
        """A column headed 'not yet' full of children's names gets read as a
        naughty list unless it says plainly that it is not one."""
        body = client.get("/api/coach/film/coverage", headers=club["director"]).json()
        assert "Coverage, not compliance" in body["how_to_read"]

    def test_it_is_named_for_the_program_s_sport(self, client, club):
        body = client.get("/api/coach/film/coverage", headers=club["director"]).json()
        assert body["label"] == "Lacrosse IQ"


class TestItObeysTheSameScopingAsItsSiblings:
    def test_a_coach_cannot_ask_about_a_team_they_are_not_on(self, client, club):
        store = api_module._store
        coach = store.create_user(club["org"]["org_id"], "coach", "Coach B")
        other = client.post(
            "/api/teams", json={"name": "2029 Red", "season": "2026"},
            headers=club["director"],
        ).json()
        store.assign_staff_to_team(coach["id"], club["team"]["id"])
        headers = {"Authorization": f"Bearer {coach['token']}"}
        res = client.get(
            f"/api/coach/film/coverage?team_id={other['id']}", headers=headers
        )
        assert res.status_code == 403

    def test_an_athlete_cannot_read_it_at_all(self, client, club):
        res = client.get(
            "/api/coach/film/coverage", headers=club["athletes"][0]["headers"]
        )
        assert res.status_code in (401, 403)
