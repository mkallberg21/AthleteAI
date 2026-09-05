#!/usr/bin/env python3
"""Refresh pre-fetched OCSP responses for SNS signing certificates.

Run on a schedule, well ahead of anything expiring:

    */30 * * * *  cd /srv/offdays && python scripts/refresh_staples.py

This is what moves revocation freshness off the request path. With staples kept
current, verifying a bounce webhook makes no network call at all, and
OFFDAYS_SNS_REVOCATION_STRICT=1 becomes practical: refusing a certificate
that cannot be proved good stops being an availability risk, because a missing
staple is a condition this job reports rather than a race decided per request.

Certificates are discovered from the SNS endpoints already seen in the webhook
log, so there is nothing to configure by hand.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from offdays import chain as chain_mod  # noqa: E402
from offdays import sns as sns_mod  # noqa: E402
from offdays import staple as staple_mod  # noqa: E402
from offdays.config import CONFIG  # noqa: E402
from offdays.db import connect, init_db  # noqa: E402


def known_cert_urls(conn) -> list[str]:
    """Signing-certificate URLs seen on real SNS traffic.

    Read from the stored webhook payloads rather than configured separately:
    the certificates worth stapling are exactly the ones already in use, and a
    second list to maintain is a second list to get wrong.
    """
    import json

    urls = []
    for row in conn.execute(
        "SELECT raw FROM webhook_events WHERE provider = 'ses' "
        "ORDER BY received_at DESC LIMIT 200"
    ):
        try:
            payload = json.loads(row["raw"] or "{}")
        except ValueError:
            continue
        url = payload.get("SigningCertURL") or payload.get("SigningCertUrl")
        if url and sns_mod.is_aws_url(url) and url not in urls:
            urls.append(url)
    return urls


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None)
    parser.add_argument(
        "--url", action="append", default=[],
        help="a signing-certificate URL to staple (repeatable)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="refresh even staples that are not near expiry",
    )
    parser.add_argument("--prune", action="store_true", help="drop long-stale staples")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    conn = connect(Path(args.db) if args.db else None)
    # Applies any pending migrations: a database created by an older
    # release will not have the tables this job reads.
    init_db(conn)
    urls = args.url or known_cert_urls(conn)

    if not urls:
        print("no SNS signing certificates seen yet; nothing to staple")
        return 0

    anchors = sns_mod.trust_anchors()
    refreshed = failed = 0

    for url in urls:
        try:
            pem = sns_mod.fetch_certificate(url)
            path = chain_mod.validate_pem(pem, anchors)
        except Exception as exc:  # noqa: BLE001 -- report and continue
            print(f"  {url}: could not fetch or validate: {exc}")
            failed += 1
            continue

        staples = staple_mod.refresh_chain(conn, path, force=args.force)
        for entry in staples:
            marker = "REVOKED" if entry.status == "revoked" else "ok"
            print(f"  {entry.subject[:56]:<58} {marker:<8} until {entry.next_update}")
        refreshed += len(staples)
        # A path where nothing could be stapled is worth saying out loud: it is
        # the state that makes strict mode start refusing webhooks.
        if not staples:
            print(f"  {url}: no OCSP responder answered for any certificate in the chain")
            failed += 1

    if args.prune:
        dropped = staple_mod.prune(conn)
        print(f"pruned {dropped} long-stale staples")

    summary = staple_mod.summary(conn)
    print(
        f"\n{refreshed} refreshed, {failed} failed · "
        f"{summary['fresh']} fresh, {summary['stale']} stale, "
        f"{summary['due_refresh']} due"
    )
    if summary["revoked"]:
        print(f"WARNING: {summary['revoked']} stapled certificate(s) are REVOKED")
        return 2
    return 1 if failed and not refreshed else 0


if __name__ == "__main__":
    raise SystemExit(main())
