"""Notification generation, deduplication, and delivery.

The dedupe behaviour carries most of the weight here: generators are designed
to be run repeatedly by a scheduler, and a streak warning that fires twelve
times a day is how push permission gets revoked.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

import pytest

from offdays import assignments, notifications as notify
from offdays.db import connect
from offdays.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "n.db"))


@pytest.fixture
def program(store):
    org = store.create_org("Northshore")
    coach = store.create_user(org, "coach", "Coach R")
    team = store.create_team(org, "Varsity")
    athletes = []
    for name in ("Jordan", "Sam"):
        a = store.create_user(org, "athlete", name, dominant_hand="right")
        store.join_team(team["join_code"], a["id"])
        athletes.append(a)
    return {"org": org, "coach": coach, "team": team, "athletes": athletes}


def train(store, athlete_id, reps=120, seed=1, when=None):
    slot = store.start_session(athlete_id, "lax_wall_ball")
    rng = random.Random(seed)
    t, events = 0, []
    for i in range(reps):
        t += max(150, int(rng.gauss(880, 190)))
        events.append({"t_ms": t, "hand": "left" if i % 2 else "right", "confidence": 0.88})
    return store.submit_session(
        athlete_id, slot["session_id"], slot["nonce"],
        duration_ms=t + 700, reps=events, mean_confidence=0.88, completed_at=when,
    )


class TestEnqueue:
    def test_stores_and_counts_unread(self, store, program):
        athlete = program["athletes"][0]["id"]
        notify.enqueue(store.conn, athlete, notify.Kind.BADGE, "Hi", "there")
        assert notify.unread_count(store.conn, athlete) == 1
        assert notify.feed(store.conn, athlete)[0]["title"] == "Hi"

    def test_dedupe_key_suppresses_repeats(self, store, program):
        athlete = program["athletes"][0]["id"]
        first = notify.enqueue(store.conn, athlete, "k", "T", dedupe_key="same")
        second = notify.enqueue(store.conn, athlete, "k", "T", dedupe_key="same")
        assert first is not None
        assert second is None
        assert len(notify.feed(store.conn, athlete)) == 1

    def test_dedupe_is_per_user(self, store, program):
        a, b = (x["id"] for x in program["athletes"])
        assert notify.enqueue(store.conn, a, "k", "T", dedupe_key="same") is not None
        assert notify.enqueue(store.conn, b, "k", "T", dedupe_key="same") is not None

    def test_mark_all_read(self, store, program):
        athlete = program["athletes"][0]["id"]
        for i in range(3):
            notify.enqueue(store.conn, athlete, "k", f"T{i}", dedupe_key=f"d{i}")
        assert notify.mark_read(store.conn, athlete) == 3
        assert notify.unread_count(store.conn, athlete) == 0

    def test_mark_one_read(self, store, program):
        athlete = program["athletes"][0]["id"]
        nid = notify.enqueue(store.conn, athlete, "k", "T", dedupe_key="d")
        notify.enqueue(store.conn, athlete, "k", "T2", dedupe_key="d2")
        assert notify.mark_read(store.conn, athlete, nid) == 1
        assert notify.unread_count(store.conn, athlete) == 1


class TestGenerators:
    def test_new_assignment_notifies_the_whole_team(self, store, program):
        today = date.today()
        aid = assignments.create(
            store.conn, org_id=program["org"], team_id=program["team"]["id"],
            created_by=program["coach"]["id"], drill_key="lax_wall_ball",
            title="Week 1", starts_on=today.isoformat(),
            due_on=(today + timedelta(days=6)).isoformat(), target_reps=300,
        )
        assert notify.notify_new_assignment(store.conn, aid) == 2
        # Re-announcing the same assignment must not spam anyone.
        assert notify.notify_new_assignment(store.conn, aid) == 0

    def test_assignment_reminder_fires_only_near_the_due_date(self, store, program):
        today = date.today()
        assignments.create(
            store.conn, org_id=program["org"], team_id=program["team"]["id"],
            created_by=program["coach"]["id"], drill_key="lax_wall_ball",
            title="Week 1", starts_on=(today - timedelta(days=1)).isoformat(),
            due_on=(today + timedelta(days=5)).isoformat(), target_reps=300,
        )
        # Five days out is too early to nag.
        assert notify.generate_assignment_reminders(store.conn, today) == 0
        # Two days out is the heads-up.
        assert notify.generate_assignment_reminders(store.conn, today + timedelta(days=3)) == 2

    def test_a_completed_assignment_produces_no_reminder(self, store, program):
        today = date.today()
        assignments.create(
            store.conn, org_id=program["org"], team_id=program["team"]["id"],
            created_by=program["coach"]["id"], drill_key="lax_wall_ball",
            title="Week 1", starts_on=(today - timedelta(days=1)).isoformat(),
            due_on=(today + timedelta(days=2)).isoformat(), target_sessions=1,
        )
        train(store, program["athletes"][0]["id"])
        made = notify.generate_assignment_reminders(store.conn, today)
        assert made == 1  # only the athlete who has not done it

    def test_streak_warning_needs_a_streak_worth_saving(self, store, program):
        """Warning about a one-day streak is noise, and noise costs permission."""
        athlete = program["athletes"][0]["id"]
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        train(store, athlete, when=yesterday)
        assert notify.generate_streak_warnings(store.conn) == 0

    def test_streak_warning_fires_for_a_real_streak_at_risk(self, store, program):
        athlete = program["athletes"][0]["id"]
        for days_ago in (4, 3, 2, 1):
            when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
            train(store, athlete, seed=days_ago, when=when)
        assert notify.generate_streak_warnings(store.conn) == 1
        # Running the scheduler again the same day must not re-warn.
        assert notify.generate_streak_warnings(store.conn) == 0

    def test_badges_notify_once_each(self, store, program):
        athlete = program["athletes"][0]["id"]
        assert notify.notify_badges(store.conn, athlete, ["first_session", "wall_100"]) == 2
        assert notify.notify_badges(store.conn, athlete, ["first_session"]) == 0

    def test_unknown_badge_keys_are_ignored(self, store, program):
        athlete = program["athletes"][0]["id"]
        assert notify.notify_badges(store.conn, athlete, ["not_a_badge"]) == 0

    def test_broadcast_reaches_every_athlete_on_the_team(self, store, program):
        sent = notify.broadcast(
            store.conn, program["team"]["id"], "Practice at 6", "Turf.", program["coach"]["id"]
        )
        assert sent == 2

    def test_run_all_is_idempotent(self, store, program):
        train(store, program["athletes"][0]["id"])
        notify.run_all(store.conn)
        again = notify.run_all(store.conn)
        assert sum(again.values()) == 0

    def test_submitting_a_session_notifies_new_badges(self, store, program):
        """The badge the athlete just earned should reach them, not sit in a table."""
        athlete = program["athletes"][0]["id"]
        train(store, athlete)
        titles = [n["title"] for n in notify.feed(store.conn, athlete)]
        assert any("First Rep" in t for t in titles)


class TestDelivery:
    def test_log_channel_marks_notifications_pushed(self, store, program):
        athlete = program["athletes"][0]["id"]
        notify.enqueue(store.conn, athlete, "k", "T", dedupe_key="d")
        assert notify.dispatch(store.conn, [notify.LogChannel()]) == 1
        # Already pushed, so a second dispatch is a no-op.
        assert notify.dispatch(store.conn, [notify.LogChannel()]) == 0

    def test_dispatch_works_with_no_channel_configured(self, store, program):
        """The in-app feed must not depend on any third-party service."""
        athlete = program["athletes"][0]["id"]
        notify.enqueue(store.conn, athlete, "k", "T", dedupe_key="d")
        assert notify.dispatch(store.conn, []) == 0
        # Still readable in the feed even though nothing shipped it.
        assert len(notify.feed(store.conn, athlete)) == 1

    def test_push_subscription_upserts_on_endpoint(self, store, program):
        athlete = program["athletes"][0]["id"]
        notify.save_subscription(store.conn, athlete, "https://push/1", "k1", "a1")
        notify.save_subscription(store.conn, athlete, "https://push/1", "k2", "a2")
        rows = store.conn.execute(
            "SELECT p256dh FROM push_subscriptions WHERE user_id = ?", (athlete,)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["p256dh"] == "k2"

    def test_webpush_channel_degrades_without_the_library(self, store, program):
        """A missing optional dependency must not break the generator."""
        athlete = program["athletes"][0]["id"]
        notify.enqueue(store.conn, athlete, "k", "T", dedupe_key="d")
        channel = notify.WebPushChannel("fake-key", "coach@example.com")
        payload = notify.Payload(1, athlete, "k", "T", "", "")
        assert channel.send(store.conn, payload) is False
