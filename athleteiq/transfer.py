"""What a drill is worth in the other sports a kid plays.

A twelve-year-old doing lateral bounds in a driveway is being told, implicitly,
that this is lacrosse work. It is not. It is the defensive slide in basketball,
the cut to close down a winger in soccer, and covering the width of a tennis
court, and a kid who knows that is a kid who has been given a reason to keep
playing three sports instead of narrowing to one.

That matters here more than it would in an adult tool. Early single-sport
specialisation is the thing youth sports medicine most consistently warns
about, and "this only helps lacrosse" is the belief that drives it. So the
transfer note is not decoration -- it is the argument for the position gating
in `benchmarks.py`, written where an athlete will actually read it.

Two rules keep it honest:

* The athlete's own sport is never listed. Telling a lacrosse player that wall
  ball helps at lacrosse is noise, and noise is what teaches kids to skip the
  text.
* A drill that genuinely does not transfer says so. `lax_quick_stick` gets a
  short, true list rather than a padded one, because a claim a kid can check
  and find false costs every other claim on the screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Transfer:
    sport: str
    #: Completes "...which is". Written for a twelve-year-old, and specific
    #: enough to be checkable: "helps with agility" is not worth reading.
    why: str

    def to_dict(self) -> dict[str, str]:
        return {"sport": self.sport, "why": self.why}


TRANSFERS: dict[str, tuple[Transfer, ...]] = {
    "gen_lateral_bound": (
        Transfer("Basketball", "staying in front of the player you are guarding is this exact move"),
        Transfer("Soccer", "cutting across to close down a winger"),
        Transfer("Tennis", "covering the width of the court and still being balanced"),
        Transfer("Football", "a defensive back breaking on the ball"),
    ),
    "gen_high_knees": (
        Transfer("Track", "clean sprint mechanics — knees up, quick off the ground"),
        Transfer("Soccer", "the last ten yards of a chase, when form falls apart"),
        Transfer("Basketball", "getting out and gone on a fast break"),
        Transfer("Football", "driving out of a stance"),
    ),
    "gen_squat_jump": (
        Transfer("Basketball", "the second jump on a rebound, which wins most of them"),
        Transfer("Volleyball", "getting above the net to block"),
        Transfer("Soccer", "winning a header you had no right to"),
        Transfer("Track", "the takeoff in long jump and high jump"),
    ),
    "gen_squat": (
        Transfer("Track", "everything fast starts from your legs"),
        Transfer("Football", "holding your ground when someone hits you"),
        Transfer("Basketball", "staying low on defence for a whole quarter"),
        Transfer("Swimming", "the push off the wall on every turn"),
    ),
    "gen_push_up": (
        Transfer("Swimming", "the pull is what actually moves you through the water"),
        Transfer("Wrestling", "controlling someone who is pushing back"),
        Transfer("Football", "getting off a block"),
        Transfer("Basketball", "holding your spot when you get bumped"),
    ),
    "gen_pull_up": (
        Transfer("Wrestling", "pulling someone where you want them, not where they want"),
        Transfer("Swimming", "the strongest part of every stroke"),
        Transfer("Gymnastics", "every single bar skill starts here"),
        Transfer("Climbing", "your whole body hanging off your hands"),
    ),
    "gen_plank": (
        Transfer("Baseball", "a bat swing comes from your middle, not your arms"),
        Transfer("Tennis", "a serve travels from the ground up through your middle"),
        Transfer("Golf", "the same rotation, from a base that does not wobble"),
        Transfer("Soccer", "staying upright when someone leans on you"),
    ),
    "gen_sit_up": (
        Transfer("Baseball", "throwing hard is a whole-body move, not an arm move"),
        Transfer("Swimming", "holding your body flat instead of dragging"),
        Transfer("Wrestling", "getting off your back"),
    ),
    "gen_burpee": (
        Transfer("Basketball", "the fourth quarter, when everyone else is tired"),
        Transfer("Soccer", "the 80th minute"),
        Transfer("Wrestling", "the last thirty seconds of a period"),
    ),
    "gen_jumping_jack": (
        Transfer("Any sport", "it is a warm-up — feet and arms on the same beat "
                              "before you do anything harder"),
    ),
    # Deliberately short. These are stick-skill drills, and the honest transfer
    # is hand-eye, not "it helps everywhere".
    "lax_wall_ball": (
        Transfer("Baseball", "hands soft enough to catch something coming in hard"),
        Transfer("Hockey", "the same two-handed stick control"),
    ),
    "lax_quick_stick": (
        Transfer("Baseball", "turning two — catch and release without a wasted beat"),
        Transfer("Hockey", "one-touch passing"),
    ),
}


def for_drill(
    drill_key: str, home_sport: str | None = None, limit: int = 3
) -> list[Transfer]:
    """Transfers for a drill, minus the athlete's own sport.

    A lacrosse player does not need to be told that wall ball helps at
    lacrosse. Filtering on the way out rather than storing per-sport copies
    keeps one true list per drill.
    """
    home = (home_sport or "").strip().lower()
    out = [t for t in TRANSFERS.get(drill_key, ()) if t.sport.strip().lower() != home]
    return out[:limit] if limit else out


def blurb(drill_key: str, home_sport: str | None = None, limit: int = 3) -> str:
    """One sentence naming the sports, for somewhere a list will not fit."""
    names = [t.sport for t in for_drill(drill_key, home_sport, limit)]
    if not names:
        return ""
    if len(names) == 1:
        listed = names[0]
    else:
        listed = f"{', '.join(names[:-1])} and {names[-1]}"
    return f"This one pays off in {listed} too."


def describe(drill_key: str, home_sport: str | None = None, limit: int = 3) -> dict[str, Any]:
    items = for_drill(drill_key, home_sport, limit)
    return {
        "drill_key": drill_key,
        "transfers": [t.to_dict() for t in items],
        "blurb": blurb(drill_key, home_sport, limit),
    }
