"""A parent can delete their own account.

Both app stores require that an account a person created can be deleted from
inside the app. The parent portal could delete a CHILD's data but not the
parent's own account. What happens to the child is the parent's choice; a
child whose only parent is gone is paused, because nobody is left to say yes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import guardians as G
from offdays.db import connect
from offdays.store import Store

CSV = (
    "First Name,Last Name,Birth Year,Parent Email,Parent Phone\n"
    "Mason,Reed,2013,dana@example.com,615-555-0100\n"
    "Owen,Reed,2015,dana@example.com,615-555-0100\n"
)


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def _family(client, second_parent=False):
    made = client.post("/api/orgs", json={"name": "Club", "sport": "lacrosse", "director_name": "Joel"}).json()
    director = {"Authorization": f"Bearer {made['director']['token']}"}
    team = client.post("/api/teams", json={"name": "2031 Red"}, headers=director).json()
    res = client.post("/api/coach/roster/import", headers=director,
                      json={"content": CSV, "team_id": team["id"]}).json()
    inv = {i["athlete_name"]: i for i in res["guardian_invites"]}
    conn = api_module._store.conn
    first = G.redeem_invite(conn, inv["Mason Reed"]["code"], "Dana Reed", "dana@example.com", phone="615-555-0100")
    G.link_existing(conn, inv["Owen Reed"]["code"], first["guardian_id"])
    kids = {a["display_name"]: a["athlete_id"] for a in res["created"]}
    for kid in kids.values():
        G.set_consent(conn, kid, first["guardian_id"], G.Scope.PARTICIPATION, True)
    out = {"director": director, "kids": kids, "gid": first["guardian_id"],
           "h": {"Authorization": f"Bearer {first['token']}"}}
    if second_parent:
        extra = G.create_invite(conn, kids["Mason Reed"], int(made["director"]["id"]) if "id" in made["director"] else 1,
                                email="chris@example.com")
        second = G.redeem_invite(conn, extra["code"], "Chris Reed", "chris@example.com")
        out["gid2"] = second["guardian_id"]
    return out


def _exists(table, col, val):
    return api_module._store.conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {col} = ?", (val,)).fetchone()["n"]


class TestDeletingYourOwnAccount:

    def test_it_needs_the_word_delete(self, client):
        f = _family(client)
        r = client.post("/api/guardians/erase-account", json={"confirm": "yes"}, headers=f["h"])
        assert r.status_code == 400
        assert _exists("users", "id", f["gid"]) == 1

    def test_the_account_and_its_contact_details_go(self, client):
        f = _family(client)
        r = client.post("/api/guardians/erase-account", json={"confirm": "DELETE"}, headers=f["h"])
        assert r.status_code == 200 and r.json()["deleted"] is True
        assert _exists("users", "id", f["gid"]) == 0
        assert _exists("guardians", "guardian_id", f["gid"]) == 0
        assert _exists("guardian_contacts", "guardian_id", f["gid"]) == 0

    def test_the_sign_in_stops_working(self, client):
        f = _family(client)
        client.post("/api/guardians/erase-account", json={"confirm": "DELETE"}, headers=f["h"])
        assert client.get("/api/guardians/me", headers=f["h"]).status_code in (401, 403)

    def test_by_default_the_children_stay_but_are_paused(self, client):
        f = _family(client)
        out = client.post("/api/guardians/erase-account", json={"confirm": "DELETE"}, headers=f["h"]).json()
        assert sorted(out["children_paused"]) == ["Mason Reed", "Owen Reed"]
        assert out["children_erased"] == []
        conn = api_module._store.conn
        for kid in f["kids"].values():
            assert _exists("users", "id", kid) == 1, "the child's record is not touched"
            assert G.current_consents(conn, kid).get(G.Scope.PARTICIPATION, False) is False, \
                "no parent is left to say yes, so the child cannot train"

    def test_a_paused_child_shows_in_the_program_as_needing_a_parent(self, client):
        from offdays import funnel
        f = _family(client)
        client.post("/api/guardians/erase-account", json={"confirm": "DELETE"}, headers=f["h"])
        stages = {a["display_name"]: a["stage"] for a in funnel.funnel(
            api_module._store.conn, 1)["athletes"]}
        assert stages["Mason Reed"] in ("no_parent", "invite_unsent", "invited")

    def test_also_deleting_the_children_removes_them_entirely(self, client):
        f = _family(client)
        out = client.post("/api/guardians/erase-account",
                          json={"confirm": "DELETE", "also_children": True}, headers=f["h"]).json()
        assert sorted(out["children_erased"]) == ["Mason Reed", "Owen Reed"]
        for kid in f["kids"].values():
            assert _exists("users", "id", kid) == 0

    def test_a_child_with_another_parent_is_never_deleted_by_the_first(self, client):
        f = _family(client, second_parent=True)
        out = client.post("/api/guardians/erase-account",
                          json={"confirm": "DELETE", "also_children": True}, headers=f["h"]).json()
        assert "Mason Reed" in out["children_kept"], "Chris has not asked for anything to be deleted"
        assert "Owen Reed" in out["children_erased"], "Owen had only this parent"
        assert _exists("users", "id", f["kids"]["Mason Reed"]) == 1
        assert _exists("users", "id", f["kids"]["Owen Reed"]) == 0
        assert _exists("users", "id", f["gid2"]) == 1

    def test_a_remaining_parent_keeps_the_childs_consent(self, client):
        f = _family(client, second_parent=True)
        client.post("/api/guardians/erase-account", json={"confirm": "DELETE"}, headers=f["h"])
        conn = api_module._store.conn
        assert G.current_consents(conn, f["kids"]["Mason Reed"]).get(G.Scope.PARTICIPATION, False) is True

    def test_the_log_proves_it_without_naming_anyone(self, client):
        f = _family(client)
        client.post("/api/guardians/erase-account", json={"confirm": "DELETE"}, headers=f["h"])
        row = api_module._store.conn.execute(
            "SELECT athlete_ref, scope FROM erasure_log ORDER BY id DESC LIMIT 1").fetchone()
        assert row["scope"] == "guardian_account"
        assert "Dana" not in row["athlete_ref"] and len(row["athlete_ref"]) == 16

    def test_only_a_parent_can_use_it(self, client):
        f = _family(client)
        assert client.post("/api/guardians/erase-account", json={"confirm": "DELETE"},
                           headers=f["director"]).status_code in (401, 403)
        assert client.post("/api/guardians/erase-account", json={"confirm": "DELETE"}).status_code in (401, 403)

    def test_a_non_parent_id_is_refused_by_the_function(self, client):
        f = _family(client)
        with pytest.raises(G.GuardianError):
            G.erase_guardian(api_module._store.conn, f["kids"]["Mason Reed"])
