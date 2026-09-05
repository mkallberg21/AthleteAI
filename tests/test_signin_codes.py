"""Sign-in codes are short on purpose, so they must survive colliding.

A code is one letter and five digits: 2.4 million of them. That is short
because a twelve-year-old reads it off a slip of paper and types it into a
phone, and lengthening it to make the maths comfortable would cost the thing
the code exists for.

Short means collisions are ordinary, not theoretical. Across a 600-athlete
club the birthday odds of two codes landing on the same value are better than
one in ten, and the club does not experience that as a statistic -- they
experience it as a roster import that dies two hundred names in. This was a
real failure: the full test suite hit it, intermittently, on the club-roster
tests, which is exactly how a club would.
"""
from __future__ import annotations

import sqlite3

import pytest

from offdays import db as db_mod
from offdays.db import connect
from offdays.store import Store, StoreError


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "t.db"))


class TestACollidingCodeIsRetried:
    def test_a_second_athlete_drawing_a_taken_code_still_gets_an_account(
        self, store, monkeypatch
    ):
        """The first draw collides, the second does not. Nobody sees an error."""
        org = store.create_org("Northshore LC")
        first = store.create_user(org, "athlete", "First", dominant_hand="right")

        draws = iter([first["token"], "Z99999"])
        monkeypatch.setattr("offdays.db.new_token", lambda: next(draws))

        second = store.create_user(org, "athlete", "Second", dominant_hand="right")
        assert second["token"] == "Z99999"
        assert second["id"] != first["id"]

    def test_the_code_it_returns_is_the_one_that_works(self, store, monkeypatch):
        """A retry that returns the first, rejected code would hand a child a
        slip of paper that does not sign them in."""
        org = store.create_org("Northshore LC")
        first = store.create_user(org, "athlete", "First", dominant_hand="right")

        draws = iter([first["token"], "Y12345"])
        monkeypatch.setattr("offdays.db.new_token", lambda: next(draws))
        second = store.create_user(org, "athlete", "Second", dominant_hand="right")

        assert store.authenticate(second["token"]).id == second["id"]

    def test_it_gives_up_rather_than_looping_for_ever(self, store, monkeypatch):
        """If every draw collides something is wrong with the generator, and a
        loop that never ends is worse than an error that names the problem."""
        org = store.create_org("Northshore LC")
        first = store.create_user(org, "athlete", "First", dominant_hand="right")

        monkeypatch.setattr("offdays.db.new_token", lambda: first["token"])
        with pytest.raises((StoreError, RuntimeError), match="unique sign-in code"):
            store.create_user(org, "athlete", "Doomed", dominant_hand="right")

    def test_a_different_constraint_failure_is_not_swallowed(self, store, monkeypatch):
        """Retrying is only correct for a code clash. A genuinely broken insert
        -- here, an org that does not exist -- must surface on the first attempt
        rather than being tried ten times and reported as a code problem."""
        draws = []
        real = db_mod.new_token

        def counted():
            draws.append(1)
            return real()

        monkeypatch.setattr("offdays.db.new_token", counted)

        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            store.create_user(999999, "athlete", "Orphan", dominant_hand="right")
        assert len(draws) <= 2, "a non-retryable failure was retried"


class TestASessionNonceIsNotASignInCode:
    """A nonce is machine-to-machine, so it never needed the small alphabet.

    Nonces were drawn from the same six-character space as sign-in codes.
    Every session ever recorded takes one, so where a sign-in collision is a
    coin-flip across a big club, a nonce collision is a certainty inside a
    single season -- and it surfaced as "could not start session" for an
    athlete standing in a driveway with nothing to fix.
    """

    def test_a_nonce_has_far_more_room_than_a_sign_in_code(self):
        from offdays.db import new_nonce, new_token
        assert len(new_nonce()) > len(new_token()) * 3

    def test_many_nonces_do_not_repeat(self):
        """Twenty thousand is roughly one club-season of sessions. The old
        generator collided reliably at this volume; the seeder proved it."""
        from offdays.db import new_nonce
        assert len({new_nonce() for _ in range(20000)}) == 20000

    def test_a_season_of_sessions_can_actually_be_recorded(self, store):
        """The end-to-end version: the seeder hit UNIQUE on sessions.nonce
        partway through building a demo, which is the same code path a club
        walks over a season."""
        org = store.create_org("Northshore LC")
        team = store.create_team(org, "U15")
        person = store.create_user(org, "athlete", "Busy", dominant_hand="right")
        store.join_team(team["join_code"], person["id"])
        for _ in range(400):
            store.start_session(person["id"], "lax_wall_ball")
        n = store.conn.execute("SELECT COUNT(DISTINCT nonce) FROM sessions").fetchone()[0]
        assert n == 400


class TestEveryPathThatIssuesACodeIsProtected:
    """create_user was not the only writer of users.token_hash."""

    def test_a_guardian_redeeming_an_invite_gets_an_unused_code(self, store, monkeypatch):
        from offdays import guardians as guardians_mod
        org = store.create_org("Northshore LC")
        director = store.create_user(org, "director", "Dir")
        kid = store.create_user(org, "athlete", "Kid", dominant_hand="right")
        first = store.create_user(org, "athlete", "Taken", dominant_hand="right")

        draws = iter([first["token"], "Z11111"])
        monkeypatch.setattr("offdays.db.new_token", lambda: next(draws))

        invite = guardians_mod.create_invite(store.conn, kid["id"], director["id"],
                                             email="p@example.com")
        parent = guardians_mod.redeem_invite(store.conn, invite["code"], "Parent", "p@example.com")
        assert parent["token"] == "Z11111"
        assert store.authenticate(parent["token"]).id == parent["guardian_id"]


class TestTheCodeItselfIsStillReadable:
    def test_it_stays_short_enough_for_a_child_to_type(self):
        """The retry exists so this can stay true. If a later change lengthens
        the code to dodge collisions, this is the test that argues back."""
        code = db_mod.new_token()
        assert len(code) == 6
        assert code[0].isalpha() and code[1:].isdigit()

    def test_it_avoids_the_letters_that_read_as_digits(self):
        """I and O off a slip of paper are 1 and 0."""
        assert not (set("IO") & set(db_mod.new_token()))
