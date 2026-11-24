#!/usr/bin/env python3
"""Why did "Forgot your password?" send nothing? Says, for one address, what the server knows.

The sign-in page gives the same answer for every address on purpose, so it can never say who has an account. That
also means it cannot tell a real person why their link did not come. This does, for the operator. It only reads.

    podman exec -it offdays_app_1 python scripts/login_status.py someone@example.com

It prints whether the address is a sign-in, whether it was confirmed, what links were made for it, and what happened
to each email sent to it, then one line saying what to do. To get someone back in right away, use
scripts/reset_password.py, which prints a one-time code.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from offdays import mailer, passwords, staff_mail  # noqa: E402


def findings(conn: sqlite3.Connection, email: str, now: datetime | None = None) -> dict:
    """Everything the report is built from, as data (so it can be tested)."""
    now = now or datetime.now(timezone.utc)
    address = passwords.normalise_email(email)
    out: dict = {"email": address, "mail_available": staff_mail.mail_available()}
    out["people"] = [dict(r) for r in conn.execute(
        "SELECT u.id, u.role, u.display_name, u.active, o.name AS org FROM users u "
        "JOIN organizations o ON o.id = u.org_id WHERE lower(trim(COALESCE(u.email, ''))) = ? ORDER BY u.id",
        (address,))]
    cred = passwords.by_email(conn, address)
    out["login"] = None
    if cred is not None:
        user = conn.execute(
            "SELECT u.id, u.role, u.display_name, u.active, u.org_id, o.name AS org FROM users u "
            "JOIN organizations o ON o.id = u.org_id WHERE u.id = ?", (cred["user_id"],)).fetchone()
        since = (now - timedelta(hours=1)).isoformat()
        out["login"] = {
            "user_id": int(cred["user_id"]), "role": user["role"], "name": user["display_name"], "org": user["org"],
            "active": bool(user["active"]), "confirmed_at": cred["email_verified_at"],
            "held": user["role"] in ("guardian", "athlete") and mailer.mail_held(conn, user["org_id"]),
            "links_last_hour": int(conn.execute(
                "SELECT COUNT(*) FROM email_tokens WHERE user_id = ? AND purpose = 'reset' AND created_at >= ?",
                (cred["user_id"], since)).fetchone()[0]),
            "links": [dict(r) for r in conn.execute(
                "SELECT purpose, created_at, expires_at, used_at FROM email_tokens WHERE user_id = ? "
                "ORDER BY id DESC LIMIT 6", (cred["user_id"],))],
        }
    sup = conn.execute("SELECT reason, created_at FROM email_suppressions WHERE email = ?", (address,)).fetchone()
    out["suppressed"] = dict(sup) if sup else None
    out["mail"] = [dict(r) for r in conn.execute(
        "SELECT subject, status, attempts, last_error, queued_at, sent_at FROM email_outbox "
        "WHERE lower(to_email) = ? ORDER BY id DESC LIMIT 8", (address,))]
    out["why"], out["do"] = verdict(out)
    return out


def verdict(f: dict) -> tuple[str, str]:
    """(why no link came, what to do), in plain words. The first reason that applies, in the order the server checks."""
    login = f["login"]
    code = "Run scripts/reset_password.py with this address for a one-time code."
    if not f["mail_available"]:
        return ("This server has no email provider, so no link can be sent to anyone.",
                "Connect a provider, or use a recovery code or scripts/reset_password.py.")
    if login is None:
        if f["people"]:
            who = f["people"][0]
            return (f"{who['display_name']} ({who['role']}) has this address on file but never chose a password, so "
                    "there is no password to reset. They sign in with their link or code.",
                    "Send them a new sign-in link from the Coaches list (a director: sign in with the director code).")
        return ("Nobody has this address. It may be misspelled, or they signed up with a different one.",
                "Check the spelling, or look the person up by name.")
    if not login["confirmed_at"]:
        return ("The address was never confirmed: they chose a password but did not open the confirm link. A reset "
                "link is only sent to a confirmed address.", code)
    if not login["active"]:
        return ("This account has been removed from its program.", "Add them back from the dashboard.")
    if login["held"]:
        return ("This is a parent or athlete and the program's email is on hold.", "The director releases the hold.")
    if f["suppressed"]:
        return (f"Mail to this address is blocked: {f['suppressed']['reason']}",
                "Clear it under Bounces on the dashboard once the address is fixed. " + code)
    if login["links_last_hour"] >= staff_mail.HOURLY_LIMIT:
        return (f"{login['links_last_hour']} links were asked for in the last hour; the limit is "
                f"{staff_mail.HOURLY_LIMIT}.", "Wait an hour, or: " + code)
    resets = [m for m in f["mail"] if "reset" in (m["subject"] or "").lower()]
    if resets and resets[0]["status"] != "sent":
        return (f"The reset email was made but not delivered (status: {resets[0]['status']}; "
                f"{resets[0]['last_error'] or 'no error recorded'}).", "Fix the provider error. " + code)
    if resets:
        return (f"A reset email was handed to the provider at {resets[0]['sent_at']}. If it is not in the inbox it is "
                "in spam, or the provider dropped it.", "Check spam and the provider's log. " + code)
    return ("Everything is in order and no reset has been asked for with this exact address.",
            "Ask again from the sign-in page with this address.")


def render(f: dict) -> str:
    lines = [f"Address: {f['email']}", f"Email provider connected: {'yes' if f['mail_available'] else 'NO'}"]
    login = f["login"]
    if login is None:
        lines.append("Sign-in with a password: none")
        for p in f["people"]:
            lines.append(f"  On file for: {p['display_name']} ({p['role']}, {p['org']}){'' if p['active'] else ' [removed]'}")
    else:
        lines.append(f"Sign-in with a password: {login['name']} ({login['role']}, {login['org']})"
                     f"{'' if login['active'] else ' [removed]'}")
        lines.append(f"  Address confirmed: {login['confirmed_at'] or 'NO'}")
        for t in login["links"]:
            state = "used or replaced" if t["used_at"] else "live"
            lines.append(f"  {t['purpose']} link made {t['created_at']} ({state})")
    if f["suppressed"]:
        lines.append(f"Blocked: {f['suppressed']['reason']} ({f['suppressed']['created_at']})")
    lines.append("Recent email to this address:" if f["mail"] else "Recent email to this address: none")
    for m in f["mail"]:
        lines.append(f"  {m['queued_at']}  {m['status']:<10} {m['subject']}"
                     + (f"  [{m['last_error']}]" if m["last_error"] else ""))
    lines += ["", "Why no link: " + f["why"], "What to do:  " + f["do"]]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or "@" not in argv[1]:
        print(__doc__)
        return 2
    from offdays.config import CONFIG
    from offdays.db import connect
    conn = connect(CONFIG.db_path)
    conn.execute("PRAGMA busy_timeout = 30000")
    print(render(findings(conn, argv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
