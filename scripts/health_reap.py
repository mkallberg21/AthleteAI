#!/usr/bin/env python3
"""Periodic health + repair job for a deployed 0FFDAYS instance.

Run this on a schedule (cron, supervisor, systemd timer) every 15-60 minutes.
It does the things that should *not* happen inside a request handler:

* checkpoint the WAL so the -wal file does not grow without bound;
* mark open sessions older than 24h as abandoned so they stop leaking into the
  review queue and the athlete's own history;
* surface a disk-space alarm if the filesystem around the DB is getting full;
* optionally take a live backup via the SQLite backup API (no need to stop the
  web server first at this DB size);
* optionally run a full PRAGMA integrity_check (heavy; daily is plenty).

Safe to run as often as you like: every operation is either idempotent or
deduped by a WHERE clause. The web app keeps serving while this runs.

    # every 15 minutes: checkpoint + stale cleanup + disk alarm
    */15 * * * *  cd /srv/offdays && python scripts/health_reap.py

    # once a day, off-peak: add a live backup + integrity check
    30 3 * * *    cd /srv/offdays && python scripts/health_reap.py \\
                       --backup backups/offdays-$(date +\\%F).db --integrity

The app's own /api/health, /api/ready, and /api/live endpoints surface the same
signals to a load balancer or an operator without needing this script.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from offdays import health as health_mod
from offdays.config import CONFIG

logger = logging.getLogger("offdays.health_reap")


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _record(kind: str, label: str, payload: dict) -> None:
    line = f"[{_now_iso()}] health_reap {kind} {label} " + str(payload)
    if payload.get("error") or payload.get("reason") or payload.get("integrity") == "error":
        logger.warning(line)
    else:
        logger.info(line)


def run(
    *,
    checkpoint: bool,
    clean: bool,
    disk: bool,
    integrity: bool,
    backup: Path | None,
) -> int:
    failures = 0

    if checkpoint:
        _record("checkpoint", "wal", health_mod.checkpoint_wal())

    if clean:
        _record("clean", "stuck_sessions", health_mod.clean_stuck_sessions())

    if disk:
        _record("disk", "usage", health_mod._disk())

    if integrity:
        _record("integrity", "check", health_mod.run_integrity_check())

    if backup:
        _record("backup", str(backup), health_mod.live_backup(backup))

    # Summary from the live health endpoint so the last line of output is the
    # same signal a load balancer would see.
    summary = health_mod.health_summary()
    _record("summary", "health", summary)
    if summary.get("status") != "ok":
        failures += 1

    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        default=None,
        help="database path (defaults to CONFIG.db_path)",
    )
    ap.add_argument(
        "--quiet",
        action="store_true",
        help="only log warnings/errors, not the routine per-step lines",
    )
    ap.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="skip WAL checkpoint (useful when you only want cleanup + backup)",
    )
    ap.add_argument(
        "--no-clean",
        action="store_true",
        help="skip stale-session cleanup",
    )
    ap.add_argument(
        "--no-disk",
        action="store_true",
        help="skip disk-space alarm",
    )
    ap.add_argument(
        "--integrity",
        action="store_true",
        help="run a full PRAGMA integrity_check (heavy; daily is plenty)",
    )
    ap.add_argument(
        "--backup",
        default=None,
        help="take a live backup to this path (e.g. backups/offdays-2026-09-03.db)",
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if not args.quiet else logging.WARNING,
        format="%(message)s",
    )

    if args.db:
        CONFIG.db_path = Path(args.db)

    steps = dict(
        checkpoint=not args.no_checkpoint,
        clean=not args.no_clean,
        disk=not args.no_disk,
        integrity=args.integrity,
        backup=Path(args.backup) if args.backup else None,
    )

    if not any(steps.values()):
        print("nothing to do. Pass at least one of --checkpoint, --clean, "
              "--disk, --integrity, --backup", file=sys.stderr)
        return 2

    return run(**steps)


if __name__ == "__main__":
    raise SystemExit(main())
