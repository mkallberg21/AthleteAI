"""A season has a last day, and after it the athletes' doors close.

A parent says yes once and the child is in for the season -- which only
means something if the season ends. The director sets the date; the morning
after, athlete sign-in pauses until the next date is set. Parents and staff
are never cut off: a parent's rights do not expire with a fixture list, and
a director has to be able to get in to open the next season.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import guardians as G
from offdays.db import connect
from offdays.store import Store, StoreError

YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()
TODAY = date.today().isoformat()


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "s.db"))


@pytest.fixture
def program(store):
    org = store.create_org("Nashville Dogs")
    director = store.create_user(org, "director", "Dir K")
    team = store.create_team(org, "2031 Red")
    kid = store.create_user(org, "athlete", "Jordan Pierce", birth_year=2012, dominant_hand="right")
    store.join_team(team["join_code"], kid["id"])
    invite = G.create_invite(store.conn, kid["id"], director["id"])
    parent = G.redeem_invite(store.conn, invite["code"], "Dana Pierce")
    G.set_consent(store.conn, kid["id"], parent["guardian_id"], G.Scope.PARTICIPATION, True)
    return {"org": org, "director": director, "kid": kid, "parent": parent}


def set_end(store, org, when):
    store.conn.execute("UPDATE organizations SET season_ends_on = ? WHERE id = ?", (when, org))
    store.conn.commit()


class TestTheDoorCloses:
    def test_no_date_means_no_cutoff(self, store, program):
        assert store.season_over(program["org"]) is False
        assert store.authenticate(program["kid"]["token"]).id == program["kid"]["id"]

    def test_the_end_date_itself_is_still_a_training_day(self, store, program):
        set_end(store, program["org"], TODAY)
        assert store.season_over(program["org"]) is False
        assert store.authenticate(program["kid"]["token"]).id == program["kid"]["id"]

    def test_the_morning_after_the_athlete_cannot_sign_in(self, store, program):
        set_end(store, program["org"], YESTERDAY)
        with pytest.raises(StoreError, match="season has ended"):
            store.authenticate(program["kid"]["token"])

    def test_parents_and_staff_are_never_cut_off(self, store, program):
        set_end(store, program["org"], YESTERDAY)
        assert store.authenticate(program["parent"]["token"]).role == "guardian"
        assert store.authenticate(program["director"]["token"]).role == "director"

    def test_setting_next_seasons_date_lets_the_same_link_back_in(self, store, program):
        """Nobody re-registers. The parent's yes and the kid's link both stand."""
        set_end(store, program["org"], YESTERDAY)
        with pytest.raises(StoreError):
            store.authenticate(program["kid"]["token"])
        set_end(store, program["org"], TOMORROW)
        assert store.authenticate(program["kid"]["token"]).id == program["kid"]["id"]
        assert G.has_consent(store.conn, program["kid"]["id"], G.Scope.PARTICIPATION)

    def test_a_malformed_date_fails_open_rather_than_locking_everyone_out(self, store, program):
        set_end(store, program["org"], "June 30")
        assert store.season_over(program["org"]) is False


class TestThroughTheApi:
    @pytest.fixture
    def client(self, tmp_path):
        api_module._store = Store(connect(tmp_path / "api.db"))
        yield TestClient(api_module.app)
        api_module._store = None

    @pytest.fixture
    def org(self, client):
        made = client.post(
            "/api/orgs", json={"name": "Nashville Dogs", "director_name": "Dir K"}
        ).json()
        director = {"Authorization": f"Bearer {made['director']['token']}"}
        team = client.post(
            "/api/teams", json={"name": "2031 Red", "season": "2026"}, headers=director
        ).json()
        kid = client.post(
            "/api/athletes",
            json={"display_name": "Jordan P.", "birth_year": 2012, "dominant_hand": "right",
                  "guardian_consent": True, "join_code": team["join_code"]},
            headers=director,
        ).json()
        return {"director": director, "kid": {"Authorization": f"Bearer {kid['token']}"},
                "kid_token": kid["token"]}

    def test_a_director_sets_and_reads_the_date(self, client, org):
        res = client.put("/api/org/season", json={"ends_on": TOMORROW}, headers=org["director"])
        assert res.status_code == 200
        assert res.json()["ends_on"] == TOMORROW and res.json()["over"] is False
        got = client.get("/api/org/season", headers=org["director"]).json()
        assert got["ends_on"] == TOMORROW

    def test_a_bad_date_is_refused(self, client, org):
        res = client.put("/api/org/season", json={"ends_on": "30/06/2027"}, headers=org["director"])
        assert res.status_code == 400

    def test_blank_clears_the_cutoff(self, client, org):
        client.put("/api/org/season", json={"ends_on": YESTERDAY}, headers=org["director"])
        client.put("/api/org/season", json={"ends_on": ""}, headers=org["director"])
        assert client.get("/api/me", headers=org["kid"]).status_code == 200

    def test_the_director_chooses_shots_a_day_under_an_automatic_ceiling(self, client, org):
        got = client.get("/api/org/season", headers=org["director"]).json()["shots"]
        assert got["chosen"] == 0 and got["max"] == 150
        bands = {r["band"]: r for r in got["ceiling_by_age"]}
        assert bands["13-14"]["ceiling"] == 80 and bands["13-14"]["counts"] == 80
        res = client.put("/api/org/season", json={"daily_shots": 50}, headers=org["director"])
        assert res.status_code == 200, res.text
        bands = {r["band"]: r for r in res.json()["shots"]["ceiling_by_age"]}
        assert res.json()["shots"]["chosen"] == 50
        assert bands["13-14"]["counts"] == 50          # the director's number
        assert bands["10 and under"]["counts"] == 40   # the ceiling, automatically
        assert bands["17+"]["counts"] == 50
        res = client.put("/api/org/season", json={"daily_shots": 500}, headers=org["director"])
        assert res.status_code == 400
        res = client.put("/api/org/season", json={"daily_shots": 0}, headers=org["director"])
        assert res.json()["shots"]["chosen"] == 0
        assert {r["band"]: r["counts"] for r in res.json()["shots"]["ceiling_by_age"]}["13-14"] == 80

    def test_a_coach_cannot_set_shots_a_day(self, client, org):
        store = api_module._store
        coach = store.create_user(store.conn.execute(
            "SELECT org_id FROM users LIMIT 1").fetchone()["org_id"], "coach", "Coach")
        res = client.put("/api/org/season", json={"daily_shots": 50},
                         headers={"Authorization": f"Bearer {coach['token']}"})
        assert res.status_code == 403

    def test_the_phase_setting_still_works_on_its_own(self, client, org):
        res = client.put("/api/org/season", json={"phase": "in_season"}, headers=org["director"])
        assert res.status_code == 200, res.text
        assert res.json()["phase"]["key"] == "in_season"

    def test_after_the_date_the_kid_gets_the_reason_not_a_lockout(self, client, org):
        client.put("/api/org/season", json={"ends_on": YESTERDAY}, headers=org["director"])
        res = client.get("/api/me", headers=org["kid"])
        assert res.status_code == 403
        assert "season has ended" in res.json()["detail"]
        # Not counted as a wrong guess: a kid retrying the link all week is
        # not an attacker, and must not be throttled into a real lockout.
        for _ in range(12):
            assert client.get("/api/me", headers=org["kid"]).status_code == 403

    def test_the_director_is_still_in_after_the_date(self, client, org):
        client.put("/api/org/season", json={"ends_on": YESTERDAY}, headers=org["director"])
        assert client.get("/api/org/season", headers=org["director"]).json()["over"] is True


class TestTheCoachPageHasTheControl:
    def test_the_date_field_is_wired(self):
        from pathlib import Path
        html = (Path(__file__).resolve().parents[1] / "offdays/web/static/coach.html").read_text(encoding="utf-8")
        assert 'id="season-ends"' in html and "ends_on" in html


class TestTheSeasonIsWhatTheClubIsBilledOn:
    """Fifty cents per rostered athlete per day, from the day the roster is
    submitted to the end date the director set. 500 athletes, 1 February to
    30 June: 150 days, $37,500."""

    @pytest.fixture
    def client(self, tmp_path):
        api_module._store = Store(connect(tmp_path / "b.db"))
        yield TestClient(api_module.app)
        api_module._store = None

    @pytest.fixture
    def director(self, client):
        made = client.post(
            "/api/orgs", json={"name": "Nashville Dogs", "director_name": "Dir K"}
        ).json()
        headers = {"Authorization": f"Bearer {made['director']['token']}"}
        team = client.post(
            "/api/teams", json={"name": "2031 Red", "season": "2027"}, headers=headers
        ).json()
        from offdays import billing
        billing.start_subscription(api_module._store.conn, made["org_id"], "club_roster", trial=False)
        return {"headers": headers, "team": team, "org": made["org_id"]}

    CSV = "Last Name,First Name,Birth Year\n" + "\n".join(
        f"Kid,Number{i},2012" for i in range(20))

    def test_a_roster_import_never_sets_or_moves_the_dates(self, client, director):
        """A test import in January must not start a February season. The
        director picks both dates; the roster is just the roster."""
        client.post(
            "/api/coach/roster/import",
            json={"content": self.CSV, "team_id": director["team"]["id"]},
            headers=director["headers"],
        )
        got = client.get("/api/org/season", headers=director["headers"]).json()
        assert got["starts_on"] == "" and got["ends_on"] == ""
        client.put("/api/org/season", json={"starts_on": "2027-02-01"}, headers=director["headers"])
        client.post(
            "/api/coach/roster/import",
            json={"content": self.CSV, "team_id": director["team"]["id"]},
            headers=director["headers"],
        )
        assert client.get("/api/org/season", headers=director["headers"]).json()["starts_on"] == "2027-02-01"

    def test_the_start_can_be_set_alone_before_any_roster_exists(self, client, director):
        res = client.put("/api/org/season", json={"starts_on": "2027-02-01"}, headers=director["headers"]).json()
        assert res["starts_on"] == "2027-02-01" and res["ends_on"] == "" and res["days"] == 0

    def test_the_director_sets_both_dates_and_sees_the_day_count(self, client, director):
        res = client.put(
            "/api/org/season",
            json={"starts_on": "2027-02-01", "ends_on": "2027-06-30"},
            headers=director["headers"],
        ).json()
        assert (res["starts_on"], res["ends_on"], res["days"]) == ("2027-02-01", "2027-06-30", 150)

    def test_the_season_cannot_end_before_it_starts(self, client, director):
        res = client.put(
            "/api/org/season",
            json={"starts_on": "2027-06-30", "ends_on": "2027-02-01"},
            headers=director["headers"],
        )
        assert res.status_code == 400
        assert "before it starts" in res.json()["detail"]

    def test_the_invoice_is_days_times_athletes_times_fifty_cents(self, client, director):
        client.post(
            "/api/coach/roster/import",
            json={"content": self.CSV, "team_id": director["team"]["id"]},
            headers=director["headers"],
        )
        client.put(
            "/api/org/season",
            json={"starts_on": "2027-02-01", "ends_on": "2027-06-30"},
            headers=director["headers"],
        )
        inv = client.get("/api/org/invoice", headers=director["headers"]).json()
        assert inv["season_days"] == 150
        assert inv["athletes"] == 20
        assert inv["per_athlete_cents"] == 7500
        assert inv["total_cents"] == 20 * 7500
        assert inv["total_display"] == "$1,500.00"

    def test_no_dates_means_a_note_not_a_number(self, client, director):
        inv = client.get("/api/org/invoice", headers=director["headers"]).json()
        assert inv["season_set"] is False and inv["total_cents"] == 0
        assert "Season card" in inv["note"]
