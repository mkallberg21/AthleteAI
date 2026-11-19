"""A coach opens a player and sees which clips they watched and how many times."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays.db import connect
from offdays.store import Store

STATIC = Path(api_module.__file__).parent / "web" / "static"


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "fw.db"))


@pytest.fixture
def club(store):
    org = store.create_org("Nashville Dogs", sport="lacrosse")
    director = store.create_user(org, "director", "Joel")
    coach = store.create_user(org, "coach", "Coach Tommy")
    other = store.create_user(org, "coach", "Coach Mike")
    red = store.create_team(org, "2031 Red", "2026")
    blue = store.create_team(org, "2031 Blue", "2026")
    store.assign_staff_to_team(coach["id"], red["id"])
    store.assign_staff_to_team(other["id"], blue["id"])
    ryder = store.create_user(org, "athlete", "Ryder", birth_year=2013, dominant_hand="right")
    sam = store.create_user(org, "athlete", "Sam", birth_year=2013, dominant_hand="right")
    store.join_team(red["join_code"], ryder["id"])
    store.join_team(blue["join_code"], sam["id"])
    return {"org": org, "director": director, "coach": coach, "other": other, "ryder": ryder, "sam": sam}


@pytest.fixture
def api(store, club):
    api_module._store = store
    yield TestClient(api_module.app), (lambda who: {"Authorization": f"Bearer {club[who]['token']}"})
    api_module._store = None


def clip(store, club, title):
    cur = store.conn.execute(
        "INSERT INTO clips(org_id, video_id, title, created_at, end_s) VALUES (?,?,?,?,60)",
        (club["org"], "vid" + title.replace(" ", ""), title, datetime.now(timezone.utc).isoformat()))
    store.conn.commit()
    return cur.lastrowid


def watch(store, athlete, clip_id, days_ago=0, looks=1, verdict="watched", seconds=60, unplayable=0):
    day = (datetime.now(timezone.utc).date() - timedelta(days=days_ago)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    store.conn.execute(
        "INSERT INTO clip_watches(athlete_id, clip_id, day, watched_s, verdict, looks, unplayable, started_at, last_beat_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)", (athlete, clip_id, day, seconds, verdict, looks, unplayable, now, now))
    store.conn.commit()


def film(client, h, who, athlete, days=30):
    res = client.get(f"/api/coach/athletes/{athlete}/training?days={days}", headers=h(who))
    assert res.status_code == 200
    return res.json()["film"]


class TestWhatTheCoachSees:
    def test_a_player_who_watched_nothing_has_an_empty_list(self, api, club):
        client, h = api
        f = film(client, h, "coach", club["ryder"]["id"])
        assert f["clips"] == [] and f["total_clips"] == 0 and f["total_times"] == 0 and f["again"] == 0

    def test_a_clip_watched_once_counts_once(self, api, club, store):
        client, h = api
        watch(store, club["ryder"]["id"], clip(store, club, "Sliding and Recovery"))
        f = film(client, h, "coach", club["ryder"]["id"])
        assert [(c["title"], c["times"], c["days"]) for c in f["clips"]] == [("Sliding and Recovery", 1, 1)]
        assert f["again"] == 0

    def test_a_clip_watched_several_times_in_a_day_counts_every_pass(self, api, club, store):
        client, h = api
        watch(store, club["ryder"]["id"], clip(store, club, "Clears"), looks=3)
        c = film(client, h, "coach", club["ryder"]["id"])["clips"][0]
        assert c["times"] == 3 and c["days"] == 1

    def test_and_across_days_the_passes_add_up(self, api, club, store):
        client, h = api
        cid = clip(store, club, "Face Offs")
        watch(store, club["ryder"]["id"], cid, days_ago=5, looks=2)
        watch(store, club["ryder"]["id"], cid, days_ago=1, looks=1)
        f = film(client, h, "coach", club["ryder"]["id"])
        c = f["clips"][0]
        assert c["times"] == 3 and c["days"] == 2 and c["first_on"] < c["last_on"]
        assert f["total_clips"] == 1 and f["total_times"] == 3 and f["again"] == 1

    def test_the_window_follows_the_days_chosen(self, api, club, store):
        client, h = api
        watch(store, club["ryder"]["id"], clip(store, club, "Old one"), days_ago=20)
        assert film(client, h, "coach", club["ryder"]["id"], 7)["total_clips"] == 0
        assert film(client, h, "coach", club["ryder"]["id"], 30)["total_clips"] == 1

    def test_a_clip_that_would_not_play_is_not_counted_as_watched(self, api, club, store):
        client, h = api
        watch(store, club["ryder"]["id"], clip(store, club, "Dead link"), unplayable=1)
        assert film(client, h, "coach", club["ryder"]["id"])["clips"] == []

    def test_a_row_with_a_zero_still_counts_as_one_view(self, api, club, store):
        client, h = api
        watch(store, club["ryder"]["id"], clip(store, club, "Odd"), looks=0)
        assert film(client, h, "coach", club["ryder"]["id"])["clips"][0]["times"] == 1

    def test_minutes_and_how_it_went_are_there(self, api, club, store):
        client, h = api
        watch(store, club["ryder"]["id"], clip(store, club, "Quick"), seconds=90, verdict="partial")
        c = film(client, h, "coach", club["ryder"]["id"])["clips"][0]
        assert c["minutes"] == 1.5 and c["last_verdict"] == "partial"


class TestItIsNeverARanking:
    def test_the_list_is_newest_first_whatever_the_counts(self, api, club, store):
        client, h = api
        a, b, c = clip(store, club, "A"), clip(store, club, "B"), clip(store, club, "C")
        watch(store, club["ryder"]["id"], a, days_ago=6, looks=9)
        watch(store, club["ryder"]["id"], b, days_ago=2, looks=1)
        watch(store, club["ryder"]["id"], c, days_ago=4, looks=5)
        assert [x["title"] for x in film(client, h, "coach", club["ryder"]["id"])["clips"]] == ["B", "C", "A"]

    def test_nothing_about_the_comprehension_answer_is_per_player_here(self, api, club, store):
        client, h = api
        cid = clip(store, club, "With a question")
        watch(store, club["ryder"]["id"], cid)
        store.conn.execute("UPDATE clip_watches SET answered = 1, answer_ok = 1 WHERE clip_id = ?", (cid,))
        store.conn.commit()
        c = film(client, h, "coach", club["ryder"]["id"])["clips"][0]
        assert not {"answered", "answer_ok", "settled", "correct"} & set(c)

    def test_the_screen_says_going_back_is_the_module_working(self):
        html = (STATIC / "coach.html").read_text(encoding="utf-8")
        assert "Going back to a clip is the film module working" in html and "Newest first" in html


class TestWhoMaySee:
    def test_a_coach_cannot_see_another_teams_players_film(self, api, club, store):
        client, h = api
        watch(store, club["sam"]["id"], clip(store, club, "Secret"))
        assert client.get(f"/api/coach/athletes/{club['sam']['id']}/training", headers=h("coach")).status_code == 404

    def test_a_director_sees_anyone(self, api, club, store):
        client, h = api
        watch(store, club["sam"]["id"], clip(store, club, "Open"))
        assert film(client, h, "director", club["sam"]["id"])["total_clips"] == 1

    def test_one_players_film_is_not_in_anothers(self, api, club, store):
        client, h = api
        watch(store, club["sam"]["id"], clip(store, club, "Sam's"))
        assert film(client, h, "director", club["ryder"]["id"])["clips"] == []

    def test_the_other_clip_rows_do_not_move(self, api, club, store):
        """The rest of the panel is as it was: the film block is added, nothing replaced."""
        client, h = api
        body = client.get(f"/api/coach/athletes/{club['ryder']['id']}/training", headers=h("coach")).json()
        assert {"athlete", "strip", "totals", "by_drill", "sessions", "film"} <= set(body)


class TestTheScreen:
    HTML = (STATIC / "coach.html").read_text(encoding="utf-8")

    def test_the_panel_has_a_film_watched_section_fed_from_the_response(self):
        assert "function renderFilmLog(f)" in self.HTML and "renderFilmLog(d.film)" in self.HTML
        assert "Film watched" in self.HTML and "watched more than once" in self.HTML
