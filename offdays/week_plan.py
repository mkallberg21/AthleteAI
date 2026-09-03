"""Compose the athlete's week plan from assignments, budget, and film.

A single endpoint an athlete can read in one glance: what their coach has
assigned this week, where they sit against their age budget, and how much
film time they have left. The plain-language line is the part a twelve-year-
old actually acts on.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import benchmarks as benchmarks_mod
from .assignments import for_athlete as assignments_for
from .assignments import progress_for_athlete


@dataclass
class WeekPlan:
    """Everything an athlete needs to see in one place."""

    assignments: list[dict]
    budget: dict
    film: dict
    line: str

    def to_dict(self) -> dict:
        return {
            "assignments": self.assignments,
            "budget": self.budget,
            "film": self.film,
            "line": self.line,
        }


def for_athlete(store, athlete_id: int) -> WeekPlan:
    """Build the week plan from the three underlying surfaces."""
    open_assignments = assignments_for(store.conn, athlete_id, only_open=True)

    result_assignments = []
    for a in open_assignments:
        p = progress_for_athlete(store.conn, a, athlete_id)
        result_assignments.append(
            {
                **a.to_dict(),
                "progress": p.to_dict(),
                "days_remaining": a.days_remaining(),
            }
        )

    budget_report = benchmarks_mod.report(store.conn, athlete_id)

    film_today = {"clips": [], "bands": [], "day_state": {}}
    try:
        org_id = store.org_for_user(athlete_id)
        film_today = store.clips_for_athlete(athlete_id, org_id)
    except Exception:
        pass

    age = _athlete_age(store.conn, athlete_id)
    line = _compose_line(result_assignments, budget_report, film_today, age)
    return WeekPlan(
        assignments=result_assignments,
        budget=budget_report,
        film=film_today,
        line=line,
    )


def _athlete_age(conn, athlete_id: int) -> int | None:
    """Current age in years, or None when birth_year is unknown."""
    try:
        from datetime import date
        row = conn.execute(
            "SELECT birth_year FROM users WHERE id = ?", (athlete_id,)
        ).fetchone()
        if row and row["birth_year"]:
            age = date.today().year - int(row["birth_year"])
            # Clamp conservatively so an unestimated birth year does not read as
            # an adult. Anything we cannot place gets None, and the line falls
            # back to the band label instead of a wrong number.
            if 0 <= age <= 200:
                return age
    except Exception:
        pass
    return None


def _compose_line(
    assignments: list[dict],
    budget: dict,
    film: dict,
    age: int | None,
) -> str:
    """One sentence that says what this week actually asks for, age-appropriately.

    The line reads differently by age. A six-year-old gets short, plain words and
    is never asked for a number this app cannot see. A sixteen-year-old gets a
    real sentence that names the week's ask. Every age gets told plainly when it
    is already enough.
    """
    from .benchmarks import Status

    band = budget.get("band", {})
    band_min_age = band.get("min_age")
    band_max_age = band.get("max_age")
    budget_status = budget.get("status", Status.UNKNOWN)
    budget_minutes = budget.get("minutes", 0)
    budget_target = band.get("weekly_target", 0)
    budget_max = band.get("weekly_max", 0)
    budget_days_target = band.get("days_target", 0)
    session_max = band.get("session_max", 0)
    band_label = band.get("label", "")

    effective_age = age if age is not None else band_min_age
    is_young = effective_age is not None and effective_age <= 10

    assigned_sessions = sum(
        1
        for a in assignments
        if not a["progress"]["sessions_met"]
        and a["progress"]["sessions_done"] < a.get("target_sessions", 0)
        and a.get("target_sessions", 0) > 0
    )
    total_assigned_reps = sum(
        a["target_reps"]
        for a in assignments
        if not a["progress"]["reps_met"] and a.get("target_reps", 0) > 0
    )

    day_state = film.get("day_state", {})
    film_minutes_left = day_state.get("minutes_left", 0)
    film_clips_left = day_state.get("clips_left", 0)

    parts: list[str] = []

    if not assignments and budget_status == Status.UNKNOWN and not film_clips_left:
        if is_young:
            return "Nothing set for this week yet — have fun with the ball when you feel like it."
        return "Nothing set for this week yet. When your coach assigns work it shows up here."

    if assignments:
        if total_assigned_reps > 0 and assigned_sessions > 0:
            if is_young:
                parts.append(
                    f"You have {assigned_sessions} thing{'s' if assigned_sessions != 1 else ''} "
                    f"and {total_assigned_reps} {'' if total_assigned_reps == 1 else ''}in it to finish this week."
                )
            else:
                parts.append(
                    f"You have {assigned_sessions} session{'s' if assigned_sessions != 1 else ''} "
                    f"and {total_assigned_reps} rep{'s' if total_assigned_reps != 1 else ''} to finish this week."
                )
        elif assigned_sessions > 0:
            if is_young:
                parts.append(f"You have {assigned_sessions} thing to finish this week.")
            else:
                parts.append(f"You have {assigned_sessions} session{'s' if assigned_sessions != 1 else ''} to finish this week.")
        elif total_assigned_reps > 0:
            if is_young:
                parts.append(f"You have {total_assigned_reps} {'thing' if total_assigned_reps == 1 else 'things'} to finish this week.")
            else:
                parts.append(f"You have {total_assigned_reps} rep{'s' if total_assigned_reps != 1 else ''} to finish this week.")
        else:
            parts.append("You have no open assignments this week.")

    if budget_status == Status.UNKNOWN:
        if is_young:
            parts.append(
                f"A good week at {band_label} is about {budget_target} minutes — a couple "
                f"of short sessions, not an evening job."
            )
        else:
            parts.append(
                f"Aim for about {budget_target} minutes across {budget_days_target} days "
                f"this week — a few short sessions, not an evening job."
            )
    elif budget_status == Status.BUILDING:
        remaining = max(0, budget_target - budget_minutes)
        if is_young:
            typical = max(1, budget_target // budget_days_target)
            sessions_left = min(budget_days_target, max(1, round(remaining / typical)))
            parts.append(
                f"You are a little short this week — about {sessions_left} more short "
                f"session{'s' if sessions_left != 1 else ''} of about {typical} minutes would "
                f"round it out. Then have a rest day."
            )
        else:
            typical = max(1, budget_target // budget_days_target)
            sessions_left = min(budget_days_target, max(1, round(remaining / typical)))
            parts.append(
                f"You are short of your week's target — about {sessions_left} more "
                f"short session{'s' if sessions_left != 1 else ''} of about {typical} minutes "
                f"gets you to a good week."
            )
    elif budget_status == Status.GOOD:
        if is_young:
            parts.append(
                f"You are on track for {band_label} — about {int(budget_minutes)} of "
                f"about {budget_target} minutes this week is a good week."
            )
        else:
            parts.append(
                f"You are on track — about {int(budget_minutes)} of about "
                f"{budget_target} minutes done this week, which is a good week at {band_label}."
            )
    elif budget_status == Status.FULL:
        parts.append(
            f"You have done enough for {band_label} — about {int(budget_minutes)} minutes "
            f"is a full week. Anything else this week is a bonus, not a requirement."
        )
    elif budget_status == Status.OVER:
        over = max(0, budget_minutes - budget_max)
        if is_young:
            parts.append(
                f"You have done plenty this week — about {int(budget_minutes)} minutes, "
                f"which is above the {budget_max} minutes that suits {band_label}. "
                f"A couple of days off is the right move now."
            )
        else:
            parts.append(
                f"You have done more than enough for {band_label} — about {int(budget_minutes)} "
                f"minutes, which is past the {budget_max} minutes that suits your age "
                f"by about {int(over)}. Rest is when the work turns into progress."
            )

    if film_clips_left > 0 and film_minutes_left > 0:
        if is_young:
            parts.append(
                f"You have {film_clips_left} clip{'s' if film_clips_left != 1 else ''} "
                f"left to watch today — about {int(film_minutes_left)} minute{'s' if film_minutes_left != 1 else ''} of film."
            )
        else:
            parts.append(
                f"You have {film_clips_left} clip{'s' if film_clips_left != 1 else ''} "
                f"and about {int(film_minutes_left)} minutes of film left today."
            )
    elif film.get("clips"):
        if is_young:
            parts.append("There are clips on the shelf to watch — have a look at the film card.")
        else:
            parts.append("There are clips on the shelf to watch — check the film card.")

    return " ".join(parts) if parts else "Your week looks clear."
