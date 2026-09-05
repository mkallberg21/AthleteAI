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
        monkeypatch.setattr("offdays.store.new_token", lambda: next(draws))

        second = store.create_user(org, "athlete", "Second", dominant_hand="right")
        assert second["token"] == "Z99999"
        assert second["id"] != first["id"]

    def test_the_code_it_returns_is_the_one_that_works(self, store, monkeypatch):
        """A retry that returns the first, rejected code would hand a child a
        slip of paper that does not sign them in."""
        org = store.create_org("Northshore LC")
        first = store.create_user(org, "athlete", "First", dominant_hand="right")

        draws = iter([first["token"], "Y12345"])
        monkeypatch.setattr("offdays.store.new_token", lambda: next(draws))
        second = store.create_user(org, "athlete", "Second", dominant_hand="right")

        assert store.authenticate(second["token"]).id == second["id"]

    def test_it_gives_up_rather_than_looping_for_ever(self, store, monkeypatch):
        """If every draw collides something is wrong with the generator, and a
        loop that never ends is worse than an error that names the problem."""
        org = store.create_org("Northshore LC")
        first = store.create_user(org, "athlete", "First", dominant_hand="right")

        monkeypatch.setattr("offdays.store.new_token", lambda: first["token"])
        with pytest.raises(StoreError, match="unique sign-in code"):
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

        monkeypatch.setattr("offdays.store.new_token", counted)

        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            store.create_user(999999, "athlete", "Orphan", dominant_hand="right")
        assert len(draws) == 1, "a non-retryable failure was retried"


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
