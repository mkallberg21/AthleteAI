"""A roster file can be taken back.

The director uploads the wrong file. Delete removes the athletes that file
created -- unless someone has already trained or a parent has already
signed up, in which case deleting would destroy a child's record or a
parent's account over a mistake about a file; those athletes are kept and
named. Athletes the file only updated are not reverted.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays.db import connect
from offdays.store import Store

CSV = (
    "First Name,Last Name,Birth Year,Parent Email,Parent Phone\n"
    "Ava,Stone,2013,ava.mom@example.com,615-555-0101\n"
    "Ben,Reyes,2013,ben.dad@example.com,615-555-0102\n"
    "Cal,Moss,2013,cal.mom@example.com,615-555-0103\n"
)


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def _program(client, name="Mad Dog"):
    made = client.post("/api/orgs", json={"name": name, "sport": "lacrosse", "director_name": "Joel"}).json()
    h = {"Authorization": f"Bearer {made['director']['token']}"}
    team = client.post("/api/teams", json={"name": "2031 Red"}, headers=h).json()
    coach = api_module._store.create_user(made["org_id"], "coach", "Coach")
    return {"org_id": made["org_id"], "h": h, "team": team["id"],
            "coach": {"Authorization": f"Bearer {coach['token']}"}}


def _upload(client, p, content=CSV, filename="roster.csv"):
    r = client.post("/api/coach/roster/import", headers=p["h"],
                    json={"content": content, "team_id": p["team"], "filename": filename})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _names(client, p):
    return sorted(a["display_name"] for a in client.get("/api/coach/athletes", headers=p["h"]).json()["athletes"]) \
        if client.get("/api/coach/athletes", headers=p["h"]).status_code == 200 else None


def _athletes(p):
    return sorted(r["display_name"] for r in api_module._store.conn.execute(
        "SELECT display_name FROM users WHERE org_id = ? AND role = 'athlete'", (p["org_id"],)))


class TestTheListOfUploads:

    def test_an_upload_is_remembered_with_its_name(self, client):
        p = _program(client)
        res = _upload(client, p, filename="mad-dogs-2031.csv")
        assert res["import_id"]
        listed = client.get("/api/coach/roster/imports", headers=p["h"]).json()["imports"]
        assert [(u["filename"], u["created"], u["still_here"]) for u in listed] == [("mad-dogs-2031.csv", 3, 3)]
        assert listed[0]["team"] == "2031 Red"

    def test_a_pasted_roster_has_a_plain_name(self, client):
        p = _program(client)
        _upload(client, p, filename="")
        assert client.get("/api/coach/roster/imports", headers=p["h"]).json()["imports"][0]["filename"] == "(pasted roster)"

    def test_each_program_sees_only_its_own(self, client):
        a, b = _program(client, "A"), _program(client, "B")
        _upload(client, a)
        assert client.get("/api/coach/roster/imports", headers=b["h"]).json()["imports"] == []


class TestDeletingAnUpload:

    def test_delete_removes_the_athletes_the_file_created(self, client):
        p = _program(client)
        res = _upload(client, p)
        r = client.delete(f"/api/coach/roster/imports/{res['import_id']}", headers=p["h"])
        assert r.status_code == 200 and r.json()["removed"] == 3 and r.json()["kept"] == []
        assert _athletes(p) == []
        assert client.get("/api/coach/roster/imports", headers=p["h"]).json()["imports"] == []

    def test_the_parents_contacts_and_invites_go_with_them(self, client):
        p = _program(client)
        res = _upload(client, p)
        client.delete(f"/api/coach/roster/imports/{res['import_id']}", headers=p["h"])
        c = api_module._store.conn
        assert c.execute("SELECT COUNT(*) AS n FROM guardian_contacts WHERE org_id = ?", (p["org_id"],)).fetchone()["n"] == 0
        assert c.execute("SELECT COUNT(*) AS n FROM guardian_invites").fetchone()["n"] == 0

    def test_the_team_and_the_program_survive(self, client):
        p = _program(client)
        res = _upload(client, p)
        client.delete(f"/api/coach/roster/imports/{res['import_id']}", headers=p["h"])
        teams = client.get("/api/coach/teams", headers=p["h"]).json()
        assert any(t["name"] == "2031 Red" for t in (teams["teams"] if isinstance(teams, dict) else teams))

    def test_someone_who_has_trained_is_kept_and_named(self, client):
        p = _program(client)
        res = _upload(client, p)
        ava = res["created"][0]["athlete_id"]
        api_module._store.conn.execute(
            "INSERT INTO sessions(athlete_id, drill_key, nonce, started_at) VALUES (?, 'wall_ball', 'n1', '2026-11-01T10:00:00+00:00')",
            (ava,))
        api_module._store.conn.commit()
        r = client.delete(f"/api/coach/roster/imports/{res['import_id']}", headers=p["h"]).json()
        assert r["removed"] == 2
        assert [(k["name"], k["why"]) for k in r["kept"]] == [("Ava Stone", "has already trained")]
        assert _athletes(p) == ["Ava Stone"]

    def test_someone_whose_parent_signed_up_is_kept_and_named(self, client):
        p = _program(client)
        res = _upload(client, p)
        invite = next(i for i in res["guardian_invites"] if i["athlete_name"] == "Ben Reyes")
        r = client.post("/api/guardians/redeem", json={
            "code": invite["code"], "display_name": "Ben's Dad", "email": "ben.dad@example.com",
            "relationship": "parent", "phone": "615-555-0102"})
        assert r.status_code in (200, 201), r.text
        out = client.delete(f"/api/coach/roster/imports/{res['import_id']}", headers=p["h"]).json()
        assert out["removed"] == 2
        assert [(k["name"], k["why"]) for k in out["kept"]] == [("Ben Reyes", "a parent has already signed up")]
        assert _athletes(p) == ["Ben Reyes"]

    def test_the_list_says_how_many_are_still_here_and_how_many_stay(self, client):
        p = _program(client)
        res = _upload(client, p)
        api_module._store.conn.execute(
            "INSERT INTO sessions(athlete_id, drill_key, nonce, started_at) VALUES (?, 'wall_ball', 'n1', '2026-11-01T10:00:00+00:00')",
            (res["created"][0]["athlete_id"],))
        api_module._store.conn.commit()
        u = client.get("/api/coach/roster/imports", headers=p["h"]).json()["imports"][0]
        assert (u["created"], u["still_here"], u["keeps"]) == (3, 3, 1)

    def test_athletes_a_file_only_updated_are_left_alone(self, client):
        p = _program(client)
        _upload(client, p, filename="first.csv")
        second = _upload(client, p, filename="second.csv")
        assert second["created"] == [] and len(second["updated"]) == 3
        client.delete(f"/api/coach/roster/imports/{second['import_id']}", headers=p["h"])
        assert _athletes(p) == ["Ava Stone", "Ben Reyes", "Cal Moss"]

    def test_deleting_twice_is_a_404_not_a_second_delete(self, client):
        p = _program(client)
        res = _upload(client, p)
        assert client.delete(f"/api/coach/roster/imports/{res['import_id']}", headers=p["h"]).status_code == 200
        assert client.delete(f"/api/coach/roster/imports/{res['import_id']}", headers=p["h"]).status_code == 404

    def test_only_a_director_can_delete(self, client):
        p = _program(client)
        res = _upload(client, p)
        r = client.delete(f"/api/coach/roster/imports/{res['import_id']}", headers=p["coach"])
        assert r.status_code == 403
        assert len(_athletes(p)) == 3

    def test_another_program_cannot_delete_it(self, client):
        a, b = _program(client, "A"), _program(client, "B")
        res = _upload(client, a)
        assert client.delete(f"/api/coach/roster/imports/{res['import_id']}", headers=b["h"]).status_code == 404
        assert len(_athletes(a)) == 3

    def test_a_signed_out_caller_gets_nothing(self, client):
        p = _program(client)
        res = _upload(client, p)
        assert client.delete(f"/api/coach/roster/imports/{res['import_id']}").status_code in (401, 403)
        assert client.get("/api/coach/roster/imports").status_code in (401, 403)


class TestAddingOnePlayerMidSeason:
    """The dashboard's 'Add a player' sends a one-row roster through the same
    import, so a late joiner gets everything everyone else got."""

    ONE = ("First Name,Last Name,Birth Year,Parent Email,Parent Phone\n"
           '"Mason","Reed","2013","reed.mom@example.com","615-555-0140"\n')

    def test_one_row_makes_a_player_and_a_parent_invite(self, client):
        p = _program(client)
        _upload(client, p)
        res = _upload(client, p, content=self.ONE, filename="Added by hand: Mason Reed")
        assert [a["display_name"] for a in res["created"]] == ["Mason Reed"]
        assert [i["email"] for i in res["guardian_invites"]] == ["reed.mom@example.com"]
        assert "Mason Reed" in _athletes(p) and len(_athletes(p)) == 4

    def test_the_parents_contact_is_kept(self, client):
        p = _program(client)
        _upload(client, p, content=self.ONE)
        row = api_module._store.conn.execute(
            "SELECT email, phone FROM guardian_contacts WHERE org_id = ?", (p["org_id"],)).fetchone()
        assert (row["email"], row["phone"]) == ("reed.mom@example.com", "615-555-0140")

    def test_a_late_joiner_is_billed_from_the_day_added_not_the_season_start(self, client):
        p = _program(client)
        _upload(client, p, content=self.ONE)
        mason = api_module._store.conn.execute(
            "SELECT m.created_at FROM memberships m JOIN users u ON u.id = m.user_id "
            "WHERE u.display_name = 'Mason Reed'").fetchone()
        assert mason["created_at"][:10] == __import__("datetime").date.today().isoformat()

    def test_adding_the_same_player_twice_does_not_duplicate_them(self, client):
        p = _program(client)
        _upload(client, p, content=self.ONE)
        again = _upload(client, p, content=self.ONE)
        assert again["created"] == [] and _athletes(p).count("Mason Reed") == 1

    def test_a_row_with_no_parent_email_still_adds_the_player_but_invites_nobody(self, client):
        p = _program(client)
        res = _upload(client, p, content="First Name,Last Name,Birth Year\nMason,Reed,2013\n")
        assert len(res["created"]) == 1 and res["guardian_invites"] == []

    def test_a_hand_added_player_can_be_taken_back_like_any_upload(self, client):
        p = _program(client)
        res = _upload(client, p, content=self.ONE, filename="Added by hand: Mason Reed")
        client.delete(f"/api/coach/roster/imports/{res['import_id']}", headers=p["h"])
        assert _athletes(p) == []
