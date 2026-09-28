#!/usr/bin/env python3
"""Run every roster link a coach has put on auto-sync. Run this on a schedule.

    # every six hours is plenty -- run_due skips links synced in the last 12h
    30 */6 * * *  podman exec offdays_app_1 python scripts/run_roster_sync.py

`roster_sync.run_due` existed and was tested, but nothing called it, so the
"auto-sync" switch on the coach dashboard recorded a preference and then never
acted on it. This is the caller.

Failures are recorded on each link (where the owning coach sees them), not
raised here; the exit code is non-zero only when every due link failed, so a
cron mailer or log watcher notices a systemic problem (network, DNS) without
paging on one expired token.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from offdays import roster_sync  # noqa: E402
from offdays.db import connect  # noqa: E402
from offdays.store import Store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="database path (defaults to config)")
    parser.add_argument(
        "--older-than-hours", type=int, default=12,
        help="only sync links that have not run in this many hours",
    )
    args = parser.parse_args()

    store = Store(connect(Path(args.db) if args.db else None))
    try:
        result = roster_sync.run_due(store, older_than_hours=args.older_than_hours)
    finally:
        store.close()

    print(f"roster sync: {result['ran']} ran, {result['failed']} failed")
    if result["failed"] and result["failed"] >= result["ran"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
