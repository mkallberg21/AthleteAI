#!/usr/bin/env python3
"""Reset a coach's or director's password from the server.

This is the LAST resort. Normally a coach resets their own password by email
("Forgot your password?" -> "Email me a link"), and a director can hand a coach a
one-time code from the Coaches list. This script is for the one case neither
covers: a director who has lost every door. It needs shell access to the machine
that holds the database, so only the operator can run it. It prints a one-time
reset code; the person spends it on the "Forgot your password?" screen (under
"I have a recovery code or a code from my director") to choose a new password.
The script never learns or sets a password itself.

    podman exec -it offdays_app_1 python scripts/reset_password.py someone@example.com

It does not send anything. Read the code to the person yourself, after you are
sure it is them: a reset code is as good as the password.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from offdays import passwords  # noqa: E402
from offdays.db import connect  # noqa: E402
from offdays.config import CONFIG  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2 or "@" not in argv[1]:
        print(__doc__)
        return 2
    email = passwords.normalise_email(argv[1])
    conn = connect(CONFIG.db_path)
    conn.execute("PRAGMA busy_timeout = 30000")
    row = passwords.by_email(conn, email)
    if row is None:
        print(f"No sign-in is set up for {email}.")
        print("That person has not chosen a password yet. They can still sign in with their")
        print("six-character code.")
        return 1
    user = conn.execute(
        "SELECT u.id, u.role, u.display_name, o.name AS org FROM users u "
        "JOIN organizations o ON o.id = u.org_id WHERE u.id = ?", (row["user_id"],)
    ).fetchone()
    code = passwords.issue_reset(conn, int(row["user_id"]))
    print(f"Reset code for {user['display_name']} ({user['role']}, {user['org']}):\n")
    print(f"    {code}\n")
    print(f"Good for {passwords.RESET_HOURS} hours, works once. They enter it, with {email},")
    print("on the 'Forgot your password?' screen. Their current password and any open")
    print("sessions stop working the moment they choose a new one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
