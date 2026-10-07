"""The program keeps every parent it is told about, and asks before sharing.

A club's parent list is an asset -- sponsors, fundraising, next season --
and it must not depend on which parents happened to tap an invite. So the
roster is the source, phone-only parents count, second parents count, and
an account joins its roster row rather than starting a second list.

Keeping a list and using it for a sponsor are different things. The export
carries each parent's own answer to "may sponsors contact you", off until
they switch it on, because a text to a parent who did not is a
statutory-damages problem (TCPA) rather than a tone problem.
"""
from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import contacts, guardians as G, roster
from offdays.db import connect
from offdays.store import Store

CSV = (
    "Last Name,First Name,Birth Year,Parent Name,Parent Email,Parent Phone,"
    "Parent 2 Name,Parent 2 Email,Parent 2 Phone\n"
    "Pierce,Jordan,2012,Dana Pierce,dana@example.com,615 555 0100,"
    "Lee Pierce,lee@example.com,\n"
    "Rivera,Sam,2012,Maria Rivera,,615 555 0200,,,\n"
    "Okafor,Lee,2012,,,,,,\n"
)


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "c.db"))


@pytest.fixture
def program(store):
    org = store.create_org("Nashville Dogs")
    coach = store.create_user(org, "coach", "Coach Mike")
    team = store.create_team(org, "2031 Red")
    return {"org": org, "coach": coach, "team": team}


def import_roster(store, program, text=CSV):
    plan = store.resolve_import(program["org"], roster.parse(text))
    return store.apply_import(program["org"], program["team"]["id"], plan, program["coach"]["id"])


class TestTheRosterIsTheSource:
    def test_every_named_parent_is_kept_including_phone_only_and_second_parents(self, store, program):
        import_roster(store, program)
        rows = contacts.for_org(store.conn, program["org"])
        by = {(r["athlete_name"], r["name"]): r for r in rows}
        assert set(by) == {("Jordan Pierce", "Dana Pierce"), ("Jordan Pierce", "Lee Pierce"),
                           ("Sam Rivera", "Maria Rivera")}
        assert by[("Jordan Pierce", "Dana Pierce")]["phone"] == "615 555 0100"
        assert by[("Jordan Pierce", "Lee Pierce")]["email"] == "lee@example.com"
        maria = by[("Sam Rivera", "Maria Rivera")]
        assert maria["email"] == "" and maria["phone"] == "615 555 0200"

    def test_a_phone_only_parent_gets_no_invite_but_is_still_on_the_list(self, store, program):
        result = import_roster(store, program)
        assert [i["athlete_name"] for i in result["guardian_invites"]] == ["Jordan Pierce"]
        assert any(r["name"] == "Maria Rivera" for r in contacts.for_org(store.conn, program["org"]))

    def test_a_re_import_fills_in_rather_than_duplicating_or_blanking(self, store, program):
        import_roster(store, program)
        again = (
            "Last Name,First Name,Birth Year,Parent Name,Parent Email,Parent Phone\n"
            "Pierce,Jordan,2012,,dana@example.com,615 555 0199\n"
        )
        import_roster(store, program, again)
        rows = [r for r in contacts.for_org(store.conn, program["org"]) if r["email"] == "dana@example.com"]
        assert len(rows) == 1
        assert rows[0]["name"] == "Dana Pierce"       # not blanked
        assert rows[0]["phone"] == "615 555 0199"     # updated

    def test_a_jersey_number_in_the_phone_column_is_not_a_phone(self):
        assert roster.parse_phone("14") is None
        assert roster.parse_phone("615-555-0100") == "615-555-0100"
        assert roster.parse_phone("(615) 555 0100") == "(615) 555 0100"


class TestAnAccountJoinsItsRosterRow:
    def test_redeeming_by_the_roster_email_links_rather_than_adds(self, store, program):
        result = import_roster(store, program)
        invite = result["guardian_invites"][0]
        before = len(contacts.for_org(store.conn, program["org"]))
        g = G.redeem_invite(store.conn, invite["code"], "Dana P.", "dana@example.com", phone="615 555 0100")
        rows = contacts.for_org(store.conn, program["org"])
        assert len(rows) == before
        dana = next(r for r in rows if r["email"] == "dana@example.com")
        assert dana["has_account"] is True
        assert dana["name"] == "Dana P."

    def test_a_parent_the_roster_never_named_is_added_on_signup(self, store, program):
        import_roster(store, program)
        lee = store.conn.execute("SELECT id FROM users WHERE display_name = 'Lee Okafor'").fetchone()["id"]
        inv = G.create_invite(store.conn, lee, program["coach"]["id"])
        G.redeem_invite(store.conn, inv["code"], "Ada Okafor", "ada@example.com", phone="615 555 0300")
        row = next(r for r in contacts.for_org(store.conn, program["org"]) if r["email"] == "ada@example.com")
        assert row["athlete_name"] == "Lee Okafor" and row["phone"] == "615 555 0300"
        assert row["source"] == "invite" and row["has_account"] is True
        assert store.conn.execute("SELECT phone FROM users WHERE email = 'ada@example.com'").fetchone()["phone"] == "615 555 0300"


class TestSponsorUseIsTheParentsCall:
    def test_marketing_is_a_consent_scope_and_off_by_default(self, store, program):
        import_roster(store, program)
        assert G.Scope.MARKETING in G.SCOPE_LABELS
        rows = contacts.for_org(store.conn, program["org"])
        assert all(r["marketing"] is None for r in rows)
        assert contacts.summary(rows)["marketing_not_asked"] == len(rows)

    def test_the_parents_own_switch_shows_up_in_the_export(self, store, program):
        result = import_roster(store, program)
        invite = result["guardian_invites"][0]
        g = G.redeem_invite(store.conn, invite["code"], "Dana Pierce", "dana@example.com")
        G.set_consent(store.conn, invite["athlete_id"], g["guardian_id"], G.Scope.MARKETING, True)
        rows = contacts.for_org(store.conn, program["org"])
        assert {r["name"]: r["marketing"] for r in rows if r["athlete_name"] == "Jordan Pierce"} == {
            "Dana Pierce": True, "Lee Pierce": True}
        assert contacts.summary(rows)["marketing_yes"] == 2
        G.set_consent(store.conn, invite["athlete_id"], g["guardian_id"], G.Scope.MARKETING, False)
        assert contacts.summary(contacts.for_org(store.conn, program["org"]))["marketing_no"] == 2

    def test_the_csv_reads_yes_no_not_asked(self, store, program):
        import_roster(store, program)
        text = contacts.to_csv(contacts.for_org(store.conn, program["org"]))
        rows = list(csv.DictReader(io.StringIO(text)))
        assert {r["marketing"] for r in rows} == {"not asked"}
        assert {r["name"] for r in rows} == {"Dana Pierce", "Lee Pierce", "Maria Rivera"}
        assert next(r for r in rows if r["name"] == "Dana Pierce")["teams"] == "2031 Red"

    def test_erasing_the_athlete_takes_the_contact_rows_with_it(self, store, program):
        import_roster(store, program)
        jordan = store.conn.execute("SELECT id FROM users WHERE display_name = 'Jordan Pierce'").fetchone()["id"]
        G.erase_athlete(store.conn, jordan, scope="all")
        assert not any(r["athlete_name"] == "Jordan Pierce" for r in contacts.for_org(store.conn, program["org"]))


class TestOverTheWire:
    @pytest.fixture
    def client(self, tmp_path):
        api_module._store = Store(connect(tmp_path / "api.db"))
        yield TestClient(api_module.app)
        api_module._store = None

    @pytest.fixture
    def org(self, client):
        made = client.post("/api/orgs", json={"name": "Nashville Dogs", "director_name": "Dir K"}).json()
        director = {"Authorization": f"Bearer {made['director']['token']}"}
        team = client.post("/api/teams", json={"name": "2031 Red", "season": "2027"}, headers=director).json()
        client.post("/api/coach/roster/import", json={"content": CSV, "team_id": team["id"]}, headers=director)
        coach = api_module._store.create_user(made["org_id"], "coach", "Coach B")
        return {"director": director, "coach": {"Authorization": f"Bearer {coach['token']}"}}

    def test_a_director_gets_the_list_and_the_csv(self, client, org):
        body = client.get("/api/org/parents", headers=org["director"]).json()
        assert body["summary"]["parents"] == 3
        assert body["summary"]["with_phone"] == 2
        assert "marketing" in body["note"]
        res = client.get("/api/org/parents?format=csv", headers=org["director"])
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/csv")
        assert "Dana Pierce" in res.text

    def test_a_coach_does_not(self, client, org):
        assert client.get("/api/org/parents", headers=org["coach"]).status_code == 403

    def test_sign_up_takes_a_phone(self, client, org):
        inv = client.get("/api/coach/guardian-invites", headers=org["director"]).json()["invites"]
        # The invite list does not return codes; issue a fresh one to redeem.
        aid = inv[0]["athlete_id"]
        fresh = client.post("/api/coach/guardian-invites", json={"athlete_id": aid}, headers=org["director"]).json()
        res = client.post("/api/guardians/redeem", json={
            "code": fresh["code"], "display_name": "Dana Pierce",
            "email": "dana@example.com", "phone": "615 555 0100"})
        assert res.status_code == 201
        body = client.get("/api/org/parents", headers=org["director"]).json()
        assert body["summary"]["with_account"] == 1

    def test_the_template_names_the_parent_columns(self, client):
        t = client.get("/api/coach/roster/template").json()
        assert "Parent Phone" in t["content"] and "Parent 2 Email" in t["content"]
