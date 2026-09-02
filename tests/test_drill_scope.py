"""A child is offered their own sport's drills, and nobody else's.

This exists because the athlete-facing catalog shipped every drill in the
product to every athlete. A lacrosse player's "Pick a drill" list opened on
soccer juggling, whose own description offered it as useful for basketball
and volleyball -- three sports the child does not play, on the first screen
they see.

The tests that covered this endpoint all asserted that a particular drill was
*present* and available. None asserted what should be absent, which is the
shape of assertion that catches a list quietly containing everything.
"""
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays.db import connect
from offdays.drills import ALL_DRILLS, for_sport
from offdays.store import Store


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
        "/api/teams", json={"name": "U15 Boys", "season": "2026"}, headers=director
    ).json()
    athlete = client.post(
        "/api/athletes",
        json={"display_name": "Jordan P.", "birth_year": 2011,
              "dominant_hand": "right", "guardian_consent": True,
              "join_code": team["join_code"]},
        headers=director,
    ).json()
    athlete["headers"] = {"Authorization": f"Bearer {athlete['token']}"}
    return {"org": org, "director": director, "team": team, "athletes": [athlete]}


class TestTheCatalogIsScopedToTheSport:
    def test_a_lacrosse_program_is_not_offered_soccer(self):
        keys = {d.key for d in for_sport("lacrosse")}
        assert "lax_ground_ball" in keys
        assert "soc_juggle" not in keys
        assert not any(d.sport == "soccer" for d in for_sport("lacrosse"))

    def test_the_sport_leads_and_conditioning_follows(self):
        """Whoever is choosing should land on their own sport's work."""
        got = for_sport("lacrosse")
        assert got[0].sport == "lacrosse"
        first_general = next(i for i, d in enumerate(got) if d.sport == "general")
        assert all(d.sport == "lacrosse" for d in got[:first_general])
        assert all(d.sport == "general" for d in got[first_general:])

    def test_general_conditioning_belongs_to_everybody(self):
        """A squat is a squat whatever the athlete plays."""
        for sport in ("lacrosse", "soccer", "hockey", "swimming"):
            keys = {d.key for d in for_sport(sport)}
            assert "gen_squat" in keys, sport
            assert "gen_plank" in keys, sport

    def test_every_sport_keeps_all_of_its_own_drills(self):
        by_sport: dict[str, set[str]] = {}
        for d in ALL_DRILLS:
            by_sport.setdefault(d.sport, set()).add(d.key)
        for sport, own in by_sport.items():
            if sport == "general":
                continue
            offered = {d.key for d in for_sport(sport)}
            assert own <= offered, f"{sport} lost {sorted(own - offered)}"

    def test_softball_still_gets_the_baseball_drills_it_shares(self):
        """The one sport pair that deliberately shares a catalog."""
        keys = {d.key for d in for_sport("softball")}
        assert any(d.sport == "baseball" for d in for_sport("softball"))
        assert {d.key for d in ALL_DRILLS if d.sport == "softball"} <= keys

    def test_an_unknown_sport_gets_general_work_not_everything(self):
        """The fallback for knowing least is the smallest honest list, not the
        largest -- showing everything is the bug this function exists to fix."""
        for sport in (None, "", "quidditch"):
            got = for_sport(sport)
            assert {d.sport for d in got} == {"general"}, sport
            assert len(got) < len(ALL_DRILLS)

    def test_no_sport_is_offered_the_whole_catalog(self):
        sports = {d.sport for d in ALL_DRILLS} - {"general"}
        for sport in sports:
            assert len(for_sport(sport)) < len(ALL_DRILLS), sport


class TestTheAthleteEndpointUsesIt:
    def test_the_pick_a_drill_list_holds_no_other_sport(self, client, program):
        athlete = program["athletes"][0]
        body = client.get("/api/me/drills", headers=athlete["headers"]).json()
        assert body["sport"] == "lacrosse"
        sports = {d["sport"] for d in body["drills"]}
        assert sports == {"lacrosse", "general"}, sorted(sports)
        keys = {d["key"] for d in body["drills"]}
        assert "lax_ground_ball" in keys
        assert "soc_juggle" not in keys

    def test_the_public_reference_catalog_is_still_complete(self, client):
        """/api/drills is reference data and deliberately unscoped -- the fix
        must not quietly shrink it."""
        body = client.get("/api/drills").json()
        assert len(body["drills"]) == len(ALL_DRILLS)
