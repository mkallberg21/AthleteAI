"""One-time TeamSnap consent for verifying the adapter against a real team.

Opens nothing itself: prints the URL for the user to open. Catches the
callback on localhost, exchanges the code, then pulls the real roster for
the given team id through offdays.teamsnap and prints what came back with
emails/phones masked. The token is kept in memory only.

  python scripts/teamsnap_probe.py <team_id>
  env: TS_CLIENT_ID, TS_CLIENT_SECRET
"""

from __future__ import annotations

import http.server
import json
import os
import sys
import threading
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from offdays import teamsnap  # noqa: E402

CLIENT_ID = os.environ["TS_CLIENT_ID"]
CLIENT_SECRET = os.environ["TS_CLIENT_SECRET"]
REDIRECT = os.environ.get("TS_REDIRECT", "http://localhost:8787/callback")
TEAM = sys.argv[1] if len(sys.argv) > 1 else ""

got: dict[str, str] = {}
done = threading.Event()


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        got.update({k: v[0] for k, v in q.items()})
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h2>Connected. You can close this tab.</h2>")
        done.set()


def mask(s: str) -> str:
    if "@" in s:
        a, b = s.split("@", 1)
        return a[:1] + "***@" + b
    digits = "".join(ch for ch in s if ch.isdigit())
    return "***" + digits[-4:] if digits else s


def main():
    srv = http.server.HTTPServer(("127.0.0.1", 8787), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("OPEN THIS:", teamsnap.authorize_url(CLIENT_ID, REDIRECT, "probe"))
    print("waiting for the callback (10 min)...", flush=True)
    if not done.wait(600):
        print("no callback"); return
    srv.shutdown()
    if "code" not in got:
        print("callback without a code:", got); return
    tok = teamsnap.exchange_code(CLIENT_ID, CLIENT_SECRET, REDIRECT, got["code"])
    token = tok["access_token"]
    print("token: [REDACTED] scope=", tok.get("scope"), "expires_in=", tok.get("expires_in"))

    u = teamsnap.me(token)
    print("me:", {k: u.get(k) for k in ("id", "first_name", "last_name")}, "email:", mask(str(u.get("email") or "")))
    ts = teamsnap.teams(token)
    print(f"teams ({len(ts)}):")
    for t in ts[:20]:
        print("  ", t)
    team = TEAM or (ts[0]["id"] if ts else "")
    if not team:
        return
    print("raw member keys:", sorted(teamsnap.items(teamsnap._get(token, "/members/search", team_id=team))[0].keys())[:60])
    c = teamsnap.items(teamsnap._get(token, "/contacts/search", team_id=team))
    print("contacts:", len(c), "keys:", sorted(c[0].keys())[:40] if c else "-")
    e = teamsnap.items(teamsnap._get(token, "/contact_email_addresses/search", team_id=team))
    print("contact emails:", len(e), "keys:", sorted(e[0].keys())[:30] if e else "-")
    p = teamsnap.items(teamsnap._get(token, "/contact_phone_numbers/search", team_id=team))
    print("contact phones:", len(p), "keys:", sorted(p[0].keys())[:30] if p else "-")
    rows = teamsnap.roster(token, team)
    print(f"ROSTER for {team}: {len(rows)} players")
    with_email = sum(1 for r in rows if r.get("guardian_email"))
    with_phone = sum(1 for r in rows if r.get("guardian_phone"))
    print(f"  with parent email: {with_email}  with parent phone: {with_phone}")
    for r in rows[:40]:
        print("  ", r.get("first_name"), r.get("last_name", "")[:1] + ".", "| #", r.get("jersey", ""), "| b", r.get("birth_date", ""),
              "| P1", r.get("guardian_name", ""), mask(r.get("guardian_email", "")), mask(r.get("guardian_phone", "")),
              "| P2", r.get("guardian2_name", ""), mask(r.get("guardian2_email", "")), mask(r.get("guardian2_phone", "")))
    # Non-player members, so we can see the filter did its job
    allm = teamsnap.items(teamsnap._get(token, "/members/search", team_id=team))
    print("non-players skipped:", [(m.get("first_name"), m.get("is_non_player"), m.get("is_manager")) for m in allm if m.get("is_non_player") or m.get("is_manager")])


if __name__ == "__main__":
    main()
