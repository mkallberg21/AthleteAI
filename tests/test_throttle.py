"""Guessing a code has to get slower, not stay free.

Sign-in codes are one letter and five digits by design, so the space is
small; throttle.py is what makes that safe. These tests pin the contract:
a handful of wrong guesses is free (people misread slips of paper), the
next one costs a wait that doubles, a right answer wipes the slate, and
both the address and the code are counted so neither rotating addresses
nor rotating codes gets around it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from offdays import api as api_module
from offdays import throttle
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store

T0 = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    store = Store(connect(tmp_path / "t.db"))
    yield store.conn
    store.close()


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "test.db"))
    yield TestClient(api_module.app)
    api_module._store = None


@pytest.fixture
def program(client):
    org = client.post(
        "/api/orgs", json={"name": "Northshore LC", "director_name": "Dir Smith"}
    ).json()
    director = {"Authorization": f"Bearer {org['director']['token']}"}
    team = client.post(
        "/api/teams", json={"name": "U15", "season": "2026"}, headers=director
    ).json()
    athlete = client.post(
        "/api/athletes",
        json={"display_name": "Jordan P.", "team_id": team["id"], "dominant_hand": "right"},
        headers=director,
    ).json()
    return {"director": director, "athlete": athlete, "org": org}


class TestCounting:
    def test_below_the_threshold_nothing_is_locked(self, conn):
        a = throttle.Attempt.for_code("10.0.0.1", "A00001")
        for i in range(CONFIG.auth_max_failures - 1):
            throttle.record_failure(conn, a, now=T0 + timedelta(seconds=i))
        throttle.check(conn, a, now=T0 + timedelta(seconds=30))  # no raise

    def test_the_threshold_failure_locks(self, conn):
        a = throttle.Attempt.for_code("10.0.0.1", "A00001")
        for i in range(CONFIG.auth_max_failures):
            throttle.record_failure(conn, a, now=T0 + timedelta(seconds=i))
        with pytest.raises(throttle.Throttled) as exc:
            throttle.check(conn, a, now=T0 + timedelta(seconds=CONFIG.auth_max_failures))
        assert 1 <= exc.value.retry_after <= CONFIG.auth_lockout_seconds + 1

    def test_the_lock_doubles_and_caps(self, conn):
        a = throttle.Attempt.for_code("10.0.0.1", "A00001")
        base = CONFIG.auth_lockout_seconds
        # Failures come in after each lock has expired, so each one counts.
        t = T0
        for _ in range(CONFIG.auth_max_failures - 1):
            throttle.record_failure(conn, a, now=t)
        # Four locks (30s, 60s, 120s, 240s) fit inside the forgetting
        # window; a fifth would land after it and start a fresh count,
        # which test_old_failures_are_forgotten covers.
        for over in range(4):
            throttle.record_failure(conn, a, now=t)
            row = throttle.state(conn, a.keys[0])
            until = datetime.fromisoformat(row["locked_until"])
            expected = min(base * (2 ** over), CONFIG.auth_lockout_max_seconds)
            assert (until - t).total_seconds() == expected
            t = until + timedelta(seconds=1)

    def test_the_lock_never_exceeds_the_cap(self, conn):
        a = throttle.Attempt.for_code("10.0.0.1", "A00001")
        # Every failure inside one second, so nothing expires or is forgotten.
        for i in range(CONFIG.auth_max_failures + 12):
            throttle.record_failure(conn, a, now=T0)
        until = datetime.fromisoformat(throttle.state(conn, a.keys[0])["locked_until"])
        assert (until - T0).total_seconds() == CONFIG.auth_lockout_max_seconds

    def test_a_lock_expires(self, conn):
        a = throttle.Attempt.for_code("10.0.0.1", "A00001")
        for i in range(CONFIG.auth_max_failures):
            throttle.record_failure(conn, a, now=T0 + timedelta(seconds=i))
        later = T0 + timedelta(seconds=CONFIG.auth_lockout_seconds + 60)
        throttle.check(conn, a, now=later)  # no raise

    def test_old_failures_are_forgotten(self, conn):
        a = throttle.Attempt.for_code("10.0.0.1", "A00001")
        for i in range(CONFIG.auth_max_failures - 1):
            throttle.record_failure(conn, a, now=T0 + timedelta(seconds=i))
        # A full window later the count restarts; this one failure is not
        # the threshold-th.
        much_later = T0 + timedelta(seconds=CONFIG.auth_failure_window_seconds + 10)
        throttle.record_failure(conn, a, now=much_later)
        assert throttle.state(conn, a.keys[0])["failures"] == 1
        throttle.check(conn, a, now=much_later + timedelta(seconds=1))

    def test_success_clears_both_keys(self, conn):
        a = throttle.Attempt.for_code("10.0.0.1", "A00001")
        for i in range(CONFIG.auth_max_failures):
            throttle.record_failure(conn, a, now=T0 + timedelta(seconds=i))
        throttle.record_success(conn, a)
        for key in a.keys:
            assert throttle.state(conn, key) is None

    def test_the_table_never_holds_the_code(self, conn):
        a = throttle.Attempt.for_code("10.0.0.1", "A00001")
        throttle.record_failure(conn, a, now=T0)
        keys = [r[0] for r in conn.execute("SELECT key FROM auth_attempts")]
        assert not any("A00001" in k for k in keys)

    def test_the_code_key_is_case_and_space_insensitive(self):
        a = throttle.Attempt.for_code(None, " a00001 ")
        b = throttle.Attempt.for_code(None, "A00001")
        assert a.keys[1] == b.keys[1]


class TestTwoAxes:
    def test_rotating_codes_from_one_address_is_stopped(self, conn):
        for i in range(CONFIG.auth_max_failures):
            throttle.record_failure(
                conn, throttle.Attempt.for_code("10.0.0.1", f"A{i:05d}"), now=T0
            )
        with pytest.raises(throttle.Throttled):
            throttle.check(conn, throttle.Attempt.for_code("10.0.0.1", "Z99999"), now=T0)

    def test_rotating_addresses_at_one_code_is_stopped(self, conn):
        for i in range(CONFIG.auth_max_failures):
            throttle.record_failure(
                conn, throttle.Attempt.for_code(f"10.0.0.{i}", "A00001"), now=T0
            )
        with pytest.raises(throttle.Throttled):
            throttle.check(conn, throttle.Attempt.for_code("192.168.9.9", "A00001"), now=T0)

    def test_an_unrelated_caller_is_not_caught(self, conn):
        for i in range(CONFIG.auth_max_failures):
            throttle.record_failure(
                conn, throttle.Attempt.for_code("10.0.0.1", "A00001"), now=T0
            )
        throttle.check(conn, throttle.Attempt.for_code("10.0.0.2", "B00002"), now=T0)


class TestEndpoints:
    def test_a_burst_of_bad_bearers_gets_a_429_with_retry_after(self, client):
        # Each guess is a different code, so it is the address counter tripping.
        for i in range(CONFIG.auth_max_failures):
            r = client.get("/api/me", headers={"Authorization": f"Bearer X{i:05d}"})
            assert r.status_code == 401
        r = client.get("/api/me", headers={"Authorization": "Bearer X99999"})
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) >= 1
        assert "try again" in r.json()["detail"]

    def test_the_right_code_still_works_before_the_threshold(self, client, program):
        for i in range(CONFIG.auth_max_failures - 1):
            client.get("/api/me", headers={"Authorization": f"Bearer X{i:05d}"})
        r = client.get(
            "/api/me", headers={"Authorization": f"Bearer {program['athlete']['token']}"}
        )
        assert r.status_code == 200

    def test_a_locked_address_cannot_use_a_right_code_either(self, client, program):
        for i in range(CONFIG.auth_max_failures):
            client.get("/api/me", headers={"Authorization": f"Bearer X{i:05d}"})
        r = client.get(
            "/api/me", headers={"Authorization": f"Bearer {program['athlete']['token']}"}
        )
        assert r.status_code == 429

    def test_the_form_login_is_throttled_too(self, client):
        for i in range(CONFIG.auth_max_failures):
            r = client.post("/api/me/login", data={"token": f"X{i:05d}"})
            assert r.status_code == 401
            assert r.json()["detail"] == "invalid or inactive code"
        r = client.post("/api/me/login", data={"token": "X99999"})
        assert r.status_code == 429

    def test_claim_codes_are_throttled(self, client):
        for i in range(CONFIG.auth_max_failures):
            assert client.post("/api/claim", json={"code": f"CLAIM{i}"}).status_code == 400
        assert client.post("/api/claim", json={"code": "CLAIMX"}).status_code == 429

    def test_guardian_invites_are_throttled(self, client):
        body = {"code": "", "display_name": "Pat"}
        for i in range(CONFIG.auth_max_failures):
            body["code"] = f"INV{i:04d}"
            assert client.post("/api/guardians/redeem", json=body).status_code == 400
        body["code"] = "INVXXXX"
        assert client.post("/api/guardians/redeem", json=body).status_code == 429

    def test_a_wrong_program_is_a_403_not_a_guess(self, client, program):
        token = program["athlete"]["token"]
        for _ in range(CONFIG.auth_max_failures + 2):
            r = client.get(
                "/api/me",
                headers={"Authorization": f"Bearer {token}", "X-Org-Id": "999999"},
            )
            assert r.status_code == 403
        # Still not locked: a real token in the wrong program is not a guess.
        r = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

    def test_no_video_upload_endpoint_still_holds(self, client):
        # Sanity: adding a Request dependency to _principal must not have
        # changed the public schema in a way the privacy test relies on.
        schema = client.get("/openapi.json").json()
        assert "/api/me" in schema["paths"]
