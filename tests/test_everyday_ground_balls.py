"""Everyday Ground Balls: a timed footwork drill, and what it reports.

The touches are wrist and stick work one camera cannot see on the body, so
the drill times movement and reports direction changes and ground covered.
These tests hold that shape: no rep count, no throwing load, a movement card
on the result that says plainly what it does not measure, and client numbers
bounded rather than believed.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import movement
from offdays.db import connect
from offdays.drills import DRILLS_BY_KEY, Metric, SignalKind
from offdays.store import Store

KEY = "lax_ground_ball_everyday"


class TestTheDrill:
    def test_it_is_timed_not_counted(self):
        d = DRILLS_BY_KEY[KEY]
        assert d.metric is Metric.HOLD_SECONDS
        assert d.signal.kind is SignalKind.FOOTWORK_MOTION
        assert d.scoring.xp_per_minute > 0

    def test_it_never_counts_toward_the_throwing_ceiling(self):
        assert DRILLS_BY_KEY[KEY].load.throws_per_rep == 0

    def test_the_plain_ground_ball_drill_is_still_there(self):
        assert DRILLS_BY_KEY["lax_ground_ball"].metric is Metric.REPS

    def test_it_says_it_does_not_count_pickups(self):
        assert "not pickups" in DRILLS_BY_KEY[KEY].description


class TestTheSummary:
    def test_a_good_session(self):
        m = movement.summarise({"direction_changes": 18, "ground_torsos": 120},
                               hold_ms=170_000, duration_ms=180_000)
        assert m["moving_seconds"] == 170
        assert m["direction_changes"] == 18
        assert m["ground_yards"] == round(120 * movement.TORSO_YARDS)
        assert "direction changes" in m["note"]

    def test_standing_around_is_called_out(self):
        m = movement.summarise({"direction_changes": 2, "ground_torsos": 5},
                               hold_ms=60_000, duration_ms=180_000)
        assert "33%" in m["note"]

    def test_moving_but_never_turning_asks_for_more_directions(self):
        m = movement.summarise({"direction_changes": 1, "ground_torsos": 40},
                               hold_ms=170_000, duration_ms=180_000)
        assert "change direction more" in m["note"]

    def test_impossible_numbers_are_clipped_not_believed(self):
        m = movement.summarise({"direction_changes": 4000, "ground_torsos": 40_000},
                               hold_ms=60_000, duration_ms=60_000)
        assert m["direction_changes"] <= movement.MAX_CHANGES_PER_MINUTE + 1
        assert m["ground_yards"] <= round(movement.MAX_TORSOS_PER_MINUTE * movement.TORSO_YARDS)

    def test_no_footwork_payload_is_zero_not_an_error(self):
        m = movement.summarise(None, hold_ms=90_000, duration_ms=120_000)
        assert m["direction_changes"] == 0 and m["ground_yards"] == 0

    def test_limits_say_what_it_cannot_see(self):
        m = movement.summarise({}, hold_ms=0, duration_ms=0)
        assert any("cannot see the ball" in line for line in m["limits"])


@pytest.fixture
def athlete(tmp_path):
    store = Store(connect(tmp_path / "egb.db"))
    api_module._store = store
    org = store.create_org("Nashville Dogs", sport="lacrosse")
    team = store.create_team(org, "2031 Red", "2026")
    kid = store.create_user(org, "athlete", "Scott", birth_year=2012, dominant_hand="right")
    store.join_team(team["join_code"], kid["id"])
    yield TestClient(api_module.app), {"Authorization": f"Bearer {kid['token']}"}
    api_module._store = None


def submit(client, headers, *, hold_ms, duration_ms, footwork):
    started = client.post("/api/sessions/start", json={"drill_key": KEY},
                          headers=headers).json()
    res = client.post("/api/sessions/submit", headers=headers, json={
        "session_id": started["session_id"], "nonce": started["nonce"],
        "duration_ms": duration_ms, "reps": [], "hold_ms": hold_ms,
        "mean_confidence": 0.8, "footwork": footwork,
    })
    assert res.status_code == 200, res.text
    return res.json()


class TestOverTheWire:
    def test_a_three_minute_session_counts_and_carries_movement(self, athlete):
        client, h = athlete
        body = submit(client, h, hold_ms=165_000, duration_ms=180_000,
                      footwork={"direction_changes": 22, "ground_torsos": 140.5})
        assert body["status"] == "counted"
        assert body["xp_awarded"] > 0
        assert body["movement"]["direction_changes"] == 22
        assert body["movement"]["moving_seconds"] == 165

    def test_a_short_session_is_flagged_and_earns_little(self, athlete):
        """Under the minute minimum is noted, as for every timed drill, and
        the XP is per minute moving, so standing about earns nothing."""
        client, h = athlete
        short = submit(client, h, hold_ms=20_000, duration_ms=90_000,
                       footwork={"direction_changes": 2, "ground_torsos": 6})
        assert any("below the" in n for n in short["notes"])
        full = submit(client, h, hold_ms=165_000, duration_ms=180_000,
                      footwork={"direction_changes": 22, "ground_torsos": 140})
        assert short["xp_awarded"] < full["xp_awarded"] / 4

    def test_a_negative_or_absurd_payload_is_refused(self, athlete):
        client, h = athlete
        started = client.post("/api/sessions/start", json={"drill_key": KEY},
                              headers=h).json()
        res = client.post("/api/sessions/submit", headers=h, json={
            "session_id": started["session_id"], "nonce": started["nonce"],
            "duration_ms": 120_000, "reps": [], "hold_ms": 100_000,
            "mean_confidence": 0.8,
            "footwork": {"direction_changes": -3, "ground_torsos": 1e9},
        })
        assert res.status_code == 422
