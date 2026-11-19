"""A coach or director can drill into one player: what they have been doing, drill by drill."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays.db import connect
from offdays.store import Store


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def db():
    return api_module._store.conn


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def club(client):
    made = client.post("/api/orgs", json={"name": "Nashville Dogs", "sport": "lacrosse", "accept_terms": True,
                                          "director_name": "Matt"}).json()
    d = bearer(made["director"]["token"])
    red = client.post("/api/teams", json={"name": "2031 Red"}, headers=d).json()["id"]
    blue = client.post("/api/teams", json={"name": "2032 Blue"}, headers=d).json()["id"]
    joel = client.post("/api/coach/staff", headers=d, json={"display_name": "Joel", "email": "j@example.com", "team_ids": [red]}).json()
    csv = "First Name,Last Name,Birth Year\nDillon,Langdon,2013\nBen,Amden,2013\n"
    client.post("/api/coach/roster/import", headers=d, json={"content": csv, "team_id": red, "invite_guardians": False})
    client.post("/api/coach/roster/import", headers=d, json={"content": "First Name,Last Name,Birth Year\nCole,Dretler,2014\n",
                                                             "team_id": blue, "invite_guardians": False})
    ids = {r["display_name"]: r["athlete_id"] for r in client.get("/api/coach/team-ranking", headers=d).json()["rows"]}
    return {"d": d, "red": red, "blue": blue, "joel": bearer(joel["code"]), "ids": ids, "org_id": made["org_id"]}


def session(athlete, drill="lax_wall_ball_strong", days_ago=0, reps=40, status="counted", own=False, note="", minutes=5):
    when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")
    notes = json.dumps(["Logged by the athlete because the camera could not count this work."
                        + (f" Note: {note}" if note else "")] if own else [])
    db().execute(
        "INSERT INTO sessions(athlete_id, drill_key, nonce, started_at, submitted_at, completed_at, duration_ms, reps_total, "
        "reps_left, reps_right, status, integrity_notes, self_reported, xp_awarded) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (athlete, drill, uuid.uuid4().hex, when, when, when, minutes * 60_000, reps, reps // 2, reps - reps // 2, status, notes,
         1 if own else 0, 25))
    db().commit()


def get(client, who, athlete, **q):
    return client.get(f"/api/coach/athletes/{athlete}/training", headers=who, params=q)


class TestWhatAPlayerHasBeenDoing:
    def test_the_picture(self, client):
        c = club(client)
        a = c["ids"]["Dillon Langdon"]
        session(a, days_ago=0, reps=40)
        session(a, days_ago=1, reps=30)
        session(a, drill="lax_shooting", days_ago=2, reps=20)
        session(a, days_ago=3, status="review", reps=99)
        res = get(client, c["d"], a)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["athlete"]["display_name"] == "Dillon Langdon" and body["athlete"]["teams"] == ["2031 Red"]
        assert body["totals"]["sessions"] == 3 and body["totals"]["reps"] == 90 and body["totals"]["days_trained"] == 3
        assert body["totals"]["held"] == 1
        drills = {d["drill_key"]: d for d in body["by_drill"]}
        assert drills["lax_wall_ball_strong"]["sessions"] == 3 and drills["lax_wall_ball_strong"]["reps"] == 70
        assert drills["lax_shooting"]["reps"] == 20
        assert [s["status"] for s in body["sessions"]].count("review") == 1
        assert body["athlete"]["last_active"] == datetime.now(timezone.utc).date().isoformat()
        assert "level" in body["athlete"] and "streak" in body["athlete"] and isinstance(body["athlete"]["badges"], list)

    def test_a_strip_of_the_last_28_days(self, client):
        c = club(client)
        a = c["ids"]["Dillon Langdon"]
        session(a, days_ago=0)
        session(a, days_ago=5, own=True, minutes=20, reps=0)
        strip = get(client, c["d"], a).json()["strip"]
        assert len(strip) == 28 and strip[-1]["sessions"] == 1 and strip[-6]["logged"] == 1
        assert sum(1 for s in strip if s["sessions"]) == 2

    def test_a_player_with_nothing_yet_still_opens(self, client):
        c = club(client)
        body = get(client, c["d"], c["ids"]["Ben Amden"]).json()
        assert body["totals"]["sessions"] == 0 and body["sessions"] == [] and body["athlete"]["last_active"] is None

    def test_the_window_can_be_chosen(self, client):
        c = club(client)
        a = c["ids"]["Dillon Langdon"]
        session(a, days_ago=2)
        session(a, days_ago=20)
        assert get(client, c["d"], a, days=7).json()["totals"]["sessions"] == 1
        assert get(client, c["d"], a, days=30).json()["totals"]["sessions"] == 2
        assert get(client, c["d"], a, days=3).status_code == 422


class TestWorkTheyLoggedThemselvesIsLabelled:
    def test_it_is_marked_and_its_note_is_there_but_it_is_not_mixed_in_as_measured(self, client):
        c = club(client)
        a = c["ids"]["Dillon Langdon"]
        session(a, own=True, drill="lax_wall_ball_strong", note="Practised with my brother", minutes=20, reps=0)
        s = get(client, c["d"], a).json()["sessions"][0]
        assert s["self_reported"] is True and s["minutes"] == 20.0
        assert any("Practised with my brother" in n for n in s["notes"])

    def test_the_screen_labels_it_logged_by_player(self):
        html = (Path(api_module.__file__).parent / "web" / "static" / "coach.html").read_text(encoding="utf-8")
        assert "logged by player" in html and "never for rankings or levels" in html
        assert "data-open-athlete" in html and "/training?days=" in html


class TestWhoMayLook:
    def test_a_coach_sees_a_player_on_their_team(self, client):
        c = club(client)
        assert get(client, c["joel"], c["ids"]["Dillon Langdon"]).status_code == 200

    def test_a_coach_cannot_see_a_player_on_another_team(self, client):
        c = club(client)
        res = get(client, c["joel"], c["ids"]["Cole Dretler"])
        assert res.status_code == 404 and "Cole" not in res.text

    def test_a_director_sees_every_team(self, client):
        c = club(client)
        assert get(client, c["d"], c["ids"]["Cole Dretler"]).status_code == 200

    def test_another_programs_director_gets_nothing(self, client):
        c = club(client)
        other = client.post("/api/orgs", json={"name": "Other", "sport": "lacrosse", "accept_terms": True,
                                               "director_name": "Dana"}).json()
        assert get(client, bearer(other["director"]["token"]), c["ids"]["Dillon Langdon"]).status_code == 404

    def test_only_an_athlete_can_be_looked_up_not_a_coach_or_director(self, client):
        c = club(client)
        staff = client.get("/api/coach/staff", headers=c["d"]).json()["staff"]
        for person in staff:
            assert get(client, c["d"], person["id"]).status_code == 404

    def test_an_unknown_id_looks_the_same_as_one_that_is_not_theirs(self, client):
        c = club(client)
        a = get(client, c["joel"], 999999)
        b = get(client, c["joel"], c["ids"]["Cole Dretler"])
        assert a.status_code == b.status_code == 404 and a.json() == b.json()

    def test_a_parent_and_a_player_cannot_use_it(self, client):
        c = club(client)
        a = c["ids"]["Dillon Langdon"]
        assert client.get(f"/api/coach/athletes/{a}/training").status_code in (401, 403)

    def test_a_removed_coach_loses_it(self, client):
        c = club(client)
        joel_id = [s["id"] for s in client.get("/api/coach/staff", headers=c["d"]).json()["staff"] if s["display_name"] == "Joel"][0]
        client.post(f"/api/coach/staff/{joel_id}/remove", headers=c["d"], json={})
        assert get(client, c["joel"], c["ids"]["Dillon Langdon"]).status_code == 401


class TestWhatItNeverShows:
    def test_no_team_targets_no_rank_no_other_player(self, client):
        c = club(client)
        a = c["ids"]["Dillon Langdon"]
        session(a)
        session(c["ids"]["Ben Amden"], reps=500)
        text = json.dumps(get(client, c["d"], a).json()).lower()
        for banned in ("daily_wall_ball", "daily_shots", "rank", "ben amden", "cole", "guardian", "parent_email", "token"):
            assert banned not in text, banned
        assert "Ben" not in json.dumps(get(client, c["d"], a).json()["sessions"])


class TestOrder:
    def test_newest_day_first_even_when_synced_late(self, client):
        c = club(client)
        a = c["ids"]["Dillon Langdon"]
        session(a, days_ago=0)
        session(a, days_ago=4)          # recorded offline, uploaded after: a higher id, an older day
        days = [s["day"] for s in get(client, c["d"], a).json()["sessions"]]
        assert days == sorted(days, reverse=True)


class TestHeldWorkIsNotPassedOffAsDone:
    def test_a_session_held_for_review_is_not_last_trained_or_on_the_strip(self, client):
        c = club(client)
        a = c["ids"]["Dillon Langdon"]
        session(a, days_ago=3, reps=30)
        session(a, days_ago=0, reps=500, status="review")
        body = get(client, c["d"], a).json()
        assert body["athlete"]["last_active"] == (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
        assert body["strip"][-1]["sessions"] == 0 and body["strip"][-4]["sessions"] == 1
        assert body["totals"]["sessions"] == 1 and body["totals"]["held"] == 1
