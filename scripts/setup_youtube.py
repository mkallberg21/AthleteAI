#!/usr/bin/env python3
"""Switch on the weekly video scan: asks for a YouTube Data API key and writes it to the server.

Run this ON THE SERVER (ssh k6-server first; the prompt must say jason@k6-prod-server):

    cd ~/offdays
    python3 scripts/setup_youtube.py

It asks for the key itself at a hidden prompt: nothing shows as you paste, then press Enter. Never paste
the key into chat, a terminal command line, or a file you commit. It only touches the one line
OFFDAYS_YOUTUBE_API_KEY in ~/offdays/infra/.env.prod (mode 600), checks the key with one tiny request,
and restarts the app container so it is read. It prints how long the key is, never what it is.

Getting a key (about five minutes, free):
  1. console.cloud.google.com -> create a project (any name, e.g. "0FFDAYS").
  2. APIs & Services -> Library -> "YouTube Data API v3" -> Enable.
  3. APIs & Services -> Credentials -> Create credentials -> API key.
  4. Edit the key -> API restrictions -> Restrict key -> choose only "YouTube Data API v3". Save.
     (Do NOT add an application/website restriction: the server calls from its own address.)

The free quota is 10,000 units a day. One weekly scan uses about 1,300.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ENV_PATH = os.path.expanduser("~/offdays/infra/.env.prod")
LINE = "OFFDAYS_YOUTUBE_API_KEY"


def looks_like_key(value: str) -> bool:
    """Google API keys start AIza and are 39 characters. A Resend or Stripe key is not one."""
    return bool(re.fullmatch(r"AIza[0-9A-Za-z_\-]{35}", value))


def ask() -> str:
    for _ in range(5):
        value = getpass.getpass("YouTube API key (paste, then Enter; nothing will show): ").strip()
        if not value:
            print("  Nothing was pasted. Copy the key first, then paste and press Enter.")
        elif not looks_like_key(value):
            print(f"  That is {len(value)} characters and does not look like a Google API key (it starts AIza, 39 characters).")
        else:
            print(f"  Got it ({len(value)} characters).")
            return value
    raise SystemExit("No key entered. Run it again when the key is copied.")


def check(key: str) -> str:
    """One cheap call (videos.list, 1 unit). Returns '' if the key works, else a reason with no key in it."""
    url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(
        {"part": "id", "id": "dQw4w9WgXcQ", "key": key})
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            json.loads(resp.read().decode("utf-8"))
        return ""
    except urllib.error.HTTPError as exc:
        try:
            errors = json.loads(exc.read().decode("utf-8")).get("error", {}).get("errors", [])
            reason = errors[0].get("reason", f"http {exc.code}") if errors else f"http {exc.code}"
        except Exception:  # noqa: BLE001
            reason = f"http {exc.code}"
        hints = {"keyInvalid": "Google says the key is not valid. Copy it again from Credentials.",
                 "accessNotConfigured": "The YouTube Data API v3 is not enabled for the project that owns this key.",
                 "ipRefererBlocked": "The key has a website/IP restriction. Remove it (keep only the API restriction)."}
        return hints.get(reason, f"Google refused it: {reason}")
    except Exception:  # noqa: BLE001
        return "Could not reach Google from here. Check the server's internet and run again."


def write_env(key: str) -> None:
    if not os.path.exists(ENV_PATH):
        raise SystemExit(f"{ENV_PATH} missing; create it from infra/.env.prod.example")
    with open(ENV_PATH, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out, seen = [], False
    for line in lines:
        if re.match(rf"^{LINE}=", line):
            out.append(f"{LINE}={key}")
            seen = True
        else:
            out.append(line)
    if not seen:
        out.append(f"{LINE}={key}")
    tmp = ENV_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ENV_PATH)
    print(f"env: wrote {LINE} to {ENV_PATH} (mode 600)")


def redeploy() -> None:
    infra = os.path.expanduser("~/offdays/infra")
    cmd = ["podman-compose", "--env-file", ".env.prod", "-f", "compose.prod.yaml", "up", "-d", "--force-recreate", "app"]
    print("deploy: recreating the app container so it reads the key")
    subprocess.run(cmd, cwd=infra, check=True)


def main() -> int:
    if "--status" in sys.argv:
        have = False
        if os.path.exists(ENV_PATH):
            with open(ENV_PATH, encoding="utf-8") as f:
                have = any(re.match(rf"^{LINE}=.+", l) for l in f)
        print(f"{LINE}: {'set' if have else 'not set'}")
        return 0
    key = ask()
    problem = check(key)
    if problem:
        print("The key did not work: " + problem)
        return 1
    print("Google accepted the key.")
    write_env(key)
    redeploy()
    print("done. Try it now: podman exec offdays_app_1 python scripts/run_video_scout.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
