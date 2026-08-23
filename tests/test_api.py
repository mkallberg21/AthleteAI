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

    def test_resubmitting_replays_the_result_without_scoring_twice(self, client, program):
        """An offline client that never saw its ack will retry the same payload.

        Retrying has to be safe: the athlete gets their original result back,
        and the XP is awarded exactly once.
        """
        athlete = program["athletes"][0]
        headers = athlete["headers"]
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
        first = client.post("/api/sessions/submit", json=payload, headers=headers)
        assert first.status_code == 200

        second = client.post("/api/sessions/submit", json=payload, headers=headers)
        assert second.status_code == 200
        assert second.json()["xp_awarded"] == first.json()["xp_awarded"]
        assert second.json()["duplicate"] is True

        # The invariant that actually matters: scored once, not twice.
        profile = client.get("/api/me", headers=headers).json()
        assert profile["total_xp"] == first.json()["xp_awarded"]

    def test_a_replayed_payload_with_a_forged_nonce_is_refused(self, client, program):
        """Idempotency must not become a way to read another session's result."""
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
        client.post("/api/sessions/submit", json=payload, headers=headers)

        forged = {**payload, "nonce": "not-the-real-nonce"}
        res = client.post("/api/sessions/submit", json=forged, headers=headers)
        assert res.status_code == 400
        assert "nonce" in res.json()["detail"]

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


class TestAssignmentEndpoints:
    def _make(self, client, program, **kw):
        from datetime import date, timedelta

        today = date.today()
        body = {
            "team_id": program["team"]["id"],
            "drill_key": "lax_wall_ball",
            "title": "Week 1 Wall Ball",
            "starts_on": (today - timedelta(days=1)).isoformat(),
            "due_on": (today + timedelta(days=5)).isoformat(),
            "target_reps": 300,
            "target_sessions": 2,
            "min_offhand": 0.4,
        }
        body.update(kw)
        return client.post("/api/coach/assignments", json=body, headers=program["director"])

    def test_creating_an_assignment_notifies_the_team(self, client, program):
        res = self._make(client, program)
        assert res.status_code == 201
        assert res.json()["athletes_notified"] == 2

    def test_an_athlete_sees_their_assignment(self, client, program):
        self._make(client, program)
        items = client.get(
            "/api/assignments", headers=program["athletes"][0]["headers"]
        ).json()["assignments"]
        assert len(items) == 1
        assert items[0]["title"] == "Week 1 Wall Ball"
        assert items[0]["progress"]["complete"] is False

    def test_compliance_updates_as_work_lands(self, client, program):
        self._make(client, program, target_sessions=1, target_reps=100, min_offhand=0.0)
        do_session(client, program["athletes"][0]["headers"])
        row = client.get(
            "/api/coach/assignments", headers=program["director"]
        ).json()["assignments"][0]
        assert row["completed_count"] == 1
        assert row["athlete_count"] == 2

    def test_invalid_assignment_is_rejected_with_a_reason(self, client, program):
        res = self._make(client, program, target_reps=0, target_sessions=0, min_offhand=0.0)
        assert res.status_code == 400
        assert "target" in res.json()["detail"]

    def test_athletes_cannot_create_assignments(self, client, program):
        from datetime import date, timedelta

        today = date.today()
        res = client.post(
            "/api/coach/assignments",
            json={
                "team_id": program["team"]["id"], "drill_key": "lax_wall_ball",
                "title": "x", "starts_on": today.isoformat(),
                "due_on": (today + timedelta(days=1)).isoformat(), "target_reps": 10,
            },
            headers=program["athletes"][0]["headers"],
        )
        assert res.status_code == 403

    def test_a_coach_cannot_close_another_programs_assignment(self, client, program):
        aid = self._make(client, program).json()["assignment_id"]
        rival = client.post(
            "/api/orgs", json={"name": "Rival", "director_name": "Other"}
        ).json()
        rival_headers = {"Authorization": f"Bearer {rival['director']['token']}"}
        assert client.delete(f"/api/coach/assignments/{aid}", headers=rival_headers).status_code == 403

    def test_closing_removes_it_from_the_athlete_view(self, client, program):
        aid = self._make(client, program).json()["assignment_id"]
        client.delete(f"/api/coach/assignments/{aid}", headers=program["director"])
        items = client.get(
            "/api/assignments", headers=program["athletes"][0]["headers"]
        ).json()["assignments"]
        assert items == []


class TestNotificationEndpoints:
    def test_feed_starts_empty_and_fills(self, client, program):
        headers = program["athletes"][0]["headers"]
        assert client.get("/api/notifications", headers=headers).json()["unread"] == 0
        do_session(client, headers)  # earns badges, which notify
        data = client.get("/api/notifications", headers=headers).json()
        assert data["unread"] > 0

    def test_mark_all_read(self, client, program):
        headers = program["athletes"][0]["headers"]
        do_session(client, headers)
        client.post("/api/notifications/read", json={}, headers=headers)
        assert client.get("/api/notifications", headers=headers).json()["unread"] == 0

    def test_athletes_only_see_their_own_notifications(self, client, program):
        a, b = program["athletes"]
        do_session(client, a["headers"])
        assert client.get("/api/notifications", headers=b["headers"]).json()["unread"] == 0

    def test_push_subscription_is_accepted(self, client, program):
        res = client.post(
            "/api/notifications/subscribe",
            json={"endpoint": "https://push.example/1", "p256dh": "k", "auth": "a"},
            headers=program["athletes"][0]["headers"],
        )
        assert res.status_code == 201

    def test_vapid_key_endpoint_reports_unconfigured_cleanly(self, client):
        """No push credentials must be a clean empty answer, not an error."""
        res = client.get("/api/notifications/vapid-key")
        assert res.status_code == 200
        assert "public_key" in res.json()

    def test_broadcast_reaches_the_team(self, client, program):
        res = client.post(
            "/api/coach/broadcast",
            json={"team_id": program["team"]["id"], "title": "Practice at 6"},
            headers=program["director"],
        )
        assert res.json()["sent"] == 2

    def test_broadcast_to_another_program_is_refused(self, client, program):
        rival = client.post(
            "/api/orgs", json={"name": "Rival", "director_name": "Other"}
        ).json()
        rival_headers = {"Authorization": f"Bearer {rival['director']['token']}"}
        res = client.post(
            "/api/coach/broadcast",
            json={"team_id": program["team"]["id"], "title": "hi"},
            headers=rival_headers,
        )
        assert res.status_code == 403


class TestOfflineEndpoints:
    def test_reserve_returns_usable_slots(self, client, program):
        headers = program["athletes"][0]["headers"]
        res = client.post(
            "/api/sessions/reserve", json={"drill_key": "lax_wall_ball", "count": 3},
            headers=headers,
        )
        assert res.status_code == 201
        slots = res.json()["slots"]
        assert len(slots) == 3
        assert all(s["nonce"] and s["session_id"] for s in slots)

    def test_reserve_rejects_an_absurd_count(self, client, program):
        res = client.post(
            "/api/sessions/reserve", json={"drill_key": "lax_wall_ball", "count": 5_000},
            headers=program["athletes"][0]["headers"],
        )
        assert res.status_code == 422

    def test_a_reserved_slot_can_be_submitted_with_a_backdated_time(self, client, program):
        from datetime import datetime, timedelta, timezone

        headers = program["athletes"][0]["headers"]
        slot = client.post(
            "/api/sessions/reserve", json={"drill_key": "lax_wall_ball", "count": 1},
            headers=headers,
        ).json()["slots"][0]

        when = datetime.now(timezone.utc) - timedelta(days=2)
        res = client.post(
            "/api/sessions/submit",
            json={
                "session_id": slot["session_id"], "nonce": slot["nonce"],
                "duration_ms": 60_000,
                "reps": [{"t_ms": i * 900 + (i % 7) * 40, "hand": "left", "confidence": 0.9}
                         for i in range(1, 60)],
                "mean_confidence": 0.9,
                "completed_at": when.isoformat(),
            },
            headers=headers,
        )
        assert res.status_code == 200
        assert res.json()["counted_for_day"] == when.date().isoformat()


class TestQualityEndpoints:
    def _quality_session(self, client, headers, count=120, seed=5, offhand_penalty=0.0):
        """Submit a session carrying per-rep shape data."""
        import random

        started = client.post(
            "/api/sessions/start", json={"drill_key": "lax_wall_ball"}, headers=headers
        ).json()
        rng = random.Random(seed)
        t, reps = 0, []
        for i in range(count):
            hand = "left" if i % 2 else "right"
            rom = 0.47 * (1 + rng.gauss(0, 0.07))
            if hand == "left":
                rom *= 1 - offhand_penalty
            t += max(150, int(rng.gauss(880, 190)))
            reps.append({
                "t_ms": t, "hand": hand, "confidence": 0.9,
                "rom": round(max(0.01, rom), 3), "peak": round(rom * 0.7, 3),
                "cycle_ms": max(100, int(rng.gauss(880, 150))),
            })
        return client.post(
            "/api/sessions/submit",
            json={
                "session_id": started["session_id"], "nonce": started["nonce"],
                "duration_ms": t + 700, "reps": reps, "mean_confidence": 0.9,
            },
            headers=headers,
        )

    def test_submit_returns_a_form_score(self, client, program):
        res = self._quality_session(client, program["athletes"][0]["headers"]).json()
        assert res["status"] == "counted"
        quality = res["quality"]
        assert 0 <= quality["score"] <= 100
        assert len(quality["components"]) == 4
        assert quality["coaching_note"]

    def test_good_form_earns_a_bonus_and_bad_form_never_a_penalty(self, client, program):
        """The whole point of the bonus model: nobody loses XP for poor form."""
        res = self._quality_session(client, program["athletes"][0]["headers"]).json()
        labels = [line["label"] for line in res["xp_breakdown"]]
        assert any("form" in label.lower() for label in labels)
        assert all(line["amount"] >= 0 or "cap" in line["label"].lower()
                   for line in res["xp_breakdown"])

    def test_a_session_without_shape_data_still_counts(self, client, program):
        """Older clients report no range of motion; they must not be broken."""
        res = do_session(client, program["athletes"][0]["headers"]).json()
        assert res["status"] == "counted"
        assert res["xp_awarded"] > 0
        assert res["quality"]["score"] is None

    def test_the_off_hand_gap_reaches_the_athlete(self, client, program):
        res = self._quality_session(
            client, program["athletes"][0]["headers"], offhand_penalty=0.35
        ).json()
        assert "less range" in res["quality"]["coaching_note"]
        assert res["quality"]["offhand_rom_ratio"] < 0.8

    def test_session_quality_endpoint_returns_the_breakdown(self, client, program):
        athlete = program["athletes"][0]
        sid = self._quality_session(client, athlete["headers"]).json()["session_id"]
        res = client.get(f"/api/sessions/{sid}/quality", headers=athlete["headers"])
        assert res.status_code == 200
        assert res.json()["quality"]["score"] is not None

    def test_another_athlete_cannot_read_a_form_breakdown(self, client, program):
        a, b = program["athletes"]
        sid = self._quality_session(client, a["headers"]).json()["session_id"]
        assert client.get(f"/api/sessions/{sid}/quality", headers=b["headers"]).status_code == 403

    def test_a_coach_can_read_any_form_breakdown(self, client, program):
        sid = self._quality_session(
            client, program["athletes"][0]["headers"]
        ).json()["session_id"]
        res = client.get(f"/api/sessions/{sid}/quality", headers=program["director"])
        assert res.status_code == 200

    def test_the_profile_carries_a_form_trend(self, client, program):
        headers = program["athletes"][0]["headers"]
        for seed in range(3):
            self._quality_session(client, headers, seed=seed)
        profile = client.get("/api/me", headers=headers).json()
        assert profile["quality"]["current"] is not None
        assert profile["quality"]["samples"] == 3

    def test_the_form_leaderboard_needs_enough_sessions_to_qualify(self, client, program):
        """One tidy session must not out-rank a month of consistent work."""
        headers = program["athletes"][0]["headers"]
        self._quality_session(client, headers, seed=1)
        rows = client.get(
            "/api/leaderboard?board=quality&window=all", headers=program["director"]
        ).json()["rows"]
        assert rows == []

        for seed in (2, 3):
            self._quality_session(client, headers, seed=seed)
        rows = client.get(
            "/api/leaderboard?board=quality&window=all", headers=program["director"]
        ).json()["rows"]
        assert len(rows) == 1
        assert 0 < rows[0]["value"] <= 100

    def test_the_coach_roster_carries_a_form_column(self, client, program):
        headers = program["athletes"][0]["headers"]
        for seed in range(3):
            self._quality_session(client, headers, seed=seed)
        roster = client.get("/api/coach/roster", headers=program["director"]).json()["athletes"]
        scored = [a for a in roster if a["quality"] is not None]
        assert scored and 0 <= scored[0]["quality"] <= 100

    def test_fabricated_shape_data_is_held_for_review(self, client, program):
        """Identical range on every rep is a generated payload, not an athlete."""
        headers = program["athletes"][0]["headers"]
        started = client.post(
            "/api/sessions/start", json={"drill_key": "lax_wall_ball"}, headers=headers
        ).json()
        reps = [
            {"t_ms": i * 900 + (i % 7) * 40, "hand": "right", "confidence": 0.9,
             "rom": 0.47, "peak": 0.33, "cycle_ms": 880}
            for i in range(1, 80)
        ]
        res = client.post(
            "/api/sessions/submit",
            json={"session_id": started["session_id"], "nonce": started["nonce"],
                  "duration_ms": 80 * 900, "reps": reps, "mean_confidence": 0.9},
            headers=headers,
        ).json()
        assert res["status"] in ("review", "rejected")
        assert any("identical range" in note for note in res["notes"])
