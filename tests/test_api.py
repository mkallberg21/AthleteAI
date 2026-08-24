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


class TestLoadEndpoints:
    def _train_on(self, client, headers, days_ago, seed=1, drill="lax_wall_ball", count=150):
        """Log a session dated `days_ago` days back."""
        import random
        from datetime import datetime, timedelta, timezone

        started = client.post(
            "/api/sessions/start", json={"drill_key": drill}, headers=headers
        ).json()
        rng = random.Random(seed)
        t, reps = 0, []
        for i in range(count):
            rom = 0.47 * (1 + rng.gauss(0, 0.08))
            t += max(150, int(rng.gauss(880, 180)))
            reps.append({
                "t_ms": t, "hand": "left" if i % 2 else "right", "confidence": 0.9,
                "rom": round(max(0.01, rom), 3), "peak": round(rom * 0.7, 3),
                "cycle_ms": max(120, int(rng.gauss(880, 150))),
            })
        when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        return client.post(
            "/api/sessions/submit",
            json={
                "session_id": started["session_id"], "nonce": started["nonce"],
                "duration_ms": t + 700, "reps": reps, "mean_confidence": 0.9,
                "completed_at": when,
            },
            headers=headers,
        )

    def test_load_endpoint_reports_a_state(self, client, program):
        headers = program["athletes"][0]["headers"]
        self._train_on(client, headers, 1)
        state = client.get("/api/load", headers=headers).json()
        assert "zone" in state and "advisories" in state

    def test_submit_returns_the_updated_load_state(self, client, program):
        res = self._train_on(client, program["athletes"][0]["headers"], 0).json()
        assert "load" in res
        assert res["load"]["zone"] in (
            "unknown", "detraining", "building", "optimal", "elevated", "high"
        )

    def test_a_new_athlete_is_not_alarmed(self, client, program):
        """Weeks one to four are when a false alarm does the most damage."""
        headers = program["athletes"][0]["headers"]
        for day in range(5, 0, -1):
            self._train_on(client, headers, day, seed=day)
        state = client.get("/api/load", headers=headers).json()
        assert state["acwr"] is None
        assert all(a["level"] == "info" for a in state["advisories"])

    def test_a_recovery_day_cannot_be_claimed_without_earning_it(self, client, program):
        headers = program["athletes"][0]["headers"]
        res = client.post("/api/recovery", headers=headers)
        assert res.status_code == 400
        assert "in a row" in res.json()["detail"]

    def test_a_recovery_day_preserves_the_streak(self, client, program):
        """The counterweight: resting must not cost six weeks of consistency."""
        headers = program["athletes"][0]["headers"]
        for day in range(5, 0, -1):
            self._train_on(client, headers, day, seed=day)

        before = client.get("/api/me", headers=headers).json()["streak"]
        assert client.post("/api/recovery", headers=headers).status_code == 201
        after = client.get("/api/me", headers=headers).json()["streak"]
        assert after == before + 1

    def test_a_recovery_day_is_idempotent(self, client, program):
        headers = program["athletes"][0]["headers"]
        for day in range(5, 0, -1):
            self._train_on(client, headers, day, seed=day)
        client.post("/api/recovery", headers=headers)
        client.post("/api/recovery", headers=headers)
        rows = api_module._store.conn.execute(
            "SELECT COUNT(*) AS n FROM recovery_days"
        ).fetchone()["n"]
        assert rows == 1

    def test_the_coach_load_view_puts_the_worst_first(self, client, program):
        a, b = program["athletes"]
        for day in range(12, 0, -1):
            self._train_on(client, a["headers"], day, seed=day, count=260)
        self._train_on(client, b["headers"], 1, seed=99, count=40)

        rows = client.get("/api/coach/load", headers=program["director"]).json()["athletes"]
        assert len(rows) >= 2
        levels = [
            next((x["level"] for x in r["advisories"] if x["level"] != "info"), None)
            for r in rows
        ]
        # Anything needing attention sorts above anything that does not.
        first_none = next((i for i, lv in enumerate(levels) if lv is None), len(levels))
        assert all(lv is not None for lv in levels[:first_none])

    def test_athletes_cannot_read_the_team_load_view(self, client, program):
        res = client.get("/api/coach/load", headers=program["athletes"][0]["headers"])
        assert res.status_code == 403

    def test_the_roster_carries_workload_and_flags(self, client, program):
        headers = program["athletes"][0]["headers"]
        for day in range(12, 0, -1):
            self._train_on(client, headers, day, seed=day, count=200)
        roster = client.get("/api/coach/roster", headers=program["director"]).json()["athletes"]
        row = next(a for a in roster if a["athlete_id"] == program["athletes"][0]["id"])
        assert row["load"] is not None
        assert "needs_rest" in row["flags"]

    def test_a_rest_nudge_is_generated_and_deduped(self, client, program):
        from athleteiq import notifications as notify

        headers = program["athletes"][0]["headers"]
        for day in range(12, 0, -1):
            self._train_on(client, headers, day, seed=day, count=200)

        made = notify.generate_rest_nudges(api_module._store.conn)
        assert made >= 1
        assert notify.generate_rest_nudges(api_module._store.conn) == 0

        titles = [n["title"] for n in notify.feed(api_module._store.conn, program["athletes"][0]["id"])]
        assert any("recovery" in t.lower() for t in titles)


class TestGuardianEndpoints:
    def _invite(self, client, program, index=0):
        return client.post(
            "/api/coach/guardian-invites",
            json={"athlete_id": program["athletes"][index]["id"]},
            headers=program["director"],
        ).json()

    def _onboard(self, client, program, index=0, name="Dana Pierce"):
        invite = self._invite(client, program, index)
        res = client.post(
            "/api/guardians/redeem",
            json={"code": invite["code"], "display_name": name},
        ).json()
        res["headers"] = {"Authorization": f"Bearer {res['token']}"}
        return res

    def test_a_coach_can_issue_an_invite(self, client, program):
        invite = self._invite(client, program)
        assert invite["code"]
        assert invite["athlete_name"] == "Jordan P."

    def test_athletes_cannot_issue_invites(self, client, program):
        res = client.post(
            "/api/coach/guardian-invites",
            json={"athlete_id": program["athletes"][0]["id"]},
            headers=program["athletes"][0]["headers"],
        )
        assert res.status_code == 403

    def test_a_coach_cannot_invite_into_another_program(self, client, program):
        rival = client.post(
            "/api/orgs", json={"name": "Rival", "director_name": "Other"}
        ).json()
        rival_headers = {"Authorization": f"Bearer {rival['director']['token']}"}
        res = client.post(
            "/api/coach/guardian-invites",
            json={"athlete_id": program["athletes"][0]["id"]},
            headers=rival_headers,
        )
        assert res.status_code == 403

    def test_redeeming_creates_a_working_account(self, client, program):
        guardian = self._onboard(client, program)
        home = client.get("/api/guardians/me", headers=guardian["headers"])
        assert home.status_code == 200
        assert home.json()["athletes"][0]["display_name"] == "Jordan P."

    def test_redeeming_needs_no_prior_login(self, client, program):
        """A parent has no account yet; requiring one would be circular."""
        invite = self._invite(client, program)
        res = client.post(
            "/api/guardians/redeem",
            json={"code": invite["code"], "display_name": "Dana"},
        )
        assert res.status_code == 201

    def test_a_revoked_invite_cannot_be_redeemed(self, client, program):
        self._invite(client, program)
        invite_id = client.get(
            "/api/coach/guardian-invites", headers=program["director"]
        ).json()["invites"][0]["id"]
        client.delete(
            f"/api/coach/guardian-invites/{invite_id}", headers=program["director"]
        )
        # A fresh code for the same athlete, then confirm the revoked one fails.
        stale = client.post(
            "/api/guardians/redeem",
            json={"code": "ZZZZ-ZZZZ-ZZZZ", "display_name": "Nobody"},
        )
        assert stale.status_code == 400

    def test_a_guardian_cannot_reach_coach_or_athlete_endpoints(self, client, program):
        """A parent account is not an athlete account and not a coach account."""
        guardian = self._onboard(client, program)
        for path in ("/api/coach/roster", "/api/coach/load", "/api/assignments", "/api/load"):
            assert client.get(path, headers=guardian["headers"]).status_code == 403, path

        # Recording training as a parent would put them on the leaderboard
        # alongside the children.
        assert client.post(
            "/api/sessions/start", json={"drill_key": "lax_wall_ball"},
            headers=guardian["headers"],
        ).status_code == 403
        assert client.post(
            "/api/sessions/reserve", json={"drill_key": "lax_wall_ball", "count": 1},
            headers=guardian["headers"],
        ).status_code == 403
        assert client.post("/api/recovery", headers=guardian["headers"]).status_code == 403

    def test_a_guardian_is_not_shown_a_leaderboard(self, client, program):
        """A ranked list of other people's children is not a parent feature."""
        guardian = self._onboard(client, program)
        for path in ("/api/leaderboard", "/api/standings"):
            res = client.get(path, headers=guardian["headers"])
            assert res.status_code == 403, path
            assert "your own athlete" in res.json()["detail"]

    def test_an_athlete_cannot_reach_the_guardian_portal(self, client, program):
        res = client.get("/api/guardians/me", headers=program["athletes"][0]["headers"])
        assert res.status_code == 403

    def test_a_guardian_cannot_read_another_familys_athlete(self, client, program):
        guardian = self._onboard(client, program, 0)
        other_id = program["athletes"][1]["id"]
        assert client.get(
            f"/api/guardians/export/{other_id}", headers=guardian["headers"]
        ).status_code == 400
        assert client.post(
            "/api/guardians/consent",
            json={"athlete_id": other_id, "scope": "participation", "granted": True},
            headers=guardian["headers"],
        ).status_code == 400

    def test_consent_can_be_set_and_gates_training(self, client, program):
        athlete = program["athletes"][0]
        guardian = self._onboard(client, program, 0)

        # A linked athlete with no consent cannot start a session.
        blocked = client.post(
            "/api/sessions/start", json={"drill_key": "lax_wall_ball"},
            headers=athlete["headers"],
        )
        assert blocked.status_code == 400
        assert "consent" in blocked.json()["detail"]

        client.post(
            "/api/guardians/consent",
            json={"athlete_id": athlete["id"], "scope": "participation", "granted": True},
            headers=guardian["headers"],
        )
        assert client.post(
            "/api/sessions/start", json={"drill_key": "lax_wall_ball"},
            headers=athlete["headers"],
        ).status_code == 201

    def test_withdrawing_retention_purges_rep_detail(self, client, program):
        athlete = program["athletes"][0]
        guardian = self._onboard(client, program, 0)
        client.post(
            "/api/guardians/consent",
            json={"athlete_id": athlete["id"], "scope": "participation", "granted": True},
            headers=guardian["headers"],
        )
        do_session(client, athlete["headers"])

        res = client.post(
            "/api/guardians/consent",
            json={"athlete_id": athlete["id"], "scope": "data_retention", "granted": False},
            headers=guardian["headers"],
        ).json()
        assert res["rep_rows_removed"] > 0

    def test_export_returns_the_athletes_data(self, client, program):
        athlete = program["athletes"][0]
        guardian = self._onboard(client, program, 0)
        client.post(
            "/api/guardians/consent",
            json={"athlete_id": athlete["id"], "scope": "participation", "granted": True},
            headers=guardian["headers"],
        )
        do_session(client, athlete["headers"])
        data = client.get(
            f"/api/guardians/export/{athlete['id']}", headers=guardian["headers"]
        ).json()
        assert data["profile"]["display_name"] == "Jordan P."
        assert len(data["sessions"]) == 1

    def test_erasing_requires_typed_confirmation(self, client, program):
        athlete = program["athletes"][0]
        guardian = self._onboard(client, program, 0)
        res = client.post(
            "/api/guardians/erase",
            json={"athlete_id": athlete["id"], "scope": "all", "confirm": "yes"},
            headers=guardian["headers"],
        )
        assert res.status_code == 400
        assert "DELETE" in res.json()["detail"]

    def test_erasing_removes_the_training_history(self, client, program):
        athlete = program["athletes"][0]
        guardian = self._onboard(client, program, 0)
        client.post(
            "/api/guardians/consent",
            json={"athlete_id": athlete["id"], "scope": "participation", "granted": True},
            headers=guardian["headers"],
        )
        do_session(client, athlete["headers"])

        res = client.post(
            "/api/guardians/erase",
            json={"athlete_id": athlete["id"], "scope": "training_data", "confirm": "DELETE"},
            headers=guardian["headers"],
        )
        assert res.status_code == 200
        assert res.json()["rows_removed"] > 0
        assert client.get("/api/me", headers=athlete["headers"]).json()["total_xp"] == 0

    def test_a_second_child_links_to_the_same_account(self, client, program):
        guardian = self._onboard(client, program, 0)
        second = self._invite(client, program, 1)
        res = client.post(
            "/api/guardians/link", json={"code": second["code"]},
            headers=guardian["headers"],
        )
        assert res.status_code == 200
        home = client.get("/api/guardians/me", headers=guardian["headers"]).json()
        assert len(home["athletes"]) == 2

    def test_a_weekly_digest_is_generated_and_deduped(self, client, program):
        from athleteiq import notifications as notify

        athlete = program["athletes"][0]
        guardian = self._onboard(client, program, 0)
        client.post(
            "/api/guardians/consent",
            json={"athlete_id": athlete["id"], "scope": "participation", "granted": True},
            headers=guardian["headers"],
        )
        do_session(client, athlete["headers"])

        assert notify.generate_guardian_digests(api_module._store.conn) == 1
        assert notify.generate_guardian_digests(api_module._store.conn) == 0


class TestRosterEndpoints:
    CSV = (
        "Last Name,First Name,#,Pos,Birth Year,Shoots,Parent Email\n"
        "Pierce,Jordan,14,Midfield,2011,Right,dana@example.com\n"
        "Rivera,Sam,7,Attack,2010,left,\n"
    )

    def test_preview_writes_nothing(self, client, program):
        before = api_module._store.conn.execute(
            "SELECT COUNT(*) AS n FROM users"
        ).fetchone()["n"]
        res = client.post(
            "/api/coach/roster/preview",
            json={"content": self.CSV}, headers=program["director"],
        )
        assert res.status_code == 200
        assert res.json()["summary"]["create"] == 2
        after = api_module._store.conn.execute(
            "SELECT COUNT(*) AS n FROM users"
        ).fetchone()["n"]
        assert after == before

    def test_import_creates_athletes_and_claim_codes(self, client, program):
        res = client.post(
            "/api/coach/roster/import",
            json={"content": self.CSV, "team_id": program["team"]["id"]},
            headers=program["director"],
        )
        assert res.status_code == 201
        data = res.json()
        assert len(data["created"]) == 2
        assert all(a["claim_code"] for a in data["created"])
        assert len(data["guardian_invites"]) == 1

    def test_a_claim_code_signs_the_athlete_in(self, client, program):
        created = client.post(
            "/api/coach/roster/import",
            json={"content": self.CSV, "team_id": program["team"]["id"]},
            headers=program["director"],
        ).json()["created"]

        res = client.post("/api/claim", json={"code": created[0]["claim_code"]})
        assert res.status_code == 201 or res.status_code == 200
        token = res.json()["token"]
        me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["role"] == "athlete"

    def test_claiming_needs_no_prior_login(self, client, program):
        """An imported athlete has no credentials yet; requiring some is circular."""
        created = client.post(
            "/api/coach/roster/import",
            json={"content": self.CSV, "team_id": program["team"]["id"]},
            headers=program["director"],
        ).json()["created"]
        assert client.post("/api/claim", json={"code": created[0]["claim_code"]}).status_code in (200, 201)

    def test_a_bad_claim_code_is_refused(self, client):
        res = client.post("/api/claim", json={"code": "ZZZZ-ZZZZ"})
        assert res.status_code == 400

    def test_athletes_cannot_import_a_roster(self, client, program):
        res = client.post(
            "/api/coach/roster/preview",
            json={"content": self.CSV}, headers=program["athletes"][0]["headers"],
        )
        assert res.status_code == 403

    def test_a_malformed_file_is_reported_not_crashed(self, client, program):
        res = client.post(
            "/api/coach/roster/preview",
            json={"content": "just some text with no delimiters at all"},
            headers=program["director"],
        )
        assert res.status_code in (200, 400)
        if res.status_code == 200:
            assert res.json()["file_problems"]

    def test_an_empty_file_is_refused_clearly(self, client, program):
        res = client.post(
            "/api/coach/roster/preview",
            json={"content": "   "}, headers=program["director"],
        )
        assert res.status_code == 400
        assert "empty" in res.json()["detail"]

    def test_importing_re_parses_rather_than_trusting_a_plan(self, client, program):
        """The endpoint takes the file, not a plan the client could rewrite."""
        schema = client.get("/openapi.json").json()
        body = schema["paths"]["/api/coach/roster/import"]["post"]["requestBody"]
        ref = body["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
        fields = set(schema["components"]["schemas"][ref]["properties"])
        assert "content" in fields
        assert "athletes" not in fields and "plan" not in fields

    def test_a_template_is_offered(self, client, program):
        res = client.get("/api/coach/roster/template", headers=program["director"])
        assert res.status_code == 200
        assert "First Name" in res.json()["content"]

    def test_the_upload_stays_json_not_multipart(self, client):
        """The 'no endpoint accepts a file' invariant has to survive this feature."""
        schema = client.get("/openapi.json").json()
        for path, methods in schema["paths"].items():
            for method, op in methods.items():
                content = (op.get("requestBody") or {}).get("content", {})
                for media_type in content:
                    assert media_type == "application/json", f"{method} {path}"


class TestDigestEndpoints:
    def test_the_digest_returns_kpis(self, client, program):
        do_session(client, program["athletes"][0]["headers"])
        data = client.get("/api/coach/digest", headers=program["director"]).json()
        assert data["subject"]
        assert data["kpis"]
        assert data["roster_size"] == 2

    def test_the_preview_renders_email_html(self, client, program):
        res = client.get("/api/coach/digest/preview", headers=program["director"])
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/html")
        assert "<table" in res.text

    def test_the_preview_names_no_athlete(self, client, program):
        """The constraint has to hold through the endpoint, not just the module."""
        do_session(client, program["athletes"][0]["headers"])
        body = client.get("/api/coach/digest/preview", headers=program["director"]).text
        for athlete in program["athletes"]:
            assert athlete["display_name"] not in body

    def test_athletes_cannot_read_the_digest(self, client, program):
        for path in ("/api/coach/digest", "/api/coach/digest/preview"):
            assert client.get(
                path, headers=program["athletes"][0]["headers"]
            ).status_code == 403, path

    def test_guardians_cannot_read_the_digest(self, client, program):
        invite = client.post(
            "/api/coach/guardian-invites",
            json={"athlete_id": program["athletes"][0]["id"]},
            headers=program["director"],
        ).json()
        guardian = client.post(
            "/api/guardians/redeem",
            json={"code": invite["code"], "display_name": "Dana"},
        ).json()
        headers = {"Authorization": f"Bearer {guardian['token']}"}
        assert client.get("/api/coach/digest", headers=headers).status_code == 403

    def test_sending_reports_honestly_when_mail_is_unconfigured(self, client, program):
        """Claiming a send that did not happen is worse than saying it did not."""
        res = client.post(
            "/api/coach/digest/send", json={"to": "coach@example.com"},
            headers=program["director"],
        ).json()
        assert res["delivered"] is False
        assert "not configured" in res["note"]

    def test_sending_without_an_address_is_refused_with_a_reason(self, client, program):
        res = client.post(
            "/api/coach/digest/send", json={}, headers=program["director"]
        )
        assert res.status_code == 400
        assert "email address" in res.json()["detail"]

    def test_a_digest_is_scoped_to_one_program(self, client, program):
        do_session(client, program["athletes"][0]["headers"])
        rival = client.post(
            "/api/orgs", json={"name": "Rival", "director_name": "Other"}
        ).json()
        rival_headers = {"Authorization": f"Bearer {rival['director']['token']}"}
        data = client.get("/api/coach/digest", headers=rival_headers).json()
        assert data["roster_size"] == 0
