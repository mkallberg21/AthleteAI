"""A roster typed in by hand goes through exactly the road an uploaded file does.

The page builds a CSV from what the coach typed (offdays/web/static/roster_entry.js) and sends it to the same preview
and the same import. So nothing about families is special-cased for typing, and these tests prove that stays true,
for every sport the product knows:

  * no kid code is created or shown -- the parent is invited first, the child gets a link from the parent;
  * the program's email hold still holds, so typing a roster emails nobody until the director releases it;
  * a typed duplicate is flagged and counted once;
  * names that are awkward to type (apostrophes, commas, accents, a leading =) survive;
  * a name that would run as a spreadsheet formula is written out as plain text in every export.

The CSV used here is produced by the real roster_entry.js (run through node) so the browser code and the server
cannot drift apart without a test failing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import invites, mailer, positions
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store

STATIC = Path(__file__).resolve().parents[1] / "offdays" / "web" / "static"
NODE = shutil.which("node")

ROWS = [
    {"first": "Sam", "last": "O'Brien", "year": "2013", "email": "pat@example.com", "phone": "615-555-0101", "jersey": "7", "position": ""},
    {"first": "Ana", "last": "García-Núñez", "year": "2013", "email": "ana.mom@example.com", "phone": "", "jersey": "", "position": ""},
    {"first": "Lee", "last": "Smith, Jr.", "year": "2013", "email": "", "phone": "", "jersey": "", "position": ""},
    {"first": "Jo", "last": 'Say "Hi"', "year": "2013", "email": "jo@example.com", "phone": "", "jersey": "", "position": ""},
]


def make_csv(rows: list[dict]) -> str:
    """The CSV the page would send, built by the page's own module."""
    if not NODE:
        pytest.skip("node is not installed")
    script = (
        f"import {{ buildCsv }} from {json.dumps((STATIC / 'roster_entry.js').as_uri())};"
        f"const rows = JSON.parse(process.argv[1]);"
        f"process.stdout.write(buildCsv(rows));"
    )
    out = subprocess.run([NODE, "--input-type=module", "-e", script, json.dumps(rows)],
                         capture_output=True, text=True, encoding="utf-8", check=True)
    return out.stdout


@pytest.fixture
def client(tmp_path, monkeypatch):
    patched = replace(CONFIG, smtp_host="smtp.test", app_base_url="https://app.0ffdays.com")
    for mod in (invites, mailer):
        monkeypatch.setattr(mod, "CONFIG", patched)
    monkeypatch.setattr(api_module, "CONFIG", patched)
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def program(client, sport="lacrosse"):
    made = client.post("/api/orgs", json={"name": "Typed Club", "sport": sport, "accept_terms": True, "director_name": "Joel"}).json()
    h = {"Authorization": f"Bearer {made['director']['token']}"}
    team = client.post("/api/teams", json={"name": "2013 Red"}, headers=h).json()
    return {"org_id": made["org_id"], "h": h, "team": team["id"]}


def outbox():
    return api_module._store.conn.execute("SELECT to_email, kind FROM email_outbox").fetchall()


def do_import(client, p, csv_text):
    r = client.post("/api/coach/roster/import", headers=p["h"], json={"content": csv_text, "team_id": p["team"]})
    assert r.status_code == 201, r.text
    return r.json()


def athletes():
    return api_module._store.conn.execute(
        "SELECT u.id, u.display_name, u.birth_year, m.jersey, m.position FROM users u "
        "LEFT JOIN team_members m ON m.user_id = u.id WHERE u.role = 'athlete' ORDER BY u.id").fetchall()


class TestTheTypedCsvReadsLikeAFile:

    def test_the_preview_sees_every_player_and_every_parent(self, client):
        p = program(client)
        plan = client.post("/api/coach/roster/preview", headers=p["h"], json={"content": make_csv(ROWS)}).json()
        assert plan["summary"]["create"] == 4
        assert plan["summary"]["with_guardian_email"] == 3, "the one with no parent email is the one that cannot start"
        names = [a["display_name"] for a in plan["athletes"]]
        assert names == ["Sam O'Brien", "Ana García-Núñez", "Lee Smith, Jr.", 'Jo Say "Hi"']

    def test_every_column_arrives_where_it_should(self, client):
        p = program(client)
        do_import(client, p, make_csv(ROWS[:1]))
        a = athletes()[0]
        assert (a["display_name"], a["birth_year"], str(a["jersey"])) == ("Sam O'Brien", 2013, "7")
        board = json.dumps(client.get("/api/coach/families", headers=p["h"]).json())
        assert "pat@example.com" in board, "the parent the coach typed is the parent the program holds"

    def test_the_same_player_typed_twice_is_one_player(self, client):
        p = program(client)
        twice = ROWS[:1] + ROWS[:1]
        plan = client.post("/api/coach/roster/preview", headers=p["h"], json={"content": make_csv(twice)}).json()
        assert plan["summary"]["create"] == 1
        assert any("Same name" in m for a in plan["athletes"] for m in a["problems"]), "the second copy is skipped, with the reason"
        assert [a["action"] for a in plan["athletes"]] == ["create", "skip"]

    def test_importing_the_same_typed_roster_twice_adds_nobody_new(self, client):
        p = program(client)
        do_import(client, p, make_csv(ROWS))
        n = len(athletes())
        do_import(client, p, make_csv(ROWS))
        assert len(athletes()) == n == 4

    def test_a_blank_row_is_not_a_player(self):
        text = make_csv([{**ROWS[0]}, {k: "" for k in ROWS[0]}])
        assert len(text.strip().split("\n")) == 2


class TestFamiliesComeFirst:

    def test_no_kid_code_is_created_or_returned(self, client):
        p = program(client)
        res = do_import(client, p, make_csv(ROWS))
        assert not res.get("slips"), "typing a roster must not print codes for children"
        flat = json.dumps(res)
        assert "athlete_code" not in flat and "sign_in_code" not in flat
        # the children cannot sign in with anything yet: no code was issued
        rows = api_module._store.conn.execute("SELECT claim_code_hash FROM users WHERE role = 'athlete'").fetchall()
        assert len(rows) == 4 and all(r["claim_code_hash"] is None for r in rows)

    def test_each_parent_with_an_email_gets_an_invite_and_the_one_without_does_not(self, client):
        p = program(client)
        res = do_import(client, p, make_csv(ROWS))
        invited = {i["email"] if "email" in i else i.get("to") for i in res["guardian_invites"]}
        flat = json.dumps(res["guardian_invites"])
        for mail in ("pat@example.com", "ana.mom@example.com", "jo@example.com"):
            assert mail in flat, mail
        assert len(res["guardian_invites"]) == 3

    def test_typing_a_roster_emails_nobody_while_the_program_is_held(self, client):
        p = program(client)
        res = do_import(client, p, make_csv(ROWS))
        assert outbox() == []
        assert all(i["emailed"] is False for i in res["guardian_invites"])

    def test_the_family_board_shows_them_waiting_on_their_parent(self, client):
        p = program(client)
        do_import(client, p, make_csv(ROWS))
        board = client.get("/api/coach/families", headers=p["h"]).json()
        rows = board["families"] if "families" in board else board.get("athletes", [])
        assert len(rows) == 4
        assert all(r["stage"] in {"no_parent", "invite_pending", "invite_ready"} or "parent" in r["stage"] or "invite" in r["stage"]
                   for r in rows), [r["stage"] for r in rows]


SPORT_KEYS = sorted(positions.BY_SPORT)


class TestEverySport:

    @pytest.mark.parametrize("sport", SPORT_KEYS)
    def test_a_typed_roster_imports_in_every_sport(self, client, sport):
        p = program(client, sport)
        rows = [dict(r) for r in ROWS]
        res = do_import(client, p, make_csv(rows))
        assert len(athletes()) == 4, sport
        assert len(res["guardian_invites"]) == 3, sport
        assert outbox() == [], sport
        assert not res.get("slips"), sport

    @pytest.mark.parametrize("sport", SPORT_KEYS)
    def test_a_position_typed_for_a_sport_is_read_for_that_sport(self, client, sport):
        first = positions.BY_SPORT[sport][0]
        label = getattr(first, "label", None) or getattr(first, "name", None) or str(first)
        p = program(client, sport)
        rows = [{**ROWS[0], "position": label}]
        plan = client.post("/api/coach/roster/preview", headers=p["h"], json={"content": make_csv(rows)}).json()
        a = plan["athletes"][0]
        assert not any("position" in m.lower() and "not" in m.lower() for m in a["warnings"] + a["problems"]), (sport, label, a)


class TestAnAwkwardNameIsStillOnePlayer:

    @pytest.mark.parametrize("last", ["O'Brien", "Smith, Jr.", 'Say "Hi"', "García-Núñez", "Müller", "van der Berg", "李"])
    def test_it_round_trips(self, client, last):
        p = program(client)
        do_import(client, p, make_csv([{**ROWS[0], "last": last}]))
        assert athletes()[0]["display_name"] == f"Sam {last}"

    def test_a_name_that_is_a_formula_is_stored_as_typed_but_exported_as_text(self, client):
        p = program(client)
        evil = {**ROWS[0], "first": '=HYPERLINK("http://evil","x")', "last": "Test"}
        do_import(client, p, make_csv([evil]))
        out = client.get("/api/org/parents?format=csv", headers=p["h"]).text
        assert "HYPERLINK" in out
        for line in out.splitlines():
            assert not line.startswith("="), line
            assert ',=' not in line and '"=' not in line, line


class TestThePageIsWiredToIt:

    def test_the_coach_page_imports_the_module_and_offers_the_way_in(self):
        html = (STATIC / "coach.html").read_text(encoding="utf-8")
        assert "from './roster_entry.js'" in html
        assert 'data-source="type"' in html and 'id="src-type"' in html
        assert "previewFile(buildCsv(RT))" in html, "it must go through the same preview an uploaded file does"

    def test_the_offline_shell_keeps_the_module(self):
        sw = (STATIC / "sw.js").read_text(encoding="utf-8")
        assert "'roster_entry.js'" in sw

    def test_the_module_exists_and_is_served(self, client):
        r = client.get("/app/roster_entry.js")
        assert r.status_code == 200 and "buildCsv" in r.text
