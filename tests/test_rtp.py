"""Return to training after an injury.

The most important assertions here are about what the app refuses to do. It
never clears anyone, an athlete cannot clear themselves, and a head or neck
return cannot start on a coach's say-so.
"""

from datetime import date, timedelta

import pytest

from offdays import rtp as R
from offdays import wellness as W
from offdays.db import connect
from offdays.drills.base import Tissue
from offdays.store import Store, StoreError

TODAY = date.today()


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "t.db"))


@pytest.fixture
def program(store):
    org = store.create_org("Northshore")
    return {"org": org, "team": store.create_team(org, "U13")}


@pytest.fixture
def athlete(store, program):
    person = store.create_user(
        program["org"], "athlete", "Jordan P.", birth_year=TODAY.year - 13,
        dominant_hand="right",
    )
    store.join_team(program["team"]["join_code"], person["id"])
    return person


@pytest.fixture
def coach(store, program):
    return store.create_user(program["org"], "coach", "A Coach")


def hurt_and_close(store, athlete_id, area="knee", severity="niggle",
                   flags=("giving_way",), day=None):
    """Report something serious, then say it is better -- which opens a ramp."""
    day = day or TODAY
    saved = store.report_discomfort(
        athlete_id, area, severity, flags=list(flags), day=day,
    )
    return store.resolve_discomfort(athlete_id, saved["id"], day=day)


class TestTheAppNeverClearsAnyone:

    def test_a_serious_report_opens_a_ramp_rather_than_just_ending(self, store, athlete):
        plan = hurt_and_close(store, athlete["id"])["plan"]
        assert plan["stage"] == "rest"
        assert plan["awaiting_clearance"] is True
        assert plan["can_advance"] is False

    def test_nothing_advances_while_it_waits_on_a_human(self, store, athlete):
        plan = hurt_and_close(store, athlete["id"])["plan"]
        store.check_in(athlete["id"], "fine")
        with pytest.raises(StoreError, match="Waiting on"):
            store.advance_return_plan(athlete["id"], plan["id"])

    def test_the_clearance_is_recorded_with_a_name_and_a_date(self, store, athlete, coach):
        plan = hurt_and_close(store, athlete["id"])["plan"]
        after = store.clear_return_plan(plan["id"], coach["id"], "A Coach")
        assert after["cleared_by_name"] == "A Coach"
        assert after["cleared_on"] == TODAY.isoformat()
        assert after["stage"] == "light", "clearing starts the ramp, it does not finish it"

    def test_a_head_return_will_not_start_without_a_named_clinician(self, store, athlete):
        plan = hurt_and_close(store, athlete["id"], area="head", severity="niggle",
                              flags=())["plan"]
        assert plan["clearance"] == R.Clearance.CLINICIAN
        with pytest.raises(StoreError, match="doctor or physio"):
            store.clear_return_plan(plan["id"], 1, "A Parent", clinician_name="  ")

        after = store.clear_return_plan(
            plan["id"], 1, "A Parent", clinician_name="Dr Okafor",
        )
        assert after["clinician_name"] == "Dr Okafor"

    def test_a_stiff_thigh_needs_no_ramp_at_all(self, store, athlete):
        """Not everything that aches is an injury to come back from."""
        assert hurt_and_close(
            store, athlete["id"], area="thigh", severity="sore", flags=(),
        )["plan"] is None

    def test_clearing_twice_is_refused(self, store, athlete, coach):
        plan = hurt_and_close(store, athlete["id"])["plan"]
        store.clear_return_plan(plan["id"], coach["id"], "A Coach")
        with pytest.raises(StoreError, match="already been cleared"):
            store.clear_return_plan(plan["id"], coach["id"], "A Coach")


class TestTheRampItself:

    def _cleared(self, store, athlete, coach, day=None):
        day = day or TODAY - timedelta(days=10)
        plan = hurt_and_close(store, athlete["id"], day=day)["plan"]
        return store.clear_return_plan(plan["id"], coach["id"], "A Coach", day=day)

    def test_time_at_a_stage_is_a_floor(self, store, athlete, coach):
        plan = self._cleared(store, athlete, coach, day=TODAY)
        store.check_in(athlete["id"], "fine")
        with pytest.raises(StoreError, match="more day"):
            store.advance_return_plan(athlete["id"], plan["id"])

    def test_feeling_fine_today_is_required_too(self, store, athlete, coach):
        """Time served is not the test. Saying how you feel is."""
        plan = self._cleared(store, athlete, coach)
        with pytest.raises(StoreError, match="how you feel today"):
            store.advance_return_plan(athlete["id"], plan["id"])

    def test_a_full_ramp_walks_all_the_way_back(self, store, athlete, coach):
        start = TODAY - timedelta(days=20)
        plan = self._cleared(store, athlete, coach, day=start)
        day, seen = start, [plan["stage"]]
        for _ in range(10):
            day += timedelta(days=1)
            store.check_in(athlete["id"], "fine", day=day)
            gate = R.can_advance(store._load_plan(plan["id"]), day)
            if gate["ok"]:
                plan = store.advance_return_plan(athlete["id"], plan["id"], day=day)
                seen.append(plan["stage"])
            if plan["completed_on"]:
                break
        assert seen == ["light", "drills", "full_solo", "released"]
        assert plan["completed_on"]

    def test_the_last_stage_hands_the_decision_back_to_people(self, store):
        assert "coach's call" in R.LAST_STAGE.what
        assert "not this app's" in R.LAST_STAGE.what

    def test_an_athlete_cannot_advance_someone_elses_plan(self, store, program, athlete, coach):
        other = store.create_user(program["org"], "athlete", "Someone Else")
        plan = self._cleared(store, athlete, coach)
        store.check_in(other["id"], "fine")
        with pytest.raises(StoreError, match="no return plan"):
            store.advance_return_plan(other["id"], plan["id"])


class TestSetbacksAreSurvivable:
    """If speaking up costs a week, a thirteen-year-old who wants to play on
    Saturday stops speaking up, and the ramp becomes a formality they walk
    through while hurt."""

    def _ramped_to(self, store, athlete, coach, stage="drills"):
        start = TODAY - timedelta(days=20)
        plan = hurt_and_close(store, athlete["id"], day=start)["plan"]
        plan = store.clear_return_plan(plan["id"], coach["id"], "A Coach", day=start)
        day = start
        while plan["stage"] != stage:
            day += timedelta(days=1)
            store.check_in(athlete["id"], "fine", day=day)
            if R.can_advance(store._load_plan(plan["id"]), day)["ok"]:
                plan = store.advance_return_plan(athlete["id"], plan["id"], day=day)
        return plan, day

    def test_it_drops_one_stage_and_not_to_the_start(self, store, athlete, coach):
        plan, day = self._ramped_to(store, athlete, coach, "full_solo")
        store.report_discomfort(athlete["id"], "knee", "sore", day=day)
        after = store.return_plan(plan["id"], day)
        assert after["stage"] == "drills"
        assert after["stage"] != "rest"
        assert after["setbacks"] == 1

    def test_the_message_says_it_is_not_a_punishment(self, store, athlete, coach):
        plan, day = self._ramped_to(store, athlete, coach)
        store.report_discomfort(athlete["id"], "knee", "sore", day=day)
        loaded = store._load_plan(plan["id"])
        message = R.setback_message(loaded, "Knee").lower()
        assert "not a punishment" in message
        assert "right call every time" in message

    def test_a_second_setback_sends_it_back_to_an_adult(self, store, athlete, coach):
        plan, day = self._ramped_to(store, athlete, coach, "full_solo")
        store.report_discomfort(athlete["id"], "knee", "sore", day=day)
        store.resolve_discomfort(
            athlete["id"],
            store.wellness_status(athlete["id"], day).reports[0].id, day=day,
        )
        store.report_discomfort(athlete["id"], "knee", "sore", day=day)
        after = store.return_plan(plan["id"], day)
        assert after["setbacks"] == 2
        assert after["awaiting_clearance"] is True, "an adult looks again"

    def test_a_different_area_does_not_disturb_the_ramp(self, store, athlete, coach):
        plan, day = self._ramped_to(store, athlete, coach)
        store.report_discomfort(athlete["id"], "shoulder", "sore", day=day)
        assert store.return_plan(plan["id"], day)["setbacks"] == 0

    def test_reporting_during_a_ramp_still_protects_the_streak(self, store, athlete, coach):
        plan, day = self._ramped_to(store, athlete, coach)
        store.report_discomfort(athlete["id"], "knee", "sore", day=day)
        assert day in store._streak_days(athlete["id"])


class TestWhatTheRampHoldsBack:

    def test_nothing_is_offered_before_clearance(self, store, athlete):
        hurt_and_close(store, athlete["id"])
        status = store.wellness_status(athlete["id"])
        assert status.blocked_tissues == set(Tissue)

    def test_the_first_stage_leaves_the_injured_area_alone(self, store, athlete, coach):
        plan = hurt_and_close(store, athlete["id"])["plan"]
        store.clear_return_plan(plan["id"], coach["id"], "A Coach")
        status = store.wellness_status(athlete["id"])
        legs = W.drill_availability(status, "gen_squat", Tissue.LOWER_BODY)
        hands = W.drill_availability(status, "lax_wall_ball", Tissue.THROWING)
        assert legs["available"] is False
        assert hands["available"] is True

    def test_being_held_by_a_ramp_reads_differently_from_being_in_pain(
        self, store, athlete, coach,
    ):
        """'Resting your knee' confuses a kid whose knee stopped hurting last
        week. The reason has to say which thing is happening."""
        plan = hurt_and_close(store, athlete["id"])["plan"]
        store.clear_return_plan(plan["id"], coach["id"], "A Coach")
        reason = W.drill_availability(
            store.wellness_status(athlete["id"]), "gen_squat", Tissue.LOWER_BODY
        )["reason"]
        assert "ramp" in reason and "Resting" not in reason

    def test_a_finished_ramp_holds_nothing(self, store, athlete, coach):
        start = TODAY - timedelta(days=20)
        plan = hurt_and_close(store, athlete["id"], day=start)["plan"]
        plan = store.clear_return_plan(plan["id"], coach["id"], "A Coach", day=start)
        day = start
        while not plan["completed_on"]:
            day += timedelta(days=1)
            store.check_in(athlete["id"], "fine", day=day)
            if R.can_advance(store._load_plan(plan["id"]), day)["ok"]:
                plan = store.advance_return_plan(athlete["id"], plan["id"], day=day)
        assert store.wellness_status(athlete["id"], day).blocked_tissues == set()

    def test_a_forgotten_ramp_stops_holding_things_eventually(self, store, athlete, coach):
        old = TODAY - timedelta(days=R.STALE_AFTER_DAYS + 5)
        plan = hurt_and_close(store, athlete["id"], day=old)["plan"]
        store.clear_return_plan(plan["id"], coach["id"], "A Coach", day=old)
        assert store.active_return_plans(athlete["id"], TODAY) == []


class TestEveryRefusalExplainsItself:
    """A greyed out button with no reason is how a kid decides the app is
    broken and goes back to training on their own."""

    def test_every_blocker_is_a_sentence(self, store, athlete, coach):
        plan = hurt_and_close(store, athlete["id"])["plan"]
        assert plan["blocker"].endswith(".") and len(plan["blocker"]) > 20

        cleared = store.clear_return_plan(plan["id"], coach["id"], "A Coach")
        assert cleared["blocker"].endswith(".")

    def test_the_history_records_who_decided_what(self, store, athlete, coach):
        plan = hurt_and_close(store, athlete["id"])["plan"]
        store.clear_return_plan(plan["id"], coach["id"], "A Coach")
        kinds = [e["kind"] for e in store.plan_history(plan["id"])]
        assert kinds == ["opened", "cleared"]
        assert "A Coach" in store.plan_history(plan["id"])[1]["detail"]
