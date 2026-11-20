"""A director can hand director access to someone else: administrators who run the program next to its owner."""
from __future__ import annotations

import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import admins, invites, mailer
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
    for mod in (invites, mailer, admins):
        monkeypatch.setattr(mod, "CONFIG", patched)
    monkeypatch.setattr(api_module, "CONFIG", patched)
    api_module._store = Store(connect(tmp_path / "ad.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def db():
    return api_module._store.conn


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def club(client, name="Nashville Dogs", release=True):
    made = client.post("/api/orgs", json={"name": name, "sport": "lacrosse", "accept_terms": True,
                                          "director_name": "Matt Kallberg"}).json()
    d = bearer(made["director"]["token"])
    if release:
        client.put("/api/org/mail-hold", headers=d, json={"held": False})
    return {"org": made["org_id"], "owner": d, "owner_id": client.get("/api/coach/admins", headers=d).json()["admins"][0]["id"]}


def add(client, c, name="Dana Park", email="dana@example.com", who=None):
    return client.post("/api/coach/admins", headers=who or c["owner"], json={"display_name": name, "email": email})


def admin_headers(client, c, name="Dana Park", email="dana@example.com"):
    r = add(client, c, name, email)
    assert r.status_code == 201, r.text
    return bearer(r.json()["code"]), r.json()


ROSTER = "First Name,Last Name,Birth Year,Parent Email\nBen,Amden,2013,jess@example.com\n"


class TestOwner:
    def test_the_person_who_started_the_program_owns_it(self, client):
        c = club(client)
        got = client.get("/api/coach/admins", headers=c["owner"]).json()
        assert [(a["display_name"], a["is_owner"], a["is_you"]) for a in got["admins"]] == [("Matt Kallberg", True, True)]
        assert got["you_are_owner"] is True and got["owner_name"] == "Matt Kallberg"

    def test_a_coach_cannot_see_the_list(self, client):
        c = club(client)
        coach = api_module._store.create_user(c["org"], "coach", "Sam")
        assert client.get("/api/coach/admins", headers=bearer(coach["token"])).status_code == 403

    def test_owner_is_the_earliest_director_when_nothing_was_ever_recorded(self, client):
        c = club(client)
        _, made = admin_headers(client, c)
        db().execute("UPDATE organizations SET owner_user_id = NULL WHERE id = ?", (c["org"],))
        assert admins.owner_id(db(), c["org"]) == c["owner_id"]


class TestAddingAnAdministrator:
    def test_they_get_a_sign_in_email_with_a_hyperlink_and_the_link_works(self, client, rec):
        c = club(client)
        r = add(client, c)
        assert r.status_code == 201
        out = r.json()
        assert out["emailed"] is True and out["promoted"] is False
        mail = [m for m in rec.sent if m["to"] == "dana@example.com"][0]
        assert "Matt Kallberg made you an administrator of Nashville Dogs" in mail["text"]
        link = re.search(r'<a href="(https://app\.0ffdays\.com/app/index\.html\?code=[^"]+)"', mail["html"]).group(1)
        assert link == out["link"] and out["link"] in mail["text"]
        me = client.get("/api/me", headers=bearer(out["code"]))
        assert me.status_code == 200 and me.json()["role"] == "director"

    def test_an_administrator_can_do_a_directors_work_like_uploading_a_roster(self, client):
        c = club(client)
        h, _ = admin_headers(client, c)
        team = client.post("/api/teams", json={"name": "2031 Red"}, headers=h)
        assert team.status_code in (200, 201), team.text
        imp = client.post("/api/coach/roster/import", headers=h, json={"content": ROSTER, "team_id": team.json()["id"]})
        assert imp.status_code in (200, 201), imp.text
        assert client.get("/api/coach/staff", headers=h).status_code == 200

    def test_they_are_in_the_program_not_a_new_one(self, client):
        c = club(client)
        h, made = admin_headers(client, c)
        assert client.get("/api/coach/admins", headers=h).json()["admins"][1]["display_name"] == "Dana Park"
        row = db().execute("SELECT org_id FROM users WHERE id = ?", (made["user_id"],)).fetchone()
        assert row["org_id"] == c["org"]

    def test_while_email_is_on_hold_nothing_is_sent_and_the_owner_gets_the_link(self, client, rec):
        c = club(client, release=False)
        out = add(client, c).json()
        assert out["emailed"] is False and rec.sent == []
        assert out["link"].startswith("https://app.0ffdays.com/app/index.html?code=") and "administrator" in out["text"]

    def test_an_email_is_required(self, client):
        c = club(client)
        assert add(client, c, email="not an email").status_code == 400

    def test_the_same_email_twice_is_refused(self, client):
        c = club(client)
        add(client, c)
        r = add(client, c, name="Other Dana", email="DANA@example.com")
        assert r.status_code == 409 and "already an administrator" in r.json()["detail"]

    def test_there_is_a_limit(self, client):
        c = club(client)
        for i in range(admins.MAX_ADMINS - 1):
            assert add(client, c, name=f"Admin {i}", email=f"a{i}@example.com").status_code == 201
        r = add(client, c, name="One more", email="more@example.com")
        assert r.status_code == 409 and str(admins.MAX_ADMINS) in r.json()["detail"]

    def test_a_coach_with_that_email_is_promoted_not_duplicated(self, client, rec):
        c = club(client)
        coach = api_module._store.create_user(c["org"], "coach", "Sam Hill", email="sam@example.com")
        before = db().execute("SELECT COUNT(*) FROM users").fetchone()[0]
        r = add(client, c, name="Sam H", email="Sam@Example.com")
        assert r.status_code == 201 and r.json()["promoted"] is True and r.json()["user_id"] == coach["id"]
        assert r.json()["code"] is None
        assert db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == before
        me = client.get("/api/me", headers=bearer(coach["token"])).json()
        assert me["role"] == "director"
        assert any("You were a coach" in m["text"] for m in rec.sent if m["to"] == "sam@example.com")

    def test_an_email_address_is_not_a_way_to_find_out_who_else_is_in_the_program(self, client):
        c = club(client)
        other = club(client, name="Other Club")
        add(client, other, name="Zed", email="zed@example.com")
        r = add(client, c, name="Zed", email="zed@example.com")
        assert r.status_code == 201 and r.json()["promoted"] is False


class TestOnlyTheOwnerManagesAdministrators:
    def test_an_administrator_cannot_add_remove_hand_over_or_change_the_plan(self, client):
        c = club(client)
        h, made = admin_headers(client, c)
        assert add(client, c, name="Third", email="t@example.com", who=h).status_code == 403
        assert client.post(f"/api/coach/admins/{c['owner_id']}/remove", headers=h).status_code == 403
        assert client.post(f"/api/coach/admins/{made['user_id']}/make-owner", headers=h,
                           json={"confirm_name": "Nashville Dogs"}).status_code == 403
        r = client.post("/api/billing/plan", headers=h, json={"plan_code": "club", "seats": 10})
        assert r.status_code == 403 and "owner" in r.json()["detail"]

    def test_the_message_names_who_can(self, client):
        c = club(client)
        h, _ = admin_headers(client, c)
        assert "Matt Kallberg" in add(client, c, name="X", email="x@example.com", who=h).json()["detail"]

    def test_a_coach_cannot_add_one(self, client):
        c = club(client)
        coach = api_module._store.create_user(c["org"], "coach", "Sam")
        assert add(client, c, who=bearer(coach["token"])).status_code == 403


class TestRemoving:
    def test_access_ends_at_once(self, client):
        c = club(client)
        h, made = admin_headers(client, c)
        assert client.get("/api/coach/admins", headers=h).status_code == 200
        r = client.post(f"/api/coach/admins/{made['user_id']}/remove", headers=c["owner"])
        assert r.status_code == 200 and r.json()["removed"] is True
        assert client.get("/api/coach/admins", headers=h).status_code in (401, 403)
        assert [a["display_name"] for a in client.get("/api/coach/admins", headers=c["owner"]).json()["admins"]] == ["Matt Kallberg"]

    def test_the_owner_and_yourself_cannot_be_removed(self, client):
        c = club(client)
        r = client.post(f"/api/coach/admins/{c['owner_id']}/remove", headers=c["owner"])
        assert r.status_code == 400

    def test_the_owner_is_protected_even_from_another_caller(self, client):
        c = club(client)
        _, made = admin_headers(client, c)
        with pytest.raises(admins.AdminError, match="owner cannot be removed"):
            admins.remove_admin(db(), c["org"], made["user_id"], c["owner_id"])
        assert admins.owner_id(db(), c["org"]) == c["owner_id"]

    def test_someone_who_is_not_an_administrator_here_is_not_found(self, client):
        c = club(client)
        coach = api_module._store.create_user(c["org"], "coach", "Sam")
        assert client.post(f"/api/coach/admins/{coach['id']}/remove", headers=c["owner"]).status_code == 404
        other = club(client, name="Other Club")
        assert client.post(f"/api/coach/admins/{other['owner_id']}/remove", headers=c["owner"]).status_code == 404
        assert client.get("/api/coach/admins", headers=other["owner"]).status_code == 200

    def test_a_removed_administrator_can_be_added_again(self, client):
        c = club(client)
        _, made = admin_headers(client, c)
        client.post(f"/api/coach/admins/{made['user_id']}/remove", headers=c["owner"])
        assert add(client, c).status_code == 201


class TestHandingOver:
    def go(self, client, c, to, **body):
        body.setdefault("confirm_name", "Nashville Dogs")
        return client.post(f"/api/coach/admins/{to}/make-owner", headers=c["owner"], json=body)

    def test_the_new_owner_takes_over_and_the_old_owner_stays_an_administrator(self, client, rec):
        c = club(client)
        h, made = admin_headers(client, c)
        r = self.go(client, c, made["user_id"])
        assert r.status_code == 200 and r.json()["owner_name"] == "Dana Park" and r.json()["you_left"] is False
        # Dana now manages administrators; Matt no longer does, but still runs the program.
        assert add(client, c, name="Third", email="t@example.com", who=h).status_code == 201
        assert add(client, c, name="Fourth", email="f@example.com").status_code == 403
        assert client.get("/api/coach/admins", headers=c["owner"]).json()["you_are_owner"] is False
        assert client.get("/api/coach/staff", headers=c["owner"]).status_code == 200
        assert any(m["to"] == "dana@example.com" and "you now own the program" in m["subject"] for m in rec.sent)

    def test_the_old_owner_can_leave_in_the_same_step(self, client):
        c = club(client)
        h, made = admin_headers(client, c)
        r = self.go(client, c, made["user_id"], step_down=True)
        assert r.status_code == 200 and r.json()["you_left"] is True
        assert client.get("/api/coach/admins", headers=c["owner"]).status_code in (401, 403)
        got = client.get("/api/coach/admins", headers=h).json()
        assert [a["display_name"] for a in got["admins"]] == ["Dana Park"] and got["you_are_owner"] is True

    def test_the_programs_name_must_be_typed(self, client):
        c = club(client)
        _, made = admin_headers(client, c)
        assert self.go(client, c, made["user_id"], confirm_name="").status_code == 400
        assert self.go(client, c, made["user_id"], confirm_name="Other Club").status_code == 400
        assert client.get("/api/coach/admins", headers=c["owner"]).json()["you_are_owner"] is True
        assert self.go(client, c, made["user_id"], confirm_name="  nashville   dogs ").status_code == 200

    def test_it_can_only_go_to_an_administrator_of_this_program(self, client):
        c = club(client)
        coach = api_module._store.create_user(c["org"], "coach", "Sam")
        assert self.go(client, c, coach["id"]).status_code == 404
        other = club(client, name="Other Club")
        assert self.go(client, c, other["owner_id"]).status_code == 404
        assert self.go(client, c, c["owner_id"]).status_code == 400

    def test_while_email_is_on_hold_nothing_is_sent(self, client, rec):
        c = club(client, release=False)
        _, made = admin_headers(client, c)
        self.go(client, c, made["user_id"])
        assert rec.sent == []

    def test_the_program_is_never_left_without_an_owner(self, client):
        c = club(client)
        h, made = admin_headers(client, c)
        self.go(client, c, made["user_id"], step_down=True)
        assert admins.owner_id(db(), c["org"]) == made["user_id"]

    def test_messages_from_the_program_name_the_owner_not_whoever_has_the_lowest_id(self, client):
        c = club(client)
        h, made = admin_headers(client, c)
        self.go(client, c, made["user_id"])
        s = api_module._store
        athlete = s.create_user(c["org"], "athlete", "Ryder", birth_year=2013)
        assert s._recognising_coach(athlete["id"], c["org"])[1] == "Dana Park"


class TestWhatSitsBehindIt:
    def test_the_owner_is_stored_as_a_column(self, client):
        club(client)
        assert "owner_user_id" in [r[1] for r in db().execute("PRAGMA table_info(organizations)")]
