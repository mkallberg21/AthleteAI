"""HTTP API for AthleteIQ.

Nothing here accepts video, image data, or pose landmarks. The capture app
sends counts and timings only; there is no endpoint that could receive footage
even if a future client tried to send it.
"""

from __future__ import annotations

import base64

from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import CONFIG
from . import assignments as assignments_mod
from . import benchmarks as benchmarks_mod
from . import billing as billing_mod
from . import digest as digest_mod
from . import mailer
from . import staple as staple_mod
from . import webhooks as webhooks_mod
from . import onboarding as onboarding_mod
from . import positions as positions_mod
from . import sports as sports_mod
from . import recognition as recognition_mod
from . import rtp as rtp_mod
from . import wellness as wellness_mod
from . import transfer as transfer_mod
from . import film as film_mod
from . import guardians as guardians_mod
from . import practice as practice_mod
from . import roster as roster_mod
from . import roster_sync
from . import notifications as notify
from .assignments import AssignmentError
from .billing import BillingError
from .guardians import GuardianError
from .roster import RosterError
from .drills import ALL_DRILLS, DRILLS_BY_KEY
from .leaderboard import attach_load, coach_roster, leaderboard, team_standings
from .store import Principal, Store, StoreError, transaction

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


def _utcnow_stamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


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
def list_drills(sport: str | None = None) -> dict[str, Any]:
    """The full drill catalog, including the counting spec the client runs.

    Each drill also carries what it is worth in *other* sports. Pass `sport` to
    leave the athlete's own out -- telling a lacrosse player that wall ball
    helps at lacrosse is noise, and noise teaches kids to skip the text.

    Stays unauthenticated: this is reference data, the counting spec ships to
    every browser anyway, and the transfer notes are the same for everyone.
    """
    return {
        "sport": sport,
        "drills": [
            {**d.to_dict(), **transfer_mod.describe(d.key, sport)} for d in ALL_DRILLS
        ],
    }


@app.get("/api/me/drills")
def my_drills(
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """The catalog, with anything loading a sore area marked unavailable.

    Held back rather than forbidden: the drill still appears and can still be
    started. This app is not anyone's physio and should not pretend it can
    stop a determined thirteen-year-old -- but it should not put a sore knee
    on the home screen with a button next to it either.
    """
    sport = _org_sport(store, principal.org_id)
    status = store.wellness_status(principal.id)
    return {
        "sport": sport,
        "drills": [
            {
                **d.to_dict(),
                **transfer_mod.describe(d.key, sport),
                **wellness_mod.drill_availability(status, d.key, d.load.tissue),
            }
            for d in ALL_DRILLS
        ],
        "wellness": status.to_dict(),
    }


@app.get("/api/drills/{drill_key}")
def get_drill_spec(drill_key: str, sport: str | None = None) -> dict[str, Any]:
    if drill_key not in DRILLS_BY_KEY:
        raise HTTPException(status_code=404, detail=f"unknown drill: {drill_key}")
    return {**DRILLS_BY_KEY[drill_key].to_dict(), **transfer_mod.describe(drill_key, sport)}


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

    The sport is normalised rather than stored verbatim: a director who types
    "Girls Lacrosse" or "B-Ball" into a field they think is free text would
    otherwise get a program whose sport matches no position list, no drill
    emphasis and no transfer filter -- broken in three places at once, silently.
    """
    resolved = sports_mod.normalize(body.sport)
    if resolved is None:
        known = ", ".join(s.label for s in sports_mod.CATALOG)
        raise HTTPException(
            status_code=400,
            detail=f"{body.sport!r} is not a sport we know. Pick one of: {known}",
        )
    org_id = store.create_org(body.name, resolved.key)
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
    # Ball drills only: how fast the ball left the contact, and what took it.
    # Both bounded like everything else here, since they are client-supplied.
    speed: float | None = Field(default=None, ge=0.0, le=100.0)
    part: str = Field(default="", max_length=32)


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
    # Share of frames on which the ball was actually detected. Absent on pose
    # drills; on a ball drill its absence is itself a reason to hold the
    # session, since a real client always knows this number.
    track_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    # Confirm-mode drills only: how many contacts the ball tracker saw while
    # the body counted the reps. Used to tell a real session from a mime.
    ball_contacts: int | None = Field(default=None, ge=0, le=20_000)
    # Share of tracked frames the ball spent away from the athlete's hands.
    # Separates a throw from a throwing motion with the ball still in it.
    ball_travel: float | None = Field(default=None, ge=0.0, le=1.0)


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
            track_quality=body.track_quality,
            ball_contacts=body.ball_contacts,
            ball_travel=body.ball_travel,
        )
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/me")
def me(
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if principal.role == "athlete":
        return {
            "role": principal.role,
            **store.athlete_profile(principal.id),
            # So the capture screen knows whether to offer sending a clip. The
            # button is absent rather than present-and-failing when permission
            # is off: a child tapping something that tells them their parent
            # said no is a conversation the app should not start.
            "consents": guardians_mod.current_consents(store.conn, principal.id),
        }
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
    """Queue this week's digest and try to deliver it immediately.

    Queued first even for a manual send, so a failure is retried by the same
    worker that handles the Monday run rather than silently lost.
    """
    if body.team_id is not None and not principal.can_see_team(body.team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")

    report = digest_mod.compute(store.conn, principal.org_id, team_id=body.team_id)
    recipient = body.to or store.conn.execute(
        "SELECT email FROM users WHERE id = ?", (principal.id,)
    ).fetchone()["email"]

    if not mailer.looks_like_email(recipient):
        raise HTTPException(
            status_code=400,
            detail="No email address on file. Add one, or pass an address to send to.",
        )
    if mailer.is_suppressed(store.conn, recipient):
        raise HTTPException(
            status_code=400,
            detail=f"{recipient} has unsubscribed or previously bounced.",
        )

    dashboard = (
        f"{CONFIG.app_base_url.rstrip('/')}/app/coach.html"
        if CONFIG.app_base_url else ""
    )
    unsubscribe = mailer.unsubscribe_url(principal.id, mailer.Kind.COACH_DIGEST)
    subject = digest_mod.subject_line(report)

    # A manual send is on demand, so it carries a timestamp in its dedupe key
    # rather than collapsing into the week's scheduled copy.
    queued = mailer.enqueue(
        store.conn,
        to_email=recipient,
        subject=subject,
        html=digest_mod.render_html(report, dashboard, unsubscribe_url=unsubscribe),
        text=digest_mod.render_text(report, dashboard, unsubscribe_url=unsubscribe),
        kind=mailer.Kind.COACH_DIGEST,
        dedupe_key=f"manual:{principal.id}:{body.team_id or 'org'}:{_utcnow_stamp()}",
        user_id=principal.id,
    )
    if queued is None:
        raise HTTPException(
            status_code=400,
            detail="Not queued — you have unsubscribed from the weekly digest.",
        )

    stats = mailer.flush(store.conn, limit=5)
    row = store.conn.execute(
        "SELECT status, last_error FROM email_outbox WHERE id = ?", (queued,)
    ).fetchone()
    delivered = row["status"] == "sent"

    return {
        "to": recipient,
        "queued": True,
        "delivered": delivered,
        "status": row["status"],
        "subject": subject,
        "stats": stats,
        "note": None if (delivered and CONFIG.smtp_configured) else (
            "Email is not configured on this server, so nothing left the machine. "
            "The digest is still viewable and printable from the preview."
            if not CONFIG.smtp_configured else
            f"Queued but not yet delivered ({row['last_error'][:120]}). "
            "It will be retried automatically."
        ),
    }


# ----------------------------------------------------------------------
# Delivery webhooks
# ----------------------------------------------------------------------

@app.post("/api/webhooks/email/{provider}")
async def email_webhook(
    provider: str,
    request: Request,
    store: Store = Depends(get_store),
) -> JSONResponse:
    """Receive delivery events from a mail provider.

    Deliberately outside the bearer-token auth: the caller is a provider, not a
    user. Authenticity comes from the provider's own signature over the raw
    body, which is why this reads the body itself rather than declaring a
    model -- a parsed and re-serialized payload no longer matches what was
    signed.
    """
    secret = CONFIG.webhook_secrets.get(provider, "")
    body = await request.body()

    if len(body) > webhooks_mod.MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="payload too large")

    try:
        result = webhooks_mod.handle(
            provider, dict(request.headers), body, secret, store.conn
        )
    except webhooks_mod.WebhookError as exc:
        message = str(exc)
        if "verification" in message:
            # Deliberately terse. Telling an unauthenticated caller *why* the
            # signature failed helps them make the next one succeed.
            raise HTTPException(status_code=401, detail="unauthorized") from None
        # Verified but unreadable: accept it so the provider does not disable
        # the endpoint over a shape we have not seen, and log it for us.
        log = __import__("logging").getLogger(__name__)
        log.warning("unreadable %s webhook: %s", provider, message)
        return JSONResponse(status_code=202, content={"accepted": True, "note": message})

    return JSONResponse(status_code=200, content=result)


@app.get("/api/coach/staples")
def get_staples(
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Freshness of the pre-fetched revocation answers.

    Surfaced because a stale staple is the condition that makes strict mode
    start refusing webhooks, and it should be visible before that happens
    rather than discovered by it.
    """
    if not principal.is_director:
        raise HTTPException(status_code=403, detail="director access required")
    return {
        **staple_mod.summary(store.conn),
        "strict_mode": CONFIG.sns_revocation_strict,
        "revocation_enabled": CONFIG.sns_check_revocation,
    }


@app.get("/api/coach/bounces")
def get_bounces(
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Addresses that are failing, so someone can go and fix them."""
    if not principal.is_director:
        raise HTTPException(status_code=403, detail="director access required")
    return {
        **webhooks_mod.bounce_summary(store.conn),
        "recent_events": webhooks_mod.recent_events(store.conn, 25),
        "configured_providers": [
            name for name, secret in CONFIG.webhook_secrets.items() if secret
        ],
    }


class UnsuppressRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)


@app.post("/api/coach/bounces/unsuppress")
def unsuppress_address(
    body: UnsuppressRequest,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Put a corrected address back into circulation.

    Refuses a spam complaint: someone who reported the mail did not ask to be
    put back on the list, and an administrator should not be able to override
    that on their behalf.
    """
    if not principal.is_director:
        raise HTTPException(status_code=403, detail="director access required")

    complained = store.conn.execute(
        "SELECT 1 FROM webhook_events WHERE email = ? AND event_type = ? LIMIT 1",
        (body.email.strip().lower(), webhooks_mod.EventType.COMPLAINT),
    ).fetchone()
    if complained:
        raise HTTPException(
            status_code=400,
            detail="That recipient reported the mail as spam. They have to opt "
                   "back in themselves.",
        )

    mailer.unsuppress(store.conn, body.email)
    return {"email": body.email, "suppressed": False}


# ----------------------------------------------------------------------
# Email delivery
# ----------------------------------------------------------------------

@app.get("/api/email/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str) -> str:
    """One-click unsubscribe. Unauthenticated by design.

    Someone who wants out is holding an email, not a login. Requiring them to
    sign in to stop receiving mail is how a message gets marked as spam
    instead, which costs far more than the one recipient.
    """
    store = get_store()
    verified = mailer.verify_unsubscribe(token)
    if verified is None:
        return (
            "<!doctype html><meta charset='utf-8'>"
            "<body style='font-family:system-ui;padding:40px;max-width:32rem'>"
            "<h2>That link is not valid</h2>"
            "<p>It may have been altered in transit. Reply to the email and we "
            "will take you off the list.</p></body>"
        )

    user_id, kind = verified
    mailer.set_preference(store.conn, user_id, kind, False)
    row = store.conn.execute(
        "SELECT display_name FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    who = row["display_name"] if row else "You"

    return (
        "<!doctype html><meta charset='utf-8'>"
        "<body style='font-family:system-ui;padding:40px;max-width:32rem;line-height:1.6'>"
        f"<h2>Unsubscribed</h2><p>{who} will no longer receive the weekly email.</p>"
        "<p style='color:#5b6b7c'>Alerts inside the app are unaffected, and this "
        "changes nothing for your athletes. You can turn the email back on from "
        "your dashboard at any time.</p></body>"
    )


@app.post("/api/email/unsubscribe")
def unsubscribe_one_click(token: str) -> dict[str, Any]:
    """The POST an email client sends for List-Unsubscribe-Post."""
    store = get_store()
    verified = mailer.verify_unsubscribe(token)
    if verified is None:
        raise HTTPException(status_code=400, detail="invalid token")
    user_id, kind = verified
    mailer.set_preference(store.conn, user_id, kind, False)
    return {"unsubscribed": True, "kind": kind}


@app.get("/api/email/preferences")
def get_email_preferences(
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return {"preferences": mailer.preferences(store.conn, principal.id)}


class EmailPreference(BaseModel):
    kind: str = Field(max_length=60)
    enabled: bool


@app.post("/api/email/preferences")
def set_email_preference(
    body: EmailPreference,
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    mailer.set_preference(store.conn, principal.id, body.kind, body.enabled)
    return {"preferences": mailer.preferences(store.conn, principal.id)}


@app.get("/api/coach/outbox")
def get_outbox(
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Delivery status, so "did the coach get it?" has an answer."""
    if not principal.is_director:
        raise HTTPException(status_code=403, detail="director access required")
    return {
        **mailer.outbox_summary(store.conn, 40),
        "smtp_configured": CONFIG.smtp_configured,
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
    plan = store.resolve_import(
        principal.org_id,
        roster_mod.parse(body.content, sport=_org_sport(store, principal.org_id)),
    )
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
    plan = store.resolve_import(
        principal.org_id,
        roster_mod.parse(body.content, sport=_org_sport(store, principal.org_id)),
    )
    result = store.apply_import(
        principal.org_id, body.team_id, plan, principal.id,
        issue_guardian_invites=body.invite_guardians,
    )
    return {"summary": plan.to_dict()["summary"], **result}


# ---------------------------------------------------------------------------
# Roster links -- keeping a roster in step with wherever it already lives
# ---------------------------------------------------------------------------


@app.get("/api/coach/roster/providers")
def roster_providers() -> dict[str, Any]:
    """What a team can connect to, and how honest we are about each."""
    return {
        "providers": [
            {
                "key": p.key,
                "label": p.label,
                "credential_label": p.credential_label,
                "team_field": p.team_field,
                "help_url": p.help_url,
                "verified": p.verified,
                "note": p.note,
            }
            for p in roster_sync.PROVIDERS
        ]
    }


class RosterLink(BaseModel):
    team_id: int
    provider: str = Field(min_length=1, max_length=40)
    # Reaches back into a system holding children's contact details. It is
    # stored, used by the sync, and never read back out.
    token: str = Field(min_length=1, max_length=4_000)
    remote_ref: str = Field(min_length=1, max_length=200)


@app.post("/api/coach/roster/link", status_code=201)
def link_roster(
    body: RosterLink,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Connect a team to its roster source, then immediately dry-run it.

    The dry run is not optional. A wrong team id is the overwhelmingly common
    first mistake here, and it looks exactly like a real roster until somebody
    reads the names.
    """
    if not principal.can_see_team(body.team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")
    link = store.link_roster(
        principal.org_id, body.team_id, body.provider,
        body.token, body.remote_ref, principal.id,
    )
    return {"link": link, "preview": store.sync_roster(
        principal.org_id, body.team_id, body.provider, dry_run=True)}


@app.get("/api/coach/roster/links")
def roster_links(
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return {"links": [
        link for link in store.roster_links(principal.org_id)
        if principal.can_see_team(link["team_id"])
    ]}


class RosterSyncRequest(BaseModel):
    team_id: int
    provider: str = Field(min_length=1, max_length=40)
    apply: bool = False


@app.post("/api/coach/roster/sync")
def sync_roster(
    body: RosterSyncRequest,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if not principal.can_see_team(body.team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")
    return store.sync_roster(
        principal.org_id, body.team_id, body.provider,
        dry_run=not body.apply, actor_id=principal.id,
    )


class RosterAutoSync(BaseModel):
    team_id: int
    provider: str = Field(min_length=1, max_length=40)
    on: bool


@app.post("/api/coach/roster/auto-sync")
def set_roster_auto_sync(
    body: RosterAutoSync,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Hand the sync permission to write, once a coach has seen a run."""
    if not principal.can_see_team(body.team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")
    if body.on:
        # Not merely "a run happened" -- connecting dry-runs, so that would
        # always be true and would guard nothing. A run that *worked* is the
        # evidence that the team id is right, and a wrong team id is the
        # mistake this is here to keep off a schedule.
        link = store.roster_link(body.team_id, body.provider)
        last = link["last_result"] or {}
        if not last.get("ok"):
            raise HTTPException(
                status_code=400,
                detail=(
                    "the last sync did not succeed, so this cannot run "
                    "unattended yet: " + (last.get("error") or "it has not run")
                ),
            )
    return store.set_roster_auto_sync(
        principal.org_id, body.team_id, body.provider, body.on)


@app.delete("/api/coach/roster/link")
def unlink_roster(
    team_id: int,
    provider: str,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Disconnect. Athletes already imported stay -- they are ours now."""
    if not principal.can_see_team(team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")
    return {"removed": store.unlink_roster(principal.org_id, team_id, provider)}


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


@app.get("/api/benchmarks")
def my_benchmarks(
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """How much training suits this athlete's age, and how they compare inside it."""
    return benchmarks_mod.report(store.conn, principal.id)


@app.get("/api/coach/budgets")
def team_budgets(
    team_id: int | None = None,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Who is short of their age-appropriate budget, and who is past it.

    Both directions, deliberately. A dashboard that only surfaces the quiet
    ones teaches a squad that more is always better, which is the belief this
    whole feature exists to interrupt.
    """
    if team_id is not None and not principal.can_see_team(team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")

    athletes = coach_roster(
        store.conn, principal.org_id, team_id, "week", scope=principal.scope_filter()
    )
    sport = _org_sport(store, principal.org_id)
    return {
        **benchmarks_mod.program_summary(
            store.conn, [a["athlete_id"] for a in athletes], sport=sport
        ),
        "bands": [b.to_dict() for b in benchmarks_mod.AGE_BANDS],
        "sport": sport,
    }


def _org_sport(store: Store, org_id: int) -> str:
    row = store.conn.execute(
        "SELECT sport FROM organizations WHERE id = ?", (org_id,)
    ).fetchone()
    return (row["sport"] if row else None) or "lacrosse"


class SpecialisationSetting(BaseModel):
    #: 0 means position guidance from the youngest band; 99 keeps every
    #: athlete on the general mix permanently. Anything between is an age.
    position_emphasis_min_age: int = Field(ge=0, le=99)


@app.put("/api/org/specialisation")
def set_specialisation_age(
    body: SpecialisationSetting,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """When position-specific training guidance switches on for this program.

    Directors only. It is a judgement about how children in this program should
    be developed, which is squarely a director's call and not an assistant
    coach's -- and not ours either, which is why it is a setting rather than a
    constant. The default of 15 is the conservative end of it.
    """
    if not principal.is_director:
        raise HTTPException(
            status_code=403,
            detail="only a director can change when position training starts",
        )
    with transaction(store.conn) as conn:
        conn.execute(
            "UPDATE organizations SET position_emphasis_min_age = ? WHERE id = ?",
            (body.position_emphasis_min_age, principal.org_id),
        )
    return {
        "position_emphasis_min_age": body.position_emphasis_min_age,
        "applies_from": _specialisation_label(body.position_emphasis_min_age),
    }


def _specialisation_label(age: int) -> str:
    if age >= 99:
        return "Never — every athlete stays on the all-round plan"
    if age <= 0:
        return "All ages"
    return f"Age {age} and up"


class SportEntry(BaseModel):
    sport: str
    seasons: list[str] = Field(default_factory=list)
    is_primary: bool = False


class AthleteSports(BaseModel):
    sports: list[SportEntry] = Field(default_factory=list, max_length=12)


class CheckIn(BaseModel):
    soreness: Literal["fine", "niggle", "sore", "hurts"]


class DiscomfortReport(BaseModel):
    area: str
    severity: Literal["fine", "niggle", "sore", "hurts"]
    side: Literal["left", "right", "both", ""] = ""
    flags: list[str] = Field(default_factory=list, max_length=8)
    note: str = Field(default="", max_length=500)


class ClipQuestion(BaseModel):
    prompt: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(min_length=2, max_length=4)
    answer: int = Field(ge=0, le=3)
    because: str = Field(default="", max_length=400)


class NewClip(BaseModel):
    video: str = Field(min_length=5, max_length=500)
    title: str = Field(min_length=1, max_length=160)
    focus: str = Field(default="", max_length=400)
    provider: Literal["youtube", "link"] = "youtube"
    start_s: int = Field(default=0, ge=0, le=86_400)
    end_s: int | None = Field(default=None, ge=1, le=86_400)
    positions: list[str] = Field(default_factory=list, max_length=8)
    min_age: int = Field(default=0, ge=0, le=99)
    max_age: int = Field(default=200, ge=0, le=200)
    question: ClipQuestion | None = None


class Beat(BaseModel):
    """One heartbeat from the player.

    Note what is *not* here: elapsed time. The server takes that from its own
    record of the previous beat, because a payload that reports its own elapsed
    time can report whatever makes the numbers work.
    """

    position_s: float = Field(ge=0, le=86_400)
    muted: bool = False
    hidden: bool = False
    rate: float = Field(default=1.0, ge=0.1, le=4.0)


class ClipAnswer(BaseModel):
    choice: int = Field(ge=0, le=3)


@app.get("/api/film")
def my_film(
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Today's shortlist, and what is left of the day's allowance."""
    return store.clips_for_athlete(principal.id, principal.org_id)


@app.get("/api/film/history")
def my_film_history(
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return store.film_history(principal.id)


@app.post("/api/film/{clip_id}/start", status_code=201)
def start_watch(
    clip_id: int,
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.start_watch(principal.id, clip_id)
    except StoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/film/watches/{watch_id}/beat")
def record_beat(
    watch_id: int,
    body: Beat,
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.record_beat(
            principal.id, watch_id, body.position_s,
            muted=body.muted, hidden=body.hidden, rate=body.rate,
        )
    except StoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/film/watches/{watch_id}/answer")
def answer_clip(
    watch_id: int,
    body: ClipAnswer,
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.answer_clip(principal.id, watch_id, body.choice)
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/coach/film")
def team_film(
    team_id: int | None = None,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Who is putting the time in.

    Reports clips *completed* rather than minutes, and does not rank by volume
    -- the same rule the training boards follow. A kid who watches two clips
    properly has done the work; one who leaves six playing in a background tab
    has not, and neither number is a score to beat.
    """
    if team_id is not None and not principal.can_see_team(team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")
    athletes = coach_roster(
        store.conn, principal.org_id, team_id, "week", scope=principal.scope_filter()
    )
    return store.team_film([a["athlete_id"] for a in athletes])


@app.get("/api/coach/clips")
def list_clips(
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    rows = store.conn.execute(
        "SELECT * FROM clips WHERE org_id = ? AND active = 1 ORDER BY id DESC",
        (principal.org_id,),
    ).fetchall()
    return {
        "clips": [store._row_to_clip(r).to_dict(include_answer=True) for r in rows],
        "bands": [b.to_dict() for b in film_mod.BANDS],
    }


@app.post("/api/coach/clips", status_code=201)
def create_clip(
    body: NewClip,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    try:
        return store.create_clip(
            principal.org_id, body.video, body.title,
            focus=body.focus, provider=body.provider,
            start_s=body.start_s, end_s=body.end_s, positions=body.positions,
            min_age=body.min_age, max_age=body.max_age,
            question=body.question.model_dump() if body.question else None,
            created_by=principal.id,
        )
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/coach/clips/{clip_id}")
def retire_clip(
    clip_id: int,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return {"retired": store.retire_clip(principal.org_id, clip_id)}


@app.get("/api/wellness/form")
def wellness_form() -> dict[str, Any]:
    """The vocabulary the check-in form is built from.

    Public, like the drill catalog: it is a list of body parts and four
    phrasings of "how bad is it", and holding it behind auth would buy nothing.
    """
    return {
        "severities": [
            {"key": key, "prompt": wellness_mod.Severity.PROMPTS[key]}
            for key in wellness_mod.Severity.ORDER
        ],
        "areas": [a.to_dict() for a in wellness_mod.AREAS],
        "flags": [{"key": k, "prompt": v} for k, v in wellness_mod.FLAGS.items()],
        "sides": ["left", "right", "both"],
        "promise": (
            "Telling us you are sore never costs you a streak, points, or a "
            "place on any board. Your coach sees which area and how bad. "
            "Anything you type in the notes box is seen by you and your "
            "parent or guardian only."
        ),
    }


@app.get("/api/wellness")
def my_wellness(
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return store.wellness_status(principal.id).to_dict()


@app.post("/api/wellness/checkin")
def post_checkin(
    body: CheckIn,
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    result = store.check_in(principal.id, body.soreness)
    return {**result, **store.wellness_status(principal.id).to_dict()}


@app.post("/api/wellness/discomfort", status_code=201)
def post_discomfort(
    body: DiscomfortReport,
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Report something that hurts.

    Escalation to a guardian happens here rather than in a nightly job: a head
    knock or a joint that gives way is not a thing to tell a parent about
    tomorrow morning.
    """
    try:
        saved = store.report_discomfort(
            principal.id, body.area, body.severity,
            side=body.side, flags=body.flags, note=body.note,
        )
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    status = store.wellness_status(principal.id)
    for report, assessment in zip(status.reports, status.assessments):
        if report.id == saved["id"]:
            notify.notify_discomfort(store.conn, principal.id, report, assessment)
            store.conn.commit()
            break
    return status.to_dict()


@app.post("/api/wellness/discomfort/{report_id}/resolved")
def resolve_discomfort(
    report_id: int,
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    store.resolve_discomfort(principal.id, report_id)
    return store.wellness_status(principal.id).to_dict()


class Clearance(BaseModel):
    #: Required when the plan needs a clinician. Free text, and stored as an
    #: attestation by the person who typed it -- the app cannot verify it.
    clinician_name: str = Field(default="", max_length=120)


@app.get("/api/wellness/plans")
def my_return_plans(
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return {"plans": [p.to_dict() for p in store.active_return_plans(principal.id)]}


@app.post("/api/wellness/plans/{plan_id}/advance")
def advance_plan(
    plan_id: int,
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Move up a stage.

    The athlete's own action, but only once the gate opens: time served at the
    stage, a check-in today saying they feel fine, and -- for the first step --
    an adult having cleared them. The refusal explains itself, because a greyed
    out button with no reason is how a kid decides the app is broken and goes
    back to training on their own.
    """
    try:
        return store.advance_return_plan(principal.id, plan_id)
    except StoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/wellness/plans/{plan_id}/clearance")
def clear_plan(
    plan_id: int,
    body: Clearance,
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Record that a human has said this athlete can start their ramp.

    **This endpoint never generates a clearance -- it stores someone else's.**
    An athlete cannot clear themselves, and a plan that needs a clinician can
    only be cleared by a guardian, who is the person with standing to say what
    a doctor told the family. A coach can clear the ordinary ones, which is a
    judgement coaches already make at every practice.
    """
    plan = store.conn.execute(
        "SELECT athlete_id, clearance FROM return_plans WHERE id = ?", (plan_id,)
    ).fetchone()
    if plan is None:
        raise HTTPException(status_code=404, detail="no return plan with that id")

    athlete_id = int(plan["athlete_id"])
    if principal.id == athlete_id:
        raise HTTPException(
            status_code=403,
            detail="you cannot clear your own return — ask a parent or your coach",
        )

    is_guardian = guardians_mod.guards(store.conn, principal.id, athlete_id)
    if plan["clearance"] == rtp_mod.Clearance.CLINICIAN and not is_guardian:
        raise HTTPException(
            status_code=403,
            detail=(
                "this one has to be recorded by a parent or guardian, because it "
                "needs what a doctor or physio told the family"
            ),
        )
    if not is_guardian and not principal.is_staff:
        raise HTTPException(status_code=403, detail="not your athlete")
    if principal.is_staff and not is_guardian:
        owner = store.conn.execute(
            "SELECT org_id FROM users WHERE id = ?", (athlete_id,)
        ).fetchone()
        if owner is None or owner["org_id"] != principal.org_id:
            raise HTTPException(status_code=404, detail="no return plan with that id")

    try:
        return store.clear_return_plan(
            plan_id, principal.id, principal.display_name, body.clinician_name,
        )
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/wellness/plans/{plan_id}/history")
def plan_history(
    plan_id: int,
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Who decided what, and when. The one record here that may need answering
    for later, so it is readable by everyone with standing over the athlete."""
    plan = store.conn.execute(
        "SELECT athlete_id FROM return_plans WHERE id = ?", (plan_id,)
    ).fetchone()
    if plan is None:
        raise HTTPException(status_code=404, detail="no return plan with that id")
    athlete_id = int(plan["athlete_id"])

    allowed = principal.id == athlete_id or guardians_mod.guards(
        store.conn, principal.id, athlete_id
    )
    if not allowed and principal.is_staff:
        owner = store.conn.execute(
            "SELECT org_id FROM users WHERE id = ?", (athlete_id,)
        ).fetchone()
        allowed = owner is not None and owner["org_id"] == principal.org_id
    if not allowed:
        raise HTTPException(status_code=404, detail="no return plan with that id")
    return {"events": store.plan_history(plan_id)}


class RecognitionTemplate(BaseModel):
    milestone: str
    body: str = Field(default="", max_length=600)
    enabled: bool = True
    from_voice: Literal["coach", "voice"] = "coach"


@app.get("/api/parent/athletes/{athlete_id}/drills")
def parent_drill_log(
    athlete_id: int,
    days: int = Query(default=30, ge=1, le=180),
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Everything their athlete has done, across every drill.

    A parent gets the same picture a coach does, for their own child: what was
    trained, how much, how it was scored, and what was held for review. Held
    sessions are shown rather than hidden -- a parent finding out from their
    child that something was queried is worse than reading it here.
    """
    guardians_mod.require_guardianship(store.conn, principal.id, athlete_id)
    return store.drill_log(athlete_id, days)


@app.get("/api/parent/athletes/{athlete_id}/clips")
def parent_clips(
    athlete_id: int,
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """What their athlete has sent, who has watched it, and when it goes.

    A parent could already turn this permission on and off and had no way to
    see what it produced -- which made the consent a switch in the dark. The
    point of asking someone to allow something is that they can then look at
    what they allowed.
    """
    guardians_mod.require_guardianship(store.conn, principal.id, athlete_id)
    return {
        "clips": store.shared_clips_for_athlete(athlete_id),
        "allowed": store._may_share_video(athlete_id),
        "retention_days": store.CLIP_RETENTION_DAYS,
    }


@app.get("/api/parent/athletes/{athlete_id}/clips/{clip_id}/video")
def parent_watch_clip(
    athlete_id: int,
    clip_id: int,
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> Response:
    """Let a parent watch what was shared.

    Logged like any other view, and shown to the athlete. A teenager who can
    see that a coach watched should be able to see that a parent did too --
    the audit trail is for them, not only about them.
    """
    guardians_mod.require_guardianship(store.conn, principal.id, athlete_id)
    try:
        clip = store.shared_clip(clip_id, with_bytes=True)
    except StoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if clip["athlete_id"] != athlete_id:
        raise HTTPException(status_code=404, detail="no clip with that id")

    store.record_clip_view(clip_id, principal.id, principal.display_name)
    return Response(content=clip["bytes"], media_type=clip["mime"])


@app.get("/api/parent/athletes/{athlete_id}/messages")
def parent_messages(
    athlete_id: int,
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Every message their athlete has been sent.

    A copy of all of it, because a parent should never learn what their child
    was told from the child. There is no reply field here and no endpoint
    behind one: these messages go one way by design.
    """
    guardians_mod.require_guardianship(store.conn, principal.id, athlete_id)
    rows = store.conn.execute(
        "SELECT kind, title, body, from_name, created_at FROM notifications "
        "WHERE about_athlete_id = ? AND is_copy = 1 ORDER BY id DESC LIMIT 100",
        (athlete_id,),
    ).fetchall()
    return {
        "messages": [dict(r) for r in rows],
        "replies_allowed": False,
        "note": (
            "You see everything your athlete is sent. Messages here are "
            "one-way — nobody can reply through the app, including you."
        ),
    }


@app.get("/api/guardians/onboarding")
def parent_onboarding(
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """What this guardian still has to decide, per child.

    Short for a different reason than the athlete's: a parent's job here is
    not to set anything up, it is to make one decision that is genuinely
    theirs. Padding it with tasks would dress a consent screen up as a tour.
    """
    return onboarding_mod.parent_progress(store.conn, principal.id)


@app.get("/api/me/onboarding")
def athlete_onboarding(
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Where a new athlete is, and what is stopping them.

    Deliberately shorter than a coach's. Someone setting up a program will
    read six steps; a twelve-year-old who wants to go outside will read one,
    and the one that matters is recording a session.
    """
    return onboarding_mod.athlete_progress(store.conn, principal.id)


@app.get("/api/coach/onboarding")
def coach_onboarding(
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Where this program is in setting itself up.

    Derived from the database every time rather than from a flag saying
    somebody clicked "done" -- a remembered dismissal stays ticked after the
    team is deleted, and cannot tell a director who came back a week later
    where they actually got to.
    """
    # A coach who joined a program somebody else built gets orientation
    # rather than a setup checklist: the teams and athletes already exist, and
    # handing them "create your first team" would be telling them to redo work
    # that is done.
    if not principal.is_director:
        return onboarding_mod.staff_progress(
            store.conn, principal.id, principal.org_id,
        )
    return onboarding_mod.progress(
        store.conn,
        principal.org_id,
        "family" if store.is_family(principal.org_id) else "program",
    )


@app.get("/api/coach/recognition")
def recognition_templates(
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """The milestones, with whatever words this program has written for them."""
    return {
        "milestones": store.recognition_templates(principal.org_id),
        "tokens": list(recognition_mod.TOKENS),
        "voice": store.program_voice(principal.org_id),
        "voices": list(recognition_mod.Voice.ALL),
        "is_family": store.is_family(principal.org_id),
    }


class RecognitionPreview(BaseModel):
    body: str = Field(default="", max_length=600)
    athlete_id: int | None = None


@app.post("/api/coach/recognition/preview")
def preview_recognition(
    body: RecognitionPreview,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """What this message will look like when it lands.

    Rendered by the same function that sends it, so the preview and the real
    thing cannot drift. It matters most for a parent writing to their own
    child, where there is no coach to notice the wording came out wrong.
    """
    return store.preview_recognition(principal.org_id, body.body, body.athlete_id)


@app.get("/api/coach/recognition/sent")
def recognition_sent(
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """What has actually gone out, and to whom.

    A coach can ask their athletes. A parent writing these for their own
    children is often the only person who would ever check, so it is worth
    being able to see the messages as sent rather than as intended.
    """
    return {"sent": store.recognition_sent(principal.org_id)}


@app.put("/api/coach/recognition")
def set_recognition_template(
    body: RecognitionTemplate,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Put a coach's own words on a milestone.

    Staff rather than directors only: the words a coach uses with their own
    athletes are theirs, and a program that wants that locked down can do it
    by not making people coaches.
    """
    try:
        return store.set_recognition_template(
            principal.org_id, body.milestone, body.body, body.enabled, principal.id,
            from_voice=body.from_voice,
        )
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class SharedClip(BaseModel):
    #: Base64 of a short recording the athlete picked. Bounded well above a
    #: sensible clip and well below anything that could fill a disk.
    data: str = Field(max_length=20_000_000)
    mime: Literal["video/webm", "video/mp4"] = "video/webm"
    session_id: int | None = None
    drill_key: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=400)


@app.post("/api/clips", status_code=201)
def share_clip(
    body: SharedClip,
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Send one clip to the coaching staff.

    The only route in this product that accepts video, and it exists because a
    parent turned it on and an athlete chose this clip. Nothing calls it
    automatically.
    """
    try:
        raw = base64.b64decode(body.data, validate=True)
    except Exception as exc:  # noqa: BLE001 -- any decode failure is the same answer
        raise HTTPException(status_code=400, detail="that clip did not decode") from exc
    try:
        return store.share_clip(
            principal.id, raw, session_id=body.session_id,
            drill_key=body.drill_key, mime=body.mime, note=body.note,
        )
    except StoreError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/clips")
def my_clips(
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """What this athlete has sent, and who has watched each one."""
    return {"clips": store.shared_clips_for_athlete(principal.id)}


@app.delete("/api/clips/{clip_id}")
def unshare_clip(
    clip_id: int,
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Take it back.

    The athlete or their guardian, at any time, no reason needed.
    """
    clip = store.conn.execute(
        "SELECT athlete_id FROM shared_clips WHERE id = ?", (clip_id,)
    ).fetchone()
    if clip is None:
        raise HTTPException(status_code=404, detail="no clip with that id")
    athlete_id = int(clip["athlete_id"])
    allowed = principal.id == athlete_id or guardians_mod.guards(
        store.conn, principal.id, athlete_id
    )
    if not allowed:
        raise HTTPException(status_code=404, detail="no clip with that id")
    return {"deleted": store.delete_shared_clip(clip_id)}


@app.get("/api/coach/clips-shared")
def staff_shared_clips(
    team_id: int | None = None,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if team_id is not None and not principal.can_see_team(team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")
    athletes = coach_roster(
        store.conn, principal.org_id, team_id, "week", scope=principal.scope_filter()
    )
    return {"clips": store.shared_clips_for_org(
        principal.org_id, [a["athlete_id"] for a in athletes]
    )}


@app.get("/api/coach/clips-shared/{clip_id}/video")
def watch_shared_clip(
    clip_id: int,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> Response:
    """Play a clip an athlete sent.

    Consent is re-checked here rather than trusted from the moment of upload:
    a parent who withdrew permission this morning must not have last night's
    clip served this afternoon. Deleting on revocation already makes that
    true; checking again makes it true even if that ever fails.
    """
    try:
        clip = store.shared_clip(clip_id, with_bytes=True)
    except StoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    owner = store.conn.execute(
        "SELECT org_id FROM users WHERE id = ?", (clip["athlete_id"],)
    ).fetchone()
    if owner is None or owner["org_id"] != principal.org_id:
        raise HTTPException(status_code=404, detail="no clip with that id")
    if not store._may_share_video(clip["athlete_id"]):
        raise HTTPException(
            status_code=403,
            detail="a guardian has withdrawn permission for coach video",
        )

    store.record_clip_view(clip_id, principal.id, principal.display_name)
    return Response(content=clip["bytes"], media_type=clip["mime"])


@app.get("/api/coach/ball")
def team_ball_drills(
    team_id: int | None = None,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Skill work across the squad, and who needs help pointing their phone."""
    if team_id is not None and not principal.can_see_team(team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")
    athletes = coach_roster(
        store.conn, principal.org_id, team_id, "week", scope=principal.scope_filter()
    )
    return store.team_ball_drills([a["athlete_id"] for a in athletes])


@app.get("/api/coach/practice")
def practice_briefing(
    team_id: int | None = None,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """The ninety seconds before practice starts.

    One card: who is not training, who is on modified work, who is worth an
    eye, and what the squad has not got through. Composed from the same
    functions the full screens use, so it cannot drift from the screen a coach
    opens next.
    """
    if team_id is not None and not principal.can_see_team(team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")
    return practice_mod.brief(
        store, principal.org_id, team_id, scope=principal.scope_filter()
    ).to_dict()


@app.get("/api/coach/wellness")
def team_wellness(
    team_id: int | None = None,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Who on this squad is carrying something.

    Coaches get what changes a training decision -- area, severity band, how
    long, which way it is going. They do not get the athlete's own note; that
    is the athlete's and their guardian's. The split is enforced here rather
    than in the client, because a client-side filter is a suggestion.
    """
    if team_id is not None and not principal.can_see_team(team_id):
        raise HTTPException(status_code=403, detail="you are not assigned to that team")

    athletes = coach_roster(
        store.conn, principal.org_id, team_id, "week", scope=principal.scope_filter()
    )
    carrying, counts = [], {}
    for athlete in athletes:
        status = store.wellness_status(athlete["athlete_id"])
        # A ramp counts as carrying something even once the pain has gone --
        # an athlete mid-return is exactly who a coach must not push.
        if not status.reports and not status.plans:
            continue
        counts[status.action] = counts.get(status.action, 0) + 1
        carrying.append({
            "athlete_id": athlete["athlete_id"],
            "display_name": athlete["display_name"],
            "action": status.action,
            **{k: v for k, v in status.to_dict(include_notes=False).items()
               if k in ("open_reports", "blocked_tissues", "plans")},
        })

    carrying.sort(key=lambda a: -wellness_mod.Action.rank(a["action"]))
    return {"athletes": carrying, "counts": counts, "roster": len(athletes)}


@app.get("/api/sports")
def list_sports() -> dict[str, Any]:
    """The sports an athlete can say they play, for the picker.

    Public reference data, like the drill catalog. Seasons rather than hours,
    because a twelve-year-old can answer which seasons they play basketball
    and cannot answer how many hours a year.
    """
    return {
        "seasons": list(sports_mod.SEASONS),
        "sports": [s.to_dict() for s in sports_mod.CATALOG],
    }


@app.get("/api/me/sports")
def get_my_sports(
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return {"sports": store.athlete_sports(principal.id)}


@app.put("/api/me/sports")
def set_my_sports(
    body: AthleteSports,
    principal: Principal = Depends(_athlete),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Record what else this athlete plays.

    The athlete's own to set. It relaxes their specialisation gate and trims
    their weekly budget, so it is worth being clear that it is self-reported:
    a coach sees the list on the roster, which is the check that matters.
    """
    saved = store.set_athlete_sports(
        principal.id, [entry.model_dump() for entry in body.sports]
    )
    # Nested, not spread: Profile.to_dict() carries its own "sports" key and
    # spreading it silently replaced the ordered list we just saved.
    profile = benchmarks_mod.sport_profile(store.conn, principal.id)
    return {"sports": saved, "profile": profile.to_dict()}


@app.put("/api/athletes/{athlete_id}/sports")
def set_athlete_sports(
    athlete_id: int,
    body: AthleteSports,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Same, filled in by a coach -- usually from a roster form at signup."""
    owner = store.conn.execute(
        "SELECT org_id FROM users WHERE id = ?", (athlete_id,)
    ).fetchone()
    if owner is None or owner["org_id"] != principal.org_id:
        raise HTTPException(status_code=404, detail="unknown athlete")
    saved = store.set_athlete_sports(
        athlete_id, [entry.model_dump() for entry in body.sports]
    )
    profile = benchmarks_mod.sport_profile(store.conn, athlete_id)
    return {"sports": saved, "profile": profile.to_dict()}


class CreateFamily(BaseModel):
    family_name: str = Field(default="", max_length=200)
    parent_name: str = Field(min_length=1, max_length=120)
    email: str | None = None


class FamilyAthlete(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    dominant_hand: Literal["left", "right"] | None = None


@app.post("/api/family", status_code=201)
def create_family(body: CreateFamily, store: Store = Depends(get_store)) -> dict[str, Any]:
    """Set up a household with no club behind it.

    The parent ends up wearing both hats: director of their own small program,
    and guardian of their own children. Those are genuinely different roles --
    one sets the training, the other consents to it -- and they stay two
    records rather than one blurred super-role, so the consent checks keep
    meaning something even with the same person on both sides.
    """
    made = store.create_family(body.family_name, body.parent_name, body.email)
    return made


@app.post("/api/family/athletes", status_code=201)
def add_family_athlete(
    body: FamilyAthlete,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Add a child to a family account, guardian link and all."""
    if not store.is_family(principal.org_id):
        raise HTTPException(
            status_code=400,
            detail="that is a program account — add athletes from the coach dashboard",
        )
    team = store.conn.execute(
        "SELECT join_code FROM teams WHERE org_id = ? ORDER BY id LIMIT 1",
        (principal.org_id,),
    ).fetchone()
    try:
        return store.add_family_athlete(
            principal.org_id, principal.id, body.display_name,
            birth_year=body.birth_year, dominant_hand=body.dominant_hand,
            join_code=team["join_code"] if team else None,
        )
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class SiblingCompare(BaseModel):
    on: bool


@app.get("/api/family/board")
def family_board(
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """What a household sees instead of a leaderboard.

    Not a ranking by default. A club board works because forty athletes of
    roughly the same age are already competing for the same places; a
    household is a nine-year-old and a thirteen-year-old, and ranking them by
    reps says nothing except which of them is older.
    """
    if not store.is_family(principal.org_id):
        raise HTTPException(
            status_code=400,
            detail="that is a program account — the team leaderboard is at /leaderboard",
        )
    return store.family_board(principal.org_id)


@app.put("/api/family/board/compare")
def set_sibling_compare(
    body: SiblingCompare,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Turn the side-by-side view on or off.

    The parent's call, because parents know their own children. Even on, it
    compares consistency and form and never volume -- a younger sibling can
    win turning up and can win moving well, and cannot win reps against
    someone four years older.
    """
    try:
        return store.set_sibling_compare(principal.org_id, body.on)
    except StoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ProgramVoice(BaseModel):
    name: str = Field(default="", max_length=120)
    title: str = Field(default="", max_length=120)


@app.put("/api/coach/voice")
def set_program_voice(
    body: ProgramVoice,
    principal: Principal = Depends(_staff),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """Name the senior figure whose recognition carries extra weight.

    Directors only: whose name goes on a message to a child is a decision
    about the program, not about one team.
    """
    if not principal.is_director:
        raise HTTPException(
            status_code=403, detail="only a director can set the program voice",
        )
    return store.set_program_voice(principal.org_id, body.name, body.title)


@app.get("/api/sports/catalog")
def sports_catalog() -> dict[str, Any]:
    """Every sport a program can sign up as, for the signup dropdown.

    Public and unauthenticated: it is the list you need *before* you have an
    account. Each entry says whether positions are modelled for it, so the
    signup form can be honest rather than promising a position picker that
    turns out to be empty.
    """
    return {
        "sports": [
            {
                **sport.to_dict(),
                "positions": len(positions_mod.for_sport(sport.key)),
            }
            for sport in sports_mod.CATALOG
        ]
    }


@app.get("/api/positions")
def list_positions(
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    """The positions this org's sport actually models.

    Exists so the join form can offer a list instead of a text box. Free-text
    positions are normalised on read, but normalising a guess is repair work;
    a dropdown means there is nothing to repair. A sport with no position
    model returns an empty list, and the form falls back to free text rather
    than showing another sport's positions.
    """
    sport = _org_sport(store, principal.org_id)
    row = store.conn.execute(
        "SELECT position_emphasis_min_age FROM organizations WHERE id = ?",
        (principal.org_id,),
    ).fetchone()
    min_age = 15 if row is None or row[0] is None else int(row[0])
    return {
        "sport": sport,
        "positions": [p.to_dict() for p in positions_mod.for_sport(sport)],
        "position_emphasis_min_age": min_age,
        "applies_from": _specialisation_label(min_age),
        # So the join form can say what recording a position will and will not
        # do, instead of implying it changes training for everyone.
        "note": (
            "Position is recorded for every athlete. It shapes training "
            f"guidance from age {min_age}." if min_age < 99 else
            "Position is recorded for every athlete, and this program keeps "
            "all ages on the all-round training plan."
        ),
    }


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
