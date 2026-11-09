#!/usr/bin/env python3
"""Switch on the operator dashboard and connect Stripe. Run on the server.

    cd ~/offdays
    python3 scripts/setup_stripe.py            # full setup, asks for each value
    python3 scripts/setup_stripe.py --key-only # just make the operator key

Nothing is passed on the command line and nothing is echoed: Stripe's secret
key and the webhook secret are typed at hidden prompts, so they never reach your
shell history, this chat, or the repo. The script writes them to
~/offdays/infra/.env.prod (mode 600) and recreates the app container.

What it does
  1. Makes a long random OPERATOR KEY, prints it ONCE, and stores only its
     SHA-256 hash. Lose it and you simply run --key-only again.
  2. Asks for your Stripe secret key (restricted key, "rk_..." preferred) and
     writes it. Use a TEST key first.
  3. Asks for the webhook signing secret ("whsec_...") and writes it.
  4. Recreates the app so the new settings take effect.

The dashboard is then at  https://app.0ffdays.com/admin
"""
from __future__ import annotations

import getpass
import hashlib
import os
import re
import secrets
import subprocess
import sys

ENV_PATH = os.path.expanduser("~/offdays/infra/.env.prod")


def write_env(values: dict[str, str]) -> None:
    if not os.path.exists(ENV_PATH):
        raise SystemExit(f"{ENV_PATH} not found; create it from infra/.env.prod.example")
    with open(ENV_PATH, encoding="utf-8") as f:
        lines = f.read().splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = re.match(r"^([A-Z0-9_]+)=", line)
        if m and m.group(1) in values:
            out.append(f"{m.group(1)}={values[m.group(1)]}")
            seen.add(m.group(1))
        else:
            out.append(line)
    for k, v in values.items():
        if k not in seen:
            out.append(f"{k}={v}")
    tmp = ENV_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ENV_PATH)


def redeploy() -> None:
    infra = os.path.expanduser("~/offdays/infra")
    subprocess.run(["podman-compose", "--env-file", ".env.prod", "-f", "compose.prod.yaml",
                    "up", "-d", "--force-recreate", "app"], cwd=infra, check=True)


def ask_secret(prompt: str, prefixes: tuple[str, ...]) -> str:
    while True:
        v = getpass.getpass(prompt).strip()
        if not v:
            return ""
        if v.startswith(prefixes):
            return v
        print(f"  That does not start with {' or '.join(prefixes)}. Try again, or press Enter to skip.")


def main() -> None:
    key_only = "--key-only" in sys.argv
    values: dict[str, str] = {}

    key = secrets.token_urlsafe(32)
    values["OFFDAYS_ADMIN_KEY_SHA256"] = hashlib.sha256(key.encode()).hexdigest()

    if not key_only:
        print("\nStripe secret key. Use a TEST key (sk_test_ or rk_test_) first. Nothing shows as you type.")
        sk = ask_secret("Stripe secret key (Enter to skip): ", ("sk_test_", "rk_test_", "sk_live_", "rk_live_"))
        if sk:
            values["OFFDAYS_STRIPE_SECRET_KEY"] = sk
            if sk.startswith(("sk_live_", "rk_live_")):
                if input("That is a LIVE key: real money. Type LIVE to continue: ").strip() != "LIVE":
                    raise SystemExit("Stopped. Nothing written.")
        print("\nWebhook signing secret (whsec_...), from Stripe > Developers > Webhooks > your endpoint.")
        wh = ask_secret("Webhook secret (Enter to skip): ", ("whsec_",))
        if wh:
            values["OFFDAYS_STRIPE_WEBHOOK_SECRET"] = wh

    write_env(values)
    print(f"\nWrote {', '.join(sorted(values))} to {ENV_PATH}")
    redeploy()

    print("\n" + "=" * 60)
    print("YOUR OPERATOR KEY (shown once; save it in a password manager):\n")
    print(f"    {key}\n")
    print("Dashboard:  https://app.0ffdays.com/admin")
    print("=" * 60)


if __name__ == "__main__":
    main()
