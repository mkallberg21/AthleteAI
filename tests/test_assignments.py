"""Assignments and compliance.

Compliance is derived from counted sessions rather than stored, so these tests
lean on that: a session that is rejected or later approved must move the
numbers without anything being recomputed by hand.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from offdays import assignments
from offdays.assignments import AssignmentError
from offdays.db import connect
from offdays.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "a.db"))


@pytest.fixture
def program(store):
    org = store.create_org("Northshore")
    coach = store.create_user(org, "coach", "Coach R")
    team = store.create_team(org, "Varsity")
    athletes = []
    for name, hand in (("Jordan", "right"), ("Sam", "left")):
        a = store.create_user(org, "athlete", name, dominant_hand=hand)
        store.join_team(team["join_code"], a["id"])
        athletes.append(a)
    return {"org": org, "coach": coach, "team": team, "athletes": athletes}


def make(store, program, **kw):
    today = date.today()
    params = dict(
        org_id=program["org"],
        team_id=program["team"]["id"],
        created_by=program["coach"]["id"],
        drill_key="lax_wall_ball",
        title="Week 1",
        starts_on=(today - timedelta(days=1)).isoformat(),
        due_on=(today + timedelta(days=5)).isoformat(),
        target_reps=300,
        target_sessions=2,
        min_offhand=0.40,
    )
    params.update(kw)
    return assignments.create(store.conn, **params)


def train(store, athlete_id, reps=160, seed=1, offhand=0.5, drill="lax_wall_ball", when=None):
    slot = store.start_session(athlete_id, drill)
    rng = random.Random(seed)
    t, events = 0, []
    for _ in range(reps):
        t += max(150, int(rng.gauss(880, 190)))
        hand = "left" if rng.random() < offhand else "right"
        events.append({"t_ms": t, "hand": hand, "confidence": 0.88})
    return store.submit_session(
        athlete_id, slot["session_id"], slot["nonce"],
        duration_ms=t + 700, reps=events, mean_confidence=0.88, completed_at=when,
    )


class TestCreation:
    def test_creates_and_reads_back(self, store, program):
        aid = make(store, program)
        got = assignments.get(store.conn, aid)
        assert got is not None
        assert got.title == "Week 1"
        assert got.target_reps == 300

    def test_rejects_unknown_drill(self, store, program):
        with pytest.raises(AssignmentError, match="unknown drill"):
            make(store, program, drill_key="nope")

    def test_rejects_due_before_start(self, store, program):
        today = date.today()
        with pytest.raises(AssignmentError, match="due date"):
            make(
                store, program,
                starts_on=today.isoformat(),
                due_on=(today - timedelta(days=3)).isoformat(),
            )

    def test_rejects_an_assignment_with_no_targets(self, store, program):
        with pytest.raises(AssignmentError, match="at least one target"):
            make(store, program, target_reps=0, target_sessions=0, min_offhand=0.0)

    def test_rejects_offhand_target_on_a_drill_without_handedness(self, store, program):
        """A squat has no off-hand, so requiring one is a coach error worth catching."""
        with pytest.raises(AssignmentError, match="handedness"):
            make(store, program, drill_key="gen_squat", min_offhand=0.4)

    def test_rejects_a_team_from_another_program(self, store, program):
        other_org = store.create_org("Rival")
        other_team = store.create_team(other_org, "Theirs")
        with pytest.raises(AssignmentError, match="different program"):
            make(store, program, team_id=other_team["id"])

    def test_rejects_out_of_range_offhand(self, store, program):
        with pytest.raises(AssignmentError):
            make(store, program, min_offhand=1.4)


class TestCompliance:
    def test_no_work_means_nothing_met(self, store, program):
        aid = make(store, program)
        rows = assignments.compliance(store.conn, assignments.get(store.conn, aid))
        assert len(rows) == 2
        assert all(not r.complete for r in rows)
        assert all(r.reps_done == 0 for r in rows)

    def test_meeting_every_target_completes_it(self, store, program):
        aid = make(store, program)
        jordan = program["athletes"][0]["id"]
        train(store, jordan, reps=160, seed=1, offhand=0.5)
        train(store, jordan, reps=160, seed=2, offhand=0.5)

        progress = assignments.progress_for_athlete(
            store.conn, assignments.get(store.conn, aid), jordan, dominant_hand="right"
        )
        assert progress.sessions_done == 2
        assert progress.reps_done == 320
        assert progress.complete

    def test_volume_without_offhand_does_not_complete(self, store, program):
        """The whole point of the off-hand target is that reps alone don't satisfy it."""
        aid = make(store, program)
        sam = program["athletes"][1]["id"]
        # Sam is left-handed, so his off-hand is the right. Give him almost all left.
        train(store, sam, reps=170, seed=3, offhand=0.97)
        train(store, sam, reps=170, seed=4, offhand=0.97)

        progress = assignments.progress_for_athlete(
            store.conn, assignments.get(store.conn, aid), sam, dominant_hand="left"
        )
        assert progress.reps_met and progress.sessions_met
        assert not progress.offhand_met
        assert not progress.complete

    def test_offhand_is_relative_to_the_athletes_dominant_hand(self, store, program):
        """Identical work must score differently for a lefty and a righty."""
        aid = make(store, program)
        assignment = assignments.get(store.conn, aid)
        jordan, sam = (a["id"] for a in program["athletes"])
        train(store, jordan, reps=100, seed=7, offhand=0.9)
        train(store, sam, reps=100, seed=7, offhand=0.9)

        righty = assignments.progress_for_athlete(store.conn, assignment, jordan, dominant_hand="right")
        lefty = assignments.progress_for_athlete(store.conn, assignment, sam, dominant_hand="left")
        assert righty.offhand_share > 0.8   # mostly left = mostly off-hand
        assert lefty.offhand_share < 0.2    # mostly left = mostly dominant

    def test_a_zero_target_is_met_by_default(self, store, program):
        aid = make(store, program, target_reps=0, target_sessions=1, min_offhand=0.0)
        jordan = program["athletes"][0]["id"]
        train(store, jordan, reps=60, seed=5)
        progress = assignments.progress_for_athlete(
            store.conn, assignments.get(store.conn, aid), jordan, dominant_hand="right"
        )
        assert progress.reps_met and progress.offhand_met and progress.complete

    def test_sessions_outside_the_window_do_not_count(self, store, program):
        today = date.today()
        aid = make(
            store, program,
            starts_on=(today - timedelta(days=1)).isoformat(),
            due_on=(today + timedelta(days=1)).isoformat(),
        )
        jordan = program["athletes"][0]["id"]
        # Inside the 14-day offline backdate limit so it is honoured, but
        # outside this assignment's window.
        old = (today - timedelta(days=10)).isoformat() + "T12:00:00+00:00"
        train(store, jordan, reps=200, seed=6, when=old)

        progress = assignments.progress_for_athlete(
            store.conn, assignments.get(store.conn, aid), jordan, dominant_hand="right"
        )
        assert progress.sessions_done == 0

    def test_a_different_drill_does_not_count(self, store, program):
        aid = make(store, program)
        jordan = program["athletes"][0]["id"]
        train(store, jordan, reps=40, seed=8, drill="gen_squat")
        progress = assignments.progress_for_athlete(
            store.conn, assignments.get(store.conn, aid), jordan, dominant_hand="right"
        )
        assert progress.sessions_done == 0

    def test_compliance_is_sorted_worst_first(self, store, program):
        """The coach opens this to find who needs a nudge."""
        aid = make(store, program)
        jordan = program["athletes"][0]["id"]
        train(store, jordan, reps=160, seed=1)
        train(store, jordan, reps=160, seed=2)
        rows = assignments.compliance(store.conn, assignments.get(store.conn, aid))
        assert rows[0].reps_done < rows[-1].reps_done
        assert rows[-1].complete


class TestScoping:
    def test_unscoped_assignment_covers_the_whole_team(self, store, program):
        aid = make(store, program)
        rows = assignments.compliance(store.conn, assignments.get(store.conn, aid))
        assert len(rows) == 2

    def test_scoped_assignment_covers_only_named_athletes(self, store, program):
        jordan = program["athletes"][0]["id"]
        aid = make(store, program, athlete_ids=[jordan])
        rows = assignments.compliance(store.conn, assignments.get(store.conn, aid))
        assert [r.athlete_id for r in rows] == [jordan]

    def test_a_scoped_assignment_is_hidden_from_other_athletes(self, store, program):
        jordan, sam = (a["id"] for a in program["athletes"])
        make(store, program, athlete_ids=[jordan])
        assert len(assignments.for_athlete(store.conn, jordan)) == 1
        assert assignments.for_athlete(store.conn, sam) == []


class TestLifecycle:
    def test_athlete_sees_open_assignments(self, store, program):
        make(store, program)
        items = assignments.for_athlete(store.conn, program["athletes"][0]["id"])
        assert len(items) == 1
        assert items[0]["progress"]["complete"] is False

    def test_future_assignments_are_not_shown_yet(self, store, program):
        today = date.today()
        make(
            store, program,
            starts_on=(today + timedelta(days=3)).isoformat(),
            due_on=(today + timedelta(days=9)).isoformat(),
        )
        assert assignments.for_athlete(store.conn, program["athletes"][0]["id"]) == []

    def test_deactivating_removes_it_from_both_views(self, store, program):
        aid = make(store, program)
        assignments.deactivate(store.conn, aid)
        assert assignments.list_for_org(store.conn, program["org"]) == []
        assert assignments.for_athlete(store.conn, program["athletes"][0]["id"]) == []

    def test_deactivated_still_readable_with_include_inactive(self, store, program):
        aid = make(store, program)
        assignments.deactivate(store.conn, aid)
        got = assignments.list_for_org(store.conn, program["org"], include_inactive=True)
        assert len(got) == 1 and got[0].active is False
