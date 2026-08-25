"""The pre-practice card.

A coach standing on a field with a whistle in one hand and a phone in the
other has time for one card, read once. So most of what is tested here is
restraint: that the card stays short, that it says what to do rather than
what is wrong, and above all that it never produces the one instruction that
would be actively harmful -- chase an injured child for missed reps.

The composition is the other half. Every number on the card comes from the
same function the full coach screen uses. A briefing with its own idea of
"behind" would drift from the screen the coach opens next, and then neither
could be trusted.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from athleteiq import assignments as assignments_mod
from athleteiq import practice
from athleteiq import wellness as W
from athleteiq.db import connect
from athleteiq.store import Store

TODAY = date.today()


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "p.db"))


@pytest.fixture
def squad(store):
    org = store.create_org("Northshore")
    director = store.create_user(org, "director", "Coach Ada")
    team = store.create_team(org, "U15 Boys")
    athletes = []
    for i in range(8):
        person = store.create_user(
            org, "athlete", f"Kid {i}", birth_year=TODAY.year - 14,
            dominant_hand="right",
        )
        store.join_team(team["join_code"], person["id"])
        athletes.append(person)
    return {"org": org, "director": director, "team": team, "athletes": athletes}


def brief(store, squad):
    return practice.brief(store, squad["org"], squad["team"]["id"])


class TestAQuietDaySaysSo:
    def test_nothing_to_flag_is_stated_not_left_blank(self, store, squad):
        """An empty card reads as a loading bug. "Nothing to flag" is
        information a coach can act on -- run the session you planned."""
        card = brief(store, squad)
        assert card.quiet is True
        assert "Nothing to flag" in card.headline()

    def test_the_roster_size_is_still_reported(self, store, squad):
        assert brief(store, squad).roster == 8


class TestWhatTheCardTellsACoachToDo:
    def test_somebody_who_should_not_train_is_first(self, store, squad):
        store.report_discomfort(squad["athletes"][3]["id"], "knee", W.Severity.HURTS)
        store.report_discomfort(squad["athletes"][1]["id"], "ankle", W.Severity.NIGGLE)
        card = brief(store, squad)
        assert card.people[0].kind == practice.Kind.HOLD
        assert card.people[0].display_name == "Kid 3"

    def test_a_line_says_what_to_do_not_what_is_wrong(self, store, squad):
        store.report_discomfort(squad["athletes"][0]["id"], "shoulder", W.Severity.SORE)
        item = brief(store, squad).people[0]
        assert item.kind == practice.Kind.MODIFY
        assert item.line == "Modified work"
        # Not a severity word, not a diagnosis -- a thing to do at practice.
        assert "Keep them off" in item.detail

    def test_the_athletes_own_note_never_reaches_the_card(self, store, squad):
        """A coach who can read a child's free-text note is a coach reading a
        child's diary. The area changes a drill; the note does not."""
        store.report_discomfort(
            squad["athletes"][0]["id"], "knee", W.Severity.SORE,
            note="it started when my stepdad made me run to school",
        )
        card = brief(store, squad).to_dict()
        assert "stepdad" not in str(card)

    def test_nobody_is_named_twice(self, store, squad):
        for athlete in squad["athletes"][:3]:
            store.report_discomfort(athlete["id"], "knee", W.Severity.SORE)
        card = brief(store, squad)
        names = [p.display_name for p in card.people]
        assert len(names) == len(set(names))


class TestTheCardStaysShort:
    def test_it_stops_naming_people_and_starts_counting(self, store, squad):
        """A card that lists everybody is a card nobody reads, and a card
        nobody reads is worse than none -- it looks like diligence."""
        for athlete in squad["athletes"]:
            store.report_discomfort(athlete["id"], "knee", W.Severity.SORE)
        card = brief(store, squad)
        assert len(card.people) == practice.MAX_PEOPLE
        assert card.hidden == 8 - practice.MAX_PEOPLE

    def test_the_hidden_ones_are_still_counted_in_the_headline(self, store, squad):
        for athlete in squad["athletes"]:
            store.report_discomfort(athlete["id"], "knee", W.Severity.SORE)
        assert "8 on modified work" in brief(store, squad).headline()

    def test_the_ones_shown_are_the_ones_that_matter_most(self, store, squad):
        """If something has to be cut, it is never the child who should not
        be training."""
        for athlete in squad["athletes"][:7]:
            store.report_discomfort(athlete["id"], "ankle", W.Severity.NIGGLE)
        store.report_discomfort(squad["athletes"][7]["id"], "knee", W.Severity.HURTS)
        card = brief(store, squad)
        assert card.people[0].display_name == "Kid 7"
        assert card.people[0].kind == practice.Kind.HOLD


class TestAnInjuredChildIsNeverChasedForReps:
    """The one output this card must not produce.

    A naive join of "who is behind on their assignment" with "who is on the
    roster" tells a coach to go and push the child who is hurt. That is not a
    cosmetic problem -- it is the exact wrong instruction, delivered at the
    exact moment the coach is deciding what to make them do.
    """

    def _assign(self, store, squad):
        return assignments_mod.create(
            store.conn,
            org_id=squad["org"],
            team_id=squad["team"]["id"],
            drill_key="lax_wall_ball",
            title="Wall ball",
            target_reps=200,
            created_by=squad["director"]["id"],
            starts_on=(TODAY - timedelta(days=5)).isoformat(),
            due_on=(TODAY + timedelta(days=2)).isoformat(),
        )

    def test_they_are_left_off_the_behind_list(self, store, squad):
        self._assign(store, squad)
        hurt = squad["athletes"][0]
        store.report_discomfort(hurt["id"], "shoulder", W.Severity.HURTS)
        coverage = brief(store, squad).coverage[0]
        assert hurt["display_name"] not in coverage.behind

    def test_and_out_of_the_denominator_too(self, store, squad):
        """Otherwise the squad looks permanently behind, and a coach learns to
        ignore the number."""
        self._assign(store, squad)
        for athlete in squad["athletes"][:2]:
            store.report_discomfort(athlete["id"], "knee", W.Severity.HURTS)
        assert brief(store, squad).coverage[0].total == 6

    def test_but_a_healthy_athlete_who_is_behind_still_shows(self, store, squad):
        self._assign(store, squad)
        coverage = brief(store, squad).coverage[0]
        assert coverage.behind_total == 8
        assert coverage.done == 0

    def test_the_behind_list_is_a_reminder_not_a_roll_call(self, store, squad):
        """Three names is a nudge. Eight is a list of children in trouble,
        handed to an adult, before a session. The count is still there."""
        self._assign(store, squad)
        coverage = brief(store, squad).coverage[0]
        assert len(coverage.behind) == practice.MAX_BEHIND_NAMES
        assert coverage.behind_total == 8


class TestReturnToPlayOutranksEverything:
    def test_a_ramp_is_shown_as_modified_work_with_its_stage(self, store, squad):
        athlete = squad["athletes"][0]
        report = store.report_discomfort(athlete["id"], "ankle", W.Severity.HURTS)
        store.resolve_discomfort(athlete["id"], report["id"])
        item = brief(store, squad).people[0]
        assert item.athlete_id == athlete["id"]
        assert item.kind in (practice.Kind.HOLD, practice.Kind.MODIFY)

    def test_a_ramp_awaiting_clearance_is_a_hold(self, store, squad):
        """A head knock waits for a named human, and the card must not soften
        that into "modified work"."""
        athlete = squad["athletes"][0]
        report = store.report_discomfort(athlete["id"], "head", W.Severity.HURTS)
        store.resolve_discomfort(athlete["id"], report["id"])
        item = brief(store, squad).people[0]
        assert item.kind == practice.Kind.HOLD
        assert "clearance" in item.line.lower()

    def test_somebody_mid_ramp_is_also_excused_from_the_work_list(
        self, store, squad
    ):
        athlete = squad["athletes"][0]
        report = store.report_discomfort(athlete["id"], "ankle", W.Severity.HURTS)
        store.resolve_discomfort(athlete["id"], report["id"])
        assignments_mod.create(
            store.conn, org_id=squad["org"], team_id=squad["team"]["id"],
            drill_key="lax_wall_ball", title="Wall ball", target_reps=200,
            created_by=squad["director"]["id"],
            starts_on=(TODAY - timedelta(days=5)).isoformat(),
            due_on=(TODAY + timedelta(days=2)).isoformat(),
        )
        assert brief(store, squad).coverage[0].total == 7


class TestTheHeadlineCountsEverybody:
    """It reads from the full set, not the six the card had room for.

    Counting only the visible ones understated who needed modified work, and
    it understated it in the direction of a coach training a hurt child --
    the two it could not fit were reported as merely worth an eye.
    """

    def test_people_the_card_could_not_fit_are_still_counted(self, store, squad):
        for athlete in squad["athletes"]:
            store.report_discomfort(athlete["id"], "knee", W.Severity.SORE)
        card = brief(store, squad)
        assert card.hidden == 2
        assert card.counts[practice.Kind.MODIFY] == 8
        assert "8 on modified work" in card.headline()

    def test_and_nobody_is_recategorised_by_being_cut(self, store, squad):
        for athlete in squad["athletes"]:
            store.report_discomfort(athlete["id"], "knee", W.Severity.SORE)
        assert practice.Kind.WATCH not in brief(store, squad).counts


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
        "/api/orgs", json={"name": "Northshore LC", "director_name": "Dir Smith"}
    ).json()
    director = {"Authorization": f"Bearer {org['director']['token']}"}
    team = client.post(
        "/api/teams", json={"name": "U15 Boys", "season": "2026"}, headers=director
    ).json()
    athlete = client.post(
        "/api/athletes",
        json={"display_name": "Jordan P.", "birth_year": TODAY.year - 14,
              "dominant_hand": "right", "guardian_consent": True,
              "join_code": team["join_code"]},
        headers=director,
    ).json()
    return {"director": director, "team": team, "athlete": athlete}


class TestOverTheWire:
    def test_a_coach_gets_the_card(self, client, wired):
        res = client.get(
            f"/api/coach/practice?team_id={wired['team']['id']}",
            headers=wired["director"],
        )
        assert res.status_code == 200
        assert res.json()["quiet"] is True

    def test_an_athlete_cannot_read_their_squads_card(self, client, wired):
        """It names teammates and what each of them is carrying."""
        headers = {"Authorization": f"Bearer {wired['athlete']['token']}"}
        assert client.get("/api/coach/practice", headers=headers).status_code == 403

    def test_another_program_gets_nothing(self, client, wired):
        other = client.post(
            "/api/orgs", json={"name": "Southside", "director_name": "Other"}
        ).json()
        headers = {"Authorization": f"Bearer {other['director']['token']}"}
        res = client.get(
            f"/api/coach/practice?team_id={wired['team']['id']}", headers=headers
        )
        assert res.status_code == 200
        # Not their team, so not their roster -- no names leak across programs.
        assert res.json()["roster"] == 0
        assert res.json()["people"] == []
