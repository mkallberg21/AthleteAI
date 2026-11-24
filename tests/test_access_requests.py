"""An athlete with no working link asks a coach to let them in, and the coach says yes with one tap."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import access_requests as AR
from offdays import guardians, invites, mailer, portability
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store


class Recorder:
    def __init__(self):
        self.sent = []

    def send(self, to_email, subject, html, text, headers, *a, **k):
        self.sent.append({"to": to_email, "subject": subject, "html": html, "text": text})
        return mailer.SendResult(ok=True)


@pytest.fixture
def rec(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(mailer, "default_transport", lambda: r)
    return r


@pytest.fixture
def p(tmp_path, monkeypatch, rec):
    patched = replace(CONFIG, smtp_host="smtp.test", app_base_url="https://app.0ffdays.com")
    for mod in (mailer, invites, guardians):
        if hasattr(mod, "CONFIG"):
            monkeypatch.setattr(mod, "CONFIG", patched)
    monkeypatch.setattr(api_module, "CONFIG", patched)
    store = Store(connect(tmp_path / "ar.db"))
    api_module._store = store
    org = store.create_org("Nashville Dogs")
    director = store.create_user(org, "director", "Matt Kallberg", email="matt@example.com")
    red = store.create_team(org, "2031 Red")
    blue = store.create_team(org, "2032 Blue")
    joel = store.create_user(org, "coach", "Joel White", email="joel@example.com")
    other = store.create_user(org, "coach", "Other Coach", email="other@example.com")
    store.assign_staff_to_team(joel["id"], red["id"])
    store.assign_staff_to_team(other["id"], blue["id"])
    ryder = store.create_user(org, "athlete", "Ryder Cole", birth_year=2013)
    store.join_team(red["join_code"], ryder["id"])
    inv = guardians.create_invite(store.conn, ryder["id"], created_by=director["id"])
    dana = guardians.redeem_invite(store.conn, inv["code"], "Dana Cole", email="dana@example.com")
    guardians.set_consent(store.conn, ryder["id"], dana["guardian_id"], guardians.Scope.PARTICIPATION, True)
    rec.sent.clear()
    yield {"store": store, "org": org, "director": director, "joel": joel, "other": other, "ryder": ryder,
           "dana": dana, "red": red, "client": TestClient(api_module.app), "rec": rec}
    api_module._store = None


def bearer(p, who):
    return {"Authorization": f"Bearer {p[who]['token']}"}


def ask(p, name="Ryder Cole"):
    r = p["client"].post("/api/access/ask", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()


def check(p, secret):
    return p["client"].post("/api/access/check", json={"secret": secret}).json()


def waiting(p, who="joel"):
    return p["client"].get("/api/coach/access-requests", headers=bearer(p, who)).json()["requests"]


def answer(p, rid, what="approve", who="joel"):
    return p["client"].post(f"/api/coach/access-requests/{rid}/{what}", headers=bearer(p, who))


def release(p):
    p["store"].conn.execute("UPDATE organizations SET mail_hold = 0 WHERE id = ?", (p["org"],))
    p["store"].conn.commit()


class TestTheWholeThing:
    def test_ask_one_tap_and_the_phone_is_in(self, p):
        got = ask(p)
        assert check(p, got["secret"]) == {"status": "waiting"}
        reqs = waiting(p)
        assert [(r["name"], r["teams"], r["number"]) for r in reqs] == [("Ryder Cole", ["2031 Red"], got["number"])]
        assert answer(p, reqs[0]["id"]).status_code == 200
        out = check(p, got["secret"])
        assert out["status"] == "approved"
        me = p["client"].get("/api/me", headers={"Authorization": f"Bearer {out['token']}"})
        assert me.status_code == 200 and me.json()["role"] == "athlete" and me.json()["display_name"] == "Ryder Cole"
        assert waiting(p) == []

    def test_the_sign_in_is_handed_over_once(self, p):
        got = ask(p)
        answer(p, waiting(p)[0]["id"])
        assert check(p, got["secret"])["status"] == "approved"
        again = check(p, got["secret"])
        assert again == {"status": "used"}

    def test_the_link_the_parent_sent_keeps_working(self, p):
        got = ask(p)
        answer(p, waiting(p)[0]["id"])
        check(p, got["secret"])
        assert p["client"].get("/api/me", headers=bearer(p, "ryder")).status_code == 200

    def test_capitals_spacing_and_punctuation_in_the_name_do_not_matter(self, p):
        ask(p, "  ryder   COLE ")
        assert len(waiting(p)) == 1

    def test_a_director_can_answer_too(self, p):
        got = ask(p)
        assert answer(p, waiting(p, "director")[0]["id"], who="director").status_code == 200
        assert check(p, got["secret"])["status"] == "approved"

    def test_it_stays_signed_in_for_months(self, p):
        got = ask(p)
        answer(p, waiting(p)[0]["id"])
        check(p, got["secret"])
        exp = p["store"].conn.execute("SELECT expires_at FROM staff_sessions").fetchone()[0]
        days = (datetime.fromisoformat(exp) - datetime.now(timezone.utc)).days
        assert 170 <= days <= 181


class TestNobodyGetsInByAsking:
    def test_no_answer_means_no_sign_in(self, p):
        got = ask(p)
        for _ in range(3):
            assert check(p, got["secret"]) == {"status": "waiting"}
        assert p["store"].conn.execute("SELECT COUNT(*) FROM staff_sessions").fetchone()[0] == 0

    def test_no_closes_it(self, p):
        got = ask(p)
        assert answer(p, waiting(p)[0]["id"], "deny").status_code == 200
        assert check(p, got["secret"]) == {"status": "denied"}
        assert waiting(p) == []

    def test_a_guessed_secret_gets_nothing(self, p):
        ask(p)
        answer(p, waiting(p)[0]["id"])
        assert check(p, "not-the-secret") == {"status": "waiting"}

    def test_a_coach_of_another_team_neither_sees_nor_answers_it(self, p):
        got = ask(p)
        rid = waiting(p)[0]["id"]
        assert waiting(p, "other") == []
        assert answer(p, rid, who="other").status_code == 409
        assert check(p, got["secret"]) == {"status": "waiting"}

    def test_another_program_cannot_answer_it(self, p):
        s = p["store"]
        org2 = s.create_org("Rival Club")
        rival = s.create_user(org2, "director", "Rival Director")
        got = ask(p)
        rid = waiting(p)[0]["id"]
        r = p["client"].post(f"/api/coach/access-requests/{rid}/approve",
                             headers={"Authorization": f"Bearer {rival['token']}"})
        assert r.status_code == 409 and check(p, got["secret"]) == {"status": "waiting"}

    def test_an_athlete_or_parent_cannot_answer_it(self, p):
        ask(p)
        rid = waiting(p)[0]["id"]
        assert answer(p, rid, who="ryder").status_code == 403
        assert answer(p, rid, who="dana").status_code == 403

    def test_answering_twice_does_nothing_the_second_time(self, p):
        ask(p)
        rid = waiting(p)[0]["id"]
        assert answer(p, rid).status_code == 200
        assert answer(p, rid).status_code == 409

    def test_a_request_lapses_after_three_days(self, p):
        got = ask(p)
        rid = waiting(p)[0]["id"]
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
        p["store"].conn.execute("UPDATE access_requests SET expires_at = ?", (past,))
        assert waiting(p) == []
        assert answer(p, rid).status_code == 409
        assert check(p, got["secret"]) == {"status": "expired"}

    def test_no_parent_consent_means_no_request_at_all(self, p):
        s = p["store"]
        kid = s.create_user(p["org"], "athlete", "Sam Nokey", birth_year=2013)
        s.join_team(p["red"]["join_code"], kid["id"])
        ask(p, "Sam Nokey")
        assert waiting(p) == []

    def test_consent_withdrawn_while_waiting_cannot_be_approved(self, p):
        got = ask(p)
        guardians.set_consent(p["store"].conn, p["ryder"]["id"], p["dana"]["guardian_id"], guardians.Scope.PARTICIPATION, False)
        assert answer(p, waiting(p)[0]["id"]).status_code == 409
        assert check(p, got["secret"]) == {"status": "waiting"}

    def test_a_removed_athlete_is_not_let_in(self, p):
        got = ask(p)
        rid = waiting(p)[0]["id"]
        p["store"].conn.execute("UPDATE users SET active = 0 WHERE id = ?", (p["ryder"]["id"],))
        assert waiting(p) == [] and answer(p, rid).status_code == 409
        assert check(p, got["secret"]) == {"status": "waiting"}


class TestItDoesNotSayWhoIsOnATeam:
    def test_a_stranger_gets_the_same_answer_and_the_same_waiting(self, p):
        known, stranger = ask(p), ask(p, "Nobody Atall")
        assert set(known) == set(stranger) and known["message"] == stranger["message"]
        assert len(stranger["number"]) == 2 and stranger["number"].isdigit()
        assert check(p, stranger["secret"]) == check(p, known["secret"]) == {"status": "waiting"}
        assert len(waiting(p)) == 1

    def test_a_name_nobody_matched_is_not_kept(self, p):
        ask(p, "Nobody Atall")
        assert [r[0] for r in p["store"].conn.execute("SELECT typed_name FROM access_requests")] == [""]

    def test_a_first_name_alone_matches_nobody(self, p):
        ask(p, "Ryder")
        assert waiting(p) == []

    def test_only_hashes_of_the_secret_and_the_sign_in_are_kept(self, p):
        got = ask(p)
        answer(p, waiting(p)[0]["id"])
        token = check(p, got["secret"])["token"]
        dump = " ".join(str(tuple(r)) for t in ("access_requests", "staff_sessions")
                        for r in p["store"].conn.execute(f"SELECT * FROM {t}"))
        assert got["secret"] not in dump and token not in dump

    def test_it_is_never_in_a_program_export(self, p):
        assert "access_requests" not in portability.SOURCE_TABLES


class TestLimits:
    def test_one_athlete_can_have_three_requests_waiting(self, p):
        for _ in range(5):
            ask(p)
        assert len(waiting(p)) == AR.PER_ATHLETE_PENDING

    def test_one_network_cannot_ask_without_end(self, p, monkeypatch):
        monkeypatch.setattr(AR, "PER_SOURCE_HOURLY", 2)
        ask(p, "Nobody One"); ask(p, "Nobody Two")
        ask(p)
        assert waiting(p) == []

    def test_a_blank_name_is_refused(self, p):
        assert p["client"].post("/api/access/ask", json={"name": " "}).status_code == 400


class TestTwoWithTheSameName:
    def test_whichever_coach_says_yes_the_other_request_closes(self, p):
        s = p["store"]
        org2 = s.create_org("Rival Club")
        d2 = s.create_user(org2, "director", "Rival Director")
        twin = s.create_user(org2, "athlete", "Ryder Cole", birth_year=2012)
        g = guardians.redeem_invite(s.conn, guardians.create_invite(s.conn, twin["id"], created_by=d2["id"])["code"],
                                    "Twin Parent", email="twin@example.com")
        guardians.set_consent(s.conn, twin["id"], g["guardian_id"], guardians.Scope.PARTICIPATION, True)
        got = ask(p)
        theirs = p["client"].get("/api/coach/access-requests",
                                 headers={"Authorization": f"Bearer {d2['token']}"}).json()["requests"]
        assert len(theirs) == 1 and len(waiting(p)) == 1 and theirs[0]["number"] == waiting(p)[0]["number"]
        answer(p, waiting(p)[0]["id"])
        assert p["client"].get("/api/coach/access-requests",
                               headers={"Authorization": f"Bearer {d2['token']}"}).json()["requests"] == []
        out = check(p, got["secret"])
        assert out["status"] == "approved"
        assert [r[0] for r in s.conn.execute("SELECT user_id FROM staff_sessions")] == [p["ryder"]["id"]]


class TestWhoIsTold:
    def test_the_athletes_coach_and_the_director_are_emailed_and_nobody_else(self, p, rec):
        got = ask(p)
        told = sorted(m["to"] for m in rec.sent)
        assert told == ["joel@example.com", "matt@example.com"]
        m = rec.sent[0]
        assert m["subject"] == "Nashville Dogs: Ryder Cole is asking to be let in to 0FFDAYS"
        assert "2031 Red" in m["text"] and f"number on their screen is {got['number']}" in m["text"]
        assert '<a href="https://app.0ffdays.com/app/coach.html"' in m["html"], "the dashboard link is a hyperlink"
        assert got["secret"] not in m["text"] + m["html"]

    def test_the_email_cannot_let_anyone_in_by_itself(self, p, rec):
        """A mail scanner opens every link in an email. The only link is the dashboard, which needs a sign-in."""
        ask(p)
        import re
        links = set(re.findall(r'href="([^"]+)"', rec.sent[0]["html"]))
        assert links == {"https://app.0ffdays.com/app/coach.html"}

    def test_asking_again_does_not_email_the_coach_again(self, p, rec):
        ask(p); ask(p); ask(p)
        assert len([m for m in rec.sent if m["to"] == "joel@example.com"]) == 1

    def test_staff_are_told_even_while_the_parents_email_is_on_hold(self, p, rec):
        assert mailer.mail_held(p["store"].conn, p["org"])
        ask(p)
        assert len(rec.sent) == 2

    def test_a_stranger_asking_emails_nobody(self, p, rec):
        ask(p, "Nobody Atall")
        assert rec.sent == []

    def test_the_parent_is_told_when_a_coach_says_yes(self, p, rec):
        release(p)
        ask(p)
        rec.sent.clear()
        answer(p, waiting(p)[0]["id"])
        assert [m["to"] for m in rec.sent] == ["dana@example.com"]
        m = rec.sent[0]
        assert m["subject"] == "Joel White let Ryder sign in to 0FFDAYS on a new device"
        assert "make a new sign-in link" in m["text"]
        assert '<a href="https://app.0ffdays.com/app/parent.html"' in m["html"]

    def test_the_parent_is_not_emailed_while_the_hold_is_on(self, p, rec):
        ask(p)
        rec.sent.clear()
        answer(p, waiting(p)[0]["id"])
        assert rec.sent == []

    def test_a_no_tells_the_parent_nothing(self, p, rec):
        release(p)
        ask(p)
        rec.sent.clear()
        answer(p, waiting(p)[0]["id"], "deny")
        assert rec.sent == []

    @pytest.mark.parametrize("made", [
        AR.compose_staff(athlete="Ryder Cole", teams=["2031 Red"], org_name="Nashville Dogs", number="47", link="L"),
        AR.compose_parent(child="Ryder", coach="Joel White", parent_first="Dana", link="L"),
    ])
    def test_the_words_follow_the_house_rules(self, made):
        import re
        text = " ".join(made[:2])
        assert "\u2014" not in text and "\u2013" not in text and " - " not in text
        assert not re.search(r"\b(he|she|his|her|him)\b", text, re.I)


class TestTheParentsOffSwitch:
    def test_a_new_link_from_the_parent_signs_out_the_phone_a_coach_let_in(self, p):
        got = ask(p)
        answer(p, waiting(p)[0]["id"])
        token = check(p, got["secret"])["token"]
        hdr = {"Authorization": f"Bearer {token}"}
        assert p["client"].get("/api/me", headers=hdr).status_code == 200
        guardians.athlete_signin_link(p["store"].conn, p["dana"]["guardian_id"], p["ryder"]["id"])
        assert p["client"].get("/api/me", headers=hdr).status_code == 401

    def test_a_new_link_also_closes_a_request_still_waiting(self, p):
        got = ask(p)
        guardians.athlete_signin_link(p["store"].conn, p["dana"]["guardian_id"], p["ryder"]["id"])
        assert waiting(p) == []
        assert check(p, got["secret"]) == {"status": "denied"}

    def test_a_yes_not_yet_collected_is_cancelled_by_a_new_link(self, p):
        got = ask(p)
        answer(p, waiting(p)[0]["id"])
        guardians.athlete_signin_link(p["store"].conn, p["dana"]["guardian_id"], p["ryder"]["id"])
        assert check(p, got["secret"])["status"] == "denied"
