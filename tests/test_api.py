"""End-to-end API behaviour: onboarding, capture, scoring, leaderboards, access control."""
from __future__ import annotations

import random

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

import athleteiq.api as api_module
from athleteiq.db import connect
from athleteiq.store import Store


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "test.db"))
    yield TestClient(api_module.app)
    api_module._store = None


@pytest.fixture
def program(client):
    """A program with a director, a team, and two athletes."""
    org = client.post(
        "/api/orgs", json={"name": "Northshore LC", "director_name": "Dir Smith"}
    ).json()
    director = {"Authorization": f"Bearer {org['director']['token']}"}
    team = client.post(
        "/api/teams", json={"name": "U15 Boys", "season": "2026"}, headers=director
    ).json()

    athletes = []
    for name, hand in (("Jordan P.", "right"), ("Sam R.", "left")):
        a = client.post(
            "/api/athletes",
            json={
                "display_name": name,
                "birth_year": 2011,
                "dominant_hand": hand,
                "guardian_consent": True,
                "join_code": team["join_code"],
            },
            headers=director,
        ).json()
        a["headers"] = {"Authorization": f"Bearer {a['token']}"}
        athletes.append(a)

    return {"org": org, "director": director, "team": team, "athletes": athletes}


def do_session(client, headers, drill="lax_wall_ball", count=120, seed=5, gap=880):
    """Record a realistic session through the real endpoints."""
    started = client.post("/api/sessions/start", json={"drill_key": drill}, headers=headers).json()
    rng = random.Random(seed)
    t, reps = 0, []
    for i in range(count):
        t += max(150, int(rng.gauss(gap, 200)))
        reps.append({"t_ms": t, "hand": "left" if i % 2 else "right", "confidence": 0.88})
    return client.post(
        "/api/sessions/submit",
        json={
            "session_id": started["session_id"],
            "nonce": started["nonce"],
            "duration_ms": t + 700,
            "reps": reps,
            "mean_confidence": 0.88,
        },
        headers=headers,
    )


class TestReference:
    def test_health(self, client):
        assert client.get("/api/health").json()["status"] == "ok"

    def test_drill_catalog_is_served_with_counting_specs(self, client):
        drills = client.get("/api/drills").json()["drills"]
        assert len(drills) >= 10
        for d in drills:
            assert d["signal"]["kind"], f"{d['key']} has no signal kind"
            assert d["counter"]["down_threshold"] < d["counter"]["up_threshold"]

    def test_unknown_drill_is_404(self, client):
        assert client.get("/api/drills/not_a_drill").status_code == 404


class TestAccessControl:
    def test_endpoints_require_a_token(self, client):
        for path in ("/api/me", "/api/leaderboard", "/api/coach/roster"):
            assert client.get(path).status_code == 401, path

    def test_a_bad_token_is_rejected(self, client):
        headers = {"Authorization": "Bearer not-a-real-token"}
        assert client.get("/api/me", headers=headers).status_code == 401

    def test_athletes_cannot_reach_coach_endpoints(self, client, program):
        headers = program["athletes"][0]["headers"]
        assert client.get("/api/coach/roster", headers=headers).status_code == 403
        assert client.get("/api/coach/review-queue", headers=headers).status_code == 403
        assert client.post("/api/teams", json={"name": "X"}, headers=headers).status_code == 403

    def test_an_athlete_cannot_read_another_athletes_profile(self, client, program):
        me, other = program["athletes"]
        res = client.get(f"/api/athletes/{other['id']}", headers=me["headers"])
        assert res.status_code == 403

    def test_a_coach_can_read_any_athlete_profile(self, client, program):
        athlete = program["athletes"][0]
        res = client.get(f"/api/athletes/{athlete['id']}", headers=program["director"])
        assert res.status_code == 200

    def test_programs_are_isolated_from_each_other(self, client, program):
        """An athlete in one program must never appear in another's leaderboard."""
        other = client.post(
            "/api/orgs", json={"name": "Rival LC", "director_name": "Other Dir"}
        ).json()
        other_dir = {"Authorization": f"Bearer {other['director']['token']}"}
        do_session(client, program["athletes"][0]["headers"])

        rows = client.get("/api/leaderboard?window=all", headers=other_dir).json()["rows"]
        assert rows == []
        roster = client.get("/api/coach/roster", headers=other_dir).json()["athletes"]
        assert roster == []


class TestCaptureFlow:
    def test_a_session_counts_and_awards_xp(self, client, program):
        res = do_session(client, program["athletes"][0]["headers"]).json()
        assert res["status"] == "counted"
        assert res["xp_awarded"] > 0
        assert res["reps_total"] == 120

    def test_first_session_awards_badges(self, client, program):
        res = do_session(client, program["athletes"][0]["headers"]).json()
        keys = {b["key"] for b in res["new_badges"]}
        assert "first_session" in keys

    def test_a_session_cannot_be_submitted_twice(self, client, program):
        """Replaying a captured payload must not double-score."""
        headers = program["athletes"][0]["headers"]
        started = client.post(
            "/api/sessions/start", json={"drill_key": "lax_wall_ball"}, headers=headers
        ).json()
        payload = {
            "session_id": started["session_id"],
            "nonce": started["nonce"],
            "duration_ms": 60_000,
            "reps": [{"t_ms": i * 900 + (i % 7) * 40, "hand": "right", "confidence": 0.9}
                     for i in range(1, 60)],
            "mean_confidence": 0.9,
        }
        assert client.post("/api/sessions/submit", json=payload, headers=headers).status_code == 200
        second = client.post("/api/sessions/submit", json=payload, headers=headers)
        assert second.status_code == 400
        assert "already been submitted" in second.json()["detail"]

    def test_a_wrong_nonce_is_rejected(self, client, program):
        headers = program["athletes"][0]["headers"]
        started = client.post(
            "/api/sessions/start", json={"drill_key": "lax_wall_ball"}, headers=headers
        ).json()
        res = client.post(
            "/api/sessions/submit",
            json={
                "session_id": started["session_id"],
                "nonce": "wrong-nonce",
                "duration_ms": 60_000,
                "reps": [],
                "mean_confidence": 0.9,
            },
            headers=headers,
        )
        assert res.status_code == 400

    def test_an_athlete_cannot_submit_another_athletes_session(self, client, program):
        owner, attacker = program["athletes"]
        started = client.post(
            "/api/sessions/start", json={"drill_key": "lax_wall_ball"}, headers=owner["headers"]
        ).json()
        res = client.post(
            "/api/sessions/submit",
            json={
                "session_id": started["session_id"],
                "nonce": started["nonce"],
                "duration_ms": 60_000,
                "reps": [],
                "mean_confidence": 0.9,
            },
            headers=attacker["headers"],
        )
        assert res.status_code == 400

    def test_starting_an_unknown_drill_fails(self, client, program):
        res = client.post(
            "/api/sessions/start",
            json={"drill_key": "made_up"},
            headers=program["athletes"][0]["headers"],
        )
        assert res.status_code == 400

    def test_an_oversized_rep_list_is_refused(self, client, program):
        """A hostile client must not be able to post an unbounded payload."""
        headers = program["athletes"][0]["headers"]
        started = client.post(
            "/api/sessions/start", json={"drill_key": "lax_wall_ball"}, headers=headers
        ).json()
        res = client.post(
            "/api/sessions/submit",
            json={
                "session_id": started["session_id"],
                "nonce": started["nonce"],
                "duration_ms": 60_000,
                "reps": [{"t_ms": i, "hand": "right", "confidence": 0.9} for i in range(25_000)],
                "mean_confidence": 0.9,
            },
            headers=headers,
        )
        assert res.status_code == 422

    def test_profile_reflects_completed_work(self, client, program):
        athlete = program["athletes"][0]
        do_session(client, athlete["headers"])
        profile = client.get("/api/me", headers=athlete["headers"]).json()
        assert profile["total_xp"] > 0
        assert profile["streak"] == 1
        assert profile["stats"]["wall_ball_reps"] == 120
        assert len(profile["recent_sessions"]) == 1


class TestLeaderboards:
    def test_ranking_orders_by_value(self, client, program):
        a, b = program["athletes"]
        do_session(client, a["headers"], count=200, seed=1)
        do_session(client, b["headers"], count=40, seed=2)

        rows = client.get("/api/leaderboard?window=all", headers=program["director"]).json()["rows"]
        assert len(rows) == 2
        assert rows[0]["value"] >= rows[1]["value"]
        assert rows[0]["rank"] == 1

    @pytest.mark.parametrize("board", ["xp", "offhand", "streak", "reps", "improvement"])
    def test_every_board_returns_well_formed_rows(self, client, program, board):
        do_session(client, program["athletes"][0]["headers"])
        rows = client.get(
            f"/api/leaderboard?board={board}&window=all", headers=program["director"]
        ).json()["rows"]
        for row in rows:
            assert {"rank", "athlete_id", "display_name", "value", "level"} <= row.keys()

    def test_offhand_board_credits_the_correct_side_per_athlete(self, client, program):
        """A lefty and a righty doing identical work must score differently here."""
        righty, lefty = program["athletes"]
        do_session(client, righty["headers"], seed=3)
        do_session(client, lefty["headers"], seed=3)
        rows = client.get(
            "/api/leaderboard?board=offhand&window=all", headers=program["director"]
        ).json()["rows"]
        assert len(rows) == 2
        assert all(r["value"] > 0 for r in rows)

    def test_team_standings_rank_by_per_athlete_average(self, client, program):
        do_session(client, program["athletes"][0]["headers"])
        teams = client.get("/api/standings?window=all", headers=program["director"]).json()["teams"]
        assert teams
        team = teams[0]
        assert team["roster"] == 2
        assert team["xp_per_athlete"] == pytest.approx(team["total_xp"] / team["roster"], rel=0.02)

    def test_a_minor_without_consent_is_not_named_on_the_leaderboard(self, client, program):
        from datetime import datetime, timezone

        minor = client.post(
            "/api/athletes",
            json={
                "display_name": "Alex Kowalczyk",
                "birth_year": datetime.now(timezone.utc).year - 13,
                "dominant_hand": "right",
                "guardian_consent": False,
                "join_code": program["team"]["join_code"],
            },
            headers=program["director"],
        ).json()
        do_session(client, {"Authorization": f"Bearer {minor['token']}"})

        rows = client.get(
            "/api/leaderboard?window=all", headers=program["director"]
        ).json()["rows"]
        names = [r["display_name"] for r in rows]
        # Their full name must not appear, but they must still be on the board
        # under a handle -- being unnamed is not the same as being excluded.
        assert "Alex Kowalczyk" not in names
        assert "Kowalczyk" not in " ".join(names)
        assert "Athlete A." in names

    def test_a_coach_still_sees_the_real_name_on_the_roster(self, client, program):
        """Withholding names on shared boards must not blind the responsible adult."""
        from datetime import datetime, timezone

        client.post(
            "/api/athletes",
            json={
                "display_name": "Alex Kowalczyk",
                "birth_year": datetime.now(timezone.utc).year - 13,
                "guardian_consent": False,
                "join_code": program["team"]["join_code"],
            },
            headers=program["director"],
        )
        roster = client.get("/api/coach/roster", headers=program["director"]).json()["athletes"]
        assert "Alex Kowalczyk" in [a["display_name"] for a in roster]


class TestCoachDashboard:
    def test_roster_flags_an_athlete_who_never_trained(self, client, program):
        roster = client.get("/api/coach/roster", headers=program["director"]).json()["athletes"]
        assert all("never_trained" in a["flags"] for a in roster)

    def test_an_active_athlete_is_not_flagged(self, client, program):
        athlete = program["athletes"][0]
        do_session(client, athlete["headers"])
        roster = client.get("/api/coach/roster", headers=program["director"]).json()["athletes"]
        row = next(a for a in roster if a["athlete_id"] == athlete["id"])
        assert "never_trained" not in row["flags"]
        assert row["window_sessions"] == 1

    def test_review_queue_holds_suspicious_sessions_with_reasons(self, client, program):
        headers = program["athletes"][0]["headers"]
        started = client.post(
            "/api/sessions/start", json={"drill_key": "lax_wall_ball"}, headers=headers
        ).json()
        # Perfectly metronomic -- caught by the cadence check.
        client.post(
            "/api/sessions/submit",
            json={
                "session_id": started["session_id"],
                "nonce": started["nonce"],
                "duration_ms": 100 * 800,
                "reps": [{"t_ms": i * 800, "hand": "right", "confidence": 0.9} for i in range(1, 100)],
                "mean_confidence": 0.9,
            },
            headers=headers,
        )
        queue = client.get("/api/coach/review-queue", headers=program["director"]).json()["sessions"]
        assert len(queue) == 1
        assert queue[0]["integrity_notes"]

    def test_approving_a_held_session_credits_its_xp(self, client, program):
        headers = program["athletes"][0]["headers"]
        started = client.post(
            "/api/sessions/start", json={"drill_key": "lax_wall_ball"}, headers=headers
        ).json()
        client.post(
            "/api/sessions/submit",
            json={
                "session_id": started["session_id"],
                "nonce": started["nonce"],
                "duration_ms": 100 * 800,
                "reps": [{"t_ms": i * 800, "hand": "right", "confidence": 0.9} for i in range(1, 100)],
                "mean_confidence": 0.9,
            },
            headers=headers,
        )
        assert client.get("/api/me", headers=headers).json()["total_xp"] == 0

        sid = client.get("/api/coach/review-queue", headers=program["director"]).json()["sessions"][0]["id"]
        approved = client.post(
            f"/api/coach/review/{sid}", json={"approve": True}, headers=program["director"]
        ).json()
        assert approved["xp_awarded"] > 0
        assert client.get("/api/me", headers=headers).json()["total_xp"] > 0

    def test_rejecting_a_held_session_credits_nothing(self, client, program):
        headers = program["athletes"][0]["headers"]
        started = client.post(
            "/api/sessions/start", json={"drill_key": "lax_wall_ball"}, headers=headers
        ).json()
        client.post(
            "/api/sessions/submit",
            json={
                "session_id": started["session_id"],
                "nonce": started["nonce"],
                "duration_ms": 100 * 800,
                "reps": [{"t_ms": i * 800, "hand": "right", "confidence": 0.9} for i in range(1, 100)],
                "mean_confidence": 0.9,
            },
            headers=headers,
        )
        sid = client.get("/api/coach/review-queue", headers=program["director"]).json()["sessions"][0]["id"]
        client.post(f"/api/coach/review/{sid}", json={"approve": False}, headers=program["director"])
        assert client.get("/api/me", headers=headers).json()["total_xp"] == 0

    def test_a_coach_cannot_review_another_programs_session(self, client, program):
        headers = program["athletes"][0]["headers"]
        started = client.post(
            "/api/sessions/start", json={"drill_key": "lax_wall_ball"}, headers=headers
        ).json()
        client.post(
            "/api/sessions/submit",
            json={
                "session_id": started["session_id"],
                "nonce": started["nonce"],
                "duration_ms": 100 * 800,
                "reps": [{"t_ms": i * 800, "hand": "right", "confidence": 0.9} for i in range(1, 100)],
                "mean_confidence": 0.9,
            },
            headers=headers,
        )
        sid = client.get("/api/coach/review-queue", headers=program["director"]).json()["sessions"][0]["id"]

        rival = client.post(
            "/api/orgs", json={"name": "Rival LC", "director_name": "Other"}
        ).json()
        rival_headers = {"Authorization": f"Bearer {rival['director']['token']}"}
        res = client.post(f"/api/coach/review/{sid}", json={"approve": True}, headers=rival_headers)
        assert res.status_code == 403


class TestPrivacy:
    def test_no_endpoint_accepts_video_or_image_data(self, client):
        """The privacy promise has to be structural, not a policy note.

        Checks the actual request-body field names in the OpenAPI schema, not
        the prose -- the description is *supposed* to mention video.
        """
        schema = client.get("/openapi.json").json()
        banned = ("video", "image", "frame", "landmark", "photo", "media", "clip")

        field_names: list[str] = []
        for name, model in schema.get("components", {}).get("schemas", {}).items():
            for prop in (model.get("properties") or {}):
                field_names.append(f"{name}.{prop}")

        for field in field_names:
            lowered = field.lower()
            for term in banned:
                assert term not in lowered, f"request schema exposes {field!r}"

        # And no endpoint may accept a binary/multipart body at all.
        for path, methods in schema["paths"].items():
            for method, op in methods.items():
                content = (op.get("requestBody") or {}).get("content", {})
                for media_type in content:
                    assert media_type == "application/json", \
                        f"{method.upper()} {path} accepts {media_type}"

    def test_submissions_store_no_imagery(self, client, program):
        do_session(client, program["athletes"][0]["headers"])
        conn = api_module._store.conn
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )]
        for table in tables:
            cols = [r[1].lower() for r in conn.execute(f"PRAGMA table_info({table})")]
            for col in cols:
                assert not any(t in col for t in ("video", "image", "frame", "blob", "photo")), \
                    f"{table}.{col} looks like it stores imagery"
