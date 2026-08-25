"""Planned absence: the difference between pausing a streak and forgiving one.

Streaks already forgive one missed day, which covers a bad week. They do not
cover a family holiday or a tournament weekend away, and those are predictable
-- which makes losing a streak to one a churn moment the product walked into
with its eyes open.

There are two ways to build this and only one is honest. Counting absence days
as active days is easy and turns a fortnight away into twenty-one days of
streak, which describes nothing the child did; a number nobody believes is a
number nobody protects. So the days are removed from the timeline instead. The
gap closes, and the athlete comes back to exactly the streak they earned. They
do not gain, they just do not lose.

The other rule is who sets it. Not the athlete: a child who can declare their
own absence has a button that undoes a missed day, and a streak with an undo
button is not a streak.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from offdays import absence
from offdays.absence import AbsenceError
from offdays.db import connect
from offdays.scoring import compute_streak
from offdays.store import Store

BASE = date(2026, 7, 1)
WEEK = [BASE + timedelta(days=i) for i in range(7)]
AWAY = {BASE + timedelta(days=i) for i in range(7, 21)}
HOME = BASE + timedelta(days=21)


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "a.db"))


@pytest.fixture
def athlete(store):
    org = store.create_org("Northshore")
    director = store.create_user(org, "director", "Coach Ada")
    team = store.create_team(org, "U15 Boys")
    person = store.create_user(
        org, "athlete", "Jordan P.", birth_year=2011, dominant_hand="right"
    )
    store.join_team(team["join_code"], person["id"])
    return {"org": org, "director": director, "team": team, "person": person}


class TestItPausesRatherThanCredits:
    def test_a_gap_that_is_booked_does_not_break_the_streak(self):
        assert compute_streak(WEEK + [HOME], HOME, paused=AWAY).current == 8

    def test_the_same_gap_unbooked_still_breaks_it(self):
        """The forgiveness is the booking, not a general softening."""
        assert compute_streak(WEEK + [HOME], HOME).current == 1

    def test_the_holiday_earns_nothing(self):
        """A fortnight away must not turn a seven-day streak into twenty-one.
        A number that describes nothing the child did is one nobody protects."""
        streak = compute_streak(WEEK + [HOME], HOME, paused=AWAY)
        assert streak.current == len(WEEK) + 1
        assert streak.current < len(WEEK) + len(AWAY)

    def test_being_away_is_not_being_at_risk(self):
        """'Train today or lose it' is exactly the message this exists to
        stop sending, and a family holiday is exactly when it would land."""
        mid = BASE + timedelta(days=14)
        assert compute_streak(WEEK, mid, paused=AWAY).at_risk is False

    def test_the_warning_comes_back_the_day_they_are_home(self):
        assert compute_streak(WEEK, HOME, paused=AWAY).at_risk is True

    def test_a_longest_streak_spanning_a_break_is_recorded(self):
        assert compute_streak(WEEK + [HOME], HOME, paused=AWAY).longest == 8

    def test_overlapping_bookings_count_once(self, store, athlete):
        """A coach books the tournament and a parent books the same weekend."""
        for _ in range(2):
            absence.schedule(
                store.conn, athlete["person"]["id"],
                (BASE + timedelta(days=7)).isoformat(),
                (BASE + timedelta(days=20)).isoformat(),
                today=BASE + timedelta(days=7),
            )
        assert len(absence.paused_days(store.conn, athlete["person"]["id"])) == 14


class TestOnlyAnAdultSetsIt:
    def test_a_window_is_recorded_with_who_set_it(self, store, athlete):
        booked = absence.schedule(
            store.conn, athlete["person"]["id"],
            BASE.isoformat(), (BASE + timedelta(days=6)).isoformat(),
            set_by=athlete["director"]["id"], set_by_name="Coach Ada",
            reason="Tournament", today=BASE,
        )
        assert booked.set_by_name == "Coach Ada"
        assert booked.days == 7


class TestItStaysAPauseAndNotAnUndoButton:
    def test_a_window_longer_than_a_month_is_refused(self, store, athlete):
        """Longer than that is a season off, and a streak that survives a
        two-month gap is not describing a habit."""
        with pytest.raises(AbsenceError, match="longer than a pause"):
            absence.schedule(
                store.conn, athlete["person"]["id"], BASE.isoformat(),
                (BASE + timedelta(days=45)).isoformat(), today=BASE)

    def test_an_old_gap_cannot_be_repaired_after_the_fact(self, store, athlete):
        """A window that can start six months back is the undo button wearing
        a hat."""
        with pytest.raises(AbsenceError, match="days ago"):
            absence.schedule(
                store.conn, athlete["person"]["id"],
                (BASE - timedelta(days=60)).isoformat(),
                (BASE - timedelta(days=50)).isoformat(), today=BASE)

    def test_but_a_few_days_of_grace_is_allowed(self, store, athlete):
        """The parent who set off on Saturday and remembered on Monday."""
        booked = absence.schedule(
            store.conn, athlete["person"]["id"],
            (BASE - timedelta(days=2)).isoformat(),
            (BASE + timedelta(days=5)).isoformat(), today=BASE)
        assert booked.days == 8

    def test_booking_a_year_out_is_refused(self, store, athlete):
        with pytest.raises(AbsenceError, match="too far ahead"):
            absence.schedule(
                store.conn, athlete["person"]["id"],
                (BASE + timedelta(days=800)).isoformat(),
                (BASE + timedelta(days=810)).isoformat(), today=BASE)

    def test_backwards_dates_are_refused(self, store, athlete):
        with pytest.raises(AbsenceError, match="before it starts"):
            absence.schedule(
                store.conn, athlete["person"]["id"],
                (BASE + timedelta(days=5)).isoformat(), BASE.isoformat(),
                today=BASE)


class TestWhatTheAthleteReads:
    def test_the_note_says_the_streak_is_safe_and_asks_for_nothing(
        self, store, athlete
    ):
        booked = absence.schedule(
            store.conn, athlete["person"]["id"], BASE.isoformat(),
            (BASE + timedelta(days=6)).isoformat(), reason="Family holiday",
            today=BASE)
        note = absence.note(booked)
        assert "paused, not broken" in note
        assert "Family holiday" in note
        for nagging in ("try to", "still count", "ten minutes", "keep it up"):
            assert nagging not in note.lower(), f"the away note nags: {nagging!r}"

    def test_there_is_no_note_when_they_are_not_away(self, store, athlete):
        assert absence.note(None) == ""

    def test_current_finds_the_window_they_are_in(self, store, athlete):
        absence.schedule(
            store.conn, athlete["person"]["id"], BASE.isoformat(),
            (BASE + timedelta(days=6)).isoformat(), today=BASE)
        assert absence.current(
            store.conn, athlete["person"]["id"], BASE + timedelta(days=3)) is not None
        assert absence.current(
            store.conn, athlete["person"]["id"], BASE + timedelta(days=30)) is None


class TestNudgesGoQuiet:
    def test_no_streak_warning_while_away(self, store, athlete):
        from offdays import notifications

        today = BASE + timedelta(days=3)
        absence.schedule(
            store.conn, athlete["person"]["id"], BASE.isoformat(),
            (BASE + timedelta(days=6)).isoformat(), today=BASE)
        notifications.generate_streak_warnings(store.conn, today)
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? "
            "AND kind = 'streak_at_risk'",
            (athlete["person"]["id"],),
        ).fetchone()["n"] == 0

    def test_no_inactivity_nudge_while_away(self, store, athlete):
        """A booked absence is not going quiet. Nudging through one is how a
        family decides the app is not worth having on the phone."""
        from offdays import notifications

        store.conn.execute(
            "INSERT INTO sessions(athlete_id, drill_key, status, submitted_at, "
            "  started_at, duration_ms, reps_total, nonce) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (athlete["person"]["id"], "gen_squat", "counted",
             (BASE - timedelta(days=20)).isoformat() + "T10:00:00+00:00",
             (BASE - timedelta(days=20)).isoformat() + "T10:00:00+00:00",
             600000, 20, "n1"),
        )
        store.conn.commit()
        absence.schedule(
            store.conn, athlete["person"]["id"], BASE.isoformat(),
            (BASE + timedelta(days=6)).isoformat(), today=BASE)
        notifications.notify_inactive(store.conn, today=BASE + timedelta(days=3))
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? "
            "AND kind = 'inactive'",
            (athlete["person"]["id"],),
        ).fetchone()["n"] == 0


class TestCancelling:
    def test_cancelling_puts_the_days_back_on_the_timeline(self, store, athlete):
        booked = absence.schedule(
            store.conn, athlete["person"]["id"],
            (BASE + timedelta(days=7)).isoformat(),
            (BASE + timedelta(days=20)).isoformat(),
            today=BASE + timedelta(days=7))
        assert absence.paused_days(store.conn, athlete["person"]["id"])
        assert absence.cancel(store.conn, booked.id, athlete["person"]["id"]) is True
        assert absence.paused_days(store.conn, athlete["person"]["id"]) == set()

    def test_cancelling_someone_elses_does_nothing(self, store, athlete):
        booked = absence.schedule(
            store.conn, athlete["person"]["id"], BASE.isoformat(),
            (BASE + timedelta(days=6)).isoformat(), today=BASE)
        other = store.create_user(
            athlete["org"], "athlete", "Sam R.", birth_year=2011,
            dominant_hand="left")
        assert absence.cancel(store.conn, booked.id, other["id"]) is False


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
def wired(client):
    from offdays import api as api_mod
    from offdays import guardians as guardians_mod

    store = api_mod.get_store()
    org = client.post(
        "/api/orgs", json={"name": "Northshore LC", "director_name": "Dir"}
    ).json()
    director = {"Authorization": f"Bearer {org['director']['token']}"}
    team = client.post("/api/teams", json={"name": "U15"}, headers=director).json()
    kid = client.post(
        "/api/athletes",
        json={"display_name": "Jordan P.", "birth_year": 2011,
              "dominant_hand": "right", "guardian_consent": True,
              "join_code": team["join_code"]},
        headers=director,
    ).json()
    invite = guardians_mod.create_invite(
        store.conn, kid["id"], store.authenticate(org["director"]["token"]).id)
    parent = guardians_mod.redeem_invite(
        store.conn, invite["code"], "Sam Pierce", "sam@example.com")
    guardians_mod.set_consent(
        store.conn, kid["id"], parent["guardian_id"],
        guardians_mod.Scope.PARTICIPATION, True)
    return {"store": store, "director": director, "kid": kid,
            "parent": {"Authorization": f"Bearer {parent['token']}"}}


def body(athlete_id, days=5, **kwargs):
    today = date.today()
    out = {
        "athlete_id": athlete_id,
        "starts_on": today.isoformat(),
        "ends_on": (today + timedelta(days=days)).isoformat(),
        "reason": "Family holiday",
    }
    out.update(kwargs)
    return out


class TestOverTheWire:
    def test_a_parent_can_book_one(self, client, wired):
        res = client.post("/api/absences", json=body(wired["kid"]["id"]),
                          headers=wired["parent"])
        assert res.status_code == 201
        assert res.json()["days"] == 6

    def test_a_coach_can_book_one(self, client, wired):
        assert client.post("/api/absences", json=body(wired["kid"]["id"]),
                           headers=wired["director"]).status_code == 201

    def test_the_athlete_cannot_book_their_own(self, client, wired):
        """A streak with an undo button is not a streak."""
        headers = {"Authorization": f"Bearer {wired['kid']['token']}"}
        res = client.post("/api/absences", json=body(wired["kid"]["id"]),
                          headers=headers)
        assert res.status_code == 403
        assert "a parent or your coach" in res.json()["detail"]

    def test_but_the_athlete_can_see_theirs(self, client, wired):
        """They should know their streak is safe. They just cannot set it."""
        client.post("/api/absences", json=body(wired["kid"]["id"]),
                    headers=wired["parent"])
        headers = {"Authorization": f"Bearer {wired['kid']['token']}"}
        seen = client.get(f"/api/absences?athlete_id={wired['kid']['id']}",
                          headers=headers).json()
        assert len(seen["absences"]) == 1
        assert seen["current"] is not None

    def test_an_athlete_cannot_read_a_teammates(self, client, wired):
        """Whether a teammate is on holiday is that family's business."""
        headers = {"Authorization": f"Bearer {wired['kid']['token']}"}
        assert client.get(
            f"/api/absences?athlete_id={wired['kid']['id'] + 1}",
            headers=headers,
        ).status_code == 403

    def test_another_program_cannot_book_one(self, client, wired):
        other = client.post(
            "/api/orgs", json={"name": "Southside", "director_name": "Other"}
        ).json()
        headers = {"Authorization": f"Bearer {other['director']['token']}"}
        assert client.post("/api/absences", json=body(wired["kid"]["id"]),
                           headers=headers).status_code == 404

    def test_a_bad_window_comes_back_readable(self, client, wired):
        res = client.post("/api/absences",
                          json=body(wired["kid"]["id"], days=60),
                          headers=wired["parent"])
        assert res.status_code == 400
        assert "longer than a pause" in res.json()["detail"]

    def test_a_parent_can_cancel(self, client, wired):
        booked = client.post("/api/absences", json=body(wired["kid"]["id"]),
                             headers=wired["parent"]).json()
        assert client.delete(
            f"/api/absences/{booked['id']}?athlete_id={wired['kid']['id']}",
            headers=wired["parent"],
        ).json()["removed"] is True
