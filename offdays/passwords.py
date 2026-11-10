"""Email-and-password sign-in for coaches and directors.

The six-character code stays: parents and athletes use nothing else, and staff
keep it as a way back in. This adds a second door for the two roles that sign in
again and again, and it is built so that every other door is untouched.
`Store.authenticate` is still the only place a token becomes a person; a
password sign-in simply mints a session token that `authenticate` also knows.

This module knows nothing about email. With mail connected, a forgotten password is
recovered by an emailed link (offdays/staff_mail.py: confirm the address, then "email me
a link", unattended). This module holds the three ways back in that need no mail, in the
order a person would reach for them:

1. the *recovery code* shown once when the password is set (only when mail is not
   connected, or the confirm mail did not go);
2. a one-time *reset code* a director reads out to a coach, which is also the answer for
   a coach whose address was mistyped or never confirmed;
3. a reset the operator runs on the server (scripts/reset_password.py).

Passwords are hashed with scrypt from the standard library, salted per row, and
compared in constant time. Recovery codes, reset codes and session tokens are
random and high-entropy, so they are stored as SHA-256 digests like every other
credential in this product. Sessions end when a password changes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

# scrypt cost: 16 MiB and about 50 ms. High enough to make a stolen table slow to
# crack, low enough that a login does not hold a worker.
_N, _R, _P = 2 ** 14, 8, 1
_MAXMEM = 64 * 1024 * 1024

MIN_LENGTH = 10
MAX_LENGTH = 200
SESSION_DAYS = 30
RESET_HOURS = 24

#: Unambiguous characters: no 0/O, 1/I/L. A code is read aloud and typed.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

#: The passwords people actually choose. Not exhaustive; it is the cheap end of
#: a guess list, and the length rule does the rest.
_COMMON = frozenset("""
password password1 password12 password123 password1234 password12345 passw0rd
1234567890 12345678901 123456789012 qwertyuiop qwerty12345 qwertyuiop123
letmein123 welcome123 iloveyou123 admin12345 administrator football123
baseball123 basketball1 lacrosse123 lacrosse12 nashville123 changeme123
0ffdays123 offdays123 monkey12345 dragon12345 abc1234567 abcdefghij
1q2w3e4r5t 1qaz2wsx3edc zaq12wsx123 trustno1234 sunshine123 princess123
""".split())


class PasswordError(ValueError):
    """Said to the person, so it is written for them."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def check_email(email: str) -> str:
    e = normalise_email(email)
    if len(e) > 200 or "@" not in e or e.startswith("@") or e.endswith("@") or " " in e \
            or "." not in e.split("@", 1)[1]:
        raise PasswordError("Enter a real email address.")
    return e


def check_password(password: str, email: str = "") -> None:
    if len(password) < MIN_LENGTH:
        raise PasswordError(f"Use at least {MIN_LENGTH} characters. A few words in a row is easy to remember.")
    if len(password) > MAX_LENGTH:
        raise PasswordError(f"Keep it under {MAX_LENGTH} characters.")
    low = password.lower()
    if low in _COMMON or len(set(low)) <= 3:
        raise PasswordError("That one is too easy to guess. Try a few unrelated words.")
    # Anything built from the part of the email before the @ is the first thing a
    # person who knows you would try, however it is padded: joel1234567.
    local = normalise_email(email).split("@", 1)[0]
    if len(local) >= 4 and local in low.replace("@", ""):
        raise PasswordError("Do not build it from your email address.")


# ---------------------------------------------------------------- hashing

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P,
                            maxmem=_MAXMEM, dklen=32)
    b = lambda x: base64.b64encode(x).decode("ascii")  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b(salt)}${b(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, want = stored.split("$")
        if scheme != "scrypt":
            return False
        got = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt),
                             n=int(n), r=int(r), p=int(p), maxmem=_MAXMEM, dklen=32)
        return hmac.compare_digest(got, base64.b64decode(want))
    except (ValueError, TypeError):
        return False


#: Run on an unknown email, so "no such account" costs the same as "wrong
#: password" and the response time does not tell a stranger which emails exist.
_DUMMY = hash_password("not-a-real-password")


def burn_time() -> None:
    verify_password("x", _DUMMY)


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.strip().upper().encode("utf-8")).hexdigest()


def _code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def _token() -> str:
    return secrets.token_urlsafe(32)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- credentials

def get(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM credentials WHERE user_id = ?", (user_id,)).fetchone()


def by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM credentials WHERE email = ?", (normalise_email(email),)
    ).fetchone()


def set_first(conn: sqlite3.Connection, user_id: int, email: str, password: str) -> str:
    """Give a staff member an email and password. Returns the recovery code."""
    email = check_email(email)
    check_password(password, email)
    if get(conn, user_id) is not None:
        raise PasswordError("A password is already set. Enter the current one to change it.")
    if by_email(conn, email) is not None:
        raise PasswordError("That email cannot be used for sign-in. Try a different one.")
    recovery = _code()
    now = _iso(_now())
    conn.execute(
        "INSERT INTO credentials(user_id, email, pw_hash, recovery_hash, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, email, hash_password(password), _digest(recovery), now, now),
    )
    conn.execute("UPDATE users SET email = COALESCE(NULLIF(email, ''), ?) WHERE id = ?", (email, user_id))
    conn.commit()
    return recovery


def change(conn: sqlite3.Connection, user_id: int, current: str, new: str) -> None:
    row = get(conn, user_id)
    if row is None:
        raise PasswordError("No password is set yet.")
    if not verify_password(current or "", row["pw_hash"]):
        raise PasswordError("The current password is not right.")
    check_password(new, row["email"])
    conn.execute("UPDATE credentials SET pw_hash = ?, updated_at = ? WHERE user_id = ?",
                 (hash_password(new), _iso(_now()), user_id))
    end_sessions(conn, user_id)
    conn.commit()


def verify_login(conn: sqlite3.Connection, email: str, password: str) -> int | None:
    """The user id for a right email and password, else None, in the same time."""
    row = by_email(conn, email)
    if row is None:
        burn_time()
        return None
    return int(row["user_id"]) if verify_password(password, row["pw_hash"]) else None


def issue_reset(conn: sqlite3.Connection, user_id: int) -> str:
    """A one-time code that lets this person choose a new password."""
    if get(conn, user_id) is None:
        raise PasswordError("They have not set a password, so there is nothing to reset. "
                            "They can still sign in with their code.")
    code = _code()
    conn.execute("UPDATE credentials SET reset_hash = ?, reset_expires = ? WHERE user_id = ?",
                 (_digest(code), _iso(_now() + timedelta(hours=RESET_HOURS)), user_id))
    conn.commit()
    return code


def reset(conn: sqlite3.Connection, email: str, code: str, new_password: str) -> str | None:
    """Spend a recovery or reset code. Returns the new recovery code, or None if
    the code is wrong. A weak password raises, and the code is *not* spent."""
    row = by_email(conn, email)
    if row is None:
        burn_time()
        return None
    given = _digest(code or "")
    via_recovery = bool(row["recovery_hash"]) and hmac.compare_digest(given, row["recovery_hash"])
    via_reset = False
    if row["reset_hash"] and row["reset_expires"] and hmac.compare_digest(given, row["reset_hash"]):
        try:
            via_reset = datetime.fromisoformat(row["reset_expires"]) > _now()
        except ValueError:
            via_reset = False
    if not (via_recovery or via_reset):
        return None
    check_password(new_password, row["email"])
    fresh = _code()
    conn.execute(
        "UPDATE credentials SET pw_hash = ?, recovery_hash = ?, reset_hash = NULL, "
        "reset_expires = NULL, updated_at = ? WHERE user_id = ?",
        (hash_password(new_password), _digest(fresh), _iso(_now()), row["user_id"]),
    )
    end_sessions(conn, int(row["user_id"]))
    conn.commit()
    return fresh


# ---------------------------------------------------------------- sessions

def start_session(conn: sqlite3.Connection, user_id: int) -> str:
    token = _token()
    now = _now()
    conn.execute(
        "INSERT INTO staff_sessions(token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
        (_token_digest(token), user_id, _iso(now), _iso(now + timedelta(days=SESSION_DAYS))),
    )
    # Quietly forget sessions that ended, so the table is the size of today.
    conn.execute("DELETE FROM staff_sessions WHERE expires_at < ?", (_iso(now),))
    conn.commit()
    return token


def session_user(conn: sqlite3.Connection, token: str) -> int | None:
    row = conn.execute(
        "SELECT user_id, expires_at FROM staff_sessions WHERE token_hash = ?",
        (_token_digest(token),),
    ).fetchone()
    if row is None:
        return None
    try:
        if datetime.fromisoformat(row["expires_at"]) <= _now():
            return None
    except ValueError:
        return None
    return int(row["user_id"])


def end_sessions(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM staff_sessions WHERE user_id = ?", (user_id,))


def summary(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    row = get(conn, user_id)
    return {"set": row is not None, "email": row["email"] if row else ""}
