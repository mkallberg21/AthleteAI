"""Coaches and directors reset a forgotten password themselves, by email, unattended.

Nobody reads a mailbox and nobody forwards a code. A coach types their own email on
the sign-in page; the server emails that address a link that works once, for an hour,
and the coach chooses a new password. Rules these tests hold in place:

* an address must be CONFIRMED (a link sent to it, opened) before a reset link will
  ever be sent there, so a typo cannot hand someone else an account;
* the answer to "email me a link" is identical for a known, unknown, unconfirmed or
  deactivated address, so nobody can use it to learn who has an account;
* a link works once, expires, dies when a newer one is asked for or the address
  changes, and a weak password does not spend it;
* it is delivered at once and only to the person asking, and it never waits on or
  releases the parents' email hold;
* the abuse limits hold, and nothing secret is stored in the clear.
"""
from __future__ import annotations

import dataclasses
import json
import re
from datetime import datetime, timedelta, timezone

import pytest

import offdays.api as api_module
from offdays import mailer
from offdays.config import CONFIG
from tests.test_api import client, program  # noqa: F401  (fixtures)

EMAIL = "joel@nashvilledogs.example"
GOOD = "correct-horse-battery"
NEW = "a-brand-new-passphrase"


class Recorder:
    """Stands in for the mail provider: remembers what would have been sent."""

    def __init__(self):
        self.sent: list[dict] = []

    def send(self, to_email, subject, html, text, headers):
        self.sent.append({"to": to_email, "subject": subject, "html": html, "text": text,
                          "headers": dict(headers)})
        return mailer.SendResult(ok=True)

    def to(self, address):
        return [m for m in self.sent if m["to"] == address]


@pytest.fixture
def mail(monkeypatch):
    """The server HAS a mail provider. The parents' hold is left exactly as it ships: on."""
    patched = dataclasses.replace(CONFIG, smtp_host="smtp.test", app_base_url="https://app.0ffdays.com")
    monkeypatch.setattr(mailer, "CONFIG", patched)
    rec = Recorder()
    monkeypatch.setattr(mailer, "default_transport", lambda: rec)
    return rec


def _db():
    return api_module._store.conn


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _set(client, headers, email=EMAIL, password=GOOD, **extra):
    return client.put("/api/me/password", json={"email": email, "password": password, **extra}, headers=headers)


def _token_in(message, kind):
    m = re.search(rf"[?&]{kind}=([A-Za-z0-9_\-]+)", message["text"])
    assert m, f"no {kind} link in: {message['text']}"
    return m.group(1)


def _confirm_link(mail, address=EMAIL):
    return _token_in([m for m in mail.to(address) if "confirm" in m["text"].lower()][-1], "confirm")


def _reset_link(mail, address=EMAIL):
    return _token_in([m for m in mail.to(address) if "reset=" in m["text"]][-1], "reset")


def _confirmed(client, mail, headers, email=EMAIL):
    """A director with a password whose address has been confirmed."""
    assert _set(client, headers, email=email).status_code == 200
    token = _confirm_link(mail, email)
    assert client.post("/api/login/confirm", json={"token": token}).status_code == 200
    mail.sent.clear()


def _forgot(client, email=EMAIL):
    return client.post("/api/login/forgot", json={"email": email})


def _login(client, email=EMAIL, password=GOOD):
    return client.post("/api/login/password", json={"email": email, "password": password})


# --------------------------------------------------------------------------- confirm
class TestSettingAPasswordAsksYouToConfirmTheAddress:
    def test_a_link_goes_to_that_address(self, client, program, mail):
        res = _set(client, program["director"])
        assert res.status_code == 200, res.text
        assert res.json()["confirm_sent"] is True
        msgs = mail.to(EMAIL)
        assert len(msgs) == 1 and "confirm" in msgs[0]["subject"].lower()
        assert "?confirm=" in msgs[0]["text"]
        assert msgs[0]["text"].count("https://app.0ffdays.com/app/index.html") >= 1

    def test_with_email_working_no_recovery_code_is_handed_out(self, client, program, mail):
        assert _set(client, program["director"]).json().get("recovery_code") is None

    def test_with_no_email_service_the_recovery_code_is_still_given(self, client, program):
        res = _set(client, program["director"])
        assert res.json()["recovery_code"] and res.json()["confirm_sent"] is False

    def test_the_summary_says_whether_it_is_confirmed(self, client, program, mail):
        _set(client, program["director"])
        body = client.get("/api/me/password", headers=program["director"]).json()
        assert body["verified"] is False and body["mail"] is True
        client.post("/api/login/confirm", json={"token": _confirm_link(mail)})
        assert client.get("/api/me/password", headers=program["director"]).json()["verified"] is True

    def test_confirming_works_once(self, client, program, mail):
        _set(client, program["director"])
        token = _confirm_link(mail)
        assert client.post("/api/login/confirm", json={"token": token}).status_code == 200
        assert client.post("/api/login/confirm", json={"token": token}).status_code == 401

    def test_confirming_signs_nobody_in(self, client, program, mail):
        _set(client, program["director"])
        body = client.post("/api/login/confirm", json={"token": _confirm_link(mail)}).json()
        assert "token" not in body

    def test_a_made_up_link_is_refused(self, client, program, mail):
        assert client.post("/api/login/confirm", json={"token": "x" * 43}).status_code == 401

    def test_an_expired_link_is_refused(self, client, program, mail):
        _set(client, program["director"])
        token = _confirm_link(mail)
        _db().execute("UPDATE email_tokens SET expires_at = ?",
                      ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds"),))
        _db().commit()
        assert client.post("/api/login/confirm", json={"token": token}).status_code == 401

    def test_signing_in_with_the_password_never_waits_for_confirmation(self, client, program, mail):
        _set(client, program["director"])
        assert _login(client).status_code == 200

    def test_it_can_be_sent_again_from_settings(self, client, program, mail):
        _set(client, program["director"])
        first = _confirm_link(mail)
        res = client.post("/api/me/password/confirm-link", headers=program["director"])
        assert res.status_code == 200 and res.json()["sent"] is True
        assert len(mail.to(EMAIL)) == 2
        assert client.post("/api/login/confirm", json={"token": first}).status_code == 401
        assert client.post("/api/login/confirm", json={"token": _confirm_link(mail)}).status_code == 200

    def test_sending_again_is_limited_to_a_few_an_hour(self, client, program, mail):
        _set(client, program["director"])
        results = [client.post("/api/me/password/confirm-link", headers=program["director"]).json()["sent"]
                   for _ in range(6)]
        assert results.count(True) <= 2 and False in results
        assert len(mail.to(EMAIL)) <= 3

    def test_a_confirmed_address_has_nothing_to_resend(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        res = client.post("/api/me/password/confirm-link", headers=program["director"])
        assert res.json()["sent"] is False and mail.sent == []

    def test_the_message_is_honest_that_nobody_reads_replies(self, client, program, mail):
        _set(client, program["director"])
        msg = mail.to(EMAIL)[0]
        assert "not monitored" in msg["text"].lower()
        assert not any(k.lower() == "reply-to" for k in msg["headers"])

    def test_nothing_about_it_reaches_anyone_else(self, client, program, mail):
        _set(client, program["director"])
        assert {m["to"] for m in mail.sent} == {EMAIL}


# --------------------------------------------------------------------------- forgot
class TestEmailMeALink:
    def test_a_confirmed_address_gets_a_reset_link(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        res = _forgot(client)
        assert res.status_code == 200
        msgs = mail.to(EMAIL)
        assert len(msgs) == 1 and "?reset=" in msgs[0]["text"]
        assert "expires" in msgs[0]["text"].lower() or "hour" in msgs[0]["text"].lower()

    def test_the_answer_is_the_same_for_every_kind_of_address(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        known = _forgot(client)
        unknown = _forgot(client, "nobody@nowhere.example")
        junk = _forgot(client, "not an address")
        assert known.status_code == unknown.status_code == junk.status_code == 200
        assert known.json() == unknown.json() == junk.json()

    def test_an_unconfirmed_address_gets_no_reset_link(self, client, program, mail):
        _set(client, program["director"])
        mail.sent.clear()
        _forgot(client)
        assert mail.sent == []

    def test_an_unknown_address_gets_nothing(self, client, program, mail):
        _forgot(client, "nobody@nowhere.example")
        assert mail.sent == []

    def test_a_deactivated_account_gets_nothing(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        _db().execute("UPDATE users SET active = 0 WHERE id = (SELECT user_id FROM credentials)")
        _db().commit()
        _forgot(client)
        assert mail.sent == []

    def test_the_address_is_matched_loosely(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        _forgot(client, "  JOEL@NashvilleDogs.Example ")
        assert len(mail.to(EMAIL)) == 1

    def test_only_a_few_a_hour_go_to_one_address(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        outcomes = [_forgot(client).status_code for _ in range(6)]
        assert set(outcomes) <= {200, 429}
        assert 1 <= len(mail.to(EMAIL)) <= 3

    def test_asking_again_kills_the_earlier_link(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        _forgot(client)
        first = _reset_link(mail)
        _forgot(client)
        second = _reset_link(mail)
        assert first != second
        assert client.post("/api/login/reset-link", json={"token": first, "new_password": NEW}).status_code == 401
        assert client.post("/api/login/reset-link", json={"token": second, "new_password": NEW}).status_code == 200

    def test_spraying_requests_is_slowed_down(self, client, program, mail):
        codes = [_forgot(client, f"person{i}@example.com").status_code for i in range(14)]
        assert 429 in codes
        assert mail.sent == []

    def test_asking_never_slows_down_signing_in_with_a_code(self, client, program, mail):
        for i in range(14):
            _forgot(client, f"person{i}@example.com")
        assert client.get("/api/me/password", headers=program["director"]).status_code == 200

    def test_with_no_email_service_it_says_so_and_sends_nothing(self, client, program):
        _set(client, program["director"])
        res = _forgot(client)
        assert res.status_code == 200 and res.json()["mail"] is False
        assert _db().execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0] == 0

    def test_a_suppressed_address_is_not_mailed(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        mailer.suppress(_db(), EMAIL, "bounced")
        _forgot(client)
        assert mail.sent == []

    def test_it_goes_out_even_though_the_parents_hold_is_on(self, client, program, mail):
        assert _db().execute("SELECT mail_hold FROM organizations").fetchone()[0] == 1
        _confirmed(client, mail, program["director"])
        _forgot(client)
        assert len(mail.to(EMAIL)) == 1
        assert _db().execute("SELECT mail_hold FROM organizations").fetchone()[0] == 1
        assert not mailer.can_send(_db(), program["org"]["org_id"])

    def test_it_never_reaches_a_parent(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        _forgot(client)
        assert {m["to"] for m in mail.sent} == {EMAIL}


# --------------------------------------------------------------------------- reset
class TestChoosingANewPasswordFromTheLink:
    def _ready(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        _forgot(client)
        return _reset_link(mail)

    def test_the_link_sets_the_password_and_signs_you_in(self, client, program, mail):
        token = self._ready(client, program, mail)
        res = client.post("/api/login/reset-link", json={"token": token, "new_password": NEW})
        assert res.status_code == 200, res.text
        session = res.json()["token"]
        assert client.get("/api/me/password", headers=_bearer(session)).status_code == 200
        assert _login(client, password=NEW).status_code == 200

    def test_the_old_password_stops_working(self, client, program, mail):
        token = self._ready(client, program, mail)
        client.post("/api/login/reset-link", json={"token": token, "new_password": NEW})
        assert _login(client, password=GOOD).status_code == 401

    def test_every_open_session_is_ended(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        old = _login(client).json()["token"]
        _forgot(client)
        token = _reset_link(mail)
        assert client.get("/api/me/password", headers=_bearer(old)).status_code == 200
        client.post("/api/login/reset-link", json={"token": token, "new_password": NEW})
        assert client.get("/api/me/password", headers=_bearer(old)).status_code == 401

    def test_the_link_works_once(self, client, program, mail):
        token = self._ready(client, program, mail)
        assert client.post("/api/login/reset-link", json={"token": token, "new_password": NEW}).status_code == 200
        assert client.post("/api/login/reset-link", json={"token": token, "new_password": "another-long-one-9"}).status_code == 401
        assert _login(client, password=NEW).status_code == 200

    def test_a_weak_password_is_refused_and_does_not_spend_the_link(self, client, program, mail):
        token = self._ready(client, program, mail)
        weak = client.post("/api/login/reset-link", json={"token": token, "new_password": "short"})
        assert weak.status_code == 400 and weak.json()["detail"]
        assert client.post("/api/login/reset-link", json={"token": token, "new_password": NEW}).status_code == 200

    def test_an_expired_link_is_refused(self, client, program, mail):
        token = self._ready(client, program, mail)
        _db().execute("UPDATE email_tokens SET expires_at = ?",
                      ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds"),))
        _db().commit()
        assert client.post("/api/login/reset-link", json={"token": token, "new_password": NEW}).status_code == 401
        assert _login(client, password=GOOD).status_code == 200

    def test_a_link_lasts_about_an_hour_not_a_day(self, client, program, mail):
        self._ready(client, program, mail)
        row = _db().execute("SELECT created_at, expires_at FROM email_tokens WHERE purpose = 'reset'").fetchone()
        span = datetime.fromisoformat(row["expires_at"]) - datetime.fromisoformat(row["created_at"])
        assert timedelta(minutes=30) <= span <= timedelta(hours=2)

    def test_a_made_up_link_is_refused_and_guessing_is_slowed(self, client, program, mail):
        codes = [client.post("/api/login/reset-link", json={"token": f"{i:043d}", "new_password": NEW}).status_code
                 for i in range(14)]
        assert codes[0] == 401 and 429 in codes

    def test_a_confirm_link_cannot_reset_a_password(self, client, program, mail):
        _set(client, program["director"])
        confirm = _confirm_link(mail)
        assert client.post("/api/login/reset-link", json={"token": confirm, "new_password": NEW}).status_code == 401

    def test_a_reset_link_cannot_confirm_an_address(self, client, program, mail):
        token = self._ready(client, program, mail)
        assert client.post("/api/login/confirm", json={"token": token}).status_code == 401

    def test_changing_the_address_kills_links_already_sent(self, client, program, mail):
        token = self._ready(client, program, mail)
        res = client.post("/api/me/email", headers=program["director"],
                          json={"email": "joel.new@nashvilledogs.example", "current_password": GOOD})
        assert res.status_code == 200, res.text
        assert client.post("/api/login/reset-link", json={"token": token, "new_password": NEW}).status_code == 401

    def test_a_link_follows_its_address_even_if_the_row_was_not_cleaned_up(self, client, program, mail):
        """Two safeguards stop a link outliving its address: the links are deleted when the
        address changes, AND a link is checked against the address it was sent to. Prove the
        second on its own by changing the address underneath a live link with no clean-up."""
        token = self._ready(client, program, mail)
        _db().execute("UPDATE credentials SET email = 'someone.else@example.com'")
        _db().commit()
        assert _db().execute("SELECT COUNT(*) FROM email_tokens WHERE purpose = 'reset'").fetchone()[0] == 1
        res = client.post("/api/login/reset-link", json={"token": token, "new_password": NEW})
        assert res.status_code == 401
        assert _login(client, "someone.else@example.com", GOOD).status_code == 200, "password must be unchanged"

    def test_the_six_character_code_still_opens_the_account(self, client, program, mail):
        token = self._ready(client, program, mail)
        client.post("/api/login/reset-link", json={"token": token, "new_password": NEW})
        assert client.get("/api/me/password", headers=program["director"]).status_code == 200

    def test_a_notice_says_the_password_was_changed(self, client, program, mail):
        token = self._ready(client, program, mail)
        mail.sent.clear()
        client.post("/api/login/reset-link", json={"token": token, "new_password": NEW})
        notice = mail.to(EMAIL)
        assert len(notice) == 1 and "changed" in notice[0]["subject"].lower()
        assert NEW not in notice[0]["text"] and "reset=" not in notice[0]["text"]

    def test_a_link_only_ever_resets_its_own_account(self, client, program, mail):
        token = self._ready(client, program, mail)
        coach = api_module._store.create_user(program["org"]["org_id"], "coach", "Coach Two")
        _set(client, _bearer(coach["token"]), email="coach.two@example.com", password="coach-two-passphrase-1")
        client.post("/api/login/reset-link", json={"token": token, "new_password": NEW})
        assert _login(client, "coach.two@example.com", "coach-two-passphrase-1").status_code == 200

    def test_nothing_secret_is_stored_in_the_clear(self, client, program, mail):
        token = self._ready(client, program, mail)
        dump = json.dumps([tuple(r) for r in _db().execute("SELECT * FROM email_tokens")])
        assert token not in dump
        assert token not in json.dumps([tuple(r) for r in _db().execute("SELECT * FROM credentials")])


# --------------------------------------------------------------------------- email change
class TestChangingYourEmail:
    def test_it_needs_the_current_password(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        res = client.post("/api/me/email", headers=program["director"],
                          json={"email": "new@example.com", "current_password": "not-the-password"})
        assert res.status_code == 400
        assert mail.sent == []

    def test_the_new_address_must_be_confirmed_before_it_can_reset(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        client.post("/api/me/email", headers=program["director"],
                    json={"email": "new@example.com", "current_password": GOOD})
        assert len(mail.to("new@example.com")) == 1
        mail.sent.clear()
        _forgot(client, "new@example.com")
        assert mail.sent == [], "an unconfirmed new address must not be sent a reset link"

    def test_after_confirming_the_new_address_resets_work_and_the_old_does_not(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        client.post("/api/me/email", headers=program["director"],
                    json={"email": "new@example.com", "current_password": GOOD})
        client.post("/api/login/confirm", json={"token": _confirm_link(mail, "new@example.com")})
        mail.sent.clear()
        _forgot(client, EMAIL)
        assert mail.sent == []
        _forgot(client, "new@example.com")
        assert len(mail.to("new@example.com")) == 1

    def test_an_address_in_use_is_refused_without_saying_whose(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        coach = api_module._store.create_user(program["org"]["org_id"], "coach", "Coach Two")
        _set(client, _bearer(coach["token"]), email="coach.two@example.com", password="coach-two-passphrase-1")
        res = client.post("/api/me/email", headers=program["director"],
                          json={"email": "coach.two@example.com", "current_password": GOOD})
        assert res.status_code == 400 and "coach.two" not in res.text

    def test_sign_in_follows_the_new_address(self, client, program, mail):
        _confirmed(client, mail, program["director"])
        client.post("/api/me/email", headers=program["director"],
                    json={"email": "new@example.com", "current_password": GOOD})
        assert _login(client, "new@example.com").status_code == 200
        assert _login(client, EMAIL).status_code == 401


# --------------------------------------------------------------------------- who may use it
class TestWhoMayUseIt:
    def test_an_athlete_cannot_use_the_staff_routes(self, client, program, mail):
        h = program["athletes"][0]["headers"]
        assert client.post("/api/me/email", headers=h, json={"email": "a@b.example", "current_password": "x"}).status_code in (401, 403)
        assert client.post("/api/me/password/confirm-link", headers=h).status_code in (401, 403)

    def test_an_athlete_address_never_gets_a_reset_link(self, client, program, mail):
        # Even if a confirmed credentials row somehow existed for a child, no link goes out.
        kid = program["athletes"][0]["id"]
        _db().execute(
            "INSERT INTO credentials(user_id, email, pw_hash, email_verified_at, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (kid, "kid@example.com", "scrypt$x", "2026-11-01T00:00:00+00:00", "2026-11-01", "2026-11-01"))
        _db().commit()
        _forgot(client, "kid@example.com")
        assert mail.sent == []

    def test_the_routes_need_no_sign_in_but_reveal_nothing(self, client, program, mail):
        for path, body in (("/api/login/forgot", {"email": "x@y.example"}),
                           ("/api/login/confirm", {"token": "z" * 43}),
                           ("/api/login/reset-link", {"token": "z" * 43, "new_password": NEW})):
            res = client.post(path, json=body)
            assert res.status_code in (200, 401), (path, res.status_code)


# --------------------------------------------------------------------------- delivery
class TestDeliveredAtOnceAndOnlyThat:
    def test_the_message_goes_out_straight_away_not_on_the_hourly_run(self, client, program, mail):
        _set(client, program["director"])
        row = _db().execute("SELECT status FROM email_outbox WHERE to_email = ?", (EMAIL,)).fetchone()
        assert row["status"] == "sent"

    def test_other_queued_mail_is_left_for_the_scheduled_run(self, client, program, mail):
        other = mailer.enqueue(_db(), to_email="someone@else.example", subject="digest", html="<p>x</p>",
                               text="x", kind=mailer.Kind.TRANSACTIONAL, dedupe_key="older-message")
        _set(client, program["director"])
        assert _db().execute("SELECT status FROM email_outbox WHERE id = ?", (other,)).fetchone()["status"] == "queued"
        assert mail.to("someone@else.example") == []

    def test_a_provider_that_is_down_does_not_break_the_page(self, client, program, monkeypatch):
        patched = dataclasses.replace(CONFIG, smtp_host="smtp.test", app_base_url="https://app.0ffdays.com")
        monkeypatch.setattr(mailer, "CONFIG", patched)

        class Down:
            def send(self, *a, **k):
                raise RuntimeError("provider unreachable")

        monkeypatch.setattr(mailer, "default_transport", lambda: Down())
        res = _set(client, program["director"])
        assert res.status_code == 200
        assert _login(client).status_code == 200


# --------------------------------------------------------------------------- the pages
class TestThePagesHaveTheirHandlers:
    STATIC = __import__("pathlib").Path(__file__).resolve().parents[1] / "offdays" / "web" / "static"

    def test_the_sign_in_page_asks_for_a_link_and_spends_one(self):
        html = (self.STATIC / "index.html").read_text(encoding="utf-8")
        for needle in ("/api/login/forgot", "/api/login/reset-link", "/api/login/confirm",
                       "get('reset')", "get('confirm')", "no-referrer"):
            assert needle in html, needle

    def test_settings_can_resend_and_change_the_address(self):
        html = (self.STATIC / "coach.html").read_text(encoding="utf-8")
        for needle in ("/api/me/password/confirm-link", "/api/me/email"):
            assert needle in html, needle
