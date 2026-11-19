"""The coach page re-reads itself every couple of minutes, and never while someone is in the middle of something."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "offdays" / "web" / "static"
NODE = shutil.which("node")
BASE = dict(hidden=False, online=True, running=False, editing=False, typed=False, recentlyActive=False, versionChanged=False)


def decide(**over) -> str:
    if not NODE:
        pytest.skip("node is not installed")
    state = {**BASE, **over}
    script = (f"import * as m from {json.dumps((STATIC / 'autorefresh.js').as_uri())};"
              f"process.stdout.write(JSON.stringify(m.decide({json.dumps(state)})));")
    out = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(out.stdout)


def const(name: str):
    if not NODE:
        pytest.skip("node is not installed")
    script = (f"import * as m from {json.dumps((STATIC / 'autorefresh.js').as_uri())};process.stdout.write(JSON.stringify(m.{name}));")
    return json.loads(subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, check=True).stdout)


class TestWhenItRefreshes:
    def test_it_refreshes_when_the_page_is_open_and_nobody_is_doing_anything(self):
        assert decide() == "refresh"

    def test_every_couple_of_minutes(self):
        assert const("EVERY_MS") == 120_000

    @pytest.mark.parametrize("over", [{"hidden": True}, {"online": False}, {"running": True}])
    def test_not_when_hidden_offline_or_already_running(self, over):
        assert decide(**over) == "skip"

    @pytest.mark.parametrize("over", [{"editing": True}, {"recentlyActive": True}])
    def test_not_while_someone_is_typing_or_has_just_clicked(self, over):
        assert decide(**over) == "skip"

    def test_typed_words_alone_do_not_stop_a_data_refresh_but_do_stop_a_reload(self):
        assert decide(typed=True) == "refresh"          # the redraws keep their own boxes; only a reload would lose the words
        assert decide(typed=True, versionChanged=True) == "banner"


class TestANewVersion:
    def test_an_idle_page_reloads_itself(self):
        assert decide(versionChanged=True) == "reload"

    @pytest.mark.parametrize("over", [{"editing": True}, {"typed": True}, {"recentlyActive": True}])
    def test_a_busy_page_is_offered_a_button_instead(self, over):
        assert decide(versionChanged=True, **over) == "banner"

    @pytest.mark.parametrize("over", [{"hidden": True}, {"online": False}, {"running": True}])
    def test_a_hidden_or_offline_page_does_nothing(self, over):
        assert decide(versionChanged=True, **over) == "skip"


class TestWhereItRuns:
    def test_the_coach_page_refreshes_its_data_after_it_has_loaded(self):
        html = (STATIC / "coach.html").read_text(encoding="utf-8")
        assert "import { keepFresh } from './autorefresh.js';" in html
        assert "await startWizardIfNew(orgs.role === 'director');\n    keepFresh(refreshEverything);" in html.replace("\r\n", "\n")
        body = html.split("async function refreshEverything()")[1].split("\n}\n")[0]
        for call in ("loadTeams()", "loadFamilies()", "loadAll()", "loadParents(IS_DIRECTOR)", "homeLoad()", "/detail`"):
            assert call in body, call

    def test_an_open_team_is_redrawn_only_when_nothing_is_typed_in_it(self):
        html = (STATIC / "coach.html").read_text(encoding="utf-8")
        body = html.split("async function refreshEverything()")[1].split("\n}\n")[0]
        assert "#td-body input:focus" in body and "e.value" in body

    def test_a_refresh_keeps_the_team_someone_had_chosen_in_each_form(self):
        html = (STATIC / "coach.html").read_text(encoding="utf-8")
        assert "const setTeams = (id, html)" in html and "setTeams('import-team', options);" in html
        assert "$('import-team').innerHTML = options;" not in html

    def test_the_parent_page_only_watches_for_a_new_version(self):
        html = (STATIC / "parent.html").read_text(encoding="utf-8")
        assert "keepFresh(() => {}, { dataToo: false });" in html

    def test_the_athlete_and_sign_in_pages_never_reload_themselves(self):
        for page in ("capture.html", "index.html"):
            assert "autorefresh" not in (STATIC / page).read_text(encoding="utf-8"), page

    def test_it_works_offline_too(self):
        assert "'autorefresh.js'," in (STATIC / "sw.js").read_text(encoding="utf-8")


class TestItNeverShowsAnError:
    def test_a_failed_refresh_is_silent_and_retried(self):
        js = (STATIC / "autorefresh.js").read_text(encoding="utf-8")
        assert "catch { /* try again next time; never an error on screen */ }" in js and "finally { running = false; }" in js

    def test_the_build_is_read_from_the_live_endpoint_without_caching(self):
        js = (STATIC / "autorefresh.js").read_text(encoding="utf-8")
        assert "fetch('/api/live', { cache: 'no-store' })" in js
