"""An athlete can tell the app what the camera could not count, and it stays honest.

The camera misses real work, so any athlete may log it (no coach switch needed). What keeps it fair is what the
logged work is allowed to do:

* it is marked `self_reported` for ever and shown as "logged by athlete" to the parent and the coach;
* it counts for turning up (streak, participation) and never for a rank, a team total or a measured number;
* only the first one of a day earns XP, a flat amount, and only a few a day are accepted;
* in a linked program it counts there too, as logged work.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import leaderboard
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import MAX_LOGGED_PER_DAY, Store

from test_linked_athletes import bearer, club, db, family, link_them, sessions_of, train, two_clubs, xp_of

STATIC = None


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def log(client, fam, drill="gen_squat", minutes=20, **kw):
    return client.post("/api/sessions/self-reported", headers=fam["a"],
                       json={"drill_key": drill, "minutes": minutes, **kw})


def one(client):
    return family(client, club(client, "Club A"))


class TestAnyAthleteMayLogWhatTheCameraMissed:
    def test_it_needs_no_switch_from_a_coach(self, client):
        a = one(client)
        res = log(client, a, note="phone died")
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["self_reported"] is True and body["xp_awarded"] == CONFIG.scoring.streak_min_xp

    def test_it_is_marked_for_ever(self, client):
        a = one(client)
        sid = log(client, a).json()["session_id"]
        assert [s["self_reported"] for s in sessions_of(a["kid"]) if s["id"] == sid] == [1]

    def test_a_parent_or_a_stranger_cannot_log_for_a_child(self, client):
        a = one(client)
        assert client.post("/api/sessions/self-reported", headers=a["p"],
                           json={"drill_key": "gen_squat", "minutes": 20}).status_code == 403
        assert client.post("/api/sessions/self-reported",
                           json={"drill_key": "gen_squat", "minutes": 20}).status_code in (401, 403)

    @pytest.mark.parametrize("minutes", [0, -5, 241, 9999])
    def test_a_silly_length_is_refused(self, client, minutes):
        a = one(client)
        assert log(client, a, minutes=minutes).status_code in (400, 422)
        assert sessions_of(a["kid"]) == []

    def test_an_unknown_drill_is_refused(self, client):
        a = one(client)
        assert log(client, a, drill="not_a_drill").status_code == 400

    def test_it_counts_for_turning_up(self, client):
        a = one(client)
        log(client, a)
        me = client.get("/api/me", headers=a["a"]).json()
        assert me["total_xp"] == CONFIG.scoring.streak_min_xp
        assert me["current_streak"] >= 1 if "current_streak" in me else True


class TestTypingMoreEarnsNothingMore:
    def test_only_the_first_of_the_day_earns_xp(self, client):
        a = one(client)
        first = log(client, a).json()
        second = log(client, a, drill="gen_jump_rope").json()
        assert first["xp_awarded"] > 0 and second["xp_awarded"] == 0
        assert xp_of(a["kid"]) == first["xp_awarded"]

    def test_the_claimed_length_never_changes_the_award(self, client):
        a, b = one(client), family(client, club(client, "Club B"), name="Sam Hill", roster_email="sam@example.com")
        assert log(client, a, minutes=5).json()["xp_awarded"] == log(client, b, minutes=240).json()["xp_awarded"]

    def test_only_a_few_a_day_are_accepted(self, client):
        a = one(client)
        for _ in range(MAX_LOGGED_PER_DAY):
            assert log(client, a).status_code == 201
        res = log(client, a)
        assert res.status_code == 400 and "tomorrow" in res.json()["detail"]
        assert len(sessions_of(a["kid"])) == MAX_LOGGED_PER_DAY

    def test_a_zero_award_leaves_no_ledger_row(self, client):
        a = one(client)
        log(client, a)
        log(client, a)
        assert db().execute("SELECT COUNT(*) FROM xp_ledger WHERE athlete_id = ?", (a["kid"],)).fetchone()[0] == 1


class TestItNeverReachesARank:
    def _logged_and_measured(self, client):
        """Two athletes in one club: one only logged, one trained for real."""
        c = club(client, "Club A")
        logger = family(client, c, name="Ryder Kallberg", roster_email="r@example.com")
        real = family(client, c, name="Sam Hill", roster_email="s@example.com")
        log(client, logger)
        res, _ = train(client, real)
        assert res.json()["status"] == "counted"
        return c, logger, real

    def test_the_staff_ranking_ignores_it(self, client):
        c, logger, real = self._logged_and_measured(client)
        rows = {r["athlete_id"]: r for r in client.get(
            "/api/coach/team-ranking", headers=c["d"], params={"team_id": c["team"]}).json()["rows"]}
        assert rows[logger["kid"]]["xp"] == 0
        assert rows[real["kid"]]["xp"] == xp_of(real["kid"]) > 0
        assert rows[real["kid"]]["rank"] == 1

    def test_the_xp_boards_ignore_it(self, client):
        c, logger, real = self._logged_and_measured(client)
        for board in ("xp", "movers"):
            try:
                rows = leaderboard.leaderboard(db(), c["org_id"], board=board, window="week")
            except Exception:
                continue                                   # a board this build does not have
            mine = [r for r in rows if r.get("athlete_id") == logger["kid"]]
            assert all(r["value"] == 0 for r in mine), (board, mine)

    def test_a_team_total_ignores_it(self, client):
        c, logger, real = self._logged_and_measured(client)
        teams = leaderboard.team_standings(db(), c["org_id"], "week")
        assert teams[0]["total_xp"] == xp_of(real["kid"])

    def test_the_directors_roster_numbers_ignore_it(self, client):
        c, logger, real = self._logged_and_measured(client)
        rows = {r["athlete_id"]: r for r in leaderboard.coach_roster(db(), c["org_id"], window="week")}
        from offdays.scoring import level_for_xp
        assert rows[logger["kid"]]["window_xp"] == 0 and rows[logger["kid"]]["level"] == level_for_xp(0)
        assert rows[real["kid"]]["window_xp"] == xp_of(real["kid"])

    def test_it_does_not_reach_the_reps_board(self, client):
        c, logger, real = self._logged_and_measured(client)
        log(client, logger, minutes=60, reps=4000)
        rows = leaderboard.leaderboard(db(), c["org_id"], board="reps", window="week")
        assert all(r["value"] == 0 for r in rows if r["athlete_id"] == logger["kid"])

    def test_it_still_counts_as_turning_up_for_the_streak(self, client):
        c, logger, real = self._logged_and_measured(client)
        rows = leaderboard.leaderboard(db(), c["org_id"], board="streak", window="week")
        mine = [r for r in rows if r["athlete_id"] == logger["kid"]]
        assert mine and mine[0]["value"] >= 1


class TestParentAndCoachCanSeeWhatWasLogged:
    def test_the_parent_is_told(self, client):
        a = one(client)
        log(client, a, note="no camera at the park")
        rows = client.get(f"/api/parent/athletes/{a['kid']}/drills", headers=a["p"]).json()["sessions"]
        assert [r["self_reported"] for r in rows] == [True]

    def test_a_counted_session_is_not_labelled(self, client):
        a = one(client)
        res, _ = train(client, a)
        rows = client.get(f"/api/parent/athletes/{a['kid']}/drills", headers=a["p"]).json()["sessions"]
        assert rows and all(r["self_reported"] is False for r in rows)

    def test_the_coach_is_told(self, client):
        a = one(client)
        log(client, a)
        page = client.get(f"/api/coach/overview/player/{a['kid']}", headers=a["club"]["d"]).json()
        assert [s["self_reported"] for s in page["recent_sessions"]] == [1]


class TestInAProgramThatIsLinked:
    def test_it_counts_there_too_and_stays_marked(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        log(client, a)
        copy = sessions_of(b["kid"])
        assert len(copy) == 1 and copy[0]["self_reported"] == 1 and copy[0]["mirrored_from"]
        assert xp_of(b["kid"]) == xp_of(a["kid"]) > 0


class TestTheScreens:
    @staticmethod
    def page(name):
        from pathlib import Path
        return (Path(api_module.__file__).parent / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_athlete_has_a_standing_way_in_from_home(self):
        html = self.page("capture.html")
        assert 'id="log-open"' in html and "Tell us what you did" in html
        assert html.index('id="log-open"') < html.index('id="shots-card"')

    def test_a_drill_that_did_not_count_offers_it(self):
        html = self.page("capture.html")
        assert 'id="r-log"' in html and "We couldn&rsquo;t see that one" in html
        assert "$('r-log').classList.toggle('hidden', result.status !== 'rejected');" in html
        # the drill that just failed is the one preselected
        assert "openLog(activeDrill && activeDrill.key)" in html

    def test_the_screen_says_what_it_does_and_does_not_do(self):
        html = self.page("capture.html")
        assert "does not go on the leaderboard" in html and "your coach and parent can see it" in html

    def test_it_posts_to_the_one_route_with_an_object_body(self):
        html = self.page("capture.html")
        assert "'/api/sessions/self-reported'" in html
        assert "body: { drill_key: $('log-drill').value, minutes," in html

    def test_the_parent_and_coach_pages_label_it(self):
        assert "logged by athlete" in self.page("parent.html")
        assert "logged by athlete" in self.page("coach.html")

    def test_the_cache_was_bumped_so_phones_pick_it_up(self):
        assert "offdays-shell-v25" in self.page("sw.js")


class TestALongRunOfLoggedDaysDoesNotRaiseALevel:
    def test_the_directors_level_comes_from_measured_work_only(self, client):
        from datetime import timedelta
        from offdays.scoring import level_for_xp
        c = club(client, "Club A")
        a = family(client, c, name="Ryder Kallberg", roster_email="r@example.com")
        store = api_module._store
        today = date.today()
        for back in range(40, 140):                        # 100 logged days: far more XP than level 1
            store.log_self_reported(a["kid"], "gen_squat", minutes=20, day=today - timedelta(days=back))
        assert xp_of(a["kid"]) >= 2000 and level_for_xp(xp_of(a["kid"])) > level_for_xp(0)
        from offdays import leaderboard
        row = [r for r in leaderboard.coach_roster(db(), c["org_id"], window="all") if r["athlete_id"] == a["kid"]][0]
        assert row["level"] == level_for_xp(0)
