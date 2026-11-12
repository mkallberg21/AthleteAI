"""The director's home: all teams in one list, then one team, then one player.

Read-only views over what the program already holds. These tests pin the three things that matter:

  * the numbers are right (a team is "training" only when its players are, a team with no coach or no players says so);
  * who may see what (a coach sees only their own teams and players, another program's ids are a 404, athletes and
    parents get nothing, and only a director sees the list of every coach);
  * nothing is leaked that should not be (no team numbers, no ranking for anyone who is not staff).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays.db import connect
from offdays.store import Store


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def db():
    return api_module._store.conn


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def program(client, name="Home Club", sport="lacrosse"):
    made = client.post("/api/orgs", json={"name": name, "sport": sport, "accept_terms": True,
                                          "director_name": "Joel"}).json()
    return {"org_id": made["org_id"], "h": bearer(made["director"]["token"])}


def team(client, p, name):
    r = client.post("/api/teams", json={"name": name}, headers=p["h"])
    assert r.status_code == 201, r.text
    return r.json()["id"]


def coach(client, p, name, email, team_ids):
    r = client.post("/api/coach/staff", json={"display_name": name, "email": email, "team_ids": team_ids}, headers=p["h"])
    assert r.status_code == 201, r.text
    return {"id": r.json()["user_id"], "h": bearer(r.json()["code"])}


def roster(client, p, team_id, names, parents=True):
    head = "First Name,Last Name,Birth Year,Parent Email\n"
    body = "".join(f"{n.split()[0]},{n.split()[1]},2013,{n.split()[0].lower()}.mom@example.com\n" if parents
                   else f"{n.split()[0]},{n.split()[1]},2013,\n" for n in names)
    r = client.post("/api/coach/roster/import", headers=p["h"], json={"content": head + body, "team_id": team_id})
    assert r.status_code == 201, r.text
    ids = {}
    for a in client.get("/api/coach/team-ranking", headers=p["h"], params={"team_id": team_id}).json()["rows"]:
        ids[a["display_name"]] = a["athlete_id"]
    return ids


def train(athlete_id, xp=50, day=None, status="counted"):
    """A counted session and its XP, written the way the real path leaves them."""
    now = datetime.now(timezone.utc)
    day = day or now.strftime("%Y-%m-%d")
    c = db()
    cur = c.execute(
        "INSERT INTO sessions (athlete_id, drill_key, nonce, started_at, submitted_at, reps_total, status) "
        "VALUES (?, 'lax_wall_ball_strong', ?, ?, ?, 20, ?)",
        (athlete_id, f"n-{athlete_id}-{now.timestamp()}-{xp}", now.isoformat(), now.isoformat(), status))
    c.execute("INSERT INTO xp_ledger (athlete_id, session_id, amount, reason, day, created_at) VALUES (?, ?, ?, 'session', ?, ?)",
              (athlete_id, cur.lastrowid, xp, day, now.isoformat()))
    c.commit()


def set_seen(user_id, when):
    db().execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (when, user_id))
    db().commit()


def row_for(overview, name):
    return next(t for t in overview["teams"] if t["name"] == name)


@pytest.fixture
def club(client):
    """Four teams: one training, one stuck, one with no coach, one with no players."""
    p = program(client)
    red, blue, green, empty = (team(client, p, n) for n in ("2031 Red", "2031 Blue", "2032 Green", "2033 Empty"))
    sam = coach(client, p, "Sam Hill", "sam@example.com", [red, blue])
    pat = coach(client, p, "Pat Roe", "pat@example.com", [empty])
    ids_red = roster(client, p, red, ["Ava Moss", "Ben Cole"])
    ids_blue = roster(client, p, blue, ["Cam Diaz", "Dee Park", "Eli Fox"])
    ids_green = roster(client, p, green, ["Fay Gray"])
    for a in ids_red.values():
        train(a)
    train(ids_blue["Cam Diaz"], xp=80)
    return {**p, "red": red, "blue": blue, "green": green, "empty": empty, "sam": sam, "pat": pat,
            "ids_red": ids_red, "ids_blue": ids_blue, "ids_green": ids_green}


class TestAllTeamsInOneList:

    def test_one_row_per_team_with_the_right_counts(self, client, club):
        o = client.get("/api/coach/overview", headers=club["h"]).json()
        assert [t["name"] for t in o["teams"]] == ["2031 Blue", "2031 Red", "2032 Green", "2033 Empty"]
        red, blue = row_for(o, "2031 Red"), row_for(o, "2031 Blue")
        assert (red["players"], red["training"], red["stuck"]) == (2, 2, 0)
        assert (blue["players"], blue["training"], blue["stuck"]) == (3, 1, 2)
        assert o["totals"] == {"teams": 4, "players": 6, "training": 3, "stuck": 3}

    def test_each_team_says_what_state_it_is_in(self, client, club):
        o = client.get("/api/coach/overview", headers=club["h"]).json()
        assert row_for(o, "2031 Red")["state"] == "training"
        assert row_for(o, "2031 Blue")["state"] == "stuck"
        assert row_for(o, "2032 Green")["state"] == "no_coach"
        assert row_for(o, "2033 Empty")["state"] == "no_players"

    def test_where_the_stuck_families_are_stuck_is_counted_by_stage(self, client, club):
        blue = row_for(client.get("/api/coach/overview", headers=club["h"]).json(), "2031 Blue")
        assert sum(blue["stuck_stages"].values()) == blue["stuck"] == 2
        assert set(blue["stuck_stages"]) <= {"no_parent", "invite_unsent", "invited", "consent_pending",
                                             "link_unsent", "link_sent", "signed_in"}
        assert "training" not in blue["stuck_stages"]

    def test_a_team_shows_its_coaches_and_when_it_last_trained(self, client, club):
        o = client.get("/api/coach/overview", headers=club["h"]).json()
        red = row_for(o, "2031 Red")
        assert [c["display_name"] for c in red["coaches"]] == ["Sam Hill"]
        assert red["last_active"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert row_for(o, "2032 Green")["last_active"] is None

    def test_the_attention_list_names_what_needs_a_person(self, client, club):
        a = client.get("/api/coach/overview", headers=club["h"]).json()["attention"]
        assert a["stuck_families"] == 3
        assert a["teams_without_coach"] == ["2032 Green"]
        assert a["teams_without_players"] == ["2033 Empty"]
        assert sorted(a["coaches_not_signed_in"]) == ["Pat Roe", "Sam Hill"]
        assert a["total"] >= 4

    def test_a_coach_who_signs_in_stops_being_listed_as_never_seen(self, client, club):
        client.get("/api/coach/teams", headers=club["sam"]["h"])
        a = client.get("/api/coach/overview", headers=club["h"]).json()["attention"]
        assert a["coaches_not_signed_in"] == ["Pat Roe"]

    def test_a_coach_quiet_for_weeks_is_called_out_separately_from_one_never_seen(self, client, club):
        client.get("/api/coach/teams", headers=club["sam"]["h"])
        set_seen(club["sam"]["id"], (datetime.now(timezone.utc) - timedelta(days=40)).isoformat())
        a = client.get("/api/coach/overview", headers=club["h"]).json()["attention"]
        assert a["coaches_quiet"] == ["Sam Hill"]
        assert a["coaches_not_signed_in"] == ["Pat Roe"]

    def test_a_clean_program_has_nothing_that_needs_a_person(self, client):
        p = program(client, name="Tidy")
        t = team(client, p, "U12")
        c = coach(client, p, "Sam", "s@example.com", [t])
        client.get("/api/coach/teams", headers=c["h"])
        for a in roster(client, p, t, ["Ava Moss"]).values():
            train(a)
        a = client.get("/api/coach/overview", headers=p["h"]).json()["attention"]
        assert a["total"] == 0 and a["stuck_families"] == 0

    def test_sessions_waiting_for_review_are_counted(self, client, club):
        train(next(iter(club["ids_green"].values())), xp=0, status="review")
        assert client.get("/api/coach/overview", headers=club["h"]).json()["attention"]["sessions_to_review"] == 1

    def test_an_empty_program_is_an_empty_list_not_an_error(self, client):
        o = client.get("/api/coach/overview", headers=program(client, name="New")["h"]).json()
        assert o["teams"] == [] and o["totals"]["players"] == 0 and o["attention"]["total"] == 0

    def test_no_team_numbers_are_in_the_response(self, client, club):
        text = client.get("/api/coach/overview", headers=club["h"]).text
        for word in ("daily_wall_ball", "daily_shots", "wall_ball", "join_code"):
            assert word not in text, word

    def test_a_bad_window_is_refused(self, client, club):
        assert client.get("/api/coach/overview", headers=club["h"], params={"window": "fortnight"}).status_code == 422


class TestOneTeam:

    def test_every_player_is_ranked_and_the_ones_who_have_done_nothing_tie_at_the_bottom(self, client, club):
        d = client.get(f"/api/coach/overview/team/{club['blue']}", headers=club["h"]).json()
        assert [p["display_name"] for p in d["players"]][0] == "Cam Diaz"
        ranks = [p["rank"] for p in d["players"]]
        assert ranks == [1, 2, 2], "the two who have done nothing share one rank, below the one who has"
        assert [p["trained"] for p in d["players"]] == [True, False, False]

    def test_a_player_row_carries_the_stage_and_whose_move_it_is(self, client, club):
        d = client.get(f"/api/coach/overview/team/{club['blue']}", headers=club["h"]).json()
        cam = d["players"][0]
        assert cam["stage"] == "training" and cam["sessions"] == 1
        dee = next(p for p in d["players"] if p["display_name"] == "Dee Park")
        assert dee["stage"] != "training" and dee["stage_label"] and dee["who"] in ("program", "parent", "athlete")

    def test_the_team_page_shows_its_coaches_and_the_videos_each_added(self, client, club):
        sam = club["sam"]
        before = client.get(f"/api/coach/overview/team/{club['red']}", headers=club["h"]).json()["coaches"][0]
        assert before["videos_30d"] == 0
        r = client.post("/api/coach/clips", headers=sam["h"], json={
            "video": "https://youtu.be/dQw4w9WgXcQ", "title": "Ground balls", "focus": "Scoop through", "start_s": 0, "end_s": 60,
            "min_age": 0, "max_age": 18})
        assert r.status_code == 201, r.text
        after = client.get(f"/api/coach/overview/team/{club['red']}", headers=club["h"]).json()["coaches"][0]
        assert after["display_name"] == "Sam Hill" and after["videos_30d"] == 1

    def test_the_counts_add_up(self, client, club):
        c = client.get(f"/api/coach/overview/team/{club['blue']}", headers=club["h"]).json()["counts"]
        assert (c["players"], c["training"], c["stuck"]) == (3, 1, 2)
        assert sum(c["stages"].values()) == 2

    def test_a_team_in_another_program_is_a_404(self, client, club):
        other = program(client, name="Other Club")
        t = team(client, other, "Theirs")
        assert client.get(f"/api/coach/overview/team/{t}", headers=club["h"]).status_code == 404
        assert client.get("/api/coach/overview/team/999999", headers=club["h"]).status_code == 404

    def test_no_team_numbers_on_the_team_page(self, client, club):
        text = client.get(f"/api/coach/overview/team/{club['red']}", headers=club["h"]).text
        assert "daily_wall_ball" not in text and "join_code" not in text


class TestOnePlayer:

    def test_the_player_page_has_the_stage_the_parent_and_the_sessions(self, client, club):
        ava = club["ids_red"]["Ava Moss"]
        d = client.get(f"/api/coach/overview/player/{ava}", headers=club["h"]).json()
        assert d["athlete"]["display_name"] == "Ava Moss" and d["stage"] == "training"
        assert d["teams"][0]["name"] == "2031 Red"
        assert d["parents"][0]["email"] == "ava.mom@example.com"
        assert d["rank"] in (1, 2) and d["xp"] == 50 and d["sessions"] == 1
        assert d["recent_sessions"][0]["drill_key"] == "lax_wall_ball_strong"

    def test_a_player_who_has_not_started_says_where_the_family_is(self, client, club):
        dee = club["ids_blue"]["Dee Park"]
        d = client.get(f"/api/coach/overview/player/{dee}", headers=club["h"]).json()
        assert d["stage"] != "training" and d["stage_label"] and d["sessions"] == 0 and d["xp"] == 0
        assert d["recent_sessions"] == []

    def test_a_player_with_no_parent_on_file_is_said_plainly(self, client):
        p = program(client, name="Orphan")
        t = team(client, p, "U10")
        kid = next(iter(roster(client, p, t, ["Zed Kim"], parents=False).values()))
        d = client.get(f"/api/coach/overview/player/{kid}", headers=p["h"]).json()
        assert d["stage"] == "no_parent" and d["parents"] == [] and d["can_nudge"] is False

    def test_a_player_in_another_program_or_who_does_not_exist_is_a_404(self, client, club):
        other = program(client, name="Elsewhere")
        t = team(client, other, "X")
        stranger = next(iter(roster(client, other, t, ["Gus Lee"]).values()))
        assert client.get(f"/api/coach/overview/player/{stranger}", headers=club["h"]).status_code == 404
        assert client.get("/api/coach/overview/player/999999", headers=club["h"]).status_code == 404

    def test_the_player_page_never_shows_a_kid_code_or_token(self, client, club):
        text = client.get(f"/api/coach/overview/player/{club['ids_red']['Ava Moss']}", headers=club["h"]).text.lower()
        for word in ("token", "join_code", "kid_code", "daily_wall_ball"):
            assert word not in text, word


class TestWhoMaySee:

    def test_a_coach_sees_only_their_own_teams_in_the_list(self, client, club):
        o = client.get("/api/coach/overview", headers=club["sam"]["h"]).json()
        assert [t["name"] for t in o["teams"]] == ["2031 Blue", "2031 Red"]
        assert o["totals"]["players"] == 5

    def test_a_coach_cannot_open_a_team_that_is_not_theirs(self, client, club):
        assert client.get(f"/api/coach/overview/team/{club['green']}", headers=club["sam"]["h"]).status_code == 403
        assert client.get(f"/api/coach/overview/team/{club['red']}", headers=club["sam"]["h"]).status_code == 200

    def test_a_coach_cannot_open_a_player_who_is_not_on_their_team(self, client, club):
        fay = club["ids_green"]["Fay Gray"]
        assert client.get(f"/api/coach/overview/player/{fay}", headers=club["sam"]["h"]).status_code == 403
        ava = club["ids_red"]["Ava Moss"]
        assert client.get(f"/api/coach/overview/player/{ava}", headers=club["sam"]["h"]).status_code == 200

    def test_a_coach_does_not_see_the_program_wide_suggestion_count(self, client, club):
        assert client.get("/api/coach/overview", headers=club["sam"]["h"]).json()["attention"]["suggested_videos"] == 0

    def test_only_a_director_sees_every_coach(self, client, club):
        assert client.get("/api/coach/overview/coaches", headers=club["sam"]["h"]).status_code == 403
        d = client.get("/api/coach/overview/coaches", headers=club["h"]).json()
        assert [c["display_name"] for c in d["coaches"]] == ["Pat Roe", "Sam Hill"]
        sam = next(c for c in d["coaches"] if c["display_name"] == "Sam Hill")
        assert [t["name"] for t in sam["teams"]] == ["2031 Blue", "2031 Red"]

    def test_the_coaches_list_counts_each_coachs_videos(self, client, club):
        client.post("/api/coach/clips", headers=club["sam"]["h"], json={
            "video": "https://youtu.be/dQw4w9WgXcQ", "title": "Ground balls", "focus": "Scoop", "start_s": 0, "end_s": 60,
            "min_age": 0, "max_age": 18})
        d = client.get("/api/coach/overview/coaches", headers=club["h"]).json()
        sam = next(c for c in d["coaches"] if c["display_name"] == "Sam Hill")
        pat = next(c for c in d["coaches"] if c["display_name"] == "Pat Roe")
        assert (sam["videos_30d"], sam["videos_total"]) == (1, 1) and (pat["videos_30d"], pat["videos_total"]) == (0, 0)

    def test_an_athlete_is_refused_everywhere(self, client, club):
        kid = client.post("/api/athletes", headers=club["h"], json={"display_name": "Kid Test"}).json()
        h = bearer(kid["token"])
        ava = club["ids_red"]["Ava Moss"]
        for path in ("/api/coach/overview", f"/api/coach/overview/team/{club['red']}",
                     f"/api/coach/overview/player/{ava}", "/api/coach/overview/coaches"):
            assert client.get(path, headers=h).status_code == 403, path

    def test_nobody_signed_out_gets_anything(self, client, club):
        for path in ("/api/coach/overview", f"/api/coach/overview/team/{club['red']}",
                     "/api/coach/overview/coaches"):
            assert client.get(path).status_code == 401, path

    def test_other_programs_data_never_appears_in_the_list(self, client, club):
        other = program(client, name="Rival")
        t = team(client, other, "Rival Team")
        roster(client, other, t, ["Hal Moon"])
        o = client.get("/api/coach/overview", headers=club["h"]).json()
        assert "Rival Team" not in str(o) and "Hal Moon" not in str(o)

    def test_it_works_the_same_for_every_sport(self, client):
        for sport in ("lacrosse", "basketball", "soccer", "volleyball", "football"):
            p = program(client, name=f"{sport} club", sport=sport)
            t = team(client, p, "U12 A")
            roster(client, p, t, ["Ava Moss", "Ben Cole"])
            o = client.get("/api/coach/overview", headers=p["h"]).json()
            assert o["totals"]["players"] == 2 and o["teams"][0]["name"] == "U12 A", sport
            assert client.get(f"/api/coach/overview/team/{t}", headers=p["h"]).status_code == 200, sport


class TestStaffAreMarkedSeen:

    def test_a_coach_opening_the_app_is_recorded_once_a_day(self, client, club):
        assert db().execute("SELECT last_seen_at FROM users WHERE id = ?", (club["sam"]["id"],)).fetchone()[0] is None
        client.get("/api/coach/teams", headers=club["sam"]["h"])
        first = db().execute("SELECT last_seen_at FROM users WHERE id = ?", (club["sam"]["id"],)).fetchone()[0]
        assert first
        client.get("/api/coach/teams", headers=club["sam"]["h"])
        assert db().execute("SELECT last_seen_at FROM users WHERE id = ?", (club["sam"]["id"],)).fetchone()[0] == first


class TestTheModuleHoldsTheLineOnItsOwn:
    """The routes check scope first. These call the module directly, as a future route that forgot to would, so
    the guard is not only in one place."""

    def test_the_team_page_refuses_a_team_from_another_program(self, client, club):
        from offdays import overview
        other = program(client, name="Other Two")
        t = team(client, other, "Theirs")
        with pytest.raises(LookupError):
            overview.team_detail(db(), club["org_id"], t)

    def test_the_player_page_refuses_a_player_from_another_program(self, client, club):
        from offdays import overview
        other = program(client, name="Other Three")
        t = team(client, other, "Theirs")
        stranger = next(iter(roster(client, other, t, ["Gus Lee"]).values()))
        with pytest.raises(LookupError):
            overview.player_detail(db(), club["org_id"], stranger)

    def test_a_scoped_review_count_only_counts_the_scoped_teams(self, client, club):
        from offdays import overview
        train(next(iter(club["ids_green"].values())), xp=0, status="review")
        assert overview.program_overview(db(), club["org_id"], None)["attention"]["sessions_to_review"] == 1
        scoped = overview.program_overview(db(), club["org_id"], [club["red"], club["blue"]])
        assert scoped["attention"]["sessions_to_review"] == 0, "a review on a team the coach does not have is not theirs"

    def test_each_coachs_video_count_is_their_own(self, client, club):
        from offdays import overview
        client.post("/api/coach/clips", headers=club["sam"]["h"], json={
            "video": "https://youtu.be/dQw4w9WgXcQ", "title": "Ground balls", "focus": "Scoop", "start_s": 0, "end_s": 60,
            "min_age": 0, "max_age": 18})
        other = overview.team_detail(db(), club["org_id"], club["empty"])
        assert [c["display_name"] for c in other["coaches"]] == ["Pat Roe"]
        assert other["coaches"][0]["videos_30d"] == 0, "Sam's video is not Pat's"
        assert overview.team_detail(db(), club["org_id"], club["red"])["coaches"][0]["videos_30d"] == 1


class TestSuggestedVideosAreTheDirectorsToDecide:

    def test_the_count_is_shown_to_a_director_and_hidden_from_a_coach(self, client, club, monkeypatch):
        import offdays.video_scout as scout
        monkeypatch.setattr(scout, "enabled", lambda: True)
        monkeypatch.setattr(scout, "pending_for", lambda conn, org, sport, limit=30: [{"id": 1}, {"id": 2}, {"id": 3}])
        assert client.get("/api/coach/overview", headers=club["h"]).json()["attention"]["suggested_videos"] == 3
        assert client.get("/api/coach/overview", headers=club["sam"]["h"]).json()["attention"]["suggested_videos"] == 0

    def test_other_sports_have_no_suggestions(self, client, monkeypatch):
        import offdays.video_scout as scout
        monkeypatch.setattr(scout, "enabled", lambda: True)
        monkeypatch.setattr(scout, "pending_for", lambda conn, org, sport, limit=30: [{"id": 1}])
        p = program(client, name="Hoops", sport="basketball")
        assert client.get("/api/coach/overview", headers=p["h"]).json()["attention"]["suggested_videos"] == 0


class TestSeenIsWrittenOncePerDay:

    def test_a_second_request_the_same_day_does_not_rewrite_it(self, client, club):
        client.get("/api/coach/teams", headers=club["sam"]["h"])
        stamp = "2026-01-01T00:00:00+00:00"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        db().execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (f"{today}T00:00:01+00:00", club["sam"]["id"]))
        db().commit()
        client.get("/api/coach/teams", headers=club["sam"]["h"])
        assert db().execute("SELECT last_seen_at FROM users WHERE id = ?", (club["sam"]["id"],)).fetchone()[0] \
            == f"{today}T00:00:01+00:00", "already stamped today, so the sign-in path leaves it alone"
        db().execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (stamp, club["sam"]["id"]))
        db().commit()
        client.get("/api/coach/teams", headers=club["sam"]["h"])
        assert db().execute("SELECT last_seen_at FROM users WHERE id = ?", (club["sam"]["id"],)).fetchone()[0].startswith(today)


class TestThePageIsWired:
    """The Home tab is a view over the routes above. These pin that it is the front door and nothing was lost."""

    from pathlib import Path as _P
    HTML = (_P(__file__).resolve().parents[1] / "offdays" / "web" / "static" / "coach.html").read_text(encoding="utf-8")

    def test_home_is_the_first_tab_and_the_one_that_opens(self):
        bar = self.HTML.split('id="tabbar"', 1)[1].split("</div>", 1)[0]
        assert bar.index('data-tab="home"') < bar.index('data-tab="today"')
        assert "var tab = 'home';" in self.HTML and "localStorage.getItem(KEY) || 'home'" in self.HTML

    def test_the_old_tabs_are_all_still_there(self):
        bar = self.HTML.split('id="tabbar"', 1)[1].split("</div>", 1)[0]
        for t in ("today", "families", "teams", "settings"):
            assert f'data-tab="{t}"' in bar

    def test_the_home_reads_only_the_overview_routes_and_the_existing_resend(self):
        js = self.HTML.split("// ------------------------------------------------------------ Home: all teams", 1)[1].split(
            "// A red star on every card", 1)[0]
        assert "/api/coach/overview?window=" in js and "/api/coach/overview/team/" in js
        assert "/api/coach/overview/player/" in js and "/api/coach/overview/coaches" in js
        assert "/api/coach/families/nudge" in js, "resend goes through the one existing path"
        for forbidden in ("/api/org/mail-hold", "method: 'DELETE'", "/api/coach/roster/import", "/api/teams'"):
            assert forbidden not in js, f"the home is read-only apart from resend: {forbidden}"

    def test_the_home_never_claims_an_invite_was_sent_unless_the_server_says_so(self):
        js = self.HTML.split("async function homePlayer()", 1)[1].split("async function homeCoaches()", 1)[0]
        assert "if (res.emailed)" in js and "Emailed to" in js
        assert "Send email" in js, "when nothing was sent, the director gets a link to send it from their own mail"

    def test_the_home_card_has_no_h2_so_the_fold_script_leaves_it_open(self):
        card = self.HTML.split('id="home-card"', 1)[1].split("\n  </div>\n", 1)[0]
        assert "<h2" not in card

    def test_the_home_shows_no_team_numbers_or_codes(self):
        js = self.HTML.split("// ------------------------------------------------------------ Home: all teams", 1)[1].split(
            "// A red star on every card", 1)[0].lower()
        for word in ("daily_wall_ball", "daily_shots", "join_code", "token"):
            assert word not in js, word

    def test_the_team_filter_is_hidden_on_home_and_back_on_the_other_tabs(self):
        assert 'id="filter-card"' in self.HTML
        assert "if (c.id === 'filter-card' && tab === 'home') away = true;" in self.HTML

    def test_the_wizard_hands_over_to_the_home_when_it_finishes(self):
        fin = self.HTML.split("function wizardFinish()", 1)[1].split("async function startWizardIfNew", 1)[0]
        assert "homeLoad();" in fin
