"""A team's age, read from its name, and the day's targets that follow.

Clubs name teams by graduation year ("2031 Red"), by age ("U13", "13U",
"13 and under"), or by birth year ("2013 Blue"). All three say how old the
players are, and that is what a director is thinking about when he types
the name -- so the daily wall-ball and shooting numbers can be filled in
for him from the same age tables the app applies to every athlete, rather
than asked for.

What is inferred is a BAND, not a birthday: the targets live on the team
and the per-athlete ceiling (from the child's own birth year) still binds
above them. A team the name says nothing about gets no prefill and the
director types the numbers or leaves them to the ceilings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

#: A U.S. high-school graduation is the summer the player is ~18.
GRAD_AGE = 18

#: Bands as the shooting table uses them; the label is what the director
#: sees next to the prefilled number.
BANDS: tuple[tuple[int, str], ...] = (
    (10, "10 and under"), (12, "11-12"), (14, "13-14"), (16, "15-16"), (200, "17+"))


@dataclass(frozen=True)
class TeamAge:
    age: int                 # representative age this season
    band: str                # "13-14"
    how: str                 # "graduation year 2031", "U13", "birth year 2013"


def band_for(age: int) -> str:
    for top, label in BANDS:
        if age <= top:
            return label
    return BANDS[-1][1]


def infer(name: str, today: date | None = None) -> TeamAge | None:
    """The age a team's name implies, or None when it implies nothing."""
    today = today or date.today()
    text = (name or "").strip()
    if not text:
        return None
    # U13 / 13U / U-13 / "13 and under" / "13&U"
    m = re.search(r"\b[uU]-?(\d{1,2})\b|\b(\d{1,2})\s*[uU]\b|\b(\d{1,2})\s*(?:&|and)\s*[uU](?:nder)?\b", text)
    if m:
        n = int(next(g for g in m.groups() if g))
        if 5 <= n <= 19:
            # "U13" means 13 at most: the typical player is a year under.
            return TeamAge(age=max(5, n - 1), band=band_for(n - 1), how=f"U{n}")
    # A four-digit year: future = graduation year, past = birth year.
    for y in (int(x) for x in re.findall(r"\b(19\d{2}|20\d{2})\b", text)):
        if y > today.year:
            age = GRAD_AGE - (y - today.year)
            if 5 <= age <= 19:
                return TeamAge(age=age, band=band_for(age), how=f"graduation year {y}")
        elif today.year - 19 <= y <= today.year - 5:
            age = today.year - y
            return TeamAge(age=age, band=band_for(age), how=f"birth year {y}")
    return None


def targets_for(age: int) -> dict[str, Any]:
    """The day's wall-ball reps and shots for an age, from the drill tables
    every athlete is already held to. Wall ball is the strong-hand drill's
    number (the off-hand drill has the same table); shooting is the shooting
    drill's."""
    from .drills import DRILLS_BY_KEY
    from .scoring import daily_cap_for
    wall = DRILLS_BY_KEY["lax_wall_ball_strong"]
    shot = DRILLS_BY_KEY["lax_shooting"]
    return {
        "wall_ball": daily_cap_for(wall, age),
        "shots": daily_cap_for(shot, age),
        "wall_ball_max": wall.scoring.daily_rep_cap,
        "shots_max": shot.scoring.daily_rep_cap,
    }


def suggest(name: str, today: date | None = None) -> dict[str, Any]:
    """What to prefill for a team being created, from its name alone."""
    got = infer(name, today)
    if not got:
        return {"inferred": False, "age": None, "band": "", "how": "",
                "wall_ball": None, "shots": None}
    return {"inferred": True, "age": got.age, "band": got.band, "how": got.how,
            **targets_for(got.age)}
