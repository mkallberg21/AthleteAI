#!/usr/bin/env python3
"""Run the weekly YouTube scan. Cron calls this (Monday 06:17 UTC); you can run it by hand too.

    podman exec offdays_app_1 python scripts/run_video_scout.py

Does nothing, and says so, when OFFDAYS_YOUTUBE_API_KEY is not set. Prints counts only: never the key,
and never a request URL (the URL carries the key). Exit code is 0 unless the scan could not start.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from offdays import video_scout  # noqa: E402
from offdays.db import connect  # noqa: E402
from offdays.store import Store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="database path (defaults to config)")
    parser.add_argument("--week", type=int, default=None, help="which slice of the queries to run (default: this ISO week)")
    args = parser.parse_args()

    api = video_scout.api_from_config()
    if api is None:
        print("video scout: no OFFDAYS_YOUTUBE_API_KEY set, so nothing was scanned. Run scripts/setup_youtube.py.")
        return 0
    store = Store(connect(Path(args.db) if args.db else None))
    try:
        out = video_scout.scan(store.conn, api, week=args.week)
    finally:
        store.close()
    rejected = ", ".join(f"{k}={v}" for k, v in sorted(out.get("rejected", {}).items())) or "none"
    print(f"video scout: searched {out['searched']}, added {out['added']}, "
          f"stopped={out['stopped'] or 'no'}; turned away: {rejected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
