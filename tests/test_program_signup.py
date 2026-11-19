"""Starting a program starts with verifying the director's email: nothing exists until the link is opened and a password chosen."""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import invites, mailer, signup, staff_mail
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store

EMAIL = "matt@maddoglacrosse.com"
GOOD = "a-good-pass-phrase-2026"
FORM = {"name": "Nashville Dogs", "sport": "lacrosse", "director_name": "Matt Kallberg", "email": EMAIL, "accept_terms": True}


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
    monkeypatch.setattr(api_module, "REQUIRE_VERIFIED_SIGNUP", True)
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def db():
    return api_module._store.conn


def token_in(mail):
    m = re.search(r"index\.html\?verify=([A-Za-z0-9_\-]+)", mail["text"])
    assert m, mail["text"]
    return m.group(1)


def start(client, **over):
    return client.post("/api/orgs/start", json={**FORM, **over})


class TestStartingSendsAnEmailAndCreatesNothing:
    def test_the_form_sends_one_email_with_a_verify_link(self, client, rec):
        res = start(client)
        assert res.status_code == 200 and res.json()["ok"] is True
        assert len(rec.sent) == 1 and rec.sent[0]["to"] == EMAIL
        assert "Verify" in rec.sent[0]["subject"] and "Nashville Dogs" in rec.sent[0]["subject"]
        assert token_in(rec.sent[0])

    def test_the_link_is_a_real_hyperlink_with_a_verify_email_button(self, client, rec):
        start(client)
        html = rec.sent[0]["html"]
        assert re.search(r'<a href="https://app\.0ffdays\.com/app/index\.html\?verify=[^"]+"[^>]*>Verify email</a>', html)

    def test_no_program_and_no_director_exist_yet(self, client, rec):
        start(client)
        assert db().execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 0
        assert db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0

    def test_only_a_hash_of_the_link_is_kept(self, client, rec):
        start(client)
        tok = token_in(rec.sent[0])
        stored = db().execute("SELECT token_hash FROM program_signups").fetchone()[0]
        assert tok not in stored and len(stored) == 64

    def test_the_terms_are_required(self, client, rec):
        res = start(client, accept_terms=False)
        assert res.status_code == 400 and "terms" in res.json()["detail"] and rec.sent == []

    @pytest.mark.parametrize("bad", ["", "nope", "a@b", "a b@c.com", "@x.com"])
    def test_a_bad_address_is_refused_with_a_reason(self, client, rec, bad):
        res = start(client, email=bad)
        assert res.status_code in (400, 422) and rec.sent == []

    def test_an_unknown_sport_is_refused(self, client, rec):
        assert start(client, sport="quidditch").status_code == 400

    def test_a_blank_name_is_refused(self, client, rec):
        assert start(client, name="   ").status_code == 400 and rec.sent == []

    def test_a_server_that_cannot_send_says_so_and_holds_nothing(self, client, rec, monkeypatch):
        monkeypatch.setattr(staff_mail, "mail_available", lambda: False)
        res = start(client)
        assert res.status_code == 503 and "Email is not switched on" in res.json()["detail"]
        assert db().execute("SELECT COUNT(*) FROM program_signups").fetchone()[0] == 0


class TestOpeningTheLink:
    def test_peeking_says_which_program_and_address_without_using_the_link(self, client, rec):
        start(client)
        tok = token_in(rec.sent[0])
        seen = client.post("/api/orgs/verify-peek", json={"token": tok}).json()
        assert seen == {"org_name": "Nashville Dogs", "email": EMAIL, "director_name": "Matt Kallberg"}
        assert client.post("/api/orgs/verify-peek", json={"token": tok}).status_code == 200

    def test_choosing_a_password_creates_the_program_the_director_and_the_login(self, client, rec):
        start(client)
        res = client.post("/api/orgs/verify", json={"token": token_in(rec.sent[0]), "password": GOOD})
        assert res.status_code == 201
        body = res.json()
        assert body["role"] == "director" and body["email"] == EMAIL and body["token"]
        org = db().execute("SELECT name, sport, terms_accepted_at FROM organizations").fetchone()
        assert (org["name"], org["sport"]) == ("Nashville Dogs", "lacrosse") and org["terms_accepted_at"]
        # the address is confirmed, the login works, and the session works
        cred = db().execute("SELECT email, email_verified_at FROM credentials").fetchone()
        assert cred["email"] == EMAIL and cred["email_verified_at"]
        me = client.get("/api/me", headers={"Authorization": f"Bearer {body['token']}"}).json()
        assert me["role"] == "director" and me["display_name"] == "Matt Kallberg"
        login = client.post("/api/login/password", json={"email": EMAIL, "password": GOOD})
        assert login.status_code == 200 and login.json()["role"] == "director"

    def test_the_directors_contact_email_is_already_filled_in(self, client, rec):
        start(client)
        body = client.post("/api/orgs/verify", json={"token": token_in(rec.sent[0]), "password": GOOD}).json()
        contact = client.get("/api/me/contact", headers={"Authorization": f"Bearer {body['token']}"}).json()
        assert contact["email"] == EMAIL and contact["complete"] is False       # only the mobile is left

    def test_the_link_works_once(self, client, rec):
        start(client)
        tok = token_in(rec.sent[0])
        assert client.post("/api/orgs/verify", json={"token": tok, "password": GOOD}).status_code == 201
        again = client.post("/api/orgs/verify", json={"token": tok, "password": GOOD})
        assert again.status_code == 401 and "expired or was already used" in again.json()["detail"]
        assert db().execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 1

    def test_a_weak_password_does_not_spend_the_link(self, client, rec):
        start(client)
        tok = token_in(rec.sent[0])
        weak = client.post("/api/orgs/verify", json={"token": tok, "password": "short"})
        assert weak.status_code == 400
        assert db().execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 0
        assert client.post("/api/orgs/verify", json={"token": tok, "password": GOOD}).status_code == 201

    def test_an_expired_link_creates_nothing(self, client, rec):
        start(client)
        db().execute("UPDATE program_signups SET expires_at = ?", ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),))
        db().commit()
        tok = token_in(rec.sent[0])
        assert client.post("/api/orgs/verify-peek", json={"token": tok}).status_code == 401
        assert client.post("/api/orgs/verify", json={"token": tok, "password": GOOD}).status_code == 401
        assert db().execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 0

    def test_a_made_up_link_is_refused(self, client, rec):
        assert client.post("/api/orgs/verify", json={"token": "nonsense", "password": GOOD}).status_code == 401

    def test_the_old_code_is_not_the_way_in_any_more(self, client, rec):
        """The direct route is closed on a server that can send mail, so nobody skips the email."""
        res = client.post("/api/orgs", json={"name": "Sneaky", "sport": "lacrosse", "director_name": "Eve", "accept_terms": True})
        assert res.status_code == 403
        assert db().execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 0

    def test_the_direct_route_still_works_where_there_is_no_mail(self, client, rec, monkeypatch):
        monkeypatch.setattr(staff_mail, "mail_available", lambda: False)
        res = client.post("/api/orgs", json={"name": "Dev", "sport": "lacrosse", "director_name": "Dev", "accept_terms": True})
        assert res.status_code == 201


class TestAddressesAndLimits:
    def test_the_reply_is_the_same_for_an_address_that_already_has_a_login(self, client, rec):
        start(client)
        client.post("/api/orgs/verify", json={"token": token_in(rec.sent[0]), "password": GOOD})
        rec.sent.clear()
        again = start(client, name="Another Club")
        fresh = start(client, email="someone.new@example.com")
        assert again.status_code == fresh.status_code == 200
        assert again.json()["message"] == fresh.json()["message"]
        assert [m["to"] for m in rec.sent] == ["someone.new@example.com"]        # no email to the existing director
        assert db().execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 1

    def test_the_address_is_matched_whatever_the_case(self, client, rec):
        start(client)
        client.post("/api/orgs/verify", json={"token": token_in(rec.sent[0]), "password": GOOD})
        rec.sent.clear()
        start(client, email=EMAIL.upper())
        assert rec.sent == []

    def test_a_coach_the_director_added_cannot_start_a_program_with_that_address(self, client, rec):
        start(client)
        made = client.post("/api/orgs/verify", json={"token": token_in(rec.sent[0]), "password": GOOD}).json()
        h = {"Authorization": f"Bearer {made['token']}"}
        team = client.post("/api/teams", json={"name": "2031 Red"}, headers=h).json()["id"]
        client.post("/api/coach/staff", headers=h, json={"display_name": "Joel", "email": "joel@example.com", "team_ids": [team]})
        rec.sent.clear()
        start(client, email="joel@example.com")
        assert rec.sent == []

    def test_asking_again_retires_the_earlier_link(self, client, rec):
        start(client)
        first = token_in(rec.sent[0])
        start(client)
        second = token_in(rec.sent[1])
        assert first != second
        assert client.post("/api/orgs/verify", json={"token": first, "password": GOOD}).status_code == 401
        assert client.post("/api/orgs/verify", json={"token": second, "password": GOOD}).status_code == 201

    def test_a_few_a_day_per_address(self, client, rec, monkeypatch):
        # the per-source throttle is its own protection; lift it to see the per-address one
        monkeypatch.setattr(api_module.throttle, "check", lambda *a, **k: None)
        for _ in range(signup.DAILY_LIMIT + 3):
            start(client)
        assert len(rec.sent) == signup.DAILY_LIMIT

    def test_resend_sends_a_fresh_link_for_a_waiting_signup_and_nothing_for_anyone_else(self, client, rec):
        start(client)
        old = token_in(rec.sent[0])
        res = client.post("/api/orgs/resend-verification", json={"email": EMAIL})
        assert res.status_code == 200 and len(rec.sent) == 2
        assert client.post("/api/orgs/verify", json={"token": old, "password": GOOD}).status_code == 401
        other = client.post("/api/orgs/resend-verification", json={"email": "nobody@example.com"})
        assert other.status_code == 200 and other.json()["message"] == res.json()["message"] and len(rec.sent) == 2

    def test_a_signup_nobody_finished_is_forgotten_after_a_week(self, client, rec):
        start(client, email="old@example.com")
        db().execute("UPDATE program_signups SET created_at = ?", ((datetime.now(timezone.utc) - timedelta(days=9)).isoformat(),))
        db().commit()
        start(client)
        assert db().execute("SELECT COUNT(*) FROM program_signups WHERE email = 'old@example.com'").fetchone()[0] == 0

    def test_the_sender_confirmation_and_forgot_password_still_work_for_the_new_director(self, client, rec):
        start(client)
        client.post("/api/orgs/verify", json={"token": token_in(rec.sent[0]), "password": GOOD})
        rec.sent.clear()
        client.post("/api/login/forgot", json={"email": EMAIL})
        assert len(rec.sent) == 1 and "reset" in rec.sent[0]["subject"].lower()


class TestTheEmailReads:
    def test_it_says_what_to_do_and_follows_the_copy_rules(self, client, rec):
        start(client)
        text = rec.sent[0]["text"]
        assert "Verify" in text and "choose a password" in text and "teams, coaches and rosters" in text
        assert " - " not in text and "\u2014" not in text and "\u2013" not in text
        assert not re.search(r"\b(he|she)\b", text, re.I)


class TestThePage:
    from pathlib import Path
    HTML = (Path(api_module.__file__).parent / "web" / "static" / "index.html").read_text(encoding="utf-8")

    def test_the_program_form_asks_for_the_email_and_starts_by_email(self):
        assert 'id="org-email"' in self.HTML and "/api/orgs/start" in self.HTML
        assert "api('/api/orgs', {" not in self.HTML

    def test_the_verify_link_shows_a_password_step_then_signs_in(self):
        for needle in ("verifyLink", "/api/orgs/verify-peek", "/api/orgs/verify'", 'id="verify-card"', "Verify email"):
            assert needle in self.HTML, needle

    def test_athletes_parents_and_coaches_get_only_their_sign_in(self):
        """The front page for athletes, parents and coaches is an email, a password and Forgot your password: no codes, no invite
        or claim boxes, no create a login. A link from an email (invite, sign-in, reset) still opens the right part."""
        for role, nxt in (("athlete", "parent"), ("parent", "coach")):
            panel = self.HTML.split(f'id="panel-{role}"', 1)[1].split(f'id="panel-{nxt}"', 1)[0]
            assert "Create my login" not in panel and "Make my login" not in panel and "First time" not in panel
        coach = self.HTML.split('id="panel-coach"', 1)[1].split('id="panel-director"', 1)[0]
        assert "pw-forgot" in coach and "coach-token" not in coach and "Use your code" not in coach
        assert 'class="card hidden" id="parent-card"' in self.HTML           # the invite card shows only from the invite link
        assert "$('parent-card').classList.remove('hidden');\n  $('invite').value" in self.HTML.replace("\r\n", "\n")
        assert 'class="role-btn"' in self.HTML and self.HTML.count("<span>Sign in</span>") == 3

    def test_the_forgot_password_card_is_still_there_for_everyone(self):
        assert self.HTML.count("Forgot your password?") >= 3 and "/api/login/forgot" in self.HTML

    def test_nothing_on_the_page_offers_to_make_a_login_by_another_way(self):
        """The athlete and parent cards are built by script, so check the whole page, not just the static panels."""
        html = self.HTML.replace("\r\n", "\n")
        for phrase in ("Create my login</summary>", "Create my login</b>", "Make my login</summary>", "First time? "):
            assert phrase not in html, phrase
        assert 'for="coach-token"' not in html          # the coach has no paste your code box

    def test_the_whole_page_has_no_code_box_for_athletes_parents_or_coaches(self):
        html = self.HTML.replace("\r\n", "\n")
        assert "The code from your link" not in html and 'for="invite"' in html.split('id="parent-card"', 1)[1].split('id="family-card"', 1)[0]


class TestALinkIsSpentByItself:
    def test_the_link_is_marked_used_even_if_the_login_it_made_is_later_gone(self, client, rec):
        """The 'already has a login' check would also stop a second use; this proves the link itself is spent."""
        start(client)
        tok = token_in(rec.sent[0])
        made = client.post("/api/orgs/verify", json={"token": tok, "password": GOOD}).json()
        db().execute("DELETE FROM credentials WHERE user_id = ?", (made["user_id"],))
        db().execute("UPDATE users SET email = NULL, active = 0 WHERE id = ?", (made["user_id"],))
        db().commit()
        assert client.post("/api/orgs/verify", json={"token": tok, "password": GOOD}).status_code == 401
        assert db().execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 1
