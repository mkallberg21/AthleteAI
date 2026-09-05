"""The one leaderboard a parent may open.

A club splits a birth year into a Red side and a Blue side, and the parent on
the Blue side has a question: what is the Red side doing that mine is not.
Until now the product's answer was to refuse the question -- no leaderboard in
the parent view, on the grounds that ranked lists of other people's children
are the mechanism behind the worst behaviour in youth sports.

That reasoning is still right about the program board, and the program board
is still closed. It is wrong about this one, because refusing the question does
not retire it. It relocates it to the car park, where it gets answered with a
guess about who the coach likes. So: one cohort, ranked on work an athlete
chooses to do, with the name-masking consent gate still in force.

These tests pin the parts that make that defensible rather than merely
convenient -- the scope of what a guardian can reach, what the board ranks,
and that a child whose family said no is still counted but not named.
"""
from __future__ import annotations

import pytest

from offdays.db import connect
from offdays.leaderboard import age_group_of, age_group_teams, leaderboard_age_group
from offdays.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "c.db"))


@pytest.fixture
def program(store):
    """One birth year, split two ways, plus a cohort that must stay separate."""
    org = store.create_org("Nashville Dogs")
    red = store.create_team(org, "2031 Red", "2026", age_group="2031")
    blue = store.create_team(org, "2031 Blue", "2026", age_group="2031")
    older = store.create_team(org, "2029 Red", "2026", age_group="2029")

    people = {}
    for team, names in ((red, ["Scott", "Tanner"]),
                        (blue, ["Dano", "Harrison"]),
                        (older, ["Elder"])):
        for name in names:
            # Consented, so these tests are about cohort scope rather than
            # about name masking -- that has its own class below.
            person = store.create_user(
                org, "athlete", name, birth_year=2013, dominant_hand="right",
                guardian_consent=True)
            store.join_team(team["join_code"], person["id"])
            people[name] = person
    return {"org": org, "red": red, "blue": blue, "older": older, "people": people}


class TestTheCohortIsTheUnit:
    def test_a_cohort_board_spans_every_squad_the_year_was_split_into(self, store, program):
        rows = leaderboard_age_group(store.conn, program["org"], "2031")
        names = {r["display_name"] for r in rows}
        assert {"Scott", "Tanner", "Dano", "Harrison"} <= names

    def test_it_stops_at_the_cohort_boundary(self, store, program):
        """The point is the squad next door, not the club. An older age group
        is a different question and a different set of children."""
        rows = leaderboard_age_group(store.conn, program["org"], "2031")
        assert "Elder" not in {r["display_name"] for r in rows}

    def test_every_row_says_which_squad(self, store, program):
        """A cohort board that does not label the squad is unreadable for the
        one thing it exists to show."""
        rows = leaderboard_age_group(store.conn, program["org"], "2031")
        assert {r["team_name"] for r in rows} == {"2031 Red", "2031 Blue"}
        assert all(r["team_name"] for r in rows)

    def test_the_squads_sharing_a_cohort_can_be_named(self, store, program):
        assert age_group_teams(store.conn, program["org"], "2031") == [
            "2031 Blue", "2031 Red"]

    def test_an_athlete_knows_their_own_cohort(self, store, program):
        assert age_group_of(store.conn, program["people"]["Dano"]["id"]) == "2031"

    def test_a_team_with_no_cohort_set_has_none(self, store):
        """Most clubs will not fill this in, and nothing may break when they
        do not -- they simply never see a cohort board."""
        org = store.create_org("Unsplit LC")
        team = store.create_team(org, "Seniors")
        person = store.create_user(org, "athlete", "Solo", dominant_hand="right")
        store.join_team(team["join_code"], person["id"])
        assert age_group_of(store.conn, person["id"]) is None


class TestConsentStillGovernsNames:
    def test_a_child_whose_family_said_no_is_counted_but_not_named(self, store):
        """Counted, because leaving them off would make the board a lie about
        where everyone else placed. Not named, because that is what the family
        agreed to."""
        org = store.create_org("Nashville Dogs")
        team = store.create_team(org, "2031 Red", "2026", age_group="2031")
        shown = store.create_user(
            org, "athlete", "Named Kid", birth_year=2013,
            dominant_hand="right", guardian_consent=True)
        hidden = store.create_user(
            org, "athlete", "Hidden Kid", birth_year=2013,
            dominant_hand="right", guardian_consent=False)
        store.join_team(team["join_code"], shown["id"], jersey="7")
        store.join_team(team["join_code"], hidden["id"], jersey="9")

        rows = leaderboard_age_group(store.conn, org, "2031")
        names = {r["display_name"] for r in rows}
        assert "Named Kid" in names
        assert "Hidden Kid" not in names
        assert len(rows) == 2, "the masked child is still on the board"


@pytest.fixture
def wired(tmp_path):
    """The API, over a program whose 2031 year is split and whose 2029 is not.

    Built through the store rather than the HTTP surface because a guardian
    link is what matters here, and that is made by invitation.
    """
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import offdays.api as api_module
    from offdays import guardians as guardians_mod

    store = Store(connect(tmp_path / "w.db"))
    api_module._store = store

    org = store.create_org("Nashville Dogs")
    director = store.create_user(org, "director", "Joel White")
    red = store.create_team(org, "2031 Red", "2026", age_group="2031")
    store.create_team(org, "2031 Blue", "2026", age_group="2031")
    older = store.create_team(org, "2029 Red", "2026", age_group="2029")

    kid = store.create_user(
        org, "athlete", "Scott Anderson", birth_year=2013, dominant_hand="right")
    store.join_team(red["join_code"], kid["id"])

    elder = store.create_user(
        org, "athlete", "Elder Kid", birth_year=2011, dominant_hand="right")
    store.join_team(older["join_code"], elder["id"])

    invite = guardians_mod.create_invite(
        store.conn, kid["id"], director["id"], email="parent@example.com")
    parent = guardians_mod.redeem_invite(
        store.conn, invite["code"], "Travis Anderson", "parent@example.com")
    guardians_mod.set_consent(
        store.conn, kid["id"], parent["guardian_id"],
        guardians_mod.Scope.PARTICIPATION, True)

    client = TestClient(api_module.app)
    yield {
        "client": client,
        "guardian": {"Authorization": f"Bearer {parent['token']}"},
        "athlete": {"Authorization": f"Bearer {kid['token']}"},
    }
    api_module._store = None


class TestWhoMayOpenIt:
    """Scope is the whole argument. A guardian gets one board, not a portal
    into the club."""

    def test_a_guardian_is_refused_the_program_board(self, wired):
        r = wired["client"].get("/api/leaderboard", headers=wired["guardian"])
        assert r.status_code == 403

    def test_a_guardian_is_refused_a_cohort_that_is_not_their_child_s(self, wired):
        """The carve-out is one cohort, not a key to the club. Without this the
        exception quietly becomes the thing it was scoped to avoid."""
        r = wired["client"].get(
            "/api/leaderboard?age_group=2029", headers=wired["guardian"])
        assert r.status_code == 403

    def test_a_guardian_gets_their_own_cohort(self, wired):
        r = wired["client"].get(
            "/api/leaderboard?age_group=2031", headers=wired["guardian"])
        assert r.status_code == 200
        body = r.json()
        assert body["age_group"] == "2031"
        assert body["teams"] == ["2031 Blue", "2031 Red"]

    def test_an_athlete_gets_their_own_cohort(self, wired):
        r = wired["client"].get(
            "/api/leaderboard?age_group=2031", headers=wired["athlete"])
        assert r.status_code == 200

    def test_an_athlete_is_told_which_cohort_they_are_in(self, wired):
        """The board tab cannot offer a cohort it does not know the name of."""
        me = wired["client"].get("/api/me", headers=wired["athlete"]).json()
        assert me["age_group"] == "2031"


class TestTheWholeCohortIsShown:
    """A cut-off on this board answers the parent's question wrongly.

    The rows a limit drops are the low ones: the children who trained least.
    A parent asking why their child is on the second squad needs the bottom of
    this list as much as the top, and a child who did little should not be
    hidden from the comparison by having done little. The join already bounds
    this to one birth year at one club, so there is nothing a cap protects.
    """

    @pytest.fixture
    def big_cohort(self, store):
        """A birth year larger than the old 50-row default."""
        org = store.create_org("Nashville Dogs")
        red = store.create_team(org, "2031 Red", "2026", age_group="2031")
        blue = store.create_team(org, "2031 Blue", "2026", age_group="2031")
        for i in range(60):
            person = store.create_user(
                org, "athlete", f"Athlete {i:02d}", birth_year=2013,
                dominant_hand="right", guardian_consent=True)
            store.join_team((red if i % 2 else blue)["join_code"], person["id"])
        return org

    def test_a_cohort_larger_than_the_old_default_is_not_truncated(
            self, store, big_cohort):
        rows = leaderboard_age_group(store.conn, big_cohort, "2031")
        assert len(rows) == 60

    def test_a_child_who_trained_nothing_is_still_on_the_board(
            self, store, big_cohort):
        """Zero is a legitimate row here, and often the informative one."""
        rows = leaderboard_age_group(store.conn, big_cohort, "2031")
        assert [r for r in rows if r["value"] == 0]

    def test_an_explicit_limit_is_still_honoured(self, store, big_cohort):
        """Uncapped by default is not the same as uncappable."""
        rows = leaderboard_age_group(store.conn, big_cohort, "2031", limit=10)
        assert len(rows) == 10

    def test_the_endpoint_returns_the_cohort_without_being_asked_for_a_limit(
            self, wired):
        """The page sends no limit; the cohort still comes back.

        The name is masked here because that family consented to
        participation and not to their child being named, which is the
        behaviour TestConsentStillGovernsNames pins. The row is present
        either way -- that is the point.
        """
        r = wired["client"].get(
            "/api/leaderboard?age_group=2031", headers=wired["guardian"])
        assert r.status_code == 200
        assert [row for row in r.json()["rows"] if row["display_name"] == "Athlete S."]

    def test_the_program_board_still_defaults_to_fifty(self, store):
        """Removing the cap was scoped to the cohort board on purpose."""
        from offdays.leaderboard import leaderboard
        org = store.create_org("Big Club")
        team = store.create_team(org, "Squad", "2026", age_group="2031")
        for i in range(60):
            person = store.create_user(
                org, "athlete", f"Player {i:02d}", birth_year=2013,
                dominant_hand="right", guardian_consent=True)
            store.join_team(team["join_code"], person["id"])
        assert len(leaderboard(store.conn, org)) == 50
