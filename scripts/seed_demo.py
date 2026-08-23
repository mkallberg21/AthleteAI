#!/usr/bin/env python3
"""Seed a demo program so the dashboard and leaderboards have something in them.

Generates a realistic six-week history for two teams: some athletes train
constantly, some are streaky, one has gone quiet, and one keeps submitting
sessions with poor framing so the review queue is not empty either.

    python scripts/seed_demo.py --db data/demo.db

Prints the sign-in tokens at the end.
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from athleteiq import assignments as assignments_mod  # noqa: E402
from athleteiq import notifications as notify  # noqa: E402
from athleteiq.db import connect, transaction  # noqa: E402
from athleteiq.drills import get_drill  # noqa: E402
from athleteiq.store import Store  # noqa: E402

# name, dominant hand, sessions/week, off-hand appetite, days since they stopped
ROSTER = [
    ("Jordan Pierce",   "right", 6.0, 0.48, 0),
    ("Sam Rivera",      "left",  5.0, 0.42, 0),
    ("Alex Kowalczyk",  "right", 4.0, 0.15, 0),
    ("Bailey Nguyen",   "right", 3.0, 0.30, 1),
    ("Casey Donnelly",  "left",  2.0, 0.22, 12),
    ("Drew Halloran",   "right", 5.5, 0.45, 0),
    ("Emerson Vance",   "right", 1.0, 0.10, 21),
    ("Frankie Osei",    "right", 4.5, 0.38, 0),
]

DRILL_MIX = [
    ("lax_wall_ball", 0.55),
    ("gen_push_up", 0.15),
    ("gen_squat", 0.10),
    ("gen_high_knees", 0.10),
    ("gen_squat_jump", 0.10),
]


def pick_drill(rng: random.Random) -> str:
    roll = rng.random()
    cumulative = 0.0
    for key, weight in DRILL_MIX:
        cumulative += weight
        if roll <= cumulative:
            return key
    return DRILL_MIX[0][0]


def synth_reps(rng: random.Random, drill_key: str, offhand_bias: float, sloppy: bool):
    """Build a rep stream with human timing jitter.

    Rep pacing is derived from the drill's own validation envelope rather than
    hardcoded, so the seeder cannot invent physically impossible sessions and
    fill the review queue with its own artifacts.
    """
    drill = get_drill(drill_key)
    counts = {
        "lax_wall_ball": (80, 260),
        "gen_push_up": (20, 60),
        "gen_squat": (25, 70),
        "gen_high_knees": (60, 160),
        "gen_squat_jump": (20, 50),
    }
    count = rng.randint(*counts.get(drill_key, (40, 100)))

    # Stay comfortably inside the drill's own speed ceiling.
    fastest_gap = 1000.0 / drill.validation.max_reps_per_second
    gap = rng.uniform(fastest_gap * 1.35, fastest_gap * 2.2)

    jitter = gap * (0.30 if sloppy else 0.20)
    t = 0
    reps = []
    for _ in range(count):
        t += max(150, int(rng.gauss(gap, jitter)))
        if drill.tracks_handedness:
            hand = "left" if rng.random() < offhand_bias else "right"
        else:
            hand = "none"
        reps.append({"t_ms": t, "hand": hand, "confidence": rng.uniform(0.28, 0.48) if sloppy
                     else rng.uniform(0.80, 0.95)})
    return reps, t + int(rng.uniform(400, 1200))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/demo.db", help="path to the demo database")
    parser.add_argument("--weeks", type=int, default=6, help="weeks of history to generate")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    db_path = Path(args.db)
    if db_path.exists():
        db_path.unlink()

    rng = random.Random(args.seed)
    store = Store(connect(db_path))

    org_id = store.create_org("Northshore Lacrosse Club")
    director = store.create_user(org_id, "director", "Coach Rivera", email="coach@example.com")
    varsity = store.create_team(org_id, "Varsity", "2026")
    jv = store.create_team(org_id, "JV", "2026")

    now = datetime.now(timezone.utc)
    athletes = []

    for i, (name, hand, per_week, offhand, quiet_days) in enumerate(ROSTER):
        team = varsity if i < 4 else jv
        athlete = store.create_user(
            org_id, "athlete", name,
            birth_year=2009 + (i % 3),
            dominant_hand=hand,
            # One athlete deliberately left without consent so the leaderboard's
            # name-masking is visible in the demo.
            guardian_consent=(name != "Alex Kowalczyk"),
        )
        store.join_team(team["join_code"], athlete["id"], jersey=str(10 + i), position="Midfield")
        athletes.append((athlete, name, hand, per_week, offhand, quiet_days))

    total_sessions = 0
    for athlete, name, hand, per_week, offhand, quiet_days in athletes:
        # Alex trains hard but frames badly -- populates the review queue.
        sloppy_athlete = name == "Alex Kowalczyk"

        for day_offset in range(args.weeks * 7, quiet_days, -1):
            if rng.random() > per_week / 7.0:
                continue
            when = now - timedelta(days=day_offset, hours=rng.uniform(0, 14))
            drill_key = pick_drill(rng)
            sloppy = sloppy_athlete and rng.random() < 0.4
            reps, duration = synth_reps(rng, drill_key, offhand if hand == "right" else 1 - offhand, sloppy)

            started = store.start_session(athlete["id"], drill_key)
            store.submit_session(
                athlete["id"], started["session_id"], started["nonce"],
                duration_ms=duration, reps=reps,
                mean_confidence=(rng.uniform(0.30, 0.46) if sloppy else rng.uniform(0.82, 0.94)),
                client_version="seed", device_label="demo",
            )
            # Backdate so the history spreads across the window instead of
            # landing entirely on today.
            iso = when.isoformat(timespec="seconds")
            with transaction(store.conn) as conn:
                conn.execute(
                    "UPDATE sessions SET started_at=?, submitted_at=? WHERE id=?",
                    (iso, iso, started["session_id"]),
                )
                conn.execute(
                    "UPDATE xp_ledger SET day=?, created_at=? WHERE session_id=?",
                    (when.date().isoformat(), iso, started["session_id"]),
                )
            total_sessions += 1

    # Badges are derived from history, so re-sync after backdating.
    for athlete, *_ in athletes:
        store._sync_badges(athlete["id"])

    # A live assignment per team, so the compliance view has something in it.
    today = now.date()
    for team in (varsity, jv):
        assignments_mod.create(
            store.conn,
            org_id=org_id,
            team_id=team["id"],
            created_by=director["id"],
            drill_key="lax_wall_ball",
            title=f"{team['name']} Wall Ball Week",
            notes="Both hands. Quality over speed.",
            starts_on=(today - timedelta(days=3)).isoformat(),
            due_on=(today + timedelta(days=3)).isoformat(),
            target_reps=600,
            target_sessions=3,
            min_offhand=0.35,
        )

    for assignment in assignments_mod.list_for_org(store.conn, org_id):
        notify.notify_new_assignment(store.conn, assignment.id)
    generated = notify.run_all(store.conn)

    counts = dict(
        store.conn.execute(
            "SELECT status, COUNT(*) FROM sessions WHERE status != 'open' GROUP BY status"
        ).fetchall()
    )

    print(f"\nSeeded {db_path} with {total_sessions} sessions over {args.weeks} weeks.")
    print(f"  by status: {counts}")
    print(f"  assignments: {len(assignments_mod.list_for_org(store.conn, org_id))}")
    print(f"  notifications: {sum(generated.values())} scheduled + new-assignment alerts")
    print(f"\n  Join codes: Varsity={varsity['join_code']}  JV={jv['join_code']}")
    print("\n  Sign-in tokens")
    print(f"    {'Coach Rivera (director)':<26} {director['token']}")
    for athlete, name, *_ in athletes:
        print(f"    {name:<26} {athlete['token']}")
    print(f"\n  Run:  ATHLETEIQ_DB_PATH={db_path} uvicorn athleteiq.api:app --reload")
    print("  Then open http://127.0.0.1:8000/\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
