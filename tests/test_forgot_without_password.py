"""'Forgot your password?' from someone the program added who never chose a password.

They have nothing to reset, and used to get silence behind "Check your email". Now the address on file is sent the
link to choose a password, which signs them in.
"""
from __future__ import annotations

import dataclasses
import re

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import mailer
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store

D = "matt@example.com"
PW = "a-good-pass-phrase-2026"


class Rec:
    def __init__(self):
        self.sent = []

    def send(self, to_email, subject, html, text, headers, *a, **k):
        self.sent.append({"to": to_email, "subject": subject, "text": text, "html": html})
        return mailer.SendResult(ok=True)


@pytest.fixture
def w(tmp_path, monkeypatch):
    monkeypatch.setattr(mailer, "CONFIG", dataclasses.replace(CONFIG, smtp_host="smtp.test",
                                                              app_base_url="https://app.0ffdays.com"))
    rec = Rec()
    monkeypatch.setattr(mailer, "default_transport", lambda: rec)
    store = Store(connect(tmp_path / "fw.db"))
    api_module._store = store
    org = store.create_org("Nashville Dogs")
    director = store.create_user(org, "director", "Matt Kallberg", email=D)
    yield {"store": store, "client": TestClient(api_module.app), "rec": rec, "org": org, "director": director}
    api_module._store = None


def forgot(w, email):
    r = w["client"].post("/api/login/forgot", json={"email": email})
    assert r.status_code == 200
    return r.json()


def test_a_director_with_no_password_is_sent_a_link_to_choose_one(w):
    forgot(w, D)
    assert [m["to"] for m in w["rec"].sent] == [D]
    mail = w["rec"].sent[0]
    token = re.search(r"\?create=([A-Za-z0-9_\-]+)", mail["text"]).group(1)
    assert f'href="https://app.0ffdays.com/app/index.html?create={token}"' in mail["html"], "the link is a hyperlink"
    done = w["client"].post("/api/login/create-finish", json={"token": token, "password": PW})
    assert done.status_code in (200, 201), done.text
    assert w["client"].post("/api/login/password", json={"email": D, "password": PW}).status_code == 200


def test_capitals_in_the_typed_address_do_not_matter(w):
    forgot(w, "  Matt@Example.com ")
    assert len(w["rec"].sent) == 1


def test_the_answer_is_the_same_for_a_stranger_and_nothing_is_sent(w):
    known = forgot(w, D)
    stranger = forgot(w, "nobody@example.com")
    assert known == stranger
    assert [m["to"] for m in w["rec"].sent] == [D]


def test_someone_with_a_password_gets_the_reset_link_only(w):
    forgot(w, D)
    token = re.search(r"\?create=([A-Za-z0-9_\-]+)", w["rec"].sent[0]["text"]).group(1)
    w["client"].post("/api/login/create-finish", json={"token": token, "password": PW})
    w["rec"].sent.clear()
    forgot(w, D)
    subjects = [m["subject"] for m in w["rec"].sent]
    assert len(subjects) == 1 and "reset" in subjects[0].lower(), subjects


def test_a_removed_coach_is_sent_nothing(w):
    coach = w["store"].create_user(w["org"], "coach", "Gone Coach", email="gone@example.com")
    w["store"].conn.execute("UPDATE users SET active = 0 WHERE id = ?", (coach["id"],))
    w["store"].conn.commit()
    forgot(w, "gone@example.com")
    assert w["rec"].sent == []


def test_asking_over_and_over_does_not_flood_the_mailbox(w):
    for _ in range(6):
        w["client"].post("/api/login/forgot", json={"email": D})
    assert len(w["rec"].sent) <= 3
