"""A parent is emailed exactly what their child was sent: automatic recognition and a coach's own messages."""
from __future__ import annotations

import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import guardians, invites, mailer, message_copy
from offdays import notifications as N
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store


class Recorder:
    def __init__(self):
        self.sent = []

    def send(self, to_email, subject, html, text, headers):
        self.sent.append({"to": to_email, "subject": subject, "html": html, "text": text, "headers": headers})
        return mailer.SendResult(ok=True)


@pytest.fixture
def rec(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(mailer, "default_transport", lambda: r)
    return r


@pytest.fixture
def program(tmp_path, monkeypatch, rec):
    patched = replace(CONFIG, smtp_host="smtp.test", app_base_url="https://app.0ffdays.com", smtp_from="0FFDAYS <no-reply@mail.0ffdays.com>")
    for mod in (mailer, invites, guardians):
        if hasattr(mod, "CONFIG"):
            monkeypatch.setattr(mod, "CONFIG", patched)
    monkeypatch.setattr(api_module, "CONFIG", patched)
    store = Store(connect(tmp_path / "pc.db"))
    api_module._store = store
    org = store.create_org("Nashville Dogs")
    director = store.create_user(org, "director", "Matt Kallberg")
    coach = store.create_user(org, "coach", "Coach Tommy")
    team = store.create_team(org, "2031 Red")
    store.assign_staff_to_team(coach["id"], team["id"])
    ryder = store.create_user(org, "athlete", "Ryder Cole", birth_year=2013, dominant_hand="right")
    store.join_team(team["join_code"], ryder["id"])
    parents = []
    for name, email in (("Dana Cole", "dana@example.com"), ("Pat Cole", "pat@example.com")):
        inv = guardians.create_invite(store.conn, ryder["id"], created_by=director["id"])
        parents.append(guardians.redeem_invite(store.conn, inv["code"], name, email=email))
    yield {"store": store, "org": org, "director": director, "coach": coach, "team": team["id"], "ryder": ryder, "parents": parents}
    api_module._store = None


def release(p):
    p["store"].conn.execute("UPDATE organizations SET mail_hold = 0 WHERE id = ?", (p["org"],))
    p["store"].conn.commit()


def flush(p):
    mailer.flush(p["store"].conn)


def copies(rec):
    return [m for m in rec.sent if m["subject"].startswith("What ")]


def bearer(p, who):
    return {"Authorization": f"Bearer {p[who]['token']}"}


class TestRecognition:
    def test_each_parent_gets_the_words_their_child_was_sent(self, program, rec):
        release(program)
        s = program["store"]
        s.award_recognition(program["ryder"]["id"], sessions_before=0)
        flush(program)
        kid = s.conn.execute("SELECT title, body FROM notifications WHERE user_id = ? AND kind = 'recognition' AND is_copy = 0",
                             (program["ryder"]["id"],)).fetchone()
        got = copies(rec)
        assert sorted(m["to"] for m in got) == ["dana@example.com", "pat@example.com"]
        for m in got:
            assert kid["body"] in m["text"] and kid["title"] in m["text"]
            assert "Ryder" in m["subject"] and "Coach Tommy" in m["subject"]

    def test_the_email_is_a_whole_hyperlinked_message_from_the_coach_by_name(self, program, rec):
        release(program)
        program["store"].award_recognition(program["ryder"]["id"], sessions_before=0)
        flush(program)
        m = [x for x in copies(rec) if x["to"] == "dana@example.com"][0]
        assert re.search(r'<a href="https://app\.0ffdays\.com/app/parent\.html"[^>]*>Open 0FFDAYS</a>', m["html"])
        assert "https://app.0ffdays.com/app/parent.html" in m["text"]
        assert "Coach Tommy" in m["headers"]["From"] and "Hi Dana," in m["text"] and "word for word" in m["text"]

    def test_the_words_are_not_changed_or_shortened(self, program, rec):
        release(program)
        N.enqueue(program["store"].conn, program["ryder"]["id"], N.Kind.RECOGNITION, "Coach Tommy noticed",
                  "Line one <b>here</b> & there.\nLine two, with a second paragraph.", dedupe_key="recognition:x", from_name="Coach Tommy")
        flush(program)
        m = copies(rec)[0]
        assert "Line one <b>here</b> & there.\nLine two, with a second paragraph." in m["text"]
        assert "Line one &lt;b&gt;here&lt;/b&gt; &amp; there.<br>Line two, with a second paragraph." in m["html"]

    def test_nothing_goes_while_the_program_email_hold_is_on(self, program, rec):
        program["store"].award_recognition(program["ryder"]["id"], sessions_before=0)
        flush(program)
        assert rec.sent == []
        # the in-app copy is unaffected
        n = program["store"].conn.execute("SELECT COUNT(*) FROM notifications WHERE is_copy = 1").fetchone()[0]
        assert n == 2

    def test_releasing_the_hold_later_does_not_send_what_was_held(self, program, rec):
        program["store"].award_recognition(program["ryder"]["id"], sessions_before=0)
        release(program)
        flush(program)
        assert copies(rec) == []

    def test_the_same_message_is_never_emailed_twice(self, program, rec):
        release(program)
        for _ in range(2):
            N.enqueue(program["store"].conn, program["ryder"]["id"], N.Kind.RECOGNITION, "t", "b", dedupe_key="recognition:dup", from_name="Coach")
        flush(program)
        assert len(copies(rec)) == 2        # one per parent, not four


class TestWhoGetsOne:
    def test_a_parent_with_no_email_is_skipped_and_the_others_are_not(self, program, rec):
        release(program)
        s = program["store"]
        s.conn.execute("UPDATE users SET email = NULL WHERE id = ?", (program["parents"][0]["guardian_id"],))
        s.conn.commit()
        s.award_recognition(program["ryder"]["id"], sessions_before=0)
        flush(program)
        assert [m["to"] for m in copies(rec)] == ["pat@example.com"]

    def test_a_parent_who_stopped_these_copies_gets_none(self, program, rec):
        release(program)
        mailer.set_preference(program["store"].conn, program["parents"][0]["guardian_id"], mailer.Kind.MESSAGE_COPY, False)
        program["store"].award_recognition(program["ryder"]["id"], sessions_before=0)
        flush(program)
        assert [m["to"] for m in copies(rec)] == ["pat@example.com"]

    def test_the_email_has_a_working_stop_these_copies_link(self, program, rec):
        release(program)
        program["store"].award_recognition(program["ryder"]["id"], sessions_before=0)
        flush(program)
        m = [x for x in copies(rec) if x["to"] == "dana@example.com"][0]
        url = re.search(r"Stop these copies: (\S+)", m["text"]).group(1)
        assert "List-Unsubscribe" in m["headers"]
        page = TestClient(api_module.app).get(url.replace("https://app.0ffdays.com", ""))
        assert page.status_code == 200 and "email copy of the messages your athlete is sent" in page.text
        assert mailer.preferences(program["store"].conn, program["parents"][0]["guardian_id"])[mailer.Kind.MESSAGE_COPY] is False

    def test_another_childs_parents_get_nothing(self, program, rec):
        release(program)
        s = program["store"]
        other = s.create_user(program["org"], "athlete", "Sam Other", birth_year=2013)
        inv = guardians.create_invite(s.conn, other["id"], created_by=program["director"]["id"])
        guardians.redeem_invite(s.conn, inv["code"], "Sam Parent", email="sam.parent@example.com")
        s.award_recognition(program["ryder"]["id"], sessions_before=0)
        flush(program)
        assert "sam.parent@example.com" not in [m["to"] for m in copies(rec)]

    def test_a_household_program_does_not_email_the_parent_their_own_words(self, tmp_path, monkeypatch, rec):
        patched = replace(CONFIG, smtp_host="smtp.test", app_base_url="https://app.0ffdays.com")
        monkeypatch.setattr(mailer, "CONFIG", patched)
        s = Store(connect(tmp_path / "fam.db"))
        org = s.create_org("The Pierces")
        s.conn.execute("UPDATE organizations SET kind = 'family', mail_hold = 0 WHERE id = ?", (org,))
        s.conn.commit()
        kid = s.create_user(org, "athlete", "Kid Pierce", birth_year=2013)
        director = s.create_user(org, "director", "Dana")
        inv = guardians.create_invite(s.conn, kid["id"], created_by=director["id"])
        guardians.redeem_invite(s.conn, inv["code"], "Dana Pierce", email="dana@example.com")
        N.enqueue(s.conn, kid["id"], N.Kind.COACH_MESSAGE, "Nice work", "Keep going", dedupe_key="coach_message:f", from_name="Dana")
        mailer.flush(s.conn)
        assert copies(rec) == []


class TestOtherMessagesAreNotCopiedByEmail:
    def test_a_streak_reminder_is_still_in_app_only(self, program, rec):
        release(program)
        N.enqueue(program["store"].conn, program["ryder"]["id"], N.Kind.STREAK_AT_RISK, "Keep your streak", "Train today", dedupe_key="s:1")
        flush(program)
        assert rec.sent == []


class TestCoachMessages:
    def test_a_team_message_is_emailed_to_each_players_parents_as_written(self, program, rec):
        release(program)
        c = TestClient(api_module.app)
        res = c.post("/api/coach/broadcast", headers=bearer(program, "coach"),
                     json={"team_id": program["team"], "title": "Practice moved", "body": "Tuesday at 6, bring water."})
        assert res.status_code == 200 and res.json()["sent"] == 1
        got = copies(rec)                       # sent right after the response, without waiting for the hourly run
        assert sorted(m["to"] for m in got) == ["dana@example.com", "pat@example.com"]
        for m in got:
            assert "Practice moved" in m["text"] and "Tuesday at 6, bring water." in m["text"]

    def test_the_nudge_everyone_message_too(self, program, rec, monkeypatch):
        release(program)
        monkeypatch.setattr(api_module, "attach_load", lambda athletes, states: [{**a, "flags": ["inactive"]} for a in athletes])
        c = TestClient(api_module.app)
        res = c.post("/api/coach/nudge-everyone", headers=bearer(program, "coach"),
                     json={"title": "We miss you", "body": "Come back to training this week.", "team_id": program["team"]})
        assert res.status_code == 200 and res.json()["sent"] == 1
        assert sorted(m["to"] for m in copies(rec)) == ["dana@example.com", "pat@example.com"]
        assert all("Come back to training this week." in m["text"] for m in copies(rec))

    def test_a_team_message_while_held_is_in_app_only(self, program, rec):
        c = TestClient(api_module.app)
        c.post("/api/coach/broadcast", headers=bearer(program, "coach"),
               json={"team_id": program["team"], "title": "Practice moved", "body": "Tuesday at 6."})
        assert rec.sent == []


class TestTheSessionRouteSendsRecognitionRightAway:
    def test_the_submit_route_flushes_what_recognition_queued(self):
        import inspect
        src = inspect.getsource(api_module.submit_session) + inspect.getsource(api_module._submit_and_mail)
        assert "take_mail_ids" in src and "_send_now" in src and "BackgroundTasks" in str(inspect.signature(api_module.submit_session))


class TestTheEmailReads:
    def test_it_follows_the_copy_rules(self):
        subject, text, html = message_copy.compose(athlete_first="Ryder", sender="Coach Tommy", title="Coach Tommy noticed",
                                                   body="Ryder, first session done.", parent_first="Dana",
                                                   link="https://app.0ffdays.com/app/parent.html", unsubscribe="https://x/u")
        mine = text.split("Ryder, first session done.")[0] + text.split("Ryder, first session done.")[1]
        assert " - " not in mine and "\u2014" not in mine and "\u2013" not in mine
        assert not re.search(r"\b(he|she)\b", mine, re.I)

    def test_a_blank_sender_still_reads_properly(self):
        subject, text, _ = message_copy.compose(athlete_first="Ryder", sender="", title="t", body="b", parent_first="",
                                                link="https://l", unsubscribe="")
        assert subject == "What Your coach sent Ryder in 0FFDAYS" and text.startswith("Hi,\n")


class TestTheModuleItselfOnlyCopiesTheseTwoKinds:
    def test_asked_to_copy_anything_else_it_does_nothing(self, program, rec):
        release(program)
        for kind in (N.Kind.STREAK_AT_RISK, N.Kind.BADGE, N.Kind.INACTIVE, N.Kind.ASSIGNMENT_NEW, N.Kind.REST_DAY):
            assert message_copy.email_parents(program["store"].conn, program["ryder"]["id"], kind, "t", "b", "k", "Coach") == []
