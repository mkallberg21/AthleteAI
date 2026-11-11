"""The family funnel: which family is stuck where, and whom to nudge.

A director who uploaded forty families and sees twelve training needs the
other twenty-eight sorted by whose move it is. Each test walks one family
one step further along the real chain (roster contact -> invite -> parent
signs up -> consent -> link to the kid -> kid signs in -> kid trains) and
checks the stage the dashboard would show.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import contacts as C
from offdays import funnel as F
from offdays import guardians as G
from offdays import invites
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store


@pytest.fixture(autouse=True)
def smtp_on(monkeypatch):
    """Email "goes out" only when SMTP is configured; these tests assert it does."""
    from dataclasses import replace
    patched = replace(CONFIG, smtp_host="smtp.test")
    monkeypatch.setattr(invites, "CONFIG", patched)
    from offdays import mailer
    monkeypatch.setattr(mailer, "CONFIG", patched)
    monkeypatch.setattr(mailer, "mail_held", lambda conn, org_id: False)


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "f.db"))


@pytest.fixture
def client_with(store):
    api_module._store = store
    yield TestClient(api_module.app), store
    api_module._store = None


def submit_reps(client, headers, drill_key, reps):
    import random
    s = client.post("/api/sessions/start", json={"drill_key": drill_key}, headers=headers)
    assert s.status_code == 201, s.text
    s = s.json()
    rng, t, events = random.Random(reps), 0, []
    for i in range(reps):
        t += max(150, int(rng.gauss(880, 190)))
        events.append({"t_ms": t, "hand": "left" if i % 2 else "right", "confidence": 0.88})
    r = client.post("/api/sessions/submit", headers=headers, json={
        "session_id": s["session_id"], "nonce": s["nonce"],
        "duration_ms": t + 700, "reps": events, "mean_confidence": 0.88})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def program(store):
    org = store.create_org("Mad Dog Lacrosse")
    director = store.create_user(org, "director", "Dir K")
    kid = store.create_user(org, "athlete", "Jordan Pierce", birth_year=2012, dominant_hand="right")
    return {"org": org, "director": director, "kid": kid}


def stage(store, org, athlete_id):
    rows = F.funnel(store.conn, org)["athletes"]
    return next(a for a in rows if a["athlete_id"] == athlete_id)


class TestEachStep:

    def test_no_parent_on_file(self, store, program):
        a = stage(store, program["org"], program["kid"]["id"])
        assert a["stage"] == "no_parent" and a["who"] == "program"
        assert a["can_nudge"] is False

    def test_parent_known_but_never_invited(self, store, program):
        C.upsert(store.conn, org_id=program["org"], athlete_id=program["kid"]["id"],
                 name="Dana Pierce", email="dana@example.com")
        a = stage(store, program["org"], program["kid"]["id"])
        assert a["stage"] == "invite_unsent" and a["who"] == "program"
        assert a["parent_name"] == "Dana Pierce" and a["parent_email"] == "dana@example.com"
        assert a["can_nudge"] is True

    def test_invited_and_not_opened_is_the_parents_move(self, store, program):
        C.upsert(store.conn, org_id=program["org"], athlete_id=program["kid"]["id"],
                 email="dana@example.com")
        G.create_invite(store.conn, program["kid"]["id"], program["director"]["id"], "dana@example.com")
        a = stage(store, program["org"], program["kid"]["id"])
        assert a["stage"] == "invited" and a["who"] == "parent"
        assert a["last_invited_at"]
        assert a["can_nudge"] is True

    def test_signed_up_without_consent(self, store, program):
        inv = G.create_invite(store.conn, program["kid"]["id"], program["director"]["id"], "dana@example.com")
        G.redeem_invite(store.conn, inv["code"], "Dana Pierce", email="dana@example.com")
        a = stage(store, program["org"], program["kid"]["id"])
        assert a["stage"] == "consent_pending" and a["who"] == "parent"
        assert a["can_nudge"] is False  # the parent is in; mail would be noise

    def test_consent_given_but_link_never_sent(self, store, program):
        inv = G.create_invite(store.conn, program["kid"]["id"], program["director"]["id"], "dana@example.com")
        parent = G.redeem_invite(store.conn, inv["code"], "Dana Pierce", email="dana@example.com")
        G.set_consent(store.conn, program["kid"]["id"], parent["guardian_id"], G.Scope.PARTICIPATION, True)
        a = stage(store, program["org"], program["kid"]["id"])
        assert a["stage"] == "link_unsent" and a["who"] == "parent"

    def test_link_sent_and_kid_has_not_signed_in(self, store, program):
        inv = G.create_invite(store.conn, program["kid"]["id"], program["director"]["id"], "dana@example.com")
        parent = G.redeem_invite(store.conn, inv["code"], "Dana Pierce", email="dana@example.com")
        G.set_consent(store.conn, program["kid"]["id"], parent["guardian_id"], G.Scope.PARTICIPATION, True)
        G.athlete_signin_link(store.conn, parent["guardian_id"], program["kid"]["id"])
        a = stage(store, program["org"], program["kid"]["id"])
        assert a["stage"] == "link_sent" and a["who"] == "athlete"
        assert a["link_sent_at"]

    def test_signed_in_and_not_trained(self, store, program):
        inv = G.create_invite(store.conn, program["kid"]["id"], program["director"]["id"], "dana@example.com")
        parent = G.redeem_invite(store.conn, inv["code"], "Dana Pierce", email="dana@example.com")
        G.set_consent(store.conn, program["kid"]["id"], parent["guardian_id"], G.Scope.PARTICIPATION, True)
        link = G.athlete_signin_link(store.conn, parent["guardian_id"], program["kid"]["id"])
        store.authenticate(link["code"])  # the kid taps the link
        a = stage(store, program["org"], program["kid"]["id"])
        assert a["stage"] == "signed_in" and a["who"] == "athlete"
        assert a["last_seen_at"]

    def test_training(self, client_with, program):
        client, store = client_with
        inv = G.create_invite(store.conn, program["kid"]["id"], program["director"]["id"], "dana@example.com")
        parent = G.redeem_invite(store.conn, inv["code"], "Dana Pierce", email="dana@example.com")
        G.set_consent(store.conn, program["kid"]["id"], parent["guardian_id"], G.Scope.PARTICIPATION, True)
        link = G.athlete_signin_link(store.conn, parent["guardian_id"], program["kid"]["id"])
        out = submit_reps(client, {"Authorization": f"Bearer {link['code']}"}, "lax_wall_ball_strong", 24)
        assert out["status"] == "counted", out
        a = stage(store, program["org"], program["kid"]["id"])
        assert a["stage"] == "training" and a["who"] == ""
        assert F.funnel(store.conn, program["org"])["through"] == 1


class TestInviteWordingFollowsTheEmailHold:
    """While email is held the program never sent the invite, so the
    dashboard must not tell the director it did."""

    def invited(self, store, program):
        C.upsert(store.conn, org_id=program["org"], athlete_id=program["kid"]["id"],
                 email="dana@example.com")
        G.create_invite(store.conn, program["kid"]["id"], program["director"]["id"], "dana@example.com")
        return F.funnel(store.conn, program["org"])

    def test_held_email_says_ready_not_sent(self, store, program, monkeypatch):
        from offdays import mailer
        monkeypatch.setattr(mailer, "mail_held", lambda conn, org_id: True)
        out = self.invited(store, program)
        a = out["athletes"][0]
        assert a["stage"] == "invited"
        assert a["label"] == "Invite ready (email is on hold), parent has not signed up"
        assert out["mail_sending"] is False
        listed = {s["key"]: s["label"] for s in out["stages"]}
        assert listed["invited"] == a["label"]

    def test_no_mail_provider_also_says_ready(self, store, program, monkeypatch):
        from dataclasses import replace
        from offdays import mailer
        monkeypatch.setattr(mailer, "CONFIG", replace(CONFIG, smtp_host=""))
        a = self.invited(store, program)["athletes"][0]
        assert a["label"].startswith("Invite ready")

    def test_sending_email_says_sent(self, store, program):
        out = self.invited(store, program)
        assert out["athletes"][0]["label"] == "Invite sent, parent has not signed up"
        assert out["mail_sending"] is True


class TestCounts:

    def test_counts_add_up_and_every_stage_is_listed(self, store, program):
        out = F.funnel(store.conn, program["org"])
        assert sum(out["counts"].values()) == out["total"] == 1
        assert [s["key"] for s in out["stages"]] == [k for k, _, _ in F.STAGES]


class TestRoutes:

    @pytest.fixture
    def client(self, tmp_path):
        api_module._store = Store(connect(tmp_path / "api.db"))
        yield TestClient(api_module.app)
        api_module._store = None

    @pytest.fixture
    def org(self, client):
        made = client.post(
            "/api/orgs", json={"name": "Mad Dog Lacrosse", "accept_terms": True, "director_name": "Dir K"}
        ).json()
        director = {"Authorization": f"Bearer {made['director']['token']}"}
        kid = client.post(
            "/api/athletes", headers=director,
            json={"display_name": "Jordan Pierce", "birth_year": 2012},
        ).json()
        return {"org_id": made["org_id"], "director": director, "kid": kid}

    def test_director_sees_the_funnel(self, client, org):
        r = client.get("/api/coach/families", headers=org["director"])
        assert r.status_code == 200
        assert r.json()["athletes"][0]["stage"] == "no_parent"

    def test_a_coach_sees_only_their_teams(self, client, org):
        store = api_module._store
        red = store.create_team(org["org_id"], "2031 Red", "2026")
        blue = store.create_team(org["org_id"], "2031 Blue", "2026")
        store.join_team(blue["join_code"], org["kid"]["id"])
        coach = store.create_user(org["org_id"], "coach", "Coach A")
        store.assign_staff_to_team(coach["id"], red["id"])
        headers = {"Authorization": f"Bearer {coach['token']}"}
        r = client.get("/api/coach/families", headers=headers)
        assert r.status_code == 200
        assert r.json()["athletes"] == []  # Jordan is on Blue; this coach has Red
        assert client.get("/api/coach/families", headers=org["director"]).json()["total"] == 1

    def test_nudge_emails_the_roster_parent_and_moves_the_stage(self, client, org):
        store = api_module._store
        C.upsert(store.conn, org_id=org["org_id"], athlete_id=org["kid"]["id"],
                 name="Dana Pierce", email="dana@example.com")
        r = client.post("/api/coach/families/nudge", headers=org["director"],
                        json={"athlete_id": org["kid"]["id"]})
        assert r.status_code == 201, r.text
        assert r.json()["email"] == "dana@example.com"
        assert r.json()["emailed"] is True
        a = client.get("/api/coach/families", headers=org["director"]).json()["athletes"][0]
        assert a["stage"] == "invited"

    def test_nudge_twice_leaves_one_live_invite(self, client, org):
        store = api_module._store
        C.upsert(store.conn, org_id=org["org_id"], athlete_id=org["kid"]["id"], email="dana@example.com")
        for _ in range(2):
            assert client.post("/api/coach/families/nudge", headers=org["director"],
                               json={"athlete_id": org["kid"]["id"]}).status_code == 201
        live = store.conn.execute(
            "SELECT COUNT(*) FROM guardian_invites WHERE athlete_id = ? "
            "AND redeemed_at IS NULL AND revoked_at IS NULL", (org["kid"]["id"],)
        ).fetchone()[0]
        assert live == 1

    def test_nudge_refused_without_an_address(self, client, org):
        r = client.post("/api/coach/families/nudge", headers=org["director"],
                        json={"athlete_id": org["kid"]["id"]})
        assert r.status_code == 409

    def test_nudge_refused_once_a_parent_is_in(self, client, org):
        store = api_module._store
        inv = G.create_invite(store.conn, org["kid"]["id"], 1, "dana@example.com")
        G.redeem_invite(store.conn, inv["code"], "Dana Pierce", email="dana@example.com")
        r = client.post("/api/coach/families/nudge", headers=org["director"],
                        json={"athlete_id": org["kid"]["id"]})
        assert r.status_code == 409
        assert "parent is already signed up" in r.json()["detail"]
