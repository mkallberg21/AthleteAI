"""The privacy policy's retention promises are kept by the scheduled job.

The policy says per-rep timings are removed after 45 days and shared clips
after 30. The first was a method nobody called; these tests run the job
itself, so a promise made on the privacy page cannot quietly stop being kept.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from offdays.db import connect
from offdays.store import Store

ROOT = Path(__file__).resolve().parent.parent


def _iso(d: datetime) -> str:
    return d.isoformat()


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.db"
    store = Store(connect(path))
    org = store.create_org("Club")
    athlete = store.create_user(org, "athlete", "Mason Reed")
    return path, store, athlete["id"]


def _session(store, athlete_id, submitted_at, nonce):
    cur = store.conn.execute(
        "INSERT INTO sessions(athlete_id, drill_key, nonce, started_at, submitted_at, status) "
        "VALUES (?, 'wall_ball', ?, ?, ?, 'counted')",
        (athlete_id, nonce, submitted_at, submitted_at),
    )
    return int(cur.lastrowid)


def _rep_event(store, session_id):
    cols = [r["name"] for r in store.conn.execute("PRAGMA table_info(rep_events)")]
    values = {"session_id": session_id, "t_ms": 1000, "idx": 1}
    insert = {c: v for c, v in values.items() if c in cols}
    for r in store.conn.execute("PRAGMA table_info(rep_events)"):
        if r["notnull"] and r["name"] not in insert and r["dflt_value"] is None and not r["pk"]:
            insert[r["name"]] = 0
    names = ",".join(insert)
    store.conn.execute(
        f"INSERT INTO rep_events({names}) VALUES ({','.join('?' for _ in insert)})", tuple(insert.values()))


def _count(store):
    return store.conn.execute("SELECT COUNT(*) AS n FROM rep_events").fetchone()["n"]


def test_the_daily_job_prunes_rep_timings_past_45_days(db):
    path, store, athlete = db
    now = datetime.now(timezone.utc)
    old = _session(store, athlete, _iso(now - timedelta(days=60)), "old")
    new = _session(store, athlete, _iso(now - timedelta(days=5)), "new")
    _rep_event(store, old)
    _rep_event(store, new)
    store.conn.commit()
    assert _count(store) == 2

    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_notifications.py"), "--db", str(path), "--no-email"],
        capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr[-600:]

    after = connect(path)
    assert after.execute("SELECT COUNT(*) AS n FROM rep_events").fetchone()["n"] == 1
    kept = after.execute("SELECT session_id FROM rep_events").fetchone()["session_id"]
    assert kept == new, "the recent session's timings stay"
    assert after.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"] == 2, \
        "only the granular stream goes; the session record is kept"
    assert "pruned 1 per-rep timings" in out.stdout


def test_the_policy_page_states_the_windows_the_code_enforces():
    from offdays.config import CONFIG
    html = (ROOT / "offdays" / "web" / "static" / "privacy.html").read_text(encoding="utf-8")
    assert f"pruned after {CONFIG.rep_event_retention_days} days" in html
    assert f"deleted after {Store.CLIP_RETENTION_DAYS} days" in html
