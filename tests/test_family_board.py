"""The household board.

A club leaderboard works because forty athletes of roughly the same age are
already competing for the same places. A household is a nine-year-old and a
thirteen-year-old, and every test here is about not pretending otherwise.
"""

import random
from datetime import date, datetime, timedelta, timezone

import pytest

from athleteiq import family as F
from athleteiq.db import connect
from athleteiq.store import Store, StoreError

TODAY = date.today()


@pytest.fixture
def household(tmp_path):
    store = Store(connect(tmp_path / "f.db"))
    made = store.create_family("The Pierces", "Dana Pierce")
    older = store.add_family_athlete(
        made["org_id"], made["parent"]["id"], "Jordan Pierce",
        birth_year=TODAY.year - 14, dominant_hand="right",
        join_code=made["team"]["join_code"],
    )
    younger = store.add_family_athlete(
        made["org_id"], made["parent"]["id"], "Robin Pierce",
        birth_year=TODAY.year - 10, dominant_hand="right",
        join_code=made["team"]["join_code"],
    )
    return {"store": store, **made, "older": older, "younger": younger}


def train(store, athlete_id, day, seed=1, reps=None):
    slot = store.start_session(athlete_id, "gen_squat")
    rng = random.Random(seed)
    duration, t, out = 420_000, 0, []
    while True:
        gap = max(900, int(rng.gauss(2000, 300)))
        if t + gap > duration - 500:
            break
        t += gap
        rom = 78 * (1 + rng.gauss(0, 0.08))
        out.append({"t_ms": t, "confidence": 0.9, "rom": round(rom, 1),
                    "peak": round(rom * 0.7, 1), "cycle_ms": 2000})
    when = datetime(day.year, day.month, day.day, 17, tzinfo=timezone.utc)
    return store.submit_session(
        athlete_id, slot["session_id"], slot["nonce"], duration_ms=duration,
        reps=out[:reps] if reps else out, mean_confidence=0.9,
        completed_at=when.isoformat(),
    )


class TestSiblingsAreNotRankedByDefault:

    def test_the_board_has_no_ranking_in_it(self, household):
        board = household["store"].family_board(household["org_id"])
        assert board["compare_siblings"] is False
        assert "side_by_side" not in board
        for child in board["children"]:
            assert "rank" not in child

    def test_each_child_is_measured_against_their_own_recent_self(self, household):
        store = household["store"]
        # The older one trains far more, which is what four years buys.
        for i in range(6):
            train(store, household["older"]["id"], TODAY - timedelta(days=i), seed=i)
        for i in range(2):
            train(store, household["younger"]["id"], TODAY - timedelta(days=i), seed=i + 9)

        board = store.family_board(household["org_id"])
        by_name = {c["display_name"]: c for c in board["children"]}
        # Both compared to their own baseline, so neither is "behind".
        assert by_name["Jordan Pierce"]["days_baseline"] is not None
        assert by_name["Robin Pierce"]["days_baseline"] is not None

        # And no child's line ever mentions another child. That is the whole
        # difference between this and a leaderboard.
        names = {"Jordan", "Robin", "Pierce"}
        for child in board["children"]:
            assert child["note"], child["display_name"]
            leaked = names & set(child["note"].split())
            assert not leaked, f"{child['display_name']}'s note names {leaked}"

    def test_a_parent_can_turn_a_side_by_side_on(self, household):
        store = household["store"]
        store.set_sibling_compare(household["org_id"], True)
        board = store.family_board(household["org_id"])
        assert board["compare_siblings"] is True
        assert board["side_by_side"]

    def test_even_then_it_never_compares_volume(self, household):
        """A younger sibling can win turning up and can win moving well. They
        cannot win reps against someone four years older."""
        store = household["store"]
        store.set_sibling_compare(household["org_id"], True)
        for i in range(4):
            train(store, household["older"]["id"], TODAY - timedelta(days=i), seed=i)
        board = store.family_board(household["org_id"])
        metrics = {g["metric"] for g in board["side_by_side"]}
        assert metrics == {"days_this_week", "quality", "streak"}
        assert "reps_this_week" not in metrics
        assert "xp" not in metrics

    def test_a_program_account_has_no_household_board(self, tmp_path):
        store = Store(connect(tmp_path / "p.db"))
        org = store.create_org("A Club")
        with pytest.raises(StoreError, match="family setting"):
            store.set_sibling_compare(org, True)


class TestTheSharedNumber:

    def test_days_anyone_trained_is_the_collaborative_one(self, household):
        store = household["store"]
        train(store, household["older"]["id"], TODAY, seed=1)
        train(store, household["younger"]["id"], TODAY - timedelta(days=1), seed=2)
        board = store.family_board(household["org_id"])
        assert board["days_active"] == 2
        assert board["days_together"] == 0

    def test_days_everyone_trained_is_the_rarer_one(self, household):
        store = household["store"]
        for i in range(3):
            train(store, household["older"]["id"], TODAY - timedelta(days=i), seed=i)
            train(store, household["younger"]["id"], TODAY - timedelta(days=i), seed=i + 9)
        board = store.family_board(household["org_id"])
        assert board["days_together"] == 3
        assert board["together_streak"] == 3
        assert "everyone trained" in board["headline"]

    def test_the_together_streak_survives_a_late_sync(self, household):
        """Nobody has trained today yet, but the run through yesterday holds."""
        store = household["store"]
        for i in range(1, 4):
            train(store, household["older"]["id"], TODAY - timedelta(days=i), seed=i)
            train(store, household["younger"]["id"], TODAY - timedelta(days=i), seed=i + 9)
        assert store.family_board(household["org_id"])["together_streak"] == 3

    def test_an_empty_household_says_something_useful(self, tmp_path):
        store = Store(connect(tmp_path / "e.db"))
        made = store.create_family("New", "A Parent")
        board = store.family_board(made["org_id"])
        assert board["children"] == []
        assert "Add your athletes" in board["headline"]


class TestTrendsAreAboutThemselves:

    def test_a_first_week_reads_as_new_rather_than_behind(self, household):
        store = household["store"]
        train(store, household["younger"]["id"], TODAY, seed=3)
        child = next(
            c for c in store.family_board(household["org_id"])["children"]
            if c["display_name"] == "Robin Pierce"
        )
        assert child["trend"] == "new"
        assert "First week" in child["note"]

    def test_a_quieter_week_is_not_framed_as_failure(self):
        board = F.ChildBoard(
            athlete_id=1, display_name="Robin", age=10,
            days_this_week=1, days_baseline=4.0, sessions_this_week=1,
            reps_this_week=40, streak=0, longest_streak=6,
            quality=None, quality_baseline=None, best_quality=None,
        )
        board.trend = F._trend(board.days_this_week, board.days_baseline)
        assert board.trend == "down"
        assert "fine" in F._note(board)

    def test_a_small_wobble_is_not_a_trend(self):
        """A household of two produces small numbers, and 'up 0.3 days' is
        noise dressed as progress."""
        assert F._trend(3, 3.2) == "steady"
        assert F._trend(4, 3.2) == "up"

    def test_nothing_yet_is_encouraging_rather_than_empty(self):
        board = F.ChildBoard(
            athlete_id=1, display_name="Robin", age=10,
            days_this_week=0, days_baseline=0.0, sessions_this_week=0,
            reps_this_week=0, streak=0, longest_streak=0,
            quality=None, quality_baseline=None, best_quality=None,
        )
        assert "hard one" in F._note(board)


class TestItMatchesWhatTheAthleteSees:

    def test_the_streak_is_the_same_number_on_both_screens(self, household):
        """Two different numbers for the same word would be worse than not
        showing it."""
        store = household["store"]
        for i in range(4):
            train(store, household["older"]["id"], TODAY - timedelta(days=i), seed=i)
        board = next(
            c for c in store.family_board(household["org_id"])["children"]
            if c["athlete_id"] == household["older"]["id"]
        )
        assert board["streak"] == store.athlete_stats(household["older"]["id"]).current_streak

    def test_a_wellness_checkin_holds_the_family_streak_too(self, household):
        store = household["store"]
        for i in range(1, 4):
            train(store, household["older"]["id"], TODAY - timedelta(days=i), seed=i)
        store.check_in(household["older"]["id"], "sore")
        board = next(
            c for c in store.family_board(household["org_id"])["children"]
            if c["athlete_id"] == household["older"]["id"]
        )
        assert board["streak"] == 4, "saying you are sore must not cost a streak here either"
