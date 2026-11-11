"""The director's one-step setup: many teams at once, one coach per person, and the page wired to it.

The setup steps add nothing to the server. The page runs each team through POST /api/teams and each coach through
POST /api/coach/staff, the same two routes the one-team form uses. These tests prove that the pieces the page relies
on behave the way the page assumes, and that the page really is built the way the flow says:

  * the page's own setup_flow.js (run through node) decides which teams and coaches to send;
  * one coach on several teams is one person with one sign-in, matched on email, never on name;
  * two different people who share a name stay two people (a wrong merge would hand a stranger another coach's teams);
  * a coach cannot create teams or coaches (director only);
  * the setup shows one step at a time, in the agreed order, and the offline shell keeps the new module.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays.db import connect
from offdays.store import Store

STATIC = Path(__file__).resolve().parents[1] / "offdays" / "web" / "static"
NODE = shutil.which("node")


def run_js(body: str, arg) -> object:
    """Run the page's real setup_flow.js and return what it printed as JSON."""
    if not NODE:
        pytest.skip("node is not installed")
    script = (
        f"import * as m from {json.dumps((STATIC / 'setup_flow.js').as_uri())};"
        f"const arg = JSON.parse(process.argv[1]);"
        f"process.stdout.write(JSON.stringify({body}));"
    )
    out = subprocess.run([NODE, "--input-type=module", "-e", script, json.dumps(arg)],
                         capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(out.stdout)


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def program(client, name="Setup Club", sport="lacrosse"):
    made = client.post("/api/orgs", json={"name": name, "sport": sport, "accept_terms": True,
                                          "director_name": "Joel"}).json()
    return {"h": {"Authorization": f"Bearer {made['director']['token']}"}, "org_id": made["org_id"]}


def send_teams(client, p, names):
    """What the page does for each name from parseTeamNames."""
    for n in names:
        r = client.post("/api/teams", json={"name": n, "daily_wall_ball": 0, "daily_shots": 0}, headers=p["h"])
        assert r.status_code == 201, r.text


def send_coaches(client, p, rows):
    """What the page does: coachCalls over the typed rows, then one request per person."""
    plan = run_js("m.coachCalls(arg)", rows)
    out = []
    for call in plan["calls"]:
        r = client.post("/api/coach/staff", json=call, headers=p["h"])
        assert r.status_code == 201, r.text
        out.append(r.json())
    return plan, out


def teams(client, p):
    return client.get("/api/coach/teams", headers=p["h"]).json()["teams"]


class TestManyTeamsAtOnce:

    def test_twelve_names_become_twelve_teams(self, client):
        p = program(client)
        names = [f"20{31 + i // 2} {'Red' if i % 2 == 0 else 'Blue'}" for i in range(12)]
        plan = run_js("m.parseTeamNames(arg, [])", "\n".join(names))
        assert plan["names"] == names and plan["left"] == []
        send_teams(client, p, plan["names"])
        assert sorted(t["name"] for t in teams(client, p)) == sorted(names)

    def test_a_pasted_list_with_repeats_makes_each_team_once(self, client):
        p = program(client)
        plan = run_js("m.parseTeamNames(arg, [])", "2031 Red\n2031 red\n\nU9 Gold, U9 Gold ; U11 A")
        send_teams(client, p, plan["names"])
        assert sorted(t["name"] for t in teams(client, p)) == ["2031 Red", "U11 A", "U9 Gold"]
        assert len(plan["left"]) == 2

    def test_names_the_program_already_has_are_not_sent_again(self, client):
        p = program(client)
        send_teams(client, p, ["2031 Red"])
        have = [t["name"] for t in teams(client, p)]
        plan = run_js("m.parseTeamNames(arg[0], arg[1])", ["2031 RED\n2032 Red", have])
        assert plan["names"] == ["2032 Red"]
        assert "already a team" in plan["left"][0]["why"]

    def test_a_team_made_this_way_is_the_same_as_one_made_by_the_one_team_form(self, client):
        p = program(client)
        send_teams(client, p, ["2031 Red"])
        client.post("/api/teams", json={"name": "2031 Blue"}, headers=p["h"])
        a, b = teams(client, p)
        assert set(a) == set(b), "both routes produce the same shape"
        assert a["join_code"] and b["join_code"]

    def test_a_coach_cannot_create_teams(self, client):
        p = program(client)
        send_teams(client, p, ["2031 Red"])
        r = client.post("/api/coach/staff", json={"display_name": "Sam", "email": "sam@example.com",
                                                  "team_ids": [teams(client, p)[0]["id"]]}, headers=p["h"])
        coach_h = {"Authorization": f"Bearer {r.json()['code']}"}
        again = client.post("/api/coach/staff", json={"display_name": "X", "email": "x@example.com"}, headers=coach_h)
        assert again.status_code == 403, "only a director adds coaches"
        assert client.post("/api/teams", json={"name": "Sneaky", "coach_name": "Y"}, headers=coach_h).status_code == 403


class TestOneCoachManyTeams:

    def _rows(self, ids, who):
        return [{"team_id": ids[i], "name": n, "email": e} for i, (n, e) in who.items()]

    def test_the_same_email_on_three_teams_is_one_coach(self, client):
        p = program(client)
        send_teams(client, p, ["A", "B", "C", "D"])
        ids = [t["id"] for t in teams(client, p)]
        plan, out = send_coaches(client, p, self._rows(ids, {
            0: ("Sam Hill", "sam@example.com"), 1: ("Sam Hill", "SAM@example.com"), 2: ("S. Hill", "sam@example.com "),
            3: ("Pat Roe", "pat@example.com")}))
        assert len(plan["calls"]) == 2 and len(out) == 2
        by_name = {t["name"]: t["coaches"] for t in teams(client, p)}
        assert by_name["A"] == by_name["B"] == by_name["C"] == "Sam Hill"
        assert by_name["D"] == "Pat Roe"
        staff = client.get("/api/coach/staff", headers=p["h"]).json()
        people = staff["staff"] if isinstance(staff, dict) and "staff" in staff else staff
        assert sum(1 for u in people if "Sam" in u["display_name"]) == 1, "one account, one sign-in code"

    def test_saving_again_later_adds_the_team_to_the_same_person(self, client):
        p = program(client)
        send_teams(client, p, ["A", "B"])
        ids = [t["id"] for t in teams(client, p)]
        send_coaches(client, p, [{"team_id": ids[0], "name": "Sam Hill", "email": "sam@example.com"}])
        _, out = send_coaches(client, p, [{"team_id": ids[1], "name": "Sam Hill", "email": "sam@example.com"}])
        assert out[0]["reused"] is True and out[0]["code"] is None, "no second code for the same person"
        assert {t["name"]: t["coaches"] for t in teams(client, p)} == {"A": "Sam Hill", "B": "Sam Hill"}

    def test_two_people_with_one_name_stay_two_people(self, client):
        p = program(client)
        send_teams(client, p, ["A", "B"])
        ids = [t["id"] for t in teams(client, p)]
        plan, out = send_coaches(client, p, self._rows(ids, {0: ("Alex Kim", "a@example.com"), 1: ("Alex Kim", "b@example.com")}))
        assert len(plan["calls"]) == 2
        assert out[0]["user_id"] != out[1]["user_id"]
        assert out[0]["code"] and out[1]["code"] and out[0]["code"] != out[1]["code"]

    def test_a_coach_signs_in_and_sees_only_their_own_teams(self, client):
        p = program(client)
        send_teams(client, p, ["A", "B", "C"])
        ids = [t["id"] for t in teams(client, p)]
        _, out = send_coaches(client, p, self._rows(ids, {0: ("Sam", "s@example.com"), 1: ("Sam", "s@example.com"), 2: ("Pat", "p@example.com")}))
        sam_h = {"Authorization": f"Bearer {out[0]['code']}"}
        seen = sorted(t["name"] for t in client.get("/api/coach/teams", headers=sam_h).json()["teams"])
        assert seen == ["A", "B"], "a coach never sees a team they were not given"

    def test_an_email_that_cannot_work_is_never_sent(self, client):
        plan = run_js("m.coachCalls(arg)", [{"team_id": 1, "name": "Sam", "email": "not-an-email"},
                                            {"team_id": 2, "name": "Pat", "email": ""},
                                            {"team_id": 3, "name": "", "email": "x@example.com"}])
        assert plan["calls"] == [] and len(plan["problems"]) == 3

    def test_every_sport_goes_the_same_way(self, client):
        for sport in ("lacrosse", "basketball", "soccer", "volleyball", "football"):
            p = program(client, name=f"{sport} club", sport=sport)
            send_teams(client, p, ["U12 A", "U12 B"])
            ids = [t["id"] for t in teams(client, p)]
            _, out = send_coaches(client, p, self._rows(ids, {0: ("Sam", "s@example.com"), 1: ("Sam", "s@example.com")}))
            assert len(out) == 1, sport
            assert all(t["coaches"] == "Sam" for t in teams(client, p)), sport


class TestTheFlowIsWhatWeSaidItIs:

    HTML = (STATIC / "coach.html").read_text(encoding="utf-8")

    def _director_steps(self) -> list[str]:
        block = self.HTML.split("const WIZARD_STEPS = [", 1)[1].split("];", 1)[0]
        import re
        return re.findall(r"key: '([a-z]+)'", block)

    def test_the_order_is_one_question_at_a_time(self):
        assert self._director_steps() == [
            "code", "contact", "badge", "season", "teams", "coaches", "roster", "release", "send"]

    def test_teams_and_coaches_use_the_wizard_only_cards_not_the_one_team_form(self):
        block = self.HTML.split("const WIZARD_STEPS = [", 1)[1].split("];", 1)[0]
        assert "card: 'bulk-teams-card'" in block and "card: 'bulk-coaches-card'" in block
        assert "card: 'teams-card'" not in block, "the one-step flow must not show the whole Teams card"

    def test_the_two_new_cards_start_hidden_and_return_hidden(self):
        assert 'class="card card--wide hidden" id="bulk-teams-card"' in self.HTML
        assert 'class="card card--wide hidden" id="bulk-coaches-card"' in self.HTML
        assert "id === 'bulk-teams-card' || id === 'bulk-coaches-card'" in self.HTML

    def test_the_page_sends_each_team_and_each_person_through_the_existing_routes(self):
        assert "api('/api/teams', { method: 'POST'" in self.HTML
        assert "api('/api/coach/staff', { method: 'POST', body: c })" in self.HTML

    def test_coaches_can_wait_and_rosters_cannot(self):
        block = self.HTML.split("const WIZARD_STEPS = [", 1)[1].split("];", 1)[0]
        coaches = block.split("key: 'coaches'", 1)[1].split("key: 'roster'", 1)[0]
        roster = block.split("key: 'roster'", 1)[1].split("key: 'release'", 1)[0]
        assert "optional: true" in coaches
        assert "optional: true" not in roster

    def test_the_email_step_leaves_the_hold_alone(self):
        """The step only shows the hold card. Nothing in the flow releases it for the director."""
        block = self.HTML.split("const WIZARD_STEPS = [", 1)[1].split("];", 1)[0]
        assert "card: 'mailhold-card'" in block and "optional: true" in block.split("key: 'release'", 1)[1].split("}", 1)[0]
        flow = self.HTML.split("// ---------------------------------------------------- setup: many teams", 1)[1].split("// A red star", 1)[0]
        assert "mail-hold" not in flow, "the many-teams code must never touch the email hold"

    def test_the_offline_shell_keeps_the_module(self):
        assert "'setup_flow.js'" in (STATIC / "sw.js").read_text(encoding="utf-8")

    def test_the_module_is_served(self, client):
        r = client.get("/app/setup_flow.js")
        assert r.status_code == 200 and "parseTeamNames" in r.text and "coachCalls" in r.text

    def test_the_page_imports_the_module(self):
        assert "from './setup_flow.js'" in self.HTML
