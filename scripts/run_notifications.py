#!/usr/bin/env python3
"""Generate and deliver notifications. Run this on a schedule.

    # once an hour is plenty -- every generator dedupes, so extra runs are free
    0 * * * *  cd /srv/athleteiq && python scripts/run_notifications.py

Safe to run as often as you like: every rule carries a dedupe key, so an
athlete gets one "streak at risk" per day no matter how many times this fires.

Web Push activates only when ATHLETEIQ_VAPID_PUBLIC_KEY and
ATHLETEIQ_VAPID_PRIVATE_KEY are set and `pywebpush` is installed. Without them
notifications still generate and appear in the in-app feed -- nothing about the
product depends on a third-party service being configured.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from athleteiq import notifications as notify  # noqa: E402
from athleteiq.config import CONFIG  # noqa: E402
from athleteiq.db import connect  # noqa: E402


def build_channels(quiet: bool) -> list[notify.Channel]:
    channels: list[notify.Channel] = []
    if CONFIG.vapid_private_key and CONFIG.vapid_public_key:
        channels.append(
            notify.WebPushChannel(CONFIG.vapid_private_key, CONFIG.vapid_email)
        )
    if not quiet:
        # Always last, so it records what push could not deliver.
        channels.append(notify.LogChannel())
    return channels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="database path (defaults to config)")
    parser.add_argument(
        "--generate-only", action="store_true", help="create notifications but do not deliver"
    )
    parser.add_argument("--quiet", action="store_true", help="suppress the log channel")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    conn = connect(Path(args.db) if args.db else None)
    made = notify.run_all(conn)
    total = sum(made.values())
    print(f"generated {total}: " + ", ".join(f"{k}={v}" for k, v in made.items()))

    if args.generate_only:
        return 0

    channels = build_channels(args.quiet)
    if not channels:
        print("no delivery channels configured; notifications remain in the in-app feed")
        return 0

    sent = notify.dispatch(conn, channels)
    pushed = "web push + log" if len(channels) > 1 else type(channels[0]).__name__
    print(f"delivered {sent} via {pushed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
