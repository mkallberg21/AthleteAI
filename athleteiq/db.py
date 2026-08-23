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

SCHEMA_VERSION = 5

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
    role             TEXT NOT NULL CHECK (role IN ('athlete','coach','director','guardian')),
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
    device_label     TEXT NOT NULL DEFAULT '',
    -- When the athlete actually finished, as reported by their device. An
    -- offline session recorded Sunday and synced Monday must earn Sunday's
    -- credit, or every dead zone silently breaks a streak.
    completed_at     TEXT,
    -- Cached submit response, replayed verbatim if the client resends. An
    -- offline client that never saw its ack will retry, and it must get the
    -- original result rather than an error or a second score.
    result_json      TEXT,
    -- True when the nonce was handed out ahead of time for offline use.
    reserved         INTEGER NOT NULL DEFAULT 0,
    -- Form quality, 0-100. NULL when the session was too short to judge or the
    -- client reported no per-rep shape data.
    quality_score    INTEGER,
    quality_json     TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_athlete ON sessions(athlete_id, submitted_at);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

-- Per-rep timings, retained briefly for integrity review then pruned.
CREATE TABLE IF NOT EXISTS rep_events (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    t_ms        INTEGER NOT NULL,
    hand        TEXT CHECK (hand IN ('left','right','none')),
    confidence  REAL NOT NULL DEFAULT 0.0,
    -- Shape of the rep: the signal's extreme, the range of motion covered,
    -- and how long the cycle took. This is what form scoring reads.
    peak        REAL,
    rom         REAL,
    cycle_ms    INTEGER
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

-- A coach's prescription. This is what turns free-form logging into a
-- program: the athlete sees what was asked of them, and the coach sees who
-- did it.
CREATE TABLE IF NOT EXISTS assignments (
    id              INTEGER PRIMARY KEY,
    org_id          INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    team_id         INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    created_by      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drill_key       TEXT NOT NULL,
    title           TEXT NOT NULL,
    notes           TEXT NOT NULL DEFAULT '',
    -- Any target may be 0, meaning "not part of this assignment".
    target_reps     INTEGER NOT NULL DEFAULT 0,
    target_sessions INTEGER NOT NULL DEFAULT 0,
    -- Minimum share of reps on the athlete's weaker hand, 0..1.
    min_offhand     REAL NOT NULL DEFAULT 0.0,
    starts_on       TEXT NOT NULL,
    due_on          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_assignments_team ON assignments(team_id, active);

-- Optional narrowing: rows here restrict an assignment to specific athletes.
-- No rows means it applies to the whole team, which is the common case.
CREATE TABLE IF NOT EXISTS assignment_athletes (
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    athlete_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (assignment_id, athlete_id)
);

-- Generated nudges. Stored regardless of whether a push channel is
-- configured, so the in-app feed works with no third-party service at all.
CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    link        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    read_at     TEXT,
    pushed_at   TEXT,
    -- Collapses repeat nudges: one "streak at risk" per athlete per day, not
    -- one per cron tick.
    dedupe_key  TEXT NOT NULL,
    UNIQUE (user_id, dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, created_at);

-- Web Push endpoints, one row per device an athlete has opted in on.
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint    TEXT NOT NULL UNIQUE,
    p256dh      TEXT NOT NULL,
    auth        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    failed_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_push_user ON push_subscriptions(user_id);

-- A day the athlete deliberately rested while carrying enough load to warrant
-- it. These count toward a streak.
--
-- Without this the streak mechanic punishes resting, which turns the whole
-- gamification layer into a risk factor: the athlete most in need of a day off
-- is exactly the one with the longest streak to protect.
CREATE TABLE IF NOT EXISTS recovery_days (
    id          INTEGER PRIMARY KEY,
    athlete_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day         TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    UNIQUE (athlete_id, day)
);
CREATE INDEX IF NOT EXISTS idx_recovery_athlete ON recovery_days(athlete_id, day);

-- Who is responsible for a minor. Many-to-many on purpose: a child can have
-- two parents, and a parent can have three kids in the program.
CREATE TABLE IF NOT EXISTS guardians (
    guardian_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    athlete_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    relationship  TEXT NOT NULL DEFAULT 'parent',
    linked_at     TEXT NOT NULL,
    PRIMARY KEY (guardian_id, athlete_id)
);
CREATE INDEX IF NOT EXISTS idx_guardians_athlete ON guardians(athlete_id);

-- Single-use, expiring invitations. A code that reaches the wrong person grants
-- access to a child's data, so these are short-lived, revocable, and stored
-- hashed like any other credential.
CREATE TABLE IF NOT EXISTS guardian_invites (
    id          INTEGER PRIMARY KEY,
    athlete_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_by  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash   TEXT NOT NULL UNIQUE,
    email       TEXT,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    redeemed_at TEXT,
    redeemed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    revoked_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_invites_athlete ON guardian_invites(athlete_id);

-- Granular, revocable consent. Replaces a single boolean a coach ticked, which
-- was never a consent record -- it recorded that an adult clicked something,
-- not who agreed to what, or when, or whether they later changed their mind.
CREATE TABLE IF NOT EXISTS consents (
    id           INTEGER PRIMARY KEY,
    athlete_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    guardian_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    scope        TEXT NOT NULL,
    granted      INTEGER NOT NULL DEFAULT 1,
    granted_at   TEXT NOT NULL,
    -- What they actually agreed to, so a later policy change cannot be applied
    -- retroactively to a consent given under different terms.
    policy_version TEXT NOT NULL DEFAULT '1',
    method       TEXT NOT NULL DEFAULT 'guardian_portal'
);
CREATE INDEX IF NOT EXISTS idx_consents_athlete ON consents(athlete_id, scope);

-- Deletion leaves the data gone but the fact recorded, so a program can show
-- an auditor that a request was honoured without retaining what was deleted.
CREATE TABLE IF NOT EXISTS erasure_log (
    id            INTEGER PRIMARY KEY,
    athlete_ref   TEXT NOT NULL,
    requested_by  TEXT NOT NULL,
    scope         TEXT NOT NULL,
    rows_removed  INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
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


# Columns added to existing tables after their initial release. `CREATE TABLE
# IF NOT EXISTS` silently skips these on a database that already exists, so
# they have to be applied explicitly or an upgraded deployment reads a schema it
# does not have.
ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("completed_at", "TEXT"),
        ("result_json", "TEXT"),
        ("reserved", "INTEGER NOT NULL DEFAULT 0"),
        ("quality_score", "INTEGER"),
        ("quality_json", "TEXT"),
    ],
    "rep_events": [
        ("peak", "REAL"),
        ("rom", "REAL"),
        ("cycle_ms", "INTEGER"),
    ],
}


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    for table, columns in ADDED_COLUMNS.items():
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            continue
        present = _existing_columns(conn, table)
        for name, decl in columns:
            if name not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _widen_user_roles(conn: sqlite3.Connection) -> None:
    """Allow the 'guardian' role on a database created before it existed.

    SQLite cannot alter a CHECK constraint, so this is the documented
    rebuild-and-rename dance. Guarded by an actual probe rather than a version
    number, so it is safe to run against any vintage of the schema.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    if row is None or "guardian" in (row[0] or ""):
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        columns = ", ".join(sorted(_existing_columns(conn, "users")))
        conn.executescript(
            SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS users ("):]
            .split(");", 1)[0]
            .replace("CREATE TABLE IF NOT EXISTS users (", "CREATE TABLE users_migrated (")
            + ");"
        )
        conn.execute(f"INSERT INTO users_migrated ({columns}) SELECT {columns} FROM users")
        conn.execute("DROP TABLE users")
        conn.execute("ALTER TABLE users_migrated RENAME TO users")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def migrate(conn: sqlite3.Connection) -> int:
    """Bring an existing database up to the current schema.

    Idempotent and probe-driven rather than version-driven, because the version
    counter was being bumped for several releases before this runner existed
    and cannot be trusted to describe what is actually on disk.
    """
    before = conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    _widen_user_roles(conn)
    _add_missing_columns(conn)
    conn.commit()
    return int(before[0]) if before else 0


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    migrate(conn)
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
