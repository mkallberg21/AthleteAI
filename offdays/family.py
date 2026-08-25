"""The household board: what a family sees instead of a leaderboard.

A club leaderboard works because forty athletes of roughly the same age are
already competing for the same places, and seeing where you sit is information
you were going to get anyway. A household is not that. It is a nine-year-old
and a thirteen-year-old, and ranking them against each other by reps says
nothing except which of them is older.

So the default here is not a ranking at all. Each child is measured against
**their own recent self**, which is the only comparison that is fair when the
other competitor is their sibling and four years behind them. Alongside that
sits one genuinely shared number -- days the household trained -- which is
collaborative rather than competitive, and is the thing a family can actually
chase together.

A parent can turn on a side-by-side view, because parents know their own
children and some households genuinely thrive on it. Even then it compares
**consistency and form, never volume**, for the same reason the peer benchmarks
do not compare volume: turning up and moving well are things a younger sibling
can win, and reps are not.
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .config import CONFIG
from .scoring import compute_streak

#: A week is the unit a family actually plans in.
WEEK = 7
#: Compared against the four weeks before it, so one quiet week reads as one
#: quiet week rather than a collapse.
BASELINE_WEEKS = 4


def _today(today: date | None = None) -> date:
    return today or datetime.now(timezone.utc).date()


def _streak_days(conn: sqlite3.Connection, athlete_id: int) -> list[date]:
    """Days that count toward a streak: trained, rested deliberately, or
    checked in. Mirrors the athlete's own screen rather than inventing a
    second definition of the same word."""
    days: set[date] = set()
    for sql in (
        "SELECT day FROM xp_ledger WHERE athlete_id = ? GROUP BY day "
        "HAVING SUM(amount) >= ?",
    ):
        days.update(
            date.fromisoformat(r["day"])
            for r in conn.execute(sql, (athlete_id, CONFIG.scoring.streak_min_xp))
        )
    for sql in (
        "SELECT day FROM recovery_days WHERE athlete_id = ?",
        "SELECT day FROM wellness_checkins WHERE athlete_id = ?",
    ):
        try:
            days.update(
                date.fromisoformat(r["day"]) for r in conn.execute(sql, (athlete_id,))
            )
        except sqlite3.OperationalError:
            # An older database without that table: the streak is simply the
            # trained days, which is what it was before those existed.
            continue
    return sorted(days)


@dataclass
class ChildBoard:
    athlete_id: int
    display_name: str
    age: int | None
    days_this_week: int
    days_baseline: float
    sessions_this_week: int
    reps_this_week: int
    streak: int
    longest_streak: int
    quality: int | None
    quality_baseline: float | None
    best_quality: int | None
    #: How this week compares with their own recent normal. Never with anyone
    #: else's.
    trend: str = "steady"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "athlete_id": self.athlete_id,
            "display_name": self.display_name,
            "age": self.age,
            "days_this_week": self.days_this_week,
            "days_baseline": round(self.days_baseline, 1),
            "sessions_this_week": self.sessions_this_week,
            "reps_this_week": self.reps_this_week,
            "streak": self.streak,
            "longest_streak": self.longest_streak,
            "quality": self.quality,
            "quality_baseline": (
                round(self.quality_baseline, 1) if self.quality_baseline else None
            ),
            "best_quality": self.best_quality,
            "trend": self.trend,
            "note": self.note,
        }


def _trend(now: float, baseline: float, resolution: float = 0.5) -> str:
    """Up, down, or steady against their own average.

    A resolution floor because a household of two children produces small
    numbers, and "up 0.3 days" is noise dressed as progress -- the same reason
    the leaderboard learned to say "holding steady".
    """
    if baseline <= 0:
        return "new" if now > 0 else "steady"
    if now - baseline >= resolution:
        return "up"
    if baseline - now >= resolution:
        return "down"
    return "steady"


def _note(child: ChildBoard) -> str:
    """One line, about them and nobody else."""
    if child.days_this_week == 0 and child.days_baseline == 0:
        return "Nothing logged yet. The first one is the hard one."
    if child.trend == "new":
        return "First week of training logged."
    if child.streak >= 3:
        return f"{child.streak} days in a row right now."
    if child.trend == "up":
        return "More days than their usual week."
    if child.trend == "down":
        return "A quieter week than usual, which is fine."
    return "About their usual week."


def child_board(
    conn: sqlite3.Connection, athlete_id: int, today: date | None = None
) -> ChildBoard:
    """One child, measured against their own recent self."""
    today = _today(today)
    week_start = (today - timedelta(days=WEEK - 1)).isoformat()
    base_start = (today - timedelta(days=WEEK * (BASELINE_WEEKS + 1) - 1)).isoformat()

    profile = conn.execute(
        "SELECT display_name, birth_year FROM users WHERE id = ?", (athlete_id,)
    ).fetchone()
    age = None
    if profile is not None and profile["birth_year"]:
        age = today.year - int(profile["birth_year"])

    rows = conn.execute(
        "SELECT date(COALESCE(completed_at, submitted_at)) AS day, "
        "  reps_total, quality_score "
        "FROM sessions WHERE athlete_id = ? AND status = 'counted' "
        "AND date(COALESCE(completed_at, submitted_at)) >= ?",
        (athlete_id, base_start),
    ).fetchall()

    this_week = [r for r in rows if r["day"] >= week_start]
    before = [r for r in rows if r["day"] < week_start]

    days_now = len({r["day"] for r in this_week})
    baseline_days = len({r["day"] for r in before}) / BASELINE_WEEKS if before else 0.0

    quality_now = [int(r["quality_score"]) for r in this_week if r["quality_score"]]
    quality_before = [int(r["quality_score"]) for r in before if r["quality_score"]]
    best = conn.execute(
        "SELECT MAX(quality_score) AS best FROM sessions "
        "WHERE athlete_id = ? AND status = 'counted'",
        (athlete_id,),
    ).fetchone()

    # The same streak the athlete sees on their own screen, including the
    # recovery days and wellness check-ins that protect it. Two different
    # numbers for the same word would be worse than not showing it.
    streak = compute_streak(_streak_days(conn, athlete_id), today)

    board = ChildBoard(
        athlete_id=athlete_id,
        display_name=profile["display_name"] if profile else "",
        age=age,
        days_this_week=days_now,
        days_baseline=baseline_days,
        sessions_this_week=len(this_week),
        reps_this_week=sum(int(r["reps_total"] or 0) for r in this_week),
        streak=streak.current,
        longest_streak=streak.longest,
        quality=round(statistics.fmean(quality_now)) if quality_now else None,
        quality_baseline=statistics.fmean(quality_before) if quality_before else None,
        best_quality=int(best["best"]) if best and best["best"] else None,
    )
    board.trend = _trend(days_now, baseline_days)
    board.note = _note(board)
    return board


@dataclass
class Household:
    children: list[ChildBoard] = field(default_factory=list)
    #: Days in the last week where at least one child trained. The number a
    #: family can chase together rather than against each other.
    days_active: int = 0
    #: Days where every child who trains at all did. Rarer, and worth more.
    days_together: int = 0
    together_streak: int = 0
    compare_siblings: bool = False

    def to_dict(self) -> dict[str, Any]:
        out = {
            "children": [c.to_dict() for c in self.children],
            "days_active": self.days_active,
            "days_together": self.days_together,
            "together_streak": self.together_streak,
            "compare_siblings": self.compare_siblings,
            "headline": self.headline(),
        }
        if self.compare_siblings:
            out["side_by_side"] = self.side_by_side()
        return out

    def headline(self) -> str:
        if not self.children:
            return "Add your athletes to get started."
        if self.days_active == 0:
            return "Nobody has trained this week yet."
        if self.days_together >= 3:
            return (
                f"{self.days_together} days this week everyone trained. "
                "That is the hard one."
            )
        return f"Somebody trained on {self.days_active} of the last 7 days."

    def side_by_side(self) -> list[dict[str, Any]]:
        """Consistency and form only. Never volume.

        A younger sibling can win turning up and can win moving well. They
        cannot win reps against someone four years older, and a board that
        ranks them on it is just telling them their birthday again.
        """
        rows = []
        for column, label, values in (
            ("days_this_week", "Days trained",
             [(c.display_name, c.days_this_week) for c in self.children]),
            ("quality", "Form score",
             [(c.display_name, c.quality) for c in self.children if c.quality]),
            ("streak", "Current streak",
             [(c.display_name, c.streak) for c in self.children]),
        ):
            ranked = sorted(values, key=lambda pair: -(pair[1] or 0))
            rows.append({
                "metric": column,
                "label": label,
                "rows": [{"display_name": n, "value": v} for n, v in ranked],
            })
        return rows


def household(
    conn: sqlite3.Connection,
    org_id: int,
    today: date | None = None,
    compare_siblings: bool = False,
) -> Household:
    """The whole family's board."""
    today = _today(today)
    athletes = conn.execute(
        "SELECT id FROM users WHERE org_id = ? AND role = 'athlete' AND active = 1 "
        "ORDER BY birth_year DESC, id",
        (org_id,),
    ).fetchall()

    children = [child_board(conn, int(r["id"]), today) for r in athletes]
    board = Household(children=children, compare_siblings=compare_siblings)
    if not children:
        return board

    week_start = (today - timedelta(days=WEEK - 1)).isoformat()
    marks = ",".join("?" for _ in children)
    rows = conn.execute(
        f"SELECT date(COALESCE(completed_at, submitted_at)) AS day, "
        f"  COUNT(DISTINCT athlete_id) AS who "
        f"FROM sessions WHERE athlete_id IN ({marks}) AND status = 'counted' "
        f"AND date(COALESCE(completed_at, submitted_at)) >= ? GROUP BY day",
        (*[c.athlete_id for c in children], week_start),
    ).fetchall()

    board.days_active = len(rows)
    board.days_together = sum(1 for r in rows if int(r["who"]) == len(children))

    # Consecutive days ending today (or yesterday) where everyone trained. The
    # only streak in this module that belongs to the household rather than to
    # one child, and the only one worth putting on a fridge.
    full = {r["day"] for r in rows if int(r["who"]) == len(children)}
    cursor = today
    if cursor.isoformat() not in full:
        cursor = today - timedelta(days=1)
    while cursor.isoformat() in full:
        board.together_streak += 1
        cursor -= timedelta(days=1)
    return board
