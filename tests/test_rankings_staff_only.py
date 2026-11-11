"""Rankings are for coaches and directors. Athletes earn badges instead; parents see only their own child.

A ranked list of other people's children is the mechanism behind the worst behaviour in youth sports, so neither
an athlete nor a parent can reach one any more: not the program board, not a team board, not the age-group board a
parent used to get, not the team standings. Staff get the opposite of a cut-off list: every athlete in the team or
program, by full name, ranked, including the ones who have done nothing yet (they sit at the bottom, tied).

The athlete's reason to come back is the badge shelf: the ones earned, and the ones still locked with how far along
they are, so there is always a next one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import contacts as C
from offdays import guardians as G
from offdays import scoring
from offdays.db import connect
from offdays.store import Store

STATIC = Path(__file__).resolve().parents[1] / "offdays" / "web" / "static"
BOARD_URLS = [
    "/api/leaderboard",
    "/api/leaderboard?board=xp&window=month",
    "/api/leaderboard?board=streak",
    "/api/leaderboard?team_id=1",
    "/api/leaderboard?age_group=2013",
    "/api/leaderboard?sport=lacrosse",
    "/api/standings",
    "/api/standings?window=all",
]


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


@pytest.fixture
def program(client):
    store = api_module._store
    made = client.post("/api/orgs", json={"name": "Big Club", "director_name": "Dir K"}).json()
    org = made["org_id"]
    director = {"Authorization": f"Bearer {made['director']['token']}"}
    red = store.create_team(org, "2013 Red", "2026", age_group="2013")
    blue = store.create_team(org, "2013 Blue", "2026", age_group="2013")
    kids = {}
    for name, team, xp in [("Ana Alvarez", red, 300), ("Ben Brooks", red, 120), ("Cy Chen", red, 120),
                           ("Di Diaz", red, 0), ("Ed Evans", red, 0), ("Flo Fox", blue, 50), ("Gus Grant", blue, 0)]:
        kid = store.create_user(org, "athlete", name, birth_year=2013, dominant_hand="right")   # NO guardian consent
        store.join_team(team["join_code"], kid["id"])
        if xp:
            store.conn.execute("INSERT INTO xp_ledger(athlete_id, day, amount, reason, created_at) VALUES (?, date('now'), ?, 'test', datetime('now'))", (kid["id"], xp))
        kids[name] = kid
    store.conn.commit()
    coach = store.create_user(org, "coach", "Coach R")
    store.assign_staff_to_team(coach["id"], red["id"])
    inv = G.create_invite(store.conn, kids["Ana Alvarez"]["id"], 1, "ana.mom@example.com")
    parent = G.redeem_invite(store.conn, inv["code"], "Ana Mom", email="ana.mom@example.com")
    return {
        "org": org, "red": red, "blue": blue, "kids": kids, "store": store,
        "director": director,
        "coach": {"Authorization": f"Bearer {coach['token']}"},
        "athlete": {"Authorization": f"Bearer {kids['Ben Brooks']['token']}"},
        "parent": {"Authorization": f"Bearer {parent['token']}"},
    }


class TestAthletesAndParentsCannotSeeAnyRanking:

    @pytest.mark.parametrize("url", BOARD_URLS)
    def test_an_athlete_is_refused(self, client, program, url):
        assert client.get(url, headers=program["athlete"]).status_code == 403, url

    @pytest.mark.parametrize("url", BOARD_URLS)
    def test_a_parent_is_refused_even_for_their_own_childs_age_group(self, client, program, url):
        assert client.get(url, headers=program["parent"]).status_code == 403, url

    @pytest.mark.parametrize("url", BOARD_URLS)
    def test_nobody_signed_out_gets_one(self, client, program, url):
        assert client.get(url).status_code in (401, 403), url

    def test_the_team_ranking_is_closed_to_them_too(self, client, program):
        for who in ("athlete", "parent"):
            assert client.get("/api/coach/team-ranking", headers=program[who]).status_code == 403, who

    def test_an_athletes_own_profile_has_no_rank_in_it(self, client, program):
        me = client.get("/api/me", headers=program["athlete"])
        assert me.status_code == 200
        flat = repr({k: v for k, v in me.json().items() if k != "consents"}).lower()
        assert "rank" not in flat and "leaderboard" not in flat

    def test_a_parents_portal_payload_carries_no_ranking(self, client, program):
        r = client.get("/api/guardians/me", headers=program["parent"])
        assert r.status_code == 200
        assert "rank" not in repr(r.json()).lower()


class TestStaffStillSeeTheBoards:

    @pytest.mark.parametrize("url", ["/api/leaderboard", "/api/leaderboard?board=xp&window=all", "/api/standings"])
    def test_a_coach_and_a_director_can(self, client, program, url):
        assert client.get(url, headers=program["coach"]).status_code == 200
        assert client.get(url, headers=program["director"]).status_code == 200

    def test_staff_see_full_names_even_where_the_family_never_agreed_to_one(self, client, program):
        rows = client.get("/api/leaderboard?window=all", headers=program["director"]).json()["rows"]
        names = {r["display_name"] for r in rows}
        assert {"Ana Alvarez", "Ben Brooks", "Cy Chen", "Flo Fox"} <= names
        assert not any(n.startswith("Athlete ") or ". (#" in n for n in names), names


def ranking(client, program, who="director", **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    r = client.get("/api/coach/team-ranking" + (f"?{q}" if q else ""), headers=program[who])
    assert r.status_code == 200, r.text
    return r.json()


class TestEveryAthleteIsRanked:

    def test_the_whole_program_by_full_name_including_those_with_nothing_done(self, client, program):
        body = ranking(client, program, window="all")
        names = [r["display_name"] for r in body["rows"]]
        assert names[:4] == ["Ana Alvarez", "Ben Brooks", "Cy Chen", "Flo Fox"]
        assert sorted(names[4:]) == ["Di Diaz", "Ed Evans", "Gus Grant"]
        assert body["total"] == 7 and len(body["rows"]) == 7

    def test_ranks_are_competition_ranks_and_ties_share_one(self, client, program):
        rows = ranking(client, program, window="all")["rows"]
        by = {r["display_name"]: r for r in rows}
        assert by["Ana Alvarez"]["rank"] == 1
        assert by["Ben Brooks"]["rank"] == 2 and by["Cy Chen"]["rank"] == 2
        assert by["Flo Fox"]["rank"] == 4, "after two tied for second, the next is fourth"

    def test_those_with_nothing_are_tied_together_at_the_bottom(self, client, program):
        rows = ranking(client, program, window="all")["rows"]
        zeros = [r for r in rows if r["xp"] == 0]
        assert {r["display_name"] for r in zeros} == {"Di Diaz", "Ed Evans", "Gus Grant"}
        assert {r["rank"] for r in zeros} == {5}, "tied, not omitted, and not ranked above anyone who did something"
        assert all(r["trained"] is False for r in zeros)
        assert all(r["trained"] is True for r in rows if r["xp"] > 0)

    def test_names_inside_a_tie_are_alphabetical_so_the_list_does_not_jump_around(self, client, program):
        # Names chosen so insertion order (and id order) is NOT alphabetical, and one is lower-case to prove the sort ignores case.
        store = program["store"]
        for name in ("Zed Zane", "amy Able", "Mia Moore"):
            kid = store.create_user(program["org"], "athlete", name, birth_year=2013, dominant_hand="right")
            store.join_team(program["red"]["join_code"], kid["id"])
        rows = ranking(client, program, window="all")["rows"]
        zero_names = [r["display_name"] for r in rows if r["xp"] == 0]
        assert len(zero_names) >= 6
        assert zero_names == sorted(zero_names, key=str.lower), zero_names
        both = [r["display_name"] for r in rows if r["xp"] == 120]
        assert both == sorted(both, key=str.lower)

    def test_one_team(self, client, program):
        body = ranking(client, program, team_id=program["red"]["id"], window="all")
        assert [r["display_name"] for r in body["rows"]][:3] == ["Ana Alvarez", "Ben Brooks", "Cy Chen"]
        assert body["total"] == 5 and body["team"] == {"id": program["red"]["id"], "name": "2013 Red"}
        assert all(r["team_name"] == "2013 Red" for r in body["rows"])

    def test_each_row_says_the_team_so_a_program_wide_list_can_be_read(self, client, program):
        rows = ranking(client, program, window="all")["rows"]
        by = {r["display_name"]: r["team_name"] for r in rows}
        assert by["Flo Fox"] == "2013 Blue" and by["Ana Alvarez"] == "2013 Red"

    def test_the_window_is_respected(self, client, program):
        store = program["store"]
        store.conn.execute("UPDATE xp_ledger SET day = date('now', '-40 day') WHERE athlete_id = ?", (program["kids"]["Ana Alvarez"]["id"],))
        store.conn.commit()
        week = {r["display_name"]: r for r in ranking(client, program, window="week")["rows"]}
        alltime = {r["display_name"]: r for r in ranking(client, program, window="all")["rows"]}
        assert week["Ana Alvarez"]["xp"] == 0 and alltime["Ana Alvarez"]["xp"] == 300
        assert week["Ben Brooks"]["rank"] == 1

    def test_an_athlete_with_nothing_this_week_but_something_before_is_not_called_new(self, client, program):
        store = program["store"]
        store.conn.execute("UPDATE xp_ledger SET day = date('now', '-40 day') WHERE athlete_id = ?", (program["kids"]["Ana Alvarez"]["id"],))
        store.conn.commit()
        row = {r["display_name"]: r for r in ranking(client, program, window="week")["rows"]}["Ana Alvarez"]
        assert row["xp"] == 0 and row["last_active"] is not None

    def test_a_deactivated_athlete_is_not_listed(self, client, program):
        store = program["store"]
        store.conn.execute("UPDATE users SET active = 0 WHERE id = ?", (program["kids"]["Di Diaz"]["id"],))
        store.conn.commit()
        names = [r["display_name"] for r in ranking(client, program, window="all")["rows"]]
        assert "Di Diaz" not in names and len(names) == 6

    def test_an_athlete_on_two_teams_is_listed_once(self, client, program):
        store = program["store"]
        store.join_team(program["blue"]["join_code"], program["kids"]["Ana Alvarez"]["id"])
        names = [r["display_name"] for r in ranking(client, program, window="all")["rows"]]
        assert names.count("Ana Alvarez") == 1


class TestACoachIsNotHandedOtherTeamsChildrenByName:

    def test_on_the_program_wide_board_a_team_limited_coach_sees_masked_names(self, client, program):
        rows = client.get("/api/leaderboard?window=all", headers=program["coach"]).json()["rows"]
        assert rows, "the board has rows"
        for r in rows:
            assert r["display_name"].startswith("Athlete ") or ". (#" in r["display_name"], (
                f"{r['display_name']!r} is a full name shown to a coach who does not have that child's team")

    def test_on_their_own_team_the_same_coach_sees_full_names(self, client, program):
        rows = client.get(f"/api/leaderboard?window=all&team_id={program['red']['id']}", headers=program["coach"]).json()["rows"]
        assert {"Ana Alvarez", "Ben Brooks"} <= {r["display_name"] for r in rows}

    def test_a_director_sees_full_names_program_wide(self, client, program):
        rows = client.get("/api/leaderboard?window=all", headers=program["director"]).json()["rows"]
        assert {"Ana Alvarez", "Flo Fox"} <= {r["display_name"] for r in rows}


class TestOnlyYourOwn:

    def test_a_coach_sees_only_their_teams_in_the_program_wide_list(self, client, program):
        names = {r["display_name"] for r in ranking(client, program, who="coach", window="all")["rows"]}
        assert names == {"Ana Alvarez", "Ben Brooks", "Cy Chen", "Di Diaz", "Ed Evans"}

    def test_a_coach_is_refused_a_team_that_is_not_theirs(self, client, program):
        r = client.get(f"/api/coach/team-ranking?team_id={program['blue']['id']}", headers=program["coach"])
        assert r.status_code == 403

    def test_another_programs_team_is_not_there_at_all(self, client, program):
        other = client.post("/api/orgs", json={"name": "Rivals", "director_name": "R"}).json()
        theirs = api_module._store.create_team(other["org_id"], "Their Team", "2026")
        r = client.get(f"/api/coach/team-ranking?team_id={theirs['id']}", headers=program["director"])
        assert r.status_code in (403, 404)

    def test_an_unknown_team_is_404(self, client, program):
        assert client.get("/api/coach/team-ranking?team_id=99999", headers=program["director"]).status_code in (403, 404)

    def test_a_bad_window_is_refused(self, client, program):
        assert client.get("/api/coach/team-ranking?window=forever", headers=program["director"]).status_code == 422


class TestThePagesNoLongerShowOne:

    def test_the_athlete_home_has_no_leaderboard_button(self):
        html = (STATIC / "capture.html").read_text(encoding="utf-8")
        assert "leaderboard.html" not in html
        assert ">Leaderboards<" not in html

    def test_the_parent_portal_has_no_age_group_board(self):
        html = (STATIC / "parent.html").read_text(encoding="utf-8")
        assert "cohort-card" not in html and "/api/leaderboard" not in html and "loadCohort" not in html

    def test_the_offline_shell_no_longer_precaches_the_player_leaderboard_page(self):
        sw = (STATIC / "sw.js").read_text(encoding="utf-8")
        assert "'leaderboard.html'" not in sw

    def test_an_athlete_who_opens_the_old_page_is_sent_home_not_shown_an_error(self):
        html = (STATIC / "leaderboard.html").read_text(encoding="utf-8")
        assert "capture.html" in html


# ----------------------------------------------------------------------------------------------- badges

def stats(**kw):
    return scoring.AthleteStats(**kw)


class TestBadgeProgress:

    def test_every_badge_has_a_progress_measure(self):
        got = scoring.badge_progress(stats())
        assert set(got) == {b.key for b in scoring.BADGES}

    @pytest.mark.parametrize("s", [
        stats(), stats(session_count=1), stats(skill_reps=99), stats(skill_reps=100), stats(skill_reps=1000),
        stats(longest_streak=6), stats(longest_streak=7), stats(longest_streak=30), stats(balanced_sessions=9),
        stats(balanced_sessions=10), stats(offhand_reps=999), stats(offhand_reps=1000), stats(early_sessions=9),
        stats(early_sessions=10), stats(distinct_drills=4), stats(distinct_drills=5), stats(total_xp=10**9),
        stats(total_xp=5000, session_count=50, skill_reps=3000, longest_streak=31, distinct_drills=8),
    ])
    def test_a_badge_is_earned_exactly_when_its_progress_is_full(self, s):
        """The bar the athlete sees can never disagree with the badge the app awards."""
        earned = set(scoring.earned_badges(s))
        progress = scoring.badge_progress(s)
        for key, (have, need) in progress.items():
            assert (have >= need) == (key in earned), (key, have, need, s)

    def test_progress_is_never_beyond_the_goal_when_shown_as_a_fraction(self):
        for have, need in scoring.badge_progress(stats(skill_reps=10**6, longest_streak=999)).values():
            assert need > 0


class TestTheAthleteSeesTheBadgesTheyCanStillEarn:

    def test_a_new_athlete_sees_all_thirteen_as_next_steps_with_progress(self, client, program):
        me = client.get("/api/me", headers=program["athlete"]).json()
        assert me["badges"] == []
        assert len(me["locked_badges"]) == len(scoring.BADGES)
        for b in me["locked_badges"]:
            assert {"key", "name", "description", "tier", "have", "need"} <= set(b)
            assert 0 <= b["have"] < b["need"]

    def test_earned_badges_leave_the_locked_list(self, client, program):
        store = program["store"]
        kid = program["kids"]["Cy Chen"]
        store.conn.execute("INSERT INTO badges(athlete_id, badge_key, awarded_at) VALUES (?, 'first_session', datetime('now'))", (kid["id"],))
        store.conn.commit()
        me = client.get("/api/me", headers={"Authorization": f"Bearer {kid['token']}"}).json()
        assert [b["key"] for b in me["badges"]] == ["first_session"]
        assert "first_session" not in {b["key"] for b in me["locked_badges"]}
        assert len(me["badges"]) + len(me["locked_badges"]) == len(scoring.BADGES)

    def test_the_closest_ones_come_first(self, client, program):
        store = program["store"]
        kid = program["kids"]["Cy Chen"]
        # 90 of 100 reps toward Century is nearer than 0 of anything else
        store.conn.execute("INSERT INTO sessions(athlete_id, drill_key, status, reps_total, submitted_at, started_at, nonce) "
                           "VALUES (?, 'wall_ball', 'counted', 90, datetime('now'), datetime('now'), 'n1')", (kid["id"],))
        store.conn.commit()
        me = client.get("/api/me", headers={"Authorization": f"Bearer {kid['token']}"}).json()
        fracs = [b["have"] / b["need"] for b in me["locked_badges"]]
        assert fracs == sorted(fracs, reverse=True)

    def test_a_brand_new_athlete_is_shown_first_rep_first_and_the_level_badges_start_at_zero(self, client, program):
        fresh = program["store"].create_user(program["org"], "athlete", "Brand New", birth_year=2013, dominant_hand="right")
        me = client.get("/api/me", headers={"Authorization": f"Bearer {fresh['token']}"}).json()
        assert [b["key"] for b in me["locked_badges"]][:3] == ["first_session", "all_rounder", "streak_7"]
        by = {b["key"]: b for b in me["locked_badges"]}
        assert (by["level_10"]["have"], by["level_25"]["have"]) == (0, 0), "everyone starts at level 1: nothing climbed yet"

    def test_the_athlete_page_shows_them(self):
        html = (STATIC / "capture.html").read_text(encoding="utf-8")
        assert "locked_badges" in html and "badge-next" in html
