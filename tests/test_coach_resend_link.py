"""A director can resend a coach their sign-in link: a new link by email naming their teams, the old one dead."""
from __future__ import annotations

import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import invites, mailer
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store


class Recorder:
    def __init__(self):
        self.sent = []

    def send(self, to_email, subject, html, text, headers):
        self.sent.append({"to": to_email, "subject": subject, "html": html, "text": text})
        return mailer.SendResult(ok=True)


@pytest.fixture
def rec(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(mailer, "default_transport", lambda: r)
    return r


@pytest.fixture
def client(tmp_path, monkeypatch, rec):
    patched = replace(CONFIG, smtp_host="smtp.test", app_base_url="https://app.0ffdays.com")
    for mod in (invites, mailer):
        monkeypatch.setattr(mod, "CONFIG", patched)
    monkeypatch.setattr(api_module, "CONFIG", patched)
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def setup(client, release=True, name="Joel White", email="joel@example.com"):
    made = client.post("/api/orgs", json={"name": "Nashville Dogs", "sport": "lacrosse", "accept_terms": True,
                                          "director_name": "Matt Kallberg"}).json()
    h = {"Authorization": f"Bearer {made['director']['token']}"}
    if release:
        client.put("/api/org/mail-hold", headers=h, json={"held": False})
    red = client.post("/api/teams", json={"name": "2031 Red"}, headers=h).json()["id"]
    blue = client.post("/api/teams", json={"name": "2032 Blue"}, headers=h).json()["id"]
    coach = client.post("/api/coach/staff", headers=h, json={"display_name": name, "email": email, "team_ids": [red]}).json()
    return {"h": h, "red": red, "blue": blue, "coach": coach, "org_id": made["org_id"], "director_id": made["director"]["id"]
            if "id" in made["director"] else None}


def me(client, token):
    return client.get("/api/me", headers={"Authorization": f"Bearer {token}"})


def link_code(text):
    return re.search(r"[?&](?:invite|code|token)=([A-Z0-9]+)", text).group(1)


class TestResend:
    def test_the_coach_gets_a_new_link_naming_the_team_and_the_old_one_stops_working(self, client, rec):
        p = setup(client)
        old = p["coach"]["code"]
        rec.sent.clear()
        res = client.post(f"/api/coach/staff/{p['coach']['user_id']}/resend-link", headers=p["h"])
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["emailed"] is True and body["link"] is None and body["team_names"] == ["2031 Red"]
        assert len(rec.sent) == 1 and rec.sent[0]["to"] == "joel@example.com"
        text = rec.sent[0]["text"]
        assert "new sign-in link" in text and "You are on 2031 Red" in text
        assert "choose the team's drills and add video clips" in text
        new = link_code(text)
        assert new != old
        assert me(client, new).status_code == 200
        assert me(client, old).status_code == 401
        assert new in rec.sent[0]["html"] and "Open your coach dashboard" in rec.sent[0]["html"]

    def test_pressing_it_twice_sends_two_emails_and_only_the_latest_link_works(self, client, rec):
        p = setup(client)
        rec.sent.clear()
        for _ in range(2):
            client.post(f"/api/coach/staff/{p['coach']['user_id']}/resend-link", headers=p["h"])
        assert len(rec.sent) == 2
        first, second = link_code(rec.sent[0]["text"]), link_code(rec.sent[1]["text"])
        assert me(client, first).status_code == 401 and me(client, second).status_code == 200

    def test_a_coach_on_two_teams_sees_both_named(self, client, rec):
        p = setup(client)
        client.post("/api/coach/staff/assign", headers=p["h"], json={"user_id": p["coach"]["user_id"], "team_id": p["blue"]})
        rec.sent.clear()
        client.post(f"/api/coach/staff/{p['coach']['user_id']}/resend-link", headers=p["h"])
        assert "You are on 2031 Red and 2032 Blue" in rec.sent[0]["text"] or "You are on 2032 Blue and 2031 Red" in rec.sent[0]["text"]
        assert "those teams" in rec.sent[0]["text"]

    def test_a_coach_who_may_not_choose_drills_is_not_told_they_can(self, client, rec):
        p = setup(client)
        client.post("/api/coach/staff/drill-choice", headers=p["h"], json={"user_id": p["coach"]["user_id"], "allowed": False})
        rec.sent.clear()
        client.post(f"/api/coach/staff/{p['coach']['user_id']}/resend-link", headers=p["h"])
        t = rec.sent[0]["text"]
        assert "add video clips" in t and "choose the team's drills" not in t

    def test_under_the_hold_nothing_is_sent_and_the_director_gets_the_link_to_pass_on(self, client, rec):
        p = setup(client, release=False)
        res = client.post(f"/api/coach/staff/{p['coach']['user_id']}/resend-link", headers=p["h"]).json()
        assert rec.sent == [] and res["emailed"] is False and res["has_email"] is True
        assert res["link"] and "You are on 2031 Red" in res["text"]
        assert me(client, link_code(res["link"])).status_code == 200

    def test_a_coach_with_no_email_gets_the_link_for_the_director_to_hand_over(self, client, rec):
        p = setup(client, name="Sam Lee", email="")
        res = client.post(f"/api/coach/staff/{p['coach']['user_id']}/resend-link", headers=p["h"]).json()
        assert res["emailed"] is False and res["has_email"] is False and res["link"]
        assert rec.sent == [] or all(m["to"] != "" for m in rec.sent)

    def test_the_email_goes_to_the_address_on_file_never_one_from_the_request(self, client, rec):
        p = setup(client)
        rec.sent.clear()
        client.post(f"/api/coach/staff/{p['coach']['user_id']}/resend-link", headers=p["h"], json={"email": "evil@example.com"})
        assert [m["to"] for m in rec.sent] == ["joel@example.com"]


class TestWhoMayDoIt:
    def test_a_coach_may_not(self, client):
        p = setup(client)
        other = client.post("/api/coach/staff", headers=p["h"], json={"display_name": "Pat", "email": "p@example.com"}).json()
        res = client.post(f"/api/coach/staff/{p['coach']['user_id']}/resend-link",
                          headers={"Authorization": f"Bearer {other['code']}"})
        assert res.status_code == 403
        assert me(client, p["coach"]["code"]).status_code == 200            # and nothing was changed

    def test_an_unknown_coach_is_404(self, client):
        p = setup(client)
        assert client.post("/api/coach/staff/99999/resend-link", headers=p["h"]).status_code == 404

    def test_the_director_cannot_be_reissued_through_it(self, client):
        p = setup(client)
        staff = client.get("/api/coach/staff", headers=p["h"]).json()["staff"]
        did = [s["id"] for s in staff if s["role"] == "director"][0]
        assert client.post(f"/api/coach/staff/{did}/resend-link", headers=p["h"]).status_code == 404

    def test_another_programs_coach_is_404_and_untouched(self, client):
        a = setup(client)
        b = client.post("/api/orgs", json={"name": "Other Club", "sport": "lacrosse", "accept_terms": True,
                                           "director_name": "Dana"}).json()
        hb = {"Authorization": f"Bearer {b['director']['token']}"}
        assert client.post(f"/api/coach/staff/{a['coach']['user_id']}/resend-link", headers=hb).status_code == 404
        assert me(client, a["coach"]["code"]).status_code == 200


class TestTheButton:
    @staticmethod
    def page():
        from pathlib import Path
        return (Path(api_module.__file__).parent / "web" / "static" / "coach.html").read_text(encoding="utf-8")

    def test_each_coach_row_has_it_and_it_asks_first(self):
        html = self.page()
        assert 'data-resend-link="${person.id}"' in html and "Resend sign-in link" in html
        assert "/resend-link`, { method: 'POST' }" in html
        assert "Their old link stops working." in html

    def test_it_is_only_on_coach_rows(self):
        html = self.page()
        i = html.index('data-resend-link="${person.id}"')
        assert html.rfind("person.role === 'coach'", 0, i) > html.rfind("person.role === 'director'", 0, i)


class TestAddingACoachWithNoTeam:
    def test_the_first_sign_in_email_still_goes_out_when_no_team_is_picked(self, client, rec):
        p = setup(client)
        res = client.post("/api/coach/staff", headers=p["h"], json={"display_name": "Pat Lee", "email": "pat@example.com"})
        assert res.status_code == 201 and res.json()["emailed"] is True
        text = [m for m in outbox_texts()][-1]
        assert "added you as a coach" in text and "You are on" not in text and "new sign-in link" not in text


def outbox_texts():
    from offdays.api import _store
    return [r[0] for r in _store.conn.execute("SELECT text_body FROM email_outbox ORDER BY id")]
