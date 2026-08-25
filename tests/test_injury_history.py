"""Prior injury, and what it is allowed to change.

Prior injury is among the strongest predictors of the next one, so an athlete
who ramped back from an ankle in March should not start August on the same
thresholds as a teammate who never has. But "should start differently" points
in two very different directions, and only one of them belongs in a product
used on children.

What it does: pulls the *caution* line down on the tissues involved, so this
app asks a question sooner.

What it must never do: block training, reduce a budget, or become visible to
the people picking teams. That last one is the load-bearing rule here. A coach
can already see what an athlete is carrying today, because that changes
today's session; a career count of past injuries changes nothing about today's
session and would change quite a lot about a tryout. Making prior injury
visible to selectors is how a child learns that reporting pain costs them a
place, and every other guarantee in the wellness subsystem rests on that not
being true.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from athleteiq import injury_history, load as load_mod
from athleteiq.db import connect
from athleteiq.store import Store

TODAY = date(2026, 8, 25)


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "h.db"))


@pytest.fixture
def athlete(store):
    org = store.create_org("Northshore")
    store.create_user(org, "director", "Coach Ada")
    team = store.create_team(org, "U15 Boys")
    person = store.create_user(
        org, "athlete", "Jordan P.", birth_year=2011, dominant_hand="right"
    )
    store.join_team(team["join_code"], person["id"])
    return {"org": org, "team": team, "person": person}


def ramp(store, athlete, area, finished_on, setbacks=0):
    """A completed return-to-play plan, back-dated."""
    store.conn.execute(
        "INSERT INTO return_plans(athlete_id, area, stage, clearance, "
        "  started_on, stage_started_on, completed_on, setbacks, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (athlete["person"]["id"], area, "done", "none",
         (finished_on - timedelta(days=30)).isoformat(),
         finished_on.isoformat(), finished_on.isoformat(), setbacks,
         finished_on.isoformat()),
    )
    store.conn.commit()


class TestTheRecordCarriesForward:
    """The document asked for this to be confirmed rather than assumed."""

    def test_a_ramp_from_last_season_is_still_on_file(self, store, athlete):
        ramp(store, athlete, "ankle", date(2026, 3, 10))
        history = injury_history.for_athlete(store.conn, athlete["person"]["id"], TODAY)
        assert [i.area for i in history.injuries] == ["ankle"]

    def test_reported_discomfort_survives_a_season_too(self, store, athlete):
        """400 days of retention is longer than a year, so March is still
        readable the following August. Confirmed rather than assumed."""
        from athleteiq import wellness

        assert wellness.RETENTION_DAYS > 365

    def test_only_ramps_count_not_every_reported_niggle(self, store, athlete):
        """A ramp means an adult was involved and it was serious enough to
        need one. A child saying their leg ached once is not that."""
        store.report_discomfort(
            athlete["person"]["id"], "knee", "niggle", day=TODAY - timedelta(days=30))
        history = injury_history.for_athlete(store.conn, athlete["person"]["id"], TODAY)
        assert history.injuries == []


class TestInfluenceDecays:
    def test_a_recent_ramp_weighs_most(self, store, athlete):
        ramp(store, athlete, "ankle", TODAY - timedelta(days=30))
        history = injury_history.for_athlete(store.conn, athlete["person"]["id"], TODAY)
        assert history.injuries[0].band.key == "recent"
        assert history.tightening()["lower_body"] == 0.20

    def test_one_from_earlier_in_the_year_weighs_less(self, store, athlete):
        ramp(store, athlete, "ankle", TODAY - timedelta(days=200))
        history = injury_history.for_athlete(store.conn, athlete["person"]["id"], TODAY)
        assert history.tightening()["lower_body"] == 0.10

    def test_one_from_years_ago_weighs_nothing(self, store, athlete):
        """An ankle sprain two years ago is history, not a live risk factor.
        Treating it as one turns a childhood injury into a permanent mark."""
        ramp(store, athlete, "ankle", TODAY - timedelta(days=500))
        history = injury_history.for_athlete(store.conn, athlete["person"]["id"], TODAY)
        assert history.tightening() == {}
        assert history.note() == ""

    def test_repeats_do_not_stack(self, store, athlete):
        """Three ankle niggles in a year is not three times the risk of one,
        and a scheme that added them up would eventually tighten a child's
        thresholds until the app told them to stop moving."""
        for offset in (20, 50, 80):
            ramp(store, athlete, "ankle", TODAY - timedelta(days=offset))
        assert injury_history.for_athlete(
            store.conn, athlete["person"]["id"], TODAY
        ).tightening()["lower_body"] == 0.20

    def test_a_ramp_with_a_setback_weighs_more(self, store, athlete):
        """The body already said once that it was not ready. That is the
        clearest signal in here."""
        ramp(store, athlete, "ankle", TODAY - timedelta(days=30), setbacks=1)
        assert injury_history.for_athlete(
            store.conn, athlete["person"]["id"], TODAY
        ).tightening()["lower_body"] > 0.20

    def test_tightening_is_bounded_however_bad_the_history(self, store, athlete):
        for offset in (10, 20, 30, 40):
            ramp(store, athlete, "ankle", TODAY - timedelta(days=offset), setbacks=3)
        assert all(
            v <= 0.30
            for v in injury_history.for_athlete(
                store.conn, athlete["person"]["id"], TODAY).tightening().values()
        )


class TestItIsOnlyEverATissueSpecificCaution:
    def test_it_tightens_only_the_tissues_involved(self, store, athlete):
        """An ankle does not make throwing riskier."""
        ramp(store, athlete, "ankle", TODAY - timedelta(days=30))
        tightening = injury_history.for_athlete(
            store.conn, athlete["person"]["id"], TODAY).tightening()
        assert "lower_body" in tightening
        assert "throwing" not in tightening

    def test_a_shoulder_tightens_throwing(self, store, athlete):
        ramp(store, athlete, "shoulder", TODAY - timedelta(days=30))
        assert "throwing" in injury_history.for_athlete(
            store.conn, athlete["person"]["id"], TODAY).tightening()

    def test_the_caution_line_moves_but_the_stop_line_does_not(self):
        """Otherwise a child with a history is told to stop on a week their
        teammate is told is fine. The point is an earlier question, not an
        earlier prohibition."""
        days = [
            load_mod.DayLoad(day=TODAY - timedelta(days=i), load=10.0, sessions=1)
            for i in range(28)
        ]
        plain = load_mod.analyze(days, today=TODAY)
        tight = load_mod.analyze(days, today=TODAY, tightened={"lower_body": 0.20})
        assert plain.zone == tight.zone

    def test_a_history_adds_a_caution_a_clean_athlete_would_not_get(self):
        """The whole point, stated as the one week where the two differ."""
        days = [
            load_mod.DayLoad(day=TODAY - timedelta(days=i), load=8.0, sessions=1)
            for i in range(28)
        ]
        # A step up that stays inside the normal steady range: acwr 1.18,
        # comfortably under the 1.30 at which anybody gets a caution.
        for i in range(7):
            days[i] = load_mod.DayLoad(
                day=TODAY - timedelta(days=i), load=10.0, sessions=1)

        plain = load_mod.analyze(days, today=TODAY)
        tight = load_mod.analyze(days, today=TODAY, tightened={"lower_body": 0.20})

        assert plain.zone == load_mod.Zone.OPTIMAL
        assert "history_ramp" not in {a.code for a in plain.advisories}
        assert "history_ramp" in {a.code for a in tight.advisories}
        # And it is a caution, never a warning: an earlier question, not an
        # earlier prohibition.
        fired = next(a for a in tight.advisories if a.code == "history_ramp")
        assert fired.level == "caution"

    def test_a_week_that_is_fine_for_everyone_stays_fine(self):
        """The tightening must not fire on every week, or it becomes noise and
        then it stops being read at all."""
        days = [
            load_mod.DayLoad(day=TODAY - timedelta(days=i), load=8.0, sessions=1)
            for i in range(28)
        ]
        tight = load_mod.analyze(days, today=TODAY, tightened={"lower_body": 0.20})
        assert "history_ramp" not in {a.code for a in tight.advisories}

    def test_nothing_here_reduces_a_budget(self, store, athlete):
        """Prior injury moves when a question is asked. It does not quietly
        shrink what a child is allowed to do."""
        from athleteiq import benchmarks

        ramp(store, athlete, "ankle", TODAY - timedelta(days=30))
        report = benchmarks.report(store.conn, athlete["person"]["id"], TODAY)
        plain = benchmarks.scaled(benchmarks.band_for(15))
        assert report["budget"]["band"]["weekly_target"] == plain.weekly_target


class TestACoachDoesNotGetAnInjuryHistory:
    """The rule everything else rests on.

    A coach sees what an athlete is carrying *now*, because that changes
    today's session. A career count changes nothing about today's session and
    would change a tryout.
    """

    def test_the_athletes_own_load_state_carries_the_note(self, store, athlete):
        ramp(store, athlete, "ankle", TODAY - timedelta(days=30))
        state = store.load_state(athlete["person"]["id"])
        assert state.tightened or state.history_note

    def test_the_note_is_written_to_the_athlete_and_reassures(self, store, athlete):
        ramp(store, athlete, "ankle", TODAY - timedelta(days=30))
        note = injury_history.for_athlete(
            store.conn, athlete["person"]["id"], TODAY).note()
        assert "not stopping you" in note

    def test_the_history_itself_is_not_on_the_coach_roster(self, store, athlete):
        from athleteiq.leaderboard import coach_roster

        ramp(store, athlete, "ankle", TODAY - timedelta(days=30))
        payload = str(coach_roster(
            store.conn, athlete["org"], athlete["team"]["id"], "week"))
        for leak in ("ankle", "injuries", "prior", "days_ago"):
            assert leak not in payload, f"coach roster leaks injury history: {leak!r}"

    def test_no_count_of_past_injuries_reaches_a_coach_surface(self, store, athlete):
        from athleteiq import practice

        for offset in (30, 200, 400):
            ramp(store, athlete, "ankle", TODAY - timedelta(days=offset))
        card = str(practice.brief(
            store, athlete["org"], athlete["team"]["id"], today=TODAY).to_dict())
        for leak in ("injuries", "prior_injuries", "history"):
            assert leak not in card, f"the practice card leaks history: {leak!r}"


class TestHealthDataIsNotKeptForever:
    def test_completed_ramps_are_purged_past_the_horizon(self, store, athlete):
        """They were never purged at all, which contradicted what the wellness
        module says this product does with health data about a minor."""
        ramp(store, athlete, "knee", TODAY - timedelta(days=800))
        assert injury_history.purge_old_plans(store.conn, TODAY) >= 1
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM return_plans").fetchone()["n"] == 0

    def test_a_recent_one_is_kept(self, store, athlete):
        ramp(store, athlete, "ankle", TODAY - timedelta(days=300))
        injury_history.purge_old_plans(store.conn, TODAY)
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM return_plans").fetchone()["n"] == 1

    def test_an_open_ramp_is_never_purged(self, store, athlete):
        """An open plan is about a body that is still recovering."""
        store.conn.execute(
            "INSERT INTO return_plans(athlete_id, area, stage, clearance, "
            "  started_on, stage_started_on, created_at) VALUES (?,?,?,?,?,?,?)",
            (athlete["person"]["id"], "ankle", "stage_one", "none",
             "2020-01-01", "2020-01-01", "2020-01-01"),
        )
        store.conn.commit()
        injury_history.purge_old_plans(store.conn, TODAY)
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM return_plans").fetchone()["n"] == 1

    def test_the_events_go_with_the_plan(self, store, athlete):
        ramp(store, athlete, "knee", TODAY - timedelta(days=800))
        plan_id = store.conn.execute(
            "SELECT id FROM return_plans").fetchone()["id"]
        store.conn.execute(
            "INSERT INTO return_plan_events(plan_id, kind, detail, day, created_at) "
            "VALUES (?,?,?,?,?)",
            (plan_id, "advanced", "stage two", "2024-01-01", "2024-01-01"),
        )
        store.conn.commit()
        injury_history.purge_old_plans(store.conn, TODAY)
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM return_plan_events").fetchone()["n"] == 0

    def test_the_scheduled_purge_covers_plans_now(self, store, athlete):
        from athleteiq import notifications

        ramp(store, athlete, "knee", TODAY - timedelta(days=900))
        notifications.purge_old_wellness(store.conn, TODAY)
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM return_plans").fetchone()["n"] == 0
