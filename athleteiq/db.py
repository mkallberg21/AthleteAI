"""SQLite storage layer.

Deliberately stdlib-only (`sqlite3`) -- no ORM. The schema is small and the
queries are mostly aggregations, so an ORM would add a dependency and a layer
of indirection without buying much. Swapping to Postgres later means changing
this module and nothing else.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import CONFIG

SCHEMA_VERSION = 1

SCHEMA = """
PRAGMA foreign_keys = ON;

-- A program: a club, school athletic department, or organization.
CREATE TABLE IF NOT EXISTS organizations (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    sport       TEXT NOT NULL DEFAULT 'lacrosse',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    id          INTEGER PRIMARY KEY,
    org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    season      TEXT NOT NULL DEFAULT '',
    -- Athletes self-serve onboarding with this code; no email needed, which
    -- matters when the athletes are 12 and do not have school email.
    join_code   TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_teams_org ON teams(org_id);

CREATE TABLE IF NOT EXISTS users (
    id               INTEGER PRIMARY KEY,
    org_id           INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role IN ('athlete','coach','director')),
    display_name     TEXT NOT NULL,
    email            TEXT,
    birth_year       INTEGER,
    -- Timestamp of recorded guardian consent. NULL for a minor means their
    -- name is withheld from shared leaderboards.
    guardian_consent_at TEXT,
    -- Athlete's stated dominant hand, so the scorer knows which side is the
    -- off-hand rather than assuming right.
    dominant_hand    TEXT CHECK (dominant_hand IN ('left','right')),
    token_hash       TEXT NOT NULL UNIQUE,
    created_at       TEXT NOT NULL,
    active           INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_users_org_role ON users(org_id, role);
CREATE INDEX IF NOT EXISTS idx_users_token ON users(token_hash);

CREATE TABLE IF NOT EXISTS team_members (
    team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    jersey      TEXT,
    position    TEXT,
    joined_at   TEXT NOT NULL,
    PRIMARY KEY (team_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_team_members_user ON team_members(user_id);

-- One recording. Contains no video and no frames -- only derived counts.
CREATE TABLE IF NOT EXISTS sessions (
    id               INTEGER PRIMARY KEY,
    athlete_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drill_key        TEXT NOT NULL,
    -- Issued at session start and required at submit, so a replayed or
    -- fabricated payload cannot be posted twice.
    nonce            TEXT NOT NULL UNIQUE,
    started_at       TEXT NOT NULL,
    submitted_at     TEXT,
    duration_ms      INTEGER NOT NULL DEFAULT 0,
    reps_total       INTEGER NOT NULL DEFAULT 0,
    reps_left        INTEGER NOT NULL DEFAULT 0,
    reps_right       INTEGER NOT NULL DEFAULT 0,
    hold_ms          INTEGER NOT NULL DEFAULT 0,
    mean_confidence  REAL NOT NULL DEFAULT 0.0,
    cadence_cv       REAL NOT NULL DEFAULT 0.0,
    integrity_score  REAL NOT NULL DEFAULT 0.0,
    integrity_notes  TEXT NOT NULL DEFAULT '',
    xp_awarded       INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'open'
                     CHECK (status IN ('open','counted','review','rejected')),
    client_version   TEXT NOT NULL DEFAULT '',
    device_label     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_athlete ON sessions(athlete_id, submitted_at);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

-- Per-rep timings, retained briefly for integrity review then pruned.
CREATE TABLE IF NOT EXISTS rep_events (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    t_ms        INTEGER NOT NULL,
    hand        TEXT CHECK (hand IN ('left','right','none')),
    confidence  REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_rep_events_session ON rep_events(session_id);

-- Append-only XP record. Every leaderboard and streak is derived from this,
-- so a scoring bug can be audited and recomputed rather than guessed at.
CREATE TABLE IF NOT EXISTS xp_ledger (
    id          INTEGER PRIMARY KEY,
    athlete_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id  INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    amount      INTEGER NOT NULL,
    reason      TEXT NOT NULL,
    day         TEXT NOT NULL,          -- YYYY-MM-DD, athlete-local
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_xp_athlete_day ON xp_ledger(athlete_id, day);

CREATE TABLE IF NOT EXISTS badges (
    id          INTEGER PRIMARY KEY,
    athlete_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    badge_key   TEXT NOT NULL,
    awarded_at  TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    UNIQUE (athlete_id, badge_key)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def hash_token(token: str) -> str:
    """Tokens are stored hashed so a database leak is not a credential leak."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_join_code() -> str:
    """Short, unambiguous team code an athlete can type from a whiteboard.

    Excludes characters that get misread when a 12-year-old copies them off a
    locker room wall: O/0, I/1, S/5.
    """
    alphabet = "ABCDEFGHJKLMNPQRTUVWXYZ234679"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or CONFIG.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets the coach dashboard read while athletes are submitting.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on any exception."""
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
