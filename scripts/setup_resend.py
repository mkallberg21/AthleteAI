#!/usr/bin/env python3
"""Set up outbound mail for 0FFDAYS through Resend, end to end.

Runs on k6-server (or anywhere with the two tokens). Idempotent: every step
checks before it acts, so re-running after a DNS wait or a failure picks up
where it left off.

    RESEND_API_KEY=re_...  CLOUDFLARE_API_TOKEN=...  python3 scripts/setup_resend.py
    python3 scripts/setup_resend.py --status          # just report
    python3 scripts/setup_resend.py --test you@x.com  # send one test mail

Steps:
  1. Add mail.0ffdays.com to Resend (or find it). Region us-east-1.
  2. Push the DKIM / SPF (MX+TXT on send.) records Resend asks for into the
     Cloudflare zone for 0ffdays.com, plus a DMARC record. DNS only, no proxy.
  3. Ask Resend to verify, poll until it does (DNS can take minutes).
  4. Write OFFDAYS_SMTP_* into ~/offdays/infra/.env.prod (mode 600, in place;
     other keys untouched).
  5. Recreate the app container so it reads the new env.
  6. Optionally send a test message through the app's own mailer.

Tokens are read from the environment only. Nothing here prints them.
Resend key must be a full-access key (a "sending only" key cannot manage
domains). Cloudflare token needs Zone:DNS:Edit on 0ffdays.com.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

DOMAIN = "mail.0ffdays.com"
ZONE = "0ffdays.com"
REGION = "us-east-1"
ENV_PATH = os.path.expanduser("~/offdays/infra/.env.prod")
DMARC_RUA = os.environ.get("DMARC_RUA", "")  # e.g. mailto:you@example.com


def _req(url: str, token: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        payload = e.read().decode(errors="replace")
        raise SystemExit(f"{method} {url} -> {e.code}: {payload[:400]}") from None


# ---------------------------------------------------------------- Resend

def resend_domain(key: str) -> dict:
    found = [d for d in _req("https://api.resend.com/domains", key).get("data", [])
             if d["name"] == DOMAIN]
    if found:
        d = _req(f"https://api.resend.com/domains/{found[0]['id']}", key)
        print(f"resend: {DOMAIN} exists, status={d['status']}")
        return d
    d = _req("https://api.resend.com/domains", key, "POST", {"name": DOMAIN, "region": REGION})
    print(f"resend: added {DOMAIN} ({REGION}), status={d['status']}")
    return _req(f"https://api.resend.com/domains/{d['id']}", key)


def resend_verify(key: str, domain_id: str, wait_s: int = 600) -> str:
    _req(f"https://api.resend.com/domains/{domain_id}/verify", key, "POST")
    deadline = time.time() + wait_s
    while True:
        d = _req(f"https://api.resend.com/domains/{domain_id}", key)
        status = d["status"]
        bad = [r for r in d.get("records", []) if r.get("status") not in ("verified",)]
        print(f"resend: status={status}" + (f", {len(bad)} record(s) pending" if bad else ""))
        if status == "verified" or time.time() > deadline:
            return status
        time.sleep(20)


# ------------------------------------------------------------ Cloudflare

def cf_zone_id(token: str) -> str:
    z = _req(f"https://api.cloudflare.com/client/v4/zones?name={ZONE}", token)
    if not z.get("result"):
        raise SystemExit(f"cloudflare: zone {ZONE} not found with this token")
    return z["result"][0]["id"]


def cf_records(token: str, zone: str) -> list[dict]:
    out, page = [], 1
    while True:
        r = _req(f"https://api.cloudflare.com/client/v4/zones/{zone}/dns_records?per_page=100&page={page}", token)
        out += r["result"]
        if page >= r["result_info"]["total_pages"]:
            return out
        page += 1


def cf_upsert(token: str, zone: str, existing: list[dict], rec: dict) -> None:
    """Create or update one record. Match on (type, name) and, for TXT with
    several values at one name, on content prefix (v=spf1 / v=DMARC1 / p=)."""
    name = rec["name"].rstrip(".")
    same = [e for e in existing if e["type"] == rec["type"] and e["name"].rstrip(".") == name]
    if rec["type"] == "TXT" and same:
        head = rec["content"].split(";")[0].split("=")[0]
        same = [e for e in same if e["content"].strip('"').split(";")[0].split("=")[0] == head]
    body = {k: rec[k] for k in ("type", "name", "content", "ttl") if k in rec}
    body.setdefault("ttl", 1)
    body["proxied"] = False
    if rec["type"] == "MX":
        body["priority"] = rec.get("priority", 10)
    if same:
        cur = same[0]
        unchanged = (cur["content"].strip('"') == rec["content"].strip('"')
                     and (rec["type"] != "MX" or cur.get("priority") == body["priority"]))
        if unchanged:
            print(f"cloudflare: {rec['type']} {name} already set")
            return
        _req(f"https://api.cloudflare.com/client/v4/zones/{zone}/dns_records/{cur['id']}", token, "PUT", body)
        print(f"cloudflare: updated {rec['type']} {name}")
    else:
        _req(f"https://api.cloudflare.com/client/v4/zones/{zone}/dns_records", token, "POST", body)
        print(f"cloudflare: created {rec['type']} {name}")


def push_dns(cf_token: str, resend_domain: dict) -> None:
    zone = cf_zone_id(cf_token)
    existing = cf_records(cf_token, zone)
    for r in resend_domain.get("records", []):
        # Click-tracking CNAME is optional and rewrites links in mail, which
        # a parent invite should not have. Skip it; the others are required.
        if r.get("record") == "Tracking":
            continue
        # SPF and DKIM names come back relative to the sending domain
        # ("send", "resend._domainkey"); make them FQDNs for Cloudflare.
        name = r["name"]
        if not name.endswith(ZONE):
            name = f"{name}.{DOMAIN}"
        rec = {"type": r["type"], "name": name, "content": r["value"].strip('"'), "ttl": 1}
        if r["type"] == "MX":
            rec["priority"] = int(r.get("priority", 10))
        cf_upsert(cf_token, zone, existing, rec)
    dmarc = "v=DMARC1; p=none" + (f"; rua={DMARC_RUA}" if DMARC_RUA else "")
    cf_upsert(cf_token, zone, existing, {"type": "TXT", "name": f"_dmarc.{DOMAIN}", "content": dmarc, "ttl": 1})


# ------------------------------------------------------------ env + deploy

def write_env(key: str) -> None:
    if not os.path.exists(ENV_PATH):
        raise SystemExit(f"{ENV_PATH} missing; create it from infra/.env.prod.example")
    with open(ENV_PATH, encoding="utf-8") as f:
        lines = f.read().splitlines()
    want = {
        "OFFDAYS_SMTP_HOST": "smtp.resend.com",
        "OFFDAYS_SMTP_PORT": "587",
        "OFFDAYS_SMTP_USER": "resend",
        "OFFDAYS_SMTP_PASSWORD": key,
        "OFFDAYS_SMTP_FROM": f"0FFDAYS <no-reply@{DOMAIN}>",
    }
    seen = set()
    out = []
    for line in lines:
        m = re.match(r"^([A-Z0-9_]+)=", line)
        if m and m.group(1) in want:
            out.append(f"{m.group(1)}={want[m.group(1)]}")
            seen.add(m.group(1))
        else:
            out.append(line)
    for k, v in want.items():
        if k not in seen:
            out.append(f"{k}={v}")
    tmp = ENV_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ENV_PATH)
    print(f"env: wrote OFFDAYS_SMTP_* to {ENV_PATH}")


def redeploy() -> None:
    infra = os.path.expanduser("~/offdays/infra")
    cmd = ["podman-compose", "--env-file", ".env.prod", "-f", "compose.prod.yaml",
           "up", "-d", "--force-recreate", "app"]
    print("deploy: recreating app container")
    subprocess.run(cmd, cwd=infra, check=True)


def send_test(to: str) -> None:
    code = (
        "from offdays.db import connect, init_db; from offdays import mailer; "
        "c = connect(); init_db(c); "
        f"mailer.enqueue(c, to_email={to!r}, subject='0FFDAYS mail is live', "
        "html='<p>If you can read this, parent invites will arrive.</p>', "
        "text='If you can read this, parent invites will arrive.', "
        "kind=mailer.Kind.TRANSACTIONAL, dedupe_key='setup-test-' + __import__('time').strftime('%s')); "
        "print(mailer.flush(c))"
    )
    subprocess.run(["podman", "exec", "offdays_app_1", "python", "-c", code], check=True)


def status(resend_key: str | None) -> None:
    if resend_key:
        try:
            d = resend_domain(resend_key)
            for r in d.get("records", []):
                print(f"  {r['type']:4} {r['name']:45} {r.get('status','?')}")
        except SystemExit as e:
            print(f"resend: {e}")
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            host = next((l.split("=", 1)[1] for l in f if l.startswith("OFFDAYS_SMTP_HOST=")), "")
        print(f"env: OFFDAYS_SMTP_HOST={host or '(blank)'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--test", metavar="EMAIL")
    ap.add_argument("--no-deploy", action="store_true")
    ap.add_argument("--wait", type=int, default=600, help="seconds to wait for verification")
    args = ap.parse_args()

    resend_key = os.environ.get("RESEND_API_KEY")
    cf_token = os.environ.get("CLOUDFLARE_API_TOKEN")

    if args.status:
        status(resend_key)
        return 0
    if args.test:
        send_test(args.test)
        return 0
    if not resend_key or not resend_key.startswith("re_"):
        raise SystemExit("RESEND_API_KEY (full access) is required")
    if not cf_token:
        raise SystemExit("CLOUDFLARE_API_TOKEN (Zone:DNS:Edit on 0ffdays.com) is required")

    d = resend_domain(resend_key)
    push_dns(cf_token, d)
    final = resend_verify(resend_key, d["id"], args.wait)
    if final != "verified":
        print(f"resend: still {final}. DNS may need longer; re-run later. Env not written.")
        return 1
    write_env(resend_key)
    if not args.no_deploy:
        redeploy()
    print("done. Try: python3 scripts/setup_resend.py --test you@example.com")
    return 0


if __name__ == "__main__":
    sys.exit(main())
