"""A team's own drills: the coach picks, the players see only those.

The case this exists for: a coach wants the whole squad on the same work, not
two players on jump rope and three on something else. So a team with a list is
strict -- its players see exactly that list -- and a team without one sees the
program list as before. The director owns the program list and can stop a
coach from choosing; a coach can by default.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import library
from offdays.db import connect
from offdays.drills.catalog import for_sport
from offdays.store import Store

SPORT = "lacrosse"


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "team_drills.db"))


@pytest.fixture
def club(store):
    org = store.create_org("Nashville Dogs", sport=SPORT)
    director = store.create_user(org, "director", "Joel")
    coach = store.create_user(org, "coach", "Coach Tommy")
    other_coach = store.create_user(org, "coach", "Coach Mike")
    red = store.create_team(org, "2031 Red", "2026")
    blue = store.create_team(org, "2031 Blue", "2026")
    store.assign_staff_to_team(coach["id"], red["id"])
    store.assign_staff_to_team(other_coach["id"], blue["id"])
    kid = store.create_user(org, "athlete", "Scott", birth_year=2012, dominant_hand="right")
    both = store.create_user(org, "athlete", "Sam", birth_year=2012, dominant_hand="left")
    store.join_team(red["join_code"], kid["id"])
    store.join_team(red["join_code"], both["id"])
    store.join_team(blue["join_code"], both["id"])
    return {
        "org": org, "director": director, "coach": coach, "other_coach": other_coach,
        "red": red["id"], "blue": blue["id"], "kid": kid, "both": both,
    }


@pytest.fixture
def api(store, club):
    api_module._store = store
    client = TestClient(api_module.app)
    h = lambda who: {"Authorization": f"Bearer {club[who]['token']}"}  # noqa: E731
    yield client, h
    api_module._store = None


def keys(drills):
    return [d.key for d in drills]


class TestTheLibrary:
    def test_a_new_team_starts_on_the_starter_drills(self, store, club):
        """Everyday ground balls, wall ball with each hand on top, shooting.
        Everything else is for a coach or director to switch on."""
        assert keys(library.team_offered(store.conn, club["org"], SPORT, club["red"])) \
            == ["lax_ground_ball_everyday", "lax_shooting",
                "lax_wall_ball_strong", "lax_wall_ball_offhand"]

    def test_jump_rope_is_on_the_menu_but_off_until_turned_on(self, store, club):
        menu = keys(library.offered(store.conn, club["org"], SPORT))
        team = keys(library.team_offered(store.conn, club["org"], SPORT, club["red"]))
        assert "gen_jump_rope" in menu and "gen_jump_rope" not in team
        library.set_team_drills(store.conn, club["org"], SPORT, club["red"],
                                list(team) + ["gen_jump_rope"])
        assert "gen_jump_rope" in keys(
            library.team_offered(store.conn, club["org"], SPORT, club["red"]))

    def test_a_starter_the_director_takes_off_the_menu_drops_off(self, store, club):
        library.set_offered(store.conn, club["org"], "lax_shooting", False, SPORT)
        assert "lax_shooting" not in keys(
            library.team_offered(store.conn, club["org"], SPORT, club["red"]))

    def test_a_sport_with_no_starter_list_offers_the_whole_menu(self, store):
        org = store.create_org("Soccer Club", sport="soccer")
        team = store.create_team(org, "U12", "2026")
        assert keys(library.team_offered(store.conn, org, "soccer", team["id"])) \
            == keys(library.offered(store.conn, org, "soccer"))

    def test_a_team_with_a_list_sees_only_that_list(self, store, club):
        library.set_team_drills(store.conn, club["org"], SPORT, club["red"],
                                ["lax_wall_ball", "gen_squat"])
        assert set(keys(library.team_offered(store.conn, club["org"], SPORT, club["red"]))) \
            == {"lax_wall_ball", "gen_squat"}

    def test_an_empty_list_goes_back_to_the_program_list(self, store, club):
        library.set_team_drills(store.conn, club["org"], SPORT, club["red"], ["lax_wall_ball"])
        library.set_team_drills(store.conn, club["org"], SPORT, club["red"], [])
        assert library.team_drill_keys(store.conn, club["red"]) == []

    def test_a_coach_can_only_pick_from_the_program_list(self, store, club):
        with pytest.raises(library.LibraryError, match="program's drill list"):
            library.set_team_drills(store.conn, club["org"], SPORT, club["red"],
                                    ["soc_juggle"])

    def test_a_drill_taken_off_the_program_drops_off_the_team(self, store, club):
        library.set_team_drills(store.conn, club["org"], SPORT, club["red"],
                                ["lax_wall_ball", "gen_squat"])
        library.set_offered(store.conn, club["org"], "gen_squat", False, SPORT)
        assert keys(library.team_offered(store.conn, club["org"], SPORT, club["red"])) \
            == ["lax_wall_ball"]

    def test_another_programs_team_is_refused(self, store, club):
        other = store.create_org("Elsewhere", sport=SPORT)
        with pytest.raises(library.LibraryError, match="no such team"):
            library.set_team_drills(store.conn, other, SPORT, club["red"], ["gen_squat"])


class TestWhatAthletesSee:
    def test_a_player_sees_only_their_teams_list(self, store, club):
        library.set_team_drills(store.conn, club["org"], SPORT, club["red"],
                                ["lax_wall_ball"])
        assert keys(library.athlete_offered(
            store.conn, club["org"], SPORT, club["kid"]["id"])) == ["lax_wall_ball"]

    def test_a_player_on_two_teams_sees_both_lists_together(self, store, club):
        library.set_team_drills(store.conn, club["org"], SPORT, club["red"], ["lax_wall_ball"])
        library.set_team_drills(store.conn, club["org"], SPORT, club["blue"], ["gen_jump_rope"])
        assert set(keys(library.athlete_offered(
            store.conn, club["org"], SPORT, club["both"]["id"]))) \
            == {"lax_wall_ball", "gen_jump_rope"}

    def test_one_team_on_its_starters_adds_them_to_the_other_teams_picks(self, store, club):
        library.set_team_drills(store.conn, club["org"], SPORT, club["red"], ["lax_wall_ball"])
        seen = set(keys(library.athlete_offered(store.conn, club["org"], SPORT, club["both"]["id"])))
        assert seen == {"lax_wall_ball", "lax_ground_ball_everyday", "lax_shooting",
                        "lax_wall_ball_strong", "lax_wall_ball_offhand"}

    def test_over_the_wire(self, api, store, club):
        client, h = api
        library.set_team_drills(store.conn, club["org"], SPORT, club["red"],
                                ["lax_wall_ball", "gen_squat"])
        drills = client.get("/api/me/drills", headers=h("kid")).json()["drills"]
        assert {d["key"] for d in drills} == {"lax_wall_ball", "gen_squat"}


class TestWhoMayPick:
    def test_a_coach_may_pick_for_their_own_team_by_default(self, api, club):
        client, h = api
        r = client.put(f"/api/coach/teams/{club['red']}/drills",
                       json={"drill_keys": ["lax_wall_ball"]}, headers=h("coach"))
        assert r.status_code == 200 and r.json()["strict"] is True

    def test_a_coach_may_not_pick_for_another_coachs_team(self, api, club):
        client, h = api
        r = client.put(f"/api/coach/teams/{club['blue']}/drills",
                       json={"drill_keys": ["lax_wall_ball"]}, headers=h("coach"))
        assert r.status_code == 403

    def test_the_director_can_turn_a_coach_off_and_back_on(self, api, club):
        client, h = api
        off = client.post("/api/coach/staff/drill-choice",
                          json={"user_id": club["coach"]["id"], "allowed": False},
                          headers=h("director"))
        assert off.status_code == 200
        r = client.put(f"/api/coach/teams/{club['red']}/drills",
                       json={"drill_keys": ["lax_wall_ball"]}, headers=h("coach"))
        assert r.status_code == 403 and "director" in r.json()["detail"]
        # The screen is told up front, rather than finding out on save.
        view = client.get(f"/api/coach/teams/{club['red']}/drills", headers=h("coach")).json()
        assert view["can_edit"] is False and view["why_not"]

        client.post("/api/coach/staff/drill-choice",
                    json={"user_id": club["coach"]["id"], "allowed": True},
                    headers=h("director"))
        r = client.put(f"/api/coach/teams/{club['red']}/drills",
                       json={"drill_keys": ["lax_wall_ball"]}, headers=h("coach"))
        assert r.status_code == 200

    def test_a_locked_coachs_team_is_set_by_the_director(self, api, club):
        client, h = api
        client.post("/api/coach/staff/drill-choice",
                    json={"user_id": club["coach"]["id"], "allowed": False},
                    headers=h("director"))
        r = client.put(f"/api/coach/teams/{club['red']}/drills",
                       json={"drill_keys": ["lax_wall_ball"]}, headers=h("director"))
        assert r.status_code == 200

    def test_a_coach_cannot_flip_their_own_switch(self, api, club):
        client, h = api
        r = client.post("/api/coach/staff/drill-choice",
                        json={"user_id": club["coach"]["id"], "allowed": True},
                        headers=h("coach"))
        assert r.status_code == 403

    def test_the_staff_list_shows_the_switch(self, api, club):
        client, h = api
        client.post("/api/coach/staff/drill-choice",
                    json={"user_id": club["coach"]["id"], "allowed": False},
                    headers=h("director"))
        staff = {s["id"]: s for s in
                 client.get("/api/coach/staff", headers=h("director")).json()["staff"]}
        assert staff[club["coach"]["id"]]["can_choose_drills"] is False
        assert staff[club["other_coach"]["id"]]["can_choose_drills"] is True

    def test_only_the_director_changes_the_program_list(self, api, club):
        client, h = api
        assert client.post("/api/coach/library/gen_squat", json={"offered": False},
                           headers=h("coach")).status_code == 403
        assert client.post("/api/coach/library/gen_squat", json={"offered": False},
                           headers=h("director")).status_code == 200


class TestAssignmentsStayOnTheList:
    def body(self, team, drill):
        return {"team_id": team, "drill_key": drill, "title": "This week",
                "starts_on": "2026-10-01", "due_on": "2026-10-07", "target_reps": 200}

    def test_assigning_a_drill_off_the_teams_list_is_refused(self, api, store, club):
        client, h = api
        library.set_team_drills(store.conn, club["org"], SPORT, club["red"], ["lax_wall_ball"])
        r = client.post("/api/coach/assignments", json=self.body(club["red"], "gen_squat"),
                        headers=h("coach"))
        assert r.status_code == 400 and "team's list" in r.json()["detail"]

    def test_assigning_a_drill_on_the_list_works(self, api, store, club):
        client, h = api
        library.set_team_drills(store.conn, club["org"], SPORT, club["red"], ["lax_wall_ball"])
        r = client.post("/api/coach/assignments", json=self.body(club["red"], "lax_wall_ball"),
                        headers=h("coach"))
        assert r.status_code == 201

    def test_a_new_team_can_be_assigned_a_starter_drill(self, api, club):
        client, h = api
        r = client.post("/api/coach/assignments",
                        json=self.body(club["red"], "lax_wall_ball_offhand"),
                        headers=h("coach"))
        assert r.status_code == 201

    def test_a_new_team_cannot_be_assigned_a_drill_not_yet_turned_on(self, api, club):
        client, h = api
        r = client.post("/api/coach/assignments", json=self.body(club["red"], "gen_squat"),
                        headers=h("coach"))
        assert r.status_code == 400
