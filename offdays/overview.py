"""The director's home: one row per team, then a team, then a player.

Everything here is a read over what the program already holds. Nothing is stored, nothing new is collected, and
nothing is computed a second way:

  * where each family is comes from `funnel.funnel` (the same stages the Families card shows);
  * how much each athlete has done and who is ranked where comes from `leaderboard.team_ranking` (the same
    staff-only ranking, ties and all, with nobody left out for having done nothing);
  * who may see what is the caller's job: every function takes the team ids the caller may read (None = the whole
    program) and never reaches outside them.

Rankings and names are for staff only; this module is only ever called behind `_staff`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from . import funnel as funnel_mod
from .leaderboard import team_ranking, window_start

# A coach who has not opened the app in this long is called out on the home strip.
QUIET_COACH_DAYS = 14
# "Sending videos" is read over this many days.
VIDEO_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days_ago(n: int) -> str:
    return (_now() - timedelta(days=n)).isoformat(timespec="seconds")


def _in(ids: list[int]) -> str:
    return ",".join("?" * len(ids))


def _teams(conn: sqlite3.Connection, org_id: int, team_ids: list[int] | None) -> list[sqlite3.Row]:
    if team_ids is not None and not team_ids:
        return []
    scope = "" if team_ids is None else f"AND t.id IN ({_in(team_ids)}) "
    return conn.execute(
        "SELECT t.id, t.name, t.season FROM teams t WHERE t.org_id = ? " + scope + "ORDER BY t.name COLLATE NOCASE",
        (org_id, *(team_ids or [])),
    ).fetchall()


def _members(conn: sqlite3.Connection, team_ids: list[int]) -> dict[int, list[int]]:
    """team id -> athlete ids on it (active athletes only)."""
    if not team_ids:
        return {}
    out: dict[int, list[int]] = {t: [] for t in team_ids}
    for r in conn.execute(
        f"SELECT tm.team_id, tm.user_id FROM team_members tm JOIN users u ON u.id = tm.user_id "
        f"WHERE tm.team_id IN ({_in(team_ids)}) AND u.role = 'athlete' AND u.active = 1",
        team_ids,
    ):
        out[int(r["team_id"])].append(int(r["user_id"]))
    return out


def _coaches(conn: sqlite3.Connection, team_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """team id -> the coaches on it, with when each last opened the app."""
    if not team_ids:
        return {}
    out: dict[int, list[dict[str, Any]]] = {t: [] for t in team_ids}
    for r in conn.execute(
        f"SELECT ts.team_id, u.id, u.display_name, u.email, u.last_seen_at FROM team_staff ts "
        f"JOIN users u ON u.id = ts.user_id WHERE ts.team_id IN ({_in(team_ids)}) AND u.active = 1 "
        f"ORDER BY u.display_name COLLATE NOCASE",
        team_ids,
    ):
        out[int(r["team_id"])].append({
            "user_id": int(r["id"]), "display_name": r["display_name"], "email": r["email"] or "",
            "last_seen_at": r["last_seen_at"],
        })
    return out


def _count_review(conn: sqlite3.Connection, org_id: int, team_ids: list[int] | None) -> int:
    scope = ""
    params: list[Any] = [org_id]
    if team_ids is not None:
        if not team_ids:
            return 0
        scope = f"AND u.id IN (SELECT user_id FROM team_members WHERE team_id IN ({_in(team_ids)})) "
        params += team_ids
    return int(conn.execute(
        "SELECT COUNT(*) FROM sessions s JOIN users u ON u.id = s.athlete_id "
        "WHERE s.status = 'review' AND u.org_id = ? " + scope, params).fetchone()[0])


def program_overview(conn: sqlite3.Connection, org_id: int, team_ids: list[int] | None, window: str = "week",
                     *, suggestions: int = 0) -> dict[str, Any]:
    """One row per team, and the short list of things that need a person.

    `team_ids` is the caller's scope. `suggestions` is how many scanned videos are waiting for a coach, passed in
    because the scanner is lacrosse-only and the caller already knows the sport.
    """
    teams = _teams(conn, org_id, team_ids)
    ids = [int(t["id"]) for t in teams]
    members = _members(conn, ids)
    coaches = _coaches(conn, ids)
    fun = funnel_mod.funnel(conn, org_id, team_ids=team_ids)
    by_athlete = {a["athlete_id"]: a for a in fun["athletes"]}
    ranking = {r["athlete_id"]: r for r in team_ranking(conn, org_id, team_ids, window)}   # type: ignore[arg-type]

    rows: list[dict[str, Any]] = []
    stuck_total = 0
    for t in teams:
        tid = int(t["id"])
        kids = members.get(tid, [])
        training = sum(1 for a in kids if by_athlete.get(a, {}).get("stage") == "training")
        stuck = len(kids) - training
        stuck_total += stuck
        stages: dict[str, int] = {}
        for a in kids:
            s = by_athlete.get(a, {}).get("stage")
            if s and s != "training":
                stages[s] = stages.get(s, 0) + 1
        active = [ranking[a]["last_active"] for a in kids if a in ranking and ranking[a]["last_active"]]
        cs = coaches.get(tid, [])
        seen = [c["last_seen_at"] for c in cs if c["last_seen_at"]]
        if not kids:
            state = "no_players"
        elif not cs:
            state = "no_coach"
        elif stuck:
            state = "stuck"
        else:
            state = "training"
        rows.append({
            "id": tid, "name": t["name"], "players": len(kids), "training": training, "stuck": stuck,
            "stuck_stages": stages, "xp": sum(ranking[a]["xp"] for a in kids if a in ranking),
            "last_active": max(active) if active else None,
            "coaches": [{"user_id": c["user_id"], "display_name": c["display_name"]} for c in cs],
            "coach_last_seen": max(seen) if seen else None,
            "state": state,
        })

    quiet_cut = _days_ago(QUIET_COACH_DAYS)
    quiet = sorted({c["display_name"] for cs in coaches.values() for c in cs
                    if not c["last_seen_at"] or c["last_seen_at"] < quiet_cut})
    never = sorted({c["display_name"] for cs in coaches.values() for c in cs if not c["last_seen_at"]})
    attention = {
        "stuck_families": stuck_total,
        "teams_without_coach": [r["name"] for r in rows if r["state"] == "no_coach"],
        "teams_without_players": [r["name"] for r in rows if r["state"] == "no_players"],
        "coaches_not_signed_in": never,
        "coaches_quiet": [n for n in quiet if n not in never],
        "suggested_videos": suggestions,
        "sessions_to_review": _count_review(conn, org_id, team_ids),
    }
    attention["total"] = (
        (1 if attention["stuck_families"] else 0) + len(attention["teams_without_coach"]) + len(attention["teams_without_players"])
        + (1 if attention["coaches_not_signed_in"] else 0) + (1 if attention["coaches_quiet"] else 0)
        + (1 if attention["suggested_videos"] else 0) + (1 if attention["sessions_to_review"] else 0))
    return {
        "window": window,
        "teams": rows,
        "totals": {"teams": len(rows), "players": len(by_athlete), "training": fun["through"], "stuck": stuck_total},
        "attention": attention,
        "mail_sending": fun["mail_sending"],
        "stages": fun["stages"],
    }


def team_detail(conn: sqlite3.Connection, org_id: int, team_id: int, window: str = "week") -> dict[str, Any]:
    """One team: its players ranked (everyone, including those with nothing done), its coaches, its families."""
    team = conn.execute("SELECT id, name, season FROM teams WHERE id = ? AND org_id = ?", (team_id, org_id)).fetchone()
    if team is None:
        raise LookupError("unknown team")
    fun = funnel_mod.funnel(conn, org_id, team_ids=[team_id])
    by_athlete = {a["athlete_id"]: a for a in fun["athletes"]}
    players = []
    for r in team_ranking(conn, org_id, [team_id], window):
        f = by_athlete.get(r["athlete_id"], {})
        players.append({
            "athlete_id": r["athlete_id"], "display_name": r["display_name"], "rank": r["rank"], "xp": r["xp"],
            "trained": r["trained"], "last_active": r["last_active"],
            "stage": f.get("stage", ""), "stage_label": f.get("label", ""), "who": f.get("who", ""),
            "sessions": f.get("sessions", 0), "can_nudge": bool(f.get("can_nudge")),
        })
    cs = _coaches(conn, [team_id]).get(team_id, [])
    since = _days_ago(VIDEO_DAYS)
    for c in cs:
        c["videos_30d"] = int(conn.execute(
            "SELECT COUNT(*) FROM clips WHERE org_id = ? AND created_by = ? AND shelf = '' AND created_at >= ?",
            (org_id, c["user_id"], since)).fetchone()[0])
    stages = {k: v for k, v in fun["counts"].items() if v and k != "training"}
    return {
        "window": window, "team": {"id": int(team["id"]), "name": team["name"], "season": team["season"] or ""},
        "players": players, "coaches": cs,
        "counts": {"players": len(players), "training": fun["through"], "stuck": len(players) - fun["through"],
                   "stages": stages},
        "stages": fun["stages"], "mail_sending": fun["mail_sending"],
    }


def player_detail(conn: sqlite3.Connection, org_id: int, athlete_id: int, window: str = "week") -> dict[str, Any]:
    """One player: where the family is, who the parent is, and the last few sessions. Staff only."""
    user = conn.execute(
        "SELECT id, display_name, birth_year, last_seen_at, link_sent_at FROM users "
        "WHERE id = ? AND org_id = ? AND role = 'athlete' AND active = 1", (athlete_id, org_id)).fetchone()
    if user is None:
        raise LookupError("unknown athlete")
    teams = conn.execute(
        "SELECT t.id, t.name, tm.jersey, tm.position FROM team_members tm JOIN teams t ON t.id = tm.team_id "
        "WHERE tm.user_id = ? ORDER BY t.name COLLATE NOCASE", (athlete_id,)).fetchall()
    team_ids = [int(t["id"]) for t in teams]
    fun = funnel_mod.funnel(conn, org_id, team_ids=team_ids or [-1])
    row = next((a for a in fun["athletes"] if a["athlete_id"] == athlete_id), {})
    rank = next((r for r in team_ranking(conn, org_id, team_ids, window)       # type: ignore[arg-type]
                 if r["athlete_id"] == athlete_id), None) if team_ids else None
    contacts = [dict(c) for c in conn.execute(
        "SELECT name, email, phone, relationship FROM guardian_contacts WHERE athlete_id = ? ORDER BY id", (athlete_id,))]
    recent = [dict(s) for s in conn.execute(
        "SELECT drill_key, reps_total, started_at, status FROM sessions WHERE athlete_id = ? "
        "AND status IN ('counted','review') ORDER BY id DESC LIMIT 10", (athlete_id,))]
    return {
        "window": window,
        "athlete": {"id": int(user["id"]), "display_name": user["display_name"], "birth_year": user["birth_year"]},
        "teams": [{"id": int(t["id"]), "name": t["name"], "jersey": t["jersey"] or "", "position": t["position"] or ""}
                  for t in teams],
        "stage": row.get("stage", ""), "stage_label": row.get("label", ""), "who": row.get("who", ""),
        "can_nudge": bool(row.get("can_nudge")), "last_seen_at": user["last_seen_at"],
        "link_sent_at": user["link_sent_at"], "last_invited_at": row.get("last_invited_at"),
        "rank": rank["rank"] if rank else None, "xp": rank["xp"] if rank else 0,
        "last_active": rank["last_active"] if rank else None,
        "sessions": row.get("sessions", 0), "recent_sessions": recent, "parents": contacts,
        "mail_sending": fun["mail_sending"], "stages": fun["stages"],
    }


def coaches_overview(conn: sqlite3.Connection, org_id: int) -> dict[str, Any]:
    """Every coach in the program: their teams, when they last opened the app, and the videos they have added."""
    since = _days_ago(VIDEO_DAYS)
    out = []
    for r in conn.execute(
        "SELECT u.id, u.display_name, u.email, u.last_seen_at FROM memberships m JOIN users u ON u.id = m.user_id "
        "WHERE m.org_id = ? AND m.role = 'coach' AND m.active = 1 AND u.active = 1 "
        "ORDER BY u.display_name COLLATE NOCASE", (org_id,)):
        teams = [dict(t) for t in conn.execute(
            "SELECT t.id, t.name FROM team_staff ts JOIN teams t ON t.id = ts.team_id "
            "WHERE ts.user_id = ? AND t.org_id = ? ORDER BY t.name COLLATE NOCASE", (r["id"], org_id))]
        v30, vall = conn.execute(
            "SELECT COALESCE(SUM(created_at >= ?), 0), COUNT(*) FROM clips "
            "WHERE org_id = ? AND created_by = ? AND shelf = '' AND active = 1", (since, org_id, r["id"])).fetchone()
        out.append({"user_id": int(r["id"]), "display_name": r["display_name"], "email": r["email"] or "",
                    "last_seen_at": r["last_seen_at"], "teams": teams,
                    "videos_30d": int(v30), "videos_total": int(vall)})
    return {"coaches": out, "video_days": VIDEO_DAYS}


__all__ = ["program_overview", "team_detail", "player_detail", "coaches_overview", "window_start",
           "QUIET_COACH_DAYS", "VIDEO_DAYS"]
