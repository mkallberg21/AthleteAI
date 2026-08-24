"""Multi-program membership and team-scoped coach access.

Before this, any coach in a program could read every athlete in it. At a club
with four hundred children that is not a product gap, it is a safeguarding one:
access should follow responsibility.

Most of these tests check that a scoped coach *cannot* reach something. That is
the point -- a scoping bug is silent, and the way anyone finds out is the wrong
adult reading a child's training history.
"""
from __future__ import annotations

import pytest

from athleteiq.config import CONFIG, Config
from athleteiq.db import connect
from athleteiq.store import Store, StoreError


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "a.db"))


@pytest.fixture
def club(store):
    """One program, two teams, a director and a coach on each team."""
    org = store.create_org("Northshore LC")
    director = store.create_user(org, "director", "Director Smith")
    varsity = store.create_team(org, "Varsity")
    jv = store.create_team(org, "JV")

    varsity_coach = store.create_user(org, "coach", "Coach Varsity")
    jv_coach = store.create_user(org, "coach", "Coach JV")
    store.assign_staff_to_team(varsity_coach["id"], varsity["id"])
    store.assign_staff_to_team(jv_coach["id"], jv["id"])

    athletes = {}
    for team, name in ((varsity, "Varsity Kid"), (jv, "JV Kid")):
        athlete = store.create_user(org, "athlete", name, dominant_hand="right")
        store.join_team(team["join_code"], athlete["id"])
        athletes[name] = athlete

    return {
        "org": org, "director": director, "varsity": varsity, "jv": jv,
        "varsity_coach": varsity_coach, "jv_coach": jv_coach, "athletes": athletes,
    }


class TestMemberships:
    def test_creating_a_user_records_a_membership(self, store, club):
        row = store.conn.execute(
            "SELECT role FROM memberships WHERE user_id = ? AND org_id = ?",
            (club["director"]["id"], club["org"]),
        ).fetchone()
        assert row["role"] == "director"

    def test_one_person_can_hold_roles_in_two_programs(self, store, club):
        """A school coach who also runs a club side is one human with two jobs."""
        other_org = store.create_org("Rival LC")
        store.add_membership(club["varsity_coach"]["id"], other_org, "coach")

        principal = store.authenticate(club["varsity_coach"]["token"])
        assert len(principal.memberships) == 2

    def test_the_active_program_can_be_chosen(self, store, club):
        other_org = store.create_org("Rival LC")
        store.add_membership(club["varsity_coach"]["id"], other_org, "director")

        home = store.authenticate(club["varsity_coach"]["token"])
        assert home.org_id == club["org"]
        away = store.authenticate(club["varsity_coach"]["token"], org_id=other_org)
        assert away.org_id == other_org
        assert away.role == "director"

    def test_a_program_they_do_not_belong_to_is_refused(self, store, club):
        stranger = store.create_org("Somewhere Else")
        with pytest.raises(StoreError, match="access to that program"):
            store.authenticate(club["varsity_coach"]["token"], org_id=stranger)

    def test_the_role_is_per_program(self, store, club):
        """The same person can be a director in one club and a coach in another."""
        other_org = store.create_org("Rival LC")
        store.add_membership(club["varsity_coach"]["id"], other_org, "director")
        assert store.authenticate(club["varsity_coach"]["token"]).role == "coach"
        assert store.authenticate(
            club["varsity_coach"]["token"], org_id=other_org
        ).role == "director"


class TestTeamScope:
    def test_a_director_sees_the_whole_program(self, store, club):
        principal = store.authenticate(club["director"]["token"])
        assert principal.team_ids is None
        assert principal.can_see_team(club["varsity"]["id"])
        assert principal.can_see_team(club["jv"]["id"])

    def test_a_coach_sees_only_their_assigned_team(self, store, club):
        principal = store.authenticate(club["varsity_coach"]["token"])
        assert principal.team_ids == [club["varsity"]["id"]]
        assert principal.can_see_team(club["varsity"]["id"])
        assert not principal.can_see_team(club["jv"]["id"])

    def test_a_coach_cannot_reach_an_athlete_on_another_team(self, store, club):
        """The check that matters: guessing an id must not work either."""
        principal = store.authenticate(club["varsity_coach"]["token"])
        assert store.staff_can_see_athlete(
            principal, club["athletes"]["Varsity Kid"]["id"]
        )
        assert not store.staff_can_see_athlete(
            principal, club["athletes"]["JV Kid"]["id"]
        )

    def test_a_director_can_reach_any_athlete_in_their_program(self, store, club):
        principal = store.authenticate(club["director"]["token"])
        for athlete in club["athletes"].values():
            assert store.staff_can_see_athlete(principal, athlete["id"])

    def test_a_director_cannot_reach_another_programs_athlete(self, store, club):
        other_org = store.create_org("Rival LC")
        outsider = store.create_user(other_org, "athlete", "Their Kid")
        principal = store.authenticate(club["director"]["token"])
        assert not store.staff_can_see_athlete(principal, outsider["id"])

    def test_assignments_can_be_added_and_removed(self, store, club):
        coach = club["varsity_coach"]["id"]
        store.assign_staff_to_team(coach, club["jv"]["id"])
        principal = store.authenticate(club["varsity_coach"]["token"])
        assert set(principal.team_ids) == {club["varsity"]["id"], club["jv"]["id"]}

        store.unassign_staff_from_team(coach, club["jv"]["id"])
        principal = store.authenticate(club["varsity_coach"]["token"])
        assert principal.team_ids == [club["varsity"]["id"]]

    def test_an_unassigned_coach_falls_back_to_the_whole_program(self, store, club):
        """Deliberate: accounts predating team assignment must keep working."""
        loose = store.create_user(club["org"], "coach", "Coach Nobody")
        principal = store.authenticate(loose["token"])
        assert principal.team_ids is None

    def test_strict_scope_gives_an_unassigned_coach_nothing(self, store, club, monkeypatch):
        """What a new deployment should turn on."""
        import athleteiq.store as store_mod

        monkeypatch.setattr(
            store_mod, "CONFIG",
            Config(strict_team_scope=True),
        )
        loose = store.create_user(club["org"], "coach", "Coach Nobody")
        principal = store.authenticate(loose["token"])
        assert principal.team_ids == []
        assert not principal.can_see_team(club["varsity"]["id"])
        assert not store.staff_can_see_athlete(
            principal, club["athletes"]["Varsity Kid"]["id"]
        )

    def test_an_empty_scope_filters_to_nothing_not_everything(self, store, club):
        """The dangerous failure mode: an empty list read as 'no restriction'."""
        from athleteiq.store import Principal

        principal = Principal(
            id=1, org_id=club["org"], role="coach", display_name="x",
            dominant_hand=None, team_ids=[],
        )
        sql, params = principal.scope_filter()
        assert "1 = 0" in sql
        assert params == []

    def test_an_unscoped_filter_is_empty(self, store, club):
        principal = store.authenticate(club["director"]["token"])
        assert principal.scope_filter() == ("", [])


class TestScopedRoster:
    def test_a_coach_roster_only_lists_their_team(self, store, club):
        from athleteiq.leaderboard import coach_roster

        principal = store.authenticate(club["varsity_coach"]["token"])
        rows = coach_roster(
            store.conn, club["org"], scope=principal.scope_filter()
        )
        assert [r["display_name"] for r in rows] == ["Varsity Kid"]

    def test_a_director_roster_lists_everyone(self, store, club):
        from athleteiq.leaderboard import coach_roster

        principal = store.authenticate(club["director"]["token"])
        rows = coach_roster(store.conn, club["org"], scope=principal.scope_filter())
        assert len(rows) == 2

    def test_a_coach_on_both_teams_sees_both(self, store, club):
        from athleteiq.leaderboard import coach_roster

        store.assign_staff_to_team(club["varsity_coach"]["id"], club["jv"]["id"])
        principal = store.authenticate(club["varsity_coach"]["token"])
        rows = coach_roster(store.conn, club["org"], scope=principal.scope_filter())
        assert len(rows) == 2
