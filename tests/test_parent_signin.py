"""A parent who has lost their way back in (new phone, cleared browser) emails themselves a sign-in link. Unattended.

A parent signs up once with an invite code and is then signed in by a code the phone keeps. They have no password, so a new
phone used to be a dead end. Rules these tests hold in place:

* a link goes only to an address the PROGRAM gave us (the roster, or the address the invite was emailed to), never to an
  address the parent typed at sign-up, so a typo cannot hand a stranger a parent's account and a child's details;
* the answer is identical for a known, unknown, held, suppressed or malformed address, so it cannot be used to learn who
  is a parent;
* the director's email hold stays in charge: nothing is sent while it is on;
* a link works once, lasts an hour, dies when a newer one is asked for, and spending it signs out the old phone;
* a link opens a PARENT account and nothing else; it never opens a coach, director or athlete;
* the abuse limits hold, and nothing secret is stored in the clear.
"""
from __future__ import annotations

import dataclasses
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import mailer
from offdays import parent_signin
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store

KATHY = "kathy.k@example.com"


class Recorder:
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, to_email, subject, html, text, headers):
        self.sent.append({"to": to_email, "subject": subject, "html": html, "text": text})
        return mailer.SendResult(ok=True)

    def to(self, address):
        return [m for m in self.sent if m["to"] == address]


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


@pytest.fixture
def mail(monkeypatch):
    """The server HAS a mail provider. Each program's hold is left as it ships: on."""
    patched = dataclasses.replace(CONFIG, smtp_host="smtp.test", app_base_url="https://app.0ffdays.com")
    monkeypatch.setattr(mailer, "CONFIG", patched)
    rec = Recorder()
    monkeypatch.setattr(mailer, "default_transport", lambda: rec)
    return rec


def db():
    return api_module._store.conn


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def club(client, org="Mad Dogs", director="Joel"):
    made = client.post("/api/orgs", json={"name": org, "sport": "lacrosse", "accept_terms": True,
                                          "director_name": director}).json()
    d = bearer(made["director"]["token"])
    t = client.post("/api/teams", json={"name": "U12"}, headers=d).json()["id"]
    return {"d": d, "team": t, "org_id": made["org_id"] if "org_id" in made else made["director"].get("org_id")}


def add_family(client, c, name="Sam Dogs", roster_email=KATHY, typed_email=None, invite_email=None):
    """Roster a kid with a parent email, then have the parent redeem the invite (typing `typed_email`)."""
    first, last = name.split()
    client.post("/api/coach/roster/import", headers=c["d"], json={
        "content": f"First Name,Last Name,Birth Year,Parent Email\n{first},{last},2014,{roster_email}\n",
        "team_id": c["team"]})
    rows = client.get("/api/coach/team-ranking", headers=c["d"], params={"team_id": c["team"]}).json()["rows"]
    kid = [r for r in rows if r.get("display_name", r.get("name", r.get("athlete_name"))) == name][0]["athlete_id"]
    inv = client.post("/api/coach/guardian-invites", headers=c["d"],
                      json={"athlete_id": kid, "email": invite_email or roster_email}).json()
    parent = client.post("/api/guardians/redeem", json={
        "code": inv["code"], "display_name": "Kathy Dogs", "email": typed_email or roster_email,
        "phone": "615-555-0101"}).json()
    return {"kid": kid, "parent_token": parent["token"], "parent_id": parent["guardian_id"]}


def release(client, c):
    assert client.put("/api/org/mail-hold", json={"held": False}, headers=c["d"]).status_code == 200


def ask(client, email=KATHY):
    return client.post("/api/login/parent-forgot", json={"email": email})


def link_in(message):
    m = re.search(r"[?&]parent=([A-Za-z0-9_\-]+)", message["text"])
    assert m, message["text"]
    return m.group(1)


def spend(client, token):
    return client.post("/api/login/parent-link", json={"token": token})


@pytest.fixture
def open_club(client, mail):
    c = club(client)
    f = add_family(client, c)
    release(client, c)
    return c, f


# -------------------------------------------------------------------- the way back in
class TestAParentGetsBackIn:
    def test_the_link_goes_to_the_address_the_program_has(self, client, mail, open_club):
        assert ask(client).status_code == 200
        msgs = mail.to(KATHY)
        assert len(msgs) == 1
        assert msgs[0]["text"].count("https://app.0ffdays.com/app/index.html?parent=") == 1

    def test_the_email_names_the_child_and_says_what_it_does(self, client, mail, open_club):
        ask(client)
        text = mail.to(KATHY)[0]["text"]
        assert "Sam" in text and "signs you out of the old one" in text and "not monitored" in text

    def test_spending_it_signs_the_parent_in_as_the_same_parent(self, client, mail, open_club):
        c, f = open_club
        ask(client)
        res = spend(client, link_in(mail.to(KATHY)[0]))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["role"] == "guardian" and body["athlete_id"] == f["parent_id"]
        me = client.get("/api/me", headers=bearer(body["token"])).json()
        assert me["role"] == "guardian" and me["display_name"] == "Kathy Dogs"

    def test_the_new_sign_in_reaches_the_same_child(self, client, mail, open_club):
        c, f = open_club
        ask(client)
        token = spend(client, link_in(mail.to(KATHY)[0])).json()["token"]
        kids = client.get("/api/guardians/me", headers=bearer(token))
        assert kids.status_code == 200
        assert f["kid"] in [k.get("athlete_id", k.get("id")) for k in kids.json()["athletes"]]

    def test_the_old_phone_is_signed_out(self, client, mail, open_club):
        c, f = open_club
        assert client.get("/api/me", headers=bearer(f["parent_token"])).status_code == 200
        ask(client)
        spend(client, link_in(mail.to(KATHY)[0]))
        assert client.get("/api/me", headers=bearer(f["parent_token"])).status_code == 401

    def test_a_link_works_once(self, client, mail, open_club):
        ask(client)
        link = link_in(mail.to(KATHY)[0])
        assert spend(client, link).status_code == 200
        assert spend(client, link).status_code == 401

    def test_a_newer_link_kills_the_older_one(self, client, mail, open_club):
        ask(client)
        first = link_in(mail.to(KATHY)[0])
        ask(client)
        second = link_in(mail.to(KATHY)[1])
        assert spend(client, first).status_code == 401
        assert spend(client, second).status_code == 200

    def test_an_expired_link_is_refused(self, client, mail, open_club):
        ask(client)
        link = link_in(mail.to(KATHY)[0])
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
        db().execute("UPDATE parent_links SET expires_at = ?", (past,))
        db().commit()
        assert spend(client, link).status_code == 401

    def test_a_link_lasts_about_an_hour(self, client, mail, open_club):
        ask(client)
        row = db().execute("SELECT created_at, expires_at FROM parent_links").fetchone()
        span = datetime.fromisoformat(row["expires_at"]) - datetime.fromisoformat(row["created_at"])
        assert span == timedelta(minutes=parent_signin.LINK_MINUTES) == timedelta(minutes=60)

    def test_a_guess_is_refused(self, client, mail, open_club):
        assert spend(client, "not-a-real-link").status_code == 401
        assert spend(client, "x" * 500).status_code in (401, 422)

    def test_the_page_says_the_link_is_dead_and_how_to_get_another(self, client, mail, open_club):
        ask(client)
        link = link_in(mail.to(KATHY)[0])
        spend(client, link)
        again = spend(client, link)
        assert "expired or was already used" in again.json()["detail"] and "Ask for a new one" in again.json()["detail"]


# --------------------------------------------------------------------- who gets a link
class TestOnlyAnAddressTheProgramGaveUs:
    def test_an_address_typed_at_signup_is_not_enough(self, client, mail):
        """The roster says kathy.k@; the parent typed a different address while signing up. Only the roster's counts."""
        c = club(client)
        add_family(client, c, roster_email=KATHY, typed_email="typo.or.stranger@example.com")
        release(client, c)
        ask(client, "typo.or.stranger@example.com")
        assert mail.sent == []
        ask(client, KATHY)
        assert len(mail.to(KATHY)) == 1

    def test_the_address_the_invite_was_emailed_to_counts(self, client, mail):
        c = club(client)
        add_family(client, c, roster_email="roster@example.com", typed_email="x@example.com", invite_email=KATHY)
        release(client, c)
        ask(client, KATHY)
        assert len(mail.to(KATHY)) == 1

    def test_capitals_and_spaces_do_not_matter(self, client, mail, open_club):
        ask(client, "  Kathy.K@Example.COM ")
        assert len(mail.to(KATHY)) == 1

    def test_a_stranger_gets_nothing(self, client, mail, open_club):
        ask(client, "nobody@example.com")
        assert mail.sent == []

    def test_a_coach_or_a_director_address_never_gets_a_parent_link(self, client, mail, open_club):
        c, f = open_club
        db().execute("UPDATE users SET email = 'joel@example.com' WHERE role = 'director'")
        db().commit()
        ask(client, "joel@example.com")
        assert mail.sent == []

    def test_a_removed_parent_gets_nothing(self, client, mail, open_club):
        c, f = open_club
        db().execute("UPDATE users SET active = 0 WHERE id = ?", (f["parent_id"],))
        db().commit()
        ask(client)
        assert mail.sent == []

    def test_a_link_cannot_open_an_account_that_has_since_been_removed(self, client, mail, open_club):
        c, f = open_club
        ask(client)
        link = link_in(mail.to(KATHY)[0])
        db().execute("UPDATE users SET active = 0 WHERE id = ?", (f["parent_id"],))
        db().commit()
        assert spend(client, link).status_code == 401

    def test_a_link_cannot_be_turned_into_another_role(self, client, mail, open_club):
        c, f = open_club
        ask(client)
        link = link_in(mail.to(KATHY)[0])
        db().execute("UPDATE users SET role = 'coach' WHERE id = ?", (f["parent_id"],))
        db().commit()
        assert spend(client, link).status_code == 401

    def test_a_suppressed_address_gets_nothing(self, client, mail, open_club):
        db().execute("INSERT INTO email_suppressions(email, reason, created_at) VALUES (?,?,?)",
                     (KATHY, "bounce", datetime.now(timezone.utc).isoformat()))
        db().commit()
        ask(client)
        assert mail.sent == []
        assert db().execute("SELECT COUNT(*) FROM parent_links").fetchone()[0] == 0   # no dead link left behind

    def test_one_address_for_two_programs_gets_a_link_for_each_account(self, client, mail):
        a = club(client, org="Club A")
        add_family(client, a, name="Sam Dogs")
        release(client, a)
        b = club(client, org="Club B")
        add_family(client, b, name="Pat Cats")
        release(client, b)
        ask(client)
        assert len(mail.to(KATHY)) == 2
        assert len({link_in(m) for m in mail.to(KATHY)}) == 2


# ---------------------------------------------------------------- the director's email hold
class TestTheEmailHoldStaysInCharge:
    def test_nothing_is_sent_while_the_hold_is_on(self, client, mail):
        c = club(client)
        add_family(client, c)
        ask(client)
        assert mail.sent == []
        assert db().execute("SELECT COUNT(*) FROM parent_links").fetchone()[0] == 0

    def test_it_is_sent_once_the_director_releases_the_hold(self, client, mail):
        c = club(client)
        add_family(client, c)
        ask(client)
        assert mail.sent == []
        release(client, c)
        ask(client)
        assert len(mail.to(KATHY)) == 1

    def test_holding_again_stops_the_next_one(self, client, mail, open_club):
        c, f = open_club
        assert client.put("/api/org/mail-hold", json={"held": True}, headers=c["d"]).status_code == 200
        ask(client)
        assert mail.sent == []

    def test_one_programs_hold_does_not_block_another_programs_parent(self, client, mail):
        a = club(client, org="Club A")
        add_family(client, a, name="Sam Dogs", roster_email="a.parent@example.com")
        b = club(client, org="Club B")
        add_family(client, b, name="Pat Cats", roster_email="b.parent@example.com")
        release(client, b)
        ask(client, "a.parent@example.com")
        ask(client, "b.parent@example.com")
        assert mail.to("a.parent@example.com") == [] and len(mail.to("b.parent@example.com")) == 1

    def test_no_provider_means_no_mail_and_no_error(self, client, monkeypatch):
        patched = dataclasses.replace(CONFIG, smtp_host="", app_base_url="https://app.0ffdays.com")
        monkeypatch.setattr(mailer, "CONFIG", patched)
        c = club(client)
        add_family(client, c)
        release(client, c)
        res = ask(client)
        assert res.status_code == 200
        assert db().execute("SELECT COUNT(*) FROM parent_links").fetchone()[0] == 0


# ----------------------------------------------------------------- nobody can learn who is a parent
class TestTheAnswerNeverSaysWhoIsAParent:
    def test_the_same_reply_for_every_kind_of_address(self, client, mail, open_club):
        known = ask(client, KATHY)
        unknown = ask(client, "nobody@example.com")
        junk = ask(client, "not an email")
        assert known.status_code == unknown.status_code == junk.status_code == 200
        assert known.json() == unknown.json() == junk.json()

    def test_the_same_reply_while_the_hold_is_on(self, client, mail):
        c = club(client)
        add_family(client, c)
        held = ask(client)
        release(client, c)
        open_ = ask(client)
        assert held.json() == open_.json()

    def test_the_reply_points_to_the_director_when_nothing_comes(self, client, mail, open_club):
        assert "director" in ask(client).json()["message"].lower()


# ------------------------------------------------------------------------------ the limits
class TestTheLimitsHold:
    def test_a_few_links_an_hour_per_parent(self, client, mail, open_club):
        for _ in range(parent_signin.HOURLY_LIMIT + 2):
            ask(client)
        assert len(mail.to(KATHY)) == parent_signin.HOURLY_LIMIT

    def test_the_limit_follows_the_account_not_the_ip(self, client, mail, open_club):
        for _ in range(parent_signin.HOURLY_LIMIT):
            db().execute("INSERT INTO parent_links(guardian_id, email, token_hash, created_at, expires_at, used_at) "
                         "SELECT id, ?, hex(randomblob(8)), ?, ?, ? FROM users WHERE role='guardian'",
                         (KATHY, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          datetime.now(timezone.utc).isoformat(timespec="seconds")))
        db().commit()
        ask(client)
        assert mail.sent == []

    def test_asking_too_often_from_one_place_is_refused(self, client, mail, open_club):
        codes = [ask(client, f"x{i}@example.com").status_code for i in range(40)]
        assert 429 in codes

    def test_guessing_links_is_refused_after_a_few_tries(self, client, mail, open_club):
        codes = [spend(client, f"guess-{i}").status_code for i in range(40)]
        assert 429 in codes


# --------------------------------------------------------------------------------- secrecy
class TestNothingSecretIsKeptInTheClear:
    def test_only_a_hash_of_the_link_is_stored(self, client, mail, open_club):
        ask(client)
        link = link_in(mail.to(KATHY)[0])
        stored = db().execute("SELECT token_hash FROM parent_links").fetchone()[0]
        assert stored != link and link not in stored and len(stored) == 64

    def test_the_new_sign_in_code_is_stored_only_as_a_hash_too(self, client, mail, open_club):
        ask(client)
        token = spend(client, link_in(mail.to(KATHY)[0])).json()["token"]
        dump = " ".join(str(v) for r in db().execute("SELECT * FROM users").fetchall() for v in tuple(r))
        assert token not in dump

    def test_the_email_is_a_transactional_message_with_no_opt_out(self, client, mail, open_club):
        ask(client)
        row = db().execute("SELECT kind FROM email_outbox WHERE to_email = ?", (KATHY,)).fetchone()
        assert row["kind"] == mailer.Kind.TRANSACTIONAL

    def test_deleting_the_parent_deletes_their_links(self, client, mail, open_club):
        c, f = open_club
        ask(client)
        db().execute("PRAGMA foreign_keys = ON")
        db().execute("DELETE FROM users WHERE id = ?", (f["parent_id"],))
        db().commit()
        assert db().execute("SELECT COUNT(*) FROM parent_links").fetchone()[0] == 0


# ------------------------------------------------------------------------ the page itself
INDEX = (__import__("pathlib").Path(__file__).resolve().parents[1] / "offdays" / "web" / "static" / "index.html").read_text(encoding="utf-8")


class TestThePage:
    def test_the_parent_panel_offers_a_way_back_in(self):
        panel = INDEX[INDEX.index('id="panel-parent"'):INDEX.index('id="family-card"')]
        assert 'id="parent-back-open"' in panel and "Get back in" in panel
        assert 'id="parent-back-email"' in panel and "Email me a sign-in link" in panel

    def test_already_set_up_no_longer_sends_a_parent_to_the_athlete_door(self):
        panel = INDEX[INDEX.index('id="panel-parent"'):INDEX.index('id="family-card"')]
        assert "Already set up?" in panel and "link-signin" not in panel

    def test_the_page_asks_for_a_link_and_spends_one(self):
        assert "/api/login/parent-forgot" in INDEX and "/api/login/parent-link" in INDEX

    def test_the_link_is_taken_out_of_the_address_bar_once_read(self):
        line = [l for l in INDEX.splitlines() if "history.replaceState" in l and "parentLink" in l]
        assert line, "the secret stays in the address bar and browser history"

    def test_a_dead_link_leaves_the_parent_on_the_form_to_ask_for_another(self):
        block = INDEX[INDEX.index("if (parentLink) {"):INDEX.index("} else if (resetLink)")]
        assert "openParentBack()" in block and "setToken(data.token)" in block and "parent.html" in block


class TestADeadLinkSaysSo:
    def test_the_page_reads_the_servers_reason_not_the_generic_signed_out_message(self):
        block = INDEX[INDEX.index("if (parentLink) {"):INDEX.index("} else if (resetLink)")]
        assert "fetch('/api/login/parent-link'" in block
        assert "api('/api/login/parent-link'" not in block, "api() rewrites a 401 as 'your sign-in ended'"
        assert "data.detail" in block


class TestEveryPurposeOfTheSameMachineryIsUnchanged:
    def test_the_staff_reset_still_refuses_a_parent_address(self, client, mail, open_club):
        client.post("/api/login/forgot", json={"email": KATHY})
        assert [m for m in mail.sent if "reset=" in m["text"]] == []

    def test_a_staff_link_does_not_open_a_parent_door(self, client, mail, open_club):
        assert spend(client, "anything").status_code == 401
