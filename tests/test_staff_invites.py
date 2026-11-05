"""The director adds coaches, and the system hands each one their sign-in.

The director's kickoff is teams -> coaches -> roster. This covers the middle
step: a director names a coach, puts them on teams, and the coach gets an
email with a standing link. A coach cannot add coaches, because adding one
grants access to children's training.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import mailer
from offdays import invites
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store


@pytest.fixture(autouse=True)
def smtp_on(monkeypatch):
    """Email "goes out" only when SMTP is configured; these tests assert it does."""
    from dataclasses import replace
    patched = replace(CONFIG, smtp_host="smtp.test")
    monkeypatch.setattr(invites, "CONFIG", patched)
    monkeypatch.setattr(mailer, "CONFIG", patched)
    monkeypatch.setattr(mailer, "mail_held", lambda conn, org_id: False)


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "staff.db"))
    yield TestClient(api_module.app)
    api_module._store = None


@pytest.fixture
def org(client):
    made = client.post(
        "/api/orgs", json={"name": "Mad Dog Lacrosse", "director_name": "Joel White"}
    ).json()
    director = {"Authorization": f"Bearer {made['director']['token']}"}
    red = client.post("/api/teams", headers=director, json={"name": "2031 Red"}).json()
    blue = client.post("/api/teams", headers=director, json={"name": "2031 Blue"}).json()
    return {"org_id": made["org_id"], "director": director, "red": red, "blue": blue}


def team_id(t):
    return t.get("team_id", t.get("id"))


class TestAddingACoach:

    def test_director_adds_a_coach_on_a_team_and_they_are_emailed(self, client, org):
        r = client.post("/api/coach/staff", headers=org["director"], json={
            "display_name": "Sam Hill", "email": "sam@example.com", "team_ids": [team_id(org["red"])],
        })
        assert r.status_code == 201, r.text
        out = r.json()
        assert out["emailed"] is True
        assert out["link"].endswith(f"/app/index.html?code={out['code']}")

        # The coach can sign in with it and sees only Red.
        coach = {"Authorization": f"Bearer {out['code']}"}
        me = client.get("/api/me", headers=coach).json()
        assert me["role"] == "coach" and me["display_name"] == "Sam Hill"
        staff = client.get("/api/coach/staff", headers=org["director"]).json()["staff"]
        sam = next(p for p in staff if p["display_name"] == "Sam Hill")
        assert [t["name"] for t in sam["teams"]] == ["2031 Red"]

        # And the email is in the outbox, addressed to them, with the link.
        store = api_module._store
        row = store.conn.execute(
            "SELECT to_email, subject, text_body FROM email_outbox WHERE to_email = ?",
            ("sam@example.com",),
        ).fetchone()
        assert row is not None
        assert "Joel White" in row["text_body"] and out["code"] in row["text_body"]

    def test_no_email_means_the_code_is_read_out(self, client, org):
        r = client.post("/api/coach/staff", headers=org["director"], json={"display_name": "Sam Hill"})
        assert r.status_code == 201
        assert r.json()["emailed"] is False and r.json()["code"]

    def test_a_coach_cannot_add_coaches(self, client, org):
        made = client.post("/api/coach/staff", headers=org["director"], json={"display_name": "Sam Hill"}).json()
        coach = {"Authorization": f"Bearer {made['code']}"}
        r = client.post("/api/coach/staff", headers=coach, json={"display_name": "Pat Lee"})
        assert r.status_code == 403

    def test_a_team_from_another_program_is_refused(self, client, org):
        other = client.post("/api/orgs", json={"name": "Elsewhere", "director_name": "X"}).json()
        other_team = client.post(
            "/api/teams", headers={"Authorization": f"Bearer {other['director']['token']}"},
            json={"name": "Theirs"},
        ).json()
        r = client.post("/api/coach/staff", headers=org["director"], json={
            "display_name": "Sam Hill", "team_ids": [team_id(other_team)],
        })
        assert r.status_code == 404
        # And no coach was created on the way to the refusal.
        staff = client.get("/api/coach/staff", headers=org["director"]).json()["staff"]
        assert all(p["display_name"] != "Sam Hill" for p in staff)
