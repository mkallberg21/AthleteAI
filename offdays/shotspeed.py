"""Approximate shot speed, worked out again on the server.

The phone measures each shot as a release time, an impact time it heard, and
the distance the athlete said they shot from (see `web/static/shotspeed.js`).
It also sends the speed it worked out. This module ignores that number and
computes its own from the raw times, for the same reason ball tracking and
integrity do: the browser did the measuring, so the browser is the one place
a number cannot be trusted from. A payload that sends 140mph gets back
whatever its own timings say, which is either a real speed or nothing.

What comes out is deliberately modest.

**Approximate, and said so.** It is the average speed over the flight, a
little below what a radar gun reads at the stick, and good to roughly 10-15%
when the release is read from the camera. Every report carries that sentence.

**About this athlete, never against others.** Speed is shown to the athlete,
their parent and their coach, and nowhere else: not on any leaderboard, not
in team standings, not in the parent's cohort board. A speed board is the
fastest way to get thirteen-year-olds ripping shot after shot, and shooting
is the heaviest throw this app counts.

**Counted, never scored.** Speed changes no XP. The throws still count toward
the day's throwing ceiling exactly like wall ball, which is the part of this
that protects the arm.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from statistics import median
from typing import Any

#: Physical constants, the same as the client's. Kept in step by
#: tests/test_shotspeed.py, which runs both against the same cases.
SPEED_OF_SOUND_MS = 343.0
YD_TO_M = 0.9144
MS_TO_MPH = 2.236936
MIN_FLIGHT_MS = 60
MAX_FLIGHT_MS = 1600
MIN_MPH = 15.0
MAX_MPH = 110.0

#: Below this many timed shots a session's median is one shot's opinion.
MIN_TIMED = 3

#: How far off the two moments can be together, in ms. The release is read
#: from the swing to a 10ms hop and sat 16ms from the frame the ball left on
#: the radar clips; the impact is a hop too. Twenty is the two combined, and
#: it is what the "about" in every report is worked out from.
TIMING_MS = 20.0


def precision_mph(distance_yd: float, mph: float) -> float | None:
    """How much TIMING_MS of error moves a shot of this speed from this
    distance, in mph. Short flights are coarse: from 7 yards a 75mph shot is
    about +-9, from 15 about +-4. Rounded to whole mph."""
    if not distance_yd or distance_yd <= 0 or not mph or mph <= 0:
        return None
    distance_m = distance_yd * YD_TO_M
    flight_ms = distance_m / (mph / MS_TO_MPH) * 1000
    if flight_ms <= TIMING_MS:
        return None
    faster = distance_m / ((flight_ms - TIMING_MS) / 1000) * MS_TO_MPH
    return float(max(1, round(faster - mph)))

#: Sentences shown with every report.
LIMITS = (
    "Approximate: it is the average speed over the ball's flight, timed from "
    "your release to the sound of it hitting, so it reads a little under a "
    "radar gun.",
    "It is only as right as the distance you set. Shoot from a marked spot, "
    "7 to 15 yards out: the further, the finer the timing.",
    "It is yours, your parent's and your coach's. It is not on any leaderboard.",
)


def speed_mph(release_ms: float, impact_ms: float, distance_yd: float) -> float | None:
    """One shot's speed, or None when the timings cannot be a shot."""
    if not distance_yd or distance_yd <= 0:
        return None
    distance_m = distance_yd * YD_TO_M
    sound_back_ms = distance_m / SPEED_OF_SOUND_MS * 1000
    flight_ms = impact_ms - sound_back_ms - release_ms
    if not MIN_FLIGHT_MS <= flight_ms <= MAX_FLIGHT_MS:
        return None
    mph = distance_m / (flight_ms / 1000) * MS_TO_MPH
    if not MIN_MPH <= mph <= MAX_MPH:
        return None
    return round(mph, 1)


@dataclass
class ShotReport:
    shots: int = 0
    timed: int = 0
    distance_yd: float | None = None
    #: Per-shot speeds in shot order, None where a shot was not timed.
    speeds: list[float | None] = field(default_factory=list)
    best_mph: float | None = None
    median_mph: float | None = None
    #: Median by hand, when the stick hand was read for enough shots.
    by_hand: dict[str, float] = field(default_factory=dict)
    #: What the typical speed is good to, in mph, at this distance and speed.
    plus_minus_mph: float | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "shots": self.shots,
            "timed": self.timed,
            "distance_yd": self.distance_yd,
            "speeds": self.speeds,
            "best_mph": self.best_mph,
            "median_mph": self.median_mph,
            "by_hand": self.by_hand,
            "plus_minus_mph": self.plus_minus_mph,
            "note": self.note,
            "limits": list(LIMITS),
        }


def analyze(
    reps: list[dict[str, Any]],
    distance_yd: float | None,
    *,
    min_distance_yd: float,
    max_distance_yd: float,
) -> ShotReport:
    """Speed for each shot that has both moments, from the raw timings."""
    report = ShotReport(shots=len(reps))
    if distance_yd is None or not min_distance_yd <= distance_yd <= max_distance_yd:
        report.note = (
            "No shot speed this time: set how far you shot from before you "
            "start, and it will time every shot."
        )
        return report
    report.distance_yd = distance_yd

    by_hand: dict[str, list[float]] = {}
    for rep in reps:
        release, impact = rep.get("release_t_ms"), rep.get("impact_t_ms")
        mph = None
        if release is not None and impact is not None:
            mph = speed_mph(float(release), float(impact), distance_yd)
        report.speeds.append(mph)
        if mph is not None:
            hand = rep.get("hand")
            if hand in ("left", "right"):
                by_hand.setdefault(hand, []).append(mph)

    timed = [s for s in report.speeds if s is not None]
    report.timed = len(timed)
    if not timed:
        report.note = (
            "No shots were timed. The phone has to hear the ball hit the net: "
            "keep the microphone on and the phone within a few yards of you."
        )
        return report

    report.best_mph = max(timed)
    report.median_mph = round(median(timed), 1)
    report.by_hand = {h: round(median(v), 1) for h, v in by_hand.items() if len(v) >= MIN_TIMED}
    report.plus_minus_mph = precision_mph(distance_yd, report.median_mph)

    if report.timed < MIN_TIMED:
        report.note = (
            f"{report.timed} of {report.shots} shots were timed. A few more and "
            "the app can tell you your typical speed, not just one shot's."
        )
    else:
        about = (f" (good to about {report.plus_minus_mph:.0f} mph either way from there)"
                 if report.plus_minus_mph else "")
        report.note = (
            f"Typical shot about {report.median_mph:.0f} mph, best "
            f"{report.best_mph:.0f} mph, from {distance_yd:g} yards{about}. Compare "
            "it with your own past sessions from the same spot, not with anyone "
            "else's."
        )
    return report


def record(
    conn: sqlite3.Connection, session_id: int, athlete_id: int, day: str,
    report: ShotReport,
) -> None:
    """Keep a counted session's typical speed for standings. Needs enough
    timed shots for a median to mean something."""
    if report.median_mph is None or report.timed < MIN_TIMED or report.distance_yd is None:
        return
    conn.execute(
        "INSERT OR REPLACE INTO shot_speeds(session_id, athlete_id, day, median_mph, "
        "timed, distance_yd) VALUES (?,?,?,?,?,?)",
        (session_id, athlete_id, day, report.median_mph, report.timed, report.distance_yd),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Standing: where an athlete's speed sits among teammates and peers
#
# A percentile, not a rank and not a list. "Faster than about 60% of your
# teammates" tells a kid where they are; a sorted column of names is a
# leaderboard, and a speed leaderboard is the thing this feature refuses to
# be. So the only number that leaves here is the athlete's own percentile.
#
# Two rules keep that honest:
#
# **A floor on the group.** In a group of three, "faster than 50%" names the
# other two. Below MIN_TEAM_PEERS teammates with a speed, no team percentile
# is shown; below MIN_AGE_PEERS same-age athletes nationally, no national one.
# The national figure is built in now and switches itself on once enough kids
# across every club have shot -- nothing to deploy when that day comes.
#
# **Rounded.** To the nearest 5%, because the measurement is good to about
# 10-15% and a percentile quoted to the unit implies a precision the speed
# never had.
# ---------------------------------------------------------------------------

#: How far back a speed counts toward standing. A month is long enough for a
#: kid who shoots weekly to have a number, short enough that it is today's arm.
STANDING_DAYS = 30

#: Teammates with a speed (not counting the athlete) before a team percentile
#: is shown. Under this, a percentile identifies individuals.
MIN_TEAM_PEERS = 4

#: Same-age athletes with a speed, across every club, before a national
#: percentile is shown. High on purpose: the claim "among kids your age" is
#: only true once there are a great many of them.
MIN_AGE_PEERS = 200


def _athlete_value(conn: sqlite3.Connection, athlete_id: int, since: str) -> float | None:
    """An athlete's speed for standing: their best session median this month.

    Best session rather than one shot, so a single lucky reading cannot carry
    it; best rather than latest, so a tired Tuesday does not drop a kid ten
    places.
    """
    row = conn.execute(
        "SELECT MAX(median_mph) AS v FROM shot_speeds WHERE athlete_id = ? AND day >= ?",
        (athlete_id, since),
    ).fetchone()
    return None if row is None or row["v"] is None else float(row["v"])


def _percentile(mine: float, others: list[float]) -> int:
    """Share of the group this athlete is faster than, ties counted half,
    rounded to the nearest 5."""
    below = sum(1 for v in others if v < mine)
    tied = sum(1 for v in others if v == mine)
    pct = 100.0 * (below + 0.5 * tied) / len(others)
    return int(5 * round(pct / 5))


def standing(conn: sqlite3.Connection, athlete_id: int, today: str) -> dict[str, Any]:
    """This athlete's percentile among teammates, and among same-age athletes
    nationally once there are enough. Nothing about anyone else is returned."""
    from datetime import date, timedelta

    since = (date.fromisoformat(today) - timedelta(days=STANDING_DAYS)).isoformat()
    mine = _athlete_value(conn, athlete_id, since)
    out: dict[str, Any] = {
        "window_days": STANDING_DAYS,
        "speed_mph": mine,
        "team": {"available": False, "peers": 0, "needed": MIN_TEAM_PEERS},
        "age": {"available": False, "peers": 0, "needed": MIN_AGE_PEERS},
    }
    if mine is None:
        return out

    # Teammates: anyone on any team this athlete is on, best this month each.
    team_vals = [
        float(r["v"]) for r in conn.execute(
            "SELECT MAX(s.median_mph) AS v FROM shot_speeds s "
            "JOIN users u ON u.id = s.athlete_id AND u.active = 1 "
            "WHERE s.day >= ? AND s.athlete_id != ? AND s.athlete_id IN ("
            "  SELECT tm2.user_id FROM team_members tm1 "
            "  JOIN team_members tm2 ON tm2.team_id = tm1.team_id "
            "  WHERE tm1.user_id = ?) "
            "GROUP BY s.athlete_id",
            (since, athlete_id, athlete_id),
        )
    ]
    out["team"]["peers"] = len(team_vals)
    if len(team_vals) >= MIN_TEAM_PEERS:
        out["team"].update(available=True, percentile=_percentile(mine, team_vals))

    # Same birth year, every club. Only the athlete's own percentile comes back.
    birth = conn.execute(
        "SELECT birth_year FROM users WHERE id = ?", (athlete_id,)
    ).fetchone()
    if birth and birth["birth_year"]:
        out["age"]["birth_year"] = int(birth["birth_year"])
        age_vals = [
            float(r["v"]) for r in conn.execute(
                "SELECT MAX(s.median_mph) AS v FROM shot_speeds s "
                "JOIN users u ON u.id = s.athlete_id AND u.active = 1 "
                "WHERE s.day >= ? AND s.athlete_id != ? AND u.birth_year = ? "
                "GROUP BY s.athlete_id",
                (since, athlete_id, int(birth["birth_year"])),
            )
        ]
        out["age"]["peers"] = len(age_vals)
        if len(age_vals) >= MIN_AGE_PEERS:
            out["age"].update(available=True, percentile=_percentile(mine, age_vals))
    return out


def history(conn: sqlite3.Connection, athlete_id: int, limit: int = 20) -> list[dict[str, Any]]:
    """An athlete's recent timed shooting sessions, newest first.

    Read from the result each session stored at submit, so it shows exactly
    what the athlete was shown at the time. Never aggregated across athletes.
    """
    import json

    rows = conn.execute(
        "SELECT id, completed_at, result_json FROM sessions "
        "WHERE athlete_id = ? AND status IN ('counted','review') "
        "AND result_json LIKE '%\"shot_speed\"%' "
        "ORDER BY completed_at DESC LIMIT ?",
        (athlete_id, limit),
    ).fetchall()
    out = []
    for row in rows:
        try:
            speed = json.loads(row["result_json"]).get("shot_speed") or {}
        except (ValueError, TypeError):
            continue
        if not speed.get("timed"):
            continue
        out.append({
            "session_id": row["id"],
            "completed_at": row["completed_at"],
            "shots": speed.get("shots"),
            "timed": speed.get("timed"),
            "distance_yd": speed.get("distance_yd"),
            "median_mph": speed.get("median_mph"),
            "best_mph": speed.get("best_mph"),
            "by_hand": speed.get("by_hand") or {},
        })
    return out
