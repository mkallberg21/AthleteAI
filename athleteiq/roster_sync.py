"""Keeping a roster in step with wherever it actually lives.

The importer this builds on is forgiving and well tested, and it runs *once*.
Rosters do not hold still: a player joins in week three, another moves up an
age group in week five, and a coach who has to re-export a CSV every time is a
coach who stops bothering by half-term. That is the friction this closes.

Three decisions shape it.

**Providers produce rows; nothing else changes.** A provider's whole job is to
return the same shape the CSV parser already produces, so every bit of the
existing pipeline -- column detection, name normalisation, birth-year
inference, duplicate matching, claim codes -- is reused rather than
reimplemented per platform. Adding a platform is an adapter, not a fork.

**A departure is never automatic.** Somebody vanishing from a TeamSnap roster
is the one event continuous sync introduces that a one-off import never had,
and the tempting thing to do with it is delete. That would mean a coach
tidying their roster silently destroys a child's training history, and an API
hiccup that returns a short list does the same thing to everyone at once. So
departures are *reported*, never applied, and a human decides.

**Credentials are write-only.** A stored token reaches back into a system
holding children's contact details, so it goes in, is used, and never comes
out again -- not to the dashboard, not to an API response, not to a log line.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import roster as roster_mod

FETCH_TIMEOUT_SECONDS = 20
#: Enough for a large club, small enough that a runaway response cannot
#: exhaust memory on a modest host.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_ROWS = 5_000

#: A sync that would remove more than this share of a roster is refused
#: outright rather than reported. At that point the likeliest explanation is
#: a wrong team id or an API returning an empty page, not forty children
#: quitting overnight.
DEPARTURE_ALARM = 0.5


class SyncError(Exception):
    """Something went wrong that a coach can read and act on."""


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    #: What a coach has to paste in to connect it.
    credential_label: str
    #: What identifies the team within that platform.
    team_field: str
    help_url: str
    fetch: Callable[[str, str], list[dict[str, str]]]
    #: Whether the adapter has been exercised against the live service. None
    #: of the hosted ones have been, and saying so is not optional.
    verified: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "credential_label": self.credential_label,
            "team_field": self.team_field,
            "help_url": self.help_url,
            "verified": self.verified,
            "note": self.note,
        }


def _get(url: str, headers: dict[str, str] | None = None) -> bytes:
    """One GET, bounded in time and size.

    Bounded because the other end is somebody else's service: a hung
    connection or a response that keeps coming are both things a roster sync
    running on a cron must survive rather than inherit.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise SyncError("roster sources must be https")
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            return response.read(MAX_RESPONSE_BYTES + 1)[:MAX_RESPONSE_BYTES]
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SyncError(
                "That token was refused. It may have expired, or it may not "
                "have permission to read this team."
            ) from exc
        if exc.code == 404:
            raise SyncError("That team id was not found on their side.") from exc
        raise SyncError(f"Their server returned {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise SyncError(f"Could not reach them: {exc.reason}") from exc


def _rows_from_json(
    payload: Any, mapping: dict[str, str], container: str | None = None
) -> list[dict[str, str]]:
    """Pull roster rows out of a JSON body into the CSV parser's own shape.

    Deliberately tolerant about where the list lives, because these APIs wrap
    their collections differently and a sync that dies on an envelope change
    is a sync that dies.
    """
    data = payload
    if container and isinstance(payload, dict):
        data = payload.get(container, payload)
    if isinstance(data, dict):
        for key in ("data", "items", "results", "members", "users"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise SyncError("Their response did not contain a list of people.")

    rows: list[dict[str, str]] = []
    for entry in data[:MAX_ROWS]:
        if not isinstance(entry, dict):
            continue
        row: dict[str, str] = {}
        for ours, theirs in mapping.items():
            value = entry
            for part in theirs.split("."):
                value = value.get(part) if isinstance(value, dict) else None
                if value is None:
                    break
            if value not in (None, ""):
                row[ours] = str(value)
        if row:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Adapters
#
# Written against each platform's published API shape. None has been run
# against a live account from here -- there are no credentials to do that with
# -- so each is marked unverified, and the connect screen says so rather than
# letting a coach discover it. The field mappings are the part most likely to
# need a small correction on first contact with a real response.
# ---------------------------------------------------------------------------

def _teamsnap(token: str, team_id: str) -> list[dict[str, str]]:
    body = _get(
        "https://api.teamsnap.com/v3/members/search?"
        + urllib.parse.urlencode({"team_id": team_id}),
        {"Authorization": f"Bearer {token}", "Accept": "application/vnd.collection+json"},
    )
    payload = json.loads(body)
    # TeamSnap speaks Collection+JSON: items carry a flat list of name/value
    # pairs rather than an object, so it is flattened before mapping.
    collection = payload.get("collection", {}) if isinstance(payload, dict) else {}
    flattened = []
    for item in collection.get("items", []):
        entry = {
            field.get("name"): field.get("value")
            for field in item.get("data", [])
            if isinstance(field, dict)
        }
        flattened.append(entry)
    return _rows_from_json(
        flattened,
        {
            "first_name": "first_name",
            "last_name": "last_name",
            "jersey": "jersey_number",
            "birth_date": "birthday",
            "email": "email",
            "position": "position",
            "external_id": "id",
        },
    )


def _sportsengine(token: str, team_id: str) -> list[dict[str, str]]:
    body = _get(
        f"https://api.sportngin.com/v3/teams/{urllib.parse.quote(team_id)}/members",
        {"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    return _rows_from_json(
        json.loads(body),
        {
            "first_name": "first_name",
            "last_name": "last_name",
            "jersey": "jersey",
            "birth_date": "date_of_birth",
            "email": "email",
            "position": "position",
            "guardian_email": "guardian.email",
            "guardian_name": "guardian.name",
            "external_id": "id",
        },
        container="members",
    )


def _csv_url(token: str, url: str) -> list[dict[str, str]]:
    """Any platform that can hand out an export link.

    The universal fallback, and the one adapter here that is genuinely
    verified, because it goes through the same parser the upload button does.
    Most roster tools can produce a link like this even when their API is
    closed, behind a paywall, or simply not worth a bespoke adapter.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    text = _get(url, headers).decode("utf-8-sig", errors="replace")
    plan = roster_mod.parse(text)
    if plan.file_problems:
        raise SyncError("; ".join(plan.file_problems))
    rows = []
    for athlete in plan.athletes:
        row = {
            "name": athlete.display_name,
            "jersey": athlete.jersey,
            "position": athlete.position,
        }
        if athlete.birth_year:
            row["birth_year"] = str(athlete.birth_year)
        if athlete.email:
            row["email"] = athlete.email
        if athlete.guardian_email:
            row["guardian_email"] = athlete.guardian_email
        if athlete.external_id:
            row["external_id"] = athlete.external_id
        rows.append(row)
    return rows


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        key="teamsnap",
        label="TeamSnap",
        credential_label="Personal access token",
        team_field="TeamSnap team ID",
        help_url="https://auth.teamsnap.com/oauth/applications",
        fetch=_teamsnap,
        note=(
            "Written against TeamSnap's published v3 API. Not yet run against "
            "a live account, so treat the first sync as a dry run."
        ),
    ),
    Provider(
        key="sportsengine",
        label="SportsEngine",
        credential_label="API token",
        team_field="SportsEngine team ID",
        help_url="https://developer.sportsengine.com/",
        fetch=_sportsengine,
        note=(
            "Written against the SportsEngine/Sport Ngin v3 API. Not yet run "
            "against a live account, so treat the first sync as a dry run."
        ),
    ),
    Provider(
        key="csv_url",
        label="Any platform, via export link",
        credential_label="Token, if the link needs one (optional)",
        team_field="Export URL",
        help_url="",
        fetch=_csv_url,
        verified=True,
        note=(
            "Works with anything that can produce a CSV link — Stack Sports, "
            "LeagueApps, Sports Connect, a school export, a shared sheet. "
            "Goes through the same parser as the upload button, which is why "
            "this is the one adapter that is actually proven."
        ),
    ),
)

BY_KEY = {p.key: p for p in PROVIDERS}


def rows_to_csv(rows: list[dict[str, str]]) -> str:
    """Feed provider rows back through the parser the upload button uses.

    Round-tripping through CSV rather than constructing `Athlete` records
    directly is deliberate: it means a synced roster and an uploaded one take
    exactly the same path, so the forgiving header detection, the name
    handling and every warning a coach already trusts apply unchanged.
    """
    if not rows:
        return ""
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    lines = [",".join(columns)]
    for row in rows:
        cells = []
        for key in columns:
            value = str(row.get(key, "")).replace('"', '""')
            cells.append(f'"{value}"' if ("," in value or '"' in value) else value)
        lines.append(",".join(cells))
    return "\n".join(lines)


@dataclass
class Departure:
    athlete_id: int
    display_name: str

    def to_dict(self) -> dict[str, Any]:
        return {"athlete_id": self.athlete_id, "display_name": self.display_name}


@dataclass
class SyncResult:
    provider: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    departures: list[Departure] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = True
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "fetched": self.fetched,
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "departures": [d.to_dict() for d in self.departures],
            "warnings": list(self.warnings),
            "dry_run": self.dry_run,
            "error": self.error,
            "ok": not self.error,
        }


def find_departures(
    conn: sqlite3.Connection, team_id: int, seen_names: set[str]
) -> list[Departure]:
    """Who is on our roster and not on theirs.

    Reported and never applied. A coach tidying their TeamSnap roster must not
    silently destroy a child's training history, and an API returning a short
    page must not do it to the whole squad at once.
    """
    out = []
    for row in conn.execute(
        "SELECT u.id, u.display_name FROM team_members tm "
        "JOIN users u ON u.id = tm.user_id "
        "WHERE tm.team_id = ? AND u.role = 'athlete' AND u.active = 1",
        (team_id,),
    ):
        if roster_mod.match_key(row["display_name"]) not in seen_names:
            out.append(Departure(int(row["id"]), row["display_name"]))
    return out


def run_due(store, *, older_than_hours: int = 12, limit: int = 200) -> dict[str, int]:
    """Sync every link a coach has put on a schedule. Called from cron.

    One failing link must not stop the rest: a token that has expired on one
    team is a normal Tuesday, and it is not a reason for the other nineteen
    teams to go stale. Failures are recorded on the link, where the coach who
    owns that team will see them, rather than raised here where nobody will.
    """
    ran = failed = 0
    for org_id, team_id, provider in store.due_roster_syncs(older_than_hours)[:limit]:
        try:
            result = store.sync_roster(org_id, team_id, provider, dry_run=False)
        except Exception:  # noqa: BLE001 - one bad link must not stop the sweep
            failed += 1
            continue
        ran += 1
        if not result.get("ok"):
            failed += 1
    return {"ran": ran, "failed": failed}
