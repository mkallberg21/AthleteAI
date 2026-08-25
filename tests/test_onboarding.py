"""Getting a new program from nothing to a working first week.

The checklist is computed from the database every time. These tests are mostly
about that: a step has to un-tick itself when the thing it describes goes away,
because a checklist that was true once is worse than none.
"""

import random
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from athleteiq import guardians
from athleteiq import onboarding as O
from athleteiq.db import connect
from athleteiq.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "t.db"))


@pytest.fixture
def program(store):
    org = store.create_org("Northshore")
    director = store.create_user(org, "director", "Coach Ada")
    return {"store": store, "org": org, "director": director}


def steps(result):
    return {s["key"]: s for s in result["steps"]}


def train(store, athlete_id, seed=1):
    slot = store.start_session(athlete_id, "gen_squat")
    rng = random.Random(seed)
    t, reps = 0, []
    for _ in range(30):
        t += max(900, int(rng.gauss(2000, 300)))
        reps.append({"t_ms": t, "confidence": 0.9,
                     "rom": round(78 * (1 + rng.gauss(0, 0.08)), 1),
                     "peak": 55.0, "cycle_ms": 2000})
    return store.submit_session(
        athlete_id, slot["session_id"], slot["nonce"],
        duration_ms=t + 800, reps=reps, mean_confidence=0.9,
    )


class TestItStartsAtTheBeginning:

    def test_a_brand_new_program_has_done_nothing(self, program):
        result = O.progress(program["store"].conn, program["org"])
        assert result["complete"] is False
        assert result["required_done"] == 0
        assert result["next"]["key"] == "team"

    def test_the_next_step_is_the_first_undone_one(self, program):
        store = program["store"]
        store.create_team(program["org"], "U15")
        assert O.progress(store.conn, program["org"])["next"]["key"] == "athletes"

    def test_the_order_matches_what_unblocks_what(self):
        """A team before an athlete, an athlete before a session. The order is
        the whole reason this exists."""
        keys = [s.key for s in O.PROGRAM_STEPS if s.required]
        assert keys == ["team", "athletes", "first_session"]


class TestItIsComputedNotRemembered:

    def test_a_step_unticks_when_the_thing_goes_away(self, program):
        """The difference between a checklist that is true and one that was
        true once."""
        store = program["store"]
        team = store.create_team(program["org"], "U15")
        assert steps(O.progress(store.conn, program["org"]))["team"]["done"] is True

        store.conn.execute("DELETE FROM teams WHERE id = ?", (team["id"],))
        store.conn.commit()
        assert steps(O.progress(store.conn, program["org"]))["team"]["done"] is False

    def test_a_held_session_does_not_count_as_training(self, program):
        """Until one session actually counts, the chain is not proven."""
        store = program["store"]
        team = store.create_team(program["org"], "U15")
        athlete = store.create_user(
            program["org"], "athlete", "Jordan P.", birth_year=2011,
            dominant_hand="right",
        )
        store.join_team(team["join_code"], athlete["id"])

        slot = store.start_session(athlete["id"], "gen_squat")
        # Metronomic timing, which the integrity layer holds for review.
        reps = [{"t_ms": i * 2000, "confidence": 0.9, "rom": 78.0,
                 "peak": 55.0, "cycle_ms": 2000} for i in range(1, 30)]
        result = store.submit_session(
            athlete["id"], slot["session_id"], slot["nonce"],
            duration_ms=60_000, reps=reps, mean_confidence=0.9,
        )
        # Which flavour of not-counted it is does not matter here; the step
        # turns on a session the program can actually rely on.
        assert result["status"] != "counted"
        assert steps(O.progress(store.conn, program["org"]))["first_session"]["done"] is False

    def test_a_counted_session_finishes_the_required_steps(self, program):
        store = program["store"]
        team = store.create_team(program["org"], "U15")
        athlete = store.create_user(
            program["org"], "athlete", "Jordan P.", birth_year=2011,
            dominant_hand="right",
        )
        store.join_team(team["join_code"], athlete["id"])
        assert train(store, athlete["id"])["status"] == "counted"

        result = O.progress(store.conn, program["org"])
        assert result["complete"] is True
        assert result["required_done"] == result["required_total"]

    def test_the_signing_up_director_does_not_count_as_extra_staff(self, program):
        result = steps(O.progress(program["store"].conn, program["org"]))
        assert result["staff"]["done"] is False

        program["store"].create_user(program["org"], "coach", "A Second Coach")
        after = steps(O.progress(program["store"].conn, program["org"]))
        assert after["staff"]["done"] is True

    def test_another_program_does_not_tick_this_one_off(self, program):
        store = program["store"]
        other = store.create_org("Rival")
        store.create_team(other, "Their Team")
        assert steps(O.progress(store.conn, program["org"]))["team"]["done"] is False


class TestOptionalStepsDoNotBlock:

    def test_required_completeness_ignores_the_optional_ones(self, program):
        store = program["store"]
        team = store.create_team(program["org"], "U15")
        athlete = store.create_user(program["org"], "athlete", "Jordan P.", birth_year=2011)
        store.join_team(team["join_code"], athlete["id"])
        train(store, athlete["id"])

        result = O.progress(store.conn, program["org"])
        assert result["complete"] is True
        assert any(not s["done"] for s in result["steps"] if not s["required"])

    def test_writing_a_recognition_message_ticks_its_step(self, program):
        store = program["store"]
        store.set_recognition_template(
            program["org"], "streak_5", "Nice one {first_name}.", True,
            program["director"]["id"],
        )
        assert steps(O.progress(store.conn, program["org"]))["recognition"]["done"] is True


class TestTheGateThatSurprisesPeople:
    """Enforcement starts the moment a parent is linked, so inviting parents
    can lock athletes out overnight -- and the athlete sees a clear message
    while the coach sees nothing."""

    def _athlete_with_parent(self, program, consent=False):
        store = program["store"]
        team = store.create_team(program["org"], "U15")
        athlete = store.create_user(
            program["org"], "athlete", "Jordan P.", birth_year=2011,
            dominant_hand="right",
        )
        store.join_team(team["join_code"], athlete["id"])
        invite = guardians.create_invite(
            store.conn, athlete["id"], created_by=program["director"]["id"],
        )
        guardian = guardians.redeem_invite(store.conn, invite["code"], "A Parent")
        if consent:
            guardians.set_consent(
                store.conn, athlete["id"], guardian["guardian_id"],
                guardians.Scope.PARTICIPATION, True,
            )
        store.conn.commit()
        return athlete, guardian

    def test_it_is_named_before_a_coach_has_to_work_it_out(self, program):
        self._athlete_with_parent(program)
        found = O.blockers(program["store"].conn, program["org"])
        assert len(found) == 1
        assert found[0]["key"] == "awaiting_consent"
        assert "Jordan P." in found[0]["detail"]
        assert "Nothing is broken" in found[0]["detail"]

    def test_it_clears_the_moment_the_parent_says_yes(self, program):
        self._athlete_with_parent(program, consent=True)
        assert O.blockers(program["store"].conn, program["org"]) == []

    def test_an_athlete_with_no_parent_linked_is_not_blocked(self, program):
        """Enforcement begins when a parent joins, not before."""
        store = program["store"]
        team = store.create_team(program["org"], "U15")
        athlete = store.create_user(program["org"], "athlete", "Jordan P.", birth_year=2011)
        store.join_team(team["join_code"], athlete["id"])
        assert O.blockers(store.conn, program["org"]) == []

    def test_blockers_are_kept_apart_from_setup(self, program):
        """They are breakage, not progress, and turn up long after setup."""
        self._athlete_with_parent(program)
        result = O.progress(program["store"].conn, program["org"])
        assert result["blockers"]
        assert all("blocker" not in s["key"] for s in result["steps"])


class TestAHouseholdGetsAShorterList:

    def test_a_family_is_not_told_to_create_a_team(self, store):
        """Creating one is part of signing up, so listing it would be a step
        that is already done before they read it."""
        made = store.create_family("The Pierces", "Dana Pierce")
        result = O.progress(store.conn, made["org_id"], kind="family")
        assert "team" not in {s["key"] for s in result["steps"]}
        assert result["next"]["key"] == "athletes"

    def test_it_says_children_rather_than_athletes(self, store):
        made = store.create_family("The Pierces", "Dana Pierce")
        result = steps(O.progress(store.conn, made["org_id"], kind="family"))
        assert "children" in result["athletes"]["title"].lower()

    def test_a_household_is_not_asked_to_hire_a_coach(self, store):
        made = store.create_family("The Pierces", "Dana Pierce")
        keys = {s["key"] for s in O.progress(store.conn, made["org_id"], kind="family")["steps"]}
        assert "staff" not in keys and "parents" not in keys

    def test_adding_a_child_and_a_session_finishes_it(self, store):
        made = store.create_family("The Pierces", "Dana Pierce")
        child = store.add_family_athlete(
            made["org_id"], made["parent"]["id"], "Jordan Pierce",
            birth_year=2013, join_code=made["team"]["join_code"],
        )
        train(store, child["id"])
        assert O.progress(store.conn, made["org_id"], kind="family")["complete"] is True


class TestTheStepsPointSomewhereReal:

    def test_every_anchor_matches_an_element_on_the_dashboard(self):
        """A "Go" button that scrolls to nothing is worse than no button."""
        html = (
            Path(__file__).resolve().parent.parent
            / "athleteiq" / "web" / "static" / "coach.html"
        ).read_text()
        ids = set(re.findall(r'id="([a-z0-9-]+)"', html))
        for step in (*O.PROGRAM_STEPS, *O.FAMILY_STEPS):
            if step.anchor:
                assert step.anchor in ids, f"{step.key} points at {step.anchor}"

    def test_every_step_says_what_to_do(self):
        for step in (*O.PROGRAM_STEPS, *O.FAMILY_STEPS):
            assert step.title and step.detail, step.key
            assert len(step.detail) > 20, step.key
