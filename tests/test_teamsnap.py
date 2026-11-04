"""TeamSnap, connected by the director's consent, pulls players AND parents.

The parent join is the whole point: TeamSnap keeps parents on contact rows
and their emails/phones on rows separate again, so a naive member pull
gets names and birthdays and no way to reach a family. These tests pin the
join with a faked TeamSnap that answers the four requests in TeamSnap's
Collection+JSON shape, plus the OAuth state signing and the routes.
"""

from __future__ import annotations

import dataclasses
import json
import urllib.parse

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import teamsnap
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store


def cj(rows: list[dict]) -> dict:
    """Collection+JSON envelope the way TeamSnap sends it."""
    return {"collection": {"items": [
        {"data": [{"name": k, "value": v} for k, v in r.items()], "links": []} for r in rows
    ]}}


FAKE = {
    "/me": cj([{"id": 7, "first_name": "Joel", "last_name": "White", "email": "joel@example.com"}]),
    "/teams/search": cj([
        {"id": 10745859, "name": "Mad Dog 2031", "season_name": "Spring 2027", "sport_id": 11, "member_count": 4},
        {"id": 999, "name": "Old team", "season_name": "Fall 2025", "sport_id": 11, "member_count": 9},
    ]),
    "/members/search": cj([
        {"id": 1, "first_name": "Mason", "last_name": "Reed", "jersey_number": "7", "birthday": "2013-04-02",
         "position": "Attack", "is_non_player": False, "is_manager": False},
        {"id": 2, "first_name": "Owen", "last_name": "Hale", "jersey_number": "12", "birthday": "2013-09-14",
         "is_non_player": False, "email": "owen@example.com"},
        {"id": 3, "first_name": "Joel", "last_name": "White", "is_non_player": True, "is_manager": True},
        {"id": 4, "first_name": "Sam", "last_name": "Hill", "is_non_player": True},
    ]),
    "/contacts/search": cj([
        {"id": 100, "member_id": 1, "first_name": "Dana", "last_name": "Reed"},
        {"id": 101, "member_id": 1, "first_name": "Chris", "last_name": "Reed"},
        {"id": 102, "member_id": 2, "first_name": "Pat", "last_name": "Hale"},   # no email, no phone
    ]),
    "/contact_email_addresses/search": cj([
        {"id": 500, "contact_id": 100, "email": "dana@example.com"},
        {"id": 501, "contact_id": 101, "email": "chris@example.com"},
    ]),
    "/contact_phone_numbers/search": cj([
        {"id": 600, "contact_id": 100, "phone_number": "615-555-0100"},
    ]),
}


@pytest.fixture
def fake_teamsnap(monkeypatch):
    calls = []

    def _get(token, path, **params):
        calls.append((path, params))
        assert token == "tok-abc", "every call carries the connected token"
        return FAKE[path]

    monkeypatch.setattr(teamsnap, "_get", _get)
    return calls


class TestRosterJoin:

    def test_players_come_with_their_parents_and_staff_are_left_out(self, fake_teamsnap):
        rows = teamsnap.roster("tok-abc", "10745859")
        assert [r["first_name"] for r in rows] == ["Mason", "Owen"]      # Joel, Sam are staff
        mason = rows[0]
        assert mason["guardian_name"] == "Dana Reed"
        assert mason["guardian_email"] == "dana@example.com"
        assert mason["guardian_phone"] == "615-555-0100"
        assert mason["guardian2_name"] == "Chris Reed"
        assert mason["guardian2_email"] == "chris@example.com"
        assert "guardian2_phone" not in mason
        assert mason["birth_date"] == "2013-04-02" and mason["jersey"] == "7"
        assert mason["external_id"] == "1"

    def test_a_kid_whose_contacts_have_no_details_falls_back_to_his_own_email(self, fake_teamsnap):
        rows = teamsnap.roster("tok-abc", "10745859")
        owen = rows[1]
        assert "guardian_email" not in owen
        assert owen["email"] == "owen@example.com"

    def test_four_requests_all_scoped_to_the_team(self, fake_teamsnap):
        teamsnap.roster("tok-abc", "10745859")
        assert [p for p, _ in fake_teamsnap] == [
            "/members/search", "/contacts/search",
            "/contact_email_addresses/search", "/contact_phone_numbers/search"]
        assert all(params == {"team_id": "10745859"} for _, params in fake_teamsnap)

    def test_the_rows_go_through_the_same_importer_as_a_csv(self, fake_teamsnap):
        from offdays import roster, roster_sync
        rows = teamsnap.roster("tok-abc", "10745859")
        parsed = roster.parse(roster_sync.rows_to_csv(rows))
        by_name = {a.display_name.split()[0]: a for a in parsed.athletes}
        assert by_name["Mason"].guardian_email == "dana@example.com"
        assert by_name["Mason"].guardian_phone and "615" in by_name["Mason"].guardian_phone
        assert by_name["Mason"].guardian2_email == "chris@example.com"

    def test_teams_are_newest_season_first(self, fake_teamsnap):
        ts = teamsnap.teams("tok-abc")
        assert [t["name"] for t in ts] == ["Mad Dog 2031", "Old team"]
        assert ts[0] == {"id": "10745859", "name": "Mad Dog 2031", "season": "Spring 2027",
                         "sport_id": 11, "member_count": 4}


class TestState:

    def test_state_round_trips_and_is_bound_to_the_secret(self):
        s = teamsnap.make_state("k1", 5, 9)
        assert teamsnap.read_state("k1", s) == (5, 9)
        with pytest.raises(teamsnap.TeamSnapError):
            teamsnap.read_state("k2", s)
        with pytest.raises(teamsnap.TeamSnapError):
            teamsnap.read_state("k1", s[:-1] + ("a" if s[-1] != "a" else "b"))

    def test_an_old_state_is_refused(self, monkeypatch):
        s = teamsnap.make_state("k", 1, 1)
        monkeypatch.setattr(teamsnap.time, "time", lambda: 10 ** 10)
        with pytest.raises(teamsnap.TeamSnapError, match="expired"):
            teamsnap.read_state("k", s)


@pytest.fixture
def configured(monkeypatch):
    patched = dataclasses.replace(
        CONFIG, teamsnap_client_id="cid", teamsnap_client_secret="csec",
        app_base_url="https://app.0ffdays.com", secret_key="srv")
    monkeypatch.setattr(api_module, "CONFIG", patched)
    return patched


@pytest.fixture
def client(tmp_path, configured):
    api_module._store = Store(connect(tmp_path / "ts.db"))
    yield TestClient(api_module.app)
    api_module._store = None


@pytest.fixture
def org(client):
    made = client.post("/api/orgs", json={"name": "Mad Dog", "sport": "lacrosse", "director_name": "Joel"}).json()
    director = {"Authorization": f"Bearer {made['director']['token']}"}
    team = client.post("/api/teams", json={"name": "2031 Blue"}, headers=director).json()
    coach = api_module._store.create_user(made["org_id"], "coach", "Sam")
    return {"org_id": made["org_id"], "director": director, "team_id": team["id"],
            "coach": {"Authorization": f"Bearer {coach['token']}"}}


class TestRoutes:

    def test_not_offered_without_credentials(self, tmp_path, monkeypatch):
        monkeypatch.setattr(api_module, "CONFIG", dataclasses.replace(CONFIG, teamsnap_client_id="", teamsnap_client_secret=""))
        api_module._store = Store(connect(tmp_path / "x.db"))
        try:
            c = TestClient(api_module.app)
            made = c.post("/api/orgs", json={"name": "X", "director_name": "D"}).json()
            h = {"Authorization": f"Bearer {made['director']['token']}"}
            assert c.get("/api/teamsnap/status", headers=h).json()["offered"] is False
            assert c.get("/api/teamsnap/connect", headers=h).status_code == 404
        finally:
            api_module._store = None

    def test_connect_gives_teamsnaps_consent_url_bound_to_this_program(self, client, org):
        r = client.get("/api/teamsnap/connect", headers=org["director"])
        assert r.status_code == 200
        url = r.json()["url"]
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert url.startswith(teamsnap.AUTH_URL)
        assert q["client_id"] == ["cid"] and q["scope"] == ["read"]
        assert q["redirect_uri"] == ["https://app.0ffdays.com/api/teamsnap/callback"]
        assert teamsnap.read_state("srv", q["state"][0])[0] == org["org_id"]
        # A coach cannot connect the program's account.
        assert client.get("/api/teamsnap/connect", headers=org["coach"]).status_code == 403

    def test_callback_stores_the_token_and_sends_the_director_back(self, client, org, monkeypatch):
        monkeypatch.setattr(teamsnap, "exchange_code", lambda *a: {"access_token": "tok-abc", "scope": "read"})
        monkeypatch.setattr(teamsnap, "_get", lambda token, path, **p: FAKE[path])
        state = teamsnap.make_state("srv", org["org_id"], 1)
        r = client.get(f"/api/teamsnap/callback?code=c0de&state={state}", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/app/coach.html?teamsnap=1&teamsnap=connected"
        st = client.get("/api/teamsnap/status", headers=org["director"]).json()
        assert st["connected"] is True and st["user"] == "Joel White"
        # The token is never read back out over the API.
        assert "tok-abc" not in json.dumps(st)

    def test_a_forged_state_attaches_nothing(self, client, org, monkeypatch):
        monkeypatch.setattr(teamsnap, "exchange_code", lambda *a: {"access_token": "tok-abc"})
        state = teamsnap.make_state("other-secret", org["org_id"], 1)
        r = client.get(f"/api/teamsnap/callback?code=c0de&state={state}", follow_redirects=False)
        assert "teamsnap=error" in r.headers["location"]
        assert client.get("/api/teamsnap/status", headers=org["director"]).json()["connected"] is False

    def test_pick_a_team_and_the_roster_previews_with_parents(self, client, org, fake_teamsnap):
        api_module._store.set_teamsnap(org["org_id"], "tok-abc", "Joel White")
        teams = client.get("/api/teamsnap/teams", headers=org["director"]).json()["teams"]
        assert teams[0]["id"] == "10745859"
        r = client.post("/api/teamsnap/link", headers=org["director"],
                        json={"team_id": org["team_id"], "teamsnap_team_id": "10745859"})
        assert r.status_code == 201, r.text
        preview = r.json()["preview"]
        assert preview["fetched"] == 2
        link = r.json()["link"]
        assert link["provider"] == "teamsnap" and "tok-abc" not in json.dumps(link)
        # Apply it: the parents are on file.
        r = client.post("/api/coach/roster/sync", headers=org["director"],
                        json={"team_id": org["team_id"], "provider": "teamsnap", "apply": True})
        assert r.status_code == 200, r.text
        parents = client.get("/api/org/parents", headers=org["director"]).json()
        emails = {p["email"] for p in parents["parents"]}
        assert {"dana@example.com", "chris@example.com"} <= emails

    def test_without_a_connection_linking_says_so(self, client, org):
        r = client.post("/api/teamsnap/link", headers=org["director"],
                        json={"team_id": org["team_id"], "teamsnap_team_id": "1"})
        assert r.status_code == 409

    def test_disconnect_is_the_directors(self, client, org):
        api_module._store.set_teamsnap(org["org_id"], "tok-abc", "Joel White")
        assert client.delete("/api/teamsnap", headers=org["coach"]).status_code == 403
        assert client.delete("/api/teamsnap", headers=org["director"]).json() == {"connected": False}
        assert api_module._store.teamsnap_token(org["org_id"]) == ""
