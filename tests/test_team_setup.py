"""Creating a team is one form: its name, its coach, and the day's numbers.

The director types "2031 Red" and a coach; the wall-ball and shooting
numbers fill in from the team's age, from the same tables every athlete is
already held to, and he can change them. The numbers then bind for the
kids on that team -- as the program's guidance, under each child's own age
ceiling -- and are never handed to an athlete or a parent as a figure.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import team_age
from offdays.db import connect
from offdays.store import Store

TODAY = date(2026, 11, 4)


class TestTheNameSaysTheAge:

    @pytest.mark.parametrize("name, age, band, how", [
        ("2031 Red", 13, "13-14", "graduation year 2031"),
        ("2029 Blue", 15, "15-16", "graduation year 2029"),
        ("2035", 9, "10 and under", "graduation year 2035"),
        ("U13 Boys", 12, "11-12", "U13"),
        ("13U", 12, "11-12", "U13"),
        ("14 and under", 13, "13-14", "U14"),
        ("2013 Blue", 13, "13-14", "birth year 2013"),
        ("U9", 8, "10 and under", "U9"),
    ])
    def test_club_naming_conventions(self, name, age, band, how):
        got = team_age.infer(name, TODAY)
        assert got is not None, name
        assert (got.age, got.band, got.how) == (age, band, how)

    @pytest.mark.parametrize("name", ["Varsity", "Red", "", "Mad Dogs", "Team 7"])
    def test_a_name_that_says_nothing_prefills_nothing(self, name):
        s = team_age.suggest(name, TODAY)
        assert s["inferred"] is False and s["wall_ball"] is None and s["shots"] is None

    def test_the_numbers_are_the_age_tables_the_athletes_are_held_to(self):
        from offdays.drills import DRILLS_BY_KEY
        from offdays.scoring import daily_cap_for
        s = team_age.suggest("2031 Red", TODAY)
        assert s["wall_ball"] == daily_cap_for(DRILLS_BY_KEY["lax_wall_ball_strong"], 13) == 220
        assert s["shots"] == daily_cap_for(DRILLS_BY_KEY["lax_shooting"], 13) == 80
        younger = team_age.suggest("U9", TODAY)
        assert younger["wall_ball"] < s["wall_ball"] and younger["shots"] < s["shots"]


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


@pytest.fixture
def org(client):
    made = client.post("/api/orgs", json={"name": "Mad Dog", "sport": "lacrosse", "accept_terms": True, "director_name": "Joel"}).json()
    director = {"Authorization": f"Bearer {made['director']['token']}"}
    coach = api_module._store.create_user(made["org_id"], "coach", "Existing Coach")
    return {"org_id": made["org_id"], "director": director,
            "coach": {"Authorization": f"Bearer {coach['token']}"}}


class TestOneForm:

    def test_suggest_is_what_the_form_prefills(self, client, org):
        s = client.get("/api/teams/suggest?name=2031%20Red", headers=org["director"]).json()
        assert s["inferred"] and s["band"] == "13-14" and s["wall_ball"] == 220 and s["shots"] == 80

    def test_team_coach_and_numbers_in_one_post(self, client, org):
        r = client.post("/api/teams", headers=org["director"], json={
            "name": "2031 Red", "coach_name": "Sam Hill", "coach_email": "sam@example.com",
            "daily_wall_ball": 220, "daily_shots": 80})
        assert r.status_code == 201, r.text
        team = r.json()
        assert team["daily_wall_ball"] == 220 and team["daily_shots"] == 80
        assert team["coach"]["display_name"] == "Sam Hill" and team["coach"]["team_ids"] == [team["id"]]
        # The team table shows the coach and the numbers to staff.
        rows = client.get("/api/coach/teams", headers=org["director"]).json()["teams"]
        row = next(t for t in rows if t["id"] == team["id"])
        assert row["coaches"] == "Sam Hill" and row["daily_wall_ball"] == 220 and row["daily_shots"] == 80
        # And the coach can sign in and sees that team.
        h = {"Authorization": f"Bearer {team['coach']['code']}"}
        mine = client.get("/api/coach/teams", headers=h).json()["teams"]
        assert [t["name"] for t in mine] == ["2031 Red"]

    def test_the_director_can_overtype_the_numbers_within_the_hard_cap(self, client, org):
        r = client.post("/api/teams", headers=org["director"], json={
            "name": "2031 Blue", "daily_wall_ball": 999, "daily_shots": 999})
        assert r.status_code == 201
        assert r.json()["daily_wall_ball"] == 300 and r.json()["daily_shots"] == 150  # drill hard caps

    def test_a_team_without_a_coach_is_fine_and_zero_means_each_age(self, client, org):
        r = client.post("/api/teams", headers=org["director"], json={"name": "Varsity"})
        assert r.status_code == 201
        assert r.json()["daily_wall_ball"] == 0 and r.json()["daily_shots"] == 0 and "coach" not in r.json()

    def test_a_coach_may_make_a_team_but_not_add_a_coach(self, client, org):
        assert client.post("/api/teams", headers=org["coach"], json={"name": "2032 Red"}).status_code == 201
        r = client.post("/api/teams", headers=org["coach"], json={"name": "2032 Blue", "coach_name": "X", "coach_email": "x@example.com"})
        assert r.status_code == 403


class TestTheNumbersBindAndStayPrivate:

    def _kid_on(self, client, org, team_json, birth_year):
        store = api_module._store
        kid = store.create_user(org["org_id"], "athlete", "Mason", birth_year=birth_year, dominant_hand="right")
        store.join_team(team_json["join_code"], kid["id"])
        from offdays import library
        library.set_team_drills(store.conn, org["org_id"], "lacrosse", team_json["id"],
                                ["lax_wall_ball_strong", "lax_wall_ball_offhand", "lax_shooting"])
        return {"Authorization": f"Bearer {kid['token']}"}

    def test_the_teams_number_is_what_counts_for_its_kids(self, client, org):
        from tests.test_rep_cap import _submit
        team = client.post("/api/teams", headers=org["director"], json={
            "name": "2031 Red", "daily_wall_ball": 100, "daily_shots": 30}).json()
        h = self._kid_on(client, org, team, 2012)  # 14: ceilings 220 wall / 80 shots
        wall = _submit(client, h, "lax_wall_ball_strong", 150)
        assert wall["reps_total"] == 100 and wall["rep_cap"]["cap"] == 100
        shots = _submit(client, h, "lax_shooting", 50, gap_ms=3000)
        assert shots["reps_total"] == 30 and shots["rep_cap"]["cap"] == 30
        assert any("30 shots a day, the number your program set" in n for n in shots["notes"])

    def test_the_childs_own_ceiling_still_wins_under_the_teams_number(self, client, org):
        from tests.test_rep_cap import _submit
        team = client.post("/api/teams", headers=org["director"], json={
            "name": "2031 Red", "daily_wall_ball": 300, "daily_shots": 150}).json()
        h = self._kid_on(client, org, team, 2017)  # 9: ceilings 150 wall / 40 shots
        wall = _submit(client, h, "lax_wall_ball_strong", 200)
        assert wall["reps_total"] == 150
        shots = _submit(client, h, "lax_shooting", 60, gap_ms=3000)
        assert shots["reps_total"] == 40
        assert any("for your age" in n for n in shots["notes"])

    def test_athletes_and_parents_are_never_handed_the_numbers(self, client, org):
        """What a kid gets is a cap note after the fact, in their own terms.
        No athlete- or parent-facing response carries the team's daily
        numbers or the program's cost."""
        import json
        team = client.post("/api/teams", headers=org["director"], json={
            "name": "2031 Red", "daily_wall_ball": 100, "daily_shots": 30}).json()
        h = self._kid_on(client, org, team, 2012)
        for path in ("/api/me", "/api/me/drills", "/api/me/profile", "/api/me/budget", "/api/me/home"):
            r = client.get(path, headers=h)
            if r.status_code != 200:
                continue
            body = json.dumps(r.json())
            assert "daily_wall_ball" not in body and "daily_shots" not in body, path
            assert "per_athlete_day" not in body and "total_display" not in body, path
        # A coach's teams list carries them (staff guidance); the kid's does not exist.
        assert client.get("/api/coach/teams", headers=h).status_code in (401, 403)

class TestRemovingAMistake:

    def test_an_empty_team_can_be_removed_and_its_coach_stays(self, client, org):
        made = client.post("/api/teams", headers=org["director"], json={
            "name": "2031 Red", "coach_name": "Sam Hill", "coach_email": "sam@example.com"}).json()
        r = client.delete(f"/api/teams/{made['id']}", headers=org["director"])
        assert r.status_code == 200 and r.json()["deleted"] is True
        assert all(t["id"] != made["id"] for t in client.get("/api/coach/teams", headers=org["director"]).json()["teams"])
        staff = client.get("/api/coach/staff", headers=org["director"]).json()["staff"]
        assert any(s["display_name"] == "Sam Hill" for s in staff)

    def test_a_team_with_athletes_is_refused_with_the_reason(self, client, org):
        made = client.post("/api/teams", headers=org["director"], json={"name": "2031 Blue"}).json()
        store = api_module._store
        kid = store.create_user(org["org_id"], "athlete", "Mason", birth_year=2013)
        store.join_team(made["join_code"], kid["id"])
        r = client.delete(f"/api/teams/{made['id']}", headers=org["director"])
        assert r.status_code == 409 and "1 athlete" in r.json()["detail"]
        assert any(t["id"] == made["id"] for t in client.get("/api/coach/teams", headers=org["director"]).json()["teams"])

    def test_only_a_director_and_only_their_own_program(self, client, org):
        made = client.post("/api/teams", headers=org["director"], json={"name": "2032 Red"}).json()
        assert client.delete(f"/api/teams/{made['id']}", headers=org["coach"]).status_code == 403
        other = client.post("/api/orgs", json={"name": "Other", "accept_terms": True, "director_name": "X"}).json()
        oh = {"Authorization": f"Bearer {other['director']['token']}"}
        assert client.delete(f"/api/teams/{made['id']}", headers=oh).status_code == 404

