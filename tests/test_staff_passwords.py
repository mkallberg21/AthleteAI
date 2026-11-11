"""Coaches and directors can sign in with an email and a password they choose.

The six-character code stays as a backup. Parents and athletes are untouched.

There is no email service on this server, so a forgotten password is recovered
three ways, none of which sends mail: the recovery code shown once when the
password is set, a one-time reset code a director hands to a coach, or a reset
the operator runs on the server. Nothing here emails anyone.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import offdays.api as api_module
from offdays.config import CONFIG
from tests.test_api import client, program  # noqa: F401  (fixtures)

EMAIL = "joel@nashvilledogs.example"
GOOD = "correct-horse-battery"


def _db():
    return api_module._store.conn


def _set(client, headers, email=EMAIL, password=GOOD, **extra):
    return client.put("/api/me/password", json={"email": email, "password": password, **extra},
                      headers=headers)


def _login(client, email=EMAIL, password=GOOD):
    return client.post("/api/login/password", json={"email": email, "password": password})


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


class TestSettingOne:
    def test_a_director_can_set_one_and_gets_a_recovery_code(self, client, program):
        res = _set(client, program["director"])
        assert res.status_code == 200, res.text
        code = res.json()["recovery_code"]
        assert len(code.replace("-", "")) == 12 and code.count("-") == 2

    def test_it_reports_that_one_is_set(self, client, program):
        assert client.get("/api/me/password", headers=program["director"]).json()["set"] is False
        _set(client, program["director"])
        body = client.get("/api/me/password", headers=program["director"]).json()
        assert body["set"] is True and body["email"] == EMAIL

    @pytest.mark.parametrize("bad", ["short1", "password12345", "aaaaaaaaaaaa", "joel@nashvilledogs"])
    def test_a_weak_password_is_refused_with_a_reason(self, client, program, bad):
        res = _set(client, program["director"], password=bad)
        assert res.status_code == 400
        assert res.json()["detail"]

    def test_an_athlete_cannot_set_one(self, client, program):
        res = _set(client, program["athletes"][0]["headers"])
        assert res.status_code in (401, 403)

    def test_an_email_already_used_by_someone_else_is_refused(self, client, program):
        _set(client, program["director"])
        coach = api_module._store.create_user(program["org"]["org_id"], "coach", "Coach Two")
        res = _set(client, _bearer(coach["token"]))
        assert res.status_code == 400

    def test_changing_it_needs_the_current_one(self, client, program):
        _set(client, program["director"])
        res = _set(client, program["director"], password="a-brand-new-passphrase")
        assert res.status_code in (400, 401, 403)
        ok = client.put("/api/me/password", headers=program["director"], json={
            "password": "a-brand-new-passphrase", "current_password": GOOD})
        assert ok.status_code == 200
        assert _login(client, password="a-brand-new-passphrase").status_code == 200
        assert _login(client).status_code == 401


class TestSigningIn:
    def test_the_right_email_and_password_sign_in(self, client, program):
        _set(client, program["director"])
        res = _login(client)
        assert res.status_code == 200
        body = res.json()
        assert body["role"] == "director" and body["token"]

    def test_the_session_token_works_everywhere_a_code_does(self, client, program):
        _set(client, program["director"])
        token = _login(client).json()["token"]
        res = client.get("/api/coach/roster", headers=_bearer(token))
        assert res.status_code == 200

    def test_email_is_not_case_sensitive(self, client, program):
        _set(client, program["director"])
        assert _login(client, email=EMAIL.upper()).status_code == 200

    def test_a_wrong_password_and_an_unknown_email_look_the_same(self, client, program):
        _set(client, program["director"])
        wrong = _login(client, password="not-the-password-1")
        unknown = _login(client, email="nobody@nowhere.example")
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()

    def test_the_six_character_code_still_works(self, client, program):
        _set(client, program["director"])
        code = program["org"]["director"]["token"]
        res = client.post("/api/me/login", data={"token": code})
        assert res.status_code == 200

    def test_guessing_is_slowed_down(self, client, program):
        _set(client, program["director"])
        seen = [_login(client, password=f"wrong-guess-{i}-xx").status_code
                for i in range(CONFIG.auth_max_failures + 2)]
        assert 429 in seen
        # and the right password is refused while locked, not just the wrong ones
        assert _login(client).status_code == 429

    def test_an_expired_session_is_refused(self, client, program):
        _set(client, program["director"])
        token = _login(client).json()["token"]
        _db().execute("UPDATE staff_sessions SET expires_at = ?",
                      ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),))
        _db().commit()
        assert client.get("/api/coach/roster", headers=_bearer(token)).status_code == 401

    def test_a_parent_or_athlete_cannot_sign_in_this_way(self, client, program):
        _set(client, program["director"])
        athlete = program["athletes"][0]
        res = _login(client, email="kid@example.com", password=GOOD)
        assert res.status_code == 401
        assert athlete["token"]  # their code is the only door


class TestWhatIsStored:
    def test_the_password_is_never_stored(self, client, program):
        _set(client, program["director"])
        row = _db().execute("SELECT * FROM credentials").fetchone()
        assert GOOD not in " ".join(str(v) for v in dict(row).values())
        assert row["pw_hash"].startswith("scrypt$")

    def test_the_recovery_code_and_sessions_are_stored_hashed(self, client, program):
        recovery = _set(client, program["director"]).json()["recovery_code"]
        token = _login(client).json()["token"]
        row = dict(_db().execute("SELECT * FROM credentials").fetchone())
        sess = dict(_db().execute("SELECT * FROM staff_sessions").fetchone())
        assert recovery not in " ".join(str(v) for v in row.values())
        assert token not in " ".join(str(v) for v in sess.values())

    def test_none_of_it_is_in_a_program_export(self):
        from offdays import portability
        assert "credentials" not in portability.SOURCE_TABLES
        assert "staff_sessions" not in portability.SOURCE_TABLES


class TestForgotten:
    def _reset(self, client, code, new="a-fresh-passphrase-9", email=EMAIL):
        return client.post("/api/login/reset",
                           json={"email": email, "code": code, "new_password": new})

    def test_the_recovery_code_sets_a_new_password(self, client, program):
        recovery = _set(client, program["director"]).json()["recovery_code"]
        res = self._reset(client, recovery)
        assert res.status_code == 200, res.text
        assert _login(client, password="a-fresh-passphrase-9").status_code == 200
        assert _login(client).status_code == 401          # the old one is gone

    def test_a_used_recovery_code_is_replaced_by_a_new_one(self, client, program):
        recovery = _set(client, program["director"]).json()["recovery_code"]
        fresh = self._reset(client, recovery).json()["recovery_code"]
        assert fresh != recovery
        assert self._reset(client, recovery, new="yet-another-pass-77").status_code == 401
        assert self._reset(client, fresh, new="yet-another-pass-77").status_code == 200

    def test_a_reset_signs_out_every_session(self, client, program):
        recovery = _set(client, program["director"]).json()["recovery_code"]
        token = _login(client).json()["token"]
        self._reset(client, recovery)
        assert client.get("/api/coach/roster", headers=_bearer(token)).status_code == 401

    def test_a_reset_leaves_the_six_character_code_working(self, client, program):
        recovery = _set(client, program["director"]).json()["recovery_code"]
        self._reset(client, recovery)
        code = program["org"]["director"]["token"]
        assert client.post("/api/me/login", data={"token": code}).status_code == 200

    def test_a_wrong_code_is_refused_and_slowed(self, client, program):
        _set(client, program["director"])
        seen = [self._reset(client, f"AAAA-BBBB-{i:04d}").status_code
                for i in range(CONFIG.auth_max_failures + 2)]
        assert seen[0] == 401 and 429 in seen

    def test_a_weak_new_password_is_refused_and_the_code_is_not_spent(self, client, program):
        recovery = _set(client, program["director"]).json()["recovery_code"]
        assert self._reset(client, recovery, new="short").status_code == 400
        assert self._reset(client, recovery).status_code == 200

    def test_a_recovery_code_does_not_work_for_another_email(self, client, program):
        recovery = _set(client, program["director"]).json()["recovery_code"]
        assert self._reset(client, recovery, email="someone@else.example").status_code == 401


class TestADirectorHelpsACoach:
    def _coach(self, client, program, email="coach.sam@example.com"):
        coach = api_module._store.create_user(program["org"]["org_id"], "coach", "Coach Sam")
        _set(client, _bearer(coach["token"]), email=email, password="coach-sam-passphrase")
        return coach

    def _issue(self, client, program, coach_id, headers=None):
        return client.post(f"/api/coach/staff/{coach_id}/reset-code",
                           headers=headers or program["director"])

    def test_the_director_gets_a_one_time_code_to_hand_over(self, client, program):
        coach = self._coach(client, program)
        res = self._issue(client, program, coach["id"])
        assert res.status_code == 200, res.text
        code = res.json()["reset_code"]
        done = client.post("/api/login/reset", json={
            "email": "coach.sam@example.com", "code": code, "new_password": "sams-new-passphrase"})
        assert done.status_code == 200
        assert _login(client, "coach.sam@example.com", "sams-new-passphrase").status_code == 200

    def test_it_works_once(self, client, program):
        coach = self._coach(client, program)
        code = self._issue(client, program, coach["id"]).json()["reset_code"]
        body = {"email": "coach.sam@example.com", "code": code, "new_password": "sams-new-passphrase"}
        assert client.post("/api/login/reset", json=body).status_code == 200
        body["new_password"] = "a-second-attempt-pass"
        assert client.post("/api/login/reset", json=body).status_code == 401

    def test_it_expires(self, client, program):
        coach = self._coach(client, program)
        code = self._issue(client, program, coach["id"]).json()["reset_code"]
        _db().execute("UPDATE credentials SET reset_expires = ?",
                      ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),))
        _db().commit()
        res = client.post("/api/login/reset", json={
            "email": "coach.sam@example.com", "code": code, "new_password": "sams-new-passphrase"})
        assert res.status_code == 401

    def test_a_coach_cannot_issue_one(self, client, program):
        coach = self._coach(client, program)
        other = api_module._store.create_user(program["org"]["org_id"], "coach", "Coach Other")
        res = self._issue(client, program, coach["id"], headers=_bearer(other["token"]))
        assert res.status_code in (401, 403)

    def test_a_director_cannot_reach_another_program(self, client, program):
        rival = client.post("/api/orgs", json={"name": "Rival", "accept_terms": True, "director_name": "R"}).json()
        coach = self._coach(client, program)
        res = self._issue(client, program, coach["id"],
                          headers=_bearer(rival["director"]["token"]))
        assert res.status_code in (403, 404)

    def test_a_coach_with_no_password_is_told_to_use_their_code(self, client, program):
        coach = api_module._store.create_user(program["org"]["org_id"], "coach", "No Password")
        res = self._issue(client, program, coach["id"])
        assert res.status_code == 409
        assert "code" in res.json()["detail"].lower()


class TestNothingIsEmailed:
    def test_no_step_writes_to_the_outbox(self, client, program):
        before = _db().execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0]
        recovery = _set(client, program["director"]).json()["recovery_code"]
        _login(client)
        client.post("/api/login/reset", json={"email": EMAIL, "code": recovery,
                                              "new_password": "a-fresh-passphrase-9"})
        after = _db().execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0]
        assert after == before


class TestItGoesWithTheAccount:
    def test_deleting_the_account_deletes_the_credentials_and_sessions(self, client, program):
        _set(client, program["director"])
        _login(client)
        uid = _db().execute("SELECT user_id FROM credentials").fetchone()[0]
        assert _db().execute("SELECT COUNT(*) FROM staff_sessions").fetchone()[0] == 1
        _db().execute("PRAGMA foreign_keys = ON")
        _db().execute("DELETE FROM users WHERE id = ?", (uid,))
        _db().commit()
        assert _db().execute("SELECT COUNT(*) FROM credentials").fetchone()[0] == 0
        assert _db().execute("SELECT COUNT(*) FROM staff_sessions").fetchone()[0] == 0

    def test_a_deactivated_staff_member_cannot_sign_in(self, client, program):
        _set(client, program["director"])
        uid = _db().execute("SELECT user_id FROM credentials").fetchone()[0]
        _db().execute("UPDATE users SET active = 0 WHERE id = ?", (uid,))
        _db().commit()
        assert _login(client).status_code == 401
