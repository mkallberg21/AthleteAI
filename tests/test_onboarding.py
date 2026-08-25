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


class TestTheAthleteGetsAShorterOne:
    """Someone setting up a program will read six steps. A twelve-year-old who
    wants to go outside will read one."""

    @pytest.fixture
    def athlete(self, program):
        store = program["store"]
        team = store.create_team(program["org"], "U13")
        person = store.create_user(
            program["org"], "athlete", "Jordan P.", birth_year=2012,
            dominant_hand="right",
        )
        store.join_team(team["join_code"], person["id"])
        return person

    def test_there_is_exactly_one_required_step(self, program, athlete):
        result = O.athlete_progress(program["store"].conn, athlete["id"])
        assert result["required_total"] == 1
        assert result["next"]["key"] == "first_session"

    def test_recording_one_session_is_the_whole_requirement(self, program, athlete):
        store = program["store"]
        assert O.athlete_progress(store.conn, athlete["id"])["complete"] is False
        train(store, athlete["id"])
        assert O.athlete_progress(store.conn, athlete["id"])["complete"] is True

    def test_a_held_session_does_not_count(self, program, athlete):
        store = program["store"]
        slot = store.start_session(athlete["id"], "gen_squat")
        reps = [{"t_ms": i * 2000, "confidence": 0.9, "rom": 78.0,
                 "peak": 55.0, "cycle_ms": 2000} for i in range(1, 30)]
        store.submit_session(
            athlete["id"], slot["session_id"], slot["nonce"],
            duration_ms=60_000, reps=reps, mean_confidence=0.9,
        )
        assert O.athlete_progress(store.conn, athlete["id"])["complete"] is False

    def test_the_promise_is_stated_before_anyone_films_a_child(self, program, athlete):
        promise = O.athlete_progress(program["store"].conn, athlete["id"])["promise"]
        assert "never leaves" in promise
        assert "not to your coach" in promise

    def test_the_install_step_is_left_for_the_browser_to_answer(self, program, athlete):
        """Only the browser knows, so the server reports it undone rather than
        guessing."""
        result = steps(O.athlete_progress(program["store"].conn, athlete["id"]))
        assert result["install"]["done"] is False
        assert result["install"]["required"] is False

    def test_a_checkin_ticks_its_own_step(self, program, athlete):
        store = program["store"]
        store.check_in(athlete["id"], "fine")
        assert steps(O.athlete_progress(store.conn, athlete["id"]))["check_in"]["done"]

    def test_film_is_not_offered_when_the_program_has_curated_none(self, program, athlete):
        """Telling a kid to watch a clip that does not exist is a step they
        cannot take."""
        keys = {s["key"] for s in O.athlete_progress(
            program["store"].conn, athlete["id"])["steps"]}
        assert "film" not in keys

    def test_film_appears_once_a_coach_adds_one(self, program, athlete):
        store = program["store"]
        store.create_clip(program["org"], "dQw4w9WgXcQ", "Sliding early",
                          start_s=0, end_s=60)
        keys = {s["key"] for s in O.athlete_progress(store.conn, athlete["id"])["steps"]}
        assert "film" in keys


class TestWhatAnAthleteIsToldIsStoppingThem:

    @pytest.fixture
    def athlete(self, program):
        store = program["store"]
        team = store.create_team(program["org"], "U13")
        person = store.create_user(
            program["org"], "athlete", "Jordan P.", birth_year=2012,
            dominant_hand="right",
        )
        store.join_team(team["join_code"], person["id"])
        return person

    def test_a_linked_parent_who_has_not_answered_is_explained(self, program, athlete):
        """They meet this at the moment they press start. Saying it on the home
        screen is the difference between "waiting on my mum" and "this app is
        broken"."""
        store = program["store"]
        invite = guardians.create_invite(
            store.conn, athlete["id"], created_by=program["director"]["id"],
        )
        guardians.redeem_invite(store.conn, invite["code"], "A Parent")
        store.conn.commit()

        found = O.athlete_blockers(store.conn, athlete["id"])
        assert len(found) == 1
        assert "Nothing is wrong" in found[0]["detail"]
        assert "nudge" in found[0]["detail"]

    def test_it_clears_when_they_say_yes(self, program, athlete):
        store = program["store"]
        invite = guardians.create_invite(
            store.conn, athlete["id"], created_by=program["director"]["id"],
        )
        guardian = guardians.redeem_invite(store.conn, invite["code"], "A Parent")
        guardians.set_consent(
            store.conn, athlete["id"], guardian["guardian_id"],
            guardians.Scope.PARTICIPATION, True,
        )
        store.conn.commit()
        assert O.athlete_blockers(store.conn, athlete["id"]) == []

    def test_no_parent_linked_means_nothing_to_wait_for(self, program, athlete):
        assert O.athlete_blockers(program["store"].conn, athlete["id"]) == []

    def test_the_wording_is_for_a_child_not_a_coach(self, program, athlete):
        """The coach's version names athletes and explains the gate; this one
        is addressed to the person who cannot record."""
        store = program["store"]
        invite = guardians.create_invite(
            store.conn, athlete["id"], created_by=program["director"]["id"],
        )
        guardians.redeem_invite(store.conn, invite["code"], "A Parent")
        store.conn.commit()

        mine = O.athlete_blockers(store.conn, athlete["id"])[0]
        theirs = O.blockers(store.conn, program["org"])[0]
        assert "Jordan P." not in mine["detail"], "not addressed in the third person"
        assert "Jordan P." in theirs["detail"]


class TestWhatAParentHasToDecide:
    """A parent's job here is not to set anything up. It is to make one
    decision that is genuinely theirs, and padding that with tasks would dress
    a consent screen up as a product tour."""

    @pytest.fixture
    def family(self, program):
        store = program["store"]
        team = store.create_team(program["org"], "U13")
        kids = []
        for name, year in (("Jordan Pierce", 2012), ("Robin Pierce", 2016)):
            child = store.create_user(
                program["org"], "athlete", name, birth_year=year,
                dominant_hand="right",
            )
            store.join_team(team["join_code"], child["id"])
            kids.append(child)

        invite = guardians.create_invite(
            store.conn, kids[0]["id"], created_by=program["director"]["id"],
        )
        guardian = guardians.redeem_invite(store.conn, invite["code"], "Dana Pierce")
        second = guardians.create_invite(
            store.conn, kids[1]["id"], created_by=program["director"]["id"],
        )
        guardians.link_existing(store.conn, second["code"], guardian["guardian_id"])
        store.conn.commit()
        return {"store": store, "guardian": guardian, "kids": kids}

    def test_it_asks_per_child_not_per_account(self, family):
        """A guardian with two children can easily have decided for one."""
        result = O.parent_progress(family["store"].conn, family["guardian"]["guardian_id"])
        assert result["required_total"] == 2
        assert {a["display_name"] for a in result["athletes"]} == {
            "Jordan Pierce", "Robin Pierce",
        }

    def test_the_first_undecided_child_is_next(self, family):
        result = O.parent_progress(family["store"].conn, family["guardian"]["guardian_id"])
        assert result["next"]["display_name"] == "Jordan Pierce"

    def test_saying_no_finishes_the_decision(self, family):
        """A parent who said no has decided. A checklist that keeps asking
        after an answer is not respecting it."""
        store = family["store"]
        for child in family["kids"]:
            guardians.set_consent(
                store.conn, child["id"], family["guardian"]["guardian_id"],
                guardians.Scope.PARTICIPATION, False,
            )
        store.conn.commit()
        result = O.parent_progress(store.conn, family["guardian"]["guardian_id"])
        assert result["complete"] is True
        assert result["next"] is None

    def test_but_the_child_is_still_reported_as_unable_to_train(self, family):
        """Deciding and allowing are different things, and the second is what
        the athlete is waiting on."""
        store = family["store"]
        guardians.set_consent(
            store.conn, family["kids"][0]["id"], family["guardian"]["guardian_id"],
            guardians.Scope.PARTICIPATION, False,
        )
        store.conn.commit()
        result = O.parent_progress(store.conn, family["guardian"]["guardian_id"])
        assert "Jordan Pierce" in result["blocked"]

    def test_saying_yes_clears_both(self, family):
        store = family["store"]
        for child in family["kids"]:
            guardians.set_consent(
                store.conn, child["id"], family["guardian"]["guardian_id"],
                guardians.Scope.PARTICIPATION, True,
            )
        store.conn.commit()
        result = O.parent_progress(store.conn, family["guardian"]["guardian_id"])
        assert result["complete"] is True and result["blocked"] == []

    def test_the_leaderboard_choice_is_offered_but_never_required(self, family):
        """Left alone it stays off, which is the safe answer -- so it is worth
        surfacing once and never insisting on."""
        result = O.parent_progress(family["store"].conn, family["guardian"]["guardian_id"])
        step = next(
            s for s in result["athletes"][0]["steps"] if s["key"] == "leaderboard_name"
        )
        assert step["required"] is False
        assert "still competing" in step["detail"]

    def test_the_promise_is_shown_before_the_decision(self, family):
        result = O.parent_progress(family["store"].conn, family["guardian"]["guardian_id"])
        assert "never leaves" in result["promise"]

    def test_what_they_can_always_do_is_stated_not_made_into_tasks(self, family):
        """None of it is something to complete; all of it is worth knowing."""
        result = O.parent_progress(family["store"].conn, family["guardian"]["guardian_id"])
        joined = " ".join(result["rights"]).lower()
        for promise in ("withdraw", "download", "delete", "nobody can reply"):
            assert promise in joined
        keys = {s["key"] for a in result["athletes"] for s in a["steps"]}
        assert keys == {"participation", "leaderboard_name"}

    def test_a_guardian_of_nobody_gets_an_empty_answer(self, program):
        store = program["store"]
        stranger = store.create_user(program["org"], "coach", "Not A Parent")
        result = O.parent_progress(store.conn, stranger["id"])
        assert result["athletes"] == [] and result["complete"] is True

    def test_another_familys_children_are_not_listed(self, family, program):
        store = family["store"]
        other_child = store.create_user(
            program["org"], "athlete", "Someone Else", birth_year=2012,
        )
        invite = guardians.create_invite(
            store.conn, other_child["id"], created_by=program["director"]["id"],
        )
        guardians.redeem_invite(store.conn, invite["code"], "Another Parent")
        store.conn.commit()
        result = O.parent_progress(store.conn, family["guardian"]["guardian_id"])
        assert "Someone Else" not in {a["display_name"] for a in result["athletes"]}


class TestAnsweredIsNotTheSameAsGranted:

    def test_the_helper_tells_a_no_from_a_silence(self, program):
        store = program["store"]
        child = store.create_user(program["org"], "athlete", "Jordan P.", birth_year=2012)
        invite = guardians.create_invite(
            store.conn, child["id"], created_by=program["director"]["id"],
        )
        guardian = guardians.redeem_invite(store.conn, invite["code"], "A Parent")
        store.conn.commit()

        assert guardians.answered_scopes(store.conn, child["id"]) == set()
        guardians.set_consent(
            store.conn, child["id"], guardian["guardian_id"],
            guardians.Scope.PARTICIPATION, False,
        )
        store.conn.commit()

        assert guardians.Scope.PARTICIPATION in guardians.answered_scopes(
            store.conn, child["id"]
        )
        # And enforcement still reads it as not allowed, which is the point of
        # keeping the two ideas apart.
        assert guardians.current_consents(
            store.conn, child["id"]
        )[guardians.Scope.PARTICIPATION] is False


class TestACoachWhoJoinedSomebodyElsesProgram:
    """The teams, athletes and roster already exist. Handing them "create your
    first team" would be telling them to redo work that is done."""

    @pytest.fixture
    def joined(self, program):
        store = program["store"]
        team = store.create_team(program["org"], "U15 Boys")
        for name in ("Jordan P.", "Sam R.", "Alex T."):
            athlete = store.create_user(
                program["org"], "athlete", name, birth_year=2011,
                dominant_hand="right",
            )
            store.join_team(team["join_code"], athlete["id"])
        coach = store.create_user(program["org"], "coach", "Coach Ada")
        return {"store": store, "team": team, "coach": coach}

    def _assign(self, joined):
        store = joined["store"]
        store.conn.execute(
            "INSERT OR IGNORE INTO team_staff(team_id, user_id, role, created_at) "
            "VALUES (?,?,'coach',datetime('now'))",
            (joined["team"]["id"], joined["coach"]["id"]),
        )
        store.conn.commit()

    def test_they_are_not_told_to_build_what_exists(self, joined, program):
        result = O.staff_progress(
            joined["store"].conn, joined["coach"]["id"], program["org"],
        )
        keys = {s["key"] for s in result["steps"]}
        assert "team" not in keys and "athletes" not in keys
        assert result["kind"] == "joining"

    def test_nothing_is_required_of_them(self, joined, program):
        """Honest rather than an oversight: everything that has to happen for
        an assistant coach to start is done by somebody else."""
        result = O.staff_progress(
            joined["store"].conn, joined["coach"]["id"], program["org"],
        )
        assert result["required_total"] == 0
        assert result["complete"] is True

    def test_an_unassigned_coach_is_told_they_see_everything(self, joined, program):
        """The two scoping modes are opposites, so the message has to branch
        rather than guess. By default an unassigned coach falls back to the
        whole program -- telling them their dashboard is empty while they look
        at every child in the club would be worse than saying nothing."""
        result = O.staff_progress(
            joined["store"].conn, joined["coach"]["id"], program["org"],
        )
        assert result["blockers"][0]["key"] == "unscoped"
        assert "whole program" in result["blockers"][0]["title"]
        assert result["scope"]["athletes"] == 3, "and the count says so too"

    def test_under_strict_scoping_they_are_told_the_opposite(self, joined, program, monkeypatch):
        # CONFIG is frozen, so the module's reference to it is replaced rather
        # than the value mutated.
        from types import SimpleNamespace

        monkeypatch.setattr(O, "CONFIG", SimpleNamespace(strict_team_scope=True))
        result = O.staff_progress(
            joined["store"].conn, joined["coach"]["id"], program["org"],
        )
        assert result["blockers"][0]["key"] == "not_assigned"
        assert "Nothing is broken" in result["blockers"][0]["detail"]
        assert result["scope"]["athletes"] == 0

    def test_assigning_them_clears_it_and_shows_their_scope(self, joined, program):
        self._assign(joined)
        result = O.staff_progress(
            joined["store"].conn, joined["coach"]["id"], program["org"],
        )
        assert result["blockers"] == []
        assert result["scope"]["athletes"] == 3
        assert [t["name"] for t in result["scope"]["teams"]] == ["U15 Boys"]

    def test_they_are_told_messages_go_out_in_their_name(self, joined, program):
        """A coach might not realise that, and the first they would know is an
        athlete thanking them for something they did not write."""
        self._assign(joined)
        facts = " ".join(O.staff_progress(
            joined["store"].conn, joined["coach"]["id"], program["org"],
        )["facts"])
        assert "signed with your name" in facts
        assert "stays on their phone" in facts

    def test_the_scope_line_counts_only_their_own_athletes(self, joined, program):
        store = joined["store"]
        other = store.create_team(program["org"], "U13")
        stranger = store.create_user(
            program["org"], "athlete", "Not Theirs", birth_year=2013,
        )
        store.join_team(other["join_code"], stranger["id"])
        self._assign(joined)

        result = O.staff_progress(store.conn, joined["coach"]["id"], program["org"])
        assert result["scope"]["athletes"] == 3, "the U13 athlete is not theirs"

    def test_writing_a_message_ticks_only_for_the_one_who_wrote_it(
        self, joined, program,
    ):
        """The director's wording is not this coach's step."""
        store = joined["store"]
        self._assign(joined)
        store.set_recognition_template(
            program["org"], "streak_5", "From the director.", True,
            program["director"]["id"],
        )
        mine = steps(O.staff_progress(store.conn, joined["coach"]["id"], program["org"]))
        assert mine["recognition"]["done"] is False

        store.set_recognition_template(
            program["org"], "streak_3", "From me.", True, joined["coach"]["id"],
        )
        after = steps(O.staff_progress(store.conn, joined["coach"]["id"], program["org"]))
        assert after["recognition"]["done"] is True

    def test_the_review_step_is_absent_when_the_queue_is_empty(self, joined, program):
        """A tick for having done nothing teaches a coach the list is
        decorative."""
        self._assign(joined)
        keys = {s["key"] for s in O.staff_progress(
            joined["store"].conn, joined["coach"]["id"], program["org"],
        )["steps"]}
        assert "review" not in keys

    def test_it_appears_when_something_is_actually_waiting(self, joined, program):
        store = joined["store"]
        self._assign(joined)
        athlete = store.conn.execute(
            "SELECT user_id FROM team_members WHERE team_id = ? LIMIT 1",
            (joined["team"]["id"],),
        ).fetchone()["user_id"]

        # Held through the real submit path rather than an INSERT: a
        # hand-written row has to track eighteen NOT NULL columns and would
        # rot the next time the schema moves. A ball drill the tracker barely
        # saw is genuinely held rather than rejected.
        slot = store.start_session(athlete, "soc_juggle")
        reps = [
            {"t_ms": i * 900 + (i % 3) * 70, "hand": "left", "confidence": 0.4,
             "speed": 1.2, "part": "left_ankle"}
            for i in range(30)
        ]
        held = store.submit_session(
            athlete, slot["session_id"], slot["nonce"], duration_ms=28_000,
            reps=reps, mean_confidence=0.4, track_quality=0.06,
        )
        assert held["status"] == "review"

        result = O.staff_progress(store.conn, joined["coach"]["id"], program["org"])
        assert result["scope"]["review_waiting"] == 1
        assert "review" in {s["key"] for s in result["steps"]}

    def test_a_director_still_gets_the_setup_checklist(self, program):
        """Two different jobs: one builds a program, the other joins one."""
        result = O.progress(program["store"].conn, program["org"])
        assert "team" in {s["key"] for s in result["steps"]}
        assert result["required_total"] == 3
