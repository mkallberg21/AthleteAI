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
from offdays.scoring import credit_reps, pool_cap, pool_members


WALL = DRILLS_BY_KEY["lax_wall_ball"]
STRONG = DRILLS_BY_KEY["lax_wall_ball_strong"]
GB = DRILLS_BY_KEY["lax_ground_ball"]


def seen(total, left=0, right=0):
    return IntegrityResult(score=1.0, status="counted",
                           reps_total=total, reps_left=left, reps_right=right)


class TestTheRule:
    def test_under_the_cap_every_rep_counts(self):
        c = credit_reps(seen(300, 150, 150), WALL,
                        drill_reps_today=0, pool_reps_today=0, pool_budget=800)
        assert (c.total, c.left, c.right) == (300, 150, 150)
        assert not c.capped and c.cap_scope is None

    def test_a_half_hour_of_wall_ball_counts_the_cap_and_no_more(self):
        c = credit_reps(seen(1_800, 900, 900), WALL,
                        drill_reps_today=0, pool_reps_today=0, pool_budget=800)
        assert c.total == 800 and c.seen_total == 1_800
        assert c.capped and c.cap_scope == "drill" and c.cap == 800

    def test_the_budget_is_spent_across_the_day_not_per_session(self):
        c = credit_reps(seen(500), WALL,
                        drill_reps_today=600, pool_reps_today=600, pool_budget=800)
        assert c.total == 200

    def test_a_day_already_full_credits_nothing(self):
        c = credit_reps(seen(300), WALL,
                        drill_reps_today=800, pool_reps_today=800, pool_budget=800)
        assert c.total == 0 and c.left == 0 and c.right == 0

    def test_hands_scale_together_so_the_weak_side_share_holds(self):
        c = credit_reps(seen(1_000, 400, 600), WALL,
                        drill_reps_today=0, pool_reps_today=0, pool_budget=800)
        assert c.total == 800
        assert c.left + c.right <= 800
        assert abs(c.left / 800 - 0.4) < 0.01

    def test_the_pool_binds_when_variants_are_used_to_dodge_the_drill_cap(self):
        # 600 plain wall ball already today; strong-hand has 600 of its own
        # but the pool has only 200 left.
        c = credit_reps(seen(500), STRONG,
                        drill_reps_today=0, pool_reps_today=600, pool_budget=800)
        assert c.total == 200 and c.cap_scope == "pool" and c.cap == 800

    def test_a_drill_outside_the_pool_is_its_own_budget(self):
        assert pool_members(GB, ALL_DRILLS) == (GB,)
        assert pool_cap(GB, ALL_DRILLS) == GB.scoring.daily_rep_cap


class TestTheCatalog:
    def test_every_wall_ball_variant_and_quick_stick_share_one_budget(self):
        pooled = {d.key for d in pool_members(WALL, ALL_DRILLS)}
        assert pooled == {
            "lax_wall_ball", "lax_quick_stick", "lax_wall_ball_strong",
            "lax_wall_ball_offhand", "lax_wall_ball_one_hand", "lax_wall_ball_cross",
            "lax_wall_ball_btb", "lax_wall_ball_split",
        }
        assert pool_cap(WALL, ALL_DRILLS) == 800

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
                            ["lax_wall_ball", "lax_wall_ball_strong", "lax_ground_ball"])
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
        assert body["reps_total"] == 800
        assert body["rep_cap"] == {"seen": 1_800, "credited": 800, "cap": 800, "scope": "drill"}
        assert any("800" in n and "count toward today" in n for n in body["notes"])

        board = c.get("/api/leaderboard?board=reps&window=week", headers=hero["h"]).json()
        rows = {r["athlete_id"]: r["value"] for r in board["rows"]}
        assert rows[hero["id"]] == 800

    def test_the_table_keeps_both_numbers(self, club):
        c, hero = club["client"], club["kids"]["Hero"]
        body = _submit(c, hero["h"], "lax_wall_ball", 1_000)
        row = club["store"].conn.execute(
            "SELECT reps_total, reps_seen, reps_left, reps_right FROM sessions WHERE id=?",
            (body["session_id"],)).fetchone()
        assert row["reps_seen"] == 1_000 and row["reps_total"] == 800
        assert row["reps_left"] + row["reps_right"] <= 800

    def test_an_ordinary_session_is_untouched(self, club):
        c, kid = club["client"], club["kids"]["Steady"]
        body = _submit(c, kid["h"], "lax_wall_ball", 300)
        assert body["reps_total"] == body["reps_seen"] == 300
        assert "rep_cap" not in body
        assert not any("count toward today" in n for n in body["notes"])

    def test_the_budget_runs_across_sessions_in_a_day(self, club):
        c, hero = club["client"], club["kids"]["Hero"]
        first = _submit(c, hero["h"], "lax_wall_ball", 600)
        second = _submit(c, hero["h"], "lax_wall_ball", 600)
        assert first["reps_total"] == 600
        assert second["reps_total"] == 200 and second["reps_seen"] == 600

    def test_switching_variants_does_not_reopen_the_budget(self, club):
        c, hero = club["client"], club["kids"]["Hero"]
        _submit(c, hero["h"], "lax_wall_ball", 800)
        strong = _submit(c, hero["h"], "lax_wall_ball_strong", 400)
        assert strong["reps_total"] == 0
        assert strong["rep_cap"]["scope"] == "pool"
        assert strong["xp_awarded"] == 0

    def test_a_different_drill_has_its_own_budget(self, club):
        c, hero = club["client"], club["kids"]["Hero"]
        _submit(c, hero["h"], "lax_wall_ball", 800)
        gb = _submit(c, hero["h"], "lax_ground_ball", 100)
        assert gb["reps_total"] == 100

    def test_xp_is_for_the_reps_that_counted(self, club):
        c, hero, steady = club["client"], club["kids"]["Hero"], club["kids"]["Steady"]
        a = _submit(c, hero["h"], "lax_wall_ball", 800)
        b = _submit(c, hero["h"], "lax_wall_ball", 800)
        assert b["xp_awarded"] == 0
        assert a["xp_awarded"] > 0

    def test_the_hero_cannot_blow_away_a_steady_teammate_by_volume(self, club):
        """The point of the whole thing: 1,800 reps in a day lands at 800 on
        the board, within reach of a teammate who did two honest sessions."""
        c, hero, steady = club["client"], club["kids"]["Hero"], club["kids"]["Steady"]
        _submit(c, hero["h"], "lax_wall_ball", 1_800)
        _submit(c, steady["h"], "lax_wall_ball", 350)
        _submit(c, steady["h"], "lax_wall_ball", 350)
        board = c.get("/api/leaderboard?board=reps&window=week", headers=hero["h"]).json()
        rows = {r["athlete_id"]: r["value"] for r in board["rows"]}
        assert rows[hero["id"]] == 800
        assert rows[steady["id"]] == 700
