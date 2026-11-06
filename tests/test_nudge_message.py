"""A coach messages everyone on the "Needs a nudge" list in one go.

Who is on the list is decided by the server from the same roster the card is
drawn from, never by the browser: a coach cannot name recipients, only write the
words. Kids flagged for rest or a load spike are left out, because "get back to
training" is the wrong thing to say to them.
"""
from __future__ import annotations

import pytest

import offdays.api as api_module
from offdays import notifications as notify
from tests.test_api import client, program  # noqa: F401  (fixtures)


def _inbox(user_id: int) -> list[dict]:
    return notify.feed(api_module._store.conn, user_id)


def _train(client, athlete) -> None:
    """One counted session, submitted the way the phone submits it."""
    import random
    h = athlete["headers"]
    start = client.post("/api/sessions/start", json={"drill_key": "lax_wall_ball"}, headers=h)
    assert start.status_code == 201, start.text
    start = start.json()
    rng, t, events = random.Random(7), 0, []
    for i in range(24):
        t += max(150, int(rng.gauss(880, 190)))
        events.append({"t_ms": t, "hand": "left" if i % 2 else "right", "confidence": 0.88})
    done = client.post("/api/sessions/submit", headers=h, json={
        "session_id": start["session_id"], "nonce": start["nonce"],
        "duration_ms": t + 700, "reps": events, "mean_confidence": 0.88})
    assert done.status_code == 200 and done.json()["status"] == "counted", done.text


def _post(client, headers, **kw):
    body = {"title": "We miss you", "body": "Ten minutes today?"}
    body.update(kw)
    return client.post("/api/coach/nudge-everyone", json=body, headers=headers)


class TestWhoGetsIt:
    def test_everyone_flagged_gets_the_message(self, client, program):
        # Both athletes have never trained, so both are on the list.
        res = _post(client, program["director"])
        assert res.status_code == 200
        assert res.json()["sent"] == 2
        for a in program["athletes"]:
            titles = [n["title"] for n in _inbox(a["id"])]
            assert "We miss you" in titles

    def test_someone_not_flagged_is_left_alone(self, client, program):
        sam = program["athletes"][1]
        _train(client, sam)  # Sam trains today, so he is no longer on the list
        res = _post(client, program["director"])
        assert res.json()["sent"] == 1
        assert "We miss you" not in [n["title"] for n in _inbox(sam["id"])]

    def test_a_kid_flagged_for_rest_is_never_told_to_train_more(self, client, program, monkeypatch):
        from offdays import leaderboard
        real = leaderboard.attach_load

        def tired(athletes, states):
            out = real(athletes, states)
            for a in out:
                if a["display_name"] == "Jordan P.":
                    a["flags"] = list(a["flags"]) + ["needs_rest"]
            return out
        monkeypatch.setattr(api_module, "attach_load", tired)
        res = _post(client, program["director"])
        body = res.json()
        assert body["sent"] == 1
        assert body["skipped_rest"] == 1
        jordan = program["athletes"][0]
        assert "We miss you" not in [n["title"] for n in _inbox(jordan["id"])]

    def test_nobody_to_nudge_sends_nothing_and_says_so(self, client, program):
        for a in program["athletes"]:
            _train(client, a)
        res = _post(client, program["director"])
        assert res.status_code == 200
        assert res.json()["sent"] == 0


class TestScope:
    def _jv_coach(self, client, program):
        team = client.post("/api/teams", json={"name": "JV"}, headers=program["director"]).json()
        coach = api_module._store.create_user(program["org"]["org_id"], "coach", "Coach JV")
        api_module._store.assign_staff_to_team(coach["id"], team["id"])
        kid = client.post(
            "/api/athletes",
            json={"display_name": "JV Kid", "join_code": team["join_code"]},
            headers=program["director"],
        ).json()
        return {"Authorization": f"Bearer {coach['token']}"}, kid

    def test_a_coach_reaches_only_their_own_teams(self, client, program):
        headers, kid = self._jv_coach(client, program)
        res = _post(client, headers)
        assert res.json()["sent"] == 1
        assert "We miss you" in [n["title"] for n in _inbox(kid["id"])]
        for a in program["athletes"]:
            assert "We miss you" not in [n["title"] for n in _inbox(a["id"])]

    def test_a_coach_cannot_aim_at_another_team(self, client, program):
        headers, _ = self._jv_coach(client, program)
        res = _post(client, headers, team_id=program["team"]["id"])
        assert res.status_code == 403

    def test_the_team_filter_narrows_it(self, client, program):
        other = client.post("/api/teams", json={"name": "JV"}, headers=program["director"]).json()
        kid = client.post(
            "/api/athletes",
            json={"display_name": "JV Kid", "join_code": other["join_code"]},
            headers=program["director"],
        ).json()
        res = _post(client, program["director"], team_id=program["team"]["id"])
        assert res.json()["sent"] == 2
        assert "We miss you" not in [n["title"] for n in _inbox(kid["id"])]

    def test_an_athlete_cannot_use_it(self, client, program):
        res = _post(client, program["athletes"][0]["headers"])
        assert res.status_code in (401, 403)

    def test_another_program_is_untouched(self, client, program):
        rival = client.post("/api/orgs", json={"name": "Rival", "director_name": "R"}).json()
        rteam = client.post(
            "/api/teams", json={"name": "U15"},
            headers={"Authorization": f"Bearer {rival['director']['token']}"},
        ).json()
        rkid = client.post(
            "/api/athletes",
            json={"display_name": "Rival Kid", "join_code": rteam["join_code"]},
            headers={"Authorization": f"Bearer {rival['director']['token']}"},
        ).json()
        _post(client, program["director"])
        assert "We miss you" not in [n["title"] for n in _inbox(rkid["id"])]


class TestTheWords:
    def test_a_title_is_required(self, client, program):
        res = client.post("/api/coach/nudge-everyone", json={"title": "", "body": "x"},
                          headers=program["director"])
        assert res.status_code == 422

    def test_the_title_is_capped(self, client, program):
        res = _post(client, program["director"], title="x" * 121)
        assert res.status_code == 422

    def test_a_parent_sees_what_their_child_was_sent(self, client, program):
        # Every message an athlete receives is copied to their guardians.
        from offdays import guardians as G
        jordan = program["athletes"][0]
        conn = api_module._store.conn
        inv = G.create_invite(conn, jordan["id"], program["org"]["director"]["id"], "pat@example.com")
        parent = G.redeem_invite(conn, inv["code"], "Pat", email="pat@example.com")
        _post(client, program["director"])
        assert "We miss you" in [n["title"] for n in _inbox(parent["guardian_id"])]


class TestNothingIsEmailed:
    def test_it_writes_to_the_app_and_never_to_the_outbox(self, client, program):
        before = api_module._store.conn.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0]
        _post(client, program["director"])
        after = api_module._store.conn.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0]
        assert after == before
