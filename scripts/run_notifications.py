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
    parser.add_argument(
        "--digest", action="store_true",
        help="send the weekly coach digest now, whatever day it is",
    )
    parser.add_argument(
        "--no-email", action="store_true",
        help="compose digests and post them in-app without queueing or sending mail",
    )
    parser.add_argument(
        "--flush-only", action="store_true",
        help="skip generation; only attempt delivery of what is already queued",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    conn = connect(Path(args.db) if args.db else None)

    if args.flush_only:
        from athleteiq import mailer

        stats = mailer.flush(conn)
        print(
            f"mail: {stats['sent']} sent, {stats['retrying']} retrying, "
            f"{stats['failed']} failed, {stats['suppressed']} suppressed"
        )
        return 0

    made = notify.run_all(conn)
    total = sum(made.values())
    print(f"generated {total}: " + ", ".join(f"{k}={v}" for k, v in made.items()))

    # The coach digest goes out once a week. Gated on the weekday rather than on
    # a separate cron entry so there is one scheduled job to configure, and
    # deduped by week so running it twice on a Monday is harmless.
    from datetime import date

    if args.digest or date.today().weekday() == 0:
        result = notify.send_coach_digests(conn, dry_run=args.no_email)
        print(
            f"digests: {result['composed']} composed, {result['queued']} queued, "
            f"{result['not_queued']} not queued"
        )

    # Delivery runs on every tick, not just Monday. Queueing and sending are
    # separate steps so a retry does not have to wait a week for the next
    # scheduled composition.
    if not args.no_email:
        from athleteiq import mailer

        stats = mailer.flush(conn)
        if any(stats.values()):
            print(
                f"mail: {stats['sent']} sent, {stats['retrying']} retrying, "
                f"{stats['failed']} failed, {stats['suppressed']} suppressed"
            )

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
