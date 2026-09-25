"""Slow down anyone guessing codes.

Every credential in this product is short on purpose: a sign-in code is one
letter and five digits so a twelve-year-old can type it off a slip of paper,
and claim and guardian-invite codes are of the same order. That is fine for
a kid at a kitchen table and hopeless against a script. The code space is
2.4 million; at fifty guesses a second it is exhausted in a working day, and
each hit is a child's account.

So the space is not the defence -- this is. Failed guesses are counted per
source address and per code, and after a handful the source is refused with
a 429 and a Retry-After that doubles on each further burst. Two keys because
they defend against different attackers: an address that rotates through the
code space trips the address counter, and a botnet that rotates addresses to
hammer one child's code trips the code counter.

State lives in SQLite alongside everything else. A process-local dict would
reset on every restart and not survive a second worker; a table costs one
SELECT per authenticated request, which is nothing next to what the request
then does. A successful sign-in clears its counters so a kid who fat-fingers
the code twice and gets it the third time is not carrying a debt.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import CONFIG


class Throttled(Exception):
    """The caller has to wait. `retry_after` is whole seconds."""

    def __init__(self, retry_after: int):
        self.retry_after = max(1, int(retry_after))
        super().__init__(
            f"too many attempts; try again in {self.retry_after} seconds"
        )


@dataclass(frozen=True)
class Attempt:
    """What a caller is about to try, so the same keys cover check and record."""

    keys: tuple[str, ...]

    @classmethod
    def for_code(cls, source: str | None, code: str) -> "Attempt":
        return cls((_addr_key(source), _code_key(code)))

    @classmethod
    def for_source(cls, source: str | None) -> "Attempt":
        return cls((_addr_key(source),))


def _addr_key(source: str | None) -> str:
    return f"addr:{source or 'unknown'}"


def _code_key(code: str) -> str:
    # Hashed so the table never holds a guess that happened to be right.
    digest = hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()
    return f"code:{digest[:32]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(stamp: str | None) -> datetime | None:
    return datetime.fromisoformat(stamp) if stamp else None


def check(conn: sqlite3.Connection, attempt: Attempt, now: datetime | None = None) -> None:
    """Raise Throttled if any of the attempt's keys is currently locked.

    Read-only, so it is safe on the hot path of every bearer-authenticated
    request. Runs before the credential is looked up: a locked caller learns
    nothing from timing about whether the guess was right.
    """
    now = now or _now()
    if not attempt.keys:
        return
    placeholders = ",".join("?" for _ in attempt.keys)
    rows = conn.execute(
        f"SELECT key, locked_until FROM auth_attempts WHERE key IN ({placeholders})",
        attempt.keys,
    ).fetchall()
    waits = []
    for row in rows:
        until = _parse(row["locked_until"])
        if until and until > now:
            waits.append((until - now).total_seconds())
    if waits:
        raise Throttled(int(max(waits)) + 1)


def record_failure(
    conn: sqlite3.Connection, attempt: Attempt, now: datetime | None = None
) -> None:
    """Count a wrong guess and, past the threshold, lock the key.

    The lock doubles with each failure beyond the threshold, capped, so a
    scripted attacker is slowed to uselessness while a person who keeps
    misreading a slip of paper waits a minute rather than an hour.
    """
    now = now or _now()
    stamp = now.isoformat(timespec="seconds")
    window = timedelta(seconds=CONFIG.auth_failure_window_seconds)
    for key in attempt.keys:
        row = conn.execute(
            "SELECT failures, first_failure_at, locked_until FROM auth_attempts WHERE key = ?",
            (key,),
        ).fetchone()
        first = _parse(row["first_failure_at"]) if row else None
        locked = _parse(row["locked_until"]) if row else None
        stale = first is not None and now - first > window and not (locked and locked > now)
        fresh = row is None or stale
        failures = (0 if fresh else int(row["failures"])) + 1

        locked_until = None
        over = failures - CONFIG.auth_max_failures
        if over >= 0:
            seconds = min(
                CONFIG.auth_lockout_seconds * (2 ** over),
                CONFIG.auth_lockout_max_seconds,
            )
            locked_until = (now + timedelta(seconds=seconds)).isoformat(timespec="seconds")

        conn.execute(
            "INSERT INTO auth_attempts(key, failures, first_failure_at, locked_until) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET failures = excluded.failures, "
            "first_failure_at = excluded.first_failure_at, "
            "locked_until = excluded.locked_until",
            (key, failures, stamp if fresh else row["first_failure_at"], locked_until),
        )
    # Forget anyone who has been quiet for a full window and is not locked.
    # Keeps the table the size of the current trouble, not the year's.
    cutoff = (now - window).isoformat(timespec="seconds")
    conn.execute(
        "DELETE FROM auth_attempts WHERE first_failure_at < ? "
        "AND (locked_until IS NULL OR locked_until < ?)",
        (cutoff, stamp),
    )
    conn.commit()


def record_success(conn: sqlite3.Connection, attempt: Attempt) -> None:
    """A right answer clears the slate for every key it was checked under."""
    if not attempt.keys:
        return
    placeholders = ",".join("?" for _ in attempt.keys)
    cur = conn.execute(
        f"DELETE FROM auth_attempts WHERE key IN ({placeholders})", attempt.keys
    )
    if cur.rowcount:
        conn.commit()


def state(conn: sqlite3.Connection, key: str) -> dict | None:
    """One row, for tests and the health page."""
    row = conn.execute(
        "SELECT key, failures, first_failure_at, locked_until FROM auth_attempts WHERE key = ?",
        (key,),
    ).fetchone()
    return dict(row) if row else None
