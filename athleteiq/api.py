"""HTTP API for AthleteIQ.

Nothing here accepts video, image data, or pose landmarks. The capture app
sends counts and timings only; there is no endpoint that could receive footage
even if a future client tried to send it.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import CONFIG
from .drills import ALL_DRILLS, DRILLS_BY_KEY
from .leaderboard import coach_roster, leaderboard, team_standings
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
    store: Store = Depends(get_store),
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        return store.authenticate(token)
    except StoreError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _staff(principal: Principal = Depends(_principal)) -> Principal:
    if not principal.is_staff:
        raise HTTPException(status_code=403, detail="coach or director role required")
    return principal


@app.exception_handler(StoreError)
async def _store_error_handler(_request, exc: StoreError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


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
    principal: Principal = Depends(_principal),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return store.start_session(principal.id, body.drill_key)


class RepPayload(BaseModel):
    t_ms: int = Field(ge=0)
    hand: Literal["left", "right", "none"] = "none"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


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


@app.post("/api/sessions/submit")
def submit_session(
    body: SubmitSessionRequest,
    principal: Principal = Depends(_principal),
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
    if principal.id != athlete_id and not principal.is_staff:
        raise HTTPException(status_code=403, detail="not permitted")
    return store.athlete_profile(athlete_id)


# ----------------------------------------------------------------------
# Leaderboards
# ----------------------------------------------------------------------

@app.get("/api/leaderboard")
def get_leaderboard(
    board: Literal["xp", "offhand", "streak", "reps", "improvement"] = "xp",
    window: Literal["week", "month", "season", "all"] = "week",
    team_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(_principal),
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


@app.get("/api/standings")
def get_standings(
    window: Literal["week", "month", "season", "all"] = "week",
    principal: Principal = Depends(_principal),
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
    return {
        "window": window,
        "team_id": team_id,
        "athletes": coach_roster(store.conn, principal.org_id, team_id, window),
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
    return {"teams": [dict(r) for r in rows]}


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
