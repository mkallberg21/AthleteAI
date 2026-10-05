"""The daily rep cap: what a day of reps can count for, whatever the camera saw.

The daily XP cap already stopped XP running away, but the rep boards, badges
and roster rollups all sum reps_total, so half an hour of wall ball still put
1,800 reps on the team board next to teammates' 300. Now reps_total is what
counted toward the day and reps_seen is what the camera counted.
"""

from __future__ import annotations

import pytest

from offdays.drills import ALL_DRILLS, DRILLS_BY_KEY
from offdays.drills.base import Metric
from offdays.integrity import IntegrityResult
from offdays.scoring import (credit_reps, daily_cap_for, pace_for_age, pool_cap,
                             pool_members)


WALL = DRILLS_BY_KEY["lax_wall_ball"]
STRONG = DRILLS_BY_KEY["lax_wall_ball_strong"]
OFFHAND = DRILLS_BY_KEY["lax_wall_ball_offhand"]
QUICK = DRILLS_BY_KEY["lax_quick_stick"]
GB = DRILLS_BY_KEY["lax_ground_ball"]


def seen(total, left=0, right=0):
    return IntegrityResult(score=1.0, status="counted",
                           reps_total=total, reps_left=left, reps_right=right)


class TestTheRule:
    def test_under_the_cap_every_rep_counts(self):
        c = credit_reps(seen(300, 150, 150), WALL,
                        drill_reps_today=0, pool_reps_today=0, pool_budget=500)
        assert (c.total, c.left, c.right) == (300, 150, 150)
        assert not c.capped and c.cap_scope is None

    def test_a_half_hour_of_wall_ball_counts_the_cap_and_no_more(self):
        c = credit_reps(seen(1_800, 900, 900), WALL,
                        drill_reps_today=0, pool_reps_today=0, pool_budget=500)
        assert c.total == 500 and c.seen_total == 1_800
        assert c.capped and c.cap_scope == "drill" and c.cap == 500

    def test_the_budget_is_spent_across_the_day_not_per_session(self):
        c = credit_reps(seen(500), WALL,
                        drill_reps_today=300, pool_reps_today=300, pool_budget=500)
        assert c.total == 200

    def test_a_day_already_full_credits_nothing(self):
        c = credit_reps(seen(300), WALL,
                        drill_reps_today=500, pool_reps_today=500, pool_budget=500)
        assert c.total == 0 and c.left == 0 and c.right == 0

    def test_hands_scale_together_so_the_weak_side_share_holds(self):
        c = credit_reps(seen(1_000, 400, 600), WALL,
                        drill_reps_today=0, pool_reps_today=0, pool_budget=500)
        assert c.total == 500
        assert c.left + c.right <= 500
        assert abs(c.left / 500 - 0.4) < 0.01

    def test_the_pool_binds_when_variants_are_used_to_dodge_the_drill_cap(self):
        # 300 plain wall ball already today; quick stick has 500 of its own
        # but the pool has only 200 left.
        c = credit_reps(seen(500), QUICK,
                        drill_reps_today=0, pool_reps_today=300, pool_budget=500)
        assert c.total == 200 and c.cap_scope == "pool" and c.cap == 500

    def test_a_drill_outside_the_pool_is_its_own_budget(self):
        assert pool_members(GB, ALL_DRILLS) == (GB,)
        assert pool_cap(GB, ALL_DRILLS) == GB.scoring.daily_rep_cap


class TestTheCatalog:
    def test_plain_wall_ball_quick_stick_and_the_trick_variants_share_one_budget(self):
        pooled = {d.key for d in pool_members(WALL, ALL_DRILLS)}
        assert pooled == {
            "lax_wall_ball", "lax_quick_stick", "lax_wall_ball_one_hand",
            "lax_wall_ball_cross", "lax_wall_ball_btb", "lax_wall_ball_split",
        }
        assert pool_cap(WALL, ALL_DRILLS) == 500

    def test_each_handed_wall_ball_drill_has_its_own_five_minute_day(self):
        """Both hands are wanted, so neither spends the other's budget, and
        neither is pooled with the trick variants."""
        for d in (STRONG, OFFHAND):
            assert d.scoring.cap_pool is None
            assert d.scoring.daily_cap_minutes == 5.0
            assert pool_members(d, ALL_DRILLS) == (d,)


class TestAgeAppropriate:
    def test_pace_rises_with_age_and_tops_out(self):
        assert pace_for_age(9) < pace_for_age(12) < pace_for_age(14) < pace_for_age(17)
        assert pace_for_age(17) == pace_for_age(30)

    def test_five_minutes_for_a_ten_year_old_is_about_150_reps(self):
        assert daily_cap_for(STRONG, 10) == 150

    def test_five_minutes_for_a_fourteen_year_old_is_about_220_reps(self):
        assert daily_cap_for(STRONG, 14) == 220

    def test_a_high_schooler_gets_the_full_300(self):
        assert daily_cap_for(STRONG, 17) == 300

    def test_an_unknown_or_estimated_age_takes_the_conservative_default(self):
        assert daily_cap_for(STRONG, None) == daily_cap_for(STRONG, 12)
        assert daily_cap_for(STRONG, 17, estimated=True) == daily_cap_for(STRONG, 12)

    def test_a_drill_without_a_minute_budget_keeps_its_flat_cap(self):
        assert daily_cap_for(WALL, 10) == WALL.scoring.daily_rep_cap
        assert daily_cap_for(GB, 17) == GB.scoring.daily_rep_cap

    def test_the_minute_budget_never_exceeds_the_flat_ceiling(self):
        for d in ALL_DRILLS:
            if d.scoring.daily_cap_minutes:
                for age in (8, 12, 15, 18, 25, None):
                    assert daily_cap_for(d, age) <= d.scoring.daily_rep_cap, d.key

    def test_a_pool_budget_is_never_below_any_member_cap(self):
        for d in ALL_DRILLS:
            if d.scoring.cap_pool:
                assert pool_cap(d, ALL_DRILLS) >= d.scoring.daily_rep_cap, d.key

    def test_every_rep_drill_has_a_finite_daily_cap(self):
        """1,000 is the ScoringSpec default; a drill left on it has not had
        its cap thought about, and a counted drill with no cap is the hole
        this test exists to keep shut."""
        for d in ALL_DRILLS:
            if d.metric is Metric.REPS:
                assert d.scoring.daily_rep_cap <= 1_500, d.key


# --------------------------------------------------------------------------
# Through the store: what lands in the table and on the board
# --------------------------------------------------------------------------

@pytest.fixture
def club(tmp_path):
    """Two teammates on one team, so the board has someone to compare."""
    from fastapi.testclient import TestClient
    import offdays.api as api_module
    from offdays.db import connect
    from offdays.store import Store

    store = Store(connect(tmp_path / "cap.db"))
    api_module._store = store
    org = store.create_org("Nashville Dogs", sport="lacrosse")
    team = store.create_team(org, "2031 Red", "2026")
    # The pool spans every wall-ball variant, so the team needs them turned on.
    from offdays import library
    library.set_team_drills(store.conn, org, "lacrosse", team["id"],
                            ["lax_wall_ball", "lax_quick_stick", "lax_wall_ball_strong",
                             "lax_wall_ball_offhand", "lax_ground_ball"])
    kids = {}
    for name in ("Hero", "Steady"):
        kid = store.create_user(org, "athlete", name, birth_year=2012, dominant_hand="right")
        store.join_team(team["join_code"], kid["id"])
        kids[name] = {"id": kid["id"], "h": {"Authorization": f"Bearer {kid['token']}"}}
    coach = store.create_user(org, "coach", "Coach")
    yield {
        "client": TestClient(api_module.app), "store": store, "org": org,
        "team": team, "kids": kids,
        "coach_h": {"Authorization": f"Bearer {coach['token']}"},
    }
    api_module._store = None


def _submit(client, headers, drill_key, reps):
    """Start and submit a rep session with a plausible rep stream."""
    import random
    r = client.post("/api/sessions/start", json={"drill_key": drill_key}, headers=headers)
    assert r.status_code in (200, 201), r.text
    body = r.json()
    rng = random.Random(reps)
    t, events = 0, []
    for i in range(reps):
        t += max(150, int(rng.gauss(880, 190)))
        events.append({"t_ms": t, "hand": "left" if i % 2 else "right", "confidence": 0.88})
    r = client.post("/api/sessions/submit", json={
        "session_id": body["session_id"], "nonce": body["nonce"],
        "duration_ms": t + 700, "reps": events, "mean_confidence": 0.88,
    }, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


class TestThroughTheStore:
    def test_a_marathon_counts_the_cap_and_the_board_shows_the_cap(self, club):
        c, hero = club["client"], club["kids"]["Hero"]
        body = _submit(c, hero["h"], "lax_wall_ball", 1_800)
        assert body["status"] == "counted", body["notes"]
        assert body["reps_seen"] == 1_800
        assert body["reps_total"] == 500
        assert body["rep_cap"] == {"seen": 1_800, "credited": 500, "cap": 500, "scope": "drill"}
        assert any("500" in n and "count toward today" in n for n in body["notes"])

        board = c.get("/api/leaderboard?board=reps&window=week", headers=hero["h"]).json()
        rows = {r["athlete_id"]: r["value"] for r in board["rows"]}
        assert rows[hero["id"]] == 500

    def test_the_table_keeps_both_numbers(self, club):
        c, hero = club["client"], club["kids"]["Hero"]
        body = _submit(c, hero["h"], "lax_wall_ball", 1_000)
        row = club["store"].conn.execute(
            "SELECT reps_total, reps_seen, reps_left, reps_right FROM sessions WHERE id=?",
            (body["session_id"],)).fetchone()
        assert row["reps_seen"] == 1_000 and row["reps_total"] == 500
        assert row["reps_left"] + row["reps_right"] <= 500

    def test_an_ordinary_session_is_untouched(self, club):
        c, kid = club["client"], club["kids"]["Steady"]
        body = _submit(c, kid["h"], "lax_wall_ball", 300)
        assert body["reps_total"] == body["reps_seen"] == 300
        assert "rep_cap" not in body
        assert not any("count toward today" in n for n in body["notes"])

    def test_the_budget_runs_across_sessions_in_a_day(self, club):
        c, hero = club["client"], club["kids"]["Hero"]
        first = _submit(c, hero["h"], "lax_wall_ball", 300)
        second = _submit(c, hero["h"], "lax_wall_ball", 300)
        assert first["reps_total"] == 300
        assert second["reps_total"] == 200 and second["reps_seen"] == 300

    def test_switching_variants_does_not_reopen_the_budget(self, club):
        c, hero = club["client"], club["kids"]["Hero"]
        _submit(c, hero["h"], "lax_wall_ball", 500)
        quick = _submit(c, hero["h"], "lax_quick_stick", 400)
        assert quick["reps_total"] == 0
        assert quick["rep_cap"]["scope"] == "pool"
        assert quick["xp_awarded"] == 0

    def test_a_2012_kid_gets_about_five_minutes_on_each_hand(self, club):
        """Born 2012 -> 14 this year -> 44 a minute -> 220 a day per hand.
        The off hand is its own budget, so a full strong-hand day leaves it
        untouched, and the note talks in minutes, not reps."""
        c, hero = club["client"], club["kids"]["Hero"]
        strong = _submit(c, hero["h"], "lax_wall_ball_strong", 400)
        assert strong["reps_total"] == 220 and strong["reps_seen"] == 400
        assert any("about 5 minutes of work for your age" in n for n in strong["notes"])
        off = _submit(c, hero["h"], "lax_wall_ball_offhand", 200)
        assert off["reps_total"] == 200 and "rep_cap" not in off

    def test_a_younger_kid_gets_a_smaller_day(self, club):
        c, store, hero = club["client"], club["store"], club["kids"]["Hero"]
        store.conn.execute("UPDATE users SET birth_year = 2016 WHERE id = ?", (hero["id"],))
        store.conn.commit()
        body = _submit(c, hero["h"], "lax_wall_ball_strong", 400)
        assert body["reps_total"] == 150

    def test_a_different_drill_has_its_own_budget(self, club):
        c, hero = club["client"], club["kids"]["Hero"]
        _submit(c, hero["h"], "lax_wall_ball", 500)
        gb = _submit(c, hero["h"], "lax_ground_ball", 100)
        assert gb["reps_total"] == 100

    def test_xp_is_for_the_reps_that_counted(self, club):
        c, hero, steady = club["client"], club["kids"]["Hero"], club["kids"]["Steady"]
        a = _submit(c, hero["h"], "lax_wall_ball", 500)
        b = _submit(c, hero["h"], "lax_wall_ball", 500)
        assert b["xp_awarded"] == 0
        assert a["xp_awarded"] > 0

    def test_the_hero_cannot_blow_away_a_steady_teammate_by_volume(self, club):
        """The point of the whole thing: 1,800 reps in a day lands at 500 on
        the board, within reach of a teammate who did two honest sessions."""
        c, hero, steady = club["client"], club["kids"]["Hero"], club["kids"]["Steady"]
        _submit(c, hero["h"], "lax_wall_ball", 1_800)
        _submit(c, steady["h"], "lax_wall_ball", 220)
        _submit(c, steady["h"], "lax_wall_ball", 220)
        board = c.get("/api/leaderboard?board=reps&window=week", headers=hero["h"]).json()
        rows = {r["athlete_id"]: r["value"] for r in board["rows"]}
        assert rows[hero["id"]] == 500
        assert rows[steady["id"]] == 440
