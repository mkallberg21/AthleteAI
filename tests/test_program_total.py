"""While rosters go in, the director sees ONE dollar amount for the whole program, never one per team."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "offdays" / "web" / "static"
NODE = shutil.which("node")


def total(teams, invoice):
    if not NODE:
        pytest.skip("node is not installed")
    script = (f"import * as m from {json.dumps((STATIC / 'setup_flow.js').as_uri())};"
              f"process.stdout.write(JSON.stringify(m.programTotal({json.dumps(teams)}, {json.dumps(invoice)})));")
    return json.loads(subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True,
                                     encoding="utf-8", check=True).stdout)


TEAMS = [{"name": "2031 Red", "roster": 4}, {"name": "2032 Blue", "roster": 3}, {"name": "2033 Gold", "roster": 5}]
INV = {"athletes": 12, "season_set": True, "total_display": "$600.00"}


class TestTheTotalLine:
    def test_it_is_one_total_for_every_team_together(self):
        line = total(TEAMS, INV)
        assert "12 players on 3 teams" in line and "$600.00" in line and "not per team" in line

    def test_there_is_exactly_one_dollar_amount_and_no_team_name_in_it(self):
        line = total(TEAMS, INV)
        assert line.count("$") == 1
        assert not any(t["name"] in line for t in TEAMS)

    def test_nothing_is_shown_until_someone_is_on_a_roster(self):
        assert total([{"name": "2031 Red", "roster": 0}], {"athletes": 0, "season_set": True, "total_display": "$0.00"}) == ""
        assert total([], None) == ""

    def test_without_season_dates_it_says_to_set_them_and_shows_no_made_up_number(self):
        line = total(TEAMS, {"athletes": 12, "season_set": False, "total_display": "$0.00"})
        assert "Set the season dates" in line and "$" not in line

    def test_one_player_and_one_team_read_properly(self):
        line = total([{"name": "A", "roster": 1}], {"athletes": 1, "season_set": True, "total_display": "$50.00"})
        assert "1 player on 1 team." in line

    def test_a_coach_who_is_refused_the_invoice_still_gets_no_dollar_amount(self):
        line = total(TEAMS, None)
        assert "$" not in line


class TestWhereItShows:
    HTML = (STATIC / "coach.html").read_text(encoding="utf-8")

    def test_it_is_fed_by_the_program_wide_invoice_and_shown_to_a_director_on_the_roster_steps_only(self):
        assert "api('/api/org/invoice').catch(() => null)" in self.HTML and "programTotal(teams.teams, invoice)" in self.HTML
        assert "IS_DIRECTOR && ['roster', 'release', 'send'].includes(s.key)" in self.HTML

    def test_it_is_redrawn_wherever_the_step_is_redrawn(self):
        assert self.HTML.count("wizardShowTotal(s, st);") == 2

    def test_the_team_rows_carry_no_dollar_amount(self):
        row = self.HTML.split("function renderTeamsHome(teams) {", 1)[1].split("$('tm-list').addEventListener", 1)[0]
        assert "$" not in row.replace("${", "").replace("$(", "")
