"""scripts/login_status.py tells the operator why "Forgot your password?" sent nothing for one address."""
from __future__ import annotations

import dataclasses
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import mailer, staff_mail
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store

spec = importlib.util.spec_from_file_location(
    "login_status", Path(__file__).resolve().parent.parent / "scripts" / "login_status.py")
login_status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(login_status)

E = "joel@example.com"
PW = "a-good-pass-phrase-2026"


class Rec:
    def __init__(self, ok=True):
        self.sent, self.ok = [], ok

    def send(self, to_email, subject, html, text, headers):
        self.sent.append({"to": to_email, "subject": subject, "text": text})
        return mailer.SendResult(ok=self.ok, permanent=False, error="" if self.ok else "provider said no")


@pytest.fixture
def w(tmp_path, monkeypatch):
    patched = dataclasses.replace(CONFIG, smtp_host="smtp.test", app_base_url="https://app.0ffdays.com")
    monkeypatch.setattr(mailer, "CONFIG", patched)
    rec = Rec()
    monkeypatch.setattr(mailer, "default_transport", lambda: rec)
    store = Store(connect(tmp_path / "ls.db"))
    api_module._store = store
    org = store.create_org("Nashville Dogs")
    coach = store.create_user(org, "coach", "Joel White", email=E)
    client = TestClient(api_module.app)
    yield {"store": store, "client": client, "coach": coach, "rec": rec, "org": org, "monkeypatch": monkeypatch}
    api_module._store = None


def set_password(w):
    r = w["client"].put("/api/me/password", json={"email": E, "password": PW},
                        headers={"Authorization": f"Bearer {w['coach']['token']}"})
    assert r.status_code == 200, r.text


def confirm(w):
    w["store"].conn.execute("UPDATE credentials SET email_verified_at = '2026-11-01T00:00:00+00:00'")
    w["store"].conn.commit()


def forgot(w, email=E):
    assert w["client"].post("/api/login/forgot", json={"email": email}).status_code == 200


def why(w, email=E):
    return login_status.findings(w["store"].conn, email)


class TestTheReason:
    def test_nobody_has_the_address(self, w):
        f = why(w, "typo@example.com")
        assert f["login"] is None and "Nobody has this address" in f["why"]

    def test_on_file_but_never_chose_a_password(self, w):
        f = why(w)
        assert "never chose a password" in f["why"] and "Joel White" in f["why"]
        assert "sign-in link" in f["do"]

    def test_chose_a_password_but_never_confirmed_the_address(self, w):
        set_password(w)
        before = len(w["rec"].sent)
        forgot(w)
        assert len(w["rec"].sent) == before, "an unconfirmed address is still not sent a reset link"
        f = why(w)
        assert "never confirmed" in f["why"] and "reset_password.py" in f["do"]

    def test_confirmed_and_sent(self, w):
        set_password(w); confirm(w); forgot(w)
        f = why(w)
        assert "handed to the provider" in f["why"] and "spam" in f["why"]
        assert any("reset" in m["subject"].lower() and m["status"] == "sent" for m in f["mail"])

    def test_confirmed_but_never_asked(self, w):
        set_password(w); confirm(w)
        assert "no reset has been asked for" in why(w)["why"]

    def test_the_provider_refused_it(self, w):
        set_password(w); confirm(w)
        w["rec"].ok = False
        forgot(w)
        f = why(w)
        assert "not delivered" in f["why"] and "provider said no" in f["why"]

    def test_the_address_is_blocked_after_a_bounce(self, w):
        set_password(w); confirm(w)
        mailer.suppress(w["store"].conn, E, "hard bounce: mailbox does not exist")
        forgot(w)
        f = why(w)
        assert "blocked" in f["why"] and "mailbox does not exist" in f["why"]

    def test_asked_too_many_times_in_an_hour(self, w):
        set_password(w); confirm(w)
        for _ in range(staff_mail.HOURLY_LIMIT + 1):
            forgot(w)
        assert "limit" in why(w)["why"]

    def test_removed_from_the_program(self, w):
        set_password(w); confirm(w)
        w["store"].conn.execute("UPDATE users SET active = 0 WHERE id = ?", (w["coach"]["id"],))
        assert "removed" in why(w)["why"]

    def test_no_email_provider(self, w):
        w["monkeypatch"].setattr(mailer, "CONFIG", dataclasses.replace(CONFIG, smtp_host=""))
        assert "no email provider" in why(w)["why"]

    def test_capitals_and_spaces_in_the_address_do_not_matter(self, w):
        set_password(w)
        assert why(w, "  JOEL@Example.com ")["login"]["name"] == "Joel White"


class TestTheScript:
    def test_it_only_reads(self, w):
        set_password(w); confirm(w); forgot(w)
        conn = w["store"].conn
        before = conn.total_changes
        login_status.findings(conn, E)
        assert conn.total_changes == before

    def test_the_report_never_prints_a_link_code_or_password(self, w):
        set_password(w); confirm(w); forgot(w)
        text = login_status.render(why(w))
        link = [m for m in w["rec"].sent if "reset" in m["subject"].lower()][0]["text"]
        token = link.split("reset=")[1].split()[0]
        assert token not in text and PW not in text and w["coach"]["token"] not in text
        assert "Why no link:" in text and "What to do:" in text and "Joel White (coach, Nashville Dogs)" in text

    def test_run_without_an_address_it_explains_itself(self, capsys):
        assert login_status.main(["login_status.py"]) == 2
        assert "podman exec" in capsys.readouterr().out
