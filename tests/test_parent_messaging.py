"""Invites to parents go out as messages from 0FFDAYS on behalf of the coach or director.

* The From line names the person ("Matt (Nashville Dogs) via 0FFDAYS") on the program's own mail address, and a reply
  goes to that person, not to a mailbox nobody reads.
* The sender can add a note of their own, which is plain text, bounded, and escaped.
* It is sent right away (not at the next hourly run), and still never while the program's email hold is on.
* The sender can preview exactly what a parent will get, and send a test to themselves, which reaches nobody else.
"""
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

CSV = (
    "First Name,Last Name,Birth Year,Parent Email\n"
    "Dillon,Langdon,2013,robert@example.com\n"
    "Killian,Langdon,2015,robert@example.com\n"
    "Ben,Amden,2013,jessica@example.com\n"
)
DIRECTOR_EMAIL = "matt@nashvilledogs.example"
CSV_BEN = "First Name,Last Name,Birth Year,Parent Email\nBen,Amden,2013,jessica@example.com\n"


class Recorder:
    def __init__(self):
        self.sent = []

    def send(self, to_email, subject, html, text, headers):
        self.sent.append({"to": to_email, "subject": subject, "html": html, "text": text, "headers": dict(headers)})
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
    for mod in (invites, mailer):
        monkeypatch.setattr(mod, "CONFIG", patched)
    monkeypatch.setattr(api_module, "CONFIG", patched)
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def db():
    return api_module._store.conn


def program(client, email=DIRECTOR_EMAIL, release=True, name="Nashville Dogs", director="Matt Kallberg"):
    made = client.post("/api/orgs", json={"name": name, "sport": "lacrosse", "accept_terms": True,
                                          "director_name": director}).json()
    h = {"Authorization": f"Bearer {made['director']['token']}"}
    if email is not None:
        # A reply address counts only once its owner has confirmed it: record that they did.
        did = db().execute("SELECT id FROM users WHERE org_id = ? AND role = 'director'", (made["org_id"],)).fetchone()[0]
        db().execute("INSERT INTO sender_emails(user_id, email, confirmed_at) VALUES (?,?,?)",
                     (did, email, "2026-01-01T00:00:00+00:00"))
        db().commit()
    if release:
        assert client.put("/api/org/mail-hold", headers=h, json={"held": False}).status_code == 200
    team = client.post("/api/teams", json={"name": "2031 Red"}, headers=h).json()["id"]
    return {"h": h, "team": team, "org_id": made["org_id"]}


def roster(client, p, content=CSV):
    res = client.post("/api/coach/roster/import", headers=p["h"], json={"content": content, "team_id": p["team"]})
    assert res.status_code == 201, res.text
    return res.json()


def kid(client, p, name):
    rows = client.get("/api/coach/team-ranking", headers=p["h"], params={"team_id": p["team"]}).json()["rows"]
    return [r["athlete_id"] for r in rows if r["display_name"] == name][0]


def outbox():
    return [dict(r) for r in db().execute("SELECT * FROM email_outbox ORDER BY id").fetchall()]


class TestTheMailLayerCarriesWhoItIsFrom:
    def test_the_name_and_the_reply_address_become_headers(self, client):
        mailer.enqueue(db(), to_email="p@example.com", subject="s", html="h", text="t", kind=mailer.Kind.TRANSACTIONAL,
                       dedupe_key="a", from_name="Matt (Nashville Dogs) via 0FFDAYS", reply_to="matt@x.example")
        row = db().execute("SELECT * FROM email_outbox").fetchone()
        h = mailer._headers(row)
        assert h["From"] == '"Matt (Nashville Dogs) via 0FFDAYS" <no-reply@mail.0ffdays.com>'    # quoted: it holds parentheses
        assert h["Reply-To"] == "matt@x.example"

    def test_a_message_with_no_sender_is_unchanged(self, client):
        mailer.enqueue(db(), to_email="p@example.com", subject="s", html="h", text="t", kind=mailer.Kind.TRANSACTIONAL,
                       dedupe_key="a")
        h = mailer._headers(db().execute("SELECT * FROM email_outbox").fetchone())
        assert "From" not in h and "Reply-To" not in h

    @pytest.mark.parametrize("bad", ['Matt\r\nBcc: evil@x.example', 'Matt <evil@x.example>', 'Ma"tt', "Ma\\tt"])
    def test_a_sender_name_cannot_break_the_header(self, client, bad):
        mailer.enqueue(db(), to_email="p@example.com", subject="s", html="h", text="t", kind=mailer.Kind.TRANSACTIONAL,
                       dedupe_key="a", from_name=bad)
        h = mailer._headers(db().execute("SELECT * FROM email_outbox").fetchone())["From"]
        assert "\n" not in h and "\r" not in h and "<evil" not in h and h.endswith("<no-reply@mail.0ffdays.com>")

    @pytest.mark.parametrize("bad", ["not-an-email", "a@b.example, c@d.example", "a@b.example\r\nBcc: x@y.example",
                                     "<a@b.example>", "a@b.example;c@d.example"])
    def test_a_reply_address_that_is_not_one_address_is_dropped(self, client, bad):
        mailer.enqueue(db(), to_email="p@example.com", subject="s", html="h", text="t", kind=mailer.Kind.TRANSACTIONAL,
                       dedupe_key="a", reply_to=bad)
        assert db().execute("SELECT reply_to FROM email_outbox").fetchone()[0] == ""

    def test_smtp_uses_the_senders_name_once_and_keeps_the_domain(self, client, monkeypatch):
        import smtplib
        seen = {}

        class FakeSMTP:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def starttls(self): pass
            def login(self, *a): pass
            def send_message(self, message): seen["m"] = message

        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        mailer.SmtpTransport().send("p@example.com", "s", "<p>h</p>", "t",
                                    {"From": '"Matt (Club) via 0FFDAYS" <no-reply@mail.0ffdays.com>', "Reply-To": "matt@x.example"})
        m = seen["m"]
        assert m.get_all("From") == ['"Matt (Club) via 0FFDAYS" <no-reply@mail.0ffdays.com>']
        assert m["Reply-To"] == "matt@x.example"


class TestAnInviteIsAMessageOnBehalfOfTheSender:
    def test_it_is_from_the_director_by_name_and_replies_go_to_them(self, client, rec):
        p = program(client)
        roster(client, p)
        assert rec.sent, "nothing was sent"
        for m in rec.sent:
            assert m["headers"]["From"] == '"Matt Kallberg (Nashville Dogs) via 0FFDAYS" <no-reply@mail.0ffdays.com>'
            assert m["headers"]["Reply-To"] == DIRECTOR_EMAIL
            assert "Just reply to this email and it goes to Matt Kallberg" in m["text"]
            assert "Sent by 0FFDAYS on behalf of Matt Kallberg at Nashville Dogs" in m["text"]

    def test_it_goes_out_straight_away_not_at_the_hourly_run(self, client, rec):
        p = program(client)
        roster(client, p)
        assert {r["status"] for r in outbox()} == {"sent"} and len(rec.sent) == 2      # the Langdons, the Amdens

    def test_a_coach_sends_as_themselves(self, client, rec):
        """The sender is whoever the invite is made by: a coach's name and address, not the director's."""
        from offdays import guardians
        p = program(client)
        roster(client, p, CSV_BEN)
        coach = api_module._store.create_user(p["org_id"], "coach", "Sam Rivers", email="sam@x.example")
        db().execute("INSERT INTO sender_emails(user_id, email, confirmed_at) VALUES (?,?,?)",
                     (coach["id"], "sam@x.example", "2026-01-01T00:00:00+00:00"))
        db().commit()
        invite = guardians.create_invite(db(), kid(client, p, "Ben Amden"), coach["id"], "jessica@example.com")
        rec.sent.clear()
        assert invites.deliver(db(), invite, org_name="Nashville Dogs", coach_name="Sam Rivers")
        row = db().execute("SELECT from_name, reply_to FROM email_outbox ORDER BY id DESC").fetchone()
        assert row["from_name"] == "Sam Rivers (Nashville Dogs) via 0FFDAYS" and row["reply_to"] == "sam@x.example"

    def test_without_an_address_for_the_sender_it_says_replies_are_not_read(self, client, rec):
        p = program(client, email=None)
        roster(client, p)
        for m in rec.sent:
            assert "Reply-To" not in m["headers"]
            assert "Replies to this address are not read, so please contact Matt Kallberg directly" in m["text"]
            assert "Just reply" not in m["text"]

    def test_the_hold_still_stops_everything(self, client, rec):
        p = program(client, release=False)
        out = roster(client, p)
        assert rec.sent == [] and outbox() == [] and out["emailed"] == 0
        ids = [kid(client, p, "Dillon Langdon"), kid(client, p, "Ben Amden")]
        res = client.post("/api/coach/families/nudge-many", headers=p["h"], json={"athlete_ids": ids, "intro": "Hi!"}).json()
        assert rec.sent == [] and outbox() == []
        assert [r["status"] for r in res["results"]] == ["ready", "ready"]

    def test_a_held_program_still_gets_the_whole_message_to_send_itself(self, client, rec):
        p = program(client, release=False)
        roster(client, p, CSV_BEN)
        res = client.post("/api/coach/families/nudge-many", headers=p["h"],
                          json={"athlete_ids": [kid(client, p, "Ben Amden")], "intro": "Hi from Matt"}).json()
        text = res["results"][0]["text"]
        assert text.startswith("Hi from Matt") and "Just reply to this email" in text
        assert res["from_name"] == "Matt Kallberg (Nashville Dogs) via 0FFDAYS" and res["reply_to"] == DIRECTOR_EMAIL


class TestTheSendersOwnNote:
    def _send(self, client, p, intro, ids=None):
        roster(client, p, "First Name,Last Name,Birth Year,Parent Email\nBen,Amden,2013,jessica@example.com\n")
        return client.post("/api/coach/families/nudge-many", headers=p["h"],
                           json={"athlete_ids": ids or [kid(client, p, "Ben Amden")], "intro": intro})

    def test_the_note_is_on_top_of_what_every_parent_gets(self, client, rec):
        p = program(client)
        self._send(client, p, "Hi all, Matt here.\n\nThis is our fall pilot with 0FFDAYS.")
        m = rec.sent[-1]
        assert m["text"].startswith("Hi all, Matt here.\n\nThis is our fall pilot with 0FFDAYS.\n\n")
        assert "Hi all, Matt here." in m["html"] and "Set up Ben" in m["html"]
        assert m["html"].index("Matt here") < m["html"].index("Set up Ben")

    def test_each_parent_still_gets_their_own_link(self, client, rec):
        p = program(client)
        roster(client, p)
        ids = [kid(client, p, "Dillon Langdon"), kid(client, p, "Ben Amden")]
        rec.sent.clear()
        client.post("/api/coach/families/nudge-many", headers=p["h"], json={"athlete_ids": ids, "intro": "Hello"})
        links = {m["to"]: [w for w in m["text"].split() if "invite=" in w][0] for m in rec.sent}
        assert set(links) == {"robert@example.com", "jessica@example.com"} and len(set(links.values())) == 2

    def test_the_note_is_plain_text_not_markup(self, client, rec):
        p = program(client)
        self._send(client, p, '<script>alert(1)</script> <b>hi</b> & "quotes"')
        html = rec.sent[-1]["html"]
        assert "<script>" not in html and "&lt;script&gt;" in html and "<b>hi</b>" not in html

    def test_it_is_bounded_and_cleaned(self, client, rec):
        assert len(invites.clean_intro("x" * 5000)) == invites.MAX_INTRO
        assert invites.clean_intro("a\r\n\r\n\r\n\r\nb\x00\x07") == "a\n\nb"
        assert invites.clean_intro("   ") == ""
        p = program(client)
        roster(client, p, "First Name,Last Name,Birth Year,Parent Email\nBen,Amden,2013,j@example.com\n")
        too_long = client.post("/api/coach/families/nudge-many", headers=p["h"],
                               json={"athlete_ids": [kid(client, p, "Ben Amden")], "intro": "x" * 1501})
        assert too_long.status_code == 422

    def test_no_note_means_the_standard_message_with_only_the_footer_added(self, client, rec):
        p = program(client)
        self._send(client, p, "")
        assert "border-left" not in rec.sent[-1]["html"]
        assert rec.sent[-1]["text"].startswith("Matt Kallberg at Nashville Dogs uses 0FFDAYS")

    def test_a_family_message_names_the_children_and_carries_the_note(self, client, rec):
        p = program(client)
        roster(client, p)
        rec.sent.clear()
        client.post("/api/coach/families/nudge-many", headers=p["h"],
                    json={"athlete_ids": [kid(client, p, "Dillon Langdon")], "intro": "Welcome, Langdons."})
        m = rec.sent[-1]
        assert "Dillon and Killian" in m["subject"] and m["text"].startswith("Welcome, Langdons.")


class TestPreviewAndTest:
    def test_the_preview_shows_what_a_parent_gets_and_sends_nothing(self, client, rec):
        p = program(client)
        res = client.post("/api/coach/families/invite-preview", headers=p["h"], json={"intro": "Hi from Matt"})
        assert res.status_code == 200
        body = res.json()
        assert body["from_name"] == "Matt Kallberg (Nashville Dogs) via 0FFDAYS"
        assert body["reply_to"] == DIRECTOR_EMAIL and body["sending"] is True
        assert body["text"].startswith("Hi from Matt") and "ABCD-EFGH-JKLM" in body["text"]
        assert rec.sent == [] and outbox() == []

    def test_the_preview_uses_the_real_childs_name(self, client, rec):
        p = program(client)
        roster(client, p, "First Name,Last Name,Birth Year,Parent Email\nBen,Amden,2013,j@example.com\n")
        res = client.post("/api/coach/families/invite-preview", headers=p["h"],
                          json={"intro": "", "athlete_id": kid(client, p, "Ben Amden")}).json()
        assert "set up Ben's training app" in res["subject"]

    def test_the_preview_does_not_leak_another_programs_child(self, client, rec):
        a, b = program(client), program(client, name="Other Club", director="Other Dir", email="o@x.example")
        roster(client, b, "First Name,Last Name,Birth Year,Parent Email\nSecret,Kid,2013,s@example.com\n")
        res = client.post("/api/coach/families/invite-preview", headers=a["h"],
                          json={"intro": "", "athlete_id": kid(client, b, "Secret Kid")}).json()
        assert "Secret" not in res["subject"] + res["text"]

    def test_the_preview_says_when_email_is_on_hold(self, client):
        p = program(client, release=False)
        assert client.post("/api/coach/families/invite-preview", headers=p["h"], json={"intro": ""}).json()["sending"] is False

    def test_a_test_goes_only_to_the_sender_even_while_held(self, client, rec):
        p = program(client, release=False)
        roster(client, p)
        res = client.post("/api/coach/families/invite-test", headers=p["h"], json={"intro": "Testing"})
        assert res.status_code == 200, res.text
        assert res.json()["sent_to"] == DIRECTOR_EMAIL and res.json()["status"] == "sent"
        assert [m["to"] for m in rec.sent] == [DIRECTOR_EMAIL]
        m = rec.sent[0]
        assert m["subject"].startswith("TEST: ") and "placeholder" in m["text"] and "TEST-ONLY-0000" in m["text"]
        assert m["headers"]["From"].startswith('"Matt Kallberg (Nashville Dogs) via 0FFDAYS"')

    def test_a_test_needs_an_address_on_the_account(self, client, rec):
        p = program(client, email=None)
        assert client.post("/api/coach/families/invite-test", headers=p["h"], json={"intro": ""}).status_code == 409
        assert rec.sent == []

    def test_a_test_needs_a_mail_provider(self, client, rec, monkeypatch):
        p = program(client)
        monkeypatch.setattr(mailer, "provider_ready", lambda: False)
        assert client.post("/api/coach/families/invite-test", headers=p["h"], json={"intro": ""}).status_code == 409

    def test_two_tests_are_two_messages(self, client, rec):
        p = program(client)
        for _ in range(2):
            assert client.post("/api/coach/families/invite-test", headers=p["h"], json={"intro": ""}).status_code == 200
        assert len(rec.sent) == 2

    def test_a_parent_or_a_stranger_cannot_use_either(self, client, rec):
        p = program(client)
        for path in ("invite-preview", "invite-test"):
            assert client.post(f"/api/coach/families/{path}", json={"intro": ""}).status_code in (401, 403)
            assert client.post(f"/api/coach/families/{path}", headers={"Authorization": "Bearer nope"},
                               json={"intro": ""}).status_code in (401, 403)


class TestTheScreen:
    @staticmethod
    def page(name):
        from pathlib import Path
        return (Path(api_module.__file__).parent / "web" / "static" / name).read_text(encoding="utf-8")

    def test_there_is_a_note_box_a_preview_and_a_test_button(self):
        html = self.page("coach.html")
        for needle in ('id="msg-intro"', 'id="msg-preview"', 'id="msg-test"', "/api/coach/families/invite-preview",
                       "/api/coach/families/invite-test"):
            assert needle in html, needle

    def test_the_note_travels_with_every_send(self):
        html = self.page("coach.html")
        assert "intro: $('msg-intro').value" in html
        assert html.count("/api/coach/families/nudge-many") >= 1 and "body: { athlete_ids: ids.slice(i, i + 200), intro" in html


class TestThePreviewReadsRightWithoutAChild:
    def test_an_unnamed_child_reads_as_your_athlete_not_your_s(self, client, rec):
        p = program(client)
        m = client.post("/api/coach/families/invite-preview", headers=p["h"], json={"intro": ""}).json()
        assert "set up your athlete's training app" in m["subject"]
        assert "your's" not in m["text"] and "so your can" not in m["text"]
        assert "so your athlete can record drills" in m["text"]


class TestSendToEveryoneAtOnce:
    """\"Select everyone, Send invites\": one press, an email to every parent, in their own name and with their own link."""

    ROSTER = (
        "First Name,Last Name,Birth Year,Parent Email\n"
        + "".join(f"Kid{n},Family{n},2013,parent{n}@example.com\n" for n in range(1, 24))
    )

    def _everyone(self, client, p):
        rows = client.get("/api/coach/team-ranking", headers=p["h"], params={"team_id": p["team"]}).json()["rows"]
        return [r["athlete_id"] for r in rows]

    def test_every_parent_gets_their_own_email_with_their_childs_name_and_their_own_link(self, client, rec):
        p = program(client, release=False)
        roster(client, p, self.ROSTER)
        assert rec.sent == []                                                   # on hold: nothing yet
        client.put("/api/org/mail-hold", headers=p["h"], json={"held": False})
        ids = self._everyone(client, p)
        assert len(ids) == 23
        res = client.post("/api/coach/families/nudge-many", headers=p["h"], json={"athlete_ids": ids}).json()
        assert res["counts"]["emailed"] == 23 and res["counts"]["skipped"] == 0
        assert len(rec.sent) == 23
        by = {m["to"]: m for m in rec.sent}
        assert set(by) == {f"parent{n}@example.com" for n in range(1, 24)}
        codes = set()
        for n in range(1, 24):
            m = by[f"parent{n}@example.com"]
            assert m["subject"].endswith(f"set up Kid{n}'s training app") and f"so Kid{n} can record drills" in m["text"]
            code = re.search(r"invite=([A-Z0-9-]{14})", m["text"]).group(1)
            codes.add(code)
            assert code in m["html"] and "Why we are doing this" in m["text"]
        assert len(codes) == 23                                                # every link is their own

    def test_a_family_is_emailed_once_however_many_children_it_has(self, client, rec):
        p = program(client, release=True)
        roster(client, p, "First Name,Last Name,Birth Year,Parent Email\nAnn,Cole,2013,c@example.com\nBo,Cole,2015,c@example.com\n"
                          "Cy,Dane,2013,d@example.com\n")
        rec.sent.clear()
        ids = self._everyone(client, p)
        client.post("/api/coach/families/nudge-many", headers=p["h"], json={"athlete_ids": ids})
        assert sorted(m["to"] for m in rec.sent) == ["c@example.com", "d@example.com"]

    def test_while_on_hold_nobody_is_emailed_and_each_invite_is_left_ready(self, client, rec):
        p = program(client, release=False)
        roster(client, p, self.ROSTER)
        res = client.post("/api/coach/families/nudge-many", headers=p["h"], json={"athlete_ids": self._everyone(client, p)}).json()
        assert rec.sent == [] and res["counts"]["ready"] == 23 and res["counts"]["emailed"] == 0

    def test_only_the_director_can_turn_email_on(self, client, rec):
        p = program(client, release=False)
        coach = api_module._store.create_user(p["org_id"], "coach", "Sam", email="s@x.example")
        res = client.put("/api/org/mail-hold", headers={"Authorization": f"Bearer {coach['token']}"}, json={"held": False})
        assert res.status_code == 403
        assert client.get("/api/org/mail-hold", headers=p["h"]).json()["held"] is True


class TestTheBulkButtonExplainsAndTurnsEmailOn:
    @staticmethod
    def page():
        from pathlib import Path
        return (Path(api_module.__file__).parent / "web" / "static" / "coach.html").read_text(encoding="utf-8")

    def test_a_line_under_the_button_says_what_it_will_do(self):
        html = self.page()
        assert 'id="fam-bulk-note"' in html
        assert "Each parent gets their own email from 0FFDAYS, with their athlete" in html
        assert "You do not need to send them one by one" in html
        assert "Email is on hold, so nothing has been sent yet. When you press the button it asks to turn email on" in html

    def test_pressing_it_on_hold_offers_to_turn_email_on_and_send(self):
        html = self.page()
        assert "Press OK to turn email on and email ${word} now" in html
        assert "api('/api/org/mail-hold', { method: 'PUT', body: { held: false } })" in html
        assert "Press Cancel to only prepare the invites" in html

    def test_it_counts_parents_not_children(self):
        """Two brothers under one address are one parent, so the button and the question say so."""
        html = self.page()
        assert "const famCount = (list) => new Set(list.map(famKey)).size;" in html
        assert "const parents = famCount(picked);" in html and "${verb} to ${parents} parent" in html
        assert "const word = `${parents} parent${parents === 1 ? '' : 's'}`;" in html

    def test_a_coach_is_not_offered_the_switch(self):
        assert "if (!sending && IS_DIRECTOR && msgState && msgState.provider_configured)" in self.page()
