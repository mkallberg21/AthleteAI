"""Coaches add drills the list does not have, and give one player drills for their specialty (a face off specialist's clamp work)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import library
from offdays.db import connect
from offdays.store import Store

SPORT = "lacrosse"
CLAMP = {"name": "Face Off Clamp", "based_on": "gen_plank", "description": "Set the clamp, hold it, then pop out.",
         "setup_hint": "Side-on, whole body in frame."}


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "pd.db"))


@pytest.fixture
def club(store):
    org = store.create_org("Nashville Dogs", sport=SPORT)
    director = store.create_user(org, "director", "Joel")
    coach = store.create_user(org, "coach", "Coach Tommy")
    other = store.create_user(org, "coach", "Coach Mike")
    red = store.create_team(org, "2031 Red", "2026")
    blue = store.create_team(org, "2031 Blue", "2026")
    store.assign_staff_to_team(coach["id"], red["id"])
    store.assign_staff_to_team(other["id"], blue["id"])
    spec = store.create_user(org, "athlete", "Scott", birth_year=2012, dominant_hand="right")
    mate = store.create_user(org, "athlete", "Sam", birth_year=2012, dominant_hand="left")
    far = store.create_user(org, "athlete", "Far", birth_year=2012, dominant_hand="left")
    store.join_team(red["join_code"], spec["id"])
    store.join_team(red["join_code"], mate["id"])
    store.join_team(blue["join_code"], far["id"])
    return {"org": org, "director": director, "coach": coach, "other": other, "red": red["id"], "blue": blue["id"],
            "spec": spec, "mate": mate, "far": far}


@pytest.fixture
def api(store, club):
    api_module._store = store
    client = TestClient(api_module.app)
    h = lambda who: {"Authorization": f"Bearer {club[who]['token']}"}  # noqa: E731
    yield client, h
    api_module._store = None


def seen_by(client, h, who):
    return [d["key"] for d in client.get("/api/me/drills", headers=h(who)).json()["drills"]]


class TestACoachAddsADrillTheListLacks:
    def test_a_coach_can_add_one(self, api, club):
        client, h = api
        res = client.post("/api/coach/drills", headers=h("coach"), json=CLAMP)
        assert res.status_code == 201 and res.json()["name"] == "Face Off Clamp"
        assert res.json()["counted_as"]["key"] == "gen_plank" and res.json()["placed"] is None

    def test_it_joins_the_program_list_so_it_can_be_picked(self, api, club, store):
        client, h = api
        key = client.post("/api/coach/drills", headers=h("coach"), json=CLAMP).json()["key"]
        assert key in [d.key for d in library.offered(store.conn, club["org"], SPORT)]

    def test_but_it_is_not_pushed_to_anyone_by_being_added(self, api, club):
        client, h = api
        key = client.post("/api/coach/drills", headers=h("coach"), json=CLAMP).json()["key"]
        assert key not in seen_by(client, h, "spec") and key not in seen_by(client, h, "far")

    def test_it_can_go_straight_onto_the_coachs_team(self, api, club):
        client, h = api
        key = client.post("/api/coach/drills", headers=h("coach"), json={**CLAMP, "team_id": club["red"]}).json()["key"]
        assert key in seen_by(client, h, "spec") and key in seen_by(client, h, "mate")
        assert key not in seen_by(client, h, "far")
        # and what the team already had is still there
        assert "lax_shooting" in seen_by(client, h, "spec")

    def test_it_cannot_be_put_on_another_coachs_team(self, api, club):
        client, h = api
        res = client.post("/api/coach/drills", headers=h("coach"), json={**CLAMP, "team_id": club["blue"]})
        assert res.status_code == 403

    def test_a_coach_the_director_has_locked_cannot_add_one(self, api, club, store):
        client, h = api
        library.set_coach_may_pick(store.conn, club["org"], club["coach"]["id"], False)
        res = client.post("/api/coach/drills", headers=h("coach"), json=CLAMP)
        assert res.status_code == 403 and "director" in res.json()["detail"]

    def test_a_director_still_can_and_a_coach_still_cannot_retire_one(self, api, club):
        client, h = api
        key = client.post("/api/coach/drills", headers=h("director"), json=CLAMP).json()["key"]
        assert client.delete(f"/api/coach/drills/{key}", headers=h("coach")).status_code == 403
        assert client.delete(f"/api/coach/drills/{key}", headers=h("director")).status_code == 200

    def test_a_team_and_a_player_together_is_refused(self, api, club):
        client, h = api
        res = client.post("/api/coach/drills", headers=h("coach"),
                          json={**CLAMP, "team_id": club["red"], "athlete_id": club["spec"]["id"]})
        assert res.status_code == 400


class TestADrillForOnePlayer:
    def test_a_coach_gives_one_player_a_drill_and_only_that_player_sees_it(self, api, club):
        client, h = api
        key = client.post("/api/coach/drills", headers=h("coach"), json=CLAMP).json()["key"]
        sid = club["spec"]["id"]
        res = client.put(f"/api/coach/athletes/{sid}/drills", headers=h("coach"), json={"drill_keys": [key]})
        assert res.status_code == 200
        assert key in seen_by(client, h, "spec")
        assert key not in seen_by(client, h, "mate")
        assert "lax_shooting" in seen_by(client, h, "spec")

    def test_adding_a_drill_and_giving_it_to_the_player_is_one_step(self, api, club):
        client, h = api
        sid = club["spec"]["id"]
        made = client.post("/api/coach/drills", headers=h("coach"), json={**CLAMP, "athlete_id": sid}).json()
        assert made["placed"] == {"athlete_id": sid}
        assert made["key"] in seen_by(client, h, "spec") and made["key"] not in seen_by(client, h, "mate")

    def test_a_second_drill_added_for_the_player_keeps_the_first(self, api, club):
        client, h = api
        sid = club["spec"]["id"]
        a = client.post("/api/coach/drills", headers=h("coach"), json={**CLAMP, "athlete_id": sid}).json()["key"]
        b = client.post("/api/coach/drills", headers=h("coach"),
                        json={**CLAMP, "name": "Ground Ball Scoop", "athlete_id": sid}).json()["key"]
        assert {a, b} <= set(seen_by(client, h, "spec"))

    def test_the_view_says_what_is_the_teams_and_what_is_extra(self, api, club):
        client, h = api
        sid = club["spec"]["id"]
        key = client.post("/api/coach/drills", headers=h("coach"), json={**CLAMP, "athlete_id": sid}).json()["key"]
        view = client.get(f"/api/coach/athletes/{sid}/drills", headers=h("coach")).json()
        rows = {c["key"]: c for c in view["choices"]}
        assert rows["lax_shooting"]["on_team"] and not rows["lax_shooting"]["extra"]
        assert rows[key]["extra"] and not rows[key]["on_team"]
        assert view["can_edit"] and any(m["key"] == "gen_plank" for m in view["movements"])

    def test_taking_it_away_takes_it_away(self, api, club):
        client, h = api
        sid = club["spec"]["id"]
        key = client.post("/api/coach/drills", headers=h("coach"), json={**CLAMP, "athlete_id": sid}).json()["key"]
        client.put(f"/api/coach/athletes/{sid}/drills", headers=h("coach"), json={"drill_keys": []})
        assert key not in seen_by(client, h, "spec")

    def test_a_drill_the_team_already_has_is_not_stored_twice(self, api, club, store):
        client, h = api
        sid = club["spec"]["id"]
        client.put(f"/api/coach/athletes/{sid}/drills", headers=h("coach"), json={"drill_keys": ["lax_shooting"]})
        assert library.athlete_extra_keys(store.conn, sid) == []

    def test_a_drill_off_the_program_list_is_refused(self, api, club):
        client, h = api
        res = client.put(f"/api/coach/athletes/{club['spec']['id']}/drills", headers=h("coach"),
                         json={"drill_keys": ["no_such_drill"]})
        assert res.status_code == 400 and "not on the program's drill list" in res.json()["detail"]

    def test_a_coach_cannot_reach_a_player_on_someone_elses_team(self, api, club):
        client, h = api
        fid = club["far"]["id"]
        assert client.get(f"/api/coach/athletes/{fid}/drills", headers=h("coach")).status_code == 404
        assert client.put(f"/api/coach/athletes/{fid}/drills", headers=h("coach"), json={"drill_keys": []}).status_code == 404
        assert client.post("/api/coach/drills", headers=h("coach"), json={**CLAMP, "athlete_id": fid}).status_code == 404

    def test_a_director_can_for_any_player(self, api, club):
        client, h = api
        fid = club["far"]["id"]
        made = client.post("/api/coach/drills", headers=h("director"), json={**CLAMP, "athlete_id": fid})
        assert made.status_code == 201 and made.json()["key"] in seen_by(client, h, "far")

    def test_a_locked_coach_cannot_give_one(self, api, club, store):
        client, h = api
        library.set_coach_may_pick(store.conn, club["org"], club["coach"]["id"], False)
        view = client.get(f"/api/coach/athletes/{club['spec']['id']}/drills", headers=h("coach")).json()
        assert view["can_edit"] is False and "director" in view["why_not"]
        res = client.put(f"/api/coach/athletes/{club['spec']['id']}/drills", headers=h("coach"), json={"drill_keys": ["gen_jump_rope"]})
        assert res.status_code == 403

    def test_an_athlete_cannot_use_the_coach_routes(self, api, club):
        client, h = api
        res = client.put(f"/api/coach/athletes/{club['spec']['id']}/drills", headers=h("spec"), json={"drill_keys": ["gen_jump_rope"]})
        assert res.status_code in (401, 403)

    def test_the_director_taking_it_off_the_program_list_stops_it_reaching_the_player(self, api, club):
        client, h = api
        sid = club["spec"]["id"]
        key = client.post("/api/coach/drills", headers=h("coach"), json={**CLAMP, "athlete_id": sid}).json()["key"]
        client.delete(f"/api/coach/drills/{key}", headers=h("director"))
        assert key not in seen_by(client, h, "spec")

    def test_another_drill_from_the_wider_library_can_be_given_too(self, api, club):
        client, h = api
        sid = club["spec"]["id"]
        client.post("/api/coach/library/gen_jump_rope", headers=h("director"), json={"offered": True})
        client.put(f"/api/coach/athletes/{sid}/drills", headers=h("coach"), json={"drill_keys": ["gen_jump_rope"]})
        assert "gen_jump_rope" in seen_by(client, h, "spec") and "gen_jump_rope" not in seen_by(client, h, "mate")


class TestAssigningASpecialistDrill:
    def assign(self, client, h, who, club, key, athletes):
        return client.post("/api/coach/assignments", headers=h(who), json={
            "team_id": club["red"], "drill_key": key, "title": "Clamp work", "starts_on": "2026-01-01", "due_on": "2099-01-01",
            "target_sessions": 3, "athlete_ids": athletes})

    def test_it_can_be_assigned_to_the_player_who_has_it(self, api, club):
        client, h = api
        sid = club["spec"]["id"]
        key = client.post("/api/coach/drills", headers=h("coach"), json={**CLAMP, "athlete_id": sid}).json()["key"]
        assert self.assign(client, h, "coach", club, key, [sid]).status_code == 201

    def test_not_to_the_whole_team_or_to_a_player_who_does_not_have_it(self, api, club):
        client, h = api
        sid, mid = club["spec"]["id"], club["mate"]["id"]
        key = client.post("/api/coach/drills", headers=h("coach"), json={**CLAMP, "athlete_id": sid}).json()["key"]
        assert self.assign(client, h, "coach", club, key, []).status_code == 400
        assert self.assign(client, h, "coach", club, key, [sid, mid]).status_code == 400
        assert self.assign(client, h, "coach", club, key, [mid]).status_code == 400

    def test_a_drill_that_was_never_given_to_anyone_still_cannot_be_assigned(self, api, club):
        client, h = api
        assert self.assign(client, h, "coach", club, "gen_jump_rope", [club["spec"]["id"]]).status_code == 400


class TestTheScreen:
    from pathlib import Path
    HTML = (Path(api_module.__file__).parent / "web" / "static" / "coach.html").read_text(encoding="utf-8")

    def test_a_coach_is_no_longer_shown_the_add_a_drill_form_as_off_limits(self):
        assert "$('library-card').querySelectorAll('details').forEach((d) => d.classList.add('hidden'))" not in self.HTML

    def test_the_player_panel_has_a_drills_section_with_a_way_to_add_one(self):
        for needle in ("data-pd-save", "data-pd-new", "data-pd-name", "data-pd-based", "/api/coach/athletes/${id}/drills",
                       "Drills for"):
            assert needle in self.HTML, needle
