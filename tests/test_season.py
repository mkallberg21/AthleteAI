"""Season phases, and what they do to a training budget.

The age bands know how old a child is. They do not know whether it is
February, and that changes the answer more than a birthday does.

Two things are being defended here.

The direction. In-season the self-directed budget goes *down*. These figures
have only ever counted work on top of team practice, and a child in-season
already has three practices and a game in their week; holding the same solo
target on top of that is not ambition. Every training app's instinct is to
scale the other way, so the test says so explicitly.

The break. Post-season is the lowest phase, and the wording changes with the
number: an app that scales a budget down and then nudges a child to fill it
anyway has given away the entire point of having a break. A blank week in
November is the plan working.
"""
from __future__ import annotations

from datetime import date

import pytest

from offdays import benchmarks, season
from offdays.db import connect
from offdays.store import Store

TODAY = date.today()


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "s.db"))


@pytest.fixture
def athlete(store):
    org = store.create_org("Northshore")
    person = store.create_user(
        org, "athlete", "Jordan P.", birth_year=TODAY.year - 14,
        dominant_hand="right",
    )
    return {"org": org, "person": person}


def budget(store, athlete, phase):
    store.conn.execute(
        "UPDATE organizations SET season_phase = ? WHERE id = ?",
        (phase, athlete["org"]),
    )
    store.conn.commit()
    return benchmarks.report(store.conn, athlete["person"]["id"])["budget"]


class TestTheDirectionIsDeliberate:
    def test_in_season_is_lower_than_preseason(self, store, athlete):
        """The counterintuitive one. Practices already fill the week, and
        none of that load is counted in this number."""
        assert (budget(store, athlete, "in_season")["band"]["weekly_target"]
                < budget(store, athlete, "preseason")["band"]["weekly_target"])

    def test_the_offseason_is_the_highest(self, store, athlete):
        """Nothing on the team calendar, so a child's own work has room."""
        targets = {
            phase: budget(store, athlete, phase)["band"]["weekly_target"]
            for phase in season.BY_KEY
        }
        assert max(targets, key=targets.get) == "offseason"

    def test_the_break_is_the_lowest(self, store, athlete):
        targets = {
            phase: budget(store, athlete, phase)["band"]["weekly_target"]
            for phase in season.BY_KEY
        }
        assert min(targets, key=targets.get) == "postseason"

    def test_preseason_leaves_the_published_budget_alone(self, store, athlete):
        """The neutral phase, and the default -- so nothing changes for
        anybody until a director actually makes a decision."""
        assert season.DEFAULT.scale == 1.0
        plain = benchmarks.scaled(benchmarks.band_for(14))
        assert budget(store, athlete, "preseason")["band"]["weekly_target"] == \
            plain.weekly_target


class TestTheBreakIsNotALapse:
    def test_a_blank_week_is_not_a_nudge(self, store, athlete):
        card = budget(store, athlete, "postseason")
        assert card["headline"] == "Enjoy the break"
        assert card["status"] == benchmarks.Status.FULL

    def test_the_same_blank_week_in_preseason_still_nudges(self, store, athlete):
        """The break branch has to be the exception, not a softening of the
        whole feature -- an athlete who has stopped in March should hear so."""
        assert budget(store, athlete, "preseason")["status"] == \
            benchmarks.Status.UNKNOWN

    def test_nothing_in_the_break_copy_asks_for_more_work(self, store, athlete):
        card = budget(store, athlete, "postseason")
        text = f"{card['headline']} {card['detail']}".lower()
        for nudge in ("more session", "gets you to", "would round the week out",
                      "catch up"):
            assert nudge not in text, f"break copy is nudging: {nudge!r}"

    def test_a_light_week_during_the_break_is_called_plenty(self, store, athlete):
        """Under target during the break. Under target *is* the target."""
        from offdays.benchmarks import WeekOfTraining, assess_time, band_for

        band = band_for(14)
        week = WeekOfTraining(minutes=10.0, days=1, sessions=1)
        card = assess_time(band, week, "Jordan", season.BY_KEY["postseason"])
        assert card.status == benchmarks.Status.GOOD
        assert "nothing to catch up on" in card.detail

    def test_but_it_still_says_stop_if_they_are_hammering_it(self, store, athlete):
        """The break lowers the ceiling; it does not remove it. A child
        training through their rest period is exactly who this should reach."""
        from offdays.benchmarks import WeekOfTraining, assess_time, _rescaled, band_for

        band = _rescaled(band_for(14), season.BY_KEY["postseason"].scale)
        card = assess_time(
            band, WeekOfTraining(minutes=300.0, days=6, sessions=8), "Jordan",
            season.BY_KEY["postseason"],
        )
        assert card.status == benchmarks.Status.OVER


class TestThePhaseIsCarriedNotHidden:
    def test_the_athlete_can_see_why_the_number_moved(self, store, athlete):
        """Otherwise a budget that halves between October and November looks
        like the app moving the goalposts."""
        card = budget(store, athlete, "in_season")
        assert card["phase"]["label"] == "In-season"
        assert "already happening at practice" in card["phase"]["athlete_note"]

    def test_an_unknown_stored_phase_falls_back_rather_than_breaking(
        self, store, athlete
    ):
        card = budget(store, athlete, "winter_arc")
        assert card["phase"]["key"] == season.DEFAULT.key


class TestTheCoachSeesTheSameNumbers:
    def test_the_squad_rollup_uses_the_programs_phase(self, store, athlete):
        """A coach counting "over budget" against an unscaled band would
        disagree with the number the child was shown."""
        summary = benchmarks.program_summary(
            store.conn, [athlete["person"]["id"]],
            phase=season.BY_KEY["in_season"],
        )
        assert summary["phase"]["key"] == "in_season"

    def test_a_squad_can_go_over_in_season_on_a_week_that_was_fine_before(
        self, store, athlete
    ):
        """The whole point: the same week means something different in March.
        This is the load the season phase is there to catch."""
        from offdays.benchmarks import WeekOfTraining, assess_time, _rescaled, band_for

        week = WeekOfTraining(minutes=100.0, days=5, sessions=6)
        pre = assess_time(band_for(14), week, phase=season.BY_KEY["preseason"])
        during = assess_time(
            _rescaled(band_for(14), season.BY_KEY["in_season"].scale), week,
            phase=season.BY_KEY["in_season"],
        )
        assert pre.status != benchmarks.Status.OVER
        assert during.status == benchmarks.Status.OVER


# ---------------------------------------------------------------------------
# Over the wire
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFDAYS_DB", str(tmp_path / "api.db"))
    from offdays import api

    api.app.dependency_overrides.clear()
    return TestClient(api.app)


@pytest.fixture
def program(client):
    org = client.post(
        "/api/orgs", json={"name": "Northshore LC", "director_name": "Dir Smith"}
    ).json()
    return {"director": {"Authorization": f"Bearer {org['director']['token']}"},
            "org": org}


class TestOverTheWire:
    def test_a_director_can_set_it(self, client, program):
        res = client.put("/api/org/season", json={"phase": "in_season"},
                         headers=program["director"])
        assert res.status_code == 200
        assert client.get("/api/org/season", headers=program["director"]) \
            .json()["phase"]["key"] == "in_season"

    def test_the_default_is_the_neutral_one(self, client, program):
        assert client.get("/api/org/season", headers=program["director"]) \
            .json()["phase"]["key"] == "preseason"

    def test_a_nonsense_phase_is_refused(self, client, program):
        assert client.put("/api/org/season", json={"phase": "winter_arc"},
                          headers=program["director"]).status_code == 400

    def test_an_assistant_coach_cannot_change_it(self, client, program):
        """It silently changes what every child in the program is told to do,
        so it wants a person's name on it."""
        from offdays import api as api_mod

        store = api_mod.get_store()
        org_id = store.authenticate(
            program["director"]["Authorization"].split()[1]
        ).org_id
        coach = store.create_user(org_id, "coach", "Asst Coach")
        headers = {"Authorization": f"Bearer {coach['token']}"}
        res = client.put("/api/org/season", json={"phase": "offseason"},
                         headers=headers)
        assert res.status_code == 403
        # And it really did not take effect.
        assert client.get("/api/org/season", headers=headers) \
            .json()["phase"]["key"] == "preseason"
