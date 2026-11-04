"""Where each family is on the way from roster row to a kid who trains.

A director who uploaded forty families and sees twelve training wants one
thing from the dashboard: which of the other twenty-eight is stuck, and on
whom. That is not a training flag (the athlete has not started) and not a
setup step (the program is set up); it is a per-family funnel, and every
stage of it names the person holding it up.

Stages, in order, derived from the tables each step already writes:

    no_parent        no parent email on the roster row and nobody linked --
                     the program has nothing to send; a printed slip or a
                     corrected roster is the fix
    invite_unsent    a parent address is known but no invite was ever issued
    invited          invite issued and emailed, not yet redeemed (the parent
                     has not opened it, or it expired)
    consent_pending  a parent signed up but has not said yes to participation
    link_unsent      the parent said yes and has not sent the child the link
    link_sent        the link went out and the child has not signed in yet
    signed_in        the child has signed in and not recorded a session
    training         at least one counted session

`who` is whose move it is: `program`, `parent`, or `athlete`. The director
nudges parents and athletes; `program` stages are the director's own.

Everything here is read from the database on every call; nothing is cached
or remembered, so a parent who redeems at 9pm moves on the 9:01 refresh.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .guardians import Scope

STAGES: tuple[tuple[str, str, str], ...] = (
    # key, who, what the director reads
    ("no_parent", "program", "No parent on file"),
    ("invite_unsent", "program", "Parent not invited yet"),
    ("invited", "parent", "Invite sent, parent has not signed up"),
    ("consent_pending", "parent", "Parent signed up, has not said yes"),
    ("link_unsent", "parent", "Parent has not sent the athlete their link"),
    ("link_sent", "athlete", "Link sent, athlete has not signed in"),
    ("signed_in", "athlete", "Signed in, has not recorded a session"),
    ("training", "", "Training"),
)
ORDER = {k: i for i, (k, _, _) in enumerate(STAGES)}
WHO = {k: who for k, who, _ in STAGES}
LABEL = {k: label for k, _, label in STAGES}


def stage_for(row: sqlite3.Row) -> str:
    """One athlete's stage from the counts the funnel query joined in."""
    if row["sessions"]:
        return "training"
    if row["last_seen_at"]:
        return "signed_in"
    if row["link_sent_at"]:
        return "link_sent"
    if row["linked_guardians"]:
        return "link_unsent" if row["participation"] else "consent_pending"
    if row["open_invites"]:
        return "invited"
    if row["parent_emails"]:
        return "invite_unsent"
    return "no_parent"


def funnel(
    conn: sqlite3.Connection,
    org_id: int,
    *,
    team_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Every active athlete in the program with their stage and their parent.

    `team_ids` narrows to a coach's teams; None (a director) sees everyone.
    """
    scope = ""
    params: list[Any] = [org_id]
    if team_ids is not None:
        if not team_ids:
            return {"athletes": [], "counts": {k: 0 for k, _, _ in STAGES}, "total": 0, "stages": _stages()}
        marks = ",".join("?" * len(team_ids))
        scope = f"AND u.id IN (SELECT user_id FROM team_members WHERE team_id IN ({marks})) "
        params += team_ids

    rows = conn.execute(
        "SELECT u.id AS athlete_id, u.display_name, u.link_sent_at, u.last_seen_at, "
        "  (SELECT COUNT(*) FROM sessions s WHERE s.athlete_id = u.id "
        "     AND s.status = 'counted') AS sessions, "
        "  (SELECT COUNT(*) FROM guardians g WHERE g.athlete_id = u.id) AS linked_guardians, "
        "  COALESCE((SELECT c.granted FROM consents c WHERE c.athlete_id = u.id "
        "     AND c.scope = ? ORDER BY c.id DESC LIMIT 1), 0) AS participation, "
        "  (SELECT COUNT(*) FROM guardian_invites i WHERE i.athlete_id = u.id "
        "     AND i.redeemed_at IS NULL AND i.revoked_at IS NULL) AS open_invites, "
        "  (SELECT COUNT(*) FROM guardian_contacts gc WHERE gc.athlete_id = u.id "
        "     AND gc.email <> '') AS parent_emails, "
        "  (SELECT gc.name FROM guardian_contacts gc WHERE gc.athlete_id = u.id "
        "     ORDER BY gc.email = '' , gc.id LIMIT 1) AS parent_name, "
        "  (SELECT gc.email FROM guardian_contacts gc WHERE gc.athlete_id = u.id "
        "     AND gc.email <> '' ORDER BY gc.id LIMIT 1) AS parent_email, "
        "  (SELECT MAX(i.created_at) FROM guardian_invites i WHERE i.athlete_id = u.id) "
        "     AS last_invited_at, "
        "  (SELECT COALESCE(t.name, '') FROM team_members tm JOIN teams t ON t.id = tm.team_id "
        "     WHERE tm.user_id = u.id ORDER BY tm.team_id LIMIT 1) AS team_name "
        "FROM users u "
        "WHERE u.org_id = ? AND u.role = 'athlete' AND u.active = 1 " + scope +
        "ORDER BY u.display_name",
        (Scope.PARTICIPATION, *params),
    ).fetchall()

    athletes = []
    counts = {k: 0 for k, _, _ in STAGES}
    for r in rows:
        stage = stage_for(r)
        counts[stage] += 1
        athletes.append({
            "athlete_id": int(r["athlete_id"]),
            "display_name": r["display_name"],
            "team_name": r["team_name"] or "",
            "stage": stage,
            "label": LABEL[stage],
            "who": WHO[stage],
            "parent_name": r["parent_name"] or "",
            "parent_email": r["parent_email"] or "",
            "last_invited_at": r["last_invited_at"],
            "link_sent_at": r["link_sent_at"],
            "last_seen_at": r["last_seen_at"],
            "sessions": int(r["sessions"]),
            # The director can do something from the dashboard only where the
            # program holds an address to send to.
            "can_nudge": stage in ("invite_unsent", "invited") and bool(r["parent_email"]),
        })
    return {
        "athletes": athletes,
        "counts": counts,
        "total": len(athletes),
        "through": counts["training"],
        "stages": _stages(),
    }


def _stages() -> list[dict[str, str]]:
    return [{"key": k, "who": who, "label": label} for k, who, label in STAGES]
