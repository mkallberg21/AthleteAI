"""One athlete in several programs: one kid, one sign-in, the work counted in each.

A club roster creates its own athlete record, so a kid on two clubs' rosters starts as two separate
records, each with its own history. Rather than rebuild every dashboard, ranking, season rule and bill
around "one person in many programs", this keeps one record per program and *links* them. When a session
is counted for one, a copy is counted for each linked record, so each program's coaches, rankings,
streaks, badges and season rules work exactly as they did, and each program sees only what its own
athlete did.

The rules, which are easy to break and costly when broken:

* **A parent links, and only a parent who can prove it.** The proof is an address *the programs* gave
  us: the same roster email, or invite email, is on a parent account in both programs. A name match
  alone never links (two Sam Hills exist), and an address typed at sign-up is not trusted.
* **A parent confirms each link.** The app suggests; the parent chooses. Nothing links by itself.
* **At most one athlete per program in a group.** Two brothers on one club never merge.
* **A copy follows each program's own rules.** Not made if that program's season has ended, if the athlete
  is no longer active there, or if that program's parent has not said yes (or has withdrawn). The source
  session is never affected by a program that refuses its copy.
* **Only counted work is copied**, once, with the same reps and the same XP. A session held for review is
  copied only if and when a coach approves it. A copy is never copied again.
* **Nothing else crosses.** Not the check-ins, not the film watched, not messages, not the other program's
  name to a coach. Each program sees only its own athlete.
* **Work done before the link is not copied.** Linking counts from then on.
* **Either parent can stop it** at any time; the copies already made stay, because that work was done.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timezone
from typing import Any

from . import guardians as guardians_mod
from .db import transaction

logger = logging.getLogger(__name__)


class LinkError(Exception):
    """A link that cannot be made, in words a parent can read."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm(name: str | None) -> str:
    return " ".join((name or "").lower().split())


# ----------------------------------------------------------------------------- who is who
# THE rule for "an address the program gave us", written once. A parent account is trusted at an address
# when the program put it there: the email a redeemed invite was sent to, or a roster contact row. The
# address typed at sign-up (a 'invite' contact row, users.email) is NOT here, because a typo would hand a
# stranger a child's records.
_TRUSTED = (
    "SELECT redeemed_by AS gid, lower(email) AS email FROM guardian_invites "
    "WHERE redeemed_by IS NOT NULL AND COALESCE(email,'') <> '' "
    "UNION SELECT guardian_id AS gid, lower(email) AS email FROM guardian_contacts "
    "WHERE guardian_id IS NOT NULL AND source = 'roster' AND email <> ''"
)


def trusted_emails(conn: sqlite3.Connection, guardian_id: int) -> set[str]:
    """Addresses the PROGRAM gave us for this parent account (never the one typed at sign-up)."""
    return {r[0] for r in conn.execute(f"SELECT email FROM ({_TRUSTED}) WHERE gid = ?", (guardian_id,)).fetchall()}


def _same_person_accounts(conn: sqlite3.Connection, guardian_id: int) -> list[int]:
    """Other active parent accounts that share a program-supplied address with this one."""
    mine = sorted(trusted_emails(conn, guardian_id))
    if not mine:
        return []
    rows = conn.execute(
        f"SELECT DISTINCT t.gid FROM ({_TRUSTED}) t JOIN users g ON g.id = t.gid "
        f"WHERE t.email IN ({','.join('?' * len(mine))}) AND t.gid <> ? "
        "AND g.role = 'guardian' AND g.active = 1 ORDER BY t.gid", [*mine, guardian_id]).fetchall()
    return [int(r[0]) for r in rows]


# ----------------------------------------------------------------------------- groups
def group_of(conn: sqlite3.Connection, athlete_id: int) -> int | None:
    row = conn.execute("SELECT group_id FROM athlete_links WHERE athlete_id = ?", (athlete_id,)).fetchone()
    return int(row[0]) if row else None


def members(conn: sqlite3.Connection, athlete_id: int) -> list[int]:
    """The OTHER athlete records linked to this one."""
    gid = group_of(conn, athlete_id)
    if gid is None:
        return []
    return [int(r[0]) for r in conn.execute(
        "SELECT l.athlete_id FROM athlete_links l JOIN users u ON u.id = l.athlete_id "
        "WHERE l.group_id = ? AND l.athlete_id <> ? AND u.active = 1 AND u.role = 'athlete' "
        "ORDER BY l.athlete_id", (gid, athlete_id)).fetchall()]


def programs(conn: sqlite3.Connection, athlete_id: int) -> list[dict[str, Any]]:
    """Every program this athlete's work counts for, their own first. Empty when not linked."""
    others = members(conn, athlete_id)
    if not others:
        return []
    rows = conn.execute(
        "SELECT u.id, o.id AS org_id, o.name FROM users u JOIN organizations o ON o.id = u.org_id "
        f"WHERE u.id IN ({','.join('?' * (len(others) + 1))})", [athlete_id, *others]).fetchall()
    out = [{"athlete_id": int(r["id"]), "org_id": int(r["org_id"]), "org_name": r["name"]} for r in rows]
    out.sort(key=lambda p: (p["athlete_id"] != athlete_id, p["org_name"].lower()))
    return out


def candidates(conn: sqlite3.Connection, guardian_id: int, athlete_id: int) -> list[dict[str, Any]]:
    """Athletes in OTHER programs this parent could link to, because the same person (by a
    program-supplied address) is a parent there too. Ranked: same name first."""
    guardians_mod.require_guardianship(conn, guardian_id, athlete_id)
    me = conn.execute("SELECT id, org_id, display_name FROM users WHERE id = ?", (athlete_id,)).fetchone()
    taken_orgs = {int(me["org_id"])} | {int(p["org_id"]) for p in programs(conn, athlete_id)}
    out: dict[int, dict[str, Any]] = {}
    for g2 in _same_person_accounts(conn, guardian_id):
        for a in conn.execute(
                "SELECT a.id, a.display_name, a.birth_year, o.id AS org_id, o.name AS org_name "
                "FROM guardians gu JOIN users a ON a.id = gu.athlete_id "
                "JOIN organizations o ON o.id = a.org_id "
                "WHERE gu.guardian_id = ? AND a.active = 1 AND a.role = 'athlete'", (g2,)).fetchall():
            if int(a["org_id"]) in taken_orgs:       # includes every program this athlete is already linked to
                continue
            out[int(a["id"])] = {
                "athlete_id": int(a["id"]), "display_name": a["display_name"], "org_name": a["org_name"],
                "birth_year": a["birth_year"],
                "same_name": _norm(a["display_name"]) == _norm(me["display_name"]),
            }
    return sorted(out.values(), key=lambda c: (not c["same_name"], c["org_name"].lower(), c["athlete_id"]))


def link(conn: sqlite3.Connection, guardian_id: int, athlete_id: int, other_id: int) -> list[dict[str, Any]]:
    """Link two athlete records the parent chose. The other must be one of `candidates`."""
    if other_id == athlete_id:
        raise LinkError("Pick the same athlete in the other program.")
    if int(other_id) not in {c["athlete_id"] for c in candidates(conn, guardian_id, athlete_id)}:
        raise LinkError("That athlete cannot be linked from your account.")
    a_gid, b_gid = group_of(conn, athlete_id), group_of(conn, other_id)
    with transaction(conn) as c:
        gid = a_gid or b_gid
        if gid is None:
            gid = int(c.execute("SELECT COALESCE(MAX(group_id), 0) + 1 FROM athlete_links").fetchone()[0])
        for aid in (athlete_id, other_id):
            c.execute("INSERT OR IGNORE INTO athlete_links(athlete_id, group_id, linked_by, linked_at) "
                      "VALUES (?,?,?,?)", (aid, gid, guardian_id, _now()))
        # two existing groups meeting: everyone in the other group joins this one
        if a_gid and b_gid and a_gid != b_gid:
            c.execute("UPDATE athlete_links SET group_id = ? WHERE group_id = ?", (a_gid, b_gid))
    return programs(conn, athlete_id)


def unlink(conn: sqlite3.Connection, guardian_id: int, athlete_id: int) -> None:
    """Take this athlete record out of its group. Copies already made stay: that work was done."""
    guardians_mod.require_guardianship(conn, guardian_id, athlete_id)
    gid = group_of(conn, athlete_id)
    if gid is None:
        return
    with transaction(conn) as c:
        c.execute("DELETE FROM athlete_links WHERE athlete_id = ?", (athlete_id,))
        left = c.execute("SELECT athlete_id FROM athlete_links WHERE group_id = ?", (gid,)).fetchall()
        if len(left) == 1:                       # a group of one is not a group
            c.execute("DELETE FROM athlete_links WHERE group_id = ?", (gid,))


# ----------------------------------------------------------------------------- counting in each
def _may_receive(conn: sqlite3.Connection, athlete_id: int, day: str) -> bool:
    """That program's own rules: its season is running and its parent has said yes. (That the athlete is
    still active there is decided by `members`.)"""
    row = conn.execute(
        "SELECT o.season_ends_on FROM users u JOIN organizations o ON o.id = u.org_id WHERE u.id = ?",
        (athlete_id,)).fetchone()
    if row is None:
        return False
    ends = row["season_ends_on"]
    if ends:
        try:
            if date.fromisoformat(day) > date.fromisoformat(ends):
                return False                     # that program's season is over
        except ValueError:
            pass
    # that program's parent must have said yes (enforced only once a parent is linked, as everywhere)
    if conn.execute("SELECT 1 FROM guardians WHERE athlete_id = ? LIMIT 1", (athlete_id,)).fetchone():
        if not guardians_mod.has_consent(conn, athlete_id, guardians_mod.Scope.PARTICIPATION):
            return False
    return True


def mirror_session(conn: sqlite3.Connection, session_id: int) -> list[int]:
    """Count a counted session in every linked program that will take it. Returns the athlete ids that
    received a copy (the caller then refreshes their badges). Safe to call twice: it copies once."""
    src = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if src is None or src["status"] != "counted" or src["mirrored_from"] is not None:
        return []
    day = str(src["completed_at"] or src["submitted_at"] or src["started_at"] or "")[:10]
    skip = {"id", "athlete_id", "nonce", "mirrored_from", "result_json"}
    cols = [k for k in src.keys() if k not in skip]
    received: list[int] = []
    for sib in members(conn, int(src["athlete_id"])):
        if not _may_receive(conn, sib, day):
            continue
        if conn.execute("SELECT 1 FROM sessions WHERE athlete_id = ? AND mirrored_from = ?",
                        (sib, session_id)).fetchone():
            continue
        with transaction(conn) as c:
            cur = c.execute(
                f"INSERT INTO sessions(athlete_id, nonce, mirrored_from, {', '.join(cols)}) "
                f"VALUES (?,?,?,{', '.join('?' * len(cols))})",
                (sib, f"mirror-{session_id}-{sib}", session_id, *[src[k] for k in cols]))
            new_id = int(cur.lastrowid)
            c.execute(
                "INSERT INTO rep_events(session_id, t_ms, hand, confidence, peak, rom, cycle_ms, zone, crossed, flare) "
                "SELECT ?, t_ms, hand, confidence, peak, rom, cycle_ms, zone, crossed, flare "
                "FROM rep_events WHERE session_id = ?", (new_id, session_id))
            c.execute(
                "INSERT INTO xp_ledger(athlete_id, session_id, amount, reason, day, created_at) "
                "SELECT ?, ?, amount, reason, day, created_at FROM xp_ledger WHERE session_id = ?",
                (sib, new_id, session_id))
        received.append(sib)
    return received
