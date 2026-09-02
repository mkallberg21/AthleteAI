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

from offdays import assignments as assignments_mod  # noqa: E402
from offdays import guardians as guardians_mod  # noqa: E402
from offdays import notifications as notify  # noqa: E402
from offdays.db import connect, transaction  # noqa: E402
from offdays.drills import get_drill  # noqa: E402
from offdays.store import Store  # noqa: E402

# name, dominant hand, sessions/week, off-hand appetite, days quiet, form profile
#
# The form profile drives the synthetic per-rep shape data, so the demo shows
# genuinely different athletes rather than the same session eight times:
#   rom_cv          -- rep-to-rep variability (lower is more repeatable)
#   rom_scale       -- how much of full range they actually cover
#   decay           -- how much range they keep by the end of a session
#   offhand_deficit -- how much shorter the weak hand's range is
ROSTER = [
    # Six athletes, each carrying a behaviour the dashboard is meant to catch.
    # The names are the program's; the profiles are what make the demo worth
    # looking at, so they are described here rather than left to be inferred
    # from the numbers.
    #
    # Trains hard and never takes a day off -- the workload warning.
    ("Scott Anderson",  "right", 6.0, 0.48, 0,  dict(rom_cv=0.06, rom_scale=1.00, decay=0.97, offhand_deficit=0.05)),
    # The one doing it right: steady, balanced, a long streak.
    ("Ryder Kallberg",  "left",  5.0, 0.42, 0,  dict(rom_cv=0.08, rom_scale=0.98, decay=0.94, offhand_deficit=0.10)),
    # Grinds out volume with a badly neglected weak hand -- the case the
    # off-hand detector exists for.
    ("Gray Freeman",    "right", 4.0, 0.15, 0,  dict(rom_cv=0.11, rom_scale=0.95, decay=0.90, offhand_deficit=0.34)),
    # A sharp jump in throwing volume, which is the load advisory.
    ("Dane Early",      "right", 3.0, 0.30, 1,  dict(rom_cv=0.10, rom_scale=0.92, decay=0.93, offhand_deficit=0.14)),
    # Gone quiet for a fortnight -- the nudge list.
    ("Finn Cannan",     "left",  2.0, 0.22, 12, dict(rom_cv=0.14, rom_scale=0.86, decay=0.88, offhand_deficit=0.18)),
    # Half reps and form that falls apart, then three weeks of nothing --
    # volume without quality, and then no volume either.
    ("Dano Otis",       "right", 1.0, 0.10, 21, dict(rom_cv=0.22, rom_scale=0.62, decay=0.74, offhand_deficit=0.22)),
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


def synth_reps(rng: random.Random, drill_key: str, offhand_bias: float, sloppy: bool,
               form: dict | None = None, dominant: str = "right"):
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
    form = form or {}
    rom_cv = form.get("rom_cv", 0.10)
    rom_scale = form.get("rom_scale", 0.95)
    decay = form.get("decay", 0.93)
    deficit = form.get("offhand_deficit", 0.12)
    target = drill.quality.target_rom if drill.quality else 1.0
    offhand = "left" if dominant == "right" else "right"

    t = 0
    reps = []
    for i in range(count):
        frac = i / max(1, count - 1)
        t += max(150, int(rng.gauss(gap, jitter)))
        if drill.tracks_handedness:
            hand = "left" if rng.random() < offhand_bias else "right"
        else:
            hand = "none"

        # Range of motion: full-range baseline, shrinking through the session,
        # with the weak hand covering less ground.
        rom = target * rom_scale * (1.0 - (1.0 - decay) * frac)
        if hand == offhand:
            rom *= 1.0 - deficit
        rom *= 1 + rng.gauss(0, rom_cv * (1.6 if sloppy else 1.0))

        reps.append({
            "t_ms": t,
            "hand": hand,
            "confidence": rng.uniform(0.28, 0.48) if sloppy else rng.uniform(0.80, 0.95),
            "rom": round(max(0.01, rom), 3),
            "peak": round(max(0.01, rom) * 0.7, 3),
            "cycle_ms": max(120, int(rng.gauss(gap * 0.85, gap * 0.2))),
        })
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

    org_id = store.create_org("Nashville Dogs")
    # A club badge, so the demo shows what a program actually sees: their own
    # mark at the top of every screen. Drop a real one in web/static/teams/
    # and point this at it.
    store.set_org_logo(org_id, "nashville-dogs.svg")
    director = store.create_user(org_id, "director", "Joel White", email="director@example.com")
    # Age-group squads rather than Varsity/JV: a 2031 birth-year group split
    # into a Red and a Blue side, which is how most youth clubs actually name
    # a roster.
    red = store.create_team(org_id, "2031 Red", "2026")
    blue = store.create_team(org_id, "2031 Blue", "2026")

    # A director sees the program; a coach sees their own team. Seeding real
    # coaches rather than only a director is what makes that difference
    # visible -- signing in as Coach Matt shows 2031 Blue and nothing else.
    coach_tokens = []
    for coach_name, team in (("Coach Tommy", red), ("Coach Matt", blue),
                             ("Coach Mike", red)):
        coach = store.create_user(org_id, "coach", coach_name)
        store.assign_staff_to_team(coach["id"], team["id"])
        coach_tokens.append((coach_name, coach["token"]))

    now = datetime.now(timezone.utc)
    athletes = []

    for i, (name, hand, per_week, offhand, quiet_days, form) in enumerate(ROSTER):
        team = blue if name == "Dano Otis" else red
        athlete = store.create_user(
            org_id, "athlete", name,
            birth_year=2009 + (i % 3),
            dominant_hand=hand,
            # One athlete deliberately left without consent so the leaderboard's
            # name-masking is visible in the demo.
            guardian_consent=(name != "Gray Freeman"),
        )
        store.join_team(team["join_code"], athlete["id"], jersey=str(10 + i), position="Midfield")
        athletes.append((athlete, name, hand, per_week, offhand, quiet_days, form))

    total_sessions = 0
    for athlete, name, hand, per_week, offhand, quiet_days, form in athletes:
        # Alex trains hard but frames badly -- populates the review queue.
        sloppy_athlete = name == "Gray Freeman"

        for day_offset in range(args.weeks * 7, quiet_days, -1):
            if rng.random() > per_week / 7.0:
                continue
            when = now - timedelta(days=day_offset, hours=rng.uniform(0, 14))
            drill_key = pick_drill(rng)
            sloppy = sloppy_athlete and rng.random() < 0.4
            reps, duration = synth_reps(
                rng, drill_key, offhand if hand == "right" else 1 - offhand,
                sloppy, form=form, dominant=hand,
            )

            started = store.start_session(athlete["id"], drill_key)
            store.submit_session(
                athlete["id"], started["session_id"], started["nonce"],
                duration_ms=duration, reps=reps,
                mean_confidence=(rng.uniform(0.30, 0.46) if sloppy else rng.uniform(0.82, 0.94)),
                client_version="seed", device_label="demo",
            )
            # Backdate so the history spreads across the window instead of
            # landing entirely on today.
            #
            # completed_at has to move too: it takes precedence over
            # submitted_at everywhere downstream (streaks, assignment windows,
            # training load), so patching only submitted_at silently collapses
            # six weeks of history onto a single day. Done here rather than by
            # passing completed_at into submit_session because that path
            # deliberately clamps backdating to two weeks.
            iso = when.isoformat(timespec="seconds")
            with transaction(store.conn) as conn:
                conn.execute(
                    "UPDATE sessions SET started_at=?, submitted_at=?, completed_at=? "
                    "WHERE id=?",
                    (iso, iso, iso, started["session_id"]),
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
    for team in (red, blue):
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

    # A guardian for the first athlete, with consent already granted so the
    # demo shows a working parent portal rather than a blocked one.
    first_athlete = athletes[0][0]
    invite = guardians_mod.create_invite(
        store.conn, first_athlete["id"], director["id"], email="parent@example.com"
    )
    guardian = guardians_mod.redeem_invite(
        store.conn, invite["code"], "Travis Anderson", "parent@example.com"
    )
    for scope in (guardians_mod.Scope.PARTICIPATION, guardians_mod.Scope.DATA_RETENTION):
        guardians_mod.set_consent(
            store.conn, first_athlete["id"], guardian["guardian_id"], scope, True
        )
    # A second, unredeemed invite so the coach view has a pending one.
    pending = guardians_mod.create_invite(
        store.conn, athletes[1][0]["id"], director["id"]
    )

    generated = notify.run_all(store.conn)

    counts = dict(
        store.conn.execute(
            "SELECT status, COUNT(*) FROM sessions WHERE status != 'open' GROUP BY status"
        ).fetchall()
    )

    print(f"\nSeeded {db_path} with {total_sessions} sessions over {args.weeks} weeks.")
    print(f"  by status: {counts}")
    scored = store.conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE quality_score IS NOT NULL"
    ).fetchone()[0]
    print(f"  assignments: {len(assignments_mod.list_for_org(store.conn, org_id))}")
    print(f"  form-scored: {scored} sessions")
    print(f"  notifications: {sum(generated.values())} scheduled + new-assignment alerts")
    print(f"\n  Join codes: 2031 Red={red['join_code']}  "
          f"2031 Blue={blue['join_code']}")
    print(f"\n  Guardian invite (unredeemed, for {athletes[1][1]}): {pending['code']}")
    print("\n  Sign-in tokens")
    print(f"    {'Joel White (director)':<26} {director['token']}")
    print(f"    {'Travis Anderson (parent)':<26} {guardian['token']}")
    for coach, token in coach_tokens:
        print(f"    {coach + ' (coach)':<26} {token}")
    for athlete, name, *_ in athletes:
        print(f"    {name:<26} {athlete['token']}")
    print(f"\n  Run:  OFFDAYS_DB_PATH={db_path} uvicorn offdays.api:app --reload")
    print("  Then open http://127.0.0.1:8000/\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
