"""A player who trained today shows as trained today, even when that session earned no XP."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays.db import connect
from offdays.store import Store


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def db():
    return api_module._store.conn


def make(client):
    made = client.post("/api/orgs", json={"name": "Nashville Dogs", "sport": "lacrosse", "accept_terms": True,
                                          "director_name": "Matt"}).json()
    h = {"Authorization": f"Bearer {made['director']['token']}"}
    team = client.post("/api/teams", json={"name": "2031 Red"}, headers=h).json()["id"]
    client.post("/api/coach/roster/import", headers=h, json={
        "content": "First Name,Last Name,Birth Year\nRyder,Cole,2013\n", "team_id": team, "invite_guardians": False})
    ryder = [r["athlete_id"] for r in client.get("/api/coach/team-ranking", headers=h).json()["rows"]][0]
    return h, ryder, made["org_id"]


def session(athlete, days_ago=0, status="counted", xp=0, own=False):
    when = (datetime.now(timezone.utc) - timedelta(days=days_ago, hours=0)).isoformat(timespec="seconds")
    cur = db().execute(
        "INSERT INTO sessions(athlete_id, drill_key, nonce, started_at, submitted_at, completed_at, duration_ms, reps_total, status, "
        "integrity_notes, self_reported) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (athlete, "lax_wall_ball_strong", uuid.uuid4().hex, when, when, when, 156000, 76, status, "[]", 1 if own else 0))
    sid = cur.lastrowid
    if xp:
        day = (datetime.now(timezone.utc) - timedelta(days=days_ago)).date().isoformat()
        db().execute("INSERT INTO xp_ledger(athlete_id, session_id, amount, reason, day, created_at) VALUES (?,?,?,?,?,?)",
                     (athlete, sid, xp, "Wall Ball session", day, when))
    db().commit()
    return sid


TODAY = lambda: datetime.now(timezone.utc).date().isoformat()                     # noqa: E731
YESTERDAY = lambda: (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()   # noqa: E731


def last_active(client, h, ryder):
    rows = client.get("/api/coach/team-ranking", headers=h).json()["rows"]
    return [r for r in rows if r["athlete_id"] == ryder][0]["last_active"]


class TestLastTrained:
    def test_a_session_that_earned_xp_today_is_today(self, client):
        h, ryder, _ = make(client)
        session(ryder, 0, xp=40)
        assert last_active(client, h, ryder) == TODAY()

    def test_a_counted_session_today_that_earned_nothing_is_still_today(self, client):
        """The reported case: XP earned yesterday, today's session counted but earned none (the day's cap was already reached)."""
        h, ryder, _ = make(client)
        session(ryder, 1, xp=40)
        session(ryder, 0, xp=0)
        assert last_active(client, h, ryder) == TODAY()

    def test_the_home_screen_row_and_the_player_panel_agree(self, client):
        h, ryder, _ = make(client)
        session(ryder, 1, xp=40)
        session(ryder, 0, xp=0)
        panel = client.get(f"/api/coach/athletes/{ryder}/training", headers=h).json()["athlete"]["last_active"]
        assert panel == last_active(client, h, ryder) == TODAY()

    def test_a_held_session_is_not_counted_work(self, client):
        h, ryder, _ = make(client)
        session(ryder, 1, xp=40)
        session(ryder, 0, status="review", xp=0)
        assert last_active(client, h, ryder) == YESTERDAY()

    def test_a_rejected_or_open_session_does_not_count_either(self, client):
        h, ryder, _ = make(client)
        session(ryder, 3, xp=40)
        session(ryder, 0, status="rejected")
        session(ryder, 0, status="open")
        assert last_active(client, h, ryder) == (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()

    def test_logged_work_counts_for_showing_up(self, client):
        h, ryder, _ = make(client)
        session(ryder, 2, xp=40)
        session(ryder, 0, own=True)
        assert last_active(client, h, ryder) == TODAY()

    def test_someone_who_never_trained_has_none(self, client):
        h, ryder, _ = make(client)
        assert last_active(client, h, ryder) is None

    def test_one_players_work_does_not_move_anothers(self, client):
        h, ryder, org = make(client)
        other = api_module._store.create_user(org, "athlete", "Sam Other", birth_year=2013)
        session(other["id"], 0, xp=10)
        assert last_active(client, h, ryder) is None

    def test_the_home_dashboard_says_today(self, client):
        h, ryder, _ = make(client)
        session(ryder, 1, xp=40)
        session(ryder, 0, xp=0)
        home = client.get("/api/coach/overview", headers=h).json()
        team = home["teams"][0]
        assert team["last_active"] == TODAY()

    def test_ranking_xp_is_unchanged_by_a_zero_xp_session(self, client):
        h, ryder, org = make(client)
        session(ryder, 1, xp=40)
        rows = client.get("/api/coach/team-ranking", headers=h).json()["rows"]
        before = [r for r in rows if r["athlete_id"] == ryder][0]["xp"]
        session(ryder, 0, xp=0)
        rows = client.get("/api/coach/team-ranking", headers=h).json()["rows"]
        assert [r for r in rows if r["athlete_id"] == ryder][0]["xp"] == before > 0
