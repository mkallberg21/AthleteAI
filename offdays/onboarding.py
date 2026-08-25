"""Getting a new program from nothing to a working first week.

A director who signs up lands on a dashboard of fifteen cards, fourteen of them
empty, with nothing saying which one matters first. Every feature works and
none of them is reachable, because the order is invisible: a team has to exist
before an athlete can join one, an athlete has to exist before a code can be
handed out, and a code has to be handed out before anything happens at all.

Two things make this a checklist rather than a tour.

**Every step is derived from the database, never from a flag saying somebody
clicked "done".** A remembered dismissal is a checklist that lies: it stays
ticked after the team is deleted, and it cannot tell a director who got
half-way and came back a week later where they actually are. Computing it means
it is always true, and a step can un-tick itself if the thing it describes goes
away.

**It ends.** Once the required steps are done the whole thing collapses, because
a setup guide that never goes away stops being a guide and becomes furniture.

Separately from the steps there are `blockers`: things actively stopping
athletes from training *right now*. The one that matters is the consent gate --
enforcement begins the moment a parent is linked, so a director who invites
parents on Monday finds their athletes locked out on Tuesday and has no way to
know why. Naming it before it bites is most of the value here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from . import guardians
from .config import CONFIG


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    #: What to do, in the imperative. No more than a sentence.
    detail: str
    #: Why it is worth doing. Omitted where the title says it.
    why: str = ""
    #: Required steps gate "set up"; the rest are worth doing and can wait.
    required: bool = True
    #: Which card on the dashboard does this, for the UI to point at.
    anchor: str = ""

    def to_dict(self, done: bool, count: int = 0) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "detail": self.detail,
            "why": self.why,
            "required": self.required,
            "anchor": self.anchor,
            "done": done,
            "count": count,
        }


PROGRAM_STEPS: tuple[Step, ...] = (
    Step(
        key="team",
        title="Create your first team",
        detail="Give it a name and a season. Athletes join with its code.",
        anchor="scope-card",
    ),
    Step(
        key="athletes",
        title="Add your athletes",
        detail="One at a time, or paste a roster and import the lot.",
        why="Birth year matters more than it looks: everything is age-scaled.",
        anchor="import-card",
    ),
    Step(
        key="first_session",
        title="Get one athlete training",
        detail="Hand out their code and have them record one session.",
        why=(
            "The only step that proves the whole chain works — code handed "
            "over, app installed, camera pointed, session counted."
        ),
        anchor="roster-card",
    ),
    Step(
        key="parents",
        title="Invite the parents",
        detail="Send a guardian invite for each athlete.",
        why=(
            "Parents consent, and once one is linked their decision is what "
            "lets that athlete train. Better to do it early than mid-season."
        ),
        required=False,
        anchor="slips-card",
    ),
    Step(
        key="recognition",
        title="Write one message in your own voice",
        detail="Replace at least one of the shipped milestones with your words.",
        why="The defaults are placeholders and they read like it.",
        required=False,
        anchor="recognition-card",
    ),
    Step(
        key="staff",
        title="Add another coach",
        detail="Assign them to a team so they see only their own athletes.",
        required=False,
        anchor="staff-card",
    ),
)

FAMILY_STEPS: tuple[Step, ...] = (
    Step(
        key="athletes",
        title="Add your children",
        detail="Name and birth year. Everything is scaled by age.",
        anchor="scope-card",
    ),
    Step(
        key="first_session",
        title="Get one of them training",
        detail="Hand over their code and have them record one session.",
        why="Proves the whole chain works before you rely on it.",
        anchor="roster-card",
    ),
    Step(
        key="recognition",
        title="Write one message in your own words",
        detail="The shipped wording is a placeholder and reads like one.",
        required=False,
        anchor="recognition-card",
    ),
)


ATHLETE_STEPS: tuple[Step, ...] = (
    Step(
        key="first_session",
        title="Record one drill",
        detail="Pick anything from the list. Two minutes is a real session.",
        why="Nothing else here does anything until you have done one.",
        anchor="drill-list",
    ),
    Step(
        key="install",
        title="Put it on your home screen",
        detail="Your phone's share menu, then Add to Home Screen.",
        why="It then works in a driveway with no signal, and syncs later.",
        required=False,
        anchor="",
    ),
    Step(
        key="check_in",
        title="Say how you feel",
        detail="One tap. It never costs you a streak — that is the whole point.",
        required=False,
        anchor="wellness-card",
    ),
    Step(
        key="film",
        title="Watch one clip",
        detail="A couple of minutes of film, with something to look for.",
        required=False,
        anchor="film-card",
    ),
)

JOINING_STEPS: tuple[Step, ...] = (
    Step(
        key="recognition",
        title="Make the milestone messages yours",
        detail="Replace one of the shipped lines with something you would say.",
        why=(
            "These go out signed with your name to the athletes on your teams. "
            "Worth knowing before the first one does."
        ),
        required=False,
        anchor="recognition-card",
    ),
    Step(
        key="assignment",
        title="Set some work for your team",
        detail="A drill, a target and a window. They see it on their home screen.",
        required=False,
        anchor="roster-card",
    ),
    Step(
        key="review",
        title="Clear the review queue",
        detail="Sessions the app held rather than counted, waiting on a person.",
        why="Usually a framing or a signal problem, not anyone doing anything wrong.",
        required=False,
        anchor="review-card",
    ),
)


#: Said once, at the start, and never again. It is the thing that makes an
#: athlete and their parent comfortable, and it is true -- so it is worth the
#: line before anyone points a camera at a child.
PROMISE = (
    "Your phone watches you and counts the reps. The video never leaves it — "
    "not to us, not to your coach. What they see is the numbers."
)


def _count(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


def _state(conn: sqlite3.Connection, org_id: int) -> dict[str, int]:
    """One pass over the real state. Nothing here is remembered from a click."""
    return {
        "team": _count(conn, "SELECT COUNT(*) FROM teams WHERE org_id = ?", (org_id,)),
        "athletes": _count(
            conn,
            "SELECT COUNT(*) FROM users WHERE org_id = ? AND role = 'athlete' "
            "AND active = 1",
            (org_id,),
        ),
        "first_session": _count(
            conn,
            "SELECT COUNT(*) FROM sessions s JOIN users u ON u.id = s.athlete_id "
            "WHERE u.org_id = ? AND s.status = 'counted'",
            (org_id,),
        ),
        "parents": _count(
            conn,
            "SELECT COUNT(*) FROM guardians g JOIN users u ON u.id = g.athlete_id "
            "WHERE u.org_id = ?",
            (org_id,),
        ),
        "recognition": _count(
            conn,
            "SELECT COUNT(*) FROM recognition_templates WHERE org_id = ?",
            (org_id,),
        ),
        "staff": _count(
            conn,
            "SELECT COUNT(*) FROM users WHERE org_id = ? AND role IN ('coach', 'director') "
            "AND active = 1",
            (org_id,),
        ),
    }


def blockers(conn: sqlite3.Connection, org_id: int) -> list[dict[str, Any]]:
    """Things stopping athletes from training right now.

    Kept apart from the steps because they are not setup, they are breakage --
    and they can appear long after onboarding is finished.
    """
    out: list[dict[str, Any]] = []

    # The gate that surprises people. Enforcement starts the moment a parent is
    # linked, so inviting parents can lock athletes out overnight, and the app
    # gives the athlete a clear message while telling the coach nothing.
    waiting = conn.execute(
        "SELECT u.id, u.display_name FROM users u "
        "WHERE u.org_id = ? AND u.role = 'athlete' AND u.active = 1 "
        "AND EXISTS (SELECT 1 FROM guardians g WHERE g.athlete_id = u.id) "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM consents c WHERE c.athlete_id = u.id "
        "  AND c.scope = 'participation' AND c.granted = 1"
        ")",
        (org_id,),
    ).fetchall()
    if waiting:
        names = ", ".join(r["display_name"] for r in waiting[:4])
        more = f" and {len(waiting) - 4} more" if len(waiting) > 4 else ""
        out.append({
            "key": "awaiting_consent",
            "title": (
                f"{len(waiting)} athlete{'s' if len(waiting) != 1 else ''} "
                "waiting on a parent"
            ),
            "detail": (
                f"{names}{more} cannot record anything until their parent "
                "accepts in their own portal. Nothing is broken — this is the "
                "consent gate doing its job, and it switches on the moment a "
                "parent is linked."
            ),
            "athletes": [int(r["id"]) for r in waiting],
        })
    return out


def progress(
    conn: sqlite3.Connection, org_id: int, kind: str = "program"
) -> dict[str, Any]:
    """Where this program actually is, computed rather than remembered."""
    steps = FAMILY_STEPS if kind == "family" else PROGRAM_STEPS
    state = _state(conn, org_id)

    done_map: dict[str, bool] = {
        "team": state["team"] > 0,
        "athletes": state["athletes"] > 0,
        "first_session": state["first_session"] > 0,
        "parents": state["parents"] > 0,
        "recognition": state["recognition"] > 0,
        # More than the one who signed up.
        "staff": state["staff"] > 1,
    }

    rendered = [s.to_dict(done_map.get(s.key, False), state.get(s.key, 0)) for s in steps]
    required = [s for s in rendered if s["required"]]
    complete = all(s["done"] for s in required)
    nxt = next((s for s in rendered if not s["done"]), None)

    return {
        "kind": kind,
        "steps": rendered,
        "next": nxt,
        "complete": complete,
        "required_done": sum(1 for s in required if s["done"]),
        "required_total": len(required),
        "blockers": blockers(conn, org_id),
    }


def athlete_blockers(conn: sqlite3.Connection, athlete_id: int) -> list[dict[str, Any]]:
    """What is stopping this athlete from recording, in their own words.

    The athlete already meets this at the moment they press start. Saying it on
    the home screen instead means they find out before choosing a drill and
    getting refused, which is the difference between "waiting on my mum" and
    "this app is broken".
    """
    linked = conn.execute(
        "SELECT 1 FROM guardians WHERE athlete_id = ? LIMIT 1", (athlete_id,)
    ).fetchone()
    if linked is None:
        return []
    granted = conn.execute(
        "SELECT 1 FROM consents WHERE athlete_id = ? AND scope = 'participation' "
        "AND granted = 1 LIMIT 1",
        (athlete_id,),
    ).fetchone()
    if granted is not None:
        return []
    return [{
        "key": "awaiting_consent",
        "title": "Waiting on a parent",
        "detail": (
            "Recording is paused until a parent or guardian says yes in their "
            "own portal. Nothing is wrong and nothing is lost — give them a "
            "nudge and everything here switches on."
        ),
    }]


def athlete_progress(conn: sqlite3.Connection, athlete_id: int) -> dict[str, Any]:
    """Where a new athlete is, computed the same way a coach's is.

    Deliberately short. A coach setting up a program will read six steps; a
    twelve-year-old who wants to go outside will read one, and the one that
    matters is recording a session.
    """
    org = conn.execute(
        "SELECT org_id FROM users WHERE id = ?", (athlete_id,)
    ).fetchone()
    org_id = int(org["org_id"]) if org else 0

    done = {
        "first_session": _count(
            conn,
            "SELECT COUNT(*) FROM sessions WHERE athlete_id = ? AND status = 'counted'",
            (athlete_id,),
        ) > 0,
        "check_in": _count(
            conn, "SELECT COUNT(*) FROM wellness_checkins WHERE athlete_id = ?",
            (athlete_id,),
        ) > 0,
        "film": _count(
            conn,
            "SELECT COUNT(*) FROM clip_watches WHERE athlete_id = ? AND verdict = 'watched'",
            (athlete_id,),
        ) > 0,
        # Only the browser knows whether it was installed, so the client fills
        # this in. Reported as not done rather than guessed at here.
        "install": False,
    }

    # Not offered where the program has curated nothing: telling a kid to watch
    # a clip that does not exist is a step they cannot take.
    has_film = _count(
        conn, "SELECT COUNT(*) FROM clips WHERE org_id = ? AND active = 1", (org_id,)
    ) > 0
    steps = [s for s in ATHLETE_STEPS if s.key != "film" or has_film]

    rendered = [s.to_dict(done.get(s.key, False)) for s in steps]
    required = [s for s in rendered if s["required"]]
    return {
        "steps": rendered,
        "next": next((s for s in rendered if not s["done"]), None),
        "complete": all(s["done"] for s in required),
        "required_done": sum(1 for s in required if s["done"]),
        "required_total": len(required),
        "promise": PROMISE,
        "blockers": athlete_blockers(conn, athlete_id),
    }


#: What a guardian can always do, stated rather than made into steps. None of
#: it is a task to complete; all of it is worth knowing on day one, because it
#: is the difference between granting a permission and handing something over.
PARENT_RIGHTS = (
    "Withdraw any permission at any time, and it takes effect immediately.",
    "Download everything held about your athlete, in one file.",
    "Delete their training history, or the whole account, permanently.",
    "See every message they are sent. Nobody can reply through the app.",
)


def parent_progress(conn: sqlite3.Connection, guardian_id: int) -> dict[str, Any]:
    """What a guardian still has to decide, per child.

    Short on purpose, and short for a different reason than the athlete's: a
    parent's job here is not to set anything up, it is to make one decision
    that is genuinely theirs to make. Padding that with tasks would dress a
    consent screen up as a product tour.

    Per athlete rather than per account, because a guardian with two children
    can easily have decided for one and not the other -- and the one who is
    waiting is the one who cannot train.
    """
    rows = conn.execute(
        "SELECT u.id, u.display_name FROM guardians g "
        "JOIN users u ON u.id = g.athlete_id "
        "WHERE g.guardian_id = ? AND u.active = 1 ORDER BY u.id",
        (guardian_id,),
    ).fetchall()

    athletes: list[dict[str, Any]] = []
    for row in rows:
        athlete_id = int(row["id"])
        name = row["display_name"] or "your athlete"
        first = name.split()[0]
        answered = guardians.answered_scopes(conn, athlete_id)
        granted = guardians.current_consents(conn, athlete_id)

        decided = guardians.Scope.PARTICIPATION in answered
        athletes.append({
            "athlete_id": athlete_id,
            "display_name": name,
            "steps": [
                {
                    "key": "participation",
                    "title": f"Decide whether {first} can train",
                    "detail": (
                        "Their phone counts reps and the video never leaves it. "
                        "Their coach sees the numbers, not the footage."
                    ),
                    "required": True,
                    "done": decided,
                },
                {
                    "key": "leaderboard_name",
                    "title": f"Choose how {first} appears on team boards",
                    "detail": (
                        "Left alone they show up under an initial and a jersey "
                        "number, still competing. This is only about their name."
                    ),
                    "required": False,
                    "done": guardians.Scope.LEADERBOARD_NAME in answered,
                },
            ],
            # Decided-and-declined is a finished decision, not an unfinished
            # one. What it is not is training: that is the blocker below.
            "decided": decided,
            "blocking": not granted.get(guardians.Scope.PARTICIPATION, False),
        })

    waiting = [a for a in athletes if not a["decided"]]
    return {
        "athletes": athletes,
        "next": waiting[0] if waiting else None,
        "complete": not waiting,
        "required_done": sum(1 for a in athletes if a["decided"]),
        "required_total": len(athletes),
        "blocked": [a["display_name"] for a in athletes if a["blocking"]],
        "promise": PROMISE,
        "rights": list(PARENT_RIGHTS),
    }


def staff_progress(
    conn: sqlite3.Connection, user_id: int, org_id: int
) -> dict[str, Any]:
    """Orientation for a coach who joined a program somebody else built.

    Deliberately not the setup checklist. The teams, the athletes and the
    roster already exist; being handed "create your first team" would be
    telling them to redo work that is already done.

    There are also no required steps, and that is honest rather than an
    oversight: everything that has to happen for an assistant coach to start
    is done *by somebody else*. What they need is to know what they can see,
    what happens in their name, and what is waiting for them.
    """
    teams = conn.execute(
        "SELECT t.id, t.name FROM team_staff ts JOIN teams t ON t.id = ts.team_id "
        "WHERE ts.user_id = ? ORDER BY t.name",
        (user_id,),
    ).fetchall()
    team_ids = [int(t["id"]) for t in teams]

    athletes = 0
    review = 0
    assignments = 0
    if not team_ids and not CONFIG.strict_team_scope:
        # Unassigned and unrestricted: the honest count is the whole program,
        # because that is genuinely what they are looking at.
        athletes = _count(
            conn,
            "SELECT COUNT(*) FROM users WHERE org_id = ? AND role = 'athlete' "
            "AND active = 1",
            (org_id,),
        )
        review = _count(
            conn,
            "SELECT COUNT(*) FROM sessions s JOIN users u ON u.id = s.athlete_id "
            "WHERE u.org_id = ? AND s.status = 'review'",
            (org_id,),
        )
    if team_ids:
        marks = ",".join("?" for _ in team_ids)
        athletes = _count(
            conn,
            f"SELECT COUNT(DISTINCT tm.user_id) FROM team_members tm "
            f"WHERE tm.team_id IN ({marks})",
            tuple(team_ids),
        )
        review = _count(
            conn,
            f"SELECT COUNT(*) FROM sessions s "
            f"JOIN team_members tm ON tm.user_id = s.athlete_id "
            f"WHERE tm.team_id IN ({marks}) AND s.status = 'review'",
            tuple(team_ids),
        )
        assignments = _count(
            conn,
            f"SELECT COUNT(*) FROM assignments WHERE team_id IN ({marks})",
            tuple(team_ids),
        )

    done = {
        "recognition": _count(
            conn,
            "SELECT COUNT(*) FROM recognition_templates WHERE org_id = ? "
            "AND updated_by = ?",
            (org_id, user_id),
        ) > 0,
        "assignment": assignments > 0,
        "review": review == 0,
    }

    # Not offered when there is nothing in it. "Clear the review queue" with an
    # empty queue is a tick for having done nothing, which teaches an athlete's
    # coach that the list is decorative.
    steps = [s for s in JOINING_STEPS if s.key != "review" or review > 0]
    rendered = [s.to_dict(done.get(s.key, False)) for s in steps]

    blocking: list[dict[str, Any]] = []
    if not team_ids:
        # What an unassigned coach actually sees depends on how the program is
        # configured, and the two cases are opposites -- so the message has to
        # branch rather than guess. Saying "your dashboard is empty" to someone
        # looking at four hundred children would be worse than saying nothing.
        if CONFIG.strict_team_scope:
            blocking.append({
                "key": "not_assigned",
                "title": "You are not on a team yet",
                "detail": (
                    "A director has to assign you before any athletes appear. "
                    "Nothing is broken and there is nothing for you to fix — "
                    "this dashboard is empty because it is scoped to your "
                    "teams, not because the program is."
                ),
            })
        else:
            blocking.append({
                "key": "unscoped",
                "title": "You can currently see the whole program",
                "detail": (
                    "You are not assigned to a team, so this shows every "
                    "athlete rather than yours. Ask a director to assign you "
                    "and it narrows to the ones you actually coach — which is "
                    "how it should sit at a club with hundreds of children."
                ),
            })

    return {
        "kind": "joining",
        "steps": rendered,
        "next": next((s for s in rendered if not s["done"]), None),
        # No required steps, so a coach is never told they are unfinished for
        # something only a director can do.
        "complete": True,
        "required_done": 0,
        "required_total": 0,
        "blockers": blocking,
        "scope": {
            "teams": [{"id": int(t["id"]), "name": t["name"]} for t in teams],
            "athletes": athletes,
            "review_waiting": review,
        },
        "facts": [
            (
                f"You see {athletes} athlete{'s' if athletes != 1 else ''} across "
                f"{len(teams)} team{'s' if len(teams) != 1 else ''} — the ones you "
                "are assigned to, and nobody else's."
            ) if teams else (
                f"You can see {athletes} athlete"
                f"{'s' if athletes != 1 else ''} — everyone in the program, "
                "because you are not assigned to a team."
            ),
            "Counts, form scores and load. Never their video: that stays on their phone.",
            (
                "Milestone messages to your athletes go out signed with your "
                "name, automatically, on the day they earn one."
            ),
        ],
    }
