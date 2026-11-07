"""A coach with several teams gets a home screen per team, and never sees another team's kids.

The dashboard's team chooser narrows every card to one team. Two server routes
did not honour that: the review queue showed every held session in the program
to any coach, and Families could not be narrowed at all.
"""
from __future__ import annotations

import offdays.api as api_module
from tests.test_api import client, program  # noqa: F401  (fixtures)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _setup(client, program):
    """Sam coaches Red and Blue; a third team Green is someone else's."""
    teams = {}
    for name in ("2031 Red", "2031 Blue", "2032 Green"):
        teams[name] = client.post("/api/teams", json={"name": name}, headers=program["director"]).json()
    sam = client.post("/api/coach/staff", headers=program["director"], json={
        "display_name": "Sam Hill", "email": "sam@example.com",
        "team_ids": [teams["2031 Red"]["id"], teams["2031 Blue"]["id"]]}).json()
    kids = {}
    for team, name in (("2031 Red", "Red Kid"), ("2031 Blue", "Blue Kid"), ("2032 Green", "Green Kid")):
        kids[name] = client.post("/api/athletes", json={
            "display_name": name, "join_code": teams[team]["join_code"]}, headers=program["director"]).json()
    return teams, kids, _bearer(sam["code"])


def _hold(kid_id, drill="lax_wall_ball_strong"):
    conn = api_module._store.conn
    conn.execute(
        "INSERT INTO sessions(athlete_id, drill_key, status, started_at, submitted_at, duration_ms, "
        "reps_total, nonce) VALUES (?,?,?,?,?,?,?,?)",
        (kid_id, drill, "review", "2026-11-06T11:59:00+00:00", "2026-11-06T12:00:00+00:00", 60000, 10,
         f"n-{kid_id}-{drill}"))
    conn.commit()


class TestReviewQueueIsScoped:
    def test_a_coach_sees_held_sessions_from_their_teams_only(self, client, program):
        _, kids, sam = _setup(client, program)
        for k in kids.values():
            _hold(k["id"])
        names = {s["display_name"] for s in client.get("/api/coach/review-queue", headers=sam).json()["sessions"]}
        assert names == {"Red Kid", "Blue Kid"}

    def test_a_director_still_sees_everyone(self, client, program):
        _, kids, _ = _setup(client, program)
        for k in kids.values():
            _hold(k["id"])
        names = {s["display_name"] for s in client.get(
            "/api/coach/review-queue", headers=program["director"]).json()["sessions"]}
        assert names == {"Red Kid", "Blue Kid", "Green Kid"}

    def test_the_queue_can_be_narrowed_to_one_team(self, client, program):
        teams, kids, sam = _setup(client, program)
        for k in kids.values():
            _hold(k["id"])
        blue = teams["2031 Blue"]["id"]
        names = {s["display_name"] for s in client.get(
            f"/api/coach/review-queue?team_id={blue}", headers=sam).json()["sessions"]}
        assert names == {"Blue Kid"}

    def test_another_teams_queue_is_refused(self, client, program):
        teams, _, sam = _setup(client, program)
        res = client.get(f"/api/coach/review-queue?team_id={teams['2032 Green']['id']}", headers=sam)
        assert res.status_code == 403

    def test_a_coach_cannot_decide_another_teams_session(self, client, program):
        _, kids, sam = _setup(client, program)
        _hold(kids["Green Kid"]["id"])
        sid = api_module._store.conn.execute(
            "SELECT id FROM sessions WHERE athlete_id = ?", (kids["Green Kid"]["id"],)).fetchone()[0]
        res = client.post(f"/api/coach/review/{sid}", json={"approve": True}, headers=sam)
        assert res.status_code in (403, 404), res.text


class TestFamiliesCanBeNarrowed:
    def _names(self, client, headers, qs=""):
        return {a["display_name"] for a in client.get(f"/api/coach/families{qs}", headers=headers).json()["athletes"]}

    def test_a_coach_defaults_to_all_their_teams(self, client, program):
        _, _, sam = _setup(client, program)
        assert self._names(client, sam) == {"Red Kid", "Blue Kid"}

    def test_narrowed_to_one_team(self, client, program):
        teams, _, sam = _setup(client, program)
        assert self._names(client, sam, f"?team_id={teams['2031 Red']['id']}") == {"Red Kid"}

    def test_the_counts_follow_the_team(self, client, program):
        teams, _, sam = _setup(client, program)
        body = client.get(f"/api/coach/families?team_id={teams['2031 Blue']['id']}", headers=sam).json()
        assert body["total"] == 1

    def test_a_director_can_narrow_too(self, client, program):
        teams, _, _ = _setup(client, program)
        names = self._names(client, program["director"], f"?team_id={teams['2032 Green']['id']}")
        assert names == {"Green Kid"}

    def test_another_teams_families_are_refused(self, client, program):
        teams, _, sam = _setup(client, program)
        res = client.get(f"/api/coach/families?team_id={teams['2032 Green']['id']}", headers=sam)
        assert res.status_code == 403

    def test_another_programs_team_is_refused_for_a_director(self, client, program):
        rival = client.post("/api/orgs", json={"name": "Rival", "director_name": "R"}).json()
        rt = client.post("/api/teams", json={"name": "X"}, headers=_bearer(rival["director"]["token"])).json()
        res = client.get(f"/api/coach/families?team_id={rt['id']}", headers=program["director"])
        assert res.status_code in (403, 404)
