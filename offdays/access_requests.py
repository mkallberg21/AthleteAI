"""An athlete with no way in asks a coach to let them in, and the coach says yes with one tap.

A child's way in is the link a parent sent. Links go missing: a new phone, a cleared browser, the app added to the home
screen (which on an iPhone starts signed out), or a parent who made a newer link. The child has no email address to
fall back on, and sending the parent back through it every time is the thing this avoids.

So, at the sign-in page, the athlete types their name and asks. Their coaches and directors see the request on the
dashboard (and get an email), and one tap lets that one device in. Nothing is sent to the child, because there is
nowhere to send it: the phone that asked keeps a secret, and once a coach has said yes that secret is swapped, once,
for a sign-in on that phone.

What keeps this from being a way into someone else's account:

* A coach or director who can already see that athlete has to say yes. Nobody gets in by asking.
* The phone shows a two-digit number and the coach sees the same number beside the request, so a coach who is unsure
  can ask "what number is on your screen?".
* Only an athlete whose parent has said yes to training can be let in. This never replaces a parent's consent.
* The parent is emailed that a coach let their child in on a new device (held with the program's email hold), and
  making a new link from the parent page signs these devices out along with every other one.
* The answer to "ask" is the same whether or not the name matched anyone, so the page cannot be used to find out
  which children are in a program.
* Asking is limited per network and per athlete, and a request lapses after three days.

Only a hash of the phone's secret and of the sign-in it was swapped for is kept.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

from . import mailer
from . import passwords as pw

logger = logging.getLogger(__name__)

REQUEST_HOURS = 72            # how long a coach has to answer
SESSION_DAYS = 180            # how long the phone stays signed in once let in
PER_SOURCE_HOURLY = 30        # a whole team on one Wi-Fi can ask; a script cannot do much
PER_ATHLETE_PENDING = 3       # open requests one athlete can have waiting
STAFF_MAIL_MINUTES = 60       # at most one email per coach per athlete in this long

REPLY = ("Your coach has been asked. Keep this page open, or come back to it on this phone later. "
         "When your coach says yes, you are in.")


class AccessError(ValueError):
    """A request that cannot be acted on. The message is safe to show."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _digest(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _tidy(name: str | None) -> str:
    """A name the way people type it, made comparable: case, spacing and punctuation do not matter."""
    return " ".join(re.sub(r"[.,'’`\-]", " ", (name or "").lower()).split())


def _first(name: str | None) -> str:
    parts = (name or "").split()
    return parts[0] if parts else ""


# ----------------------------------------------------------------------- asking
def _matches(conn: sqlite3.Connection, typed: str) -> list[sqlite3.Row]:
    """Active athletes with exactly this name whose parent has said yes to training."""
    from . import guardians

    wanted = _tidy(typed)
    if len(wanted) < 3 or " " not in wanted:
        return []                                    # a first name alone is not enough to pick out one child
    rows = conn.execute(
        "SELECT id, org_id, display_name FROM users WHERE role = 'athlete' AND active = 1 "
        "AND lower(display_name) LIKE ? ORDER BY id", (wanted.split()[0][:40] + "%",)).fetchall()
    return [r for r in rows if _tidy(r["display_name"]) == wanted
            and guardians.has_consent(conn, int(r["id"]), guardians.Scope.PARTICIPATION)]


def ask(conn: sqlite3.Connection, name: str, source: str | None = None) -> dict[str, Any]:
    """Record a request and tell the athlete's coaches. The reply never says whether the name matched."""
    typed = " ".join((name or "").split())[:120]
    if len(typed) < 2:
        raise AccessError("Type your first and last name.")
    now = _now()
    conn.execute("DELETE FROM access_requests WHERE expires_at < ?", (_iso(now - timedelta(days=30)),))
    secret = secrets.token_urlsafe(32)
    number = str(secrets.randbelow(90) + 10)
    source_hash = _digest("source:" + (source or "unknown"))[:32]
    recent = int(conn.execute(
        "SELECT COUNT(DISTINCT device_hash) FROM access_requests WHERE source_hash = ? AND created_at >= ?",
        (source_hash, _iso(now - timedelta(hours=1)))).fetchone()[0])
    found = _matches(conn, typed) if recent < PER_SOURCE_HOURLY else []
    rows = []
    for a in found:
        waiting = int(conn.execute(
            "SELECT COUNT(*) FROM access_requests WHERE athlete_id = ? AND status = 'pending' AND expires_at > ?",
            (a["id"], _iso(now))).fetchone()[0])
        if waiting < PER_ATHLETE_PENDING:
            rows.append((int(a["id"]), int(a["org_id"])))
    # A row is written even when nobody matched, so the phone's later checks look the same either way.
    for athlete_id, org_id in rows or [(None, None)]:
        conn.execute(
            "INSERT INTO access_requests(athlete_id, org_id, device_hash, source_hash, pair_code, typed_name, status, "
            "created_at, expires_at) VALUES (?,?,?,?,?,?,'pending',?,?)",
            (athlete_id, org_id, _digest(secret), source_hash, number, typed if athlete_id else '', _iso(now),
             _iso(now + timedelta(hours=REQUEST_HOURS))))
    conn.commit()
    for athlete_id, _org in rows:
        try:
            _tell_staff(conn, athlete_id, number)
        except Exception:  # noqa: BLE001 - mail must never break the page the child is on
            logger.exception("access request mail failed for athlete %s", athlete_id)
    return {"secret": secret, "number": number, "message": REPLY}


# ------------------------------------------------------------------ the dashboard
def _teams(conn: sqlite3.Connection, athlete_id: int) -> list[str]:
    return [r["name"] for r in conn.execute(
        "SELECT t.name FROM team_members tm JOIN teams t ON t.id = tm.team_id WHERE tm.user_id = ? ORDER BY t.name",
        (athlete_id,))]


def pending(conn: sqlite3.Connection, org_id: int, can_see) -> list[dict[str, Any]]:
    """Requests waiting in this program that this staff member may answer. `can_see(athlete_id)` is their scope."""
    out = []
    for r in conn.execute(
        "SELECT r.id, r.athlete_id, r.pair_code, r.created_at, u.display_name FROM access_requests r "
        "JOIN users u ON u.id = r.athlete_id WHERE r.org_id = ? AND r.status = 'pending' AND r.expires_at > ? "
        "AND u.active = 1 ORDER BY r.id", (org_id, _iso(_now()))):
        if can_see(int(r["athlete_id"])):
            out.append({"id": int(r["id"]), "athlete_id": int(r["athlete_id"]), "name": r["display_name"],
                        "teams": _teams(conn, int(r["athlete_id"])), "number": r["pair_code"],
                        "asked_at": r["created_at"]})
    return out


def _open(conn: sqlite3.Connection, request_id: int, org_id: int, can_see) -> sqlite3.Row:
    row = conn.execute(
        "SELECT r.*, u.display_name FROM access_requests r JOIN users u ON u.id = r.athlete_id "
        "WHERE r.id = ? AND r.org_id = ? AND u.active = 1", (request_id, org_id)).fetchone()
    if row is None or not can_see(int(row["athlete_id"])):
        raise AccessError("That request is not there any more.")
    if row["status"] != "pending" or datetime.fromisoformat(row["expires_at"]) <= _now():
        raise AccessError("That request has already been answered, or it ran out.")
    return row


def approve(conn: sqlite3.Connection, request_id: int, org_id: int, staff_id: int, staff_name: str,
            can_see) -> dict[str, Any]:
    """Let that one phone in. Its other requests (the same name in another program) are closed."""
    from . import guardians

    row = _open(conn, request_id, org_id, can_see)
    athlete_id = int(row["athlete_id"])
    if not guardians.has_consent(conn, athlete_id, guardians.Scope.PARTICIPATION):
        raise AccessError("A parent has not said yes to training for this athlete, so there is nothing to let them into.")
    now = _iso(_now())
    conn.execute("UPDATE access_requests SET status = 'approved', decided_by = ?, decided_at = ? WHERE id = ?",
                 (staff_id, now, request_id))
    conn.execute("UPDATE access_requests SET status = 'denied', decided_at = ? "
                 "WHERE device_hash = ? AND id != ? AND status = 'pending'", (now, row["device_hash"], request_id))
    conn.commit()
    try:
        _tell_parents(conn, athlete_id, staff_name, request_id)
    except Exception:  # noqa: BLE001 - the parent's notice must never stop the child getting in
        logger.exception("access notice to parents failed for athlete %s", athlete_id)
    return {"ok": True, "name": row["display_name"]}


def deny(conn: sqlite3.Connection, request_id: int, org_id: int, staff_id: int, can_see) -> dict[str, Any]:
    row = _open(conn, request_id, org_id, can_see)
    conn.execute("UPDATE access_requests SET status = 'denied', decided_by = ?, decided_at = ? WHERE id = ?",
                 (staff_id, _iso(_now()), request_id))
    conn.commit()
    return {"ok": True, "name": row["display_name"]}


# -------------------------------------------------------------------- the phone
def check(conn: sqlite3.Connection, secret: str) -> dict[str, Any]:
    """What the waiting phone asks every few seconds. A yes is swapped for a sign-in exactly once."""
    if not secret or len(secret) > 200:
        return {"status": "waiting"}
    rows = conn.execute(
        "SELECT r.id, r.athlete_id, r.status, r.expires_at, u.active FROM access_requests r "
        "LEFT JOIN users u ON u.id = r.athlete_id WHERE r.device_hash = ? ORDER BY r.id", (_digest(secret),)).fetchall()
    if not rows:
        return {"status": "waiting"}
    now = _now()
    yes = next((r for r in rows if r["status"] == "approved" and r["active"]), None)
    if yes is not None:
        token = pw.start_session(conn, int(yes["athlete_id"]), days=SESSION_DAYS)
        conn.execute("UPDATE access_requests SET status = 'claimed', session_hash = ? WHERE id = ?",
                     (pw._token_digest(token), yes["id"]))
        conn.commit()
        return {"status": "approved", "token": token}
    if any(r["status"] == "claimed" for r in rows):
        return {"status": "used"}
    if all(datetime.fromisoformat(r["expires_at"]) <= now for r in rows):
        return {"status": "expired"}
    # "No" is only said when a coach actually answered a request for a real athlete. A name nobody matched keeps waiting,
    # so the page cannot be used to learn who is on a team.
    live = [r for r in rows if r["athlete_id"] is not None]
    if live and all(r["status"] == "denied" for r in live):
        return {"status": "denied"}
    return {"status": "waiting"}


def end_sessions(conn: sqlite3.Connection, athlete_id: int) -> int:
    """Sign out every phone a coach let in for this athlete (a parent made a new link, which is their off switch)."""
    hashes = [r["session_hash"] for r in conn.execute(
        "SELECT session_hash FROM access_requests WHERE athlete_id = ? AND session_hash IS NOT NULL", (athlete_id,))]
    for h in hashes:
        conn.execute("DELETE FROM staff_sessions WHERE token_hash = ?", (h,))
    conn.execute("UPDATE access_requests SET status = 'denied' WHERE athlete_id = ? AND status IN ('pending','approved')",
                 (athlete_id,))
    return len(hashes)


# ------------------------------------------------------------------------- mail
def _dashboard() -> str:
    base = mailer.CONFIG.app_base_url.rstrip("/") if mailer.CONFIG.app_base_url else ""
    return f"{base}/app/coach.html"


def _button(url: str, label: str) -> str:
    return (f'<p><a href="{escape(url)}" style="display:inline-block;padding:12px 20px;background:#111;color:#fff;'
            f'text-decoration:none;border-radius:6px">{escape(label)}</a></p>' + mailer.link_fallback_html(url))


def staff_for(conn: sqlite3.Connection, athlete_id: int) -> list[sqlite3.Row]:
    """The coaches of this athlete's teams and the program's directors, with an address to write to."""
    return conn.execute(
        "SELECT DISTINCT u.id, u.display_name, u.email FROM users u WHERE u.active = 1 AND COALESCE(u.email, '') != '' "
        "AND ((u.role = 'director' AND u.org_id = (SELECT org_id FROM users WHERE id = ?)) "
        "  OR (u.role = 'coach' AND u.id IN (SELECT ts.user_id FROM team_staff ts JOIN team_members tm "
        "      ON tm.team_id = ts.team_id WHERE tm.user_id = ?))) ORDER BY u.id", (athlete_id, athlete_id)).fetchall()


def compose_staff(*, athlete: str, teams: list[str], org_name: str, number: str, link: str) -> tuple[str, str, str]:
    where = f" ({', '.join(teams)})" if teams else ""
    subject = f"{org_name}: {athlete} is asking to be let in to 0FFDAYS"
    lead = (f"{athlete}{where} is at the 0FFDAYS sign-in page without a working link and asked to be let in. "
            f"The number on their screen is {number}.")
    how = ("If you are expecting this, open your dashboard and tap Let them in. That signs in the phone that asked and "
           "nothing else. If you are not sure it is them, ask what number is on their screen, or tap No.")
    foot = "This message was sent automatically and the mailbox is not monitored, so please do not reply."
    text = f"{lead}\n\n{how}\n\n{link}\n\n{foot}"
    html = (f"<p>{escape(lead)}</p><p>{escape(how)}</p>" + _button(link, "Open my dashboard")
            + f'<p style="color:#666;font-size:90%">{escape(foot)}</p>')
    return subject, text, html


def _tell_staff(conn: sqlite3.Connection, athlete_id: int, number: str) -> list[int]:
    if not mailer.CONFIG.smtp_configured:
        return []
    a = conn.execute("SELECT u.display_name, o.name AS org FROM users u JOIN organizations o ON o.id = u.org_id "
                     "WHERE u.id = ?", (athlete_id,)).fetchone()
    if a is None:
        return []
    bucket = int(_now().timestamp() // (STAFF_MAIL_MINUTES * 60))
    subject, text, html = compose_staff(athlete=a["display_name"], teams=_teams(conn, athlete_id), org_name=a["org"],
                                        number=number, link=_dashboard())
    queued = []
    for s in staff_for(conn, athlete_id):
        made = mailer.enqueue(conn, to_email=s["email"], subject=subject, html=html, text=text,
                              kind=mailer.Kind.TRANSACTIONAL, dedupe_key=f"access:{athlete_id}:{s['id']}:{bucket}",
                              user_id=int(s["id"]))
        if made:
            queued.append(made)
    if queued:
        mailer.flush(conn, only_ids=queued)
    return queued


def compose_parent(*, child: str, coach: str, parent_first: str, link: str) -> tuple[str, str, str]:
    kid = child or "your athlete"
    who = coach or "A coach"
    subject = f"{who} let {kid} sign in to 0FFDAYS on a new device"
    hello = f"Hi {parent_first}," if parent_first else "Hi,"
    lead = (f"{kid} was at the 0FFDAYS sign-in page without a working link and asked a coach to be let in. "
            f"{who} said yes, so that one device is now signed in as {kid}.")
    undo = (f"There is nothing you need to do. If that was not {kid}, open your parent page and make a new sign-in "
            "link. That signs out every device, this one included, and the new link is the only way back in.")
    foot = "This message was sent automatically and the mailbox is not monitored, so please do not reply."
    text = f"{hello}\n\n{lead}\n\n{undo}\n\n{link}\n\n{foot}"
    html = (f"<p>{escape(hello)}</p><p>{escape(lead)}</p><p>{escape(undo)}</p>" + _button(link, "Open my parent page")
            + f'<p style="color:#666;font-size:90%">{escape(foot)}</p>')
    return subject, text, html


def _tell_parents(conn: sqlite3.Connection, athlete_id: int, coach: str, request_id: int) -> list[int]:
    a = conn.execute("SELECT display_name, org_id FROM users WHERE id = ?", (athlete_id,)).fetchone()
    if a is None or not mailer.can_send(conn, int(a["org_id"])):
        return []                                    # the director's hold covers every email to a family
    base = mailer.CONFIG.app_base_url.rstrip("/") if mailer.CONFIG.app_base_url else ""
    queued = []
    for g in conn.execute(
        "SELECT u.id, u.display_name, u.email FROM guardians gd JOIN users u ON u.id = gd.guardian_id "
        "WHERE gd.athlete_id = ? AND u.active = 1 AND COALESCE(u.email, '') != '' ORDER BY u.id", (athlete_id,)
    ).fetchall():
        subject, text, html = compose_parent(child=_first(a["display_name"]), coach=coach,
                                             parent_first=_first(g["display_name"]), link=f"{base}/app/parent.html")
        made = mailer.enqueue(conn, to_email=g["email"], subject=subject, html=html, text=text,
                              kind=mailer.Kind.TRANSACTIONAL, dedupe_key=f"access-let-in:{request_id}:{g['id']}",
                              user_id=int(g["id"]))
        if made:
            queued.append(made)
    if queued:
        mailer.flush(conn, only_ids=queued)
    return queued
