"""A director can drill into a team: who is on it, who has a login and who has not, and what each has been doing."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays.db import connect
from offdays.store import Store

PARENT = "robert.langdon@example.com"


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
    empty = client.post("/api/teams", json={"name": "2033 Gold"}, headers=d).json()["id"]
    joel = client.post("/api/coach/staff", headers=d, json={"display_name": "Joel", "email": "j@example.com", "team_ids": [red]}).json()
    csv = (f"First Name,Last Name,Birth Year,Parent Email\nDillon,Langdon,2013,{PARENT}\nBen,Amden,2013,jess@example.com\n"
           "Cy,Cole,2013,\n")
    out = client.post("/api/coach/roster/import", headers=d, json={"content": csv, "team_id": red}).json()
    client.post("/api/coach/roster/import", headers=d, json={"content": "First Name,Last Name,Birth Year\nCole,Dretler,2014\n",
                                                             "team_id": blue, "invite_guardians": False})
    ids = {r["display_name"]: r["athlete_id"] for r in client.get("/api/coach/team-ranking", headers=d).json()["rows"]}
    return {"d": d, "red": red, "blue": blue, "empty": empty, "joel": bearer(joel["code"]), "joel_id": joel["user_id"],
            "ids": ids, "invites": out["guardian_invites"], "org_id": made["org_id"]}


def session(athlete, days_ago=0, own=False, status="counted"):
    when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")
    db().execute(
        "INSERT INTO sessions(athlete_id, drill_key, nonce, started_at, submitted_at, completed_at, duration_ms, reps_total, status, "
        "integrity_notes, self_reported) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (athlete, "lax_wall_ball_strong", uuid.uuid4().hex, when, when, when, 300000, 30, status, "[]", 1 if own else 0))
    db().commit()


def detail(client, who, team):
    return client.get(f"/api/coach/teams/{team}/detail", headers=who)


def player(body, name):
    return [p for p in body["players"] if p["display_name"] == name][0]


def parent_up(client, c, who="Dillon Langdon"):
    code = [i for i in c["invites"] if i["email"] == PARENT][0]["code"]
    red = client.post("/api/guardians/redeem", json={"code": code, "display_name": "Robert", "email": PARENT,
                                                      "phone": "615-555-0101"}).json()
    return red["token"]


class TestWhoHasALogin:
    def test_a_fresh_roster_shows_nobody_signed_up(self, client):
        c = club(client)
        body = detail(client, c["d"], c["red"]).json()
        assert body["team"]["name"] == "2031 Red" and body["summary"]["players"] == 3
        assert body["summary"]["parent_signed_up"] == 0 and body["summary"]["athlete_signed_in"] == 0
        assert player(body, "Cy Cole")["stage"] == "no_parent"
        assert player(body, "Dillon Langdon")["parent_signed_up"] is False

    def test_a_parent_who_signed_up_is_shown(self, client):
        c = club(client)
        parent_up(client, c)
        body = detail(client, c["d"], c["red"]).json()
        assert player(body, "Dillon Langdon")["parent_signed_up"] is True
        assert player(body, "Ben Amden")["parent_signed_up"] is False
        assert body["summary"]["parent_signed_up"] == 1

    def test_an_athlete_who_has_signed_in_is_shown(self, client):
        c = club(client)
        tok = parent_up(client, c)
        kid = c["ids"]["Dillon Langdon"]
        client.post("/api/guardians/consent", headers=bearer(tok), json={"athlete_id": kid, "scope": "participation", "granted": True})
        link = client.post(f"/api/guardians/athlete-link/{kid}", headers=bearer(tok)).json()["link"]
        code = re.search(r"code=([A-Za-z0-9]+)", link).group(1)
        before = player(detail(client, c["d"], c["red"]).json(), "Dillon Langdon")
        assert before["stage"] == "link_sent" and before["athlete_signed_in"] is False
        assert client.get("/api/me", headers=bearer(code)).status_code == 200
        after = player(detail(client, c["d"], c["red"]).json(), "Dillon Langdon")
        assert after["athlete_signed_in"] is True and after["stage"] == "signed_in"

    def test_an_email_login_is_shown_for_the_parent_and_for_the_child_separately(self, client):
        c = club(client)
        tok = parent_up(client, c)
        pid = db().execute("SELECT id FROM users WHERE role = 'guardian'").fetchone()[0]
        db().execute("INSERT INTO credentials(user_id, email, pw_hash, created_at, updated_at) VALUES (?,?,?,?,?)",
                     (pid, PARENT, "x", "2026-01-01", "2026-01-01"))
        db().commit()
        p = player(detail(client, c["d"], c["red"]).json(), "Dillon Langdon")
        assert p["parent_email_login"] is True and p["athlete_email_login"] is False
        kid = c["ids"]["Dillon Langdon"]
        db().execute("INSERT INTO credentials(user_id, email, pw_hash, created_at, updated_at) VALUES (?,?,?,?,?)",
                     (kid, "dillon@example.com", "x", "2026-01-01", "2026-01-01"))
        db().commit()
        body = detail(client, c["d"], c["red"]).json()
        assert player(body, "Dillon Langdon")["athlete_email_login"] is True
        assert player(body, "Ben Amden")["parent_email_login"] is False and body["summary"]["email_login"] == 1
        assert tok


class TestActivity:
    def test_last_trained_and_counts_for_each_player(self, client):
        c = club(client)
        a = c["ids"]["Dillon Langdon"]
        session(a, 0)
        session(a, 2)
        session(a, 20)
        session(a, 0, status="review")
        p = player(detail(client, c["d"], c["red"]).json(), "Dillon Langdon")
        assert p["sessions_7d"] == 2 and p["sessions_30d"] == 3
        assert p["last_trained"] == datetime.now(timezone.utc).date().isoformat()

    def test_logged_work_is_counted_apart(self, client):
        c = club(client)
        a = c["ids"]["Dillon Langdon"]
        session(a, 1)
        session(a, 3)
        session(a, 2, own=True)
        p = player(detail(client, c["d"], c["red"]).json(), "Dillon Langdon")
        assert p["sessions_30d"] == 3 and p["logged_30d"] == 1

    def test_someone_who_has_done_nothing_is_still_listed(self, client):
        c = club(client)
        p = player(detail(client, c["d"], c["red"]).json(), "Ben Amden")
        assert p["last_trained"] is None and p["sessions_7d"] == 0 and p["sessions_30d"] == 0

    def test_how_many_trained_this_week(self, client):
        c = club(client)
        session(c["ids"]["Dillon Langdon"], 1)
        session(c["ids"]["Ben Amden"], 10)
        assert detail(client, c["d"], c["red"]).json()["summary"]["trained_7d"] == 1


class TestOnlyThisTeam:
    def test_players_from_another_team_are_not_here(self, client):
        c = club(client)
        names = [p["display_name"] for p in detail(client, c["d"], c["red"]).json()["players"]]
        assert "Cole Dretler" not in names and len(names) == 3
        assert [p["display_name"] for p in detail(client, c["d"], c["blue"]).json()["players"]] == ["Cole Dretler"]

    def test_a_team_with_nobody_says_so_and_has_no_coach(self, client):
        c = club(client)
        body = detail(client, c["d"], c["empty"]).json()
        assert body["players"] == [] and body["summary"]["no_coach"] is True and body["coaches"] == []

    def test_its_coaches_are_listed(self, client):
        c = club(client)
        body = detail(client, c["d"], c["red"]).json()
        assert [x["display_name"] for x in body["coaches"]] == ["Joel"] and body["summary"]["no_coach"] is False
        assert body["coaches"][0]["has_login"] is False

    def test_a_removed_coach_is_gone_from_it(self, client):
        c = club(client)
        client.post(f"/api/coach/staff/{c['joel_id']}/remove", headers=c["d"], json={})
        body = detail(client, c["d"], c["red"]).json()
        assert body["coaches"] == [] and body["summary"]["no_coach"] is True


class TestWhoMayOpenIt:
    def test_a_director_opens_any_team(self, client):
        c = club(client)
        for t in (c["red"], c["blue"], c["empty"]):
            assert detail(client, c["d"], t).status_code == 200
        assert detail(client, c["d"], c["red"]).json()["can_manage"] is True

    def test_a_coach_opens_only_their_own_team_and_cannot_manage(self, client):
        c = club(client)
        ok = detail(client, c["joel"], c["red"])
        assert ok.status_code == 200 and ok.json()["can_manage"] is False
        assert detail(client, c["joel"], c["blue"]).status_code == 404

    def test_another_programs_director_and_an_unknown_team_are_the_same_404(self, client):
        c = club(client)
        other = client.post("/api/orgs", json={"name": "Other", "sport": "lacrosse", "accept_terms": True,
                                               "director_name": "Dana"}).json()
        a = detail(client, bearer(other["director"]["token"]), c["red"])
        b = detail(client, c["d"], 999999)
        assert a.status_code == b.status_code == 404 and a.json() == b.json()

    def test_nobody_signed_out_can(self, client):
        c = club(client)
        assert client.get(f"/api/coach/teams/{c['red']}/detail").status_code in (401, 403)


class TestWhatItNeverShows:
    def test_no_targets_no_rank_no_secrets(self, client):
        c = club(client)
        parent_up(client, c)
        text = json.dumps(detail(client, c["d"], c["red"]).json()).lower()
        for banned in ("daily_wall_ball", "daily_shots", "rank", "token", "pw_hash"):
            assert banned not in text, banned
        assert "dretler" not in text
