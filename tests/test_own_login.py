"""Everyone can make their own email and password login, so nobody has to send a new link.

* A coach or director creates one from the front page with the address the director added them with.
* A parent creates one with an address the program gave us (never the one typed at sign-up).
* An athlete creates one once signed in by their parent's link, and the parent can switch it off.
* The reply never says who has an account. Links are single use, last an hour, and a new one kills the old.
* Nothing is emailed to a family while the program's email hold is on.
"""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import create_login, invites, mailer, parent_signin, staff_mail
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store

PARENT = "robert.langdon@example.com"
COACH = "joel@example.com"
GOOD = "a-good-pass-phrase-2026"


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
    import offdays.guardians as guardians_mod
    for mod in (invites, mailer, guardians_mod, staff_mail):
        if hasattr(mod, "CONFIG"):
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
    team = client.post("/api/teams", json={"name": "2031 Red"}, headers=d).json()["id"]
    coach = client.post("/api/coach/staff", headers=d, json={"display_name": "Joel White", "email": COACH,
                                                             "team_ids": [team]}).json()
    return {"d": d, "team": team, "coach": coach, "dir_token": made["director"]["token"], "org_id": made["org_id"]}


def family(client, c):
    body = "First Name,Last Name,Birth Year,Parent Email\nDillon,Langdon,2013," + PARENT + "\n"
    out = client.post("/api/coach/roster/import", headers=c["d"], json={"content": body, "team_id": c["team"]}).json()
    code = out["guardian_invites"][0]["code"]
    red = client.post("/api/guardians/redeem", json={"code": code, "display_name": "Robert Langdon",
                                                      "email": PARENT, "phone": "615-555-0101"}).json()
    kids = client.get("/api/coach/team-ranking", headers=c["d"], params={"team_id": c["team"]}).json()["rows"]
    return {"parent": red["token"], "kid": kids[0]["athlete_id"]}


def link_token(text):
    return re.search(r"create=([A-Za-z0-9_-]+)", text).group(1)


def mails_to(rec, address):
    return [m for m in rec.sent if m["to"] == address and "finish creating" in m["subject"]]


def start(client, address):
    return client.post("/api/login/create-start", json={"email": address})


def finish(client, token, password=GOOD):
    return client.post("/api/login/create-finish", json={"token": token, "password": password})


def sign_in(client, email, password=GOOD):
    return client.post("/api/login/password", json={"email": email, "password": password})


class TestACoachMakesTheirOwnLogin:
    def test_the_full_path_from_the_front_page(self, client, rec):
        c = club(client)
        rec.sent.clear()
        assert start(client, COACH).status_code == 200
        m = mails_to(rec, COACH)
        assert len(m) == 1 and "Choose my password" in m[0]["html"]
        assert "https://app.0ffdays.com/app/index.html?create=" in m[0]["text"]
        res = finish(client, link_token(m[0]["text"]))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["role"] == "coach" and body["display_name"] == "Joel White" and body["email"] == COACH
        assert client.get("/api/me", headers=bearer(body["token"])).json()["role"] == "coach"
        again = sign_in(client, COACH)
        assert again.status_code == 200 and again.json()["role"] == "coach"
        assert sign_in(client, COACH, "not-the-password-1234").status_code == 401

    def test_the_address_counts_as_confirmed_so_forgot_password_works_straight_away(self, client, rec):
        club(client)
        start(client, COACH)
        finish(client, link_token(mails_to(rec, COACH)[0]["text"]))
        row = db().execute("SELECT email_verified_at FROM credentials").fetchone()
        assert row["email_verified_at"]
        rec.sent.clear()
        client.post("/api/login/forgot", json={"email": COACH})
        assert any("reset your 0FFDAYS password" in m["subject"] for m in rec.sent)

    def test_the_directors_own_login_works_the_same_way(self, client, rec):
        c = club(client)
        db().execute("UPDATE users SET email = ? WHERE role = 'director'", ("matt@example.com",))
        db().commit()
        rec.sent.clear()
        start(client, "matt@example.com")
        res = finish(client, link_token(mails_to(rec, "matt@example.com")[0]["text"]))
        assert res.json()["role"] == "director"
        assert client.get("/api/coach/staff", headers=bearer(res.json()["token"])).status_code == 200

    def test_it_works_while_email_is_on_hold_because_it_is_mail_to_one_staff_member_who_asked(self, client, rec):
        club(client, release=False)
        rec.sent.clear()
        start(client, COACH)
        assert len(mails_to(rec, COACH)) == 1

    def test_the_link_works_once(self, client, rec):
        club(client)
        start(client, COACH)
        tok = link_token(mails_to(rec, COACH)[0]["text"])
        assert finish(client, tok).status_code == 200
        assert finish(client, tok, "another-good-pass-2026").status_code == 401

    def test_a_weak_password_is_refused_and_the_link_is_not_spent(self, client, rec):
        club(client)
        start(client, COACH)
        tok = link_token(mails_to(rec, COACH)[0]["text"])
        assert finish(client, tok, "short").status_code == 400
        assert finish(client, tok).status_code == 200

    def test_an_expired_link_does_nothing(self, client, rec):
        club(client)
        start(client, COACH)
        tok = link_token(mails_to(rec, COACH)[0]["text"])
        db().execute("UPDATE login_links SET expires_at = ?", ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),))
        db().commit()
        assert finish(client, tok).status_code == 401
        assert db().execute("SELECT COUNT(*) FROM credentials").fetchone()[0] == 0

    def test_asking_again_kills_the_earlier_link(self, client, rec):
        club(client)
        start(client, COACH)
        first = link_token(mails_to(rec, COACH)[0]["text"])
        start(client, COACH)
        second = link_token(mails_to(rec, COACH)[1]["text"])
        assert finish(client, first).status_code == 401
        assert finish(client, second).status_code == 200

    def test_only_a_few_links_an_hour(self, client, rec):
        club(client)
        for _ in range(6):
            start(client, COACH)
        assert len(mails_to(rec, COACH)) == create_login.HOURLY_LIMIT

    def test_someone_who_already_has_a_login_is_sent_nothing(self, client, rec):
        club(client)
        start(client, COACH)
        finish(client, link_token(mails_to(rec, COACH)[0]["text"]))
        rec.sent.clear()
        start(client, COACH)
        assert mails_to(rec, COACH) == []

    def test_a_removed_coach_gets_nothing(self, client, rec):
        c = club(client)
        client.post(f"/api/coach/staff/{c['coach']['user_id']}/remove", headers=c["d"], json={})
        rec.sent.clear()
        start(client, COACH)
        assert mails_to(rec, COACH) == []


class TestTheAnswerNeverSaysWhoHasAnAccount:
    def test_the_same_reply_for_known_unknown_and_nonsense(self, client, rec):
        club(client)
        replies = [start(client, a).json() for a in (COACH, "nobody@example.com", "not an email", "")]
        assert all(r == replies[0] for r in replies)
        assert all(r["ok"] for r in replies)

    def test_an_unknown_address_gets_no_email(self, client, rec):
        club(client)
        rec.sent.clear()
        start(client, "nobody@example.com")
        assert rec.sent == []

    def test_an_address_in_use_by_someone_else_is_not_handed_out(self, client, rec):
        club(client)
        start(client, COACH)
        finish(client, link_token(mails_to(rec, COACH)[0]["text"]))
        other = client.post("/api/coach/staff", headers=bearer(db().execute("SELECT 1").fetchone() and
                            client.post("/api/orgs", json={"name": "Other", "sport": "lacrosse", "accept_terms": True,
                                                           "director_name": "Dana"}).json()["director"]["token"]),
                            json={"display_name": "Imposter", "email": COACH.upper()}).json()
        rec.sent.clear()
        start(client, COACH)
        assert mails_to(rec, COACH) == []
        assert other["user_id"]


class TestAParentMakesTheirOwnLogin:
    def test_a_parent_with_a_roster_address_can(self, client, rec):
        c = club(client)
        p = family(client, c)
        rec.sent.clear()
        start(client, PARENT)
        m = mails_to(rec, PARENT)
        assert len(m) == 1 and "parent of Dillon" in m[0]["text"]
        res = finish(client, link_token(m[0]["text"]))
        assert res.status_code == 200 and res.json()["role"] == "guardian"
        mine = client.get("/api/guardians/me", headers=bearer(res.json()["token"]))
        assert mine.status_code == 200
        signed = sign_in(client, PARENT)
        assert signed.json()["role"] == "guardian"
        assert client.get("/api/guardians/me", headers=bearer(signed.json()["token"])).status_code == 200
        assert p["kid"]

    def test_an_address_typed_at_sign_up_is_not_trusted(self, client, rec):
        c = club(client)
        body = "First Name,Last Name,Birth Year,Parent Email\nDillon,Langdon,2013," + PARENT + "\n"
        out = client.post("/api/coach/roster/import", headers=c["d"], json={"content": body, "team_id": c["team"]}).json()
        client.post("/api/guardians/redeem", json={"code": out["guardian_invites"][0]["code"], "display_name": "Robert",
                                                    "email": "typo@example.com", "phone": "615-555-0101"})
        rec.sent.clear()
        start(client, "typo@example.com")
        assert rec.sent == []

    def test_nothing_goes_to_a_parent_while_email_is_on_hold(self, client, rec):
        c = club(client, release=False)
        body = "First Name,Last Name,Birth Year,Parent Email\nDillon,Langdon,2013," + PARENT + "\n"
        out = client.post("/api/coach/roster/import", headers=c["d"], json={"content": body, "team_id": c["team"]}).json()
        client.post("/api/guardians/redeem", json={"code": out["guardian_invites"][0]["code"], "display_name": "Robert",
                                                    "email": PARENT, "phone": "615-555-0101"})
        rec.sent.clear()
        start(client, PARENT)
        assert rec.sent == []

    def test_a_parent_who_forgot_can_reset_by_email(self, client, rec):
        c = club(client)
        family(client, c)
        start(client, PARENT)
        finish(client, link_token(mails_to(rec, PARENT)[0]["text"]))
        rec.sent.clear()
        client.post("/api/login/forgot", json={"email": PARENT})
        resets = [m for m in rec.sent if "reset your 0FFDAYS password" in m["subject"]]
        assert len(resets) == 1
        tok = re.search(r"reset=([A-Za-z0-9_-]+)", resets[0]["text"]).group(1)
        res = client.post("/api/login/reset-link", json={"token": tok, "new_password": "brand-new-pass-2026"})
        assert res.status_code == 200 and res.json()["role"] == "guardian"
        assert sign_in(client, PARENT, "brand-new-pass-2026").status_code == 200

    def test_a_removed_parents_login_stops_working(self, client, rec):
        c = club(client)
        family(client, c)
        start(client, PARENT)
        tok = finish(client, link_token(mails_to(rec, PARENT)[0]["text"])).json()["token"]
        db().execute("UPDATE users SET active = 0 WHERE role = 'guardian'")
        db().commit()
        assert client.get("/api/guardians/me", headers=bearer(tok)).status_code in (401, 403)
        assert sign_in(client, PARENT).status_code == 401


class TestAnAthleteMakesTheirOwnLogin:
    def athlete(self, client, c):
        p = family(client, c)
        client.post("/api/guardians/consent", headers=bearer(p["parent"]),
                    json={"athlete_id": p["kid"], "scope": "participation", "granted": True})
        link = client.post(f"/api/guardians/athlete-link/{p['kid']}", headers=bearer(p["parent"])).json()["link"]
        return {**p, "token": re.search(r"code=([A-Za-z0-9]+)", link).group(1)}

    def test_a_signed_in_athlete_chooses_an_email_and_then_signs_in_with_it(self, client, rec):
        c = club(client)
        a = self.athlete(client, c)
        rec.sent.clear()
        res = client.post("/api/me/make-login", headers=bearer(a["token"]), json={"email": "dillon@example.com"})
        assert res.status_code == 200 and res.json()["sent"] is True
        m = mails_to(rec, "dillon@example.com")
        assert len(m) == 1 and "for Dillon" in m[0]["text"]
        out = finish(client, link_token(m[0]["text"]))
        assert out.json()["role"] == "athlete"
        signed = sign_in(client, "dillon@example.com")
        assert signed.status_code == 200 and signed.json()["role"] == "athlete"
        assert client.get("/api/me", headers=bearer(signed.json()["token"])).json()["role"] == "athlete"
        assert client.get("/api/me/login", headers=bearer(a["token"])).json() == {
            "has_login": True, "email": "dillon@example.com", "mail": True}

    def test_a_coach_cannot_start_one_for_a_child(self, client, rec):
        c = club(client)
        a = self.athlete(client, c)
        res = client.post("/api/me/make-login", headers=c["d"], json={"email": "kid@example.com"})
        assert res.status_code in (200, 400)
        assert db().execute("SELECT COUNT(*) FROM login_links WHERE user_id = ?", (a["kid"],)).fetchone()[0] == 0

    def test_nothing_is_sent_while_email_is_on_hold(self, client, rec):
        c = club(client, release=False)
        a = self.athlete(client, c)
        rec.sent.clear()
        res = client.post("/api/me/make-login", headers=bearer(a["token"]), json={"email": "dillon@example.com"})
        assert res.status_code == 400 and "has not started sending email" in res.json()["detail"]
        assert rec.sent == []

    def test_the_parents_own_address_cannot_be_reused_for_the_child(self, client, rec):
        c = club(client)
        a = self.athlete(client, c)
        start(client, PARENT)
        finish(client, link_token(mails_to(rec, PARENT)[0]["text"]))
        res = client.post("/api/me/make-login", headers=bearer(a["token"]), json={"email": PARENT})
        assert res.status_code == 400 and "cannot be used for sign-in" in res.json()["detail"]

    def test_a_bad_address_is_refused(self, client, rec):
        c = club(client)
        a = self.athlete(client, c)
        assert client.post("/api/me/make-login", headers=bearer(a["token"]), json={"email": "nope"}).status_code == 400

    def test_a_parent_can_switch_the_childs_login_off_and_the_link_still_works(self, client, rec):
        c = club(client)
        a = self.athlete(client, c)
        client.post("/api/me/make-login", headers=bearer(a["token"]), json={"email": "dillon@example.com"})
        out = finish(client, link_token(mails_to(rec, "dillon@example.com")[0]["text"]))
        assert client.get(f"/api/guardians/athlete-login/{a['kid']}", headers=bearer(a["parent"])).json()["has_login"] is True
        res = client.delete(f"/api/guardians/athlete-login/{a['kid']}", headers=bearer(a["parent"]))
        assert res.json() == {"removed": True}
        assert sign_in(client, "dillon@example.com").status_code == 401
        assert client.get("/api/me", headers=bearer(out.json()["token"])).status_code == 401      # the open session ends
        assert client.get("/api/me", headers=bearer(a["token"])).status_code == 200                 # the link still works
        assert db().execute("SELECT email FROM users WHERE id = ?", (a["kid"],)).fetchone()["email"] in (None, "")

    def test_another_parent_cannot_switch_it_off(self, client, rec):
        c = club(client)
        a = self.athlete(client, c)
        body = "First Name,Last Name,Birth Year,Parent Email\nBen,Amden,2013,jess@example.com\n"
        out = client.post("/api/coach/roster/import", headers=c["d"], json={"content": body, "team_id": c["team"]}).json()
        other = client.post("/api/guardians/redeem", json={"code": out["guardian_invites"][-1]["code"], "display_name": "Jess",
                                                            "email": "jess@example.com", "phone": "615-555-0102"}).json()
        res = client.delete(f"/api/guardians/athlete-login/{a['kid']}", headers=bearer(other["token"]))
        assert res.status_code in (400, 403, 404)
        assert client.get(f"/api/guardians/athlete-login/{a['kid']}", headers=bearer(a['parent'])).json()['has_login'] is False
        client.post('/api/me/make-login', headers=bearer(a['token']), json={'email': 'dillon@example.com'})
        finish(client, link_token(mails_to(rec, 'dillon@example.com')[0]['text']))
        client.delete(f"/api/guardians/athlete-login/{a['kid']}", headers=bearer(other['token']))
        assert sign_in(client, 'dillon@example.com').status_code == 200

    def test_an_athlete_login_stops_when_the_season_ends(self, client, rec):
        c = club(client)
        a = self.athlete(client, c)
        client.post("/api/me/make-login", headers=bearer(a["token"]), json={"email": "dillon@example.com"})
        finish(client, link_token(mails_to(rec, "dillon@example.com")[0]["text"]))
        db().execute("UPDATE organizations SET season_ends_on = '2020-01-01'")
        db().commit()
        signed = sign_in(client, "dillon@example.com")
        assert client.get("/api/me", headers=bearer(signed.json()["token"])).status_code in (401, 403)


class TestNothingIsStoredInTheClear:
    def test_only_hashes_of_links_and_passwords(self, client, rec):
        club(client)
        start(client, COACH)
        tok = link_token(mails_to(rec, COACH)[0]["text"])
        finish(client, tok)
        dump = " ".join(str(tuple(r)) for t in ("login_links", "credentials") for r in db().execute(f"SELECT * FROM {t}"))
        assert tok not in dump and GOOD not in dump
