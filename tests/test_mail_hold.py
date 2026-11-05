"""The email hold: connecting a mail provider must not, by itself, email parents.

A program's `mail_hold` is ON by default. While it is on, no invite, no coach
welcome and no weekly digest leaves the building, even on a server that has a
mail provider. The director releases it on purpose, and can put it back.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import invites, mailer
from offdays import notifications as notify
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store

CSV = (
    "First Name,Last Name,Birth Year,Parent Email,Parent Phone\n"
    "Mason,Reed,2013,dana@example.com,615-555-0100\n"
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    # A server that HAS a mail provider: the hold is the only thing in the way.
    patched = replace(CONFIG, smtp_host="smtp.test", app_base_url="https://app.0ffdays.com")
    for mod in (invites, mailer):
        monkeypatch.setattr(mod, "CONFIG", patched)
    monkeypatch.setattr(api_module, "CONFIG", patched)
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def _program(client):
    made = client.post("/api/orgs", json={"name": "Club", "sport": "lacrosse", "director_name": "Joel"}).json()
    h = {"Authorization": f"Bearer {made['director']['token']}"}
    team = client.post("/api/teams", json={"name": "2031 Red"}, headers=h).json()
    coach = api_module._store.create_user(made["org_id"], "coach", "Sam", email="sam@example.com")
    return {"org_id": made["org_id"], "h": h, "team": team["id"],
            "coach": {"Authorization": f"Bearer {coach['token']}"}}


def _outbox():
    return api_module._store.conn.execute("SELECT to_email, kind FROM email_outbox").fetchall()


def _import(client, p):
    r = client.post("/api/coach/roster/import", headers=p["h"], json={"content": CSV, "team_id": p["team"]})
    assert r.status_code == 201, r.text
    return r.json()


class TestHeldByDefault:

    def test_a_new_program_starts_held(self, client):
        p = _program(client)
        state = client.get("/api/org/mail-hold", headers=p["h"]).json()
        assert state == {"held": True, "provider_configured": True, "sending": False}

    def test_importing_a_roster_emails_nobody(self, client):
        p = _program(client)
        res = _import(client, p)
        assert _outbox() == []
        assert res["guardian_invites"][0]["emailed"] is False
        assert res["smtp_configured"] is False, "the page must offer 'send it yourself'"

    def test_resending_an_invite_emails_nobody(self, client):
        p = _program(client)
        _import(client, p)
        aid = api_module._store.conn.execute("SELECT id FROM users WHERE role='athlete'").fetchone()["id"]
        r = client.post("/api/coach/families/nudge", headers=p["h"], json={"athlete_id": aid})
        assert r.status_code == 201 and r.json()["emailed"] is False
        assert _outbox() == []

    def test_a_new_coach_is_not_emailed(self, client):
        p = _program(client)
        r = client.post("/api/coach/staff", headers=p["h"], json={
            "display_name": "Pat", "email": "pat@example.com", "team_ids": [p["team"]]})
        assert r.status_code in (200, 201), r.text
        assert r.json()["emailed"] is False
        assert _outbox() == []

    def test_the_weekly_digest_is_not_queued_for_a_held_program(self, client):
        p = _program(client)
        stats = notify.send_coach_digests(api_module._store.conn)
        assert stats["queued"] == 0
        assert [r for r in _outbox() if r["kind"] == mailer.Kind.COACH_DIGEST] == []

    def test_the_director_can_still_email_their_own_digest_to_themselves(self, client):
        """The hold is about families. A preview to your own inbox is yours."""
        p = _program(client)
        api_module._store.conn.execute(
            "UPDATE users SET email = 'joel@example.com' WHERE role = 'director'")
        api_module._store.conn.commit()
        r = client.post("/api/coach/digest/send", headers=p["h"], json={})
        assert r.status_code != 403


class TestReleasingIt:

    def test_a_director_can_release_it(self, client):
        p = _program(client)
        r = client.put("/api/org/mail-hold", headers=p["h"], json={"held": False})
        assert r.status_code == 200
        assert r.json() == {"held": False, "provider_configured": True, "sending": True}

    def test_released_import_emails_the_parent(self, client):
        p = _program(client)
        client.put("/api/org/mail-hold", headers=p["h"], json={"held": False})
        res = _import(client, p)
        assert res["guardian_invites"][0]["emailed"] is True
        assert [r["to_email"] for r in _outbox()] == ["dana@example.com"]

    def test_released_coach_welcome_is_emailed(self, client):
        p = _program(client)
        client.put("/api/org/mail-hold", headers=p["h"], json={"held": False})
        r = client.post("/api/coach/staff", headers=p["h"], json={
            "display_name": "Pat", "email": "pat@example.com", "team_ids": [p["team"]]})
        assert r.json()["emailed"] is True
        assert [x["to_email"] for x in _outbox()] == ["pat@example.com"]

    def test_holding_it_again_stops_new_mail(self, client):
        p = _program(client)
        client.put("/api/org/mail-hold", headers=p["h"], json={"held": False})
        client.put("/api/org/mail-hold", headers=p["h"], json={"held": True})
        _import(client, p)
        assert _outbox() == []

    def test_one_programs_release_does_not_release_another(self, client):
        a, b = _program(client), _program(client)
        client.put("/api/org/mail-hold", headers=a["h"], json={"held": False})
        assert client.get("/api/org/mail-hold", headers=b["h"]).json()["held"] is True
        _import(client, b)
        assert _outbox() == []


class TestWhoMayChangeIt:

    def test_a_coach_cannot_release_it(self, client):
        p = _program(client)
        r = client.put("/api/org/mail-hold", headers=p["coach"], json={"held": False})
        assert r.status_code == 403
        assert client.get("/api/org/mail-hold", headers=p["h"]).json()["held"] is True

    def test_a_coach_can_see_the_state(self, client):
        p = _program(client)
        assert client.get("/api/org/mail-hold", headers=p["coach"]).status_code == 200

    def test_a_signed_out_caller_gets_nothing(self, client):
        assert client.get("/api/org/mail-hold").status_code in (401, 403)
        assert client.put("/api/org/mail-hold", json={"held": False}).status_code in (401, 403)


class TestWhenInDoubtNothingIsSent:

    def test_an_unknown_program_is_held(self, client):
        assert mailer.mail_held(api_module._store.conn, 99999) is True
        assert mailer.mail_held(api_module._store.conn, None) is True

    def test_a_server_with_no_provider_never_sends_even_when_released(self, client, monkeypatch):
        p = _program(client)
        client.put("/api/org/mail-hold", headers=p["h"], json={"held": False})
        none = replace(CONFIG, smtp_host="", app_base_url="https://app.0ffdays.com")
        for mod in (invites, mailer):
            monkeypatch.setattr(mod, "CONFIG", none)
        monkeypatch.setattr(api_module, "CONFIG", none)
        assert client.get("/api/org/mail-hold", headers=p["h"]).json()["sending"] is False
        res = _import(client, p)
        assert res["guardian_invites"][0]["emailed"] is False
        assert _outbox() == []
