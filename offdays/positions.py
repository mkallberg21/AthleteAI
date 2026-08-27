"""Canonical positions, and what a position's solo time is actually for.

Three problems sit between a `position` column and a useful benchmark, and
this module exists because the first two are usually skipped:

1. **The column is free text.** A coach importing a roster types "Middie",
   "midfield", "MF", "M" and "Mid" across five rows of the same spreadsheet.
   Exact-match SQL groups none of them together, so a position filter looks
   implemented and silently matches nobody. Everything here normalises first.

2. **A team does not have eight goalies.** Position benchmarks that need a
   full peer group only work at program scale, which makes them useless to
   the single team that just signed up. So peers widen in steps -- position,
   then position family, then simply "athletes your age" -- and the answer
   says which step it settled on rather than quietly comparing a goalie to
   a squad of midfielders.

3. **Comparison is the least useful half.** What a defender should be doing
   with a driveway hour does not depend on how many other defenders logged
   sessions this week. The `emphasis` mix below is real position guidance
   that works with a peer group of zero, on day one.

Everything here is expressed as a **share of solo time**, never as an amount.
The weekly budget in `benchmarks.py` decides how long an athlete trains; this
module only ever has an opinion about how that time is divided. A position
suggestion that reads "and also do these" would quietly undo the budget, so
suggestions are phrased as swaps and tested for it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Peer families, used when a position alone is too small to compare within.
# LSM sits with the defenders rather than the midfielders: they are defenders
# who run, and the stick work they practise is a defender's.
GROUP_LABELS = {
    "offense": "attackers and midfielders",
    "defense": "defenders",
    "specialist": "face-off specialists",
    "goalie": "goalies",
    "field": "field players",
}


@dataclass(frozen=True)
class Position:
    key: str
    label: str
    sport: str
    group: str
    aliases: tuple[str, ...]
    #: Drill key -> share of solo training time. Sums to 1.0.
    emphasis: dict[str, float]
    #: One line an athlete can act on, about what their solo time is for.
    focus: str
    #: Set where appending "s" to the label is wrong, which is most of them:
    #: a squad of Midfields is a squad of midfielders.
    plural_label: str = ""
    #: Whether weak-hand parity is a goal for this position. For a goalie it
    #: is not: their stick work is two-handed save mechanics and an outlet
    #: pass, so scoring them on left/right balance measures nothing they are
    #: trying to build.
    offhand_matters: bool = True

    @property
    def plural(self) -> str:
        if self.plural_label:
            return self.plural_label
        return f"{self.label}s" if not self.label.endswith("s") else self.label

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "sport": self.sport,
            "group": self.group,
            "focus": self.focus,
            "plural": self.plural,
            "emphasis": dict(self.emphasis),
            "offhand_matters": self.offhand_matters,
        }


def mix(**weights: float) -> dict[str, float]:
    """Turn relative weights into shares of solo time that sum to 1.

    Written this way because the alternative is a hundred hand-balanced dicts
    of decimals across sixteen sports, where one typo silently gives a
    position a mix that adds up to 0.97 and nobody ever notices. Here the
    numbers are read as "twice as much of this as that" and normalised.
    """
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("a position needs at least one drill weighted")
    return {key: value / total for key, value in weights.items()}


LACROSSE: tuple[Position, ...] = (
    Position(
        key="attack", label="Attack", sport="lacrosse", group="offense",
        aliases=("attack", "attackman", "attackmen", "attacker", "att", "a",
                 "offense", "offence", "forward"),
        emphasis={
            # Ground balls sit at the same 16% for every position on the
            # field. They are the one part of lacrosse that belongs to
            # nobody in particular, and a plan that gave an attacker a
            # third of a defender's share was quietly teaching that
            # picking the ball up is somebody else's job.
            # Dodging is the job, so the split-dodge pattern earns real weight
            # here and nowhere else on the field gets as much of it.
            "lax_ground_ball": 0.16, "lax_wall_ball": 0.13,
            "lax_wall_ball_offhand": 0.13, "lax_wall_ball_split": 0.11,
            "lax_quick_stick": 0.11, "gen_lateral_bound": 0.09,
            "lax_wall_ball_one_hand": 0.07, "gen_squat": 0.07,
            "gen_squat_jump": 0.05, "gen_plank": 0.04,
            "gen_push_up": 0.04,
        },
        plural_label="attackers",
        focus="Hands and tight-space quickness. Most of your time is stick work.",
    ),
    Position(
        key="midfield", label="Midfield", sport="lacrosse", group="offense",
        aliases=("midfield", "midfielder", "midfielders", "middie", "middy",
                 "mid", "mids", "m", "mf", "midi"),
        emphasis={
            # Ground balls sit at the same 16% for every position on the
            # field. They are the one part of lacrosse that belongs to
            # nobody in particular, and a plan that gave an attacker a
            # third of a defender's share was quietly teaching that
            # picking the ball up is somebody else's job.
            "lax_ground_ball": 0.16, "lax_wall_ball": 0.14,
            "lax_wall_ball_offhand": 0.11, "lax_wall_ball_split": 0.09,
            "gen_high_knees": 0.09, "lax_wall_ball_cross": 0.07,
            "gen_squat_jump": 0.07, "gen_lateral_bound": 0.06,
            "gen_squat": 0.06, "lax_quick_stick": 0.05,
            "gen_burpee": 0.05, "gen_plank": 0.03, "gen_push_up": 0.02,
        },
        plural_label="midfielders",
        focus="You cover more ground than anyone. Stick work plus an engine.",
    ),
    Position(
        key="defense", label="Defense", sport="lacrosse", group="defense",
        aliases=("defense", "defence", "defender", "defenders", "defenseman",
                 "defencemen", "defensemen", "d", "def", "close d",
                 "close defense", "close defence", "pole", "dpole", "d pole"),
        emphasis={
            # Ground balls sit at the same 16% for every position on the
            # field. They are the one part of lacrosse that belongs to
            # nobody in particular, and a plan that gave an attacker a
            # third of a defender's share was quietly teaching that
            # picking the ball up is somebody else's job.
            "gen_lateral_bound": 0.16, "lax_ground_ball": 0.16,
            "lax_wall_ball": 0.12, "lax_wall_ball_offhand": 0.12,
            "gen_squat": 0.12, "gen_high_knees": 0.08,
            "lax_wall_ball_one_hand": 0.06, "gen_push_up": 0.06,
            "gen_plank": 0.06, "gen_pull_up": 0.06,
        },
        plural_label="defenders",
        focus="Footwork and strength first, but a defender still needs hands.",
    ),
    Position(
        key="lsm", label="Long-Stick Midfield", sport="lacrosse", group="defense",
        aliases=("lsm", "long stick midfield", "long stick midfielder",
                 "long stick middie", "longstick", "long pole", "long pole midfield",
                 "d mid", "dmid", "d midfield", "defensive midfield",
                 "defensive midfielder"),
        emphasis={
            # Ground balls sit at the same 16% for every position on the
            # field. They are the one part of lacrosse that belongs to
            # nobody in particular, and a plan that gave an attacker a
            # third of a defender's share was quietly teaching that
            # picking the ball up is somebody else's job.
            "gen_lateral_bound": 0.16, "lax_ground_ball": 0.16,
            "lax_wall_ball": 0.13, "lax_wall_ball_offhand": 0.10,
            "gen_high_knees": 0.10, "gen_squat": 0.10, "gen_burpee": 0.08,
            "gen_squat_jump": 0.07, "lax_wall_ball_one_hand": 0.05,
            "gen_plank": 0.03, "gen_push_up": 0.02,
        },
        plural_label="long-stick midfielders",
        focus="A defender's job at a midfielder's pace. Ground balls and legs.",
    ),
    Position(
        key="fogo", label="Face-Off", sport="lacrosse", group="specialist",
        aliases=("fogo", "faceoff", "face off", "face-off", "faceoff specialist",
                 "fo", "fogos", "draw", "draw specialist", "draw control"),
        emphasis={
            # Ground balls sit at the same 16% for every position on the
            # field. They are the one part of lacrosse that belongs to
            # nobody in particular, and a plan that gave an attacker a
            # third of a defender's share was quietly teaching that
            # picking the ball up is somebody else's job.
            "lax_faceoff_clamp": 0.26, "lax_ground_ball": 0.16,
            "lax_quick_stick": 0.10, "gen_squat_jump": 0.09,
            "lax_wall_ball_one_hand": 0.08, "gen_plank": 0.07,
            "lax_wall_ball": 0.06, "gen_pull_up": 0.06,
            "lax_wall_ball_offhand": 0.04, "gen_push_up": 0.04,
            "gen_burpee": 0.02, "gen_lateral_bound": 0.02,
        },
        plural_label="face-off specialists",
        focus="One explosive move, repeated. Grip, core and a fast first step.",
    ),
    Position(
        key="goalie", label="Goalie", sport="lacrosse", group="goalie",
        aliases=("goalie", "goalies", "goal", "goalkeeper", "goaltender",
                 "keeper", "gk", "g", "netminder", "net"),
        emphasis={
            # Ground balls sit at the same 16% for every position on the
            # field. They are the one part of lacrosse that belongs to
            # nobody in particular, and a plan that gave an attacker a
            # third of a defender's share was quietly teaching that
            # picking the ball up is somebody else's job.
            # Save positions lead. Until that drill existed this mix was
            # entirely made of substitutes -- stick work and lateral jumps
            # standing in for a position whose actual job the app could not
            # see -- so a goalie was the one athlete here being handed
            # somebody else's practice.
            #
            # Off-hand work is prescribed here like everywhere else. The old
            # reasoning was that a goalie's hands do not swap on the stick,
            # which is true of the grip and false of the job: a save is made
            # with both hands, the outlet that follows it is a real throw,
            # and a keeper who can only clear to one side is a keeper the
            # ride aims at.
            "lax_goalie_saves": 0.23, "lax_ground_ball": 0.16,
            "lax_quick_stick": 0.13, "gen_lateral_bound": 0.11,
            "lax_wall_ball_offhand": 0.08, "lax_wall_ball": 0.07,
            "gen_plank": 0.07, "lax_wall_ball_one_hand": 0.05,
            "gen_squat_jump": 0.05, "gen_squat": 0.03,
            "gen_push_up": 0.02,
        },
        plural_label="goalies",
        focus="Both hands, reactions and a hard first step sideways.",
    ),
)

#: Used when the sport has no position model, or the athlete has not given one.
#: An even spread rather than a guess -- it should read as "no opinion yet",
#: which is honest, rather than as a recommendation nobody chose.
GENERIC = Position(
    key="general", label="Athlete", sport="general", group="field",
    aliases=(),
    emphasis={
        "gen_squat": 0.15, "gen_push_up": 0.15, "gen_plank": 0.12,
        "gen_lateral_bound": 0.12, "gen_high_knees": 0.12,
        "gen_squat_jump": 0.12, "gen_burpee": 0.12, "gen_sit_up": 0.10,
    },
    focus="General athleticism: move well, in every direction.",
)

# ---------------------------------------------------------------------------
# The other sports
#
# Weak-hand parity is computed from the left/right split a drill reports, so it
# is offered exactly where a position's plan contains a drill that reports one
# and where the two sides are genuinely both worth building.
#
# That used to read "a lacrosse-only comparison ... the only drills that report
# a split are the two stick drills", which stopped being true once every sport's
# own skill drill was actually prescribed. Juggling reports which foot and
# dribbling reports which hand, and both are things a coach would want levelled.
#
# It stays off in three places, and each is a judgement rather than an oversight:
#
#   baseball / softball -- wall throws report an arm, but bilateral throwing is
#       not a goal in these sports, it is a way to hurt a growing elbow. The one
#       thing here that should not be encouraged toward parity.
#   tennis -- the wall rally reports a hand, but a player has one racket hand.
#       The two wings that matter are forehand and backhand, which this does not
#       measure and should not pretend to.
#   volleyball and everything with no reporting drill -- there is no split to
#       compare, and a metric that would read zero for every child is a metric
#       that ranks them on nothing.
# ---------------------------------------------------------------------------

#: Sports where both sides are genuinely worth building AND a prescribed drill
#: reports the split. Checked against the catalogue by `test_positions.py`, so
#: adding a sport here without the drill to back it fails rather than shipping a
#: comparison that reads zero for everyone.
BILATERAL_SPORTS = frozenset({"lacrosse", "soccer", "basketball"})


def _pos(key, label, sport, group, aliases, emphasis, focus, plural=""):
    return Position(
        key=key, label=label, sport=sport, group=group, aliases=aliases,
        emphasis=emphasis, focus=focus, plural_label=plural,
        offhand_matters=sport in BILATERAL_SPORTS,
    )


# Basketball plans lead on basketball, the way lacrosse does. Weak-hand pound
# carries real weight in all three: it is the one drill here whose pattern the
# app can genuinely confirm, and the hand nobody practises is the hand a
# defender plays. The defensive stance is the only conditioning work that is
# actually the sport rather than a substitute for it.
BASKETBALL: tuple[Position, ...] = (
    _pos("guard", "Guard", "basketball", "perimeter",
         ("guard", "point guard", "pg", "shooting guard", "sg", "combo guard", "g", "1", "2"),
         mix(bkb_form_shot=5, bkb_dribble=4, bkb_crossover=4, bkb_pound_weak=3,
             bkb_slide=3, bkb_pound_low=2, bkb_stance=2, bkb_between_legs=2,
             bkb_wall_pass=2, gen_lateral_bound=2, gen_high_knees=2,
             gen_squat_jump=2, gen_lunge=1),
         "Change direction, then change it again. Low, quick and never upright.",
         "guards"),
    _pos("wing", "Wing", "basketball", "perimeter",
         ("wing", "forward", "small forward", "sf", "3", "swing"),
         mix(bkb_form_shot=5, bkb_dribble=3, bkb_slide=3, bkb_crossover=3,
             bkb_pound_weak=3, bkb_wall_pass=2, bkb_stance=2, bkb_pound_low=2,
             gen_lateral_bound=2, gen_squat_jump=2, gen_lunge=2, gen_push_up=2,
             gen_tuck_jump=2),
         "Guard anyone, rebound anyway. Jumping and lateral work together.",
         "wings"),
    _pos("post", "Post", "basketball", "frontcourt",
         ("post", "center", "centre", "c", "power forward", "pf", "4", "5", "big"),
         # A post still needs a handle -- the modern game asks them to face up
         # and put it on the floor -- but strength stays the priority, so the
         # ball work here is the two drills that survive contact.
         mix(bkb_form_shot=3, bkb_pound_weak=3, bkb_wall_pass=2, bkb_slide=2,
             bkb_dribble=2, bkb_stance=2,
             gen_squat=4, gen_squat_jump=4, gen_tuck_jump=3, gen_push_up=3,
             gen_lunge=3, gen_side_plank=2, gen_glute_bridge=2,
             gen_lateral_bound=1),
         "Hold your ground, then go up twice. Strength before anything else.",
         "posts"),
)

# Soccer plans lead on soccer. Weak-foot work appears in every outfield plan,
# because it is the one thing here the app can genuinely confirm and the foot
# nobody practises is the foot a defender shows you.
SOCCER: tuple[Position, ...] = (
    _pos("goalkeeper", "Goalkeeper", "soccer", "goalie",
         ("goalkeeper", "keeper", "gk", "goalie", "goal", "1"),
         mix(soc_wall_pass=5, soc_juggle=3, soc_juggle_weak=2, soc_toe_taps=2,
             gen_lateral_bound=4, gen_squat_jump=3, gen_push_up=2, gen_lunge=2,
             gen_side_plank=2, gen_plank=2, gen_burpee=1),
         "Explode sideways off one foot, then get straight back up.",
         "goalkeepers"),
    _pos("defender", "Defender", "soccer", "defence",
         ("defender", "defence", "defense", "centre back", "center back", "cb",
          "full back", "fullback", "lb", "rb", "back", "d"),
         mix(soc_shuffle=5, soc_wall_pass=4, soc_juggle=3, soc_juggle_weak=2,
             soc_toe_taps=2, gen_lateral_bound=3, gen_squat=2, gen_lunge=2,
             gen_high_knees=2, gen_glute_bridge=2, gen_plank=1, gen_side_plank=1),
         "Turn and go with someone quicker than you, over and over.",
         "defenders"),
    _pos("midfielder", "Midfielder", "soccer", "midfield",
         ("midfielder", "midfield", "mid", "cm", "cdm", "cam", "m", "8", "6", "10"),
         mix(soc_wall_pass=5, soc_juggle_alt=4, soc_juggle=3, soc_toe_taps=3,
             soc_juggle_weak=3, soc_thigh=2, soc_shuffle=2,
             gen_high_knees=3, gen_burpee=2, gen_lunge=2, gen_glute_bridge=2,
             gen_squat=1, gen_plank=1),
         "You run further than anyone on the pitch. Build the engine.",
         "midfielders"),
    _pos("forward", "Forward", "soccer", "attack",
         ("forward", "striker", "st", "cf", "winger", "wing", "attacker", "9", "7", "11"),
         mix(soc_toe_taps=4, soc_juggle_alt=4, soc_juggle=3, soc_juggle_weak=3,
             soc_wall_pass=3, soc_thigh=2,
             gen_squat_jump=3, gen_high_knees=3, gen_lateral_bound=2,
             gen_lunge=2, gen_glute_bridge=2, gen_squat=1),
         "First five yards, and being able to do it again in the 80th minute.",
         "forwards"),
)

# Volleyball plans lead on volleyball. Every position passes and every position
# serves, so both appear in all four -- the libero heaviest on passing, and the
# serve kept modest everywhere because it is the one action in this sport that
# lands on the throwing axis.
VOLLEYBALL: tuple[Position, ...] = (
    _pos("setter", "Setter", "volleyball", "back",
         ("setter", "s", "set"),
         mix(vb_set=6, vb_set_wall=4, vb_pass=3, vb_serve=2, vb_block_jump=2,
             gen_lateral_bound=3, gen_squat_jump=2, gen_plank=2, gen_lunge=2,
             gen_push_up=2, gen_side_plank=1, gen_dead_bug=1),
         "Get to the ball early and be balanced when you arrive.",
         "setters"),
    _pos("hitter", "Hitter", "volleyball", "front",
         ("hitter", "outside", "outside hitter", "oh", "opposite", "opp", "right side",
          "rs", "attacker", "spiker"),
         # The approach carries the most weight and the most load in the whole
         # catalogue, which is the honest shape of this position: jumper's knee
         # is what this sport hands teenagers.
         mix(vb_approach=5, vb_arm_swing=4, vb_pass=3, vb_serve=2, vb_set=2,
             gen_tuck_jump=3, gen_squat_jump=2, gen_squat=2, gen_lunge=2,
             gen_hollow_hold=2, gen_glute_bridge=2, gen_side_plank=1),
         "Jump high, land safe, do it forty more times.",
         "hitters"),
    _pos("middle", "Middle Blocker", "volleyball", "front",
         ("middle", "middle blocker", "mb", "middle hitter", "blocker"),
         mix(vb_block_jump=5, vb_approach=4, vb_arm_swing=3, vb_pass=2, vb_serve=2,
             gen_lateral_bound=3, gen_tuck_jump=3, gen_squat=2, gen_squat_jump=2,
             gen_glute_bridge=2, gen_side_plank=1, gen_plank=1),
         "Sideways along the net, then straight up. Both, every rally.",
         "middle blockers"),
    _pos("libero", "Libero", "volleyball", "back",
         ("libero", "l", "ds", "defensive specialist", "back row"),
         # The one position that never hits, so no approach and no arm swing --
         # and the only one where passing leads outright.
         mix(vb_pass=7, vb_set=3, vb_serve=2,
             gen_lateral_bound=4, gen_wall_sit=2, gen_lunge=2,
             gen_mountain_climber=2, gen_burpee=2, gen_plank=2, gen_squat=1,
             gen_high_knees=1),
         "Low the whole time, and off the floor fast when you hit it.",
         "liberos"),
)

BASEBALL_POSITIONS = (
    # Shared by baseball and softball -- the plans are the same work, and a
    # softball player throwing at a wall is doing the same drill whatever the
    # key is prefixed with.
    #
    # Wall throws sit lowest for the pitcher on purpose. They cost a full throw
    # per rep against the shoulder, and a solo plan that quietly adds throwing
    # volume to a twelve-year-old pitcher's week is the exact thing the load
    # model exists to prevent.
    ("pitcher", "Pitcher", ("pitcher", "p", "rhp", "lhp", "starter", "reliever"),
     mix(bb_long_toss=2, bb_wall_throw=1, bb_fielding=2, bb_tee_swing=2,
         gen_glute_bridge=4, gen_side_plank=4, gen_lunge=3, gen_dead_bug=3,
         gen_squat=2, gen_plank=2, gen_push_up=1),
     "Everything you throw comes up from the ground through your middle.",
     "pitchers"),
    ("catcher", "Catcher", ("catcher", "c", "backstop"),
     mix(bb_catcher_stance=5, bb_quick_hands=4, bb_wall_throw=2, bb_tee_swing=3,
         bb_fielding=2, gen_wall_sit=3, gen_squat=3, gen_lunge=2,
         gen_glute_bridge=2, gen_side_plank=2, gen_push_up=1),
     "You are in a squat for two hours. Build legs that can take it.",
     "catchers"),
    ("infield", "Infield", ("infield", "infielder", "shortstop", "ss", "second base",
                            "2b", "third base", "3b", "first base", "1b", "middle infield"),
     mix(bb_fielding=5, bb_quick_hands=4, bb_tee_swing=3, bb_wall_throw=2,
         gen_lateral_bound=4, gen_wall_sit=2, gen_lunge=2, gen_side_plank=2,
         gen_squat=2, gen_glute_bridge=1, gen_plank=1),
     "First step sideways, low hands, and a throw from anywhere.",
     "infielders"),
    ("outfield", "Outfield", ("outfield", "outfielder", "center field", "cf",
                              "left field", "lf", "right field", "rf"),
     mix(bb_long_toss=4, bb_tee_swing=3, bb_fielding=3, bb_wall_throw=2,
         gen_high_knees=4, gen_glute_bridge=3, gen_squat_jump=3, gen_lunge=2,
         gen_lateral_bound=2, gen_side_plank=1, gen_squat=1),
     "Long sprints from standing, then throw hard at the end of one.",
     "outfielders"),
)

BASEBALL: tuple[Position, ...] = tuple(
    _pos(k, label, "baseball", "field" if k in ("infield", "outfield") else k,
         aliases, emphasis, focus, plural)
    for k, label, aliases, emphasis, focus, plural in BASEBALL_POSITIONS
)

#: Softball shares baseball's plans everywhere except the mound.
#:
#: A windmill pitch is a full underhand arm circle -- a different motion from an
#: overhand throw, loading a different part of the shoulder, and the single
#: highest-volume action anyone on a softball field performs. Handing a softball
#: pitcher a baseball pitcher's plan was the same mistake as handing a goalie a
#: midfielder's, and it hid the one number in this sport most worth counting.
SOFTBALL_PITCHER = mix(
    sb_windmill=5, bb_fielding=2, bb_tee_swing=2, bb_wall_throw=1,
    gen_glute_bridge=4, gen_side_plank=4, gen_lunge=3, gen_dead_bug=3,
    gen_squat=2, gen_plank=2,
)

SOFTBALL: tuple[Position, ...] = tuple(
    _pos(k, label, "softball", "field" if k in ("infield", "outfield") else k,
         aliases,
         SOFTBALL_PITCHER if k == "pitcher" else emphasis,
         focus, plural)
    for k, label, aliases, emphasis, focus, plural in BASEBALL_POSITIONS
)

CHEER: tuple[Position, ...] = (
    _pos("base", "Base", "cheer", "bases",
         ("base", "main base", "side base", "bases"),
         mix(gen_squat=5, gen_wall_sit=3, gen_lunge=3, gen_push_up=3,
             gen_side_plank=3, gen_glute_bridge=2, gen_plank=2, gen_dead_bug=1),
         "Someone else's safety is your legs and your grip. Strength first.",
         "bases"),
    _pos("flyer", "Flyer", "cheer", "flyers",
         ("flyer", "flier", "top girl", "top"),
         mix(gen_hollow_hold=5, gen_side_plank=4, gen_dead_bug=3, gen_plank=3,
             gen_lunge=2, gen_glute_bridge=2, gen_wall_sit=2, gen_tuck_jump=1),
         "Stay tight and still. Everything is core control and balance.",
         "flyers"),
    _pos("backspot", "Backspot", "cheer", "bases",
         ("backspot", "back spot", "back", "spotter"),
         mix(gen_squat=4, gen_glute_bridge=3, gen_side_plank=3, gen_push_up=3,
             gen_plank=3, gen_lunge=3, gen_dead_bug=2, gen_wall_sit=2),
         "You catch what goes wrong. Strong back, strong middle, quick feet.",
         "backspots"),
    _pos("tumbler", "Tumbler", "cheer", "tumbling",
         ("tumbler", "tumbling", "tumble"),
         mix(gen_hollow_hold=4, gen_tuck_jump=4, gen_squat_jump=3, gen_push_up=3,
             gen_dead_bug=2, gen_lunge=2, gen_glute_bridge=2, gen_side_plank=2),
         "Pop off the floor, then hold a shape in the air.",
         "tumblers"),
)

DANCE: tuple[Position, ...] = (
    _pos("ballet", "Ballet", "dance", "technique",
         ("ballet", "classical", "pointe"),
         mix(gen_lunge=4, gen_hollow_hold=3, gen_glute_bridge=3, gen_dead_bug=3,
             gen_side_plank=3, gen_wall_sit=2, gen_plank=2, gen_squat=2),
         "Control and single-leg strength. Effortless is built, not born.",
         "ballet dancers"),
    _pos("contemporary", "Contemporary", "dance", "technique",
         ("contemporary", "modern", "lyrical", "jazz"),
         mix(gen_lunge=4, gen_glute_bridge=3, gen_hollow_hold=3, gen_side_plank=3,
             gen_squat_jump=2, gen_dead_bug=2, gen_push_up=2, gen_plank=2),
         "Getting to the floor and back up without it costing you anything.",
         "contemporary dancers"),
    _pos("hip_hop", "Hip Hop", "dance", "power",
         ("hip hop", "hiphop", "street", "breaking", "b boy", "b girl"),
         mix(gen_squat_jump=4, gen_push_up=4, gen_mountain_climber=3, gen_plank=3,
             gen_burpee=2, gen_lunge=2, gen_hollow_hold=2, gen_side_plank=2),
         "Power off the floor and weight through your hands.",
         "hip hop dancers"),
    _pos("pom", "Pom & Team", "dance", "power",
         ("pom", "poms", "dance team", "kick", "drill team"),
         mix(gen_tuck_jump=4, gen_lunge=3, gen_hollow_hold=3, gen_squat_jump=3,
             gen_glute_bridge=3, gen_dead_bug=2, gen_side_plank=2, gen_squat=1),
         "Sharp, high, and identical to the seven people next to you.",
         "pom dancers"),
)

SWIMMING: tuple[Position, ...] = (
    _pos("sprint", "Sprint Freestyle", "swimming", "sprint",
         ("sprint", "sprinter", "freestyle", "free", "50", "100", "sprint free"),
         mix(gen_squat_jump=4, gen_pull_up=4, gen_hollow_hold=3, gen_push_up=3,
             gen_glute_bridge=2, gen_dead_bug=2, gen_side_plank=2, gen_squat=2),
         "The start and the walls. Explosive legs and a strong pull.",
         "sprinters"),
    _pos("distance", "Distance", "swimming", "distance",
         ("distance", "distance free", "500", "1000", "1650", "mid distance", "open water"),
         mix(gen_pull_up=4, gen_hollow_hold=4, gen_plank=3, gen_dead_bug=3,
             gen_glute_bridge=3, gen_push_up=2, gen_side_plank=2, gen_squat=1),
         "Hold your line when you are tired. That is where races are lost.",
         "distance swimmers"),
    _pos("stroke", "Stroke", "swimming", "stroke",
         ("stroke", "butterfly", "fly", "backstroke", "back", "breaststroke", "breast", "im"),
         mix(gen_pull_up=4, gen_hollow_hold=4, gen_push_up=3, gen_side_plank=3,
             gen_glute_bridge=3, gen_squat_jump=2, gen_dead_bug=2, gen_plank=1),
         "Shoulders that last and a middle that does not wriggle.",
         "stroke swimmers"),
)

TRACK: tuple[Position, ...] = (
    _pos("sprints", "Sprints", "track", "speed",
         ("sprints", "sprint", "sprinter", "100", "200", "400", "relay", "hurdles", "hurdler"),
         mix(gen_high_knees=5, gen_glute_bridge=4, gen_squat_jump=3, gen_lunge=3,
             gen_hollow_hold=2, gen_squat=2, gen_dead_bug=1, gen_side_plank=1),
         "Knees up, ground contact short, hamstrings strong enough to take it.",
         "sprinters"),
    _pos("middle_distance", "Middle Distance", "track", "endurance",
         ("middle distance", "mid distance", "800", "1500", "mile", "1600"),
         mix(gen_high_knees=4, gen_lunge=4, gen_glute_bridge=3, gen_burpee=2,
             gen_plank=2, gen_side_plank=2, gen_dead_bug=2, gen_squat=2),
         "Form that holds when it hurts, and legs that hold you up on one foot.",
         "middle distance runners"),
    _pos("distance", "Distance", "track", "endurance",
         ("distance", "3200", "5000", "10000", "3k", "5k", "10k", "steeple"),
         mix(gen_lunge=4, gen_glute_bridge=4, gen_side_plank=3, gen_dead_bug=3,
             gen_plank=2, gen_high_knees=2, gen_squat=2, gen_wall_sit=1),
         "Single-leg strength and hip control. That is what stops injuries.",
         "distance runners"),
    _pos("jumps", "Jumps", "track", "power",
         ("jumps", "jumper", "long jump", "high jump", "triple jump", "pole vault", "vault"),
         mix(gen_squat_jump=5, gen_tuck_jump=4, gen_lunge=3, gen_glute_bridge=3,
             gen_hollow_hold=2, gen_squat=2, gen_lateral_bound=2, gen_side_plank=1),
         "One foot, all your speed, straight up. Land it safely too.",
         "jumpers"),
    _pos("throws", "Throws", "track", "power",
         ("throws", "thrower", "shot", "shot put", "discus", "javelin", "hammer"),
         mix(gen_squat=5, gen_side_plank=4, gen_push_up=3, gen_glute_bridge=3,
             gen_dead_bug=3, gen_lunge=2, gen_squat_jump=2, gen_pull_up=2),
         "Legs and rotation. The arm is the last thing that happens.",
         "throwers"),
)

FOOTBALL: tuple[Position, ...] = (
    _pos("quarterback", "Quarterback", "football", "skill",
         ("quarterback", "qb", "signal caller"),
         mix(gen_side_plank=4, gen_lunge=3, gen_glute_bridge=3, gen_dead_bug=3,
             gen_lateral_bound=3, gen_squat=2, gen_plank=2, gen_push_up=1),
         "Throw from a base that does not move, and move when it has to.",
         "quarterbacks"),
    _pos("skill", "Running Back & Receiver", "football", "skill",
         ("running back", "rb", "halfback", "tailback", "fullback", "wide receiver",
          "wr", "receiver", "tight end", "te", "slot", "athlete"),
         mix(gen_lateral_bound=4, gen_high_knees=4, gen_squat_jump=3, gen_lunge=3,
             gen_glute_bridge=3, gen_squat=2, gen_plank=1, gen_mountain_climber=1),
         "Cut without slowing down, and be there again the next play.",
         "skill players"),
    _pos("line", "Line", "football", "line",
         ("offensive line", "o line", "ol", "lineman", "line", "guard", "tackle",
          "center", "defensive line", "d line", "dl", "defensive end", "de", "nose"),
         mix(gen_squat=5, gen_push_up=4, gen_lunge=3, gen_wall_sit=3,
             gen_glute_bridge=3, gen_side_plank=2, gen_plank=2, gen_burpee=1),
         "Low, strong, and still strong in the fourth quarter.",
         "linemen"),
    _pos("linebacker", "Linebacker", "football", "front_seven",
         ("linebacker", "lb", "mike", "will", "sam", "backer"),
         mix(gen_lateral_bound=4, gen_squat=3, gen_burpee=3, gen_lunge=3,
             gen_mountain_climber=3, gen_squat_jump=2, gen_plank=2, gen_push_up=2),
         "Read it, then be somewhere else fast. Sideways more than forwards.",
         "linebackers"),
    _pos("defensive_back", "Defensive Back", "football", "secondary",
         ("defensive back", "db", "cornerback", "corner", "cb", "safety", "free safety",
          "strong safety", "nickel"),
         mix(gen_lateral_bound=5, gen_high_knees=4, gen_squat_jump=3, gen_lunge=3,
             gen_glute_bridge=3, gen_plank=1, gen_squat=1, gen_side_plank=1),
         "Backpedal, flip your hips, and run with someone who knows where they are going.",
         "defensive backs"),
)

GYMNASTICS: tuple[Position, ...] = (
    _pos("all_around", "All Around", "gymnastics", "all",
         ("all around", "all-around", "aa", "all rounder"),
         mix(gen_hollow_hold=4, gen_pull_up=4, gen_push_up=3, gen_tuck_jump=3,
             gen_side_plank=2, gen_dead_bug=2, gen_lunge=2, gen_squat_jump=2),
         "Everything at once. Hollow shape, pulling strength, and a pop off the floor.",
         "all-arounders"),
    _pos("bars", "Bars & Rings", "gymnastics", "upper",
         ("bars", "uneven bars", "ub", "high bar", "rings", "parallel bars", "pommel"),
         mix(gen_pull_up=6, gen_hollow_hold=4, gen_push_up=3, gen_dead_bug=2,
             gen_side_plank=2, gen_plank=2, gen_glute_bridge=1),
         "Your whole body hangs off your hands, and stays in one shape while it does.",
         "bars gymnasts"),
    _pos("floor_vault", "Floor & Vault", "gymnastics", "power",
         ("floor", "vault", "tumbling", "fx", "vt"),
         mix(gen_tuck_jump=5, gen_squat_jump=4, gen_hollow_hold=3, gen_lunge=3,
             gen_push_up=2, gen_glute_bridge=2, gen_dead_bug=2, gen_side_plank=1),
         "Speed into power, then a shape held tight in the air.",
         "floor gymnasts"),
    _pos("beam", "Beam", "gymnastics", "balance",
         ("beam", "balance beam", "bb"),
         mix(gen_lunge=4, gen_hollow_hold=4, gen_dead_bug=3, gen_side_plank=3,
             gen_glute_bridge=3, gen_plank=2, gen_tuck_jump=2, gen_wall_sit=1),
         "Single-leg control and a middle that does not wobble.",
         "beam gymnasts"),
)

# Two positions in this sport rather than four, and they are genuinely
# different jobs: a singles player covers ground and grooves groundstrokes, a
# doubles player lives inside two steps of the net. Both serve, and both get the
# split step, because it is the one movement that precedes every shot either of
# them will ever hit.
TENNIS: tuple[Position, ...] = (
    _pos("singles", "Singles", "tennis", "court",
         ("singles", "single", "baseline", "baseliner"),
         mix(ten_alternate=4, ten_one_wing=4, ten_wall_rally=3, ten_recovery=3,
             ten_split_step=3, ten_serve=2, ten_volley=1,
             gen_lateral_bound=3, gen_side_plank=2, gen_lunge=2,
             gen_high_knees=2, gen_glute_bridge=1),
         "Cover the width of the court, then hit a ball while balanced.",
         "singles players"),
    _pos("doubles", "Doubles", "tennis", "court",
         ("doubles", "double", "net", "serve volley", "volleyer"),
         # The net position, so volleys lead and the long grooving rallies give
         # way to reactions inside two steps.
         mix(ten_volley=5, ten_split_step=4, ten_serve=3, ten_alternate=2,
             ten_wall_rally=2, ten_recovery=2, ten_one_wing=1,
             gen_lateral_bound=3, gen_squat_jump=2, gen_side_plank=2,
             gen_lunge=2, gen_push_up=1, gen_wall_sit=1),
         "Short, sharp, reactive. Most of it happens inside two steps.",
         "doubles players"),
)

CROSS_COUNTRY: tuple[Position, ...] = (
    _pos("distance", "Distance Runner", "cross_country", "endurance",
         ("distance", "runner", "distance runner", "harrier", "5k", "varsity", "jv"),
         mix(gen_lunge=4, gen_glute_bridge=4, gen_side_plank=3, gen_dead_bug=3,
             gen_plank=2, gen_high_knees=2, gen_squat=2, gen_wall_sit=1),
         "Hills and single-leg strength. Most running injuries start at the hip.",
         "distance runners"),
)

# Four positions rather than three, because a centre and a winger want
# genuinely different driveway hours: a centre handles the puck in traffic all
# night, a winger shoots. Everything here is off-ice, which is not a compromise
# -- it is what a hockey player's hour at home has always actually been.
#
# `offhand_matters` is False for every one of them, and that is a real
# statement rather than an oversight. A hockey player holds the stick the same
# way for their entire life; scoring them on left/right hand balance would
# measure nothing they are trying to build. Their weak side is the backhand,
# and `sweep.py` reports it from the width of the sweep instead.
HOCKEY: tuple[Position, ...] = (
    _pos("centre", "Centre", "hockey", "skaters",
         ("centre", "center", "c", "centreman", "centerman", "1c", "2c"),
         # The most puck touches of anyone on the ice, and the most of them in
         # a crowd, so the tight handle carries more weight here than anywhere.
         mix(hoc_stickhandle=5, hoc_wide_handles=3, hoc_shot=3, hoc_shuffle=2,
             hoc_stance=2, gen_lateral_bound=4, gen_wall_sit=2, gen_lunge=2,
             gen_glute_bridge=2, gen_side_plank=2, gen_squat=2),
         "More puck touches than anyone, most of them in traffic. Hands first.",
         "centres"),
    _pos("winger", "Winger", "hockey", "skaters",
         ("winger", "wing", "lw", "rw", "left wing", "right wing", "w", "forward", "f"),
         # The shot leads. A winger's job on most shifts ends with one.
         mix(hoc_shot=5, hoc_stickhandle=3, hoc_wide_handles=3, hoc_stance=2,
             hoc_shuffle=1, gen_lateral_bound=4, gen_squat_jump=3, gen_squat=2,
             gen_lunge=2, gen_glute_bridge=2, gen_side_plank=1),
         "Get open, and be ready to shoot the first time it arrives.",
         "wingers"),
    _pos("defence", "Defence", "hockey", "skaters",
         ("defence", "defense", "defenceman", "defenseman", "d", "blue line",
          "blueliner", "dman"),
         # Slides lead: walking the blue line and holding a gap are both the
         # same footwork, and crossed feet are the moment either one fails.
         mix(hoc_shuffle=5, hoc_wide_handles=3, hoc_stance=3, hoc_shot=2,
             hoc_stickhandle=2, gen_lateral_bound=4, gen_squat=3, gen_lunge=2,
             gen_glute_bridge=2, gen_side_plank=2, gen_push_up=1),
         "Gaps and edges. Backwards as fast as most people go forwards.",
         "defencemen"),
    _pos("goaltender", "Goaltender", "hockey", "goalie",
         ("goaltender", "goalie", "goal", "g", "netminder", "keeper", "tendy"),
         # The one plan in this sport that is mostly not stick work, because
         # the position mostly is not. Hips and groins carry it.
         mix(hoc_butterfly=6, hoc_shuffle=3, hoc_stance=2, gen_lateral_bound=4,
             gen_lunge=3, gen_glute_bridge=3, gen_side_plank=3, gen_dead_bug=2,
             gen_wall_sit=2, gen_mountain_climber=2),
         "Down and up, sideways, on one hip. Groins and hips need real work.",
         "goaltenders"),
)

RUGBY: tuple[Position, ...] = (
    _pos("front_row", "Front Row", "rugby", "forwards",
         ("front row", "prop", "hooker", "loosehead", "tighthead", "1", "2", "3"),
         mix(gen_squat=5, gen_push_up=4, gen_wall_sit=3, gen_glute_bridge=3,
             gen_side_plank=3, gen_lunge=2, gen_plank=2, gen_pull_up=1),
         "Scrummaging is a squat against another person. Legs, back, neck.",
         "front rowers"),
    _pos("second_row", "Second & Back Row", "rugby", "forwards",
         ("second row", "lock", "back row", "flanker", "flank", "number 8", "no 8",
          "4", "5", "6", "7", "8"),
         mix(gen_squat=4, gen_burpee=3, gen_pull_up=3, gen_lunge=3,
             gen_mountain_climber=3, gen_push_up=2, gen_squat_jump=2, gen_plank=2),
         "Up and down all game. Get off the floor and into the next one.",
         "forwards"),
    _pos("half_back", "Half Backs", "rugby", "backs",
         ("half back", "halfback", "scrum half", "scrumhalf", "fly half", "flyhalf",
          "9", "10"),
         mix(gen_lateral_bound=4, gen_side_plank=4, gen_lunge=3, gen_high_knees=3,
             gen_glute_bridge=2, gen_dead_bug=2, gen_squat=2, gen_plank=2),
         "Pass off both hands from anywhere, and be moving when you do it.",
         "half backs"),
    _pos("backs", "Centres & Back Three", "rugby", "backs",
         ("centre", "center", "wing", "winger", "fullback", "full back", "back three",
          "outside back", "11", "12", "13", "14", "15"),
         mix(gen_high_knees=4, gen_lateral_bound=4, gen_squat_jump=3, gen_lunge=3,
             gen_glute_bridge=3, gen_squat=2, gen_side_plank=2, gen_plank=1),
         "Straight-line speed, and the ability to change your mind mid-stride.",
         "backs"),
)


BY_SPORT: dict[str, tuple[Position, ...]] = {
    "lacrosse": LACROSSE,
    "basketball": BASKETBALL,
    "soccer": SOCCER,
    "volleyball": VOLLEYBALL,
    "baseball": BASEBALL,
    "softball": SOFTBALL,
    "cheer": CHEER,
    "dance": DANCE,
    "swimming": SWIMMING,
    "track": TRACK,
    "football": FOOTBALL,
    "gymnastics": GYMNASTICS,
    "tennis": TENNIS,
    "cross_country": CROSS_COUNTRY,
    "hockey": HOCKEY,
    "rugby": RUGBY,
}

#: Every position across every sport, for tests and admin tooling.
ALL_POSITIONS: tuple[Position, ...] = tuple(
    position for group in BY_SPORT.values() for position in group
) + (GENERIC,)


def for_sport(sport: str | None) -> tuple[Position, ...]:
    """Positions modelled for a sport, or none if it has no model yet.

    Returning empty rather than a plausible-looking guess matters: a soccer
    program should get honest silence on positions, not lacrosse emphasis
    with the labels changed.
    """
    return BY_SPORT.get((sport or "").strip().lower(), ())


def _clean(raw: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Handles the shapes rosters actually contain: "Middie", "MID-FIELD",
    "Attack ", "D-Pole", "Goalie (JV)".
    """
    text = re.sub(r"\([^)]*\)", " ", (raw or "").lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


#: Strings that mean "no position given", in cleaned form. Checked before
#: anything else, because some of them are actively dangerous: "N/A" splits on
#: the slash into ["N", "A"], and "A" is a perfectly good alias for Attack. A
#: roster that says it does not know must not be read as saying "attacker".
PLACEHOLDERS = frozenset({
    "n a", "na", "none", "no position", "not assigned", "unassigned",
    "tbd", "tba", "tbc", "unknown", "undecided", "pending", "x",
    "various", "multi", "multiple", "any", "all", "other",
})

_ALIAS_CACHE: dict[str, dict[str, Position]] = {}


def _alias_map(sport: str) -> dict[str, Position]:
    if sport not in _ALIAS_CACHE:
        table: dict[str, Position] = {}
        for pos in for_sport(sport):
            for alias in (pos.key, pos.label, *pos.aliases):
                table[_clean(alias)] = pos
        _ALIAS_CACHE[sport] = table
    return _ALIAS_CACHE[sport]


def normalize(raw: str | None, sport: str = "lacrosse") -> Position | None:
    """Free-text position -> canonical position, or None if unrecognised.

    None is a real answer, not a failure to try. A roster row reading
    "TBD" or "?" should widen the peer pool rather than invent a position,
    and a coach should be able to see which rows did not resolve.
    """
    text = _clean(raw or "")
    if not text or text in PLACEHOLDERS:
        return None
    table = _alias_map(sport)

    if text in table:
        return table[text]

    # "attackman/midfield" and "midfield, attack" -- take the first that
    # resolves, since the first listed is conventionally the primary.
    for part in re.split(r" (?:or|and) |/|,", raw or ""):
        cleaned = _clean(part)
        if cleaned and cleaned in table:
            return table[cleaned]

    # Multi-word entries that carry a qualifier the alias list does not
    # know: "starting midfield", "jv goalie", "midfield 2".
    tokens = text.split()
    for token in tokens:
        if token in table and len(token) > 1:
            return table[token]
    # Single letters only when the whole entry is that letter, handled above:
    # "a" in "a team" must not silently become Attack.
    return None


def resolve(raw: str | None, sport: str = "lacrosse") -> Position:
    """Like `normalize`, but always returns something usable.

    Callers that need guidance rather than grouping use this: an athlete
    with no position still deserves a sensible drill mix.
    """
    return normalize(raw, sport) or GENERIC


def group_of(position: Position | None) -> str:
    return position.group if position else "field"


def emphasis_for(position: Position | None) -> dict[str, float]:
    return dict((position or GENERIC).emphasis)


def unrecognised(values: list[str], sport: str = "lacrosse") -> list[str]:
    """Distinct free-text positions that did not resolve, for a coach to fix."""
    seen: dict[str, None] = {}
    for value in values:
        if (value or "").strip() and normalize(value, sport) is None:
            seen.setdefault(value.strip(), None)
    return sorted(seen)
