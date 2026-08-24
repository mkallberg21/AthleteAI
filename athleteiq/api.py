"""HTTP API for AthleteIQ.

Nothing here accepts video, image data, or pose landmarks. The capture app
sends counts and timings only; there is no endpoint that could receive footage
even if a future client tried to send it.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import CONFIG
from . import assignments as assignments_mod
from . import billing as billing_mod
from . import digest as digest_mod
from . import guardians as guardians_mod
from . import roster as roster_mod
from . import notifications as notify
from .assignments import AssignmentError
from .billing import BillingError
from .guardians import GuardianError
from .roster import RosterError
from .drills import ALL_DRILLS, DRILLS_BY_KEY
from .leaderboard import attach_load, coach_roster, leaderboard, team_standings
from .store import Principal, Store, StoreError

app = FastAPI(
    title="AthleteIQ",
    version=__version__,
    description=(
        "On-device training analysis for youth athletes. Video never leaves the "
        "athlete's phone; this API handles derived counts, scoring, and coach "
        "reporting only."
    ),
)

_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def _principal(
    authorization: str | None = Header(default=None),
    x_org_id: int | None = Header(default=None, alias="X-Org-Id"),
    store: Store = Depends(get_store),
) -> Principal:
    """Resolve the caller, in one program.

    The active program comes from an X-Org-Id header, defaulting to their home
    org. Someone with roles in two clubs is one account, not two logins.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        return store.authenticate(token, org_id=x_org_id)
    except StoreError as exc:
        # A token that is valid but not for that program is a 403, not a 401 --
        # re-authenticating would not help.
        status = 403 if "access to that program" in str(exc) else 401
        raise HTTPException(status_code=status, detail=str(exc)) from exc


def _staff(principal: Principal = Depends(_principal)) -> Principal:
    if not principal.is_staff:
        raise HTTPException(status_code=403, detail="coach or director role required")
    return principal


@app.exception_handler(StoreError)
async def _store_error_handler(_request, exc: StoreError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(AssignmentError)
async def _assignment_error_handler(_request, exc: AssignmentError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(GuardianError)
async def _guardian_error_handler(_request, exc: GuardianError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(RosterError)
async def _roster_error_handler(_request, exc: RosterError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(BillingError)
async def _billing_error_handler(_request, exc: BillingError) -> JSONResponse:
    # 402: this is a plan limit, not a malformed request or a missing right.
    return JSONResponse(status_code=402, content={"detail": str(exc)})


def _guardian(principal: Principal = Depends(_principal)) -> Principal:
    if principal.role != "guardian":
        raise HTTPException(status_code=403, detail="guardian account required")
    return principal


def _athlete(principal: Principal = Depends(_principal)) -> Principal:
    """Endpoints that record or report an athlete's own training.

    Guardians and coaches are authenticated users, but they are not athletes:
    without this a parent account could log sessions, earn XP, and appear on a
    leaderboard alongside the children.
    """
    if principal.role != "athlete":
        raise HTTPException(status_code=403, detail="athlete account required")
    return principal


def _competitor(principal: Principal = Depends(_principal)) -> Principal:
    """Who may see a leaderboard.

    Athletes and their coaches, not guardians. A ranked list of other people's
    children, for adults to scroll, is the mechanism behind the worst behaviour
    in youth sports -- so the parent portal has no leaderboard, and neither does
    the API for a parent's token.
    """
    if principal.role == "guardian":
        raise HTTPException(
            status_code=403,
            detail="Leaderboards are for athletes and coaches. Your portal shows "
                   "your own athlete's progress.",
        )
    return principal


# ----------------------------------------------------------------------
# Public / reference
# ----------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "version": __version__, "drills": len(ALL_DRILLS)}


@app.get("/api/drills")
def list_drills() -> dict[str, Any]:
    """The full drill catalog, including the counting spec the client runs."""
    return {"drills": [d.to_dict() for d in ALL_DRILLS]}


@app.get("/api/drills/{drill_key}")
def get_drill_spec(drill_key: str) -> dict[str, Any]:
    if drill_key not in DRILLS_BY_KEY:
        raise HTTPException(status_code=404, detail=f"unknown drill: {drill_key}")
    return DRILLS_BY_KEY[drill_key].to_dict()


# ----------------------------------------------------------------------
# Onboarding
# ----------------------------------------------------------------------

class CreateOrgRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sport: str = "lacrosse"
    director_name: str = Field(min_length=1, max_length=120)


@app.post("/api/orgs", status_code=201)
def create_org(body: CreateOrgRequest, store: Store = Depends(get_store)) -> dict[str, Any]:
    """Bootstrap a program and its first director account.

    Open by design so a program can self-serve. In a real deployment this sits
    behind whatever signup/billing gate the business needs.
    """
    org_id = store.create_org(body.name, body.sport)
    director = store.create_user(org_id, "director", body.director_name)
    return {"org_id": org_id, "director": director}


class CreateTeamRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    season: str = ""


@app.post("/api/teams", status_code=201)
def create_team(
    body: CreateTeamRequest,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return store.create_team(principal.org_id, body.name, body.season)


class CreateAthleteRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    dominant_hand: Literal["left", "right"] | None = None
    guardian_consent: bool = False
    join_code: str | None = None
    jersey: str = ""
    position: str = ""


@app.post("/api/athletes", status_code=201)
def create_athlete(
    body: CreateAthleteRequest,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Create an athlete and return their one-time login token.

    Coach-mediated on purpose: for minors, an adult in the program is the one
    who creates the account, and the token is handed over in person.
    """
    athlete = store.create_user(
        principal.org_id,
        "athlete",
        body.display_name,
        birth_year=body.birth_year,
        dominant_hand=body.dominant_hand,
        guardian_consent=body.guardian_consent,
    )
    if body.join_code:
        store.join_team(body.join_code, athlete["id"], body.jersey, body.position)
    return athlete


class JoinTeamRequest(BaseModel):
    join_code: str = Field(min_length=4, max_length=12)
    jersey: str = ""
    position: str = ""


@app.post("/api/teams/join")
def join_team(
    body: JoinTeamRequest,
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    team_id = store.join_team(body.join_code, principal.id, body.jersey, body.position)
    return {"team_id": team_id, "joined": True}


# ----------------------------------------------------------------------
# Sessions -- the athlete capture flow
# ----------------------------------------------------------------------

class StartSessionRequest(BaseModel):
    drill_key: str


@app.post("/api/sessions/start", status_code=201)
def start_session(
    body: StartSessionRequest,
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return store.start_session(principal.id, body.drill_key)


class RepPayload(BaseModel):
    t_ms: int = Field(ge=0)
    hand: Literal["left", "right", "none"] = "none"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    # Shape of the rep, used for form scoring. Optional so older clients keep
    # working -- they simply get no form score rather than an error.
    # Bounded because these are client-supplied and feed a public leaderboard.
    peak: float | None = Field(default=None, ge=-1000.0, le=1000.0)
    rom: float | None = Field(default=None, ge=0.0, le=1000.0)
    cycle_ms: int | None = Field(default=None, ge=0, le=600_000)


class SubmitSessionRequest(BaseModel):
    session_id: int
    nonce: str
    duration_ms: int = Field(ge=0)
    # Capped so a malformed or hostile client cannot exhaust memory. The cap is
    # far above any real session: 20k reps is hours of continuous work.
    reps: list[RepPayload] = Field(default_factory=list, max_length=20_000)
    hold_ms: int = Field(default=0, ge=0)
    mean_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    client_version: str = ""
    device_label: str = ""
    # The device's own completion time, so a session recorded offline is
    # credited to the day it was actually trained rather than the day it synced.
    completed_at: str | None = None


@app.post("/api/sessions/submit")
def submit_session(
    body: SubmitSessionRequest,
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Submit a finished session. Counts only -- no imagery is accepted."""
    try:
        return store.submit_session(
            principal.id,
            body.session_id,
            body.nonce,
            duration_ms=body.duration_ms,
            reps=[r.model_dump() for r in body.reps],
            hold_ms=body.hold_ms,
            mean_confidence=body.mean_confidence,
            client_version=body.client_version,
            device_label=body.device_label,
            completed_at=body.completed_at,
        )
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/me")
def me(
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if principal.role == "athlete":
        return {"role": principal.role, **store.athlete_profile(principal.id)}
    return {
        "role": principal.role,
        "athlete_id": principal.id,
        "display_name": principal.display_name,
        "org_id": principal.org_id,
    }


@app.get("/api/athletes/{athlete_id}")
def athlete_profile(
    athlete_id: int,
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if principal.id != athlete_id:
        if not principal.is_staff or not store.staff_can_see_athlete(principal, athlete_id):
            raise HTTPException(status_code=403, detail="not permitted")
    return store.athlete_profile(athlete_id)


class ReserveRequest(BaseModel):
    drill_key: str
    count: int = Field(default=3, ge=1, le=10)


@app.post("/api/sessions/reserve", status_code=201)
def reserve_sessions(
    body: ReserveRequest,
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Hand out session slots the athlete can spend with no connection."""
    return {"slots": store.reserve_sessions(principal.id, body.drill_key, body.count)}


# ----------------------------------------------------------------------
# Assignments
# ----------------------------------------------------------------------

class CreateAssignmentRequest(BaseModel):
    team_id: int
    drill_key: str
    title: str = Field(min_length=1, max_length=120)
    starts_on: str
    due_on: str
    target_reps: int = Field(default=0, ge=0, le=100_000)
    target_sessions: int = Field(default=0, ge=0, le=200)
    min_offhand: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: str = Field(default="", max_length=500)
    # Empty means the whole team, which is the common case.
    athlete_ids: list[int] = Field(default_factory=list, max_length=200)


@app.post("/api/coach/assignments", status_code=201)
def create_assignment(
    body: CreateAssignmentRequest,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if not principal.can_see_team(body.team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")
    assignment_id = assignments_mod.create(
        store.conn,
        org_id=principal.org_id,
        team_id=body.team_id,
        created_by=principal.id,
        drill_key=body.drill_key,
        title=body.title,
        starts_on=body.starts_on,
        due_on=body.due_on,
        target_reps=body.target_reps,
        target_sessions=body.target_sessions,
        min_offhand=body.min_offhand,
        notes=body.notes,
        athlete_ids=body.athlete_ids,
    )
    # Announce it immediately -- an assignment nobody is told about is just a
    # row in a table.
    notified = notify.notify_new_assignment(store.conn, assignment_id)
    return {"assignment_id": assignment_id, "athletes_notified": notified}


@app.get("/api/coach/assignments")
def list_assignments(
    team_id: int | None = None,
    include_inactive: bool = False,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Assignments with per-athlete compliance, worst first."""
    if team_id is not None and not principal.can_see_team(team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")
    items = [
        a for a in assignments_mod.list_for_org(
            store.conn, principal.org_id, team_id=team_id, include_inactive=include_inactive
        )
        if principal.can_see_team(a.team_id)
    ]
    out = []
    for assignment in items:
        rows = [p.to_dict() for p in assignments_mod.compliance(store.conn, assignment)]
        done = sum(1 for r in rows if r["complete"])
        out.append(
            {
                **assignment.to_dict(),
                "days_remaining": assignment.days_remaining(),
                "athletes": rows,
                "completed_count": done,
                "athlete_count": len(rows),
            }
        )
    return {"assignments": out}


@app.delete("/api/coach/assignments/{assignment_id}")
def deactivate_assignment(
    assignment_id: int,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    assignment = assignments_mod.get(store.conn, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=404, detail="unknown assignment")
    owner = store.conn.execute(
        "SELECT org_id FROM assignments WHERE id = ?", (assignment_id,)
    ).fetchone()
    if owner["org_id"] != principal.org_id:
        raise HTTPException(status_code=403, detail="assignment belongs to another program")
    assignments_mod.deactivate(store.conn, assignment_id)
    return {"assignment_id": assignment_id, "active": False}


@app.get("/api/assignments")
def my_assignments(
    include_closed: bool = False,
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """The athlete's own assignments with live progress."""
    return {
        "assignments": assignments_mod.for_athlete(
            store.conn, principal.id, only_open=not include_closed
        )
    }


# ----------------------------------------------------------------------
# Notifications
# ----------------------------------------------------------------------

@app.get("/api/notifications")
def get_notifications(
    limit: int = Query(default=30, ge=1, le=100),
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return {
        "unread": notify.unread_count(store.conn, principal.id),
        "notifications": notify.feed(store.conn, principal.id, limit),
    }


class MarkReadRequest(BaseModel):
    notification_id: int | None = None


@app.post("/api/notifications/read")
def read_notifications(
    body: MarkReadRequest,
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Mark one notification read, or all when no id is given."""
    return {"marked": notify.mark_read(store.conn, principal.id, body.notification_id)}


class PushSubscribeRequest(BaseModel):
    endpoint: str = Field(min_length=1, max_length=1000)
    p256dh: str = Field(min_length=1, max_length=400)
    auth: str = Field(min_length=1, max_length=400)


@app.post("/api/notifications/subscribe", status_code=201)
def subscribe_push(
    body: PushSubscribeRequest,
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    notify.save_subscription(
        store.conn, principal.id, body.endpoint, body.p256dh, body.auth
    )
    return {"subscribed": True}


@app.get("/api/notifications/vapid-key")
def vapid_key() -> dict[str, Any]:
    """The public key a browser needs to subscribe.

    Empty when push is not configured -- the client then falls back to the
    in-app feed, which needs no third-party service.
    """
    return {"public_key": CONFIG.vapid_public_key}


class BroadcastRequest(BaseModel):
    team_id: int
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=500)


@app.post("/api/coach/broadcast")
def coach_broadcast(
    body: BroadcastRequest,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    team = store.conn.execute(
        "SELECT org_id FROM teams WHERE id = ?", (body.team_id,)
    ).fetchone()
    if team is None:
        raise HTTPException(status_code=404, detail="unknown team")
    if team["org_id"] != principal.org_id:
        raise HTTPException(status_code=403, detail="team belongs to another program")
    if not principal.can_see_team(body.team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")
    sent = notify.broadcast(store.conn, body.team_id, body.title, body.body, principal.id)
    return {"sent": sent}


# ----------------------------------------------------------------------
# Leaderboards
# ----------------------------------------------------------------------

@app.get("/api/leaderboard")
def get_leaderboard(
    board: Literal["xp", "offhand", "streak", "reps", "improvement", "quality"] = "xp",
    window: Literal["week", "month", "season", "all"] = "week",
    team_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(_competitor),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    rows = leaderboard(
        store.conn,
        principal.org_id,
        board=board,
        window=window,
        team_id=team_id,
        limit=limit,
    )
    return {"board": board, "window": window, "team_id": team_id, "rows": rows}


@app.get("/api/sessions/{session_id}/quality")
def session_quality(
    session_id: int,
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """The full form breakdown for one session."""
    import json as _json

    row = store.conn.execute(
        "SELECT athlete_id, drill_key, quality_score, quality_json FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown session")
    if row["athlete_id"] != principal.id and not principal.is_staff:
        raise HTTPException(status_code=403, detail="not permitted")

    try:
        report = _json.loads(row["quality_json"]) if row["quality_json"] else None
    except (ValueError, TypeError):
        report = None
    return {"session_id": session_id, "drill_key": row["drill_key"], "quality": report}


@app.post("/api/recovery", status_code=201)
def log_recovery(
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Log today as a deliberate rest day.

    Counts toward the streak, so an athlete carrying high load is not forced to
    choose between resting and losing six weeks of consistency.
    """
    try:
        return store.log_recovery_day(principal.id)
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/load")
def my_load(
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return store.load_state(principal.id).to_dict()


@app.get("/api/coach/load")
def team_load(
    team_id: int | None = None,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Workload across the roster, athletes needing attention first."""
    rows = store.conn.execute(
        "SELECT u.id, u.display_name FROM users u "
        + ("JOIN team_members tm ON tm.user_id = u.id AND tm.team_id = ? " if team_id else "")
        + "WHERE u.org_id = ? AND u.role = 'athlete' AND u.active = 1",
        ([team_id, principal.org_id] if team_id else [principal.org_id]),
    ).fetchall()

    out = []
    for row in rows:
        state = store.load_state(row["id"])
        out.append({
            "athlete_id": row["id"],
            "display_name": row["display_name"],
            **state.to_dict(),
        })

    severity = {"warning": 0, "caution": 1, "info": 2, None: 3}
    out.sort(key=lambda a: (
        severity.get(
            next((x["level"] for x in a["advisories"] if x["level"] == "warning"), None)
            or next((x["level"] for x in a["advisories"] if x["level"] == "caution"), None),
            3,
        ),
        -(a["acwr"] or 0),
    ))
    return {"athletes": out}


# ----------------------------------------------------------------------
# Programs, roles, and billing
# ----------------------------------------------------------------------

@app.get("/api/orgs/mine")
def my_orgs(
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Every program this person holds a role in, and which one is active.

    Pass the chosen org back as an X-Org-Id header on later requests.
    """
    return {
        "active_org_id": principal.org_id,
        "role": principal.role,
        "team_scoped": principal.team_scoped,
        "memberships": [
            {"org_id": m.org_id, "org_name": m.org_name, "role": m.role}
            for m in principal.memberships
        ],
    }


class StaffAssignment(BaseModel):
    user_id: int
    team_id: int


@app.post("/api/coach/staff/assign")
def assign_staff(
    body: StaffAssignment,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Put a coach on a team. Directors only -- this grants access to children."""
    if not principal.is_director:
        raise HTTPException(
            status_code=403, detail="only a director can change team assignments"
        )
    team = store.conn.execute(
        "SELECT org_id FROM teams WHERE id = ?", (body.team_id,)
    ).fetchone()
    if team is None or team["org_id"] != principal.org_id:
        raise HTTPException(status_code=404, detail="unknown team")
    member = store.conn.execute(
        "SELECT 1 FROM memberships WHERE user_id = ? AND org_id = ?",
        (body.user_id, principal.org_id),
    ).fetchone()
    if member is None:
        raise HTTPException(status_code=404, detail="that person is not in this program")

    store.assign_staff_to_team(body.user_id, body.team_id)
    return {"assigned": True, "user_id": body.user_id, "team_id": body.team_id}


@app.post("/api/coach/staff/unassign")
def unassign_staff(
    body: StaffAssignment,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if not principal.is_director:
        raise HTTPException(
            status_code=403, detail="only a director can change team assignments"
        )
    store.unassign_staff_from_team(body.user_id, body.team_id)
    return {"assigned": False, "user_id": body.user_id, "team_id": body.team_id}


@app.get("/api/coach/staff")
def list_staff(
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    rows = store.conn.execute(
        "SELECT u.id, u.display_name, m.role, u.email FROM memberships m "
        "JOIN users u ON u.id = m.user_id "
        "WHERE m.org_id = ? AND m.role IN ('coach','director') AND m.active = 1 "
        "ORDER BY m.role, u.display_name",
        (principal.org_id,),
    ).fetchall()

    out = []
    for row in rows:
        teams = [
            dict(t) for t in store.conn.execute(
                "SELECT t.id, t.name FROM team_staff ts JOIN teams t ON t.id = ts.team_id "
                "WHERE ts.user_id = ? AND t.org_id = ?",
                (row["id"], principal.org_id),
            )
        ]
        out.append({**dict(row), "teams": teams, "sees_whole_program": not teams})
    return {"staff": out}


@app.get("/api/billing")
def get_billing(
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    subscription = billing_mod.get_subscription(store.conn, principal.org_id)
    return {
        **subscription.to_dict(),
        "plans": [p.to_dict() for p in billing_mod.PLANS],
        "recommended": billing_mod.recommend(store.conn, principal.org_id),
        "history": billing_mod.history(store.conn, principal.org_id, 20),
    }


@app.get("/api/billing/quote")
def billing_quote(
    plan: str,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """What a plan would cost this program at its current size."""
    return billing_mod.quote(store.conn, principal.org_id, plan)


class ChangePlanRequest(BaseModel):
    plan_code: str = Field(max_length=40)
    seats: int = Field(default=0, ge=0, le=100_000)


@app.post("/api/billing/plan")
def change_plan(
    body: ChangePlanRequest,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if not principal.is_director:
        raise HTTPException(
            status_code=403, detail="only a director can change the plan"
        )
    subscription = billing_mod.start_subscription(
        store.conn, principal.org_id, body.plan_code,
        trial=False, seats=body.seats, actor=principal.display_name,
    )
    return subscription.to_dict()


# ----------------------------------------------------------------------
# Weekly digest
# ----------------------------------------------------------------------

@app.get("/api/coach/digest")
def get_digest(
    team_id: int | None = None,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Last week's team numbers, as data."""
    report = digest_mod.compute(store.conn, principal.org_id, team_id=team_id)
    return {"subject": digest_mod.subject_line(report), **report.to_dict()}


@app.get("/api/coach/digest/preview", response_class=HTMLResponse)
def preview_digest(
    team_id: int | None = None,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> str:
    """The digest exactly as it will arrive by email.

    A coach who wants to forward it, print it, or paste it into a team channel
    can do so from here without waiting for Monday.
    """
    report = digest_mod.compute(store.conn, principal.org_id, team_id=team_id)
    dashboard = (
        f"{CONFIG.app_base_url.rstrip('/')}/app/coach.html"
        if CONFIG.app_base_url else ""
    )
    return digest_mod.render_html(report, dashboard)


class SendDigestRequest(BaseModel):
    team_id: int | None = None
    # Defaults to the requesting coach, so the common case is "send me a copy".
    to: str | None = Field(default=None, max_length=200)


@app.post("/api/coach/digest/send")
def send_digest(
    body: SendDigestRequest,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    report = digest_mod.compute(store.conn, principal.org_id, team_id=body.team_id)
    recipient = body.to or store.conn.execute(
        "SELECT email FROM users WHERE id = ?", (principal.id,)
    ).fetchone()["email"]

    if not recipient:
        raise HTTPException(
            status_code=400,
            detail="No email address on file. Add one, or pass an address to send to.",
        )

    dashboard = (
        f"{CONFIG.app_base_url.rstrip('/')}/app/coach.html"
        if CONFIG.app_base_url else ""
    )
    delivered = notify.send_email(
        recipient,
        digest_mod.subject_line(report),
        digest_mod.render_html(report, dashboard),
        digest_mod.render_text(report, dashboard),
    )
    return {
        "to": recipient,
        "delivered": delivered,
        "subject": digest_mod.subject_line(report),
        "note": None if delivered else (
            "Email is not configured on this server, so nothing was sent. The "
            "digest is still viewable and printable from the preview."
        ),
    }


# ----------------------------------------------------------------------
# Roster import
# ----------------------------------------------------------------------

# The file arrives as text inside a JSON body rather than as a multipart
# upload. That keeps the invariant that every request body on this API is
# application/json, which is what makes "no endpoint accepts a file" checkable
# rather than merely stated.
class RosterFile(BaseModel):
    content: str = Field(min_length=1, max_length=2_000_000)


@app.post("/api/coach/roster/preview")
def preview_roster(
    body: RosterFile,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Parse a roster file and say exactly what importing it would do.

    Nothing is written. Applying is a separate, explicit call.
    """
    plan = store.resolve_import(principal.org_id, roster_mod.parse(body.content))
    return plan.to_dict()


class RosterImport(BaseModel):
    content: str = Field(min_length=1, max_length=2_000_000)
    team_id: int
    invite_guardians: bool = True


@app.post("/api/coach/roster/import", status_code=201)
def import_roster(
    body: RosterImport,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Create and update athletes from a roster file.

    Re-parsed here rather than trusting a plan echoed back by the client: a
    plan is a preview, not an instruction, and accepting one would let a
    modified payload create athletes the file never contained.
    """
    if not principal.can_see_team(body.team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")
    plan = store.resolve_import(principal.org_id, roster_mod.parse(body.content))
    result = store.apply_import(
        principal.org_id, body.team_id, plan, principal.id,
        issue_guardian_invites=body.invite_guardians,
    )
    return {"summary": plan.to_dict()["summary"], **result}


@app.get("/api/coach/roster/template")
def roster_template() -> dict[str, Any]:
    """A sample file, for a coach who has no export to start from."""
    return {
        "filename": "athleteiq-roster-template.csv",
        "content": (
            "First Name,Last Name,#,Position,Birth Year,Shoots,Parent Email\n"
            "Jordan,Pierce,14,Midfield,2011,Right,parent1@example.com\n"
            "Sam,Rivera,7,Attack,2010,Left,parent2@example.com\n"
        ),
        "notes": [
            "Column names are matched loosely -- Jersey #, No., and Number all work.",
            "Only a name column is required. Everything else is optional.",
            "Grade or Class Of works instead of Birth Year, but ages from those "
            "are estimates and the athlete is treated as a minor.",
            "A parent email issues a guardian invite automatically.",
        ],
    }


class ClaimRequest(BaseModel):
    code: str = Field(min_length=4, max_length=40)


@app.post("/api/claim")
def claim_account(body: ClaimRequest, store: Store = Depends(get_store)) -> dict[str, Any]:
    """Exchange a printed claim code for a login token. Unauthenticated by design."""
    try:
        return store.claim_account(body.code)
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ----------------------------------------------------------------------
# Guardians
# ----------------------------------------------------------------------

class InviteRequest(BaseModel):
    athlete_id: int
    email: str | None = Field(default=None, max_length=200)


@app.post("/api/coach/guardian-invites", status_code=201)
def create_guardian_invite(
    body: InviteRequest,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Issue an invite code for a guardian. Shown once, stored hashed."""
    owner = store.conn.execute(
        "SELECT org_id FROM users WHERE id = ?", (body.athlete_id,)
    ).fetchone()
    if owner is None:
        raise HTTPException(status_code=404, detail="unknown athlete")
    if owner["org_id"] != principal.org_id:
        raise HTTPException(status_code=403, detail="athlete belongs to another program")
    if not store.staff_can_see_athlete(principal, body.athlete_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that athlete's team")
    return guardians_mod.create_invite(
        store.conn, body.athlete_id, principal.id, body.email
    )


@app.get("/api/coach/guardian-invites")
def list_guardian_invites(
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    rows = store.conn.execute(
        "SELECT i.id, i.athlete_id, u.display_name, i.email, i.created_at, "
        "       i.expires_at, i.redeemed_at, i.revoked_at "
        "FROM guardian_invites i JOIN users u ON u.id = i.athlete_id "
        "WHERE u.org_id = ? ORDER BY i.created_at DESC LIMIT 100",
        (principal.org_id,),
    ).fetchall()
    return {"invites": [dict(r) for r in rows]}


@app.delete("/api/coach/guardian-invites/{invite_id}")
def revoke_guardian_invite(
    invite_id: int,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    owner = store.conn.execute(
        "SELECT u.org_id FROM guardian_invites i JOIN users u ON u.id = i.athlete_id "
        "WHERE i.id = ?",
        (invite_id,),
    ).fetchone()
    if owner is None:
        raise HTTPException(status_code=404, detail="unknown invite")
    if owner["org_id"] != principal.org_id:
        raise HTTPException(status_code=403, detail="invite belongs to another program")
    guardians_mod.revoke_invite(store.conn, invite_id)
    return {"invite_id": invite_id, "revoked": True}


class RedeemRequest(BaseModel):
    code: str = Field(min_length=4, max_length=40)
    display_name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=200)
    relationship: str = Field(default="parent", max_length=40)


@app.post("/api/guardians/redeem", status_code=201)
def redeem_guardian_invite(
    body: RedeemRequest, store: Store = Depends(get_store)
) -> dict[str, Any]:
    """Create a guardian account from an invite code. Unauthenticated by design."""
    return guardians_mod.redeem_invite(
        store.conn, body.code, body.display_name, body.email, body.relationship
    )


class LinkRequest(BaseModel):
    code: str = Field(min_length=4, max_length=40)
    relationship: str = Field(default="parent", max_length=40)


@app.post("/api/guardians/link")
def link_another_athlete(
    body: LinkRequest,
    principal: Principal = Depends(_guardian),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Attach a second child to an existing guardian account."""
    athlete_id = guardians_mod.link_existing(
        store.conn, body.code, principal.id, body.relationship
    )
    return {"athlete_id": athlete_id, "linked": True}


@app.get("/api/guardians/me")
def guardian_home(
    principal: Principal = Depends(_guardian),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return {
        "display_name": principal.display_name,
        **store.guardian_summary(principal.id),
    }


class ConsentRequest(BaseModel):
    athlete_id: int
    scope: str = Field(max_length=60)
    granted: bool


@app.post("/api/guardians/consent")
def set_consent(
    body: ConsentRequest,
    principal: Principal = Depends(_guardian),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    guardians_mod.require_guardianship(store.conn, principal.id, body.athlete_id)
    result = guardians_mod.set_consent(
        store.conn, body.athlete_id, principal.id, body.scope, body.granted
    )
    purged = 0
    if body.scope == guardians_mod.Scope.DATA_RETENTION and not body.granted:
        # Applied now, not at the next scheduled prune.
        purged = store.purge_rep_detail(body.athlete_id)
    return {**result, "rep_rows_removed": purged}


@app.get("/api/guardians/export/{athlete_id}")
def export_athlete_data(
    athlete_id: int,
    principal: Principal = Depends(_guardian),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Everything held about one athlete."""
    guardians_mod.require_guardianship(store.conn, principal.id, athlete_id)
    return guardians_mod.export_athlete(store.conn, athlete_id)


class EraseRequest(BaseModel):
    athlete_id: int
    scope: Literal["training_data", "all"] = "training_data"
    # Typed to guard against a misrouted click deleting a child's history.
    confirm: str = Field(max_length=40)


@app.post("/api/guardians/erase")
def erase_athlete_data(
    body: EraseRequest,
    principal: Principal = Depends(_guardian),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    guardians_mod.require_guardianship(store.conn, principal.id, body.athlete_id)
    if body.confirm.strip().upper() != "DELETE":
        raise HTTPException(
            status_code=400, detail="type DELETE to confirm this cannot be undone"
        )
    return guardians_mod.erase_athlete(
        store.conn, body.athlete_id, body.scope, requested_by="guardian"
    )


@app.get("/api/standings")
def get_standings(
    window: Literal["week", "month", "season", "all"] = "week",
    principal: Principal = Depends(_competitor),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return {"window": window, "teams": team_standings(store.conn, principal.org_id, window)}


# ----------------------------------------------------------------------
# Coach dashboard
# ----------------------------------------------------------------------

@app.get("/api/coach/roster")
def get_roster(
    team_id: int | None = None,
    window: Literal["week", "month", "season", "all"] = "week",
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if team_id is not None and not principal.can_see_team(team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")
    athletes = coach_roster(
        store.conn, principal.org_id, team_id, window, scope=principal.scope_filter()
    )
    states = {a["athlete_id"]: store.load_state(a["athlete_id"]).to_dict() for a in athletes}
    return {
        "window": window,
        "team_id": team_id,
        "athletes": attach_load(athletes, states),
    }


@app.get("/api/coach/teams")
def get_teams(
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    rows = store.conn.execute(
        "SELECT t.id, t.name, t.season, t.join_code, "
        "  (SELECT COUNT(*) FROM team_members tm WHERE tm.team_id = t.id) AS roster "
        "FROM teams t WHERE t.org_id = ? ORDER BY t.name",
        (principal.org_id,),
    ).fetchall()
    return {
        "teams": [dict(r) for r in rows if principal.can_see_team(r["id"])],
        "team_scoped": principal.team_scoped,
    }


@app.get("/api/coach/review-queue")
def review_queue(
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Sessions held for a human decision, with the reason attached."""
    import json as _json

    rows = store.conn.execute(
        "SELECT s.id, s.drill_key, s.submitted_at, s.duration_ms, s.reps_total, "
        "       s.integrity_score, s.integrity_notes, s.mean_confidence, "
        "       u.display_name, u.id AS athlete_id "
        "FROM sessions s JOIN users u ON u.id = s.athlete_id "
        "WHERE s.status = 'review' AND u.org_id = ? "
        "ORDER BY s.submitted_at DESC LIMIT 100",
        (principal.org_id,),
    ).fetchall()

    out = []
    for r in rows:
        item = dict(r)
        try:
            item["integrity_notes"] = _json.loads(r["integrity_notes"])
        except (ValueError, TypeError):
            item["integrity_notes"] = [r["integrity_notes"]] if r["integrity_notes"] else []
        item["drill_name"] = (
            DRILLS_BY_KEY[r["drill_key"]].name if r["drill_key"] in DRILLS_BY_KEY else r["drill_key"]
        )
        out.append(item)
    return {"sessions": out}


class ReviewDecision(BaseModel):
    approve: bool


@app.post("/api/coach/review/{session_id}")
def decide_review(
    session_id: int,
    body: ReviewDecision,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    owner = store.conn.execute(
        "SELECT u.org_id FROM sessions s JOIN users u ON u.id = s.athlete_id WHERE s.id = ?",
        (session_id,),
    ).fetchone()
    if owner is None:
        raise HTTPException(status_code=404, detail="unknown session")
    if owner["org_id"] != principal.org_id:
        raise HTTPException(status_code=403, detail="session belongs to another program")
    try:
        return store.review_session(session_id, body.approve, principal.id)
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ----------------------------------------------------------------------
# Static app
# ----------------------------------------------------------------------

if CONFIG.static_dir.is_dir():
    app.mount("/app", StaticFiles(directory=CONFIG.static_dir, html=True), name="app")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(CONFIG.static_dir / "index.html")
