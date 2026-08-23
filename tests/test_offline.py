"""Offline capture: reserved slots, idempotent submit, and day attribution.

These are the correctness properties an athlete in a dead zone depends on. A
lost session breaks a streak and a broken streak loses the athlete, so the
failure modes here matter more than they look.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from athleteiq.db import connect
from athleteiq.store import OFFLINE_BACKDATE_LIMIT_DAYS, Store, StoreError


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "o.db"))


@pytest.fixture
def athlete(store):
    org = store.create_org("Northshore")
    team = store.create_team(org, "Varsity")
    a = store.create_user(org, "athlete", "Jordan", dominant_hand="right")
    store.join_team(team["join_code"], a["id"])
    return a


def rep_stream(count=100, seed=1):
    rng = random.Random(seed)
    t, events = 0, []
    for i in range(count):
        t += max(150, int(rng.gauss(880, 190)))
        events.append({"t_ms": t, "hand": "left" if i % 2 else "right", "confidence": 0.88})
    return events, t + 700


class TestReservedSlots:
    def test_reserves_the_requested_number(self, store, athlete):
        slots = store.reserve_sessions(athlete["id"], "lax_wall_ball", 3)
        assert len(slots) == 3
        assert len({s["nonce"] for s in slots}) == 3
        assert len({s["session_id"] for s in slots}) == 3

    def test_reserved_slots_are_marked_as_such(self, store, athlete):
        slots = store.reserve_sessions(athlete["id"], "lax_wall_ball", 1)
        row = store.conn.execute(
            "SELECT reserved, status FROM sessions WHERE id = ?", (slots[0]["session_id"],)
        ).fetchone()
        assert row["reserved"] == 1
        assert row["status"] == "open"

    def test_reserve_count_is_clamped(self, store, athlete):
        """A client asking for a thousand slots must not get them."""
        assert len(store.reserve_sessions(athlete["id"], "lax_wall_ball", 9_999)) == 10
        assert len(store.reserve_sessions(athlete["id"], "lax_wall_ball", 0)) == 1

    def test_unknown_drill_is_refused(self, store, athlete):
        with pytest.raises(StoreError, match="unknown drill"):
            store.reserve_sessions(athlete["id"], "not_a_drill", 1)

    def test_a_reserved_slot_submits_normally(self, store, athlete):
        slot = store.reserve_sessions(athlete["id"], "lax_wall_ball", 1)[0]
        reps, duration = rep_stream()
        result = store.submit_session(
            athlete["id"], slot["session_id"], slot["nonce"],
            duration_ms=duration, reps=reps, mean_confidence=0.88,
        )
        assert result["status"] == "counted"
        assert result["xp_awarded"] > 0


class TestIdempotentSubmit:
    def test_resubmitting_returns_the_original_result(self, store, athlete):
        """An offline client that never saw its ack will retry."""
        slot = store.reserve_sessions(athlete["id"], "lax_wall_ball", 1)[0]
        reps, duration = rep_stream()
        first = store.submit_session(
            athlete["id"], slot["session_id"], slot["nonce"],
            duration_ms=duration, reps=reps, mean_confidence=0.88,
        )
        second = store.submit_session(
            athlete["id"], slot["session_id"], slot["nonce"],
            duration_ms=duration, reps=reps, mean_confidence=0.88,
        )
        assert second["xp_awarded"] == first["xp_awarded"]
        assert second["reps_total"] == first["reps_total"]
        assert second["duplicate"] is True

    def test_a_retry_never_scores_twice(self, store, athlete):
        slot = store.reserve_sessions(athlete["id"], "lax_wall_ball", 1)[0]
        reps, duration = rep_stream()
        for _ in range(4):
            store.submit_session(
                athlete["id"], slot["session_id"], slot["nonce"],
                duration_ms=duration, reps=reps, mean_confidence=0.88,
            )
        entries = store.conn.execute(
            "SELECT COUNT(*) AS n FROM xp_ledger WHERE athlete_id = ?", (athlete["id"],)
        ).fetchone()["n"]
        assert entries == 1

    def test_a_retry_cannot_inflate_the_original(self, store, athlete):
        """Resending with a bigger payload must not overwrite the first result."""
        slot = store.reserve_sessions(athlete["id"], "lax_wall_ball", 1)[0]
        reps, duration = rep_stream(100)
        first = store.submit_session(
            athlete["id"], slot["session_id"], slot["nonce"],
            duration_ms=duration, reps=reps, mean_confidence=0.88,
        )
        bigger, longer = rep_stream(400, seed=9)
        second = store.submit_session(
            athlete["id"], slot["session_id"], slot["nonce"],
            duration_ms=longer, reps=bigger, mean_confidence=0.88,
        )
        assert second["reps_total"] == first["reps_total"] == 100

    def test_a_wrong_nonce_cannot_read_back_the_result(self, store, athlete):
        """The idempotency path must not become an oracle for other athletes."""
        slot = store.reserve_sessions(athlete["id"], "lax_wall_ball", 1)[0]
        reps, duration = rep_stream()
        store.submit_session(
            athlete["id"], slot["session_id"], slot["nonce"],
            duration_ms=duration, reps=reps, mean_confidence=0.88,
        )
        with pytest.raises(StoreError, match="nonce"):
            store.submit_session(
                athlete["id"], slot["session_id"], "wrong-nonce",
                duration_ms=duration, reps=reps, mean_confidence=0.88,
            )

    def test_another_athlete_cannot_replay_a_session(self, store, athlete):
        other = store.create_user(1, "athlete", "Sam")
        slot = store.reserve_sessions(athlete["id"], "lax_wall_ball", 1)[0]
        reps, duration = rep_stream()
        store.submit_session(
            athlete["id"], slot["session_id"], slot["nonce"],
            duration_ms=duration, reps=reps, mean_confidence=0.88,
        )
        with pytest.raises(StoreError, match="different athlete"):
            store.submit_session(
                other["id"], slot["session_id"], slot["nonce"],
                duration_ms=duration, reps=reps, mean_confidence=0.88,
            )


class TestDayAttribution:
    def test_a_backdated_session_credits_the_day_it_was_trained(self, store, athlete):
        """Trained Sunday in a dead zone, synced Monday -- Sunday gets the credit."""
        when = datetime.now(timezone.utc) - timedelta(days=3)
        slot = store.reserve_sessions(athlete["id"], "lax_wall_ball", 1)[0]
        reps, duration = rep_stream()
        result = store.submit_session(
            athlete["id"], slot["session_id"], slot["nonce"],
            duration_ms=duration, reps=reps, mean_confidence=0.88,
            completed_at=when.isoformat(),
        )
        assert result["counted_for_day"] == when.date().isoformat()
        day = store.conn.execute(
            "SELECT day FROM xp_ledger WHERE athlete_id = ?", (athlete["id"],)
        ).fetchone()["day"]
        assert day == when.date().isoformat()

    def test_a_future_dated_session_is_clamped_to_today(self, store, athlete):
        """A device clock set forward must not let an athlete bank future days."""
        when = datetime.now(timezone.utc) + timedelta(days=10)
        slot = store.reserve_sessions(athlete["id"], "lax_wall_ball", 1)[0]
        reps, duration = rep_stream()
        result = store.submit_session(
            athlete["id"], slot["session_id"], slot["nonce"],
            duration_ms=duration, reps=reps, mean_confidence=0.88,
            completed_at=when.isoformat(),
        )
        assert result["counted_for_day"] == datetime.now(timezone.utc).date().isoformat()

    def test_backdating_past_the_limit_falls_back_to_today(self, store, athlete):
        when = datetime.now(timezone.utc) - timedelta(days=OFFLINE_BACKDATE_LIMIT_DAYS + 10)
        slot = store.reserve_sessions(athlete["id"], "lax_wall_ball", 1)[0]
        reps, duration = rep_stream()
        result = store.submit_session(
            athlete["id"], slot["session_id"], slot["nonce"],
            duration_ms=duration, reps=reps, mean_confidence=0.88,
            completed_at=when.isoformat(),
        )
        assert result["counted_for_day"] == datetime.now(timezone.utc).date().isoformat()

    def test_a_malformed_completion_time_falls_back_to_today(self, store, athlete):
        slot = store.reserve_sessions(athlete["id"], "lax_wall_ball", 1)[0]
        reps, duration = rep_stream()
        result = store.submit_session(
            athlete["id"], slot["session_id"], slot["nonce"],
            duration_ms=duration, reps=reps, mean_confidence=0.88,
            completed_at="last tuesday",
        )
        assert result["counted_for_day"] == datetime.now(timezone.utc).date().isoformat()

    def test_the_daily_cap_applies_to_the_credited_day(self, store, athlete):
        """Backdating must not be a way around the daily cap."""
        from athleteiq.config import CONFIG

        when = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        for seed in range(6):
            slot = store.reserve_sessions(athlete["id"], "lax_wall_ball", 1)[0]
            reps, duration = rep_stream(400, seed=seed)
            store.submit_session(
                athlete["id"], slot["session_id"], slot["nonce"],
                duration_ms=duration, reps=reps, mean_confidence=0.88,
                completed_at=when,
            )
        banked = store.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS t FROM xp_ledger WHERE athlete_id = ? AND day = ?",
            (athlete["id"], when[:10]),
        ).fetchone()["t"]
        assert banked <= CONFIG.scoring.daily_xp_cap
