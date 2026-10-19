"""Shooting distance from everything the phone has, and the server's say over it.

The scene is sent as numbers (goal size and place, torso, feet, tilt) and the
distance is worked out HERE, weighed factor by factor, with an error bar that
the speed inherits. The phone's own answer is never read. One case is pinned
against the JS copy so the two cannot drift.
"""
from __future__ import annotations

import random

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import distance, library, shotspeed
from offdays.db import connect
from offdays.store import Store

#: Pinned with tests/js/distance.test.mjs: same scene, same answer.
PARITY_SCENE = {
    "typed_yd": 10, "view_w": 720, "view_h": 1280,
    "goal": {"w": 0.24, "h": 0.22, "cx": 0.15, "base_y": 0.05, "seen": 40, "of": 50},
    "athlete": {"torso": 0.20, "cx": -0.3, "feet_y": 0.6}, "pitch_deg": 8,
}
PARITY_YD = 9.25
PARITY_PLUS_MINUS_YD = 0.81


class TestTheMaths:
    def test_matches_the_phone_on_the_pinned_scene(self):
        r = distance.estimate(PARITY_SCENE, 13)
        assert r.source == "camera+set"
        assert r.distance_yd == pytest.approx(PARITY_YD, abs=0.01)
        assert r.plus_minus_yd == pytest.approx(PARITY_PLUS_MINUS_YD, abs=0.01)

    def test_every_factor_is_listed_with_its_own_error(self):
        r = distance.estimate(PARITY_SCENE, 13)
        names = [f["name"] for f in r.factors]
        assert names == ["set", "goal width", "goal height", "shooter size", "placement", "ground plane", "camera"]
        assert all(f["plus_minus_yd"] > 0 for f in r.factors)

    def test_goal_width_alone_is_the_lens_times_six_feet(self):
        # 0.2 of the short side wide, default lens 1.15: 1.15 * 1.88m / 0.2
        r = distance.estimate({"view_w": 720, "view_h": 1280, "goal": {"w": 0.2, "seen": 5, "of": 5}})
        assert r.source == "camera"
        assert r.distance_yd == pytest.approx(1.15 * distance.GOAL_WIDTH_M / 0.2 * distance.YD_PER_M, abs=0.05)

    def test_no_goal_means_the_set_distance_about_a_yard(self):
        r = distance.estimate({"typed_yd": 8, "view_w": 720, "view_h": 1280, "goal": {"w": 0.02, "seen": 5, "of": 5}})
        assert r.source == "set"
        assert r.distance_yd == pytest.approx(8, abs=0.05)
        assert r.plus_minus_yd == pytest.approx(distance.TYPED_SIGMA_M * distance.YD_PER_M, abs=0.02)
        assert any(f["name"] == "goal width" and not f["used"] for f in r.factors)

    def test_a_goal_seen_too_rarely_is_not_trusted(self):
        r = distance.estimate({"typed_yd": 8, "view_w": 720, "view_h": 1280, "goal": {"w": 0.2, "seen": 2, "of": 50}})
        assert r.source == "set"

    def test_a_camera_that_disagrees_loses_to_the_pace_and_says_so(self):
        r = distance.estimate({"typed_yd": 7, "view_w": 720, "view_h": 1280, "goal": {"w": 0.12, "cx": 0, "seen": 50, "of": 50}})
        assert r.source == "set"
        assert r.distance_yd == pytest.approx(7, abs=0.05)
        assert "Check the spot" in r.note
        assert r.focal_hint is None
        assert not [f for f in r.factors if f["name"] == "camera"][0]["used"]

    def test_a_learned_lens_tightens_the_camera(self):
        loose = distance.estimate({"view_w": 720, "view_h": 1280, "goal": {"w": 0.2, "seen": 5, "of": 5}})
        tight = distance.estimate({"view_w": 720, "view_h": 1280, "goal": {"w": 0.2, "seen": 5, "of": 5}, "focal": 1.15})
        assert tight.focal_learned and not loose.focal_learned
        assert tight.plus_minus_yd < loose.plus_minus_yd

    def test_the_lens_hint_is_what_would_make_the_camera_match_the_pace(self):
        r = distance.estimate(PARITY_SCENE, 13)
        assert r.focal_hint is not None and distance.FOCAL_RANGE[0] < r.focal_hint < distance.FOCAL_RANGE[1]

    def test_learning_the_lens_is_slow_and_bounded(self):
        assert distance.learn_focal(None, 1.3) == 1.3
        assert distance.learn_focal(1.0, 1.4) == pytest.approx(1.1)
        assert distance.learn_focal(1.0, 9.0) == 1.0

    def test_unknown_age_takes_the_twelve_year_old_torso(self):
        assert distance.torso_for_age(None) == distance.torso_for_age(12)

    def test_nothing_at_all_is_nothing(self):
        r = distance.estimate(None)
        assert r.source == "none" and r.distance_yd is None


class TestSpeedCarriesTheDistanceError:
    def test_a_yard_in_eight_widens_the_speed(self):
        timing = shotspeed.precision_mph(8, 60)
        both = shotspeed.precision_with_distance(8, 60, 1.0)
        assert both > timing
        assert both == pytest.approx((timing ** 2 + (60 / 8) ** 2) ** 0.5, abs=0.1)

    def test_no_distance_error_is_the_timing_alone(self):
        assert shotspeed.precision_with_distance(8, 60, None) == shotspeed.precision_mph(8, 60)


@pytest.fixture
def club(tmp_path):
    store = Store(connect(tmp_path / "t.db"))
    api_module._store = store
    org = store.create_org("Nashville Dogs", sport="lacrosse")
    team = store.create_team(org, "2031 Red", "2026")
    library.set_team_drills(store.conn, org, "lacrosse", team["id"], ["lax_shooting"])
    kid = store.create_user(org, "athlete", "Scott", birth_year=2013, dominant_hand="right")
    store.join_team(team["join_code"], kid["id"])
    yield {"client": TestClient(api_module.app), "store": store,
           "kid": {"id": kid["id"], "h": {"Authorization": f"Bearer {kid['token']}"}}}
    api_module._store = None


def shoot(client, headers, typed_yd, scene, n=6, mph=60):
    s = client.post("/api/sessions/start", json={"drill_key": "lax_shooting"}, headers=headers).json()
    rng, t, reps = random.Random(n), 0, []
    metres = typed_yd * shotspeed.YD_TO_M
    for i in range(n):
        t += max(1500, int(rng.gauss(4000, 400)))
        flight = metres / (mph / shotspeed.MS_TO_MPH) * 1000
        back = metres / shotspeed.SPEED_OF_SOUND_MS * 1000
        reps.append({"t_ms": t, "hand": "right", "confidence": 0.9, "source": "sound",
                     "release_t_ms": t - int(flight + back), "impact_t_ms": t})
    body = {"session_id": s["session_id"], "nonce": s["nonce"], "duration_ms": t + 2000,
            "reps": reps, "mean_confidence": 0.9, "shot_distance_yd": typed_yd}
    if scene is not None:
        body["shot_scene"] = scene
    r = client.post("/api/sessions/submit", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


class TestOverTheWire:
    def test_the_scene_decides_the_distance_and_the_kid_sees_why(self, club):
        c, k = club["client"], club["kid"]
        scene = {k2: v for k2, v in PARITY_SCENE.items() if k2 != "typed_yd"}
        res = shoot(c, k["h"], 10, scene)
        speed = res["shot_speed"]
        assert speed["distance"]["source"] == "camera+set"
        assert speed["distance_yd"] == pytest.approx(PARITY_YD, abs=0.01)
        assert speed["distance"]["plus_minus_yd"] == pytest.approx(PARITY_PLUS_MINUS_YD, abs=0.01)
        assert [f["name"] for f in speed["distance"]["factors"]][:2] == ["set", "goal width"]
        # The speed is recomputed from the measured distance, not the typed one.
        assert speed["median_mph"] == pytest.approx(60 * PARITY_YD / 10, abs=1.0)
        assert "measured from the goal" in speed["note"]

    def test_no_scene_is_exactly_the_old_behaviour(self, club):
        c, k = club["client"], club["kid"]
        res = shoot(c, k["h"], 8, None)
        speed = res["shot_speed"]
        assert speed["distance_yd"] == 8
        assert speed["distance"]["source"] == "set"
        assert speed["median_mph"] == pytest.approx(60, abs=0.5)

    def test_the_lens_is_learned_only_when_camera_and_pace_agree(self, club):
        c, k, store = club["client"], club["kid"], club["store"]
        focal = lambda: store.conn.execute("SELECT camera_focal FROM users WHERE id=?", (k["id"],)).fetchone()[0]
        assert focal() is None
        # Disagreeing: goal reads 20 yd against a typed 7.
        shoot(c, k["h"], 7, {"view_w": 720, "view_h": 1280, "goal": {"w": 0.12, "cx": 0, "seen": 50, "of": 50}})
        assert focal() is None
        scene = {k2: v for k2, v in PARITY_SCENE.items() if k2 != "typed_yd"}
        shoot(c, k["h"], 10, scene)
        first = focal()
        assert first is not None and distance.FOCAL_RANGE[0] < first < distance.FOCAL_RANGE[1]
        res = shoot(c, k["h"], 10, scene)
        assert res["shot_speed"]["distance"]["focal_learned"] is True

    def test_a_scene_out_of_bounds_is_refused(self, club):
        c, k = club["client"], club["kid"]
        s = c.post("/api/sessions/start", json={"drill_key": "lax_shooting"}, headers=k["h"]).json()
        r = c.post("/api/sessions/submit", headers=k["h"], json={
            "session_id": s["session_id"], "nonce": s["nonce"], "duration_ms": 30000, "reps": [],
            "shot_distance_yd": 8, "shot_scene": {"view_w": 720, "view_h": 1280, "goal": {"w": 99}}})
        assert r.status_code == 422
