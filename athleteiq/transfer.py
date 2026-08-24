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

from . import sports
from typing import Any


@dataclass(frozen=True)
class Transfer:
    sport: str
    #: Completes "...which is". Written for a twelve-year-old, and specific
    #: enough to be checkable: "helps with agility" is not worth reading.
    why: str
    #: True when this athlete plays the sport. Set per-athlete by `for_drill`,
    #: never stored -- the table itself knows nothing about any one child.
    plays: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"sport": self.sport, "why": self.why, "plays": self.plays}


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
    "gen_lunge": (
        Transfer("Soccer", "every stride is one leg holding you up on its own"),
        Transfer("Basketball", "stepping through contact without losing your balance"),
        Transfer("Track", "the single-leg strength sprinting is built on"),
        Transfer("Gymnastics", "landing on one foot and staying there"),
    ),
    "gen_glute_bridge": (
        Transfer("Track", "the back of your legs is what makes you fast, not the front"),
        Transfer("Soccer", "the muscle that pulls up lame in the 80th minute"),
        Transfer("Swimming", "the kick comes from your hips"),
        Transfer("Football", "driving forward from a low position"),
    ),
    "gen_mountain_climber": (
        Transfer("Wrestling", "scrambling on the mat with your hands down"),
        Transfer("Basketball", "getting back on defence after a turnover"),
        Transfer("Rugby", "getting off the floor and back into the line"),
    ),
    "gen_tuck_jump": (
        Transfer("Volleyball", "the block jump, and the one straight after it"),
        Transfer("Basketball", "going up twice for the same rebound"),
        Transfer("Cheer", "getting the height to finish a skill cleanly"),
        Transfer("Gymnastics", "the pop off the floor a tumbling pass needs"),
    ),
    "gen_dead_bug": (
        Transfer("Gymnastics", "keeping your middle still while your limbs move"),
        Transfer("Dance", "control, which is what makes a line look effortless"),
        Transfer("Swimming", "not wriggling — a wriggle is drag"),
    ),
    "gen_wall_sit": (
        Transfer("Skiing & Snowboarding", "this is literally the position, for a whole run"),
        Transfer("Ice Hockey", "the low stance you have to hold a whole shift"),
        Transfer("Tennis", "staying loaded and ready between points"),
        Transfer("Basketball", "a defensive stance that does not stand up when you tire"),
    ),
    "gen_hollow_hold": (
        Transfer("Gymnastics", "the shape almost every skill starts and finishes in"),
        Transfer("Swimming", "holding your body flat instead of dragging"),
        Transfer("Diving", "the tight line that stops a splash"),
        Transfer("Cheer", "staying rigid while somebody else is holding you up"),
    ),
    "gen_side_plank": (
        Transfer("Tennis", "a groundstroke is your middle rotating, not your arm"),
        Transfer("Baseball", "throwing across your body without giving anything away"),
        Transfer("Ice Hockey", "taking a hit along the boards and staying up"),
        Transfer("Rugby", "staying on your feet in contact"),
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
    drill_key: str,
    home_sport: str | None = None,
    limit: int = 3,
    plays: list[str] | None = None,
) -> list[Transfer]:
    """Transfers for a drill, minus the athlete's own sport.

    A lacrosse player does not need to be told that wall ball helps at
    lacrosse. Filtering on the way out rather than storing per-sport copies
    keeps one true list per drill.

    `plays` reorders the result so the sports this athlete actually plays come
    first. "This helps in basketball" is a claim; "this helps in basketball,
    which you play on Tuesdays" is a reason. Sorting rather than filtering
    keeps the rest of the list visible, since part of the point is to make a
    single-sport kid curious about a sport they have not tried.
    """
    # Both sides go through the sport catalog rather than being compared as
    # strings. A program's sport is stored as a key (`cross_country`,
    # `hockey`), these notes are written as labels ("Track", "Ice Hockey"),
    # and a plain compare quietly shows a hockey program "Ice Hockey" in its
    # own list -- the exact noise this filter exists to remove.
    def _key(name: str | None) -> str:
        resolved = sports.normalize(name)
        return resolved.key if resolved else (name or "").strip().lower()

    home = _key(home_sport)
    out = [t for t in TRANSFERS.get(drill_key, ()) if _key(t.sport) != home]

    mine = {_key(name) for name in (plays or []) if name}
    if mine:
        out = [Transfer(t.sport, t.why, plays=_key(t.sport) in mine) for t in out]
        out.sort(key=lambda t: not t.plays)
    return out[:limit] if limit else out


def _listed(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def blurb(
    drill_key: str,
    home_sport: str | None = None,
    limit: int = 3,
    plays: list[str] | None = None,
) -> str:
    """One sentence naming the sports, for somewhere a list will not fit.

    When the athlete plays one of them, that sport leads and is called out.
    "This helps in basketball" is a claim; "this helps in basketball, which
    you play" is a reason, and the difference is whether a kid reads the rest
    of the sentence.
    """
    items = for_drill(drill_key, home_sport, limit, plays)
    if not items:
        return ""

    theirs = [t.sport for t in items if t.plays]
    rest = [t.sport for t in items if not t.plays]
    if not theirs:
        return f"This one pays off in {_listed(rest)} too."

    verb = "which you play" if len(theirs) == 1 else "both of which you play" \
        if len(theirs) == 2 else "all of which you play"
    if not rest:
        return f"This one pays off in {_listed(theirs)}, {verb}."
    return f"This one pays off in {_listed(theirs)}, {verb} — and in {_listed(rest)}."


def describe(
    drill_key: str,
    home_sport: str | None = None,
    limit: int = 3,
    plays: list[str] | None = None,
) -> dict[str, Any]:
    items = for_drill(drill_key, home_sport, limit, plays)
    return {
        "drill_key": drill_key,
        "transfers": [t.to_dict() for t in items],
        "blurb": blurb(drill_key, home_sport, limit, plays),
    }
