"""One coach, or one director's assistant, can run several teams from one login.

Found by asking the real API: entering the same coach on three teams made three
coach accounts, three codes and three welcome emails, and the coach had to sign
in separately for each team. A person is matched by email (never by name alone,
because two different people can share a name), or a director picks them from the
list of coaches already in the program.
"""
from __future__ import annotations

import pytest

import offdays.api as api_module
from offdays import invites as invites_mod
from tests.test_api import client, program  # noqa: F401  (fixtures)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _team(client, program, name, **kw):
    body = {"name": name}
    body.update(kw)
    return client.post("/api/teams", json=body, headers=program["director"])


def _coaches(client, program):
    rows = client.get("/api/coach/staff", headers=program["director"]).json()["staff"]
    return [s for s in rows if s["role"] == "coach"]


class TestTheSameEmailIsTheSamePerson:
    def test_a_second_team_reuses_the_coach(self, client, program):
        a = _team(client, program, "2031 Red", coach_name="Sam Hill", coach_email="sam@example.com").json()
        b = _team(client, program, "2031 Blue", coach_name="Sam Hill", coach_email="sam@example.com").json()
        coaches = _coaches(client, program)
        assert len(coaches) == 1
        assert sorted(t["name"] for t in coaches[0]["teams"]) == ["2031 Blue", "2031 Red"]
        assert b["coach"]["reused"] is True
        assert a["coach"].get("reused") in (False, None)

    def test_the_email_is_not_case_sensitive(self, client, program):
        _team(client, program, "A", coach_name="Sam Hill", coach_email="sam@example.com")
        _team(client, program, "B", coach_name="Sam Hill", coach_email="  SAM@Example.COM ")
        assert len(_coaches(client, program)) == 1

    def test_a_reused_coach_gets_no_new_code(self, client, program):
        _team(client, program, "A", coach_name="Sam Hill", coach_email="sam@example.com")
        b = _team(client, program, "B", coach_name="Sam Hill", coach_email="sam@example.com").json()
        assert not b["coach"].get("code")
        assert not b["coach"].get("link")

    def test_the_same_code_still_opens_everything(self, client, program):
        a = _team(client, program, "2031 Red", coach_name="Sam Hill", coach_email="sam@example.com").json()
        _team(client, program, "2031 Blue", coach_name="Sam Hill", coach_email="sam@example.com")
        token = a["coach"]["code"]
        teams = client.get("/api/coach/teams", headers=_bearer(token)).json()["teams"]
        assert sorted(t["name"] for t in teams) == ["2031 Blue", "2031 Red"]

    def test_a_reused_coach_is_not_sent_another_welcome(self, client, program, monkeypatch):
        sent = []
        real = invites_mod.deliver_staff
        monkeypatch.setattr(invites_mod, "deliver_staff", lambda *a, **k: sent.append(k) or real(*a, **k))
        _team(client, program, "A", coach_name="Sam Hill", coach_email="sam@example.com")
        assert len(sent) == 1
        _team(client, program, "B", coach_name="Sam Hill", coach_email="sam@example.com")
        assert len(sent) == 1, "the welcome went out a second time to the same person"

    def test_a_name_alone_never_merges_two_people(self, client, program):
        _team(client, program, "A", coach_name="Sam Hill")
        _team(client, program, "B", coach_name="Sam Hill")
        assert len(_coaches(client, program)) == 2

    def test_a_different_email_is_a_different_person(self, client, program):
        _team(client, program, "A", coach_name="Sam Hill", coach_email="sam@example.com")
        _team(client, program, "B", coach_name="Sam Hill", coach_email="sam.h@other.example")
        assert len(_coaches(client, program)) == 2

    def test_another_programs_coach_with_that_email_is_not_reused(self, client, program):
        rival = client.post("/api/orgs", json={"name": "Rival", "director_name": "R"}).json()
        rh = _bearer(rival["director"]["token"])
        client.post("/api/teams", json={"name": "X", "coach_name": "Sam Hill",
                                        "coach_email": "sam@example.com"}, headers=rh)
        _team(client, program, "A", coach_name="Sam Hill", coach_email="sam@example.com")
        mine = _coaches(client, program)
        assert len(mine) == 1 and [t["name"] for t in mine[0]["teams"]] == ["A"]


class TestPickingAnExistingCoach:
    def _sam(self, client, program):
        _team(client, program, "2031 Red", coach_name="Sam Hill", coach_email="sam@example.com")
        return _coaches(client, program)[0]["id"]

    def test_a_director_can_pick_one_from_the_list(self, client, program):
        sam = self._sam(client, program)
        res = _team(client, program, "2032 Red", coach_user_id=sam)
        assert res.status_code == 201, res.text
        assert res.json()["coach"]["reused"] is True
        coaches = _coaches(client, program)
        assert len(coaches) == 1 and len(coaches[0]["teams"]) == 2

    def test_picking_needs_no_name_or_email(self, client, program):
        sam = self._sam(client, program)
        assert _team(client, program, "B", coach_user_id=sam).status_code == 201

    def test_a_coach_from_another_program_is_refused(self, client, program):
        rival = client.post("/api/orgs", json={"name": "Rival", "director_name": "R"}).json()
        rh = _bearer(rival["director"]["token"])
        client.post("/api/teams", json={"name": "X", "coach_name": "Rae", "coach_email": "rae@x.example"}, headers=rh)
        rae = client.get("/api/coach/staff", headers=rh).json()["staff"]
        rae_id = next(s["id"] for s in rae if s["role"] == "coach")
        res = _team(client, program, "B", coach_user_id=rae_id)
        assert res.status_code == 404
        assert len(_coaches(client, program)) == 0

    def test_only_a_coach_can_be_picked(self, client, program):
        athlete = program["athletes"][0]
        res = _team(client, program, "B", coach_user_id=athlete["id"])
        assert res.status_code == 404

    def test_a_coach_cannot_assign_staff(self, client, program):
        sam = self._sam(client, program)
        other = api_module._store.create_user(program["org"]["org_id"], "coach", "Other")
        res = client.post("/api/teams", json={"name": "C", "coach_user_id": sam},
                          headers=_bearer(other["token"]))
        assert res.status_code == 403

    def test_a_unknown_id_is_refused(self, client, program):
        assert _team(client, program, "B", coach_user_id=999999).status_code == 404


class TestAddACoachForm:
    def test_adding_the_same_email_again_gives_them_the_extra_teams(self, client, program):
        a = _team(client, program, "A", coach_name="Sam Hill", coach_email="sam@example.com").json()
        b = _team(client, program, "B").json()
        res = client.post("/api/coach/staff", headers=program["director"], json={
            "display_name": "Sam Hill", "email": "sam@example.com", "team_ids": [b["id"]]})
        assert res.status_code == 201, res.text
        assert res.json()["reused"] is True
        coaches = _coaches(client, program)
        assert len(coaches) == 1 and len(coaches[0]["teams"]) == 2


class TestOneLoginSeesEveryTeam:
    def _two_teams(self, client, program):
        a = _team(client, program, "2031 Red", coach_name="Sam Hill", coach_email="sam@example.com").json()
        b = _team(client, program, "2031 Blue", coach_user_id=_coaches(client, program)[0]["id"]).json()
        c = _team(client, program, "2032 Red").json()
        kids = {}
        for team, name in ((a, "Red Kid"), (b, "Blue Kid"), (c, "Other Kid")):
            kids[name] = client.post("/api/athletes", json={"display_name": name, "join_code": team["join_code"]},
                                     headers=program["director"]).json()
        return a["coach"]["code"], kids

    def test_the_roster_has_both_teams_and_not_the_third(self, client, program):
        token, _ = self._two_teams(client, program)
        names = {r["display_name"] for r in client.get("/api/coach/roster", headers=_bearer(token)).json()["athletes"]}
        assert {"Red Kid", "Blue Kid"} <= names
        assert "Other Kid" not in names

    def test_the_team_filter_narrows_to_one(self, client, program):
        token, _ = self._two_teams(client, program)
        teams = client.get("/api/coach/teams", headers=_bearer(token)).json()["teams"]
        blue = next(t for t in teams if t["name"] == "2031 Blue")
        names = {r["display_name"] for r in client.get(
            f"/api/coach/roster?team_id={blue['id']}", headers=_bearer(token)).json()["athletes"]}
        assert names == {"Blue Kid"}

    def test_the_third_team_is_refused(self, client, program):
        token, _ = self._two_teams(client, program)
        teams = client.get("/api/coach/teams", headers=program["director"]).json()["teams"]
        other = next(t for t in teams if t["name"] == "2032 Red")
        res = client.get(f"/api/coach/roster?team_id={other['id']}", headers=_bearer(token))
        assert res.status_code == 403

    def test_a_message_reaches_only_their_teams(self, client, program):
        token, kids = self._two_teams(client, program)
        teams = client.get("/api/coach/teams", headers=_bearer(token)).json()["teams"]
        for t in teams:
            client.post("/api/coach/broadcast", json={"team_id": t["id"], "title": "Practice at 6"},
                        headers=_bearer(token))
        from offdays import notifications as N
        conn = api_module._store.conn
        got = lambda k: "Practice at 6" in [n["title"] for n in N.feed(conn, kids[k]["id"])]  # noqa: E731
        assert got("Red Kid") and got("Blue Kid") and not got("Other Kid")
