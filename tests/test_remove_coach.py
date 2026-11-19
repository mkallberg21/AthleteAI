"""A director can remove a coach, hand their teams to another coach, and a coach put on a team is emailed."""
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
    import offdays.config as config_mod
    monkeypatch.setattr(config_mod, "CONFIG", patched)
    for mod in (invites, mailer):
        monkeypatch.setattr(mod, "CONFIG", patched)
    monkeypatch.setattr(api_module, "CONFIG", patched)
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def db():
    return api_module._store.conn


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def club(client, release=True):
    made = client.post("/api/orgs", json={"name": "Nashville Dogs", "sport": "lacrosse", "accept_terms": True,
                                          "director_name": "Matt Kallberg"}).json()
    d = bearer(made["director"]["token"])
    if release:
        client.put("/api/org/mail-hold", headers=d, json={"held": False})
    red = client.post("/api/teams", json={"name": "2031 Red"}, headers=d).json()["id"]
    blue = client.post("/api/teams", json={"name": "2032 Blue"}, headers=d).json()["id"]
    joel = client.post("/api/coach/staff", headers=d, json={"display_name": "Joel White", "email": "joel@example.com",
                                                            "team_ids": [red]}).json()
    sam = client.post("/api/coach/staff", headers=d, json={"display_name": "Sam Lee", "email": "sam@example.com",
                                                           "team_ids": []}).json()
    return {"d": d, "red": red, "blue": blue, "joel": joel, "sam": sam, "org_id": made["org_id"]}


def remove(client, c, who, **body):
    return client.post(f"/api/coach/staff/{who['user_id']}/remove", headers=c["d"], json=body)


def teams_of(user_id):
    return [r["name"] for r in db().execute(
        "SELECT t.name FROM team_staff ts JOIN teams t ON t.id = ts.team_id WHERE ts.user_id = ? ORDER BY t.name", (user_id,))]


class TestRemovingACoach:
    def test_their_access_ends_at_once(self, client, rec):
        c = club(client)
        assert client.get("/api/coach/teams", headers=bearer(c["joel"]["code"])).status_code == 200
        res = remove(client, c)  if False else remove(client, c, c["joel"])
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["removed"] is True and body["teams"] == ["2031 Red"] and body["teams_without_coach"] == ["2031 Red"]
        assert client.get("/api/coach/teams", headers=bearer(c["joel"]["code"])).status_code == 401
        assert teams_of(c["joel"]["user_id"]) == []
        assert "Joel White" not in [s["display_name"] for s in client.get("/api/coach/staff", headers=c["d"]).json()["staff"]]

    def test_an_open_email_and_password_session_ends_too(self, client, rec):
        from offdays import passwords
        c = club(client)
        session = passwords.start_session(db(), c["joel"]["user_id"])
        assert client.get("/api/coach/teams", headers=bearer(session)).status_code == 200
        remove(client, c, c["joel"])
        assert client.get("/api/coach/teams", headers=bearer(session)).status_code == 401

    def test_what_they_did_stays_on_record(self, client, rec):
        c = club(client)
        remove(client, c, c["joel"])
        row = db().execute("SELECT active FROM users WHERE id = ?", (c["joel"]["user_id"],)).fetchone()
        assert row is not None and row["active"] == 0

    def test_their_teams_can_go_to_another_coach_who_is_told(self, client, rec):
        c = club(client)
        rec.sent.clear()
        res = remove(client, c, c["joel"], replace_with=c["sam"]["user_id"])
        body = res.json()
        assert body["replaced_by"] == "Sam Lee" and body["teams_without_coach"] == [] and body["notified"] is True
        assert teams_of(c["sam"]["user_id"]) == ["2031 Red"]
        mail = [m for m in rec.sent if m["to"] == "sam@example.com" and "now coaching" in m["subject"]]
        assert len(mail) == 1 and "You are" not in mail[0]["subject"]
        assert "2031 Red" in mail[0]["text"] and "https://app.0ffdays.com/app/index.html" in mail[0]["text"]
        assert "href=\"https://app.0ffdays.com/app/index.html\"" in mail[0]["html"]
        assert not re.search(r"[?&](invite|code|create|reset)=", mail[0]["text"])        # no secret in it

    def test_teams_left_without_a_coach_are_named(self, client, rec):
        c = club(client)
        client.post("/api/coach/staff/assign", headers=c["d"], json={"user_id": c["sam"]["user_id"], "team_id": c["red"]})
        res = remove(client, c, c["joel"]).json()
        assert res["teams_without_coach"] == []                      # Sam still coaches it

    def test_a_director_cannot_be_removed_through_it(self, client, rec):
        c = club(client)
        did = [s["id"] for s in client.get("/api/coach/staff", headers=c["d"]).json()["staff"] if s["role"] == "director"][0]
        res = client.post(f"/api/coach/staff/{did}/remove", headers=c["d"], json={})
        assert res.status_code in (400, 404)

    def test_a_second_director_cannot_be_removed_as_if_they_were_a_coach(self, client, rec):
        c = club(client)
        second = api_module._store.create_user(c["org_id"], "director", "Dana Second", email="dana@example.com")
        res = client.post(f"/api/coach/staff/{second['id']}/remove", headers=c["d"], json={})
        assert res.status_code == 404
        assert client.get("/api/coach/staff", headers=bearer(second["token"])).status_code == 200

    def test_a_coach_cannot_remove_anyone(self, client, rec):
        c = club(client)
        res = client.post(f"/api/coach/staff/{c['sam']['user_id']}/remove", headers=bearer(c["joel"]["code"]), json={})
        assert res.status_code == 403
        assert client.get("/api/coach/teams", headers=bearer(c["sam"]["code"])).status_code == 200

    def test_another_programs_coach_is_untouched(self, client, rec):
        c = club(client)
        other = client.post("/api/orgs", json={"name": "Other", "sport": "lacrosse", "accept_terms": True,
                                               "director_name": "Dana"}).json()
        res = client.post(f"/api/coach/staff/{c['joel']['user_id']}/remove", headers=bearer(other["director"]["token"]), json={})
        assert res.status_code == 404
        assert client.get("/api/coach/teams", headers=bearer(c["joel"]["code"])).status_code == 200

    def test_the_replacement_must_be_in_this_program_and_not_the_same_person(self, client, rec):
        c = club(client)
        other = client.post("/api/orgs", json={"name": "Other", "sport": "lacrosse", "accept_terms": True,
                                               "director_name": "Dana"}).json()
        theirs = client.post("/api/coach/staff", headers=bearer(other["director"]["token"]),
                             json={"display_name": "Eve", "email": "eve@example.com"}).json()
        assert remove(client, c, c["joel"], replace_with=theirs["user_id"]).status_code == 404
        assert remove(client, c, c["joel"], replace_with=c["joel"]["user_id"]).status_code == 400
        assert client.get("/api/coach/teams", headers=bearer(c["joel"]["code"])).status_code == 200       # nothing happened

    def test_a_removed_coach_cannot_be_removed_twice(self, client, rec):
        c = club(client)
        assert remove(client, c, c["joel"]).status_code == 200
        assert remove(client, c, c["joel"]).status_code == 404

    def test_a_coach_in_two_programs_only_leaves_this_one(self, client, rec):
        c = club(client)
        other = client.post("/api/orgs", json={"name": "Other", "sport": "lacrosse", "accept_terms": True,
                                               "director_name": "Dana"}).json()
        api_module._store.add_membership(c["joel"]["user_id"], other["org_id"], "coach")
        remove(client, c, c["joel"])
        row = db().execute("SELECT active FROM users WHERE id = ?", (c["joel"]["user_id"],)).fetchone()
        assert row["active"] == 1
        assert client.get("/api/coach/teams", headers={**bearer(c["joel"]["code"]), "X-Org-Id": str(c["org_id"])}).status_code in (401, 403)


class TestPuttingACoachOnATeam:
    def test_the_coach_is_emailed_with_a_plain_sign_in_link(self, client, rec):
        c = club(client)
        rec.sent.clear()
        res = client.post("/api/coach/staff/assign", headers=c["d"], json={"user_id": c["sam"]["user_id"], "team_id": c["blue"]})
        assert res.json()["emailed"] is True
        mail = [m for m in rec.sent if m["to"] == "sam@example.com"]
        assert len(mail) == 1
        assert "2032 Blue" in mail[0]["subject"] and "choose the team's drills and add video clips" in mail[0]["text"]
        assert "https://app.0ffdays.com/app/index.html" in mail[0]["text"] and "Open 0FFDAYS" in mail[0]["html"]

    def test_a_coach_already_on_the_team_is_not_emailed_again(self, client, rec):
        c = club(client)
        client.post("/api/coach/staff/assign", headers=c["d"], json={"user_id": c["sam"]["user_id"], "team_id": c["blue"]})
        rec.sent.clear()
        res = client.post("/api/coach/staff/assign", headers=c["d"], json={"user_id": c["sam"]["user_id"], "team_id": c["blue"]})
        assert res.json()["emailed"] is False and rec.sent == []

    def test_nothing_is_sent_while_email_is_on_hold(self, client, rec):
        c = club(client, release=False)
        rec.sent.clear()
        res = client.post("/api/coach/staff/assign", headers=c["d"], json={"user_id": c["sam"]["user_id"], "team_id": c["blue"]})
        assert res.json()["assigned"] is True and res.json()["emailed"] is False and rec.sent == []
        assert teams_of(c["sam"]["user_id"]) == ["2032 Blue"]

    def test_a_coach_who_may_not_choose_drills_is_not_told_they_can(self, client, rec):
        c = club(client)
        client.post("/api/coach/staff/drill-choice", headers=c["d"], json={"user_id": c["sam"]["user_id"], "allowed": False})
        rec.sent.clear()
        client.post("/api/coach/staff/assign", headers=c["d"], json={"user_id": c["sam"]["user_id"], "team_id": c["blue"]})
        t = [m for m in rec.sent if m["to"] == "sam@example.com"][0]["text"]
        assert "add video clips" in t and "choose the team's drills" not in t

    def test_an_athlete_or_a_removed_coach_cannot_be_put_on_a_team(self, client, rec):
        c = club(client)
        remove(client, c, c["joel"])
        res = client.post("/api/coach/staff/assign", headers=c["d"], json={"user_id": c["joel"]["user_id"], "team_id": c["blue"]})
        assert res.status_code == 404

    def test_a_new_coach_added_with_a_team_is_emailed_that_team(self, client, rec):
        c = club(client)
        rec.sent.clear()
        client.post("/api/coach/staff", headers=c["d"], json={"display_name": "Pat Lee", "email": "pat@example.com",
                                                              "team_ids": [c["red"], c["blue"]]})
        db_mail = [r["text_body"] for r in db().execute("SELECT text_body FROM email_outbox WHERE to_email = 'pat@example.com'")]
        assert len(db_mail) == 1
        assert "You are on 2031 Red and 2032 Blue" in db_mail[0] or "You are on 2032 Blue and 2031 Red" in db_mail[0]
        assert "?invite=" in db_mail[0] or "code=" in db_mail[0]


class TestTheButtons:
    @staticmethod
    def page():
        from pathlib import Path
        return (Path(api_module.__file__).parent / "web" / "static" / "coach.html").read_text(encoding="utf-8")

    def test_coach_rows_have_a_remove_button_that_asks_and_offers_a_replacement(self):
        html = self.page()
        assert 'data-remove-coach="${person.id}"' in html and "Remove coach" in html
        assert "/remove`, { method: 'POST'" in html
        assert "Give their teams to" in html
        assert "loses access at once" in html
