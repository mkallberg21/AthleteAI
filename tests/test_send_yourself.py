"""No outbound email configured: the director sends the invites himself.

This is the pilot's starting state. Nothing may claim it was sent; every
invite comes back with the whole message (to, subject, text with the link)
so the dashboard can hand it to the director's own mail app, and the
Families card keeps saying "not invited" rather than "invited" for a mail
that never went anywhere.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import contacts as C
from offdays import invites, roster
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store

CSV = "Name,Birth Year,Parent Email\nMason Reed,2013,mason.parent@example.com\n"


@pytest.fixture(autouse=True)
def no_smtp(monkeypatch):
    from dataclasses import replace
    monkeypatch.setattr(invites, "CONFIG", replace(CONFIG, smtp_host="", app_base_url="https://app.0ffdays.com"))
    assert not invites.CONFIG.smtp_configured


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "nosmtp.db"))
    yield TestClient(api_module.app)
    api_module._store = None


@pytest.fixture
def org(client):
    made = client.post("/api/orgs", json={"name": "Mad Dog Lacrosse", "director_name": "Joel White"}).json()
    director = {"Authorization": f"Bearer {made['director']['token']}"}
    team = client.post("/api/teams", headers=director, json={"name": "2031 Red"}).json()
    return {"org_id": made["org_id"], "director": director, "team_id": team.get("team_id", team.get("id"))}


class TestRosterImport:

    def test_nothing_claims_to_have_been_sent(self, client, org):
        r = client.post("/api/coach/roster/import", headers=org["director"],
                        json={"content": CSV, "team_id": org["team_id"]})
        assert r.status_code == 201, r.text
        out = r.json()
        assert out["emailed"] == 0
        assert out["smtp_configured"] is False
        inv = out["guardian_invites"][0]
        assert inv["emailed"] is False
        # Nothing was queued either: there is no server to drain it.
        assert api_module._store.conn.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0] == 0

    def test_the_invite_carries_the_whole_message_for_the_director_to_send(self, client, org):
        out = client.post("/api/coach/roster/import", headers=org["director"],
                          json={"content": CSV, "team_id": org["team_id"]}).json()
        inv = out["guardian_invites"][0]
        assert inv["email"] == "mason.parent@example.com"
        assert inv["link"] == f"https://app.0ffdays.com/app/index.html?invite={inv['code']}"
        assert inv["subject"].startswith("Mad Dog Lacrosse:")
        assert inv["link"] in inv["text"] and inv["code"] in inv["text"]
        assert "Joel White" in inv["text"]
        assert "video never leaves" in inv["text"]

    def test_the_code_in_that_message_works_for_the_parent(self, client, org):
        out = client.post("/api/coach/roster/import", headers=org["director"],
                          json={"content": CSV, "team_id": org["team_id"]}).json()
        code = out["guardian_invites"][0]["code"]
        r = client.post("/api/guardians/redeem", json={"code": code, "display_name": "Mason's Mom", "email": "dana@example.com", "phone": "615 555 0100"})
        assert r.status_code in (200, 201), r.text


class TestCoachAndNudge:

    def test_adding_a_coach_hands_back_the_message(self, client, org):
        r = client.post("/api/coach/staff", headers=org["director"],
                        json={"display_name": "Sam Hill", "email": "sam@example.com", "team_ids": [org["team_id"]]})
        out = r.json()
        assert r.status_code == 201 and out["emailed"] is False
        assert out["smtp_configured"] is False
        assert out["link"] in out["text"] and "Joel White" in out["text"]
        assert out["subject"].startswith("Mad Dog Lacrosse:")

    def test_nudge_hands_back_the_message_too(self, client, org):
        store = api_module._store
        kid = client.post("/api/athletes", headers=org["director"], json={"display_name": "Eli Tanner", "birth_year": 2013}).json()
        C.upsert(store.conn, org_id=org["org_id"], athlete_id=kid["id"], email="eli.parent@example.com")
        r = client.post("/api/coach/families/nudge", headers=org["director"], json={"athlete_id": kid["id"]})
        out = r.json()
        assert r.status_code == 201 and out["emailed"] is False
        assert out["email"] == "eli.parent@example.com"
        assert out["link"] in out["text"]
