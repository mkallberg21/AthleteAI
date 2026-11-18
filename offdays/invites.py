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


MAX_INTRO = 1500


def clean_intro(value: str | None) -> str:
    """The coach's own words, as plain text: trimmed, bounded, no stray control characters."""
    text = "".join(c for c in (value or "").replace("\r\n", "\n").replace("\r", "\n") if c == "\n" or c >= " ")
    lines = [ln.rstrip() for ln in text.strip().split("\n")]
    out: list[str] = []
    for ln in lines:                                  # never more than one blank line in a row
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()[:MAX_INTRO]


def sender_display(coach_name: str, org_name: str) -> str:
    """The name on the From line: a message from 0FFDAYS, said to be on behalf of this coach."""
    return mailer.clean_display_name(f"{coach_name} ({org_name}) via 0FFDAYS")


def staff_reply_to(conn: sqlite3.Connection, user_id: int | None) -> str:
    """Where a parent's reply goes: the sender's own address, but only once they have confirmed it is theirs.

    An address nobody has proved (a typo, someone else's) is never used: a parent's reply must not go to a stranger.
    """
    from . import sender_email
    return sender_email.confirmed_address(conn, user_id)


def compose(
    *,
    athlete_name: str,
    org_name: str,
    coach_name: str,
    code: str,
    also: list[str] | tuple[str, ...] = (),
    intro: str = "",
    reply_to: str = "",
) -> tuple[str, str, str]:
    """The invite as a message from 0FFDAYS on behalf of a coach or director.

    Adds to the base invite: the sender's own note on top (`intro`, plain text), and a line at the bottom that
    says who it is from and where a reply goes.
    """
    subject, html, text = _compose_base(
        athlete_name=athlete_name, org_name=org_name, coach_name=coach_name, code=code, also=also)
    note = clean_intro(intro)
    who = f"{coach_name} at {org_name}"
    if reply_to:
        foot_text = (f"Sent by 0FFDAYS on behalf of {who}. Just reply to this email and it goes to {coach_name}.")
        foot_html = (f"Sent by 0FFDAYS on behalf of {escape(coach_name)} at {escape(org_name)}. "
                     f"Just reply to this email and it goes to {escape(coach_name)}.")
    else:
        foot_text = (f"Sent by 0FFDAYS on behalf of {who}. Replies to this address are not read, so please "
                     f"contact {coach_name} directly.")
        foot_html = (f"Sent by 0FFDAYS on behalf of {escape(coach_name)} at {escape(org_name)}. Replies to this "
                     f"address are not read, so please contact {escape(coach_name)} directly.")
    if note:
        text = f"{note}\n\n{text}"
        paras = "".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in note.split("\n\n"))
        html = f'<div style="border-left:3px solid #008BFD;padding-left:12px;margin-bottom:16px">{paras}</div>' + html
    text = f"{text}\n\n--\n{foot_text}"
    html = html + f'<p style="color:#777;font-size:85%;margin-top:20px">{foot_html}</p>'
    return subject, html, text


def _compose_base(
    *,
    athlete_name: str,
    org_name: str,
    coach_name: str,
    code: str,
    also: list[str] | tuple[str, ...] = (),
) -> tuple[str, str, str]:
    """Subject, HTML and plain text for one invite (`also`: the parent's other children it covers).

    Written for someone who has never heard of the app and is being asked to
    let it point a camera at their child. The promise -- the video never
    leaves the phone -- is in the first paragraph, because that is the
    question they have before any other.
    """
    first = athlete_name.split()[0] if athlete_name.strip() else "your athlete"
    link = invite_link(code)
    days = guardians.INVITE_TTL_DAYS
    if also:
        return _compose_family([first] + [n.split()[0] for n in also if n.strip()],
                               org_name=org_name, coach_name=coach_name, code=code, link=link, days=days)
    subject = f"{org_name}: set up {first}'s training app"

    text = (
        f"{coach_name} at {org_name} uses 0FFDAYS so {first} can record "
        f"drills at home and get credit for the work.\n\n"
        f"The app counts reps on {first}'s own phone. The video never leaves "
        f"the phone: it is not uploaded or stored anywhere. Their coach sees "
        f"the numbers, never the footage.\n\n"
        f"Nothing happens until you say so. Set up your parent account, decide "
        f"whether {first} can train, and the app gives you a sign-in link to "
        f"text or email to {first}'s phone.\n\n"
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
        f"whether {escape(first)} can train, and the app gives you a sign-in link "
        f"to text or email to {escape(first)}'s phone.</p>"
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


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _compose_family(firsts: list[str], *, org_name: str, coach_name: str, code: str, link: str,
                    days: int) -> tuple[str, str, str]:
    """The same invite for a parent with several children on the roster: one email, one account."""
    names = _join(firsts)
    subject = f"{org_name}: set up {names} on 0FFDAYS"
    text = (
        f"{coach_name} at {org_name} uses 0FFDAYS so {names} can record drills at home and get credit for the "
        f"work.\n\n"
        f"The app counts reps on each athlete's own phone. The video never leaves the phone: it is not uploaded or "
        f"stored anywhere. Their coach sees the numbers, never the footage.\n\n"
        f"One parent account covers all of them. Set it up once, decide for each athlete whether they can train, "
        f"and the app gives you a separate sign-in link for each to text or email to that athlete's phone.\n\n"
        f"Open this link:\n{link}\n\n"
        f"Or go to the app and enter the invite code {code}.\n\n"
        f"The code works once and expires in {days} days. If it has expired, ask {coach_name} for a new one.\n\n"
        f"You can withdraw any permission at any time, download everything held about any of them, or delete it, "
        f"from the same page."
    )
    html = (
        f"<p>{escape(coach_name)} at <b>{escape(org_name)}</b> uses 0FFDAYS so {escape(names)} can record drills "
        f"at home and get credit for the work.</p>"
        f"<p>The app counts reps on each athlete's own phone. <b>The video never leaves the phone</b>: it is not "
        f"uploaded or stored anywhere. Their coach sees the numbers, never the footage.</p>"
        f"<p><b>One parent account covers all of them.</b> Set it up once, decide for each athlete whether they can "
        f"train, and the app gives you a separate sign-in link for each to text or email to that athlete's "
        f"phone.</p>"
        f'<p><a href="{escape(link)}" style="display:inline-block;padding:12px 20px;'
        f'background:#111;color:#fff;text-decoration:none;border-radius:6px">'
        f"Set up {escape(names)}</a></p>"
        f'<p style="color:#555">Or go to the app and enter the invite code <code>{escape(code)}</code>.</p>'
        f'<p style="color:#555">The code works once and expires in {days} days. '
        f"If it has expired, ask {escape(coach_name)} for a new one.</p>"
        f'<p style="color:#555;font-size:90%">You can withdraw any permission at any time, download everything '
        f"held about any of them, or delete it, from the same page.</p>"
    )
    return subject, html, text


def compose_staff(
    *,
    coach_name: str,
    org_name: str,
    director_name: str,
    code: str,
) -> tuple[str, str, str]:
    """Subject, HTML and plain text for a coach's sign-in.

    Shorter than the parent's: a coach was asked by the director, not by an
    app, and the thing they need is the link and what they will see when
    they tap it. The link is their standing sign-in, same as an athlete's.
    """
    from .guardians import signin_link

    first = coach_name.split()[0] if coach_name.strip() else "Coach"
    link = signin_link(code)
    subject = f"{org_name}: your 0FFDAYS coach sign-in"
    text = (
        f"{director_name} added you as a coach at {org_name} on 0FFDAYS.\n\n"
        f"Your athletes record drills at home on their own phones; the app "
        f"counts the reps and you see who is putting the work in. No video "
        f"ever reaches you, only the numbers.\n\n"
        f"Sign in here, on any phone or computer:\n{link}\n\n"
        f"Or go to the app and enter the code {code}.\n\n"
        f"Keep this message: the link is your sign-in for the season."
    )
    html = (
        f"<p>{escape(director_name)} added you as a coach at <b>{escape(org_name)}</b> "
        f"on 0FFDAYS.</p>"
        f"<p>Your athletes record drills at home on their own phones; the app counts "
        f"the reps and you see who is putting the work in. No video ever reaches you, "
        f"only the numbers.</p>"
        f'<p><a href="{escape(link)}" style="display:inline-block;padding:12px 20px;'
        f'background:#111;color:#fff;text-decoration:none;border-radius:6px">'
        f"Open your coach dashboard</a></p>"
        f'<p style="color:#555">Or go to the app and enter the code '
        f"<code>{escape(code)}</code>.</p>"
        f'<p style="color:#555;font-size:90%">Keep this message: the link is your '
        f"sign-in for the season.</p>"
    )
    return subject, html, text


def deliver_staff(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    email: str,
    coach_name: str,
    org_name: str,
    director_name: str,
    code: str,
) -> bool:
    """Queue the coach's sign-in email. True only if the program can send it."""
    email = (email or "").strip()
    owner = conn.execute("SELECT org_id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not email or not mailer.can_send(conn, owner["org_id"] if owner else None):
        return False
    subject, html, text = compose_staff(
        coach_name=coach_name, org_name=org_name, director_name=director_name, code=code,
    )
    queued = mailer.enqueue(
        conn,
        to_email=email,
        subject=subject,
        html=html,
        text=text,
        kind=mailer.Kind.TRANSACTIONAL,
        dedupe_key=f"staff_signin:{user_id}:{code[:2]}",
        user_id=user_id,
    )
    return queued is not None


def deliver(
    conn: sqlite3.Connection,
    invite: dict[str, Any],
    *,
    org_name: str,
    coach_name: str,
    intro: str = "",
    queued_ids: list[int] | None = None,
) -> bool:
    """Queue the invite email. True only if the program can actually send it.

    It goes out as a message from 0FFDAYS on behalf of the person who sent it (their name on the From line,
    replies to their own address), with their note on top when they wrote one. The id of what was queued is
    appended to `queued_ids` so the caller can send it at once instead of waiting for the hourly run.

    Transactional, so a digest opt-out never holds it back, and keyed on the
    invite id so a refreshed import cannot send the same code twice. An
    invite with no email (a family the roster had no address for) is simply
    not queued: that family gets the printed slip.

    With no SMTP configured nothing is queued and this returns False, so the
    dashboard offers the director the message to send from their own mail
    rather than telling them it went out. (The console transport reports
    success so dev queues drain; that is a fact about the queue, not about
    whether a parent will ever see the email.)
    """
    email = (invite.get("email") or "").strip()
    if not email:
        return False
    owner = conn.execute(
        "SELECT org_id FROM users WHERE id = ?", (invite.get("athlete_id"),)
    ).fetchone()
    if not mailer.can_send(conn, owner["org_id"] if owner else None):
        return False
    reply_to = staff_reply_to(conn, invite.get("created_by"))
    subject, html, text = compose(
        athlete_name=invite["athlete_name"], org_name=org_name,
        coach_name=coach_name, code=invite["code"], also=invite.get("also_names") or (),
        intro=intro, reply_to=reply_to,
    )
    queued = mailer.enqueue(
        conn,
        to_email=email,
        subject=subject,
        html=html,
        text=text,
        kind=mailer.Kind.TRANSACTIONAL,
        dedupe_key=f"guardian_invite:{invite['invite_id']}",
        from_name=sender_display(coach_name, org_name),
        reply_to=reply_to,
    )
    if queued is not None and queued_ids is not None:
        queued_ids.append(queued)
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
