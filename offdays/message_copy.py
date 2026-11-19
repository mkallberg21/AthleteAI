"""Parents get an email with exactly what their child was sent.

Every message an athlete receives is already copied into the parent's in-app feed (notifications._mirror_to_guardians). For the two
kinds a person writes or a coach sets up, the automatic recognition ("noticed you...") and the coach's own messages (a note to the
team or to the players who need a nudge), the parent is also emailed the very same words: the title and the body as the child saw
them, who sent it, and a link to open 0FFDAYS.

* Word for word. Nothing is summarized or rewritten, so a parent never reads something different from what their child read.
* Held with the program's email hold, like every other email to a family: nothing goes out until the director starts sending.
  Nothing is queued while held, so releasing the hold does not send a backlog of old messages.
* Not for a household program, where the parent writes the messages themselves.
* A parent can stop these copies from the link in the email (one kind of mail, `message_copy`); in-app copies are unaffected.
* One email per parent per child per message.
"""
from __future__ import annotations

import logging
import sqlite3
from html import escape

from . import mailer

logger = logging.getLogger(__name__)

#: Notification kinds whose words a parent is also emailed. Kept as strings so this module does not import notifications.
KINDS = ("recognition", "coach_message")


def _first(name: str | None) -> str:
    parts = (name or "").split()
    return parts[0] if parts else ""


def compose(*, athlete_first: str, sender: str, title: str, body: str, parent_first: str, link: str,
            unsubscribe: str) -> tuple[str, str, str]:
    """(subject, text, html) with the message exactly as the athlete saw it."""
    who = sender or "Your coach"
    kid = athlete_first or "your athlete"
    subject = f"What {who} sent {kid} in 0FFDAYS"
    hello = f"Hi {parent_first}," if parent_first else "Hi,"
    footer_text = ("\n\nThis message was sent automatically and the mailbox is not monitored, so please do not reply."
                   + (f"\nStop these copies: {unsubscribe}" if unsubscribe else ""))
    quoted = "\n".join(x for x in (title, body) if x)
    text = (f"{hello}\n\n{who} sent {kid} this message in 0FFDAYS. It is exactly what {kid} was sent, word for word:\n\n"
            f"{quoted}\n\nYou get a copy of every message {kid} is sent in the app. Open 0FFDAYS: {link}" + footer_text)
    body_html = f"<br>".join(escape(line) for line in body.split("\n")) if body else ""
    html = (f"<p>{escape(hello)}</p>"
            f"<p>{escape(who)} sent {escape(kid)} this message in 0FFDAYS. It is exactly what {escape(kid)} was sent, word for word:</p>"
            f'<blockquote style="margin:12px 0;padding:10px 14px;border-left:4px solid #008BFD;background:#f3f7fb">'
            f"<b>{escape(title)}</b>" + (f"<br>{body_html}" if body_html else "") + "</blockquote>"
            f"<p>You get a copy of every message {escape(kid)} is sent in the app.</p>"
            f'<p><a href="{escape(link)}" style="display:inline-block;padding:12px 20px;background:#111;color:#fff;'
            f'text-decoration:none;border-radius:6px">Open 0FFDAYS</a></p>'
            + mailer.link_fallback_html(link)
            + '<p style="color:#666;font-size:90%">This message was sent automatically and the mailbox is not monitored, '
              "so please do not reply."
            + (f' <a href="{escape(unsubscribe)}" style="color:#666">Stop these copies</a>.' if unsubscribe else "") + "</p>")
    return subject, text, html


def email_parents(conn: sqlite3.Connection, athlete_id: int, kind: str, title: str, body: str, key: str,
                  from_name: str) -> list[int]:
    """Queue one email per parent with the athlete's message word for word. Returns the queued outbox ids (none when held)."""
    if kind not in KINDS:
        return []
    row = conn.execute("SELECT display_name, org_id FROM users WHERE id = ?", (athlete_id,)).fetchone()
    if row is None:
        return []
    org_id = int(row["org_id"])
    # The director's email hold and a working mail provider, the same gate every other family email passes.
    if not mailer.can_send(conn, org_id):
        return []
    kind_row = conn.execute("SELECT kind FROM organizations WHERE id = ?", (org_id,)).fetchone()
    if kind_row is not None and kind_row["kind"] == "family":
        return []
    base = mailer.CONFIG.app_base_url.rstrip("/") if mailer.CONFIG.app_base_url else ""
    link = f"{base}/app/parent.html"
    queued: list[int] = []
    for g in conn.execute(
        "SELECT u.id, u.display_name, u.email FROM guardians gd JOIN users u ON u.id = gd.guardian_id "
        "WHERE gd.athlete_id = ? AND u.active = 1 AND COALESCE(u.email, '') != '' ORDER BY u.id", (athlete_id,)
    ).fetchall():
        try:
            subject, text, html = compose(
                athlete_first=_first(row["display_name"]), sender=from_name, title=title, body=body,
                parent_first=_first(g["display_name"]), link=link,
                unsubscribe=mailer.unsubscribe_url(int(g["id"]), mailer.Kind.MESSAGE_COPY))
            made = mailer.enqueue(conn, to_email=g["email"], subject=subject, html=html, text=text,
                                  kind=mailer.Kind.MESSAGE_COPY, dedupe_key=f"msgcopy:{g['id']}:{athlete_id}:{key}",
                                  user_id=int(g["id"]), from_name=from_name or "")
        except Exception:  # noqa: BLE001 - a copy to a parent must never stop the message reaching the child
            logger.exception("parent copy failed for athlete %s", athlete_id)
            continue
        if made:
            queued.append(made)
    return queued
