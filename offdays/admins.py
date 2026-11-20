"""Administrators: other people who can run a program next to its owner, and handing the program over.

An administrator is a director (the same role, so everything a director can do, they can do: upload rosters, add teams
and coaches, send parent invites, see how every athlete is doing). What makes one person the program's *owner* is
`organizations.owner_user_id`, and only the owner can:

* add or remove an administrator,
* hand the program to another administrator (and, if they wish, leave the program at the same moment),
* change the billing plan.

If `owner_user_id` was never set (every program before this existed), the owner is the program's earliest active
director, which is the person who started it. Nobody has to migrate anything.
"""

from __future__ import annotations

import secrets
import sqlite3
from html import escape
from typing import Any

from . import guardians, mailer, passwords
from .config import CONFIG
from .db import transaction

#: Owner included. A club has a director, maybe a second for another site, and an assistant; more than this is a sign
#: that coaches are being given the wrong role.
MAX_ADMINS = 5


class AdminError(ValueError):
    """Something the owner asked for that cannot be done; the message is for them."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now_iso() -> str:
    return guardians._iso(guardians._now())


def _directors(conn: sqlite3.Connection, org_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT u.id, u.display_name, u.email, m.created_at FROM memberships m JOIN users u ON u.id = m.user_id "
        "WHERE m.org_id = ? AND m.role = 'director' AND m.active = 1 AND u.active = 1 "
        "ORDER BY m.created_at, u.id", (org_id,)).fetchall()


def owner_id(conn: sqlite3.Connection, org_id: int) -> int | None:
    """The program's owner: the person recorded as owner, or else its earliest active director."""
    directors = _directors(conn, org_id)
    if not directors:
        return None
    row = conn.execute("SELECT owner_user_id FROM organizations WHERE id = ?", (org_id,)).fetchone()
    chosen = row["owner_user_id"] if row else None
    if chosen is not None and any(int(d["id"]) == int(chosen) for d in directors):
        return int(chosen)
    return int(directors[0]["id"])


def is_owner(conn: sqlite3.Connection, org_id: int, user_id: int) -> bool:
    return owner_id(conn, org_id) == int(user_id)


def list_admins(conn: sqlite3.Connection, org_id: int, viewer_id: int) -> dict[str, Any]:
    owner = owner_id(conn, org_id)
    admins = [{
        "id": int(d["id"]), "display_name": d["display_name"], "email": d["email"] or "",
        "is_owner": int(d["id"]) == owner, "is_you": int(d["id"]) == int(viewer_id),
    } for d in _directors(conn, org_id)]
    admins.sort(key=lambda a: (not a["is_owner"], a["display_name"].lower()))
    names = [a["display_name"] for a in admins if a["is_owner"]]
    return {"admins": admins, "owner_name": names[0] if names else "", "org_name": _org_name(conn, org_id),
            "you_are_owner": owner == int(viewer_id),
            "max": MAX_ADMINS, "room": max(0, MAX_ADMINS - len(admins))}


def _org_name(conn: sqlite3.Connection, org_id: int) -> str:
    row = conn.execute("SELECT name FROM organizations WHERE id = ?", (org_id,)).fetchone()
    return (row["name"] if row else "") or "your program"


def _app_link() -> str:
    return f"{(CONFIG.app_base_url or '').rstrip('/')}/app/index.html"


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------

WHAT_AN_ADMIN_CAN_DO = ("upload rosters, add teams and coaches, send parent invites, and see how every athlete is doing. "
                        "Only the owner can add or remove administrators, hand the program over, or change the plan")


def compose_welcome(*, name: str, org_name: str, owner_name: str, link: str, promoted: bool) -> tuple[str, str, str]:
    subject = f"{org_name}: you are now an administrator on 0FFDAYS"
    first = (name.split() or ["there"])[0]
    lead = (f"{owner_name} made you an administrator of {org_name} on 0FFDAYS. You were a coach there; now you also run "
            f"the program." if promoted else f"{owner_name} made you an administrator of {org_name} on 0FFDAYS.")
    how = ("Sign in the way you always do, with your email and password or your link." if promoted
           else "Keep this message: the link is your sign-in.")
    text = (f"Hi {first},\n\n{lead}\n\nAn administrator can {WHAT_AN_ADMIN_CAN_DO}.\n\n"
            f"Sign in here, on any phone, tablet or computer:\n{link}\n\n{how}")
    html = (f"<p>Hi {escape(first)},</p><p>{escape(lead)}</p>"
            f"<p>An administrator can {escape(WHAT_AN_ADMIN_CAN_DO)}.</p>"
            f'<p><a href="{escape(link)}" style="display:inline-block;padding:12px 20px;background:#111;color:#fff;'
            f'text-decoration:none;border-radius:6px">Open 0FFDAYS</a></p>{mailer.link_fallback_html(link)}'
            f'<p style="color:#555">{escape(how)}</p>')
    return subject, html, text


def compose_new_owner(*, name: str, org_name: str, old_owner: str, old_stays: bool) -> tuple[str, str, str]:
    first = (name.split() or ["there"])[0]
    link = _app_link()
    subject = f"{org_name}: you now own the program on 0FFDAYS"
    tail = (f"{old_owner} is still an administrator." if old_stays else f"{old_owner} no longer has access.")
    text = (f"Hi {first},\n\n{old_owner} handed ownership of {org_name} on 0FFDAYS to you. You can now add and remove "
            f"administrators, hand the program on, and change the plan. {tail}\n\nSign in here:\n{link}")
    html = (f"<p>Hi {escape(first)},</p><p>{escape(old_owner)} handed ownership of <b>{escape(org_name)}</b> on 0FFDAYS to "
            f"you. You can now add and remove administrators, hand the program on, and change the plan. {escape(tail)}</p>"
            f'<p><a href="{escape(link)}" style="display:inline-block;padding:12px 20px;background:#111;color:#fff;'
            f'text-decoration:none;border-radius:6px">Open 0FFDAYS</a></p>{mailer.link_fallback_html(link)}')
    return subject, html, text


def compose_old_owner(*, name: str, org_name: str, new_owner: str, stays: bool) -> tuple[str, str, str]:
    first = (name.split() or ["there"])[0]
    subject = f"{org_name}: you handed the program to {new_owner} on 0FFDAYS"
    tail = ("You are still an administrator, so you can keep working as before." if stays
            else "Your access has ended. If that was a mistake, ask them to add you back.")
    text = f"Hi {first},\n\nYou handed ownership of {org_name} on 0FFDAYS to {new_owner}. {tail}"
    html = (f"<p>Hi {escape(first)},</p><p>You handed ownership of <b>{escape(org_name)}</b> on 0FFDAYS to "
            f"{escape(new_owner)}. {escape(tail)}</p>")
    return subject, html, text


def _queue(conn: sqlite3.Connection, org_id: int, user_id: int, email: str, message: tuple[str, str, str],
           queued: list[int] | None, kind: str) -> bool:
    """Queue one of these emails if the program may send. The email hold applies like everywhere else."""
    email = (email or "").strip()
    if not email or not mailer.can_send(conn, org_id):
        return False
    subject, html, text = message
    qid = mailer.enqueue(conn, to_email=email, subject=subject, html=html, text=text, kind=mailer.Kind.TRANSACTIONAL,
                         dedupe_key=f"admin_{kind}:{user_id}:{secrets.token_hex(6)}", user_id=user_id)
    if qid is not None and queued is not None:
        queued.append(qid)
    return qid is not None


# ---------------------------------------------------------------------------
# Actions (the caller has already checked who is asking)
# ---------------------------------------------------------------------------

def add_admin(store, org_id: int, by_id: int, *, display_name: str, email: str,
              queued: list[int] | None = None) -> dict[str, Any]:
    conn = store.conn
    email = (email or "").strip()
    name = " ".join((display_name or "").split())
    if not name:
        raise AdminError("Give the administrator's name.")
    if not mailer.looks_like_email(email):
        raise AdminError("An administrator needs an email address, so they can sign in and get back in.")
    if len(_directors(conn, org_id)) >= MAX_ADMINS:
        raise AdminError(f"A program can have up to {MAX_ADMINS} administrators, you included. Remove one first.", 409)
    for d in _directors(conn, org_id):
        if (d["email"] or "").strip().lower() == email.lower():
            raise AdminError(f"{d['display_name']} is already an administrator.", 409)

    owner_name = conn.execute("SELECT display_name FROM users WHERE id = ?", (by_id,)).fetchone()["display_name"]
    org_name = _org_name(conn, org_id)
    coach = conn.execute(
        "SELECT u.id, u.display_name, u.email FROM users u JOIN memberships m ON m.user_id = u.id AND m.org_id = ? "
        "WHERE u.active = 1 AND m.active = 1 AND m.role = 'coach' AND lower(trim(u.email)) = ? ORDER BY u.id LIMIT 1",
        (org_id, email.lower())).fetchone()
    if coach is not None:
        # The same person as an existing coach (matched on email only, as everywhere else): promote, do not duplicate.
        with transaction(conn) as c:
            c.execute("UPDATE memberships SET role = 'director' WHERE user_id = ? AND org_id = ?", (coach["id"], org_id))
            c.execute("UPDATE users SET role = 'director' WHERE id = ? AND org_id = ?", (coach["id"], org_id))
        user_id, token, link, promoted = int(coach["id"]), None, _app_link(), True
        name, email = coach["display_name"], (coach["email"] or email).strip()
    else:
        made = store.create_user(org_id, "director", name, email=email)
        user_id, token, promoted = int(made["id"]), made["token"], False
        link = guardians.signin_link(token)
    message = compose_welcome(name=name, org_name=org_name, owner_name=owner_name, link=link, promoted=promoted)
    emailed = _queue(conn, org_id, user_id, email, message, queued, "welcome")
    return {"user_id": user_id, "display_name": name, "email": email, "promoted": promoted, "emailed": emailed,
            "code": token, "link": link, "subject": message[0], "text": message[2],
            "smtp_configured": mailer.can_send(conn, org_id)}


def _end_access(conn: sqlite3.Connection, org_id: int, user_id: int) -> None:
    with transaction(conn) as c:
        c.execute("DELETE FROM team_staff WHERE user_id = ? AND team_id IN (SELECT id FROM teams WHERE org_id = ?)",
                  (user_id, org_id))
        c.execute("UPDATE memberships SET active = 0 WHERE user_id = ? AND org_id = ?", (user_id, org_id))
        others = c.execute("SELECT COUNT(*) FROM memberships WHERE user_id = ? AND active = 1", (user_id,)).fetchone()[0]
        if not others:
            c.execute("UPDATE users SET active = 0 WHERE id = ?", (user_id,))
        c.execute("DELETE FROM login_links WHERE user_id = ?", (user_id,))
    passwords.end_sessions(conn, user_id)
    conn.commit()


def remove_admin(conn: sqlite3.Connection, org_id: int, by_id: int, user_id: int) -> dict[str, Any]:
    if user_id == by_id:
        raise AdminError("You cannot remove yourself. Hand the program to another administrator and leave instead.")
    if user_id == owner_id(conn, org_id):
        raise AdminError("The owner cannot be removed. Hand the program to another administrator first.")
    row = next((d for d in _directors(conn, org_id) if int(d["id"]) == int(user_id)), None)
    if row is None:
        raise AdminError("No such administrator in this program.", 404)
    _end_access(conn, org_id, user_id)
    return {"removed": True, "user_id": user_id, "display_name": row["display_name"]}


def hand_over(conn: sqlite3.Connection, org_id: int, by_id: int, new_owner_id: int, *, confirm_name: str,
              step_down: bool = False, queued: list[int] | None = None) -> dict[str, Any]:
    org_name = _org_name(conn, org_id)
    if " ".join((confirm_name or "").split()).lower() != " ".join(org_name.split()).lower():
        raise AdminError("Type the program's name exactly to confirm the hand over.")
    if new_owner_id == by_id:
        raise AdminError("You already own this program.")
    new = next((d for d in _directors(conn, org_id) if int(d["id"]) == int(new_owner_id)), None)
    if new is None:
        raise AdminError("Choose one of the program's administrators. Add the person as an administrator first.", 404)
    old = conn.execute("SELECT display_name, email FROM users WHERE id = ?", (by_id,)).fetchone()
    with transaction(conn) as c:
        c.execute("UPDATE organizations SET owner_user_id = ? WHERE id = ?", (new_owner_id, org_id))
    conn.commit()
    told_new = _queue(conn, org_id, int(new["id"]), new["email"] or "",
                      compose_new_owner(name=new["display_name"], org_name=org_name, old_owner=old["display_name"],
                                        old_stays=not step_down), queued, "new_owner")
    told_old = _queue(conn, org_id, by_id, old["email"] or "",
                      compose_old_owner(name=old["display_name"], org_name=org_name, new_owner=new["display_name"],
                                        stays=not step_down), queued, "old_owner")
    if step_down:
        _end_access(conn, org_id, by_id)
    return {"owner_id": int(new_owner_id), "owner_name": new["display_name"], "you_left": bool(step_down),
            "told_new_owner": told_new, "told_you": told_old}
