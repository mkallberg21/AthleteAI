"""Self-monitoring for a deployed 0FFDAYS instance.

This is a *checking* module, not an agent. The app is single-process,
single-DB, stdlib-only, and usually run directly by `uvicorn` — the right
level of monitoring is:

* an /api/health endpoint that probes the *real* things (DB reachable, schema
  current, WAL size, stuck sessions, disk space) instead of returning
  {"status": "ok"} every time;
* a FastAPI lifespan hook that runs integrity + migration on startup and
  checkpoints WAL on clean shutdown;
* a small cron-able reaper (``scripts/health_reap.py``) that does the work
  that should not happen inside a request: WAL checkpoint, expired-session
  cleanup, disk alarm, and an optional live backup via the SQLite backup API.

Nothing here is required for the app to start. If the health module cannot
read the database it reports the failure in the health payload rather than
crashing the process — a monitoring probe that takes down the app is worse
than no probe.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import __version__
from .config import CONFIG
from .db import connect, init_db, SCHEMA_VERSION, migrate

# ---------------------------------------------------------------------------
# One probe connection. Created at import time so the health endpoint can
# answer without opening a fresh connection per request. Wrapped in its own
# try/except: a monitoring endpoint that crashes the app is the wrong tradeoff.
# ---------------------------------------------------------------------------
_db_ok: bool = False
_probe_conn: sqlite3.Connection | None = None
_probe_err: str | None = None

try:
    _probe_conn = connect()
    _probe_conn.execute("SELECT 1")
    _db_ok = True
except Exception as exc:
    _probe_err = str(exc)


# Thresholds an operator cares about — stated once so the health endpoint and
# the reaper agree about what "bad" means.
WAL_BYTES_WARNING = 50 * 1024 * 1024      # 50 MB of growth without a checkpoint
WAL_BYTES_CRITICAL = 200 * 1024 * 1024    # 200 MB — definitely checkpoint this
STUCK_SESSION_HOURS = 24                   # open sessions older than this leak
STUCK_SESSION_THRESHOLD = 50               # above this, surface in health
DISK_PERCENT_FREE_MIN = 10.0               # below this, serve a degraded signal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat()


def _cutoff_iso(hours_ago: float) -> str:
    import datetime as _dt

    return (
        _dt.datetime.now(tz=_dt.timezone.utc)
        - _dt.timedelta(hours=hours_ago)
    ).isoformat()


def _wal_path() -> Path:
    db = Path(CONFIG.db_path)
    return Path(str(db) + "-wal")


def _wal_bytes() -> int | None:
    try:
        p = _wal_path()
        if p.exists():
            return p.stat().st_size
    except Exception:
        pass
    return None


def _disk() -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(Path(CONFIG.db_path).parent)
        free_mb = usage.free / (1024 * 1024)
        total_mb = usage.total / (1024 * 1024)
        pct = 100.0 * usage.free / usage.total if usage.total else 0.0
        return {
            "free_mb": round(free_mb, 1),
            "total_mb": round(total_mb, 1),
            "percent_free": round(pct, 1),
            "alert": pct < DISK_PERCENT_FREE_MIN,
        }
    except Exception:
        return {"error": "unreachable"}


# ---------------------------------------------------------------------------
# DB payload — what /api/health returns about the database
# ---------------------------------------------------------------------------

def db_payload() -> dict[str, Any]:
    """Diagnostics about the database the app is running on.

    Returned inside /api/health so an operator or a load balancer can tell the
    difference between "process is alive" and "process is alive and the DB it
    needs is actually reachable and at the right schema version".
    """
    if not _db_ok:
        return {
            "db": "unreachable",
            "reason": _probe_err,
            "schema_version": None,
            "expected_schema_version": SCHEMA_VERSION,
        }

    # Read-only probe, wrapped so a bad query does not take down the probe.
    try:
        row = _probe_conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        stored = int(row["value"]) if row else None
    except Exception:
        stored = None

    try:
        cutoff = _cutoff_iso(STUCK_SESSION_HOURS)
        stuck = _probe_conn.execute(
            "SELECT COUNT(*) FROM sessions "
            "WHERE status = 'open' AND started_at < ?",
            (cutoff,),
        ).fetchone()[0]
    except Exception:
        stuck = None

    try:
        tables = sorted(
            r[0]
            for r in _probe_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        )
    except Exception:
        tables = []

    return {
        "db": "ok",
        "schema_version": stored,
        "expected_schema_version": SCHEMA_VERSION,
        "schema_current": stored == SCHEMA_VERSION,
        "tables": tables,
        "stuck_open_sessions": stuck,
        "wal_file_bytes": _wal_bytes(),
    }


# ---------------------------------------------------------------------------
# Public health signal
# ---------------------------------------------------------------------------

def health_summary() -> dict[str, Any]:
    """Aggregate readiness signal returned by /api/health.

    Composed of db + disk + a small local-state check so a single GET tells an
    operator whether the instance is healthy enough to serve traffic.
    """
    issues: list[str] = []

    db = db_payload()
    if db.get("db") != "ok":
        issues.append("db unreachable")
    elif not db.get("schema_current"):
        issues.append(
            f"schema_version {db.get('schema_version')} != expected {db.get('expected_schema_version')}"
        )

    stuck = db.get("stuck_open_sessions")
    if stuck is not None and stuck > STUCK_SESSION_THRESHOLD:
        issues.append(
            f"stuck_open_sessions={stuck} (threshold {STUCK_SESSION_THRESHOLD})"
        )

    wal = db.get("wal_file_bytes")
    if wal is not None and wal > WAL_BYTES_WARNING:
        issues.append(f"wal_file_bytes={wal} (warning {WAL_BYTES_WARNING})")

    disk = _disk()
    if isinstance(disk, dict) and disk.get("alert"):
        issues.append(
            f"disk_percent_free={disk.get('percent_free')} (min {DISK_PERCENT_FREE_MIN})"
        )

    return {
        "status": "ok" if not issues else "degraded",
        "issues": issues,
        "version": __version__,
        "db": db,
        "disk": disk,
        "utc_now": _utcnow_iso(),
    }


# ---------------------------------------------------------------------------
# Actions the reaper (and the shutdown hook) runs
# ---------------------------------------------------------------------------

def checkpoint_wal() -> dict[str, Any]:
    """Checkpoint the WAL so a clean shutdown (or a cron reaper) does not leave
    a multi-GB -wal file behind.

    Safe to call even when the connection is in a bad state: returns a status
    dict rather than raising into a caller that did not expect it.
    """
    if not _db_ok:
        return {"checkpoint": "skipped", "reason": _probe_err or "db unreachable"}
    try:
        before = _wal_bytes() or 0
        _probe_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        _probe_conn.commit()
        after = _wal_bytes() or 0
        return {
            "checkpoint": "ok",
            "wal_before_bytes": before,
            "wal_after_bytes": after,
            "reclaimed_bytes": max(0, before - after),
        }
    except Exception as exc:
        return {"checkpoint": "error", "reason": str(exc)}


def run_integrity_check() -> dict[str, Any]:
    """Full PRAGMA integrity_check. Heavy on a large DB; intended for the reaper
    or a scheduled job, not for a per-request health probe.
    """
    if not _db_ok:
        return {"integrity": "skipped", "reason": _probe_err or "db unreachable"}
    try:
        row = _probe_conn.execute("PRAGMA integrity_check").fetchone()
        ok = row[0] == "ok" if row else False
        return {"integrity": row[0] if row else "unknown", "integrity_ok": ok}
    except Exception as exc:
        return {"integrity": "error", "reason": str(exc)}


def clean_stuck_sessions() -> dict[str, Any]:
    """Mark open sessions that have been open longer than STUCK_SESSION_HOURS as
    abandoned so they stop showing up as active in the review queue and the
    athlete's own history.

    Idempotent and safe to run from cron on every tick — the WHERE clause is the
    dedupe. Returns how many rows were affected so the reaper can log it.
    """
    if not _db_ok:
        return {"cleaned": 0, "reason": _probe_err or "db unreachable"}
    try:
        cutoff = _cutoff_iso(STUCK_SESSION_HOURS)
        # A soft transition: mark them 'abandoned' rather than deleting. Keeps
        # the history legible for a coach or an audit without filling the active
        # queue with stale rows.
        n = _probe_conn.execute(
            "UPDATE sessions SET status = 'abandoned' "
            "WHERE status = 'open' AND started_at < ?",
            (cutoff,),
        ).rowcount
        _probe_conn.commit()
        return {"cleaned": n, "cutoff_hours": STUCK_SESSION_HOURS}
    except Exception as exc:
        return {"cleaned": -1, "reason": str(exc)}


def migrate_if_needed() -> dict[str, Any]:
    """Apply missing columns / schema upgrades if this start sees a stale DB.

    Called from the lifespan startup hook so a deployed instance upgrades itself
    on restart rather than requiring a separate migration command. Idempotent.
    """
    if not _db_ok:
        return {"migrate": "skipped", "reason": _probe_err or "db unreachable"}
    try:
        before = _schema_version()
        migrate(_probe_conn)
        after = _schema_version()
        _probe_conn.commit()
        return {
            "migrate": "ok",
            "schema_version_before": before,
            "schema_version_after": after,
            "upgraded": after is not None and before is not None and after > before,
        }
    except Exception as exc:
        return {"migrate": "error", "reason": str(exc)}


def _schema_version() -> int | None:
    try:
        row = _probe_conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        return int(row["value"]) if row else None
    except Exception:
        return None


@contextmanager
def backup_conn():
    """Context manager yielding a second connection suitable for the SQLite
    backup API (online backup without stopping the web server).

    The web server already runs with ``check_same_thread=False``, so a separate
    process/script can open its own connection and call ``conn.backup(target)``
    against a target file while the app keeps serving. This helper is the
    reaper's tool for taking a live backup.
    """
    conn = connect()
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def live_backup(target: Path | str) -> dict[str, Any]:
    """Take a live backup of the current database to *target* without stopping
    the web server.

    Uses the SQLite online-backup API so the source DB can keep being written to
    during the copy. At the sizes this app runs at (tens of MB, not GB) the copy
    finishes fast enough that this is realistic as a daily cron job.

    Returns the path and size of the backup file on success, or an error dict.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with backup_conn() as src:
            bak = sqlite3.connect(str(target))
            try:
                src.backup(bak)
                bak.commit()
            finally:
                bak.close()
        size = target.stat().st_size
        return {
            "backup": "ok",
            "path": str(target),
            "bytes": size,
            "bytes_human": _human_bytes(size),
        }
    except Exception as exc:
        return {"backup": "error", "reason": str(exc)}


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
