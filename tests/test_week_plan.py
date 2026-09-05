"""The athlete's home screen: what this week actually asks for.

This is the first thing a thirteen-year-old sees when they open the app, and
until now it had no tests at all. Two bugs lived in it as a result, both of
which only appeared once an athlete had real data:

* The assignments list was re-wrapped as though `assignments.for_athlete`
  returned Assignment objects. It returns dicts. So the endpoint raised
  AttributeError for any athlete who actually had an open assignment, and
  worked only for athletes who had nothing to show.

* The endpoint called `_athlete_age` without importing it, so it raised
  NameError on every request it ever received.

* The week's sentence was handed the whole benchmarks report instead of its
  budget section, so every number it read missed and defaulted to zero. A
  child on a 75-minute band was told to aim for "about 0 minutes across 0
  days".

Both are the same shape of mistake: a dict where an object was assumed, and a
wrapper where its contents were assumed. Neither is visible in a unit test of
the pieces; both are obvious the moment you ask for a real athlete's week.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from offdays import assignments
from offdays.db import connect
from offdays.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "w.db"))


@pytest.fixture
def athlete(store):
    """One thirteen-year-old on a team, with an open assignment waiting."""
    org = store.create_org("Nashville Dogs")
    coach = store.create_user(org, "coach", "Coach Tommy")
    team = store.create_team(org, "2031 Red", "2026", age_group="2031")
    person = store.create_user(
        org, "athlete", "Scott Anderson", birth_year=date.today().year - 13,
        dominant_hand="right", guardian_consent=True)
    store.join_team(team["join_code"], person["id"])

    today = date.today()
    assignments.create(
        store.conn,
        org_id=org, team_id=team["id"], created_by=coach["id"],
        drill_key="lax_wall_ball", title="Wall Ball Week",
        starts_on=(today - timedelta(days=1)).isoformat(),
        due_on=(today + timedelta(days=5)).isoformat(),
        target_reps=600, target_sessions=3, min_offhand=0.35,
    )
    return {"org": org, "team": team, "id": person["id"]}


class TestItSurvivesHavingSomethingToShow:
    def test_an_athlete_with_an_open_assignment_gets_a_week_plan(self, store, athlete):
        """The regression. This raised AttributeError for exactly the athletes
        the screen was written for."""
        plan = store.week_plan(athlete_id=athlete["id"]).to_dict()
        assert len(plan["assignments"]) == 1

    def test_each_assignment_carries_its_own_progress(self, store, athlete):
        """The screen leads with what was asked and how far along they are, so
        progress has to survive the trip rather than being recomputed."""
        a = store.week_plan(athlete_id=athlete["id"]).to_dict()["assignments"][0]
        assert "progress" in a and "days_remaining" in a
        assert a["drill_key"] == "lax_wall_ball"
        assert a["progress"]["reps_done"] == 0
        assert a["progress"]["sessions_done"] == 0

    def test_an_athlete_with_nothing_assigned_still_gets_a_plan(self, store):
        """The empty case used to be the only one that worked. It must keep
        working now that the populated one does."""
        org = store.create_org("Quiet LC")
        team = store.create_team(org, "Seniors")
        person = store.create_user(
            org, "athlete", "Nobody", birth_year=date.today().year - 13,
            dominant_hand="right")
        store.join_team(team["join_code"], person["id"])
        plan = store.week_plan(athlete_id=person["id"]).to_dict()
        assert plan["assignments"] == []
        assert plan["line"]


class TestTheSentenceUsesRealNumbers:
    def test_it_does_not_tell_a_child_to_train_zero_minutes(self, store, athlete):
        """The bug this pins read 'about 0 minutes across 0 days'. Any zero in
        the week's ask means the line is reading the wrong dict again."""
        line = store.week_plan(athlete_id=athlete["id"]).to_dict()["line"]
        assert "0 minutes" not in line
        assert "0 days" not in line

    def test_it_names_the_band_s_own_weekly_target(self, store, athlete):
        """A thirteen-year-old's band asks for 75 minutes over 3 days. If the
        line cannot see the band it cannot say either number."""
        plan = store.week_plan(athlete_id=athlete["id"]).to_dict()
        band = plan["budget"]["budget"]["band"]
        assert band["weekly_target"] == 75
        line = plan["line"]
        assert str(band["weekly_target"]) in line or "short of your week" in line

    def test_the_payload_still_carries_the_whole_report(self, store, athlete):
        """The fix must not narrow what the page receives. capture.html reads
        comparisons and position out of this, not just the budget."""
        budget = store.week_plan(athlete_id=athlete["id"]).to_dict()["budget"]
        assert "comparisons" in budget
        assert "budget" in budget and "band" in budget["budget"]

    def test_the_assignment_is_named_in_the_sentence(self, store, athlete):
        line = store.week_plan(athlete_id=athlete["id"]).to_dict()["line"]
        assert "session" in line and "reps" in line


class TestOverTheWire:
    def test_the_endpoint_does_not_500_for_a_real_athlete(self, tmp_path, athlete, store):
        """The bug reached production as a 500 on the athlete's home screen,
        so the test that would have caught it is an HTTP one."""
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient
        import offdays.api as api_module

        api_module._store = store
        try:
            client = TestClient(api_module.app)
            token = store.conn.execute(
                "SELECT token_hash FROM users WHERE id = ?", (athlete["id"],)
            ).fetchone()
            assert token is not None
            # Sign in with the athlete's own code by re-creating one we know.
            person = store.create_user(
                athlete["org"], "athlete", "Wire Kid",
                birth_year=date.today().year - 13, dominant_hand="right")
            store.join_team(athlete["team"]["join_code"], person["id"])
            r = client.get(
                "/api/me/week-plan",
                headers={"Authorization": f"Bearer {person['token']}"})
            assert r.status_code == 200, r.text
            assert "assignments" in r.json()
        finally:
            api_module._store = None
