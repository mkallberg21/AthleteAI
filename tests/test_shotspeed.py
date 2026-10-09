"""Approximate lacrosse shot speed: the server's own check, and who may see it.

Speed is worked out here from the raw release and impact times the phone sent,
never taken from a number the phone computed. It is shown to the athlete,
their parent and their coach, and to nobody else -- no leaderboard, no team
listing. Every one of those boundaries is tested below.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import shotspeed
from offdays.db import connect
from offdays.drills import DRILLS_BY_KEY
from offdays.store import Store

EIGHT_YD_M = 8 * shotspeed.YD_TO_M


def heard_at(release: float, mph: float, metres: float = EIGHT_YD_M) -> float:
    flight = metres / (mph / shotspeed.MS_TO_MPH) * 1000
    back = metres / shotspeed.SPEED_OF_SOUND_MS * 1000
    return release + flight + back


class TestTheMaths:
    def test_a_known_shot_reads_back_its_own_speed(self):
        assert shotspeed.speed_mph(1000, heard_at(1000, 60), 8) == pytest.approx(60, abs=0.2)

    def test_matches_the_phone_on_the_same_case(self):
        """tests/js/shotspeed.test.mjs asserts 60 mph for this exact shot too;
        the two implementations must not drift apart."""
        assert round(shotspeed.speed_mph(1000, heard_at(1000, 60), 8)) == 60

    @pytest.mark.parametrize("release,impact", [(1000, 1010), (1000, 900), (1000, 4000)])
    def test_impossible_flights_give_nothing(self, release, impact):
        assert shotspeed.speed_mph(release, impact, 8) is None


class TestTheReport:
    LIMITS = dict(min_distance_yd=7, max_distance_yd=15)

    def shots(self, speeds, hand="right"):
        out, t = [], 1000
        for mph in speeds:
            rep = {"hand": hand, "impact_t_ms": None, "release_t_ms": None}
            if mph is not None:
                rep["release_t_ms"] = t
                rep["impact_t_ms"] = heard_at(t, mph)
            out.append(rep)
            t += 5000
        return out

    def test_typical_and_best(self):
        r = shotspeed.analyze(self.shots([50, 55, 60, 52]), 8, **self.LIMITS)
        assert r.timed == 4 and r.shots == 4
        assert r.best_mph == pytest.approx(60, abs=0.2)
        assert r.median_mph == pytest.approx(53.5, abs=0.3)
        assert "Compare it with your own" in r.note

    def test_untimed_shots_still_count_as_shots(self):
        r = shotspeed.analyze(self.shots([50, None, 55, None, 58]), 8, **self.LIMITS)
        assert r.shots == 5 and r.timed == 3
        assert r.speeds[1] is None

    def test_no_distance_means_no_speed_and_says_why(self):
        r = shotspeed.analyze(self.shots([50, 55, 60]), None, **self.LIMITS)
        assert r.timed == 0 and r.median_mph is None
        assert "how far you shot from" in r.note

    def test_a_distance_outside_the_drills_range_is_refused(self):
        r = shotspeed.analyze(self.shots([50, 55, 60]), 40, **self.LIMITS)
        assert r.median_mph is None
        # Under 7 yards a hop of timing is too large a share of the flight.
        r = shotspeed.analyze(self.shots([50, 55, 60]), 5, **self.LIMITS)
        assert r.median_mph is None and "how far you shot from" in r.note

    def test_every_distance_from_seven_to_fifteen_yards_is_timed(self):
        for yd in (7, 8, 10, 12, 15):
            reps = self.shots([50, 55, 60], )
            # heard_at defaults to 8 yards; rebuild the impacts for this distance.
            for rep, mph in zip(reps, (50, 55, 60)):
                rep["impact_t_ms"] = heard_at(rep["release_t_ms"], mph, yd * shotspeed.YD_TO_M)
            r = shotspeed.analyze(reps, yd, **self.LIMITS)
            assert r.timed == 3, yd
            assert r.median_mph == pytest.approx(55, abs=0.3), yd

    def test_the_report_says_what_it_is_good_to_and_it_tightens_with_distance(self):
        """The same timing error is a bigger share of a short flight: 75 mph
        from 7 yards is about +-9 mph, from 15 about +-4."""
        near = shotspeed.precision_mph(7, 75)
        far = shotspeed.precision_mph(15, 75)
        assert near is not None and far is not None and near > far
        assert 7 <= near <= 11 and 3 <= far <= 5
        assert shotspeed.precision_mph(10, 45) < shotspeed.precision_mph(10, 75)
        reps = self.shots([70, 75, 80])
        for rep, mph in zip(reps, (70, 75, 80)):
            rep["impact_t_ms"] = heard_at(rep["release_t_ms"], mph, 7 * shotspeed.YD_TO_M)
        r = shotspeed.analyze(reps, 7, **self.LIMITS)
        assert r.plus_minus_mph == near
        assert "good to about" in r.note and "either way" in r.note
        assert r.to_dict()["plus_minus_mph"] == near

    def test_by_hand_only_with_enough_shots_each(self):
        reps = self.shots([50, 52, 54]) + self.shots([45, 47], hand="left")
        r = shotspeed.analyze(reps, 8, **self.LIMITS)
        assert "right" in r.by_hand and "left" not in r.by_hand

    def test_limits_ride_on_every_report(self):
        assert shotspeed.analyze([], 8, **self.LIMITS).to_dict()["limits"] == list(shotspeed.LIMITS)


class TestTheDrill:
    def test_shooting_is_clocked_lacrosse_counted_by_ear(self):
        d = DRILLS_BY_KEY["lax_shooting"]
        assert d.sport == "lacrosse" and d.shot is not None and d.sound is not None
        assert d.to_dict()["shot"]["default_distance_yd"] == 8
        assert d.shot.min_distance_yd == 7 and d.shot.max_distance_yd == 15

    def test_every_shot_counts_toward_the_throwing_ceiling(self):
        assert DRILLS_BY_KEY["lax_shooting"].load.throws_per_rep == 1.0


# ---------------------------------------------------------------------------
# Over the wire
# ---------------------------------------------------------------------------


@pytest.fixture
def club(tmp_path):
    store = Store(connect(tmp_path / "shots.db"))
    api_module._store = store
    org = store.create_org("Nashville Dogs", sport="lacrosse")
    director = store.create_user(org, "director", "Joel")
    coach = store.create_user(org, "coach", "Coach Tommy")
    other_coach = store.create_user(org, "coach", "Coach Mike")
    red = store.create_team(org, "2031 Red", "2026")
    blue = store.create_team(org, "2031 Blue", "2026")
    store.assign_staff_to_team(coach["id"], red["id"])
    store.assign_staff_to_team(other_coach["id"], blue["id"])
    kid = store.create_user(org, "athlete", "Scott", birth_year=2012, dominant_hand="right")
    other_kid = store.create_user(org, "athlete", "Sam", birth_year=2012, dominant_hand="left")
    store.join_team(red["join_code"], kid["id"])
    store.join_team(red["join_code"], other_kid["id"])
    from offdays import guardians
    invite = guardians.create_invite(store.conn, kid["id"], director["id"], "p@example.com")
    parent = guardians.redeem_invite(store.conn, invite["code"], "Travis")
    # A child with a linked parent trains only once that parent has said yes.
    guardians.set_consent(store.conn, kid["id"], parent["guardian_id"],
                          guardians.Scope.PARTICIPATION, True)
    client = TestClient(api_module.app)
    h = {
        "kid": {"Authorization": f"Bearer {kid['token']}"},
        "other_kid": {"Authorization": f"Bearer {other_kid['token']}"},
        "coach": {"Authorization": f"Bearer {coach['token']}"},
        "other_coach": {"Authorization": f"Bearer {other_coach['token']}"},
        "parent": {"Authorization": f"Bearer {parent['token']}"},
    }
    yield client, h, kid["id"]
    api_module._store = None


def shoot(client, headers, speeds, distance=8, forged=None):
    started = client.post("/api/sessions/start", json={"drill_key": "lax_shooting"},
                          headers=headers).json()
    reps, t = [], 2000
    for i, mph in enumerate(speeds):
        rep = {"t_ms": int(heard_at(t, mph)), "hand": "right", "confidence": 0.8,
               "source": "sound", "release_t_ms": t, "impact_t_ms": int(heard_at(t, mph))}
        if forged is not None:
            rep["speed"] = forged  # a client trying to report its own number
        reps.append(rep)
        t += 4000 + (i * 37) % 300
    res = client.post("/api/sessions/submit", headers=headers, json={
        "session_id": started["session_id"], "nonce": started["nonce"],
        "duration_ms": t + 1000, "reps": reps, "mean_confidence": 0.8,
        "shot_distance_yd": distance,
    })
    assert res.status_code == 200, res.text
    return res.json()


class TestOverTheWire:
    def test_the_athlete_gets_their_speeds_back(self, club):
        client, h, _ = club
        body = shoot(client, h["kid"], [48, 52, 55, 50, 53, 51])
        s = body["shot_speed"]
        assert s["timed"] == 6
        assert s["median_mph"] == pytest.approx(51.5, abs=0.5)
        assert s["best_mph"] == pytest.approx(55, abs=0.3)

    def test_the_server_ignores_any_speed_the_phone_sends(self, club):
        client, h, _ = club
        body = shoot(client, h["kid"], [48, 52, 55, 50, 53, 51], forged=99.0)
        assert body["shot_speed"]["best_mph"] < 60

    def test_history_for_the_athlete_their_parent_and_their_coach(self, club):
        client, h, kid_id = club
        shoot(client, h["kid"], [48, 52, 55, 50, 53, 51])
        mine = client.get("/api/me/shot-speed", headers=h["kid"]).json()["sessions"]
        assert len(mine) == 1 and mine[0]["median_mph"]
        parent = client.get(f"/api/parent/athletes/{kid_id}/shot-speed", headers=h["parent"])
        assert parent.status_code == 200 and parent.json()["sessions"] == mine
        coach = client.get(f"/api/coach/athletes/{kid_id}/shot-speed", headers=h["coach"])
        assert coach.status_code == 200 and coach.json()["sessions"] == mine

    def test_nobody_else_can_see_them(self, club):
        client, h, kid_id = club
        shoot(client, h["kid"], [48, 52, 55, 50, 53, 51])
        # A coach of another team.
        assert client.get(f"/api/coach/athletes/{kid_id}/shot-speed",
                          headers=h["other_coach"]).status_code == 403
        # Another child's parent route, and a teammate trying the parent route.
        assert client.get(f"/api/parent/athletes/{kid_id}/shot-speed",
                          headers=h["other_kid"]).status_code in (400, 403)

    def test_speed_is_on_no_leaderboard(self, club):
        client, h, _ = club
        shoot(client, h["kid"], [48, 52, 55, 50, 53, 51])
        for path in ("/api/leaderboard?window=week", "/api/standings?window=week"):
            r = client.get(path, headers=h["kid"])
            if r.status_code == 200:
                text = r.text.lower()
                assert "mph" not in text and "shot_speed" not in text, path


# ---------------------------------------------------------------------------
# Standing: an athlete's own percentile, and nothing about anyone else
# ---------------------------------------------------------------------------

TODAY = "2026-10-05"


@pytest.fixture
def squad(tmp_path):
    """A club with one team of N athletes, each given a recorded speed."""
    store = Store(connect(tmp_path / "standing.db"))
    org = store.create_org("Nashville Dogs", sport="lacrosse")
    team = store.create_team(org, "2031 Red", "2026")
    other = store.create_team(org, "2031 Blue", "2026")

    def add(speed, *, team_code=team["join_code"], birth_year=2012, day=TODAY):
        kid = store.create_user(org, "athlete", f"K{speed}", birth_year=birth_year)
        store.join_team(team_code, kid["id"])
        if speed is not None:
            sid = store.start_session(kid["id"], "lax_shooting")["session_id"]
            shotspeed.record(store.conn, sid, kid["id"], day, shotspeed.ShotReport(
                shots=6, timed=6, distance_yd=8, median_mph=float(speed)))
        return kid["id"]

    return store, add, other["join_code"]


class TestStanding:
    def test_middle_of_the_team(self, squad):
        store, add, _ = squad
        me = add(50)
        for v in (40, 45, 55, 60):
            add(v)
        s = shotspeed.standing(store.conn, me, TODAY)
        assert s["team"]["available"] is True
        assert s["team"]["percentile"] == 50
        assert s["speed_mph"] == 50

    def test_rounded_to_the_nearest_five(self, squad):
        store, add, _ = squad
        me = add(50)
        for v in (40, 45, 47, 55, 60, 62):  # 3 of 6 below -> 50%
            add(v)
        add(30)                               # 4 of 7 below -> 57.1% -> 55
        s = shotspeed.standing(store.conn, me, TODAY)
        assert s["team"]["percentile"] == 55

    def test_a_small_team_shows_nothing_and_says_how_many_more(self, squad):
        store, add, _ = squad
        me = add(50)
        for v in (40, 60, 45):  # 3 teammates: under the floor of 4
            add(v)
        s = shotspeed.standing(store.conn, me, TODAY)
        assert s["team"]["available"] is False
        assert "percentile" not in s["team"]
        assert s["team"]["peers"] == 3 and s["team"]["needed"] == shotspeed.MIN_TEAM_PEERS

    def test_teammates_without_a_speed_are_not_counted(self, squad):
        store, add, _ = squad
        me = add(50)
        for v in (40, 45, 55):
            add(v)
        add(None)
        add(None)
        assert shotspeed.standing(store.conn, me, TODAY)["team"]["peers"] == 3

    def test_another_teams_athletes_are_not_teammates(self, squad):
        store, add, blue = squad
        me = add(50)
        for v in (40, 45, 55, 60):
            add(v, team_code=blue)
        assert shotspeed.standing(store.conn, me, TODAY)["team"]["peers"] == 0

    def test_old_sessions_fall_out_of_the_window(self, squad):
        store, add, _ = squad
        me = add(50)
        for v in (40, 45, 55, 60):
            add(v, day="2026-07-01")
        assert shotspeed.standing(store.conn, me, TODAY)["team"]["peers"] == 0

    def test_best_session_counts_not_the_latest(self, squad):
        store, add, _ = squad
        me = add(50)
        sid = store.start_session(me, "lax_shooting")["session_id"]
        shotspeed.record(store.conn, sid, me, TODAY, shotspeed.ShotReport(
            shots=6, timed=6, distance_yd=8, median_mph=41.0))
        assert shotspeed.standing(store.conn, me, TODAY)["speed_mph"] == 50

    def test_no_speed_of_my_own_means_no_standing(self, squad):
        store, add, _ = squad
        me = add(None)
        for v in (40, 45, 55, 60):
            add(v)
        s = shotspeed.standing(store.conn, me, TODAY)
        assert s["speed_mph"] is None and s["team"]["available"] is False

    def test_nothing_about_anyone_else_is_returned(self, squad):
        """The whole payload is this athlete's own numbers and group sizes."""
        store, add, _ = squad
        me = add(50)
        others = [add(v) for v in (41.5, 46.5, 57.5, 61.5)]
        s = shotspeed.standing(store.conn, me, TODAY)
        text = repr(s)
        for v in ("41.5", "46.5", "57.5", "61.5"):
            assert v not in text
        for oid in others:
            assert f"K{oid}" not in text
        assert set(s) == {"window_days", "speed_mph", "team", "age"}

    def test_national_age_group_switches_itself_on(self, squad, monkeypatch):
        """Built now, shown only once enough same-age kids exist. Lowered here
        so the test does not need two hundred athletes."""
        store, add, blue = squad
        me = add(50, birth_year=2012)
        for v in (40, 45, 55):
            add(v, team_code=blue, birth_year=2012)   # same age, other team
        add(70, team_code=blue, birth_year=2010)      # older: not counted
        monkeypatch.setattr(shotspeed, "MIN_AGE_PEERS", 3)
        s = shotspeed.standing(store.conn, me, TODAY)
        assert s["age"]["birth_year"] == 2012
        assert s["age"]["peers"] == 3
        assert s["age"]["available"] is True and s["age"]["percentile"] == 65

    def test_national_age_group_stays_off_below_the_floor(self, squad):
        store, add, blue = squad
        me = add(50)
        for v in (40, 45, 55, 60):
            add(v, team_code=blue)
        s = shotspeed.standing(store.conn, me, TODAY)
        assert s["age"]["available"] is False and "percentile" not in s["age"]

    def test_a_held_session_does_not_count_until_approved(self, tmp_path):
        """Recorded at submit only when counted; review_session adds it."""
        store = Store(connect(tmp_path / "held.db"))
        org = store.create_org("X", sport="lacrosse")
        kid = store.create_user(org, "athlete", "K", birth_year=2012)
        sid = store.start_session(kid["id"], "lax_shooting")["session_id"]
        n = store.conn.execute("SELECT COUNT(*) FROM shot_speeds").fetchone()[0]
        assert n == 0 and sid

    def test_erasure_removes_the_speeds(self, squad):
        from offdays import guardians
        store, add, _ = squad
        me = add(50)
        guardians.erase_athlete(store.conn, me, "training_data")
        assert store.conn.execute(
            "SELECT COUNT(*) FROM shot_speeds WHERE athlete_id = ?", (me,)
        ).fetchone()[0] == 0


class TestStandingOverTheWire:
    def test_kid_parent_and_coach_all_get_the_same_standing(self, club):
        client, h, kid_id = club
        shoot(client, h["kid"], [48, 52, 55, 50, 53, 51])
        mine = client.get("/api/me/shot-speed", headers=h["kid"]).json()["standing"]
        parent = client.get(f"/api/parent/athletes/{kid_id}/shot-speed",
                            headers=h["parent"]).json()["standing"]
        coach = client.get(f"/api/coach/athletes/{kid_id}/shot-speed",
                           headers=h["coach"]).json()["standing"]
        assert mine == parent == coach
        assert mine["speed_mph"] is not None
        # One teammate on this club: far under the floor, so no percentile.
        assert mine["team"]["available"] is False

    def test_the_session_is_recorded_for_standing_when_counted(self, club):
        client, h, kid_id = club
        shoot(client, h["kid"], [48, 52, 55, 50, 53, 51])
        conn = api_module._store.conn
        row = conn.execute(
            "SELECT median_mph, timed FROM shot_speeds WHERE athlete_id = ?", (kid_id,)
        ).fetchone()
        assert row is not None and row["timed"] == 6
