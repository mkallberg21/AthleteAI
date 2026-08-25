"""Telling a coach when an assignment is not landing.

The assignment loop reported compliance passively: a coach who did not open
the dashboard never learned their assignment went nowhere.

Both touches are deliberately about the *assignment* rather than about the
children. "Four of eighteen with three days left" invites a coach to ask
whether it was too much, unclear, or badly timed. A list of names invites them
to chase four kids -- and a stalling assignment is more often a coaching
problem than a compliance one. The names live on the compliance table behind a
login, already sorted worst-first, which is the right place for a nudge and
the wrong place for a broadcast.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from athleteiq import absence, assignments as assignments_mod, notifications
from athleteiq.db import connect
from athleteiq.store import Store

TODAY = date(2026, 8, 20)
START = TODAY - timedelta(days=5)
DUE = TODAY + timedelta(days=5)


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "st.db"))


@pytest.fixture
def squad(store):
    org = store.create_org("Northshore")
    director = store.create_user(org, "director", "Coach Ada")
    team = store.create_team(org, "U15 Boys")
    athletes = []
    for i in range(10):
        person = store.create_user(
            org, "athlete", f"Kid {i}", birth_year=2011, dominant_hand="right")
        store.join_team(team["join_code"], person["id"])
        athletes.append(person)
    return {"org": org, "director": director, "team": team, "athletes": athletes}


def assign(store, squad, **kwargs):
    params = dict(
        org_id=squad["org"], team_id=squad["team"]["id"],
        created_by=squad["director"]["id"], drill_key="gen_squat",
        title="Fifty squats", target_reps=50,
        starts_on=START.isoformat(), due_on=DUE.isoformat(),
    )
    params.update(kwargs)
    return assignments_mod.create(store.conn, **params)


def finish(store, athlete, day=None, reps=60):
    """Enough work to complete a 50-rep assignment."""
    rng = random.Random(athlete["id"])
    started = store.start_session(athlete["id"], "gen_squat")
    t, events = 0, []
    for _ in range(reps):
        t += max(600, int(rng.gauss(1400, 200)))
        value = 74.0 + rng.uniform(-3, 3)
        events.append({"t_ms": t, "hand": "none", "confidence": 0.9,
                       "rom": value, "peak": value,
                       "cycle_ms": 1150 + rng.randint(-120, 120)})
    store.submit_session(
        athlete["id"], started["session_id"], started["nonce"],
        duration_ms=t + 900, reps=events, mean_confidence=0.9)
    store.conn.execute(
        "UPDATE sessions SET submitted_at = ? WHERE id = ?",
        ((day or TODAY).isoformat() + "T18:00:00+00:00", started["session_id"]))
    store.conn.commit()


def coach_notes(store, squad):
    return store.conn.execute(
        "SELECT title, body FROM notifications WHERE user_id = ? "
        "AND kind = 'assignment_stalled' ORDER BY id",
        (squad["director"]["id"],),
    ).fetchall()


class TestTheHalfwayNudge:
    def test_it_fires_when_almost_nobody_has_finished(self, store, squad):
        assign(store, squad)
        halfway = START + timedelta(days=5)
        notifications.generate_assignment_stalls(store.conn, halfway)
        notes = coach_notes(store, squad)
        assert len(notes) == 1
        assert "not landing" in notes[0]["title"]

    def test_it_does_not_fire_when_the_squad_is_getting_on_with_it(
        self, store, squad
    ):
        assign(store, squad)
        for athlete in squad["athletes"][:5]:
            finish(store, athlete, day=START + timedelta(days=2))
        notifications.generate_assignment_stalls(
            store.conn, START + timedelta(days=5))
        assert coach_notes(store, squad) == []

    def test_it_asks_about_the_assignment_not_about_the_children(
        self, store, squad
    ):
        """A stalling assignment is more often a coaching problem than a
        compliance one, and the copy should point a coach at that first."""
        assign(store, squad)
        notifications.generate_assignment_stalls(
            store.conn, START + timedelta(days=5))
        body = coach_notes(store, squad)[0]["body"]
        assert "too much, unclear, or badly timed" in body
        assert "there is still time to change it" in body

    def test_no_child_is_named(self, store, squad):
        assign(store, squad)
        for athlete in squad["athletes"][:2]:
            finish(store, athlete, day=START + timedelta(days=1))
        notifications.generate_assignment_stalls(
            store.conn, START + timedelta(days=5))
        text = str(coach_notes(store, squad))
        for athlete in squad["athletes"]:
            assert athlete["display_name"] not in text

    def test_it_fires_once_however_often_the_cron_runs(self, store, squad):
        assign(store, squad)
        halfway = START + timedelta(days=5)
        for _ in range(3):
            notifications.generate_assignment_stalls(store.conn, halfway)
        assert len(coach_notes(store, squad)) == 1

    def test_a_window_too_short_to_have_a_halfway_is_skipped(self, store, squad):
        assign(store, squad, starts_on=TODAY.isoformat(),
               due_on=(TODAY + timedelta(days=1)).isoformat())
        notifications.generate_assignment_stalls(store.conn, TODAY)
        assert coach_notes(store, squad) == []


class TestTheClosingSummary:
    """A coach who set an assignment deserves to know how it went whether or
    not they opened the dashboard. That is the loop this closes."""

    def test_a_good_one_is_reported_as_working(self, store, squad):
        assign(store, squad)
        for athlete in squad["athletes"][:9]:
            finish(store, athlete)
        notifications.generate_assignment_stalls(store.conn, DUE)
        body = coach_notes(store, squad)[-1]["body"]
        assert "That one worked" in body

    def test_a_middling_one_points_at_the_compliance_table(self, store, squad):
        assign(store, squad)
        for athlete in squad["athletes"][:5]:
            finish(store, athlete)
        notifications.generate_assignment_stalls(store.conn, DUE)
        assert "compliance table" in coach_notes(store, squad)[-1]["body"]

    def test_a_failed_one_blames_the_assignment_not_the_squad(
        self, store, squad
    ):
        assign(store, squad)
        finish(store, squad["athletes"][0])
        notifications.generate_assignment_stalls(store.conn, DUE)
        body = coach_notes(store, squad)[-1]["body"]
        assert "usually the assignment rather than the squad" in body
        assert "smaller target or a longer window" in body

    def test_it_always_fires_even_when_the_assignment_went_well(
        self, store, squad
    ):
        assign(store, squad)
        for athlete in squad["athletes"]:
            finish(store, athlete)
        notifications.generate_assignment_stalls(store.conn, DUE)
        assert len(coach_notes(store, squad)) == 1


class TestWhoIsCounted:
    """Same rule as the pre-practice card, team goals and the evaluation
    export: an athlete who cannot train is not a shortfall."""

    def test_an_injured_athlete_leaves_the_denominator(self, store, squad):
        assign(store, squad)
        for athlete in squad["athletes"][:4]:
            store.report_discomfort(
                athlete["id"], "knee", "hurts", day=TODAY - timedelta(days=1))
        for athlete in squad["athletes"][4:]:
            finish(store, athlete)
        notifications.generate_assignment_stalls(store.conn, DUE)
        assert "6 of 6" in coach_notes(store, squad)[-1]["body"]

    def test_an_athlete_away_leaves_it_too(self, store, squad):
        assign(store, squad)
        absence.schedule(
            store.conn, squad["athletes"][0]["id"],
            (DUE - timedelta(days=3)).isoformat(), DUE.isoformat(),
            today=DUE - timedelta(days=3))
        for athlete in squad["athletes"][1:]:
            finish(store, athlete)
        notifications.generate_assignment_stalls(store.conn, DUE)
        assert "9 of 9" in coach_notes(store, squad)[-1]["body"]

    def test_a_squad_where_nobody_can_train_produces_nothing(
        self, store, squad
    ):
        """Telling a coach that nought of nought finished is noise."""
        assign(store, squad)
        for athlete in squad["athletes"]:
            store.report_discomfort(
                athlete["id"], "knee", "hurts", day=TODAY - timedelta(days=1))
        notifications.generate_assignment_stalls(store.conn, DUE)
        assert coach_notes(store, squad) == []


class TestItReachesTheRightPerson:
    def test_it_goes_to_whoever_set_the_assignment(self, store, squad):
        other = store.create_user(squad["org"], "coach", "Coach Bee")
        assign(store, squad, created_by=other["id"])
        notifications.generate_assignment_stalls(
            store.conn, START + timedelta(days=5))
        assert coach_notes(store, squad) == []
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? "
            "AND kind = 'assignment_stalled'", (other["id"],),
        ).fetchone()["n"] == 1

    def test_no_athlete_receives_it(self, store, squad):
        """It is a note about how an assignment is going, addressed to the
        person who set it. A child receiving it would read it as a telling-off
        for something they may well have finished."""
        assign(store, squad)
        notifications.generate_assignment_stalls(
            store.conn, START + timedelta(days=5))
        ids = ",".join(str(a["id"]) for a in squad["athletes"])
        assert store.conn.execute(
            f"SELECT COUNT(*) AS n FROM notifications WHERE user_id IN ({ids}) "
            "AND kind = 'assignment_stalled'"
        ).fetchone()["n"] == 0

    def test_the_scheduled_run_includes_it(self, store, squad):
        assert "assignment_stalls" in notifications.run_all(store.conn, TODAY)
