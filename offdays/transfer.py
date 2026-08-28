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
    # The ball drills. Short lists, like the stick drills, and for the same
    # reason: these are sport skills, and the honest transfer is the underlying
    # coordination rather than "it helps everywhere".
    "soc_juggle": (
        Transfer("Basketball", "soft first touch — the ball stops where you want it"),
        Transfer("Volleyball", "reading a ball out of the air and getting under it"),
    ),
    "bkb_dribble": (
        Transfer("Soccer", "controlling something without looking down at it"),
        Transfer("Ice Hockey", "the same hands-and-eyes-up problem, with a stick"),
    ),
    "vb_set": (
        Transfer("Basketball", "soft hands and a shot that starts from your legs"),
        Transfer("Cheer", "catching something coming down and absorbing it"),
    ),
    "bb_wall_throw": (
        Transfer("Lacrosse", "throw, catch, repeat — the same wall, a different tool"),
        Transfer("Football", "a throwing motion that starts at your feet"),
    ),
    "ten_wall_rally": (
        Transfer("Volleyball", "tracking a fast ball and getting your feet there first"),
        Transfer("Baseball", "reading a bounce early enough to do something about it"),
    ),
    # Deliberately short. These are stick-skill drills, and the honest transfer
    # is hand-eye, not "it helps everywhere".
    "lax_wall_ball": (
        Transfer("Baseball", "hands soft enough to catch something coming in hard"),
        Transfer("Hockey", "the same two-handed stick control"),
    ),
    "lax_wall_ball_strong": (
        Transfer("Baseball", "hands soft enough to catch something coming in hard"),
        Transfer("Hockey", "the same two-handed stick control"),
    ),
    "lax_wall_ball_offhand": (
        Transfer("Basketball", "a weak hand you can actually finish with"),
        Transfer("Hockey", "backhand control, which is the same problem"),
    ),
    "lax_wall_ball_one_hand": (
        Transfer("Baseball", "the top-hand grip strength a one-handed grab needs"),
        Transfer("Tennis", "wrist and forearm control through a short stroke"),
    ),
    "lax_wall_ball_cross": (
        Transfer("Basketball", "changing hands under pressure without looking"),
        Transfer("Hockey", "moving the puck across your body mid-stride"),
    ),
    # Deliberately short. Behind-the-back wall ball is hand control and not
    # much else, and inventing a third sport for it would be the padding this
    # module exists to avoid.
    "lax_wall_ball_btb": (
        Transfer("Basketball", "knowing where the ball is without watching it"),
    ),
    "lax_wall_ball_split": (
        Transfer("Basketball", "a crossover that actually changes a defender's feet"),
        Transfer("Soccer", "planting hard and going the other way"),
        Transfer("Football", "the jab step and cut"),
    ),
    "lax_faceoff_clamp": (
        Transfer("Wrestling", "the same low stance and the same fight for "
                              "position from it"),
        Transfer("Football", "a lineman's first step off the snap"),
    ),
    "lax_ground_ball": (
        Transfer("Baseball", "fielding a grounder — the same low body, same funnel"),
        Transfer("Soccer", "getting low to a loose ball first"),
        Transfer("Wrestling", "the level change is the same movement"),
    ),
    "bb_long_toss": (
        Transfer("Lacrosse", "an overhand shot on the run"),
        Transfer("Football", "a quarterback's deep ball, same chain"),
        Transfer("Tennis", "the serve is this motion with a racket in it"),
    ),
    "bb_quick_hands": (
        Transfer("Basketball", "catch and release with no wasted motion"),
        Transfer("Volleyball", "clean hands on a ball arriving fast"),
    ),
    "bb_tee_swing": (
        Transfer("Golf", "the same rotation, held lower"),
        Transfer("Hockey", "a slap shot is this swing on ice"),
        Transfer("Lacrosse", "shooting through your hips rather than your arms"),
    ),
    "bb_fielding": (
        Transfer("Lacrosse", "ground balls -- the same low body, same funnel"),
        Transfer("Tennis", "getting down to a low ball and staying balanced"),
        Transfer("Soccer", "a defender's low, side-on base"),
    ),
    "bb_catcher_stance": (
        Transfer("Wrestling", "the same low base, and the same burning legs"),
        Transfer("Basketball", "a defensive stance held far too long"),
    ),
    "sb_windmill": (
        Transfer("Volleyball", "a serve loads the shoulder the same way"),
        Transfer("Track", "the throwing events reward the same repeatability"),
    ),
    "ten_alternate": (
        Transfer("Basketball", "changing hands under pressure"),
        Transfer("Lacrosse", "switching hands on the move"),
    ),
    "ten_one_wing": (
        Transfer("Lacrosse", "off-hand wall ball -- grooving the side you avoid"),
        Transfer("Soccer", "your weak foot, for the same reason"),
    ),
    "ten_volley": (
        Transfer("Volleyball", "blocking hands, quick and without a swing"),
        Transfer("Basketball", "catch and release with no wasted motion"),
    ),
    "ten_serve": (
        Transfer("Volleyball", "a serve is this motion without a racket"),
        Transfer("Baseball", "the same overhead chain, and the same shoulder"),
        Transfer("Basketball", "the overhead outlet pass"),
    ),
    "ten_split_step": (
        Transfer("Volleyball", "the hop a libero lands from before every dig"),
        Transfer("Basketball", "being stopped before a closeout arrives"),
        Transfer("Soccer", "a keeper's set position before a shot"),
    ),
    "ten_recovery": (
        Transfer("Basketball", "a defensive slide is this exact movement"),
        Transfer("Soccer", "jockeying a winger without turning your hips"),
        Transfer("Lacrosse", "a defender's approach and break down"),
    ),
    "rug_quick_hands": (
        Transfer("Basketball", "moving the ball before the defence resets"),
        Transfer("Netball", "very nearly the same pass, on the same clock"),
    ),
    "rug_wall_pass": (
        Transfer("Lacrosse", "the same reason to give your weak side the reps"),
        Transfer("Basketball", "a chest pass, thrown further"),
        Transfer("Hockey", "the same hands crossing the body, on a stick"),
    ),
    "rug_spin_pass": (
        Transfer("Baseball", "rotation through the hips rather than the arms"),
        Transfer("Football", "the ball travels because your body turned"),
    ),
    "fb_quick_release": (
        Transfer("Basketball", "catch and shoot with no wasted motion"),
        Transfer("Baseball", "an infielder's transfer and release"),
    ),
    "fb_wall_throw": (
        Transfer("Baseball", "very nearly the same arm, on a smaller ball"),
        Transfer("Lacrosse", "throwing through your hips rather than your arm"),
        Transfer("Volleyball", "a serve loads the shoulder the same way"),
    ),
    "fb_deep_ball": (
        Transfer("Baseball", "a long toss, and the same reason to count them"),
        Transfer("Track", "the throwing events reward the same repeatability"),
    ),
    "fb_kick": (
        Transfer("Soccer", "a goal kick is this swing, from a run-up"),
        Transfer("Dance", "the same hip range, held under control"),
        Transfer("Track", "hurdling asks the same hip to open that far"),
    ),
    "fb_shuffle": (
        Transfer("Basketball", "a defensive slide is this exact movement"),
        Transfer("Tennis", "recovering to the middle without crossing over"),
        Transfer("Hockey", "walking the blue line without turning your hips"),
    ),
    "gen_pogo": (
        Transfer("Basketball", "the second jump, which is the one that rebounds"),
        Transfer("Dance", "petit allegro is this, with better feet"),
        Transfer("Track", "sprinting is a series of very short ground contacts"),
    ),
    "gen_skater_bound": (
        Transfer("Hockey", "a skating stride is a bound you never land from"),
        Transfer("Tennis", "the wide ball, and getting back from it"),
        Transfer("Soccer", "changing direction off one leg without slowing down"),
    ),
    "gen_calf_raise": (
        Transfer("Volleyball", "every block and every approach leaves from here"),
        Transfer("Basketball", "the last thing that touches the floor on a jump"),
        Transfer("Track", "sprinting is a series of these, done very fast"),
    ),
    "gen_handstand_hold": (
        Transfer("Cheer", "a base holds this shape with somebody standing on it"),
        Transfer("Swimming", "overhead position and the shoulders that hold it"),
        Transfer("Wrestling", "carrying your own weight through your arms"),
    ),
    "gen_dead_hang": (
        Transfer("Rock Climbing", "the same grip, and the same thing that fails first"),
        Transfer("Lacrosse", "hands that do not open up in a battle for the ball"),
        Transfer("Baseball", "grip strength is the quiet half of bat speed"),
    ),
    "hoc_stickhandle": (
        Transfer("Lacrosse", "the same hands, holding something heavier"),
        Transfer("Basketball", "a tight handle in a crowd, on the floor instead"),
        Transfer("Field Hockey", "very nearly the same skill, lower down"),
    ),
    "hoc_wide_handles": (
        Transfer("Lacrosse", "protecting the stick out away from your body"),
        Transfer("Basketball", "a wide crossover, and the same reach"),
    ),
    "hoc_shot": (
        Transfer("Baseball", "a swing is this rotation, held level"),
        Transfer("Golf", "the same weight transfer, the same follow-through"),
        Transfer("Lacrosse", "shooting through your hips rather than your arms"),
    ),
    "hoc_butterfly": (
        Transfer("Soccer", "a keeper getting up off the floor, over and over"),
        Transfer("Wrestling", "standing up out of a bad position, quickly"),
    ),
    "hoc_shuffle": (
        Transfer("Basketball", "a defensive slide is this exact movement"),
        Transfer("Tennis", "recovering to the middle without crossing over"),
        Transfer("Soccer", "jockeying a winger without turning your hips"),
    ),
    "hoc_stance": (
        Transfer("Basketball", "a defensive stance held far too long"),
        Transfer("Skiing", "the same knees, the same burning quads"),
    ),
    "soc_juggle_weak": (
        Transfer("Basketball", "your weak hand, and the same reason for it"),
        Transfer("Lacrosse", "off-hand wall ball -- the hard half of the work"),
    ),
    "soc_juggle_alt": (
        Transfer("Basketball", "a crossover has to work both ways too"),
        Transfer("Lacrosse", "switching hands under pressure"),
    ),
    "soc_thigh": (
        Transfer("Volleyball", "cushioning a ball rather than hitting it"),
        Transfer("Basketball", "soft hands on a hard pass"),
    ),
    "soc_wall_pass": (
        Transfer("Lacrosse", "wall ball -- the same loop, the same reason it works"),
        Transfer("Basketball", "wall passes, catch and release"),
        Transfer("Volleyball", "a first touch that sets up the second"),
    ),
    "soc_toe_taps": (
        Transfer("Basketball", "quick feet on a closeout"),
        Transfer("Tennis", "the small adjusting steps before a shot"),
    ),
    "soc_shuffle": (
        Transfer("Basketball", "a defensive slide is this exact movement"),
        Transfer("Tennis", "recovering across the baseline"),
        Transfer("Lacrosse", "a defender's approach and break down"),
    ),
    "vb_pass": (
        Transfer("Basketball", "getting your feet there instead of reaching"),
        Transfer("Tennis", "a low, still base under a ball coming fast"),
        Transfer("Soccer", "receiving with a surface you have already set"),
    ),
    "vb_set_wall": (
        Transfer("Basketball", "soft hands on a ball arriving quickly"),
        Transfer("Lacrosse", "wall ball -- the same loop, the same reason"),
    ),
    "vb_serve": (
        Transfer("Tennis", "the serve is the same motion with a racket in it"),
        Transfer("Baseball", "the same overhead chain, and the same shoulder"),
        Transfer("Lacrosse", "an overhand shot on the run"),
    ),
    "vb_arm_swing": (
        Transfer("Baseball", "the throwing arm does this exact thing"),
        Transfer("Tennis", "a serve is this swing, held differently"),
        Transfer("Basketball", "the overhead outlet pass"),
    ),
    "vb_approach": (
        Transfer("Basketball", "a two-foot rebound jump off a moving start"),
        Transfer("Track", "the long jump's last two steps are the same idea"),
        Transfer("Football", "going up for a ball with somebody on you"),
    ),
    "vb_block_jump": (
        Transfer("Basketball", "contesting a shot without fouling"),
        Transfer("Football", "a lineman's punch, standing and quick"),
    ),
    "bkb_form_shot": (
        Transfer("Volleyball", "the same overhead push, with two hands"),
        Transfer("Lacrosse", "a repeatable release, built the same slow way"),
        Transfer("Tennis", "the serve motion rewards the identical patience"),
    ),
    "bkb_slide": (
        Transfer("Tennis", "recovering across the baseline between shots"),
        Transfer("Soccer", "jockeying a winger without turning your hips"),
        Transfer("Lacrosse", "a defender's approach and break down"),
        Transfer("Hockey", "the same lateral push, on edges"),
    ),
    "bkb_crossover": (
        Transfer("Soccer", "the same push-and-go, with a foot instead of a hand"),
        Transfer("Lacrosse", "a split dodge is this move holding a stick"),
        Transfer("Football", "the jab step that makes a defender commit"),
    ),
    "bkb_between_legs": (
        Transfer("Soccer", "close control with your feet in a crowd"),
        Transfer("Lacrosse", "protecting the stick through traffic"),
    ),
    "bkb_pound_weak": (
        Transfer("Lacrosse", "off-hand wall ball — the same hard half of the work"),
        Transfer("Soccer", "your weak foot, which defenders find in about a half"),
        Transfer("Hockey", "handling on your backhand"),
    ),
    "bkb_pound_low": (
        Transfer("Soccer", "keeping the ball under you at speed"),
        Transfer("Hockey", "quick hands in tight"),
    ),
    "bkb_wall_pass": (
        Transfer("Lacrosse", "wall ball — same loop, same reason it works"),
        Transfer("Volleyball", "clean hands on a ball coming back fast"),
        Transfer("Football", "catching with your hands and not your chest"),
    ),
    "bkb_stance": (
        Transfer("Tennis", "the ready position you return serve from"),
        Transfer("Volleyball", "a libero's platform is built from this"),
        Transfer("Wrestling", "the same low base, and the same burning legs"),
        Transfer("Soccer", "staying down and side-on as a defender"),
    ),
    "lax_goalie_saves": (
        Transfer("Hockey", "a goalie's job is the same job — get the body part "
                           "nearest the puck to it first"),
        Transfer("Soccer", "keeping, and reacting to a spot rather than a ball"),
        Transfer("Tennis", "the split step and the first move to a corner"),
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
