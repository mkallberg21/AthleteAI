#!/usr/bin/env python3
"""Grant, change or withdraw a club's sponsorship rebate. Operator only.

There is no automatic rebate. A club gets one when you decide it does, here,
one club at a time, and the rate is recorded on the organisation so every
invoice and every accrual reads it from the same place.

    podman exec offdays_app_1 python scripts/set_rebate.py --list
    podman exec offdays_app_1 python scripts/set_rebate.py --org 3 --rate 0.075
    podman exec offdays_app_1 python scripts/set_rebate.py --org 3 --rate 0

Changing the rate changes what accrues from now on. It does not touch what
has already been credited to the club's balance.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from offdays import billing  # noqa: E402
from offdays.db import connect, init_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="SQLite path (default: the configured one)")
    parser.add_argument("--list", action="store_true", help="show every program and its rate")
    parser.add_argument("--org", type=int, help="organisation id")
    parser.add_argument("--rate", type=float, help="fraction, e.g. 0.075 for 7.5%%; 0 withdraws")
    args = parser.parse_args()

    conn = connect(Path(args.db) if args.db else None)
    init_db(conn)

    if args.list or args.org is None:
        rows = conn.execute(
            "SELECT id, name, COALESCE(sponsorship_rebate_rate, 0) AS r FROM organizations "
            "WHERE kind = 'program' ORDER BY id"
        ).fetchall()
        for r in rows:
            bal = billing.rebate_balance(conn, int(r["id"]))
            print(f"{r['id']:>4}  {r['name']:<32} rate {float(r['r']):>6.1%}   balance ${bal / 100:,.2f}")
        if args.org is None:
            return 0

    if args.rate is None:
        parser.error("--rate is required with --org")
    try:
        rate = billing.set_rebate_rate(conn, args.org, args.rate)
    except billing.BillingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    name = conn.execute("SELECT name FROM organizations WHERE id = ?", (args.org,)).fetchone()["name"]
    print(f"{name}: sponsorship rebate {'withdrawn' if rate == 0 else f'set to {rate:.1%}'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
