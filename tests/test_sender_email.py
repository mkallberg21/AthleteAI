"""A coach or director confirms the email their messages to parents are sent on behalf of.

0FFDAYS sends from its own verified domain (a message "from" a Gmail or Outlook address would be rejected by the receiving
server). What makes it the sender's message is their name on the From line and replies to their own inbox, in whatever
email platform they use. That needs one thing from them: an address they have proved is theirs, by clicking a link
emailed to it. An unconfirmed address is never used as a reply address.
"""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import invites, mailer, sender_email
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store


class Recorder:
    def __init__(self):
        self.sent = []

    def send(self, to_email, subject, html, text, headers):
        self.sent.append({"to": to_email, "subject": subject, "text": text, "html": html, "headers": dict(headers)})
        return mailer.SendResult(ok=True)


@pytest.fixture
def rec(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(mailer, "default_transport", lambda: r)
    return r


@pytest.fixture
def client(tmp_path, monkeypatch, rec):
    patched = replace(CONFIG, smtp_host="smtp.test", app_base_url="https://app.0ffdays.com",
                      smtp_from="0FFDAYS <no-reply@mail.0ffdays.com>")
    for mod in (invites, mailer, sender_email):
        if hasattr(mod, "CONFIG"):
            monkeypatch.setattr(mod, "CONFIG", patched)
    monkeypatch.setattr(api_module, "CONFIG", patched)
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def db():
    return api_module._store.conn


def program(client, name="Nashville Dogs", director="Matt Kallberg"):
    made = client.post("/api/orgs", json={"name": name, "sport": "lacrosse", "accept_terms": True,
                                          "director_name": director}).json()
    h = {"Authorization": f"Bearer {made['director']['token']}"}
    uid = db().execute("SELECT id FROM users WHERE org_id = ? AND role = 'director'", (made["org_id"],)).fetchone()[0]
    return {"h": h, "uid": uid, "org_id": made["org_id"]}


def ask(client, p, email):
    return client.post("/api/me/sender-email", headers=p["h"], json={"email": email})


def token_from(rec, to):
    mail = [m for m in rec.sent if m["to"] == to][-1]
    return re.search(r"[?]sender=([A-Za-z0-9_-]+)", mail["text"]).group(1)


def confirm(client, token):
    return client.post("/api/login/sender-confirm", json={"token": token})


class TestAskingForTheLink:
    def test_a_link_is_emailed_to_that_address_only(self, client, rec):
        p = program(client)
        res = ask(client, p, "Matt@NashvilleDogs.example")
        assert res.status_code == 200, res.text
        assert [m["to"] for m in rec.sent] == ["matt@nashvilledogs.example"]
        assert res.json() == {"email": "matt@nashvilledogs.example", "confirmed": False, "pending": True,
                              "sent": True, "mail": True}

    def test_the_email_explains_what_confirming_does_and_does_not_do(self, client, rec):
        p = program(client)
        ask(client, p, "matt@x.example")
        text = rec.sent[0]["text"]
        assert "sent on your behalf" in text and "the reply comes to this inbox" in text
        assert "never reads your email or sends from your account" in text
        assert "?sender=" in text and rec.sent[0]["subject"].startswith("Nashville Dogs: confirm your email")

    @pytest.mark.parametrize("bad", ["", "nope", "a b@x.example", "a@x.example, b@x.example", "<a@x.example>",
                                     "a@x.example\r\nBcc: z@x.example", "a@x.example;b@x.example"])
    def test_anything_that_is_not_one_address_is_refused(self, client, rec, bad):
        p = program(client)
        assert ask(client, p, bad).status_code in (400, 422)
        assert rec.sent == []

    def test_nothing_can_be_sent_without_a_mail_provider(self, client, rec, monkeypatch):
        p = program(client)
        monkeypatch.setattr(mailer, "provider_ready", lambda: False)
        assert ask(client, p, "matt@x.example").status_code == 400
        assert client.get("/api/me/sender-email", headers=p["h"]).json()["mail"] is False

    def test_only_a_few_an_hour(self, client, rec):
        p = program(client)
        for _ in range(sender_email.HOURLY_LIMIT):
            assert ask(client, p, "matt@x.example").status_code == 200
        assert ask(client, p, "matt@x.example").status_code == 400
        assert len(rec.sent) == sender_email.HOURLY_LIMIT

    def test_the_link_is_stored_only_as_a_hash(self, client, rec):
        p = program(client)
        ask(client, p, "matt@x.example")
        token = token_from(rec, "matt@x.example")
        row = db().execute("SELECT * FROM sender_emails").fetchone()
        assert token not in "".join(str(v) for v in tuple(row))
        assert row["token_hash"] and len(row["token_hash"]) == 64

    def test_a_parent_a_stranger_and_an_athlete_cannot_use_it(self, client, rec):
        for call in (lambda h: client.get("/api/me/sender-email", headers=h),
                     lambda h: client.post("/api/me/sender-email", headers=h, json={"email": "a@x.example"})):
            assert call({}).status_code in (401, 403)
            assert call({"Authorization": "Bearer nope"}).status_code in (401, 403)


class TestClickingIt:
    def test_nothing_is_used_until_it_is_clicked(self, client, rec):
        p = program(client)
        ask(client, p, "matt@x.example")
        assert invites.staff_reply_to(db(), p["uid"]) == ""
        pre = client.post("/api/coach/families/invite-preview", headers=p["h"], json={"intro": ""}).json()
        assert pre["reply_to"] == "" and "Replies to this address are not read" in pre["text"]

    def test_clicking_it_makes_replies_go_there(self, client, rec):
        p = program(client)
        ask(client, p, "matt@x.example")
        res = confirm(client, token_from(rec, "matt@x.example"))
        assert res.status_code == 200 and res.json() == {"ok": True, "email": "matt@x.example"}
        assert client.get("/api/me/sender-email", headers=p["h"]).json()["confirmed"] is True
        pre = client.post("/api/coach/families/invite-preview", headers=p["h"], json={"intro": ""}).json()
        assert pre["reply_to"] == "matt@x.example" and "Just reply to this email" in pre["text"]

    def test_the_link_works_once(self, client, rec):
        p = program(client)
        ask(client, p, "matt@x.example")
        t = token_from(rec, "matt@x.example")
        assert confirm(client, t).status_code == 200
        assert confirm(client, t).status_code == 401

    def test_a_wrong_or_empty_link_does_nothing(self, client, rec):
        p = program(client)
        ask(client, p, "matt@x.example")
        for junk in ("", "nope", "x" * 300):
            assert confirm(client, junk).status_code in (401, 422)
        assert client.get("/api/me/sender-email", headers=p["h"]).json()["confirmed"] is False

    def test_an_old_link_is_dead(self, client, rec):
        p = program(client)
        ask(client, p, "matt@x.example")
        old = token_from(rec, "matt@x.example")
        ask(client, p, "matt@x.example")
        new = token_from(rec, "matt@x.example")
        assert old != new and confirm(client, old).status_code == 401 and confirm(client, new).status_code == 200

    def test_an_expired_link_is_dead(self, client, rec):
        p = program(client)
        ask(client, p, "matt@x.example")
        t = token_from(rec, "matt@x.example")
        db().execute("UPDATE sender_emails SET expires_at = ?", ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),))
        db().commit()
        assert confirm(client, t).status_code == 401

    def test_changing_the_address_unconfirms_it_and_kills_the_old_link(self, client, rec):
        p = program(client)
        ask(client, p, "old@x.example")
        old = token_from(rec, "old@x.example")
        ask(client, p, "new@x.example")
        assert confirm(client, old).status_code == 401
        assert invites.staff_reply_to(db(), p["uid"]) == ""
        assert confirm(client, token_from(rec, "new@x.example")).status_code == 200
        assert invites.staff_reply_to(db(), p["uid"]) == "new@x.example"

    def test_a_new_address_is_not_trusted_just_because_the_old_one_was(self, client, rec):
        """Confirm one address, then ask for another: the new one has proved nothing yet."""
        p = program(client)
        ask(client, p, "old@x.example")
        confirm(client, token_from(rec, "old@x.example"))
        ask(client, p, "new@x.example")
        st = client.get("/api/me/sender-email", headers=p["h"]).json()
        assert st["confirmed"] is False and st["email"] == "new@x.example" and st["pending"] is True
        assert invites.staff_reply_to(db(), p["uid"]) == ""

    def test_asking_again_for_a_confirmed_address_keeps_it_confirmed(self, client, rec):
        p = program(client)
        ask(client, p, "matt@x.example")
        confirm(client, token_from(rec, "matt@x.example"))
        ask(client, p, "matt@x.example")
        assert invites.staff_reply_to(db(), p["uid"]) == "matt@x.example"

    def test_two_programs_are_independent(self, client, rec):
        a, b = program(client), program(client, name="Mad Dog", director="Other")
        ask(client, a, "same@x.example")
        confirm(client, token_from(rec, "same@x.example"))
        assert invites.staff_reply_to(db(), a["uid"]) == "same@x.example"
        assert invites.staff_reply_to(db(), b["uid"]) == ""

    def test_an_address_confirmed_for_email_sign_in_counts_too(self, client, rec):
        p = program(client)
        db().execute("INSERT INTO credentials(user_id, email, pw_hash, email_verified_at, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?)", (p["uid"], "matt@x.example", "x", "2026-01-01T00:00:00+00:00", "2026", "2026"))
        db().commit()
        assert invites.staff_reply_to(db(), p["uid"]) == "matt@x.example"

    def test_an_unconfirmed_sign_in_address_does_not(self, client, rec):
        p = program(client)
        db().execute("INSERT INTO credentials(user_id, email, pw_hash, created_at, updated_at) VALUES (?,?,?,?,?)",
                     (p["uid"], "typo@x.example", "x", "2026", "2026"))
        db().commit()
        assert invites.staff_reply_to(db(), p["uid"]) == ""

    def test_an_address_on_the_account_but_never_confirmed_is_never_used(self, client, rec):
        p = program(client)
        db().execute("UPDATE users SET email = 'stranger@x.example' WHERE id = ?", (p["uid"],))
        db().commit()
        assert invites.staff_reply_to(db(), p["uid"]) == ""


class TestTheTestSend:
    def test_it_goes_to_the_confirmed_address_and_only_that(self, client, rec):
        p = program(client)
        ask(client, p, "matt@x.example")
        confirm(client, token_from(rec, "matt@x.example"))
        rec.sent.clear()
        res = client.post("/api/coach/families/invite-test", headers=p["h"], json={"intro": "hi"})
        assert res.status_code == 200 and [m["to"] for m in rec.sent] == ["matt@x.example"]

    def test_it_is_refused_before_confirming_and_says_why(self, client, rec):
        p = program(client)
        res = client.post("/api/coach/families/invite-test", headers=p["h"], json={"intro": ""})
        assert res.status_code == 409 and "Confirm your email first" in res.json()["detail"]
        assert rec.sent == []


class TestTheScreens:
    @staticmethod
    def page(name):
        from pathlib import Path
        return (Path(api_module.__file__).parent / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_link_lands_on_a_confirmation_page(self):
        html = self.page("index.html")
        assert "params.get('sender')" in html and "/api/login/sender-confirm" in html
        assert 'id="sender-card"' in html and "Your email is confirmed" in html
        assert "|| senderLink) history.replaceState" in html               # the secret leaves the address bar

    def test_the_message_box_walks_through_confirming(self):
        html = self.page("coach.html")
        for needle in ("/api/me/sender-email", 'id="msg-sender"', "msg-email-send", "msg-email-check", "I clicked it",
                       "Email me a confirmation link", "never reads your email or sends from your account"):
            assert needle in html, needle

    def test_sending_from_your_own_mail_lets_you_pick_your_service(self):
        html = self.page("coach.html")
        assert "a[href^=\"mailto:\"]" in html and "Which email do you use?" in html
        for needle in ("mail.google.com/mail/?view=cm", "outlook.live.com/mail/0/deeplink/compose",
                       "outlook.office.com/mail/deeplink/compose", "compose.mail.yahoo.com", "Remember my choice",
                       "The mail app on this computer", "MAIL_PREF", "name: 'Gmail'", "Outlook.com or Hotmail",
                       "Outlook for work or school", "Yahoo Mail"):
            assert needle in html, needle
