"""Getting a guardian invite from the roster to the parent's inbox.

The roster carries a parent email, and the import mints an invite code for
every athlete who has one. Until now that was where it stopped: the code was
stored next to the email and never sent, so the only way it reached a family
was a coach cutting up printed slips at practice. For a 35-kid pilot that is a
chore; for a club it is the reason nobody signs up.

This module composes and queues the email. It does not send: the outbox is
drained by the hourly notifications job, which already retries and respects
suppression, and with no SMTP configured the console transport logs it so the
printed slip remains the only real path and nothing pretends otherwise.
"""

from __future__ import annotations

import sqlite3
from html import escape
from typing import Any

from . import guardians, mailer
from .config import CONFIG


def invite_link(code: str) -> str:
    """The sign-up page with the code already filled in.

    A parent on a phone is not going to copy a twelve-character code out of
    an email into a form. The link lands them on the form with the code typed;
    they add their name and press one button.
    """
    base = CONFIG.app_base_url.rstrip("/") if CONFIG.app_base_url else ""
    return f"{base}/app/index.html?invite={code}"


def compose(
    *,
    athlete_name: str,
    org_name: str,
    coach_name: str,
    code: str,
) -> tuple[str, str, str]:
    """Subject, HTML and plain text for one invite.

    Written for someone who has never heard of the app and is being asked to
    let it point a camera at their child. The promise -- the video never
    leaves the phone -- is in the first paragraph, because that is the
    question they have before any other.
    """
    first = athlete_name.split()[0] if athlete_name.strip() else "your athlete"
    link = invite_link(code)
    days = guardians.INVITE_TTL_DAYS
    subject = f"{org_name}: set up {first}'s training app"

    text = (
        f"{coach_name} at {org_name} uses 0FFDAYS so {first} can record "
        f"drills at home and get credit for the work.\n\n"
        f"The app counts reps on {first}'s own phone. The video never leaves "
        f"the phone: it is not uploaded or stored anywhere. Their coach sees "
        f"the numbers, never the footage.\n\n"
        f"Nothing happens until you say so. Set up your parent account, decide "
        f"whether {first} can train, and the app hands you their sign-in code "
        f"to pass on.\n\n"
        f"Open this link:\n{link}\n\n"
        f"Or go to the app and enter the invite code {code}.\n\n"
        f"The code works once and expires in {days} days. If it has expired, "
        f"ask {coach_name} for a new one.\n\n"
        f"You can withdraw any permission at any time, download everything "
        f"held about {first}, or delete it, from the same page."
    )

    html = (
        f"<p>{escape(coach_name)} at <b>{escape(org_name)}</b> uses 0FFDAYS so "
        f"{escape(first)} can record drills at home and get credit for the work.</p>"
        f"<p>The app counts reps on {escape(first)}'s own phone. <b>The video never "
        f"leaves the phone</b>: it is not uploaded or stored anywhere. Their coach "
        f"sees the numbers, never the footage.</p>"
        f"<p>Nothing happens until you say so. Set up your parent account, decide "
        f"whether {escape(first)} can train, and the app hands you their sign-in "
        f"code to pass on.</p>"
        f'<p><a href="{escape(link)}" style="display:inline-block;padding:12px 20px;'
        f'background:#111;color:#fff;text-decoration:none;border-radius:6px">'
        f"Set up {escape(first)}'s account</a></p>"
        f'<p style="color:#555">Or go to the app and enter the invite code '
        f"<code>{escape(code)}</code>.</p>"
        f'<p style="color:#555">The code works once and expires in {days} days. '
        f"If it has expired, ask {escape(coach_name)} for a new one.</p>"
        f'<p style="color:#555;font-size:90%">You can withdraw any permission at '
        f"any time, download everything held about {escape(first)}, or delete it, "
        f"from the same page.</p>"
    )
    return subject, html, text


def deliver(
    conn: sqlite3.Connection,
    invite: dict[str, Any],
    *,
    org_name: str,
    coach_name: str,
) -> bool:
    """Queue the invite email. True if it was queued.

    Transactional, so a digest opt-out never holds it back, and keyed on the
    invite id so a refreshed import cannot send the same code twice. An
    invite with no email (a family the roster had no address for) is simply
    not queued: that family gets the printed slip.
    """
    email = (invite.get("email") or "").strip()
    if not email:
        return False
    subject, html, text = compose(
        athlete_name=invite["athlete_name"], org_name=org_name,
        coach_name=coach_name, code=invite["code"],
    )
    queued = mailer.enqueue(
        conn,
        to_email=email,
        subject=subject,
        html=html,
        text=text,
        kind=mailer.Kind.TRANSACTIONAL,
        dedupe_key=f"guardian_invite:{invite['invite_id']}",
    )
    return queued is not None


def delivery_status(conn: sqlite3.Connection, invite_ids: list[int]) -> dict[int, str]:
    """Outbox status per invite, so a coach can see which emails went.

    'none' means nothing was ever queued (no email on the roster, or an
    address that was not an address); otherwise the outbox status as it
    stands: queued, sent, failed, suppressed.
    """
    if not invite_ids:
        return {}
    marks = ",".join("?" for _ in invite_ids)
    keys = [f"guardian_invite:{i}" for i in invite_ids]
    rows = conn.execute(
        f"SELECT dedupe_key, status FROM email_outbox WHERE dedupe_key IN ({marks})",
        keys,
    ).fetchall()
    found = {r["dedupe_key"]: r["status"] for r in rows}
    return {i: found.get(f"guardian_invite:{i}", "none") for i in invite_ids}
