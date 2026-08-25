"""A number a squad chases together.

Every other board in this product ranks individuals. This is the household
board's pattern brought to a team: one shared number, chased collaboratively,
whose marginal contributor is the athlete a participation metric exists to
reach.

The shape is the whole design, and it is what these tests are about.
Contribution is binary and capped -- a count of athletes who each clear a
small personal bar -- so the committed athlete doing six sessions moves the
number exactly as much as the quiet one doing three. A goal denominated in
reps would let one athlete carry the squad and would make a quiet one visibly
the shortfall, which is a worse object than the leaderboard it replaced.

And nobody is ever named. Not who is in, not who is not, not a count of who
is not.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from athleteiq import team_goals
from athleteiq.db import connect
from athleteiq.store import Store
from athleteiq.team_goals import GoalError

TODAY = date(2026, 8, 20)
START = TODAY - timedelta(days=6)


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "g.db"))


@pytest.fixture
def squad(store):
    org = store.create_org("Northshore")
    director = store.create_user(org, "director", "Coach Ada")
    team = store.create_team(org, "U15 Boys")
    athletes = []
    for i in range(10):
        person = store.create_user(
            org, "athlete", f"Kid {i}", birth_year=2011, dominant_hand="right"
        )
        store.join_team(team["join_code"], person["id"])
        athletes.append(person)
    return {"org": org, "director": director, "team": team, "athletes": athletes}


def train(store, athlete, day, seed=None):
    """One real session, back-dated. Jittered because the integrity layer
    rejects metronomic reps as fabricated -- correctly."""
    rng = random.Random(seed if seed is not None else (athlete["id"], day.toordinal()).__hash__())
    started = store.start_session(athlete["id"], "gen_squat")
    t, reps = 0, []
    for _ in range(20):
        t += max(600, int(rng.gauss(1500, 220)))
        value = 74.0 + rng.uniform(-3, 3)
        reps.append({"t_ms": t, "hand": "none", "confidence": 0.9, "rom": value,
                     "peak": value, "cycle_ms": 1150 + rng.randint(-120, 120)})
    store.submit_session(
        athlete["id"], started["session_id"], started["nonce"],
        duration_ms=t + 900, reps=reps, mean_confidence=0.9,
    )
    store.conn.execute(
        "UPDATE sessions SET submitted_at = ? WHERE id = ?",
        (day.isoformat() + "T18:00:00+00:00", started["session_id"]),
    )
    store.conn.commit()


def make(store, squad, **kwargs):
    params = dict(
        org_id=squad["org"], team_id=squad["team"]["id"],
        created_by=squad["director"]["id"], title="Everyone gets out 3 days",
        target_athletes=8, starts_on=START.isoformat(), ends_on=TODAY.isoformat(),
        per_athlete_days=3,
    )
    params.update(kwargs)
    return team_goals.create(store.conn, **params)


class TestContributionIsCapped:
    """The property that makes this different from a leaderboard.

    If one athlete could move the number further by doing more, the quiet
    athlete would stop being the point and start being the shortfall.
    """

    def test_doing_double_the_work_counts_once(self, store, squad):
        goal_id = make(store, squad)
        for offset in range(6):                      # twice the bar
            train(store, squad["athletes"][0], START + timedelta(days=offset))
        assert team_goals.get(store.conn, goal_id, TODAY).counted == 1

    def test_three_keen_athletes_move_it_exactly_three(self, store, squad):
        goal_id = make(store, squad)
        for athlete in squad["athletes"][:3]:
            for offset in range(6):
                train(store, athlete, START + timedelta(days=offset))
        assert team_goals.get(store.conn, goal_id, TODAY).counted == 3

    def test_a_quiet_athlete_clearing_the_bar_counts_the_same(self, store, squad):
        """Exactly the same as the athlete who did double. That is the point."""
        goal_id = make(store, squad)
        for offset in range(6):
            train(store, squad["athletes"][0], START + timedelta(days=offset))
        before = team_goals.get(store.conn, goal_id, TODAY).counted
        for offset in range(3):                      # exactly the bar
            train(store, squad["athletes"][1], START + timedelta(days=offset))
        after = team_goals.get(store.conn, goal_id, TODAY).counted
        assert after - before == 1

    def test_the_bar_cannot_be_set_high_enough_to_become_a_volume_target(
        self, store, squad
    ):
        with pytest.raises(GoalError, match="volume target"):
            make(store, squad, per_athlete_days=20, ends_on=(
                START + timedelta(days=25)).isoformat())

    def test_a_goal_with_no_bar_at_all_is_refused(self, store, squad):
        with pytest.raises(GoalError, match="personal bar"):
            make(store, squad, per_athlete_days=0, per_athlete_sessions=0)


class TestNobodyIsNamed:
    def test_the_squad_payload_carries_no_identities(self, store, squad):
        goal_id = make(store, squad)
        for offset in range(3):
            train(store, squad["athletes"][0], START + timedelta(days=offset))
        payload = str(team_goals.get(store.conn, goal_id, TODAY).to_dict())
        for athlete in squad["athletes"]:
            assert athlete["display_name"] not in payload
            assert f'"athlete_id": {athlete["id"]}' not in payload

    def test_there_is_no_count_of_who_has_not_got_there(self, store, squad):
        """A shortfall count is a name with the name removed. Everyone on a
        ten-person squad can work out who the two are."""
        goal_id = make(store, squad)
        keys = set(team_goals.get(store.conn, goal_id, TODAY).to_dict())
        for leaky in ("missing", "behind", "not_counted", "shortfall", "remaining"):
            assert leaky not in keys

    def test_the_headline_never_frames_anyone_as_the_reason(self, store, squad):
        goal_id = make(store, squad)
        for athlete in squad["athletes"][:4]:
            for offset in range(3):
                train(store, athlete, START + timedelta(days=offset))
        headline = team_goals.get(store.conn, goal_id, TODAY).headline().lower()
        for accusing in ("let us down", "need", "still waiting", "short by",
                         "only", "haven't", "have not"):
            assert accusing not in headline, f"headline accuses: {accusing!r}"

    def test_an_athlete_sees_their_own_standing_and_no_one_elses(
        self, store, squad
    ):
        goal_id = make(store, squad)
        for offset in range(3):
            train(store, squad["athletes"][0], START + timedelta(days=offset))
        goal = team_goals.get(store.conn, goal_id, TODAY)
        mine = team_goals.standing(
            store.conn, goal, squad["athletes"][1]["id"], TODAY).to_dict()
        assert mine["i_count"] is False
        assert mine["counted"] == 1               # the squad total is fine
        assert "Kid 0" not in str(mine)


class TestAnAthleteWhoCannotTrainIsNotAShortfall:
    """Same rule as the pre-practice card. Counting a hurt child as missing
    asks their squad to want them back before they are ready."""

    def test_they_come_out_of_the_denominator(self, store, squad):
        make(store, squad)
        store.report_discomfort(
            squad["athletes"][0]["id"], "knee", "hurts",
            day=TODAY - timedelta(days=2))
        goal = team_goals.for_team(store.conn, squad["team"]["id"], TODAY)[0]
        assert goal.eligible == 9 and goal.excused == 1

    def test_and_they_are_told_the_goal_is_not_waiting_on_them(
        self, store, squad
    ):
        goal_id = make(store, squad)
        store.report_discomfort(
            squad["athletes"][0]["id"], "knee", "hurts",
            day=TODAY - timedelta(days=2))
        goal = team_goals.get(store.conn, goal_id, TODAY)
        note = team_goals.standing(
            store.conn, goal, squad["athletes"][0]["id"], TODAY).note()
        assert "not waiting on you" in note

    def test_someone_mid_ramp_is_excused_too(self, store, squad):
        make(store, squad)
        athlete = squad["athletes"][0]
        report = store.report_discomfort(
            athlete["id"], "ankle", "hurts", day=TODAY - timedelta(days=5))
        store.resolve_discomfort(athlete["id"], report["id"],
                                 day=TODAY - timedelta(days=3))
        goal = team_goals.for_team(store.conn, squad["team"]["id"], TODAY)[0]
        assert goal.excused == 1

    def test_a_mild_niggle_does_not_excuse_anybody(self, store, squad):
        """Excusing on every report would let the denominator drift away from
        the squad, and would quietly reward saying you are sore."""
        make(store, squad)
        store.report_discomfort(
            squad["athletes"][0]["id"], "ankle", "niggle",
            day=TODAY - timedelta(days=2))
        goal = team_goals.for_team(store.conn, squad["team"]["id"], TODAY)[0]
        assert goal.excused == 0


class TestWhatAnAthleteReads:
    def test_a_near_miss_is_a_small_achievable_ask(self, store, squad):
        """Aimed at exactly the athlete this feature exists to reach."""
        goal_id = make(store, squad)
        for offset in range(2):
            train(store, squad["athletes"][0], START + timedelta(days=offset))
        goal = team_goals.get(store.conn, goal_id, TODAY)
        mine = team_goals.standing(store.conn, goal, squad["athletes"][0]["id"], TODAY)
        assert mine.note() == "One more day and you are in."

    def test_being_in_does_not_ask_for_more(self, store, squad):
        goal_id = make(store, squad)
        for offset in range(3):
            train(store, squad["athletes"][0], START + timedelta(days=offset))
        goal = team_goals.get(store.conn, goal_id, TODAY)
        note = team_goals.standing(
            store.conn, goal, squad["athletes"][0]["id"], TODAY).note()
        assert "for you, not the count" in note

    def test_an_athlete_sees_goals_for_every_team_they_are_on(self, store, squad):
        make(store, squad)
        assert len(team_goals.for_athlete(
            store.conn, squad["athletes"][0]["id"], TODAY)) == 1

    def test_a_goal_that_has_not_started_is_not_shown_yet(self, store, squad):
        make(store, squad, starts_on=(TODAY + timedelta(days=1)).isoformat(),
             ends_on=(TODAY + timedelta(days=7)).isoformat())
        assert team_goals.for_athlete(
            store.conn, squad["athletes"][0]["id"], TODAY) == []


class TestValidation:
    def test_a_target_bigger_than_the_squad_is_refused(self, store, squad):
        with pytest.raises(GoalError, match="only 10 athletes"):
            make(store, squad, target_athletes=99)

    def test_a_window_too_short_to_chase_is_refused(self, store, squad):
        with pytest.raises(GoalError, match="between"):
            make(store, squad, per_athlete_days=1,
                 starts_on=TODAY.isoformat(), ends_on=TODAY.isoformat())

    def test_a_window_too_long_to_feel_is_refused(self, store, squad):
        with pytest.raises(GoalError, match="between"):
            make(store, squad, starts_on=(TODAY - timedelta(days=60)).isoformat(),
                 ends_on=TODAY.isoformat())

    def test_a_bar_that_cannot_fit_in_the_window_is_refused(self, store, squad):
        with pytest.raises(GoalError, match="cannot be trained"):
            make(store, squad, per_athlete_days=6,
                 starts_on=(TODAY - timedelta(days=3)).isoformat(),
                 ends_on=TODAY.isoformat())

    def test_backwards_dates_are_refused(self, store, squad):
        with pytest.raises(GoalError, match="before it starts"):
            make(store, squad, starts_on=TODAY.isoformat(),
                 ends_on=(TODAY - timedelta(days=7)).isoformat())


# ---------------------------------------------------------------------------
# Over the wire
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ATHLETEIQ_DB", str(tmp_path / "api.db"))
    from athleteiq import api

    api.app.dependency_overrides.clear()
    return TestClient(api.app)


@pytest.fixture
def wired(client):
    org = client.post(
        "/api/orgs", json={"name": "Northshore LC", "director_name": "Dir"}
    ).json()
    director = {"Authorization": f"Bearer {org['director']['token']}"}
    team = client.post("/api/teams", json={"name": "U15"}, headers=director).json()
    athlete = client.post(
        "/api/athletes",
        json={"display_name": "Jordan P.", "birth_year": 2011,
              "dominant_hand": "right", "guardian_consent": True,
              "join_code": team["join_code"]},
        headers=director,
    ).json()
    return {"director": director, "team": team, "athlete": athlete}


def goal_body(team_id, **kwargs):
    # Live dates: the endpoints read the real clock, so a window pinned to a
    # fixed TODAY would already be over by the time the request lands.
    now = date.today()
    body = {
        "team_id": team_id, "title": "Everyone out 3 days",
        "target_athletes": 1, "per_athlete_days": 3,
        "starts_on": now.isoformat(),
        "ends_on": (now + timedelta(days=6)).isoformat(),
    }
    body.update(kwargs)
    return body


class TestOverTheWire:
    def test_a_coach_can_set_one(self, client, wired):
        res = client.post("/api/coach/goals",
                          json=goal_body(wired["team"]["id"]),
                          headers=wired["director"])
        assert res.status_code == 201
        assert res.json()["target_athletes"] == 1

    def test_the_bar_cap_is_enforced_at_the_edge_too(self, client, wired):
        """Not only in the module. A validation that lives in one layer is a
        validation somebody routes around."""
        res = client.post(
            "/api/coach/goals",
            json=goal_body(wired["team"]["id"], per_athlete_days=30),
            headers=wired["director"],
        )
        assert res.status_code == 422

    def test_a_bad_goal_comes_back_readable_not_as_a_500(self, client, wired):
        res = client.post(
            "/api/coach/goals",
            json=goal_body(wired["team"]["id"], target_athletes=99),
            headers=wired["director"],
        )
        assert res.status_code == 400
        assert "only 1 athletes" in res.json()["detail"]

    def test_an_athlete_sees_their_own_standing(self, client, wired):
        client.post("/api/coach/goals", json=goal_body(wired["team"]["id"]),
                    headers=wired["director"])
        headers = {"Authorization": f"Bearer {wired['athlete']['token']}"}
        goals = client.get("/api/me/goals", headers=headers).json()["goals"]
        assert len(goals) == 1
        assert goals[0]["i_count"] is False
        assert goals[0]["my_note"]

    def test_an_athlete_cannot_set_a_goal(self, client, wired):
        headers = {"Authorization": f"Bearer {wired['athlete']['token']}"}
        assert client.post("/api/coach/goals", json=goal_body(wired["team"]["id"]),
                           headers=headers).status_code == 403

    def test_the_coach_list_carries_no_names(self, client, wired):
        client.post("/api/coach/goals", json=goal_body(wired["team"]["id"]),
                    headers=wired["director"])
        body = client.get("/api/coach/goals", headers=wired["director"]).text
        assert "Jordan" not in body

    def test_another_program_cannot_set_a_goal_on_your_team(self, client, wired):
        other = client.post(
            "/api/orgs", json={"name": "Southside", "director_name": "Other"}
        ).json()
        headers = {"Authorization": f"Bearer {other['director']['token']}"}
        res = client.post("/api/coach/goals", json=goal_body(wired["team"]["id"]),
                          headers=headers)
        assert res.status_code in (400, 403)
        assert client.get("/api/coach/goals", headers=headers).json()["goals"] == []

    def test_closing_one_takes_it_off_the_athletes_screen(self, client, wired):
        goal = client.post("/api/coach/goals", json=goal_body(wired["team"]["id"]),
                           headers=wired["director"]).json()
        assert client.delete(f"/api/coach/goals/{goal['id']}",
                             headers=wired["director"]).status_code == 200
        headers = {"Authorization": f"Bearer {wired['athlete']['token']}"}
        assert client.get("/api/me/goals", headers=headers).json()["goals"] == []
