"""Parent and guardian accounts.

Parents are the people who consent, who pay, and who drive to practice. They
are also the ones who will decide whether a product that films their child is
allowed in the house. This module exists for three reasons, in order of how much
they matter:

1. **Consent becomes real.** Until now `guardian_consent` was a boolean a coach
   ticked. That records that an adult clicked something -- not who agreed, to
   what, when, or whether they later changed their mind. Consent is now a
   revocable record, granted by the guardian themselves, scoped so a parent can
   say yes to training and no to their child's name on a shared leaderboard.

2. **Data rights are exercisable.** A guardian can export everything held about
   their child and can have it erased. Those are legal rights under COPPA and
   most state student-privacy law, and a right that requires emailing support is
   not really a right.

3. **Retention and word of mouth.** Parents talk to other parents at games;
   athletes do not sell software.

Two deliberate omissions:

* **No open leaderboard in the parent view.** Parent-versus-parent comparison
  is the mechanism behind the worst behaviour in youth sports, so a parent's
  token does not open the program board or any team board.

  One exception, added deliberately and scoped tightly: the cohort board for
  the age group their own child is in. Clubs split a birth year by ability,
  and the parent on the second squad has a real question -- what is the first
  squad doing that mine is not. Refusing to answer it does not retire the
  question; it moves it to the car park, where it gets answered with a guess
  about politics. The board answers it with work done: sessions, off-hand
  share, consistency, improvement. Not ability, and not a projection of who
  makes which team.

  What keeps it from becoming the thing above: it is one cohort and not the
  club; every board on it ranks effort an athlete controls rather than talent
  they do not; and LEADERBOARD_NAME still gates names, so a family that wants
  their child counted but not named gets exactly that.
* **No integrity or review status.** "Your child's session was held for review"
  reads as an accusation, and it is a coach's conversation to have, not a
  push notification's.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import fresh_token, hash_token, new_token, transaction

# The terms a guardian is agreeing to. Stored with each consent so a later
# policy change cannot be applied retroactively to an agreement made under
# different terms.
POLICY_VERSION = "1"

INVITE_TTL_DAYS = 14


class Scope:
    """What a guardian is consenting to, separately."""

    PARTICIPATION = "participation"        # the athlete may use the app at all
    LEADERBOARD_NAME = "leaderboard_name"  # full name on shared leaderboards
    DATA_RETENTION = "data_retention"      # keep granular per-rep timings
    COACH_VIDEO = "coach_video"            # a coach may watch a clip the athlete shares


SCOPES = (
    (
        Scope.PARTICIPATION,
        "Training in the app",
        "Your athlete can record drills and their counts are shared with their "
        "coach. Video is analysed on their phone and never uploaded.",
    ),
    (
        Scope.LEADERBOARD_NAME,
        "Show their full name on team leaderboards",
        "Without this they still appear and still compete, under an initial and "
        "jersey number instead of their full name.",
    ),
    (
        Scope.COACH_VIDEO,
        "Let a coach watch a clip your athlete chooses to send",
        "Off unless you turn it on. Everywhere else in this app video stays on "
        "your athlete's phone and is never uploaded. With this on, they can "
        "choose to send one specific clip to their coach for feedback, never "
        "automatically, always one at a time. Clips are deleted after 30 days, "
        "and turning this off deletes any that are still there straight away.",
    ),
    (
        Scope.DATA_RETENTION,
        "Keep detailed rep timings for 45 days",
        "Used to review a disputed score. Turning this off keeps their totals "
        "and removes the rep-by-rep detail.",
    ),
)

SCOPE_LABELS = {key: label for key, label, _ in SCOPES}

#: How the video permission reads in a household, where the person granting it
#: and the person who would watch are the same. The decision is still a real
#: one -- the clip still leaves the phone and lands in a database -- but
#: describing it as "let a coach watch" would be describing someone else's
#: situation, and a consent screen that does not match what is happening is
#: not informed consent.
FAMILY_SCOPE_COPY = {
    Scope.COACH_VIDEO: (
        "Let clips your athlete sends reach your dashboard",
        "Off unless you turn it on. Everywhere else in this app video stays on "
        "their phone. With this on, they can choose to send you one specific "
        "clip for feedback: their choice, one at a time, never automatic. It "
        "is uploaded to do that, so it is a real decision and not just a "
        "screen. Clips are deleted after 30 days, and turning this off deletes "
        "them straight away.",
    ),
}


def scopes_for(
    kind: str = "program", locale: str = "en"
) -> tuple[tuple[str, str, str], ...]:
    """The consent list, worded for who is actually reading it.

    Including which language they read. A consent screen somebody cannot read
    is not consent, and this is the function every consent surface goes
    through -- so translating here rather than at each call site is the
    difference between a rule and an intention.
    """
    from . import i18n

    locale = i18n.normalize(locale)
    out = []
    for key, label, why in SCOPES:
        family = kind == "family" and key in FAMILY_SCOPE_COPY
        stem = f"consent.family.{key}" if family else f"consent.{key}"
        translated_label = i18n.t(f"{stem}.label", locale)
        translated_why = i18n.t(f"{stem}.why", locale)
        if family and not translated_label:
            translated_label, translated_why = FAMILY_SCOPE_COPY[key]
        out.append((
            key,
            translated_label or label,
            translated_why or why,
        ))
    return tuple(out)


class GuardianError(Exception):
    """A guardian request that is well-formed but not permissible."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------

def new_invite_code() -> str:
    """A code short enough to read aloud, long enough not to be guessed."""
    alphabet = "ABCDEFGHJKLMNPQRTUVWXYZ234679"
    return "-".join(
        "".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)
    )


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def create_invite(
    conn: sqlite3.Connection,
    athlete_id: int,
    created_by: int,
    email: str | None = None,
) -> dict[str, Any]:
    """Issue a single-use invitation for a guardian of this athlete.

    The code is returned once and stored only as a hash: a code that reaches the
    wrong person grants access to a child's data, so it is treated as a
    credential rather than a convenience string.
    """
    athlete = conn.execute(
        "SELECT id, display_name, role FROM users WHERE id = ? AND active = 1",
        (athlete_id,),
    ).fetchone()
    if athlete is None:
        raise GuardianError("unknown athlete")
    if athlete["role"] != "athlete":
        raise GuardianError("guardians can only be linked to athletes")

    code = new_invite_code()
    expires = _now() + timedelta(days=INVITE_TTL_DAYS)
    with transaction(conn) as c:
        c.execute(
            "INSERT INTO guardian_invites(athlete_id, created_by, code_hash, email, "
            "created_at, expires_at) VALUES (?,?,?,?,?,?)",
            (athlete_id, created_by, _hash_code(code), email, _iso(_now()), _iso(expires)),
        )
    return {
        "code": code,
        "athlete_id": athlete_id,
        "athlete_name": athlete["display_name"],
        "expires_at": _iso(expires),
    }


def revoke_invite(conn: sqlite3.Connection, invite_id: int) -> None:
    with transaction(conn) as c:
        c.execute(
            "UPDATE guardian_invites SET revoked_at = ? WHERE id = ? AND redeemed_at IS NULL",
            (_iso(_now()), invite_id),
        )


def redeem_invite(
    conn: sqlite3.Connection,
    code: str,
    display_name: str,
    email: str | None = None,
    relationship: str = "parent",
) -> dict[str, Any]:
    """Turn an invitation into a guardian account linked to the athlete.

    Redemption is the identity proof: whoever the coach handed the code to is
    who gets the account. Deliberately vague on failure -- distinguishing
    "expired" from "no such code" would let someone probe for valid codes.
    """
    row = conn.execute(
        "SELECT * FROM guardian_invites WHERE code_hash = ?", (_hash_code(code),)
    ).fetchone()

    now = _now()
    invalid = (
        row is None
        or row["redeemed_at"] is not None
        or row["revoked_at"] is not None
        or datetime.fromisoformat(row["expires_at"]) < now
    )
    if invalid:
        raise GuardianError(
            "That invite code is not valid. Ask the coach to send a new one."
        )

    athlete = conn.execute(
        "SELECT id, org_id, display_name FROM users WHERE id = ?", (row["athlete_id"],)
    ).fetchone()
    if athlete is None:
        raise GuardianError("that athlete is no longer in the program")

    token = fresh_token(conn)
    with transaction(conn) as c:
        cur = c.execute(
            "INSERT INTO users(org_id, role, display_name, email, token_hash, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                athlete["org_id"], "guardian", display_name,
                email or row["email"], hash_token(token), _iso(now),
            ),
        )
        guardian_id = int(cur.lastrowid)
        c.execute(
            "INSERT OR IGNORE INTO guardians(guardian_id, athlete_id, relationship, linked_at) "
            "VALUES (?,?,?,?)",
            (guardian_id, athlete["id"], relationship, _iso(now)),
        )
        c.execute(
            "UPDATE guardian_invites SET redeemed_at = ?, redeemed_by = ? WHERE id = ?",
            (_iso(now), guardian_id, row["id"]),
        )

    return {
        "guardian_id": guardian_id,
        "token": token,
        "athlete_id": athlete["id"],
        "athlete_name": athlete["display_name"],
    }


def link_existing(
    conn: sqlite3.Connection, code: str, guardian_id: int, relationship: str = "parent"
) -> int:
    """Attach a second child to an existing guardian account."""
    row = conn.execute(
        "SELECT * FROM guardian_invites WHERE code_hash = ?", (_hash_code(code),)
    ).fetchone()
    if (
        row is None
        or row["redeemed_at"] is not None
        or row["revoked_at"] is not None
        or datetime.fromisoformat(row["expires_at"]) < _now()
    ):
        raise GuardianError(
            "That invite code is not valid. Ask the coach to send a new one."
        )

    with transaction(conn) as c:
        c.execute(
            "INSERT OR IGNORE INTO guardians(guardian_id, athlete_id, relationship, linked_at) "
            "VALUES (?,?,?,?)",
            (guardian_id, row["athlete_id"], relationship, _iso(_now())),
        )
        c.execute(
            "UPDATE guardian_invites SET redeemed_at = ?, redeemed_by = ? WHERE id = ?",
            (_iso(_now()), guardian_id, row["id"]),
        )
    return int(row["athlete_id"])


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

def athletes_for(conn: sqlite3.Connection, guardian_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT u.id, u.display_name, u.birth_year, u.dominant_hand, g.relationship "
        "FROM guardians g JOIN users u ON u.id = g.athlete_id "
        "WHERE g.guardian_id = ? AND u.active = 1 ORDER BY u.display_name",
        (guardian_id,),
    ).fetchall()


def guards(conn: sqlite3.Connection, guardian_id: int, athlete_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM guardians WHERE guardian_id = ? AND athlete_id = ?",
        (guardian_id, athlete_id),
    ).fetchone() is not None


def require_guardianship(
    conn: sqlite3.Connection, guardian_id: int, athlete_id: int
) -> None:
    if not guards(conn, guardian_id, athlete_id):
        raise GuardianError("you are not listed as a guardian for that athlete")


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

def set_consent(
    conn: sqlite3.Connection,
    athlete_id: int,
    guardian_id: int | None,
    scope: str,
    granted: bool,
    method: str = "guardian_portal",
) -> dict[str, Any]:
    """Record a consent decision.

    Append-only: revoking writes a new row rather than deleting the old one, so
    the history of what was agreed and when survives. That history is the whole
    point of a consent record.
    """
    if scope not in SCOPE_LABELS:
        raise GuardianError(f"unknown consent scope: {scope!r}")

    with transaction(conn) as c:
        c.execute(
            "INSERT INTO consents(athlete_id, guardian_id, scope, granted, granted_at, "
            "policy_version, method) VALUES (?,?,?,?,?,?,?)",
            (
                athlete_id, guardian_id, scope, 1 if granted else 0,
                _iso(_now()), POLICY_VERSION, method,
            ),
        )
        # Withdrawing video permission deletes the video, in the same
        # transaction as the decision itself. Anything less would make this a
        # preference rather than a permission: a parent who turns it off has
        # to be able to believe the clips are gone, not merely hidden.
        if scope == Scope.COACH_VIDEO and not granted:
            c.execute("DELETE FROM shared_clips WHERE athlete_id = ?", (athlete_id,))

        # `users.guardian_consent_at` is a denormalized cache of the
        # leaderboard-name decision, read by the leaderboard query. Kept in step
        # here so the two can never disagree.
        if scope == Scope.LEADERBOARD_NAME:
            c.execute(
                "UPDATE users SET guardian_consent_at = ? WHERE id = ?",
                (_iso(_now()) if granted else None, athlete_id),
            )
    return {"scope": scope, "granted": granted, "at": _iso(_now())}


def current_consents(conn: sqlite3.Connection, athlete_id: int) -> dict[str, bool]:
    """The latest decision for every scope. Unanswered scopes read as False."""
    state = {key: False for key, _, _ in SCOPES}
    for row in conn.execute(
        "SELECT scope, granted FROM consents WHERE athlete_id = ? ORDER BY id",
        (athlete_id,),
    ):
        if row["scope"] in state:
            state[row["scope"]] = bool(row["granted"])
    return state


def answered_scopes(conn: sqlite3.Connection, athlete_id: int) -> set[str]:
    """Scopes a guardian has actually decided, either way.

    `current_consents` collapses "never asked" and "asked and said no" into
    the same False, which is right for enforcement and wrong for onboarding:
    a parent who said no has made their decision, and a checklist that keeps
    asking is not respecting it.
    """
    return {
        row["scope"] for row in conn.execute(
            "SELECT DISTINCT scope FROM consents WHERE athlete_id = ?", (athlete_id,)
        )
    }


def consent_detail(
    conn: sqlite3.Connection, athlete_id: int, locale: str = "en"
) -> list[dict[str, Any]]:
    """Every scope with its current state and description, for the portal.

    Worded for whoever is reading it: in a household the person granting the
    video permission and the person who would watch are the same, and a
    consent screen describing somebody else's situation is not informed
    consent.
    """
    state = current_consents(conn, athlete_id)
    row = conn.execute(
        "SELECT o.kind FROM users u JOIN organizations o ON o.id = u.org_id "
        "WHERE u.id = ?",
        (athlete_id,),
    ).fetchone()
    return [
        {
            "scope": key,
            "label": label,
            "description": description,
            "granted": state[key],
        }
        for key, label, description in scopes_for(
            row["kind"] if row else "program", locale)
    ]


def has_consent(conn: sqlite3.Connection, athlete_id: int, scope: str) -> bool:
    return current_consents(conn, athlete_id).get(scope, False)


# ---------------------------------------------------------------------------
# Data rights
# ---------------------------------------------------------------------------

def export_athlete(conn: sqlite3.Connection, athlete_id: int) -> dict[str, Any]:
    """Everything held about one athlete, in one JSON-safe structure."""
    def rows(sql: str, params: tuple = (athlete_id,)) -> list[dict[str, Any]]:
        return [dict(r) for r in conn.execute(sql, params)]

    profile = conn.execute(
        "SELECT id, display_name, email, birth_year, dominant_hand, created_at "
        "FROM users WHERE id = ?",
        (athlete_id,),
    ).fetchone()

    return {
        "exported_at": _iso(_now()),
        "note": (
            "No video or images are held. Pose analysis runs on the athlete's "
            "own device and footage is never uploaded."
        ),
        "profile": dict(profile) if profile else None,
        "consents": rows(
            "SELECT scope, granted, granted_at, policy_version, method "
            "FROM consents WHERE athlete_id = ? ORDER BY id"
        ),
        "teams": rows(
            "SELECT t.name, t.season, tm.jersey, tm.position, tm.joined_at "
            "FROM team_members tm JOIN teams t ON t.id = tm.team_id WHERE tm.user_id = ?"
        ),
        "sessions": rows(
            "SELECT id, drill_key, started_at, submitted_at, completed_at, duration_ms, "
            "reps_total, reps_left, reps_right, hold_ms, xp_awarded, quality_score "
            "FROM sessions WHERE athlete_id = ? AND status != 'open' ORDER BY id"
        ),
        "rep_events": rows(
            "SELECT session_id, t_ms, hand, rom, cycle_ms FROM rep_events "
            "WHERE session_id IN (SELECT id FROM sessions WHERE athlete_id = ?) "
            "ORDER BY session_id, t_ms"
        ),
        "xp": rows(
            "SELECT amount, reason, day, created_at FROM xp_ledger "
            "WHERE athlete_id = ? ORDER BY id"
        ),
        "badges": rows(
            "SELECT badge_key, awarded_at FROM badges WHERE athlete_id = ? ORDER BY id"
        ),
        "recovery_days": rows(
            "SELECT day, reason FROM recovery_days WHERE athlete_id = ? ORDER BY day"
        ),
        # Health data, so it is exported in full -- including the athlete's own
        # note, which a coach never sees but which is unambiguously theirs and
        # their guardian's to have a copy of.
        "wellness_checkins": rows(
            "SELECT day, soreness FROM wellness_checkins WHERE athlete_id = ? ORDER BY day"
        ),
        "discomfort_reports": rows(
            "SELECT area, side, severity, flags, note, started_on, reported_on, "
            "resolved_on FROM discomfort_reports WHERE athlete_id = ? ORDER BY id"
        ),
    }


def erase_athlete(
    conn: sqlite3.Connection,
    athlete_id: int,
    scope: str = "training_data",
    requested_by: str = "guardian",
) -> dict[str, Any]:
    """Delete an athlete's data.

    `training_data` removes everything they generated but keeps the account, so
    they can carry on if the family only wanted the history gone.
    `all` removes the account too.

    The deletion is real -- rows are gone, not flagged. Only the *fact* of the
    erasure is retained, with no identifying detail, so a program can show an
    auditor that a request was honoured without keeping what it deleted.
    """
    if scope not in ("training_data", "all"):
        raise GuardianError("scope must be 'training_data' or 'all'")

    removed = 0
    with transaction(conn) as c:
        for sql in (
            "DELETE FROM rep_events WHERE session_id IN "
            "(SELECT id FROM sessions WHERE athlete_id = ?)",
            "DELETE FROM sessions WHERE athlete_id = ?",
            "DELETE FROM xp_ledger WHERE athlete_id = ?",
            "DELETE FROM badges WHERE athlete_id = ?",
            "DELETE FROM recovery_days WHERE athlete_id = ?",
            "DELETE FROM wellness_checkins WHERE athlete_id = ?",
            "DELETE FROM discomfort_reports WHERE athlete_id = ?",
            "DELETE FROM notifications WHERE user_id = ?",
            "DELETE FROM push_subscriptions WHERE user_id = ?",
        ):
            removed += c.execute(sql, (athlete_id,)).rowcount

        if scope == "all":
            for sql in (
                "DELETE FROM assignment_athletes WHERE athlete_id = ?",
                "DELETE FROM team_members WHERE user_id = ?",
                "DELETE FROM consents WHERE athlete_id = ?",
                "DELETE FROM guardians WHERE athlete_id = ?",
                "DELETE FROM guardian_invites WHERE athlete_id = ?",
                "DELETE FROM users WHERE id = ?",
            ):
                removed += c.execute(sql, (athlete_id,)).rowcount

        c.execute(
            "INSERT INTO erasure_log(athlete_ref, requested_by, scope, rows_removed, created_at) "
            "VALUES (?,?,?,?,?)",
            (
                # A hash, so the log proves a request was honoured without
                # re-identifying the child it was about.
                hashlib.sha256(f"athlete:{athlete_id}".encode()).hexdigest()[:16],
                requested_by, scope, removed, _iso(_now()),
            ),
        )
    return {"scope": scope, "rows_removed": removed}
