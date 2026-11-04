"""TeamSnap, connected the way TeamSnap wants: the director signs in to
TeamSnap once, says yes, and his teams appear here.

Why OAuth and not "paste the roster URL": the roster page is a roster only
to a browser that is signed in as him. Reading it from our server would
mean holding his TeamSnap password, which is against their terms, breaks on
their next redesign, and is not something a parent wants between their kid
and a stranger's stored credential. The API path is the same idea done
properly -- a token scoped to read, issued to this app, revocable by him.

Shape:
  GET  /api/teamsnap/connect   -> redirect to TeamSnap's consent screen
  GET  /api/teamsnap/callback  -> code -> access token, stored on the org
  GET  /api/teamsnap/teams     -> the teams that account can see
  then the existing roster link (provider=teamsnap) with that token.

Collection+JSON (TeamSnap v3) is flattened once in `items()`; everything
else works on plain dicts. Parents live on separate `contacts` rows, with
their email addresses and phone numbers on separate rows again
(`contact_email_addresses`, `contact_phone_numbers`), so a roster pull is
four requests, joined here by member id.
"""

from __future__ import annotations

import hmac
import hashlib
import json
import secrets
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import Any

AUTH_URL = "https://auth.teamsnap.com/oauth/authorize"
TOKEN_URL = "https://auth.teamsnap.com/oauth/token"
API = "https://api.teamsnap.com/v3"
ACCEPT = "application/vnd.collection+json"
TIMEOUT = 20
MAX_BYTES = 8 * 1024 * 1024
#: A consent round-trip that takes longer than this is not the same person.
STATE_TTL_SECONDS = 15 * 60


class TeamSnapError(Exception):
    """Something TeamSnap said, in words a director can act on."""


# ---------------------------------------------------------------- OAuth


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "read",
        "state": state,
    })


def make_state(secret: str, org_id: int, user_id: int) -> str:
    """Signed, time-stamped: ties the callback to the director who clicked
    Connect, so a stray callback cannot attach a token to someone else's
    program."""
    nonce = secrets.token_urlsafe(12)
    body = f"{org_id}.{user_id}.{int(time.time())}.{nonce}"
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def read_state(secret: str, state: str) -> tuple[int, int]:
    try:
        org_s, user_s, ts_s, nonce, sig = state.split(".")
    except ValueError as exc:
        raise TeamSnapError("that connection attempt is not recognised; start again") from exc
    body = f"{org_s}.{user_s}.{ts_s}.{nonce}"
    want = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(want, sig):
        raise TeamSnapError("that connection attempt is not recognised; start again")
    if time.time() - int(ts_s) > STATE_TTL_SECONDS:
        raise TeamSnapError("that connection attempt expired; start again")
    return int(org_s), int(user_s)


def exchange_code(client_id: str, client_secret: str, redirect_uri: str, code: str) -> dict[str, Any]:
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "code": code,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            payload = json.loads(r.read(MAX_BYTES))
    except urllib.error.HTTPError as exc:
        raise TeamSnapError(f"TeamSnap refused the sign-in ({exc.code}); try connecting again") from exc
    except urllib.error.URLError as exc:
        raise TeamSnapError(f"could not reach TeamSnap: {exc.reason}") from exc
    if "access_token" not in payload:
        raise TeamSnapError("TeamSnap did not return a token; try connecting again")
    return payload


# ---------------------------------------------------------------- API


def _get(token: str, path: str, **params: Any) -> dict[str, Any]:
    url = path if path.startswith("https://") else API + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": ACCEPT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read(MAX_BYTES))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise TeamSnapError("TeamSnap no longer accepts this connection; connect again") from exc
        if exc.code == 404:
            raise TeamSnapError("that team was not found on TeamSnap") from exc
        raise TeamSnapError(f"TeamSnap returned {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise TeamSnapError(f"could not reach TeamSnap: {exc.reason}") from exc


def items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Collection+JSON items -> plain dicts. Links are kept under '_links'."""
    out = []
    for item in (payload.get("collection") or {}).get("items") or []:
        entry: dict[str, Any] = {}
        for f in item.get("data") or []:
            if isinstance(f, dict) and "name" in f:
                entry[f["name"]] = f.get("value")
        entry["_links"] = {l.get("rel"): l.get("href") for l in item.get("links") or [] if isinstance(l, dict)}
        out.append(entry)
    return out


def me(token: str) -> dict[str, Any]:
    rows = items(_get(token, "/me"))
    if not rows:
        raise TeamSnapError("TeamSnap did not say who this is")
    return rows[0]


def teams(token: str) -> list[dict[str, Any]]:
    """Every team the signed-in account belongs to, newest season first."""
    user = me(token)
    rows = items(_get(token, "/teams/search", user_id=user["id"]))
    rows.sort(key=lambda t: (t.get("season_name") or "", t.get("name") or ""), reverse=True)
    return [{
        "id": str(t["id"]),
        "name": t.get("name") or "",
        "season": t.get("season_name") or "",
        "sport_id": t.get("sport_id"),
        "member_count": t.get("member_count"),
    } for t in rows]


def roster(token: str, team_id: str) -> list[dict[str, str]]:
    """The players on a team with their parents' names, emails and phones,
    in the shape the roster importer already reads.

    Non-players (coaches, managers, the director himself) are left out:
    `is_non_player` is TeamSnap's own flag for them. A parent is any contact
    row for the member; the first with an email is Parent 1, the next
    Parent 2. The member's own email is used only when there is no contact
    with one -- an older kid who manages his own TeamSnap.
    """
    members = items(_get(token, "/members/search", team_id=team_id))
    contacts = items(_get(token, "/contacts/search", team_id=team_id))
    emails = items(_get(token, "/contact_email_addresses/search", team_id=team_id))
    phones = items(_get(token, "/contact_phone_numbers/search", team_id=team_id))

    email_by_contact: dict[str, list[str]] = {}
    for e in emails:
        if e.get("email"):
            email_by_contact.setdefault(str(e.get("contact_id")), []).append(str(e["email"]))
    phone_by_contact: dict[str, list[str]] = {}
    for p in phones:
        if p.get("phone_number"):
            phone_by_contact.setdefault(str(p.get("contact_id")), []).append(str(p["phone_number"]))
    contacts_by_member: dict[str, list[dict[str, Any]]] = {}
    for c in contacts:
        contacts_by_member.setdefault(str(c.get("member_id")), []).append(c)

    rows: list[dict[str, str]] = []
    for m in members:
        if m.get("is_non_player") or m.get("is_manager") or m.get("is_owner"):
            continue
        mid = str(m.get("id"))
        row: dict[str, str] = {
            "first_name": str(m.get("first_name") or ""),
            "last_name": str(m.get("last_name") or ""),
            "jersey": str(m.get("jersey_number") or ""),
            "birth_date": str(m.get("birthday") or ""),
            "position": str(m.get("position") or ""),
            "external_id": mid,
        }
        # Parents: contact rows with an email, in TeamSnap's order.
        parents = []
        for c in contacts_by_member.get(mid, []):
            cid = str(c.get("id"))
            em = email_by_contact.get(cid, [])
            ph = phone_by_contact.get(cid, [])
            name = " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x) or ""
            if em or ph:
                parents.append((name, em[0] if em else "", ph[0] if ph else ""))
        if parents:
            row["guardian_name"], row["guardian_email"], row["guardian_phone"] = parents[0]
            if len(parents) > 1:
                row["guardian2_name"], row["guardian2_email"], row["guardian2_phone"] = parents[1]
        elif m.get("email"):
            row["email"] = str(m["email"])
        rows.append({k: v for k, v in row.items() if v})
    return rows
