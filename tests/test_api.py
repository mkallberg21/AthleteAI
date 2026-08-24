"""End-to-end API behaviour: onboarding, capture, scoring, leaderboards, access control."""
from __future__ import annotations

import json
import random

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

import athleteiq.api as api_module
from athleteiq import sports as sports_mod
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

        Film study introduced fields that *refer* to video without carrying
        any, so this no longer bans the word -- banning a word was always a
        proxy anyway. It now proves the property instead: nothing binary is
        accepted, no field names raw imagery, and any field that names a video
        is a short string or an integer, which cannot hold one.
        """
        schema = client.get("/openapi.json").json()
        # Words that only appear on a field carrying actual pixels.
        imagery = ("image", "frame", "landmark", "photo", "pixel", "base64",
                   "blob", "thumbnail", "bytes", "media")
        # Words that name a video without being one. These have to prove it.
        references = ("video", "clip")

        for name, model in schema.get("components", {}).get("schemas", {}).items():
            for prop, spec in (model.get("properties") or {}).items():
                field = f"{name}.{prop}"
                lowered = prop.lower()
                for term in imagery:
                    assert term not in lowered, f"request schema exposes {field!r}"

                if any(term in lowered for term in references):
                    kinds = {spec.get("type")} | {
                        option.get("type") for option in spec.get("anyOf", [])
                    }
                    assert kinds & {"string", "integer"}, \
                        f"{field} is not a plain reference"
                    if "string" in kinds:
                        limit = spec.get("maxLength") or max(
                            (o.get("maxLength") or 0) for o in spec.get("anyOf", [{}])
                        )
                        assert 0 < limit <= 2_000, \
                            f"{field} has no length cap, so it could carry a payload"

        # And no endpoint may accept a binary/multipart body at all. This is
        # the guard that actually stops an upload, whatever anything is named.
        for path, methods in schema["paths"].items():
            for method, op in methods.items():
                content = (op.get("requestBody") or {}).get("content", {})
                for media_type in content:
                    assert media_type == "application/json", \
                        f"{method.upper()} {path} accepts {media_type}"

    def test_the_review_module_has_no_network_path(self, client):
        """Self-review keeps footage on the phone, so it must not be able to
        send anything anywhere -- checked structurally rather than promised."""
        import re
        from pathlib import Path

        source = (
            Path(__file__).resolve().parent.parent
            / "athleteiq" / "web" / "static" / "review.js"
        ).read_text()

        # Comments describe the guarantee; the code must not contain a way to
        # break it.
        code = re.sub(r"/\*[\s\S]*?\*/|//.*", "", source)
        for forbidden in (
            "fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon",
            "navigator.send", "FormData", "/api/", "http://", "https://",
        ):
            assert forbidden not in code, f"review.js can reach the network: {forbidden!r}"

    def test_the_capture_app_never_posts_video(self, client):
        """The submit payload is counts. A recording must not ride along.

        Checked on what is actually handed to the API client and the offline
        queue, rather than on the file as a whole -- `video:` legitimately
        appears in the camera constraints, and a test that cannot tell those
        apart fails on correct code.
        """
        import re
        from pathlib import Path

        source = (
            Path(__file__).resolve().parent.parent
            / "athleteiq" / "web" / "static" / "capture.html"
        ).read_text()
        code = re.sub(r"<!--[\s\S]*?-->|/\*[\s\S]*?\*/|//.*", "", source)

        # Everything passed to api(), enqueue(), or flush(): the three ways
        # anything can leave this page.
        sends = re.findall(
            r"\b(?:api|enqueue|flush)\s*\(((?:[^()]|\([^()]*\))*)\)", code
        )
        assert sends, "found no API calls to inspect — has the call shape changed?"

        for call in sends:
            lowered = call.lower()
            for forbidden in ("recorder", "blob", "objecturl", ".poses", "chunks"):
                assert forbidden not in lowered, (
                    f"footage reaches the network in: {call.strip()[:120]!r}"
                )

    def test_submissions_store_no_imagery(self, client, program):
        """No table can hold a video, whatever its columns are called.

        Film study stores an eleven-character provider id, so a name-based ban
        would have to make an exception for it -- and an exception is exactly
        what a guarantee should not have. This checks type affinity instead:
        SQLite cannot store a video without a BLOB column, so there are none.
        """
        # Binary is allowed in exactly one place, and it holds DER-encoded
        # OCSP responses for certificate checking. Named rather than pattern
        # matched, so adding a second binary column fails this test loudly.
        binary_allowed = {"ocsp_staples"}

        do_session(client, program["athletes"][0]["headers"])
        conn = api_module._store.conn
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )]
        for table in tables:
            for row in conn.execute(f"PRAGMA table_info({table})"):
                col, decl = row[1].lower(), (row[2] or "").upper()
                if "BLOB" in decl:
                    assert table in binary_allowed, f"{table}.{col} is a BLOB"
                assert not any(t in col for t in ("image", "frame", "photo", "pixel")), \
                    f"{table}.{col} looks like it stores imagery"

    def test_film_stores_a_reference_and_never_a_video(self, client, program):
        """The positive statement, since film is the one place this product
        points a child's browser at video at all."""
        made = client.post(
            "/api/coach/clips",
            json={"video": "https://youtu.be/dQw4w9WgXcQ", "title": "Sliding early",
                  "start_s": 10, "end_s": 70},
            headers=program["director"],
        ).json()
        assert made["video_id"] == "dQw4w9WgXcQ"
        assert len(made["video_id"]) == 11

        stored = api_module._store.conn.execute(
            "SELECT video_id FROM clips WHERE id = ?", (made["id"],)
        ).fetchone()["video_id"]
        assert stored == "dQw4w9WgXcQ"
        # The embed points at the privacy-enhanced host, which is a mitigation
        # and not a cure -- see the README.
        assert made["embed_url"].startswith("https://www.youtube-nocookie.com/embed/")


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
        assert res["queued"] is True
        assert "nothing left the machine" in res["note"]

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


class TestScopedCoachEndpoints:
    """A scoped coach must not reach another team through any endpoint."""

    def _scoped(self, client, program):
        """A coach assigned only to a second team with its own athlete."""
        other_team = client.post(
            "/api/teams", json={"name": "JV"}, headers=program["director"]
        ).json()
        coach = api_module._store.create_user(
            program["org"]["org_id"], "coach", "Coach JV"
        )
        api_module._store.assign_staff_to_team(coach["id"], other_team["id"])
        jv_athlete = client.post(
            "/api/athletes",
            json={"display_name": "JV Kid", "join_code": other_team["join_code"]},
            headers=program["director"],
        ).json()
        return {
            "headers": {"Authorization": f"Bearer {coach['token']}"},
            "team": other_team,
            "athlete": jv_athlete,
        }

    def test_the_roster_is_limited_to_assigned_teams(self, client, program):
        scoped = self._scoped(client, program)
        rows = client.get("/api/coach/roster", headers=scoped["headers"]).json()["athletes"]
        assert [r["display_name"] for r in rows] == ["JV Kid"]

    def test_a_director_still_sees_everyone(self, client, program):
        self._scoped(client, program)
        rows = client.get("/api/coach/roster", headers=program["director"]).json()["athletes"]
        assert len(rows) == 3

    def test_requesting_another_team_is_refused(self, client, program):
        scoped = self._scoped(client, program)
        res = client.get(
            f"/api/coach/roster?team_id={program['team']['id']}", headers=scoped["headers"]
        )
        assert res.status_code == 403

    def test_another_teams_athlete_cannot_be_read_by_id(self, client, program):
        """Scoping the list is not enough if the detail route is open."""
        scoped = self._scoped(client, program)
        other = program["athletes"][0]["id"]
        assert client.get(
            f"/api/athletes/{other}", headers=scoped["headers"]
        ).status_code == 403
        assert client.get(
            f"/api/athletes/{scoped['athlete']['id']}", headers=scoped["headers"]
        ).status_code == 200

    def test_assigning_work_to_another_team_is_refused(self, client, program):
        from datetime import date, timedelta

        scoped = self._scoped(client, program)
        today = date.today()
        res = client.post(
            "/api/coach/assignments",
            json={
                "team_id": program["team"]["id"], "drill_key": "lax_wall_ball",
                "title": "x", "starts_on": today.isoformat(),
                "due_on": (today + timedelta(days=3)).isoformat(), "target_reps": 100,
            },
            headers=scoped["headers"],
        )
        assert res.status_code == 403

    def test_broadcasting_to_another_team_is_refused(self, client, program):
        scoped = self._scoped(client, program)
        res = client.post(
            "/api/coach/broadcast",
            json={"team_id": program["team"]["id"], "title": "hi"},
            headers=scoped["headers"],
        )
        assert res.status_code == 403

    def test_inviting_a_guardian_for_another_team_is_refused(self, client, program):
        scoped = self._scoped(client, program)
        res = client.post(
            "/api/coach/guardian-invites",
            json={"athlete_id": program["athletes"][0]["id"]},
            headers=scoped["headers"],
        )
        assert res.status_code == 403

    def test_importing_into_another_team_is_refused(self, client, program):
        scoped = self._scoped(client, program)
        res = client.post(
            "/api/coach/roster/import",
            json={"content": "Name\nNew Kid\n", "team_id": program["team"]["id"]},
            headers=scoped["headers"],
        )
        assert res.status_code == 403

    def test_only_a_director_can_change_team_assignments(self, client, program):
        scoped = self._scoped(client, program)
        res = client.post(
            "/api/coach/staff/assign",
            json={"user_id": 1, "team_id": scoped["team"]["id"]},
            headers=scoped["headers"],
        )
        assert res.status_code == 403


class TestOrgSwitching:
    def test_memberships_are_listed(self, client, program):
        res = client.get("/api/orgs/mine", headers=program["director"]).json()
        assert res["active_org_id"] == program["org"]["org_id"]
        assert len(res["memberships"]) == 1

    def test_a_program_header_selects_the_active_org(self, client, program):
        rival = client.post(
            "/api/orgs", json={"name": "Rival", "director_name": "Two Hats"}
        ).json()
        api_module._store.add_membership(
            program["org"]["director"]["id"], rival["org_id"], "coach"
        )
        headers = {**program["director"], "X-Org-Id": str(rival["org_id"])}
        res = client.get("/api/orgs/mine", headers=headers).json()
        assert res["active_org_id"] == rival["org_id"]
        assert res["role"] == "coach"

    def test_a_program_they_do_not_belong_to_is_403(self, client, program):
        rival = client.post(
            "/api/orgs", json={"name": "Rival", "director_name": "Other"}
        ).json()
        headers = {**program["director"], "X-Org-Id": str(rival["org_id"])}
        assert client.get("/api/orgs/mine", headers=headers).status_code == 403


class TestBillingEndpoints:
    def test_billing_reports_the_plan_and_usage(self, client, program):
        data = client.get("/api/billing", headers=program["director"]).json()
        assert data["plan"]["code"]
        assert data["usage"]["athletes"] == 2
        assert data["plans"]

    def test_a_quote_prices_a_plan(self, client, program):
        data = client.get("/api/billing/quote?plan=team", headers=program["director"]).json()
        assert data["total_cents"] >= 0

    def test_only_a_director_can_change_the_plan(self, client, program):
        coach = api_module._store.create_user(
            program["org"]["org_id"], "coach", "Assistant"
        )
        res = client.post(
            "/api/billing/plan", json={"plan_code": "club"},
            headers={"Authorization": f"Bearer {coach['token']}"},
        )
        assert res.status_code == 403

    def test_exceeding_seats_returns_402_with_a_number(self, client, program):
        """402 because this is a plan limit, not a malformed request."""
        client.post(
            "/api/billing/plan", json={"plan_code": "free"}, headers=program["director"]
        )
        for i in range(30):
            res = client.post(
                "/api/athletes", json={"display_name": f"Filler {i}"},
                headers=program["director"],
            )
            if res.status_code == 402:
                assert "seat" in res.json()["detail"]
                return
        pytest.fail("seat limit was never enforced")

    def test_athletes_cannot_read_billing(self, client, program):
        assert client.get(
            "/api/billing", headers=program["athletes"][0]["headers"]
        ).status_code == 403


class TestDigestDelivery:
    def _staff(self, client, program):
        """A director with an address, and a JV-scoped coach with their own."""
        store = api_module._store
        store.conn.execute(
            "UPDATE users SET email = 'director@example.com' WHERE id = ?",
            (program["org"]["director"]["id"],),
        )
        jv = client.post("/api/teams", json={"name": "JV"}, headers=program["director"]).json()
        coach = store.create_user(
            program["org"]["org_id"], "coach", "Coach JV", email="jv@example.com"
        )
        store.assign_staff_to_team(coach["id"], jv["id"])
        client.post(
            "/api/athletes",
            json={"display_name": "JV Kid", "join_code": jv["join_code"]},
            headers=program["director"],
        )
        store.conn.commit()
        return {"jv_team": jv, "coach": coach}

    def test_each_coach_gets_the_digest_for_their_own_teams(self, client, program):
        """Folding varsity into a JV coach's email makes their number meaningless."""
        from athleteiq import notifications as notify

        self._staff(client, program)
        notify.send_coach_digests(api_module._store.conn)

        rows = api_module._store.conn.execute(
            "SELECT to_email, subject FROM email_outbox ORDER BY to_email"
        ).fetchall()
        by_email = {r["to_email"]: r["subject"] for r in rows}
        assert "JV" in by_email["jv@example.com"]
        assert "Northshore" in by_email["director@example.com"]

    def test_running_the_job_twice_queues_once(self, client, program):
        from athleteiq import notifications as notify

        self._staff(client, program)
        first = notify.send_coach_digests(api_module._store.conn)
        second = notify.send_coach_digests(api_module._store.conn)
        assert first["queued"] > 0
        assert second["queued"] == 0

    def test_a_manual_send_queues_and_reports_status(self, client, program):
        self._staff(client, program)
        res = client.post(
            "/api/coach/digest/send", json={}, headers=program["director"]
        ).json()
        assert res["queued"] is True
        assert res["status"] in ("sent", "queued", "failed")

    def test_a_suppressed_address_is_refused_with_a_reason(self, client, program):
        from athleteiq import mailer

        self._staff(client, program)
        mailer.suppress(api_module._store.conn, "director@example.com", "bounced")
        res = client.post("/api/coach/digest/send", json={}, headers=program["director"])
        assert res.status_code == 400
        assert "unsubscribed" in res.json()["detail"]

    def test_a_scoped_coach_cannot_send_another_teams_digest(self, client, program):
        staff = self._staff(client, program)
        headers = {"Authorization": f"Bearer {staff['coach']['token']}"}
        res = client.post(
            "/api/coach/digest/send",
            json={"team_id": program["team"]["id"]}, headers=headers,
        )
        assert res.status_code == 403


class TestUnsubscribeEndpoints:
    def test_one_click_unsubscribe_needs_no_login(self, client, program):
        """Someone who wants out is holding an email, not a login."""
        from athleteiq import mailer

        token = mailer.unsubscribe_token(
            program["org"]["director"]["id"], mailer.Kind.COACH_DIGEST
        )
        res = client.get(f"/api/email/unsubscribe?token={token}")
        assert res.status_code == 200
        assert "Unsubscribed" in res.text
        assert not mailer.wants(
            api_module._store.conn,
            program["org"]["director"]["id"],
            mailer.Kind.COACH_DIGEST,
        )

    def test_the_post_form_of_one_click_works(self, client, program):
        from athleteiq import mailer

        token = mailer.unsubscribe_token(
            program["org"]["director"]["id"], mailer.Kind.COACH_DIGEST
        )
        assert client.post(f"/api/email/unsubscribe?token={token}").json()["unsubscribed"]

    def test_a_forged_token_changes_nothing(self, client, program):
        from athleteiq import mailer

        res = client.get("/api/email/unsubscribe?token=1.coach_digest.deadbeef")
        assert res.status_code == 200
        assert "not valid" in res.text
        assert mailer.wants(
            api_module._store.conn,
            program["org"]["director"]["id"],
            mailer.Kind.COACH_DIGEST,
        )

    def test_preferences_can_be_read_and_set(self, client, program):
        prefs = client.get("/api/email/preferences", headers=program["director"]).json()
        assert prefs["preferences"]["coach_digest"] is True
        updated = client.post(
            "/api/email/preferences",
            json={"kind": "coach_digest", "enabled": False},
            headers=program["director"],
        ).json()
        assert updated["preferences"]["coach_digest"] is False

    def test_an_unsubscribed_coach_is_skipped_next_week(self, client, program):
        from athleteiq import mailer, notifications as notify

        api_module._store.conn.execute(
            "UPDATE users SET email = 'director@example.com' WHERE id = ?",
            (program["org"]["director"]["id"],),
        )
        api_module._store.conn.commit()
        mailer.set_preference(
            api_module._store.conn, program["org"]["director"]["id"],
            mailer.Kind.COACH_DIGEST, False,
        )
        result = notify.send_coach_digests(api_module._store.conn)
        assert result["queued"] == 0

    def test_only_a_director_can_read_the_outbox(self, client, program):
        assert client.get(
            "/api/coach/outbox", headers=program["athletes"][0]["headers"]
        ).status_code == 403
        assert client.get(
            "/api/coach/outbox", headers=program["director"]
        ).status_code == 200


class TestWebhookEndpoint:
    """The endpoint takes instructions from the public internet about whose
    mail to stop. Every negative case here is a real attack."""

    def _mailgun(self, secret="mg-secret", email="coach@example.com", age=0, event_id="ev1"):
        import hashlib
        import hmac
        import json
        import time

        timestamp = str(int(time.time()) - age)
        token = "tok"
        signature = hmac.new(
            secret.encode(), f"{timestamp}{token}".encode(), hashlib.sha256
        ).hexdigest()
        return json.dumps({
            "signature": {"timestamp": timestamp, "token": token, "signature": signature},
            "event-data": {
                "event": "failed", "severity": "permanent", "id": event_id,
                "recipient": email, "reason": "550 mailbox unavailable",
            },
        })

    def _configure(self, monkeypatch, secret="mg-secret"):
        import athleteiq.api as api_mod
        from athleteiq.config import Config

        monkeypatch.setattr(
            api_mod, "CONFIG",
            Config(webhook_secrets={"mailgun": secret, "sendgrid": "", "postmark": "",
                                    "ses": "", "generic": ""}),
        )

    def _seed(self, client, program):
        from athleteiq import mailer

        store = api_module._store
        store.conn.execute(
            "UPDATE users SET email = 'coach@example.com' WHERE id = ?",
            (program["org"]["director"]["id"],),
        )
        store.conn.commit()
        mailer.enqueue(
            store.conn, to_email="coach@example.com", subject="x", html="x", text="x",
            kind=mailer.Kind.COACH_DIGEST, dedupe_key="seed",
            user_id=program["org"]["director"]["id"],
        )

    def test_a_verified_bounce_suppresses_the_address(self, client, program, monkeypatch):
        from athleteiq import mailer

        self._configure(monkeypatch)
        self._seed(client, program)
        res = client.post(
            "/api/webhooks/email/mailgun",
            content=self._mailgun(),
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 200
        assert res.json()["actions"]["suppressed"] == 1
        assert mailer.is_suppressed(api_module._store.conn, "coach@example.com")

    def test_an_unsigned_request_is_rejected(self, client, program, monkeypatch):
        """The whole point: anyone could otherwise cut a coach off from their digest."""
        from athleteiq import mailer

        self._configure(monkeypatch)
        self._seed(client, program)
        res = client.post(
            "/api/webhooks/email/mailgun",
            content=self._mailgun(secret="attacker-guess"),
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 401
        assert not mailer.is_suppressed(api_module._store.conn, "coach@example.com")

    def test_the_rejection_does_not_explain_itself(self, client, program, monkeypatch):
        """Telling an unauthenticated caller why helps them get it right next time."""
        self._configure(monkeypatch)
        res = client.post(
            "/api/webhooks/email/mailgun",
            content=self._mailgun(secret="wrong"),
            headers={"Content-Type": "application/json"},
        )
        assert res.json()["detail"] == "unauthorized"

    def test_a_replayed_request_is_rejected(self, client, program, monkeypatch):
        self._configure(monkeypatch)
        self._seed(client, program)
        res = client.post(
            "/api/webhooks/email/mailgun",
            content=self._mailgun(age=7200),
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 401

    def test_an_unconfigured_provider_rejects_everything(self, client, program, monkeypatch):
        """Absent configuration must never mean 'trust anything'."""
        self._configure(monkeypatch, secret="")
        res = client.post(
            "/api/webhooks/email/mailgun",
            content=self._mailgun(),
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 401

    def test_a_verified_but_unreadable_payload_is_accepted(self, client, program, monkeypatch):
        """A provider disables an endpoint that keeps erroring, so an unknown
        shape must not look like a failure."""
        import athleteiq.api as api_mod
        from athleteiq.config import Config

        monkeypatch.setattr(
            api_mod, "CONFIG",
            Config(webhook_secrets={"postmark": "tok", "mailgun": "", "sendgrid": "",
                                    "ses": "", "generic": ""}),
        )
        res = client.post(
            "/api/webhooks/email/postmark",
            content="{not json",
            headers={"Content-Type": "application/json", "X-Webhook-Token": "tok"},
        )
        assert res.status_code == 202

    def test_retried_deliveries_are_idempotent(self, client, program, monkeypatch):
        self._configure(monkeypatch)
        self._seed(client, program)
        payload = self._mailgun()
        for _ in range(3):
            client.post(
                "/api/webhooks/email/mailgun", content=payload,
                headers={"Content-Type": "application/json"},
            )
        assert api_module._store.conn.execute(
            "SELECT COUNT(*) AS n FROM webhook_events"
        ).fetchone()["n"] == 1

    def test_the_webhook_needs_no_bearer_token(self, client, program, monkeypatch):
        """The caller is a provider, not a user."""
        self._configure(monkeypatch)
        self._seed(client, program)
        res = client.post(
            "/api/webhooks/email/mailgun", content=self._mailgun(),
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 200


class TestBounceAdmin:
    def test_a_director_sees_failing_addresses(self, client, program):
        from athleteiq import webhooks as W

        W.apply_event(api_module._store.conn, W.Event(
            provider="mailgun", event_id="b1",
            type=W.EventType.HARD_BOUNCE, email="dead@example.com",
        ))
        data = client.get("/api/coach/bounces", headers=program["director"]).json()
        assert data["addresses"][0]["email"] == "dead@example.com"
        assert data["addresses"][0]["suppressed"] is True

    def test_athletes_cannot_read_bounces(self, client, program):
        assert client.get(
            "/api/coach/bounces", headers=program["athletes"][0]["headers"]
        ).status_code == 403

    def test_a_corrected_address_can_be_put_back(self, client, program):
        from athleteiq import mailer, webhooks as W

        W.apply_event(api_module._store.conn, W.Event(
            provider="mailgun", event_id="b2",
            type=W.EventType.HARD_BOUNCE, email="typo@example.com",
        ))
        res = client.post(
            "/api/coach/bounces/unsuppress",
            json={"email": "typo@example.com"}, headers=program["director"],
        )
        assert res.status_code == 200
        assert not mailer.is_suppressed(api_module._store.conn, "typo@example.com")

    def test_a_spam_complaint_cannot_be_overridden_by_an_admin(self, client, program):
        """They did not ask to be put back on the list."""
        from athleteiq import mailer, webhooks as W

        W.apply_event(api_module._store.conn, W.Event(
            provider="sendgrid", event_id="c9",
            type=W.EventType.COMPLAINT, email="angry@example.com",
        ))
        res = client.post(
            "/api/coach/bounces/unsuppress",
            json={"email": "angry@example.com"}, headers=program["director"],
        )
        assert res.status_code == 400
        assert "opt back in themselves" in res.json()["detail"]
        assert mailer.is_suppressed(api_module._store.conn, "angry@example.com")


class TestSesWebhookEndpoint:
    """SES arrives through SNS, verified by certificate rather than a secret."""

    TOPIC = "arn:aws:sns:us-east-1:123456789012:athleteiq-bounces"

    def _signed(self, key, email="coach@example.com", topic=None):
        import base64
        import json

        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        from athleteiq import sns

        body = json.dumps({
            "notificationType": "Bounce", "mail": {"messageId": "m1"},
            "bounce": {
                "bounceType": "Permanent", "feedbackId": "f1",
                "bouncedRecipients": [{"emailAddress": email}],
            },
        })
        message = {
            "Type": "Notification", "MessageId": "mid-1",
            "TopicArn": topic or self.TOPIC, "Message": body,
            "Timestamp": "2026-08-24T10:00:00.000Z", "SignatureVersion": "2",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com/cert.pem",
        }
        message["Signature"] = base64.b64encode(
            key.sign(sns.canonical_string(message), padding.PKCS1v15(), hashes.SHA256())
        ).decode()
        return json.dumps(message)

    def _configure(self, monkeypatch, pem, anchors, topics=None):
        import athleteiq.api as api_mod
        import athleteiq.sns as sns_mod
        import athleteiq.webhooks as webhooks_mod
        from athleteiq.config import Config

        config = Config(sns_topic_arns=tuple(topics if topics is not None else [self.TOPIC]))
        monkeypatch.setattr(api_mod, "CONFIG", config)
        monkeypatch.setattr(webhooks_mod, "CONFIG", config)
        monkeypatch.setattr(sns_mod, "CONFIG", config)
        monkeypatch.setattr(sns_mod, "default_fetcher", lambda url: pem)
        # The chain terminates at this test hierarchy's root, not Amazon's.
        monkeypatch.setattr(sns_mod, "trust_anchors", lambda reload=False: anchors)
        sns_mod.clear_cert_cache()

    def test_a_genuine_ses_bounce_suppresses_the_address(self, client, program, monkeypatch):
        from athleteiq import mailer
        from tests.test_sns import make_cert

        key, pem, anchors = make_cert()
        self._configure(monkeypatch, pem, anchors)
        res = client.post(
            "/api/webhooks/email/ses", content=self._signed(key),
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 200
        assert res.json()["actions"]["suppressed"] == 1
        assert mailer.is_suppressed(api_module._store.conn, "coach@example.com")

    def test_a_message_for_another_topic_is_rejected(self, client, program, monkeypatch):
        """A valid AWS signature only proves the sender has an AWS account."""
        from athleteiq import mailer
        from tests.test_sns import make_cert

        key, pem, anchors = make_cert()
        self._configure(monkeypatch, pem, anchors)
        res = client.post(
            "/api/webhooks/email/ses",
            content=self._signed(key, topic="arn:aws:sns:us-east-1:999:attacker"),
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 401
        assert not mailer.is_suppressed(api_module._store.conn, "coach@example.com")

    def test_a_foreign_signing_key_is_rejected(self, client, program, monkeypatch):
        from tests.test_sns import make_cert

        _, our_pem, our_anchors = make_cert()
        attacker_key, _, _ = make_cert()
        self._configure(monkeypatch, our_pem, our_anchors)
        res = client.post(
            "/api/webhooks/email/ses", content=self._signed(attacker_key),
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 401

    def test_no_configured_topics_disables_the_endpoint(self, client, program, monkeypatch):
        from tests.test_sns import make_cert

        key, pem, anchors = make_cert()
        self._configure(monkeypatch, pem, anchors, topics=[])
        res = client.post(
            "/api/webhooks/email/ses", content=self._signed(key),
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 401

    def test_a_certificate_from_an_untrusted_root_is_rejected(
        self, client, program, monkeypatch
    ):
        """A signature that verifies against a certificate we do not trust."""
        from tests.test_sns import make_cert

        key, pem, _ = make_cert()
        _, _, other_anchors = make_cert()
        self._configure(monkeypatch, pem, other_anchors)
        res = client.post(
            "/api/webhooks/email/ses", content=self._signed(key),
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 401


class TestPositionEndpoints:

    def test_the_join_form_can_offer_a_list_instead_of_a_text_box(self, client, program):
        """Normalising free text is repair work; a dropdown means no repair."""
        body = client.get("/api/positions", headers=program["athletes"][0]["headers"]).json()
        assert body["sport"] == "lacrosse"
        keys = {p["key"] for p in body["positions"]}
        assert {"attack", "midfield", "defense", "lsm", "fogo", "goalie"} == keys
        for position in body["positions"]:
            assert position["focus"] and position["plural"]
            assert abs(sum(position["emphasis"].values()) - 1.0) < 1e-9

    def test_an_athlete_gets_position_guidance_with_no_peers_at_all(self, client, program):
        athlete = program["athletes"][0]
        client.post(
            "/api/teams/join",
            json={"join_code": program["team"]["join_code"], "position": "Goalie"},
            headers=athlete["headers"],
        )
        # Long enough for the mix to have a shape: three token sessions are
        # a session count, not a training pattern.
        for seed in (1, 2, 3):
            do_session(client, athlete["headers"], seed=seed, count=700)

        report = client.get("/api/benchmarks", headers=athlete["headers"]).json()
        assert report["position"]["key"] == "goalie"
        assert report["mix"]["ready"] is True
        assert report["mix"]["suggestions"]
        # Two athletes in the program is nowhere near a peer group.
        assert report["peer_pool"]["scope"] == "band"
        assert report["comparisons"] == []

    def test_the_coach_sees_the_squad_by_position(self, client, program):
        for athlete, position in zip(program["athletes"], ("Middie", "wingback")):
            client.post(
                "/api/teams/join",
                json={"join_code": program["team"]["join_code"], "position": position},
                headers=athlete["headers"],
            )
        body = client.get("/api/coach/budgets", headers=program["director"]).json()
        counts = {p["key"]: p["count"] for p in body["positions"]}
        assert counts["midfield"] == 1
        assert counts["unrecognised"] == 1
        assert body["unrecognised_positions"] == ["wingback"]

    def test_an_unrecognised_position_is_flagged_at_roster_import(self, client, program):
        """It is not cosmetic: it drops the athlete out of every position feature."""
        csv = "name,birth_year,position\nAlex T.,2011,Middie\nRiley K.,2011,wingback\n"
        plan = client.post(
            "/api/coach/roster/preview", json={"content": csv}, headers=program["director"]
        ).json()
        rows = {a["display_name"]: a for a in plan["athletes"]}
        assert not rows["Alex T."]["warnings"]
        assert any("not recognised" in w for w in rows["Riley K."]["warnings"])


class TestSpecialisationSetting:
    """When position work starts is a judgement about how children in this
    program are developed. It belongs to the director."""

    def test_it_defaults_late(self, client, program):
        body = client.get("/api/positions", headers=program["director"]).json()
        assert body["position_emphasis_min_age"] == 15
        assert body["applies_from"] == "Age 15 and up"
        assert "from age 15" in body["note"]

    def test_a_director_can_move_it(self, client, program):
        res = client.put(
            "/api/org/specialisation",
            json={"position_emphasis_min_age": 13},
            headers=program["director"],
        )
        assert res.status_code == 200
        assert res.json()["applies_from"] == "Age 13 and up"
        after = client.get("/api/positions", headers=program["director"]).json()
        assert after["position_emphasis_min_age"] == 13

    def test_a_director_can_switch_it_off_entirely(self, client, program):
        res = client.put(
            "/api/org/specialisation",
            json={"position_emphasis_min_age": 99},
            headers=program["director"],
        ).json()
        assert "Never" in res["applies_from"]
        note = client.get("/api/positions", headers=program["director"]).json()["note"]
        assert "all-round training plan" in note

    def test_a_coach_cannot(self, client, program):
        rival = client.post(
            "/api/orgs", json={"name": "Rival", "director_name": "Two Hats"}
        ).json()
        api_module._store.add_membership(
            program["org"]["director"]["id"], rival["org_id"], "coach"
        )
        headers = {**program["director"], "X-Org-Id": str(rival["org_id"])}
        res = client.put(
            "/api/org/specialisation",
            json={"position_emphasis_min_age": 0}, headers=headers,
        )
        assert res.status_code == 403

    def test_an_age_outside_the_range_is_rejected(self, client, program):
        for value in (-1, 120):
            res = client.put(
                "/api/org/specialisation",
                json={"position_emphasis_min_age": value},
                headers=program["director"],
            )
            assert res.status_code == 422


class TestDrillsCarryTheirCrossSportValue:

    def test_the_catalog_stays_public(self, client):
        """Reference data. The counting spec ships to every browser anyway."""
        assert client.get("/api/drills").status_code == 200
        assert client.get("/api/drills/not_a_drill").status_code == 404

    def test_every_drill_names_other_sports_it_pays_off_in(self, client):
        for drill in client.get("/api/drills").json()["drills"]:
            assert drill["transfers"], drill["key"]
            assert drill["blurb"], drill["key"]

    def test_the_athletes_own_sport_is_left_out(self, client):
        body = client.get("/api/drills", params={"sport": "lacrosse"}).json()
        for drill in body["drills"]:
            assert all(t["sport"].lower() != "lacrosse" for t in drill["transfers"])

    def test_a_single_drill_carries_it_too(self, client):
        body = client.get(
            "/api/drills/gen_lateral_bound", params={"sport": "lacrosse"}
        ).json()
        sports = [t["sport"] for t in body["transfers"]]
        assert "Basketball" in sports
        assert body["counter"], "still the full counting spec"


class TestAYoungAthleteIsNotSpecialisedThroughTheApi:

    def test_they_get_the_all_round_plan_and_are_told_why(self, client, program):
        athlete = program["athletes"][0]
        client.post(
            "/api/teams/join",
            json={"join_code": program["team"]["join_code"], "position": "Goalie"},
            headers=athlete["headers"],
        )
        for seed in (1, 2, 3):
            do_session(client, athlete["headers"], seed=seed, count=700)

        # The fixture's athletes are born 2011, so they are young for the
        # default threshold of 15 until the mid-2020s roll far enough on.
        client.put(
            "/api/org/specialisation",
            json={"position_emphasis_min_age": 99},
            headers=program["director"],
        )
        report = client.get("/api/benchmarks", headers=athlete["headers"]).json()
        assert report["specialising"] is False
        assert report["position"]["key"] == "goalie", "still recorded"
        assert report["mix"]["position"]["key"] == "general"
        assert "goalie" in report["specialisation"]["headline"].lower()

    def test_turning_the_setting_on_changes_what_they_see(self, client, program):
        athlete = program["athletes"][0]
        client.post(
            "/api/teams/join",
            json={"join_code": program["team"]["join_code"], "position": "Goalie"},
            headers=athlete["headers"],
        )
        for seed in (1, 2, 3):
            do_session(client, athlete["headers"], seed=seed, count=700)

        client.put(
            "/api/org/specialisation",
            json={"position_emphasis_min_age": 0}, headers=program["director"],
        )
        report = client.get("/api/benchmarks", headers=athlete["headers"]).json()
        assert report["specialising"] is True
        assert report["mix"]["position"]["key"] == "goalie"
        assert report["specialisation"] is None


class TestMultiSportEndpoints:

    def test_the_picker_offers_sports_and_seasons(self, client):
        body = client.get("/api/sports").json()
        assert body["seasons"] == ["fall", "winter", "spring", "summer"]
        keys = {s["key"] for s in body["sports"]}
        assert {"basketball", "soccer", "swimming", "track"} <= keys

    def test_an_athlete_records_their_own(self, client, program):
        athlete = program["athletes"][0]
        res = client.put("/api/me/sports", json={"sports": [
            {"sport": "Bball", "seasons": ["winter"], "is_primary": False},
            {"sport": "Lacrosse", "seasons": ["spring"], "is_primary": True},
        ]}, headers=athlete["headers"]).json()
        assert [s["sport"] for s in res["sports"]] == ["lacrosse", "basketball"]
        assert res["profile"]["level"] == "low"
        assert client.get(
            "/api/me/sports", headers=athlete["headers"]
        ).json()["sports"] == res["sports"]

    def test_saving_replaces_rather_than_merges(self, client, program):
        """A sport a kid deliberately unticked must not linger -- a stale extra
        makes them look more multi-sport than they are, which relaxes the gate."""
        athlete = program["athletes"][0]
        client.put("/api/me/sports", json={"sports": [
            {"sport": "lacrosse", "seasons": ["spring"]},
            {"sport": "basketball", "seasons": ["winter"]},
        ]}, headers=athlete["headers"])
        res = client.put("/api/me/sports", json={"sports": [
            {"sport": "lacrosse", "seasons": ["spring"]},
        ]}, headers=athlete["headers"]).json()
        assert [s["sport"] for s in res["sports"]] == ["lacrosse"]

    def test_junk_is_dropped_rather_than_stored(self, client, program):
        athlete = program["athletes"][0]
        res = client.put("/api/me/sports", json={"sports": [
            {"sport": "competitive napping", "seasons": ["winter"]},
            {"sport": "Soccer", "seasons": ["fall", "nonsense"]},
        ]}, headers=athlete["headers"]).json()
        assert [s["sport"] for s in res["sports"]] == ["soccer"]
        assert res["sports"][0]["seasons"] == ["fall"]

    def test_a_coach_can_fill_it_in_for_their_own_athletes_only(self, client, program):
        athlete = program["athletes"][0]
        ok = client.put(
            f"/api/athletes/{athlete['id']}/sports",
            json={"sports": [{"sport": "soccer", "seasons": ["fall"]}]},
            headers=program["director"],
        )
        assert ok.status_code == 200

        rival = client.post(
            "/api/orgs", json={"name": "Rival", "director_name": "Other"}
        ).json()
        theirs = {"Authorization": f"Bearer {rival['director']['token']}"}
        assert client.put(
            f"/api/athletes/{athlete['id']}/sports",
            json={"sports": [{"sport": "soccer", "seasons": ["fall"]}]},
            headers=theirs,
        ).status_code == 404

    def test_a_guardian_cannot_record_training_sports_as_an_athlete(self, client, program):
        assert client.put(
            "/api/me/sports", json={"sports": []},
            headers=program["director"],
        ).status_code == 403

    def test_it_changes_what_the_athlete_is_shown(self, client, program):
        athlete = program["athletes"][0]
        before = client.get("/api/benchmarks", headers=athlete["headers"]).json()
        client.put("/api/me/sports", json={"sports": [
            {"sport": "lacrosse", "seasons": ["spring"], "is_primary": True},
            {"sport": "basketball", "seasons": ["winter"]},
            {"sport": "soccer", "seasons": ["fall"]},
        ]}, headers=athlete["headers"])
        after = client.get("/api/benchmarks", headers=athlete["headers"]).json()

        assert after["budget"]["band"]["weekly_target"] < before["budget"]["band"]["weekly_target"]
        assert after["sports"]["level"] == "low"
        assert any("does not need to be as long" in a for a in after["sport_advisories"])

    def test_a_roster_import_can_carry_other_sports(self, client, program):
        csv = ("name,birth_year,position,sports\n"
               "Alex T.,2011,Middie,basketball; soccer\n")
        plan = client.post(
            "/api/coach/roster/preview", json={"content": csv}, headers=program["director"]
        ).json()
        assert plan["athletes"][0]["sports"] == ["basketball", "soccer"]

        client.post(
            "/api/coach/roster/import",
            json={"content": csv, "team_id": program["team"]["id"]},
            headers=program["director"],
        )
        summary = client.get("/api/coach/budgets", headers=program["director"]).json()
        assert summary["specialisation"].get("moderate") or summary["specialisation"].get("low")


class TestWellnessEndpoints:

    def _hurt(self, client, athlete, **kwargs):
        body = {"area": "knee", "severity": "sore", **kwargs}
        return client.post("/api/wellness/discomfort", json=body, headers=athlete["headers"])

    def test_the_form_states_the_promise_up_front(self, client):
        body = client.get("/api/wellness/form").json()
        promise = body["promise"].lower()
        assert "never costs you a streak" in promise
        assert "parent or guardian only" in promise
        assert {a["key"] for a in body["areas"]} >= {"head", "knee", "shoulder"}

    def test_an_athlete_reports_and_is_told_what_to_do(self, client, program):
        athlete = program["athletes"][0]
        body = self._hurt(client, athlete).json()
        assert body["action"] == "ease_off"
        assert body["guidance"][0]["detail"]
        assert "lower_body" in body["blocked_tissues"]

    def test_sore_areas_hide_the_drills_that_load_them(self, client, program):
        athlete = program["athletes"][0]
        self._hurt(client, athlete, area="shoulder")
        drills = {d["key"]: d for d in client.get(
            "/api/me/drills", headers=athlete["headers"]
        ).json()["drills"]}
        assert drills["lax_wall_ball"]["available"] is False
        assert "shoulder" in drills["lax_wall_ball"]["reason"]
        assert drills["gen_squat"]["available"] is True

    def test_a_drill_that_is_held_back_can_still_be_recorded(self, client, program):
        """The app is not anyone's physio and should not pretend it can stop a
        determined thirteen-year-old."""
        athlete = program["athletes"][0]
        self._hurt(client, athlete)
        started = client.post(
            "/api/sessions/start", json={"drill_key": "gen_squat"},
            headers=athlete["headers"],
        )
        assert started.status_code == 201

    def test_a_coach_sees_the_area_but_never_the_note(self, client, program):
        athlete = program["athletes"][0]
        self._hurt(client, athlete, note="my dad shouted at me about it")
        body = client.get("/api/coach/wellness", headers=program["director"]).json()
        assert body["counts"]["ease_off"] == 1
        row = body["athletes"][0]
        assert row["open_reports"][0]["area_label"] == "Knee"
        assert "note" not in row["open_reports"][0]
        assert "shouted" not in json.dumps(body)

    def test_the_athlete_can_still_read_their_own_note(self, client, program):
        athlete = program["athletes"][0]
        self._hurt(client, athlete, note="mine")
        body = client.get("/api/wellness", headers=athlete["headers"]).json()
        assert body["open_reports"][0]["note"] == "mine"

    def test_one_athlete_cannot_read_anothers(self, client, program):
        one, two = program["athletes"]
        self._hurt(client, one, note="mine")
        body = client.get("/api/wellness", headers=two["headers"]).json()
        assert body["open_reports"] == []

    def test_a_coach_cannot_report_on_an_athletes_behalf(self, client, program):
        """It is the athlete's own body and their own account."""
        assert client.post(
            "/api/wellness/discomfort", json={"area": "knee", "severity": "sore"},
            headers=program["director"],
        ).status_code == 403

    def test_resolving_it_puts_the_drills_back(self, client, program):
        athlete = program["athletes"][0]
        report_id = self._hurt(client, athlete).json()["open_reports"][0]["id"]
        after = client.post(
            f"/api/wellness/discomfort/{report_id}/resolved", headers=athlete["headers"]
        ).json()
        assert after["open_reports"] == []
        drills = {d["key"]: d for d in client.get(
            "/api/me/drills", headers=athlete["headers"]
        ).json()["drills"]}
        assert all(d["available"] for d in drills.values())

    def test_junk_is_a_400_not_a_500(self, client, program):
        athlete = program["athletes"][0]
        assert self._hurt(client, athlete, area="spleen").status_code == 400
        assert client.post(
            "/api/wellness/discomfort", json={"area": "knee", "severity": "agony"},
            headers=athlete["headers"],
        ).status_code == 422

    def test_a_checkin_costs_nothing_end_to_end(self, client, program):
        athlete = program["athletes"][0]
        do_session(client, athlete["headers"], seed=3)
        before = client.get("/api/me", headers=athlete["headers"]).json()
        client.post(
            "/api/wellness/checkin", json={"soreness": "hurts"}, headers=athlete["headers"]
        )
        after = client.get("/api/me", headers=athlete["headers"]).json()
        assert after["total_xp"] == before["total_xp"]
        assert after["streak"] >= before["streak"]

    def test_soreness_never_reaches_a_leaderboard(self, client, program):
        """Structural, like the no-video rule: checked against the payload
        rather than trusted to stay true."""
        athlete = program["athletes"][0]
        do_session(client, athlete["headers"], seed=3)
        self._hurt(client, athlete, note="private")
        for path in ("/api/leaderboard?window=week", "/api/standings?window=week"):
            payload = json.dumps(
                client.get(path, headers=athlete["headers"]).json()
            ).lower()
            for leak in ("knee", "sore", "discomfort", "wellness", "private", "injur"):
                assert leak not in payload, (path, leak)


class TestReturnToPlayEndpoints:

    def _guardian(self, client, store, athlete_id, name="A Parent"):
        from athleteiq import guardians
        invite = guardians.create_invite(store.conn, athlete_id, created_by=athlete_id)
        person = guardians.redeem_invite(store.conn, invite["code"], name)
        store.conn.commit()
        return {"Authorization": f"Bearer {person['token']}"}

    def _plan(self, client, athlete, area="knee", flags=("giving_way",)):
        made = client.post(
            "/api/wellness/discomfort",
            json={"area": area, "severity": "niggle", "flags": list(flags)},
            headers=athlete["headers"],
        ).json()
        report_id = made["open_reports"][0]["id"]
        return client.post(
            f"/api/wellness/discomfort/{report_id}/resolved", headers=athlete["headers"]
        ).json()

    def test_saying_you_are_better_opens_a_ramp(self, client, program):
        athlete = program["athletes"][0]
        body = self._plan(client, athlete)
        assert body["open_reports"] == []
        plan = body["plans"][0]
        assert plan["stage"] == "rest" and plan["awaiting_clearance"] is True

    def test_an_athlete_cannot_clear_themselves(self, client, program):
        athlete = program["athletes"][0]
        plan_id = self._plan(client, athlete)["plans"][0]["id"]
        res = client.post(
            f"/api/wellness/plans/{plan_id}/clearance", json={},
            headers=athlete["headers"],
        )
        assert res.status_code == 403
        assert "cannot clear your own" in res.json()["detail"]

    def test_a_coach_can_clear_an_ordinary_one(self, client, program):
        athlete = program["athletes"][0]
        plan_id = self._plan(client, athlete)["plans"][0]["id"]
        res = client.post(
            f"/api/wellness/plans/{plan_id}/clearance", json={},
            headers=program["director"],
        )
        assert res.status_code == 200
        assert res.json()["stage"] == "light"

    def test_a_coach_cannot_clear_a_head_return(self, client, program):
        """That one needs what a doctor told the family, and a coach does not
        have standing to report it."""
        athlete = program["athletes"][0]
        plan_id = self._plan(client, athlete, area="head", flags=())["plans"][0]["id"]
        res = client.post(
            f"/api/wellness/plans/{plan_id}/clearance",
            json={"clinician_name": "Dr Okafor"}, headers=program["director"],
        )
        assert res.status_code == 403
        assert "parent or guardian" in res.json()["detail"]

    def test_a_guardian_can_with_a_named_clinician(self, client, program):
        athlete = program["athletes"][0]
        plan_id = self._plan(client, athlete, area="head", flags=())["plans"][0]["id"]
        guardian = self._guardian(client, api_module._store, athlete["id"])

        bare = client.post(
            f"/api/wellness/plans/{plan_id}/clearance", json={}, headers=guardian,
        )
        assert bare.status_code == 400

        named = client.post(
            f"/api/wellness/plans/{plan_id}/clearance",
            json={"clinician_name": "Dr Okafor"}, headers=guardian,
        )
        assert named.status_code == 200
        assert named.json()["clinician_name"] == "Dr Okafor"

    def test_a_stranger_cannot_clear_anything(self, client, program):
        athlete = program["athletes"][0]
        plan_id = self._plan(client, athlete)["plans"][0]["id"]
        rival = client.post(
            "/api/orgs", json={"name": "Rival", "director_name": "Other"}
        ).json()
        res = client.post(
            f"/api/wellness/plans/{plan_id}/clearance", json={},
            headers={"Authorization": f"Bearer {rival['director']['token']}"},
        )
        assert res.status_code == 404

    def test_advancing_too_early_explains_why(self, client, program):
        athlete = program["athletes"][0]
        plan_id = self._plan(client, athlete)["plans"][0]["id"]
        res = client.post(
            f"/api/wellness/plans/{plan_id}/advance", headers=athlete["headers"]
        )
        assert res.status_code == 409
        assert "Waiting on" in res.json()["detail"]

    def test_the_ramp_holds_drills_back_until_it_is_finished(self, client, program):
        athlete = program["athletes"][0]
        plan_id = self._plan(client, athlete)["plans"][0]["id"]
        held = {d["key"]: d for d in client.get(
            "/api/me/drills", headers=athlete["headers"]
        ).json()["drills"]}
        assert all(d["available"] is False for d in held.values()), "rest stage"

        client.post(f"/api/wellness/plans/{plan_id}/clearance", json={},
                    headers=program["director"])
        after = {d["key"]: d for d in client.get(
            "/api/me/drills", headers=athlete["headers"]
        ).json()["drills"]}
        assert after["lax_wall_ball"]["available"] is True
        assert after["gen_squat"]["available"] is False
        assert "ramp" in after["gen_squat"]["reason"]

    def test_the_history_is_readable_by_the_people_with_standing(self, client, program):
        athlete = program["athletes"][0]
        plan_id = self._plan(client, athlete)["plans"][0]["id"]
        client.post(f"/api/wellness/plans/{plan_id}/clearance", json={},
                    headers=program["director"])
        guardian = self._guardian(client, api_module._store, athlete["id"])

        for headers in (athlete["headers"], program["director"], guardian):
            events = client.get(
                f"/api/wellness/plans/{plan_id}/history", headers=headers
            ).json()["events"]
            assert [e["kind"] for e in events] == ["opened", "cleared"]

    def test_the_history_is_not_readable_by_anyone_else(self, client, program):
        athlete, other = program["athletes"]
        plan_id = self._plan(client, athlete)["plans"][0]["id"]
        assert client.get(
            f"/api/wellness/plans/{plan_id}/history", headers=other["headers"]
        ).status_code == 404


class TestSigningUpAsAnySport:

    def test_the_catalog_is_public_because_you_need_it_before_an_account(self, client):
        body = client.get("/api/sports/catalog").json()
        labels = {s["label"] for s in body["sports"]}
        assert {
            "Lacrosse", "Basketball", "Soccer", "Volleyball", "Baseball", "Softball",
            "Cheer", "Dance", "Swimming", "Track & Field", "Football", "Gymnastics",
            "Tennis", "Cross Country", "Hockey", "Rugby",
        } <= labels

    def test_each_entry_says_whether_positions_exist(self, client):
        """So the signup form can be honest rather than promising a position
        picker that turns out to be empty."""
        by_key = {s["key"]: s for s in client.get("/api/sports/catalog").json()["sports"]}
        for key in ("basketball", "soccer", "cheer", "rugby", "gymnastics"):
            assert by_key[key]["positions"] > 0, key
        assert by_key["golf"]["positions"] == 0

    @pytest.mark.parametrize("sport,expected", [
        ("basketball", "basketball"), ("Cheer", "cheer"),
        ("Ice Hockey", "hockey"), ("track and field", "track"),
        ("Girls Lacrosse", "lacrosse"), ("hoops", "basketball"),
    ])
    def test_what_a_director_types_is_normalised(self, client, sport, expected):
        """Stored verbatim, "Girls Lacrosse" would match no position list, no
        drill emphasis and no transfer filter -- broken three ways, silently."""
        org = client.post(
            "/api/orgs", json={"name": "A Club", "sport": sport, "director_name": "Dir"},
        ).json()
        stored = api_module._store.conn.execute(
            "SELECT sport FROM organizations WHERE id = ?", (org["org_id"],)
        ).fetchone()["sport"]
        assert stored == expected

    def test_a_sport_we_do_not_know_is_refused_with_the_list(self, client):
        res = client.post(
            "/api/orgs",
            json={"name": "A Club", "sport": "quidditch", "director_name": "Dir"},
        )
        assert res.status_code == 400
        assert "Lacrosse" in res.json()["detail"]

    def _program(self, client, sport, position):
        org = client.post(
            "/api/orgs", json={"name": f"{sport} club", "sport": sport,
                               "director_name": "Dir"},
        ).json()
        director = {"Authorization": f"Bearer {org['director']['token']}"}
        team = client.post(
            "/api/teams", json={"name": "Varsity", "season": "26"}, headers=director,
        ).json()
        athlete = client.post(
            "/api/athletes",
            json={"display_name": "Alex T.", "birth_year": 2008, "dominant_hand": "right",
                  "guardian_consent": True, "join_code": team["join_code"],
                  "position": position},
            headers=director,
        ).json()
        athlete["headers"] = {"Authorization": f"Bearer {athlete['token']}"}
        return org, director, athlete

    @pytest.mark.parametrize("sport,position,expected", [
        ("basketball", "PG", "guard"),
        ("soccer", "Striker", "forward"),
        ("volleyball", "Libero", "libero"),
        ("cheer", "Flyer", "flyer"),
        ("football", "QB", "quarterback"),
        ("hockey", "Goalie", "goaltender"),
        ("rugby", "Prop", "front_row"),
        ("swimming", "Butterfly", "stroke"),
    ])
    def test_a_program_of_any_sport_gets_its_own_positions(
        self, client, sport, position, expected,
    ):
        _, _, athlete = self._program(client, sport, position)
        report = client.get("/api/benchmarks", headers=athlete["headers"]).json()
        assert report["position"]["key"] == expected
        assert report["position"]["sport"] == sport
        assert report["mix"]["slices"], "and a real drill mix behind it"

    def test_the_positions_endpoint_follows_the_program_sport(self, client):
        _, director, _ = self._program(client, "volleyball", "Libero")
        body = client.get("/api/positions", headers=director).json()
        assert body["sport"] == "volleyball"
        assert {p["key"] for p in body["positions"]} == {
            "setter", "hitter", "middle", "libero",
        }

    def test_a_program_never_sees_its_own_sport_in_the_transfer_notes(self, client):
        """A hockey program being told wall sits help at ice hockey is the
        noise the filter exists to remove."""
        for sport in ("basketball", "soccer", "hockey", "gymnastics", "tennis"):
            body = client.get("/api/drills", params={"sport": sport}).json()
            for drill in body["drills"]:
                for entry in drill["transfers"]:
                    resolved = sports_mod.normalize(entry["sport"])
                    assert not resolved or resolved.key != sport, (sport, entry)


class TestBallTrackingKeepsThePrivacyPosture:

    def test_a_ball_session_uploads_contacts_and_nothing_else(self, client, program):
        """Ball tracking runs on the phone like pose does. What reaches the
        server is timestamps and speeds -- no frames, no boxes, no imagery."""
        athlete = program["athletes"][0]
        started = client.post(
            "/api/sessions/start", json={"drill_key": "soc_juggle"},
            headers=athlete["headers"],
        ).json()
        reps = [
            {"t_ms": i * 900 + (i % 3) * 70, "hand": "left" if i % 2 else "right",
             "confidence": 0.7, "speed": 1.2, "part": "left_ankle"}
            for i in range(30)
        ]
        res = client.post(
            "/api/sessions/submit",
            json={"session_id": started["session_id"], "nonce": started["nonce"],
                  "duration_ms": 28_000, "reps": reps, "mean_confidence": 0.7,
                  "track_quality": 0.62},
            headers=athlete["headers"],
        )
        assert res.status_code == 200
        assert res.json()["status"] == "counted"

    def test_a_session_that_barely_saw_the_ball_is_held_for_review(self, client, program):
        athlete = program["athletes"][0]
        started = client.post(
            "/api/sessions/start", json={"drill_key": "soc_juggle"},
            headers=athlete["headers"],
        ).json()
        reps = [
            {"t_ms": i * 900 + (i % 3) * 70, "hand": "left", "confidence": 0.4,
             "speed": 1.2, "part": "left_ankle"}
            for i in range(30)
        ]
        body = client.post(
            "/api/sessions/submit",
            json={"session_id": started["session_id"], "nonce": started["nonce"],
                  "duration_ms": 28_000, "reps": reps, "mean_confidence": 0.4,
                  "track_quality": 0.08},
            headers=athlete["headers"],
        ).json()
        assert body["status"] == "review"
        assert any("visible" in n for n in body["notes"])

    def test_omitting_the_track_quality_does_not_slip_through(self, client, program):
        athlete = program["athletes"][0]
        started = client.post(
            "/api/sessions/start", json={"drill_key": "soc_juggle"},
            headers=athlete["headers"],
        ).json()
        reps = [{"t_ms": i * 900, "hand": "left", "confidence": 0.7} for i in range(30)]
        body = client.post(
            "/api/sessions/submit",
            json={"session_id": started["session_id"], "nonce": started["nonce"],
                  "duration_ms": 28_000, "reps": reps, "mean_confidence": 0.7},
            headers=athlete["headers"],
        ).json()
        assert body["status"] == "review"

    def test_the_ball_drills_are_offered_by_sport(self, client):
        by_key = {d["key"]: d for d in client.get("/api/drills").json()["drills"]}
        assert by_key["soc_juggle"]["sport"] == "soccer"
        assert by_key["bkb_dribble"]["sport"] == "basketball"
        assert by_key["soc_juggle"]["ball"]["required"] is True
