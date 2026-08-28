"""What a good rep looks like, for every drill.

Form scoring could already tell a child their range was short. It could not
tell them what "not short" looks like, and a score without a fix is just a
mark out of ten -- which is the thing this product is otherwise careful not
to hand a twelve-year-old.

Two halves, and the first is the important one.

**Cues.** Per drill, per scoring component, a sentence saying what to do
differently and one saying why it matters. They are keyed to the same
component keys `quality.py` emits, so the fix an athlete reads is always the
fix for the thing that actually scored lowest -- not a generic tip list they
have to search.

**A reference.** Film study points a browser at somebody else's video and
inherits every problem that comes with a third-party embed: an ad before a
drill, a sidebar of recommendations, a link out. None of that belongs in
front of a child mid-session, so the reference here is generated from the
drill's own spec instead -- the target range, the tempo band, the shape of
the movement, drawn as a trace the athlete can watch their own rep against.

Generating it rather than filming it has a property a stock clip cannot have:
it is built from the same numbers the scorer marks against, so it can never
drift out of agreement with the score. A video shot once and a threshold
tuned later disagree silently, and the child is the one who pays for that.

A program that films its own demonstration can still drop a file in
`web/static/technique/<drill_key>.mp4` and it will be offered alongside the
trace. Nothing is shipped in the repo -- `available` is computed from the
filesystem, so this is honest about which drills actually have one.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .drills import ALL_DRILLS, DRILLS_BY_KEY
from .drills.base import DrillSpec, Metric, SignalKind

#: Where a deployment drops its own demonstration files, if it has any.
CLIP_DIR = Path(__file__).resolve().parent / "web" / "static" / "technique"

#: Kept short on purpose. A reference a child watches for forty seconds is a
#: reference that has eaten the session it was meant to improve.
MAX_CLIP_SECONDS = 20


@dataclass(frozen=True)
class Cue:
    """One fix, for one thing that scored low."""

    #: Matches a `quality.Component.key`, or "offhand" for the handed gap.
    component: str
    fix: str      # what to do differently, in the second person
    why: str      # why it is worth doing, in one clause

    def to_dict(self) -> dict[str, Any]:
        return {"component": self.component, "fix": self.fix, "why": self.why}


# Written per drill rather than generated, because "go deeper" is not advice.
# The fix has to name the body part and the feeling, which is the part a
# template cannot do.
CUES: dict[str, tuple[Cue, ...]] = {
    "gen_squat": (
        Cue("depth", "Sit back like there is a chair behind you, until your "
                     "thighs are about level with the floor.",
            "half a squat trains half the leg"),
        Cue("tempo", "Take about a second down and a second up. If you are "
                     "bouncing, you are using the bounce and not the muscle.",
            "control is what makes it count"),
        Cue("consistency", "Pick a spot on the wall and keep your eyes on it. "
                           "Every rep should look like the one before.",
            "reps that all look different are hard to get better at"),
        Cue("endurance", "Stop the set when your reps start getting shallower, "
                         "not when you cannot do another one.",
            "the shallow ones at the end teach your body the shallow version"),
    ),
    "gen_push_up": (
        Cue("depth", "Go down until your chest is about a fist off the floor, "
                     "elbows pointing back rather than straight out.",
            "the bottom third is where the strength comes from"),
        Cue("tempo", "Lower for about a second. Dropping down and pushing off "
                     "the floor is a different, easier exercise.",
            "you want the muscle doing it, not the bounce"),
        Cue("consistency", "Keep a straight line from your head to your heels "
                           "and hold it the whole way down.",
            "the hips sagging is the first thing to go"),
        Cue("endurance", "When your hips start to drop, that is the end of the "
                         "set. Rest and do another one.",
            "reps after the form goes are practising the wrong shape"),
    ),
    "gen_sit_up": (
        Cue("depth", "Come all the way up until your chest is near your knees, "
                     "and go all the way back down.",
            "the little ones in the middle do the least"),
        Cue("tempo", "Slow on the way down. Most people rush that half and it "
                     "is the half that works.",
            "lowering under control is where the core earns it"),
        Cue("consistency", "Do not yank on your neck. Hands crossed on your "
                           "chest keeps you honest.",
            "pulling your head forward fakes the range"),
        Cue("endurance", "Stop when you start using a swing to get up.",
            "the swing is your hips, not your stomach"),
    ),
    "gen_lunge": (
        Cue("depth", "Drop your back knee towards the floor until your front "
                     "thigh is about level.",
            "a shallow lunge misses the muscle it is for"),
        Cue("tempo", "Step, sink, and stand back up under control. Do not fall "
                     "into it.",
            "falling into a lunge is how knees get sore"),
        Cue("consistency", "Front knee over your front foot, not rolling "
                           "inwards. Same on both legs.",
            "the knee drifting in is worth fixing early"),
        Cue("endurance", "If you start wobbling, that is the set finished.",
            "balance going is the first sign of fatigue"),
    ),
    "gen_glute_bridge": (
        Cue("depth", "Push your hips all the way up until your body is a "
                     "straight line from knees to shoulders.",
            "the top of the movement is the whole point"),
        Cue("tempo", "Squeeze at the top for a beat before coming down.",
            "the pause is what makes it work"),
        Cue("consistency", "Keep your feet flat and your knees the same width "
                           "apart the whole time.",
            "knees falling apart changes which muscle is working"),
        Cue("endurance", "Stop when your hips stop reaching the top.",
            "half-height reps are a different exercise"),
    ),
    "gen_dead_bug": (
        Cue("depth", "Reach the opposite arm and leg out long and low, without "
                     "letting your back come off the floor.",
            "the range is limited by your back, not your limbs"),
        Cue("tempo", "Slowly. This one is meant to look easy and feel hard.",
            "speed is how people cheat this one"),
        Cue("consistency", "Press your lower back into the floor and keep it "
                           "there for every rep.",
            "if your back arches, the exercise has stopped"),
        Cue("endurance", "Finish the set when your back starts lifting.",
            "that is the muscle you came for giving up"),
    ),
    "gen_pull_up": (
        Cue("depth", "Pull until your chin clears the bar, and lower all the "
                     "way until your arms are straight.",
            "stopping short trains the easy half"),
        Cue("tempo", "Come down slowly. The lowering half builds as much as "
                     "the pulling half.",
            "dropping off the bar wastes half the rep"),
        Cue("consistency", "Stop the swinging. If you are kicking, the set is "
                           "over.",
            "a kip is a different exercise"),
        Cue("endurance", "Stop when you stop clearing the bar.",
            "reps that do not get there do not count"),
    ),
    "gen_plank": (
        Cue("position", "Straight line from your head to your heels. Hips not "
                        "up in the air, not sagging down.",
            "the line is the entire exercise"),
        Cue("endurance", "Come down when your hips start dropping, rather than "
                         "hanging on with bad form.",
            "a shorter good plank beats a long sagging one"),
    ),
    "gen_side_plank": (
        Cue("position", "Push your hip up so your body is a straight line, and "
                        "keep your shoulder stacked over your elbow.",
            "letting the hip drop takes the work off the side you are training"),
        Cue("endurance", "Stop when your hip starts sinking.",
            "past that you are resting on the floor, not holding"),
    ),
    "gen_hollow_hold": (
        Cue("position", "Lower back pressed flat into the floor, shoulders and "
                        "feet just off it.",
            "if your back lifts, the hold has stopped working"),
        Cue("endurance", "Come down when your back starts to arch.",
            "arching means your hip flexors took over"),
    ),
    "gen_wall_sit": (
        Cue("position", "Slide down until your thighs are level with the floor "
                        "and your knees are over your ankles.",
            "sitting high makes it easy in a way that does not show"),
        Cue("endurance", "Stand up when you start creeping higher up the wall.",
            "creeping up is the set ending whether you notice or not"),
    ),
    "gen_jumping_jack": (
        Cue("depth", "All the way out and all the way up -- hands meeting "
                     "above your head, feet wide.",
            "small ones are barely moving"),
        Cue("tempo", "Find a rhythm you can hold, rather than sprinting the "
                     "first ten.",
            "an even pace is what makes it conditioning"),
        Cue("consistency", "Same size every time, all the way through.",
            "shrinking halfway is the usual pattern"),
        Cue("endurance", "Slow down before you shrink, not after.",
            "smaller reps are your body quitting quietly"),
    ),
    "gen_high_knees": (
        Cue("depth", "Drive your knees up to about hip height, not just a "
                     "quick jog on the spot.",
            "low knees make this a jog"),
        Cue("tempo", "Quick feet. Short, sharp contacts with the floor.",
            "the speed is the training effect"),
        Cue("consistency", "Stay tall. Leaning back is the usual mistake.",
            "leaning back drops your knee height without you noticing"),
        Cue("endurance", "Finish the set when your knees stop coming up.",
            "there is nothing left to train once the height goes"),
    ),
    "gen_mountain_climber": (
        Cue("depth", "Drive each knee right up towards your chest.",
            "short ones turn this into a shuffle"),
        Cue("tempo", "Fast but even. Do not let your hips bounce.",
            "bouncing hips means your core stopped holding"),
        Cue("consistency", "Keep your shoulders over your hands and your hips "
                           "flat the whole time.",
            "hips riding up is the plank part giving in"),
        Cue("endurance", "Stop when your hips start to lift.",
            "past that you are just moving your legs"),
    ),
    "gen_burpee": (
        Cue("depth", "Chest to the floor at the bottom, and a proper jump with "
                     "your hands overhead at the top.",
            "both ends get skipped when people are tired"),
        Cue("tempo", "Steady. Burpees are won by not stopping, not by going "
                     "flat out for twenty seconds.",
            "an even pace gets you more reps than a sprint"),
        Cue("consistency", "Every rep gets the same chest-to-floor and the "
                           "same jump.",
            "the shrinking rep is the burpee's signature"),
        Cue("endurance", "Slow the pace before the reps get smaller.",
            "you keep more of the session that way"),
    ),
    "gen_tuck_jump": (
        Cue("depth", "Pull your knees up towards your chest at the top, rather "
                     "than just hopping.",
            "the tuck is what makes it a tuck jump"),
        Cue("tempo", "Land softly and reset. This is not a rhythm exercise.",
            "soft landings are what keep your knees happy"),
        Cue("consistency", "Land in the same spot you took off from.",
            "drifting means you are jumping off balance"),
        Cue("endurance", "Stop when your knees stop coming up or your landings "
                         "get loud.",
            "loud landings are tired legs"),
    ),
    "gen_squat_jump": (
        Cue("depth", "Sink to a proper squat before you jump, and land back "
                     "into one.",
            "a shallow dip gives you a shallow jump"),
        Cue("tempo", "Explode up, land soft, take a beat, go again.",
            "the pause is what keeps the jumps sharp"),
        Cue("consistency", "Knees tracking over your toes on every landing.",
            "knees caving in on landing is the one to fix"),
        Cue("endurance", "Stop when the jumps get low. Height is the point.",
            "low jumps train slowness"),
    ),
    "gen_lateral_bound": (
        Cue("depth", "Push properly sideways and stick the landing on one leg "
                     "before you go back.",
            "small hops miss the balance part"),
        Cue("tempo", "Hold each landing for a beat.",
            "the stick is where the ankle and knee learn to control it"),
        Cue("consistency", "Land in a controlled position every time rather "
                           "than scrambling to stay upright.",
            "a bound you cannot land is a bound you cannot use"),
        Cue("offhand", "Push off your weaker leg as hard as your strong one, "
                       "and cover the same distance both directions.",
            "almost everybody bounds further off one leg, and the other one "
            "is the one that gets hurt"),
        Cue("endurance", "Stop when you cannot stick the landings.",
            "wobbly landings are how ankles get rolled"),
    ),
    "lax_wall_ball": (
        Cue("depth", "Full throwing motion -- take the stick back past your "
                     "ear and follow through, rather than flicking at it.",
            "a short flick will not survive a game"),
        Cue("tempo", "Find a steady rhythm rather than rushing. Catch, cradle, "
                     "throw.",
            "rushing is where the drops come from"),
        Cue("consistency", "Same spot on the wall every time. Aim small.",
            "a target is what turns reps into accuracy"),
        Cue("offhand", "Give your weak hand the same number of reps and the "
                       "same full motion, even though it feels awful.",
            "your weak hand is the fastest thing you can improve"),
        Cue("endurance", "Stop when your throws start dropping short.",
            "tired reps groove a tired throw"),
    ),
    "lax_wall_ball_strong": (
        Cue("depth", "Take the stick back past your ear and follow through at "
                     "the target, every rep.",
            "a short flick will not survive a game"),
        Cue("tempo", "Catch, cradle once, throw. Do not rush the catch to get "
                     "to the throw.",
            "rushed hands are where drops come from"),
        Cue("consistency", "Pick one brick and hit it. Aim small.",
            "a target is what turns reps into accuracy"),
        Cue("offhand", "If your strong hand is this far ahead, the off-hand "
                       "set is the one that will actually move your game.",
            "defenders find your weak hand in about one possession"),
        Cue("endurance", "Stop when your throws start dropping short.",
            "tired reps groove a tired throw"),
    ),
    "lax_wall_ball_offhand": (
        Cue("depth", "Same full motion as your strong hand -- back past the "
                     "ear, full follow-through. Do not shorten it because it "
                     "feels awkward.",
            "a shortened off-hand throw becomes permanent"),
        Cue("tempo", "Slower than your strong side is fine. Complete beats "
                     "quick here.",
            "you are building a motion, not a highlight"),
        Cue("consistency", "It will be scattered at first. Aim at the same "
                           "spot anyway and let it come in.",
            "the scatter closes faster than you expect"),
        Cue("offhand", "This whole drill is the off hand. Keep the weak hand "
                       "on top for every single rep, even the last ones.",
            "the reps you swap back on are the reps that do not count"),
        Cue("endurance", "Finish the set before the motion shortens, not "
                         "after.",
            "a short tired rep teaches the short version"),
    ),
    "lax_wall_ball_one_hand": (
        Cue("depth", "Short and controlled -- this is not a full throw. Wrist "
                     "and forearm, not the whole arm.",
            "the point is control, not distance"),
        Cue("tempo", "Quick hands, close to the wall. If you are stepping "
                     "into it you are too far back.",
            "distance turns this into a different drill"),
        Cue("consistency", "Same height every rep. Chest to head, not over "
                           "the shoulder.",
            "a repeatable one-hander is what you can use in traffic"),
        Cue("offhand", "Do a set with each hand. The bottom hand comes off "
                       "either way.",
            "one-handed catches happen on both sides"),
        Cue("endurance", "Stop when your grip starts sliding.",
            "top-hand strength is the thing being built"),
    ),
    "lax_wall_ball_cross": (
        Cue("depth", "Complete the switch before you throw. Hands finish, "
                     "then the throw starts.",
            "a rushed exchange is where the ball comes out"),
        Cue("tempo", "Catch, switch, throw. Three beats, not one scramble.",
            "the switch is the skill, not the throw"),
        Cue("consistency", "Alternate every single rep. Same spot on the wall "
                           "from both sides.",
            "the point is that both sides look the same"),
        Cue("offhand", "Half these reps are off-hand throws by design -- give "
                       "them the same motion as the strong side.",
            "an even split is what this drill is for"),
        Cue("endurance", "When the switches get sloppy, stop.",
            "a sloppy exchange practised is a sloppy exchange kept"),
    ),
    "lax_wall_ball_btb": (
        Cue("depth", "Wrap it properly behind your back rather than round "
                     "your hip.",
            "round the hip is a different, easier throw"),
        Cue("tempo", "Slow is fine. Nobody does this fast at first.",
            "control comes before speed on this one"),
        Cue("consistency", "Same release point each time, even if the ball "
                           "goes everywhere at first.",
            "you are learning where the head is without looking"),
        Cue("offhand", "Try a few on your other side once the strong side "
                       "lands.",
            "it is worth knowing you can"),
        Cue("endurance", "Keep the set short. This is a garnish, not a meal.",
            "a hundred of these builds less than twenty good regular throws"),
    ),
    "lax_wall_ball_split": (
        Cue("depth", "Plant hard and change direction. A step across is not a "
                     "split dodge.",
            "the plant is what beats a defender"),
        Cue("tempo", "Catch, plant, split, throw. Let the footwork finish "
                     "before the hands go.",
            "hands and feet arriving together is what sells it"),
        Cue("consistency", "Same footwork every rep, both directions.",
            "a dodge you can only go one way with is half a dodge"),
        Cue("offhand", "Split both ways so you throw off both hands.",
            "a one-way dodge gets scouted in a half"),
        Cue("endurance", "Stop when your plant goes soft.",
            "soft plants are how ankles and knees get hurt"),
    ),
    "lax_faceoff_clamp": (
        Cue("depth", "Get all the way down into your stance every rep. Hips "
                     "low, back flat, hands at the ground.",
            "a high stance loses before the whistle goes"),
        Cue("tempo", "Fast. This is the one drill where speed beats a pretty "
                     "rep -- clamp, rip, up, reset.",
            "a face-off is decided in about half a second"),
        Cue("consistency", "Every rep the same. A clamp that varies is a "
                           "clamp that loses half the time.",
            "the same motion under pressure is the whole skill"),
        Cue("offhand", "Do a set clamping the other way. You will use your "
                       "strong side in a game, but the other one is your "
                       "insurance when a referee sets you up badly.",
            "a one-way face-off man gets scouted in a half"),
        Cue("endurance", "Stop when your stance starts creeping up, not when "
                         "your hands slow down.",
            "the stance goes first and takes everything else with it"),
    ),
    "bb_long_toss": (
        Cue("depth", "Crow hop into every one and finish over your front leg. "
                     "A flat-footed long toss is just a hard throw.",
            "the legs are where a safe throw comes from"),
        Cue("tempo", "Slow between throws. This is the one drill here where "
                     "you should be resting more than working.",
            "recovery between throws is what keeps the arm safe"),
        Cue("consistency", "Same distance for the whole set. Backing up as you "
                           "warm up is a different drill and a harder one.",
            "creeping distance is how a session gets away from you"),
        Cue("offhand", "Throw with your usual arm. This is not a drill for "
                       "building the other one.",
            "bilateral throwing is a way to hurt two elbows instead of one"),
        Cue("endurance", "Stop when the ball starts sailing, not when your arm "
                         "aches. By the ache it is already too late.",
            "loss of control is the first sign of a tired arm, and the only "
            "early one"),
    ),
    "bb_quick_hands": (
        Cue("depth", "Short arm action. If you are taking it back past your "
                     "ear this is a throwing drill, not a transfer one.",
            "a long arm action is exactly what this drill exists to shorten"),
        Cue("tempo", "Feet moving the whole time. The hands are quick because "
                     "the feet got there first.",
            "quick hands with slow feet is a throw from a bad position"),
        Cue("consistency", "Same transfer point every rep -- glove to hand in "
                           "front of your chest, not down by your hip.",
            "a low transfer adds a tenth of a second you do not have"),
        Cue("offhand", "Usual arm only. Volume matters more than variety here.",
            "these still count on the day's arm total"),
        Cue("endurance", "Stop when the transfers start getting sloppy.",
            "sloppy hands are tired hands, and tired hands drop balls"),
    ),
    "bb_tee_swing": (
        Cue("depth", "Full swing, all the way through and around. A checked "
                     "swing off a tee teaches a checked swing.",
            "the tee exists so you can do it properly, every time"),
        Cue("tempo", "Take your time between swings. Twenty good ones beat "
                     "sixty rushed ones and you will feel the difference.",
            "rushed reps groove the thing you were trying to fix"),
        Cue("consistency", "Same tee height, same stance, same swing. Change "
                           "one thing at a time or you learn nothing.",
            "moving the tee around is how a session becomes exercise"),
        Cue("endurance", "Stop when your swing starts getting long.",
            "a long swing late in a set is a tired core, not a technical fault"),
    ),
    "bb_fielding": (
        Cue("depth", "Get your hips down, not your shoulders. If your back is "
                     "rounding you are bending instead of fielding.",
            "bending at the waist puts your eyes in the wrong place"),
        Cue("tempo", "Down and up under control. This is footwork, not a "
                     "conditioning drill.",
            "rushing it grooves a bad first step"),
        Cue("consistency", "Hands out in front where you can see them, every "
                           "rep.",
            "hands under your body is how a ball goes between your legs"),
        Cue("endurance", "Stop when you stop getting all the way down.",
            "a high fielding position is where bad hops come from"),
    ),
    "bb_catcher_stance": (
        Cue("position", "Hips low, chest up, and heels down if your ankles "
                        "will let you. The clock only runs while you are "
                        "actually down.",
            "a high crouch is a crouch that cannot block anything"),
        Cue("endurance", "Stop when your hips start rising, not when your legs "
                         "burn. The burn is the drill working.",
            "the hips come up first and take the whole position with them"),
    ),
    "sb_windmill": (
        Cue("depth", "All the way round. A half circle is a different pitch "
                     "and it will not count.",
            "the circle is where the speed comes from"),
        Cue("tempo", "Same stride and same rhythm every pitch. Speed comes "
                     "from the circle being repeatable, not from forcing it.",
            "forcing a windmill is how a shoulder and a lower back get hurt"),
        Cue("consistency", "Same release point every time. If you are missing "
                           "high and low, that is the release, not your aim.",
            "release point is the whole of control in this motion"),
        Cue("offhand", "Your pitching arm only. Nothing here is a reason to "
                       "build the other one.",
            "a pitching arm is not something to build twice"),
        Cue("endurance", "Stop well before your arm aches. These count on the "
                         "day's total for a reason -- a windmill pitcher throws "
                         "more than anybody else on the field.",
            "the volume nobody counts is the volume that hurts people"),
    ),
    "ten_alternate": (
        Cue("depth", "Turn your shoulders early. If you are reaching for the "
                     "ball you have already lost the wing change.",
            "the turn is what makes the swing possible, not the swing itself"),
        Cue("tempo", "Stand further off the wall than feels comfortable. This "
                     "drill is about having time, not about speed.",
            "close to the wall you never get to change wings at all"),
        Cue("consistency", "Every other ball on the other side, with no "
                           "cheating back to the good wing.",
            "the app checks this, and so does an opponent"),
        Cue("offhand", "Half of this is already your weaker wing, which is why "
                       "it earns more than a plain rally.",
            "alternating is the cheapest way to get weak-wing balls in"),
        Cue("endurance", "Stop when you start running around your backhand.",
            "running around it is the habit this drill exists to break"),
    ),
    "ten_one_wing": (
        Cue("depth", "Recover to the middle after every ball. Standing on one "
                     "side is a much easier drill than the one you meant to do.",
            "the recovery is most of the work and all of the fitness"),
        Cue("tempo", "Same rhythm every ball. This is a grooving drill, not a "
                     "race.",
            "grooving a stroke needs repetition, not intensity"),
        Cue("consistency", "Same contact point every time -- out in front, not "
                           "beside you.",
            "a late contact point is the single most common fault in the sport"),
        Cue("offhand", "Pick your weaker wing. The stronger one does not need "
                       "the reps and you know which is which.",
            "nobody improves the shot they already like hitting"),
        Cue("endurance", "Stop when your contact point starts drifting back.",
            "a late ball is a tired ball, and it grooves the wrong thing"),
    ),
    "ten_volley": (
        Cue("depth", "No backswing. Block it -- the pace is already there and "
                     "the racket only has to be in the way.",
            "a backswing at the net is how a volley ends up in the fence"),
        Cue("tempo", "Fast and continuous. There is a speed floor here and a "
                     "groundstroke rally does not clear it.",
            "the rate is the whole verification"),
        Cue("consistency", "Racket head above your wrist, every ball. Drop it "
                           "and the volley goes down.",
            "a dropped racket head is the fault that ends every net point"),
        Cue("offhand", "Both wings evenly. Backhand volleys are the ones "
                       "nobody practises.",
            "a net player gets attacked on the wing they avoid"),
        Cue("endurance", "Stop when your racket head starts dropping.",
            "the arm tires before the legs here, and it shows first in the head"),
    ),
    "ten_serve": (
        Cue("depth", "Reach up and hit it at full stretch. A serve struck "
                     "below full reach has to be hit harder for the same "
                     "result.",
            "height buys angle, and angle is free"),
        Cue("tempo", "The toss is the serve. Same height, same spot, every "
                     "time -- everything after it is just repeating.",
            "an inconsistent toss makes an inconsistent serve, always"),
        Cue("consistency", "Change one thing at a time. Grip, stance or toss, "
                           "never two at once.",
            "changing two things at once teaches you nothing about either"),
        Cue("offhand", "Serve with your usual hand. This is not a drill for "
                       "building the other one.",
            "a serving shoulder is not something to build twice"),
        Cue("endurance", "Stop well before your shoulder aches. Serving is the "
                         "one thing in tennis that counts as throwing.",
            "a sore serving shoulder at fifteen becomes a chronic one at twenty"),
    ),
    "ten_split_step": (
        Cue("depth", "Land wider than your shoulders. A narrow landing means "
                     "you cannot push off in either direction.",
            "the width is what makes the next step possible"),
        Cue("tempo", "Land just as they hit it, not before and not after. The "
                     "timing is the entire skill.",
            "an early split step has landed and stopped by the time you need it"),
        Cue("consistency", "Same small hop every time. This is not a jump.",
            "a big hop takes longer to land from than the ball takes to arrive"),
        Cue("endurance", "Stop when the hop starts disappearing.",
            "the split step is the first thing tired legs quietly drop"),
    ),
    "ten_recovery": (
        Cue("depth", "Push off and actually cover ground. A shuffle that stays "
                     "still leaves the whole court open.",
            "the app measures how far your feet get apart, and so does your "
            "opponent"),
        Cue("tempo", "Recover before the next ball, not while it is coming.",
            "moving as the ball arrives means hitting off balance"),
        Cue("consistency", "Never cross your feet. The app can see it happen "
                           "and will tell you how many times.",
            "crossed feet is the moment you cannot change direction"),
        Cue("offhand", "Both directions evenly. Everybody is worse recovering "
                       "to one side.",
            "an opponent finds the side you cannot recover to inside a set"),
        Cue("endurance", "Stop when you start standing up out of your stance.",
            "an upright player has already given up the next two shots"),
    ),
    "rug_quick_hands": (
        Cue("depth", "The ball has to cross your body. Catching and popping it "
                     "straight back out on the same side is not a pass.",
            "the app counts the crossing, and so does a defender"),
        Cue("tempo", "Catch and pass in one movement. If you have time to "
                     "gather it, get further from the wall.",
            "the whole drill is the time you do not take"),
        Cue("consistency", "Both directions, every time. Alternate on purpose "
                           "rather than drifting onto your good side.",
            "everybody drifts, and nobody notices they have"),
        Cue("endurance", "Stop when the ball starts hitting your chest before "
                         "your hands do.",
            "that is your hands slowing down, not the ball speeding up"),
    ),
    "rug_wall_pass": (
        Cue("depth", "Hands from your back hip through to pointing at the "
                     "target. A pass that starts at your chest has half the "
                     "distance and half the accuracy.",
            "the pass gets its speed from how far you carry it"),
        Cue("tempo", "Catch, turn your shoulders, pass. Same rhythm each way, "
                     "even though one way will feel wrong for a while.",
            "the side that feels wrong is the side worth the session"),
        Cue("consistency", "Same number each way. The app will tell you if one "
                           "side is coming up short.",
            "one-sided passers get found in a single game"),
        Cue("endurance", "When your weak side starts getting shorter, that is "
                         "the end of the set rather than the moment to push.",
            "a tired weak side practises being weak"),
    ),
    "rug_spin_pass": (
        Cue("depth", "All the way from behind your back hip to a full "
                     "follow-through. This is the drill where the width is the "
                     "whole point.",
            "a short spin pass is just a pass with a longer name"),
        Cue("tempo", "One at a time, with your feet set. These are individual "
                     "passes, not a set you rush through.",
            "the feet are where the distance comes from"),
        Cue("consistency", "Same launch point both ways. Most players have a "
                           "long side and a short side and have never measured "
                           "either.",
            "the app measures both and will tell you the gap"),
        Cue("endurance", "Stop when the ball stops spinning. That is your hands "
                         "going, and the next twenty reps teach the wrong thing.",
            "a wobbling pass is a slower pass"),
    ),
    "fb_quick_release": (
        Cue("depth", "Ball from your ear, not from behind your head. If you "
                     "are winding up, it is not a quick release.",
            "the whole drill is the distance the ball does not travel"),
        Cue("tempo", "Fast and repeatable. If you have to reset your feet "
                     "between throws you are throwing, not releasing.",
            "the speed floor is what tells these apart from full throws"),
        Cue("consistency", "Same slot every rep. A compact motion that changes "
                           "every time is just a small inaccurate one.",
            "quick and wrong is still wrong"),
        Cue("offhand", "Do not throw these with your other arm to even things "
                       "up. One arm throws in this sport, and it is the one "
                       "the day's total is protecting.",
            "a throwing arm is not a hand you swap"),
        Cue("endurance", "Stop when the ball starts sailing. That is the arm "
                         "talking, not your aim.",
            "accuracy goes before the arm feels like anything"),
    ),
    "fb_wall_throw": (
        Cue("depth", "Full motion. Load it properly and finish across your "
                     "body -- a throw that stops at release is an arm throw.",
            "the follow-through is where the shoulder gets to slow down"),
        Cue("tempo", "One throw at a time. Set your feet, throw, reset.",
            "rushed reps are how a session of forty becomes a session of a hundred"),
        Cue("consistency", "Same footwork every rep. Change one thing at a "
                           "time or you are practising forty different throws.",
            "a repeatable throw is what becomes an accurate one"),
        Cue("offhand", "This is a one-armed sport and that is fine. What "
                       "matters is that the app knows how many that arm threw "
                       "today.",
            "the count is the point, not the balance"),
        Cue("endurance", "When you start dropping your elbow to get the ball "
                         "there, the session is over.",
            "a dropping elbow is the first sign an arm has had enough"),
    ),
    "fb_deep_ball": (
        Cue("depth", "Everything into it -- hips, front side, full "
                     "follow-through. If you are not doing that, throw the "
                     "shorter drill instead.",
            "a half-hearted deep ball costs the arm the same and teaches less"),
        Cue("tempo", "Take your time between them. These are not a set, they "
                     "are individual throws.",
            "the rest between is part of the drill"),
        Cue("consistency", "Same drop, same launch point. The distance comes "
                           "from your legs being in the same place each time.",
            "throwing further with your arm is the way arms get hurt"),
        Cue("offhand", "Never these with the other arm. Not once.",
            "an unconditioned arm throwing maximally is the worst version of this"),
        Cue("endurance", "Keep the number small on purpose. Twenty good ones "
                         "beats fifty, and the app will tell you where you are "
                         "against the day.",
            "this is the drill the daily throwing total exists for"),
    ),
    "fb_kick": (
        Cue("depth", "Swing all the way through and let the leg finish high. "
                     "Stopping the swing at the ball is where groins get hurt.",
            "the follow-through is how the leg decelerates safely"),
        Cue("tempo", "One at a time, with a proper walk-back. Kicking is not a "
                     "set you rush through.",
            "the approach is most of the kick"),
        Cue("consistency", "Same steps, same plant, every single time. Move "
                           "one and you have changed the whole thing.",
            "a kicker's job is doing one movement identically"),
        Cue("offhand", "Do a few easy swings with the other leg at the end. "
                       "Not to kick with -- just so one hip is not doing "
                       "everything.",
            "the plant leg and the swing leg age very differently"),
        Cue("endurance", "Stop when your plant foot starts drifting. That is "
                         "fatigue, and it is the rep before something tweaks.",
            "the last few of a long session are the ones that hurt you"),
    ),
    "fb_shuffle": (
        Cue("depth", "Push off the outside foot and cover ground. A slide that "
                     "stays still gives up the whole route.",
            "the app measures how far your feet get apart, and so does a receiver"),
        Cue("tempo", "Slide, reset, slide. Do not hop -- both feet in the air "
                     "means you cannot break on anything.",
            "the moment you are airborne you are beaten"),
        Cue("consistency", "Never cross your feet. The app can see it happen "
                           "and will tell you how many times.",
            "crossed feet is the exact moment somebody runs past you"),
        Cue("offhand", "Both directions evenly. Everybody has a side they "
                       "cannot go, and a receiver finds it in one drive.",
            "you will be tested to your worse side, on purpose"),
        Cue("endurance", "Stop when you start standing up out of your stance.",
            "an upright defender has already lost the route"),
    ),
    "gen_calf_raise": (
        Cue("depth", "All the way up onto the balls of your feet, then all the "
                     "way down until your heels touch. The top inch is the "
                     "whole exercise.",
            "half a calf raise trains the half you were never short of"),
        Cue("tempo", "Two seconds up, two seconds down. If you are bouncing, "
                     "the tendon is doing it instead of the muscle.",
            "the bounce is free, and free does not make you stronger"),
        Cue("consistency", "Same height every rep. Pick a mark on the wall at "
                           "eye level and rise to it each time.",
            "reps that all end somewhere different are hard to improve on"),
        Cue("endurance", "Stop when you can no longer get all the way up, not "
                         "when your calves burn.",
            "the short ones at the end are practising a short range"),
    ),
    "gen_handstand_hold": (
        Cue("position", "Arms locked straight, ears between your shoulders, "
                        "and squeeze your legs together. Push the floor away.",
            "bent arms is where a handstand becomes a fall"),
        Cue("endurance", "Come down while you still choose to. If your arms "
                         "are shaking, that set is over.",
            "the last five seconds of a bad handstand are how wrists get hurt"),
    ),
    "gen_dead_hang": (
        Cue("position", "Arms straight, shoulders pulled down away from your "
                        "ears rather than shrugged up around them.",
            "hanging from the shoulder joint is what makes it a strength drill"),
        Cue("endurance", "Come off the bar when your grip goes, not after it "
                         "goes. Two shorter hangs beat one that ends in a drop.",
            "the fall at the end is the only dangerous part of this"),
    ),
    "hoc_stickhandle": (
        Cue("depth", "Get the puck out past your hands and back. Rolling it "
                     "under your nose is not stickhandling, it is fidgeting.",
            "the app measures how far across your body your hands travel"),
        Cue("tempo", "Quick and even. A handle with a pause in it is a handle "
                     "a defender steps into.",
            "the rhythm is what makes it hard to read"),
        Cue("consistency", "Head up. Look at the wall, not at the puck, and "
                           "keep every trip across the same size.",
            "you will never look down on the ice, so do not practise it"),
        Cue("endurance", "Stop when your hands start dragging behind the puck.",
            "tired hands practise the sloppy version"),
    ),
    "hoc_wide_handles": (
        Cue("depth", "All the way out, both sides. Your bottom arm should be "
                     "nearly straight at the far end of each one.",
            "this drill is the width -- a narrow one is just tight handles"),
        Cue("tempo", "Slower than tight handles. Reach, control it, come back.",
            "rushing the reach is how the puck ends up behind you"),
        Cue("consistency", "Same distance each way. Most players are much "
                           "wider on their forehand and have never noticed.",
            "the app measures both sides and will tell you the gap"),
        Cue("endurance", "When the reaches start getting shorter, that is the "
                         "end of the set.",
            "short reaches at the end teach your hands the short version"),
    ),
    "hoc_shot": (
        Cue("depth", "Start the puck behind your back foot and finish with "
                     "your hands past your front hip. The whole sweep.",
            "the puck picks up its speed over the distance it is dragged"),
        Cue("tempo", "One shot at a time. Pull the next puck over, set your "
                     "feet, then shoot -- do not machine-gun them.",
            "ten proper shots beat forty rushed ones"),
        Cue("consistency", "Same spot on the pad, same feet, every time. Move "
                           "the puck around and you are practising forty "
                           "different shots badly.",
            "a repeatable shot is what becomes an accurate one"),
        Cue("endurance", "Stop when your follow-through starts dropping.",
            "the arms give out before the legs, and the shot goes with them"),
    ),
    "hoc_butterfly": (
        Cue("depth", "Hips all the way down, not a knee drop. If one leg gets "
                     "there first you are falling, not dropping.",
            "the app measures how far your hips travel, and so does the puck"),
        Cue("tempo", "Down under control, up as fast as you can. The recovery "
                     "is the half of this that wins games.",
            "the second shot comes while you are still getting up"),
        Cue("consistency", "Chest up the whole way. The moment you fold "
                           "forward you cannot see the puck or push off.",
            "a goalie folded over is a goalie who has stopped goaltending"),
        Cue("endurance", "Stop when getting up starts taking two pushes.",
            "this is the exact thing that runs out in the third period"),
    ),
    "hoc_shuffle": (
        Cue("depth", "Push off the outside foot and actually cover ground. A "
                     "slide that goes nowhere closes nothing off.",
            "the app measures how far apart your feet get, and so does a winger"),
        Cue("tempo", "Slide, reset, slide. Do not hop -- both feet in the air "
                     "means you cannot change direction.",
            "the moment you are airborne you are committed"),
        Cue("consistency", "Never let your feet cross. The app can see it "
                           "happen and will tell you how many times.",
            "crossed feet is the exact moment a winger goes past you"),
        Cue("offhand", "Both directions evenly. Almost everybody is worse "
                       "going one way and has never checked.",
            "a forward finds the side you cannot slide to inside one shift"),
        Cue("endurance", "Stop when you start standing up out of your stance.",
            "an upright defender has already lost the gap"),
    ),
    "hoc_stance": (
        Cue("position", "Knees over your toes, chest up, back flat. If you can "
                        "see your own knees, you are bent at the waist.",
            "the waist bend is what stops you pushing off"),
        Cue("endurance", "Stop when your hips start creeping up, not when your "
                         "legs give out.",
            "the last thirty seconds standing up are teaching the wrong shape"),
    ),
    "soc_juggle_weak": (
        Cue("depth", "Small touches, knee height. A weak foot that has to "
                     "stretch for every ball never gets comfortable.",
            "control comes from the ball staying close, not from reaching"),
        Cue("tempo", "Slow. This is not a drill you rush -- the count is not "
                     "the point.",
            "rushing your weak foot just practises the panic"),
        Cue("consistency", "Same part of the foot every time, laces flat.",
            "a weak foot that varies is a weak foot that never becomes reliable"),
        Cue("offhand", "This drill IS the weak foot. Doing it on your strong "
                       "one is a different, easier drill.",
            "the hard half is the only half that changes anything"),
        Cue("endurance", "Stop when the ball starts running away from you, not "
                         "when your leg is tired.",
            "control going is the signal; a tired leg is just the work"),
    ),
    "soc_juggle_alt": (
        Cue("depth", "Knee height, both feet. If it is going above your head "
                     "you are buying time instead of controlling it.",
            "high juggling hides a weak touch"),
        Cue("tempo", "Even rhythm. Left, right, left, right -- the same beat "
                     "the whole way.",
            "the rhythm is what makes it a skill rather than a scramble"),
        Cue("consistency", "Every other touch on the other foot, with no "
                           "cheating back to the good one.",
            "the app checks this, and so does a defender"),
        Cue("offhand", "Half of this drill is already your weak foot, which is "
                       "why it is worth more than plain juggling.",
            "alternating is the cheapest way to get weak-foot touches in"),
        Cue("endurance", "Stop when you start double-touching on one side.",
            "a double touch is the weak foot quietly opting out"),
    ),
    "soc_thigh": (
        Cue("depth", "Thigh flat and level, knee up near waist height. A "
                     "sloping thigh sends the ball away from you.",
            "the thigh is a platform, and a tilted platform is a lost ball"),
        Cue("tempo", "Let it sit on the thigh for a beat. This is a control "
                     "drill, not a speed one.",
            "cushioning is the skill; popping it straight back is not"),
        Cue("consistency", "Same height every touch. If it is climbing, you "
                           "are hitting rather than cushioning.",
            "a rising ball means a stiff leg"),
        Cue("offhand", "Both thighs, evenly. Most players have one that has "
                       "never touched a ball.",
            "your weak side gets found the moment you are under pressure"),
        Cue("endurance", "Stop when your knee stops coming all the way up.",
            "a low knee turns a cushion into a bounce"),
    ),
    "soc_wall_pass": (
        Cue("depth", "Strike through the middle of the ball with your instep. "
                     "A toe-poke gets there but goes nowhere useful.",
            "the app has a speed floor, and so does a real pass"),
        Cue("tempo", "Control, then pass. Two touches, not one panicked one.",
            "the first touch is what makes the second one easy"),
        Cue("consistency", "Same spot on the wall every time. A pass that "
                           "wanders is a teammate who has to stretch.",
            "a stretched teammate is a lost ball"),
        Cue("offhand", "Alternate feet by the set, not by the pass, so the "
                       "weak one gets a real turn.",
            "swapping every rep lets the good foot carry the drill"),
        Cue("endurance", "Stop when your first touch starts getting away.",
            "a heavy touch late in a set is exactly what happens late in a game"),
    ),
    "soc_toe_taps": (
        Cue("depth", "Just the top of the ball. You are tapping it, not "
                     "standing on it.",
            "weight on the ball is how ankles get rolled"),
        Cue("tempo", "As fast as you can hold it together. There is a speed "
                     "floor here and a slow tap does not count at all.",
            "the speed is the entire drill"),
        Cue("consistency", "Chest up and eyes forward. If you have to watch "
                           "your feet, slow down until you do not.",
            "a player looking at the ball cannot see the pass"),
        Cue("offhand", "Even both ways. Most players tap harder on one side "
                       "without noticing.",
            "the uneven side is the one that fails under pressure"),
        Cue("endurance", "Stop when you start losing the rhythm, not when your "
                         "calves burn.",
            "the rhythm going is the signal that the skill has stopped"),
    ),
    "soc_shuffle": (
        Cue("depth", "Push off the back foot and actually cover ground. A "
                     "shuffle that stays still lets a winger go outside you.",
            "the app measures how far your feet get apart, and so does a winger"),
        Cue("tempo", "Stay side-on and patient. Diving in is what a good "
                     "attacker is waiting for.",
            "the tackle you rush is the one that gets beaten"),
        Cue("consistency", "Never cross your feet. The app can see it happen "
                           "and will tell you how many times.",
            "crossed feet is the exact moment a winger goes past you"),
        Cue("offhand", "Both directions evenly. Almost everybody is worse "
                       "shuffling to their weaker side.",
            "a winger finds the side you cannot defend inside twenty minutes"),
        Cue("endurance", "Stop when you start standing up out of your stance.",
            "an upright defender is a defender who has already been beaten"),
    ),
    "vb_pass": (
        Cue("depth", "Get your platform under the ball by moving your feet, "
                     "not by swinging your arms up at it.",
            "arms that swing send the ball anywhere but where you meant"),
        Cue("tempo", "Let the ball come to you. Rushing at it is what makes a "
                     "pass shoot off sideways.",
            "a passer who reaches is a passer who shanks"),
        Cue("consistency", "Same platform every ball -- thumbs together, "
                           "elbows locked, shoulders forward.",
            "the platform is the only flat surface in the whole skill"),
        Cue("endurance", "Stop when you start playing the ball with your hands "
                         "instead of your arms.",
            "hands come out when the legs are gone, and that is a set, not a pass"),
    ),
    "vb_set_wall": (
        Cue("depth", "Hands above your forehead, every ball. If they drop to "
                     "your chin you are passing with your fingers.",
            "a low set is how fingers get jammed"),
        Cue("tempo", "Quick and soft. The wall gives it back faster than you "
                     "do, which is the whole reason to do it here.",
            "the speed is the point; a slow wall set is just setting to yourself"),
        Cue("consistency", "Same distance off the wall the whole set. Drifting "
                           "in makes it easier and teaches you nothing.",
            "the drill only works at the range that is hard for you"),
        Cue("endurance", "Stop when your hands start slapping rather than "
                         "catching and pushing.",
            "slapping is a tired setter, and it is also a double"),
    ),
    "vb_serve": (
        Cue("depth", "Reach up and hit it at full stretch. A serve struck "
                     "below full reach has to be hit harder to do the same "
                     "thing.",
            "height buys you angle, and angle is free"),
        Cue("tempo", "The toss is the serve. Same height, same spot, every "
                     "time -- everything after it is just repeating.",
            "an inconsistent toss makes an inconsistent serve, always"),
        Cue("consistency", "Same starting spot, same number of steps. Change "
                           "one thing at a time or you will never know what "
                           "helped.",
            "changing two things at once teaches you nothing about either"),
        Cue("offhand", "Serve with your usual hand. This is not a drill for "
                       "building the other one.",
            "a serving shoulder is not something to build twice"),
        Cue("endurance", "Stop well before your shoulder aches. Serving is the "
                         "one thing here that counts as throwing.",
            "a sore serving shoulder at fourteen becomes a chronic one at twenty"),
    ),
    "vb_arm_swing": (
        Cue("depth", "Draw the elbow back and high, then swing all the way "
                     "through. A half swing builds a half swing.",
            "range now is power later, and it is easier to build than to fix"),
        Cue("tempo", "Fast through contact, then let the arm finish across "
                     "your body. Do not stop it dead.",
            "stopping the arm dead is how a shoulder gets hurt"),
        Cue("consistency", "Same swing every rep. It has to be repeatable "
                           "before it is worth making it fast.",
            "a swing that varies is a hitter who cannot be set"),
        Cue("offhand", "Both arms work here -- the non-hitting arm points and "
                       "pulls down. Do not let it hang.",
            "the arm that is not hitting is half of where the power comes from"),
        Cue("endurance", "Stop counting and start listening to your shoulder. "
                         "These count as throws for a reason.",
            "swing volume is the injury nobody counts in this sport"),
    ),
    "vb_approach": (
        Cue("depth", "Get low into the last two steps. The jump comes out of "
                     "that, not out of your arms.",
            "a tall approach is a short jump"),
        Cue("tempo", "Slow, then fast. The last two steps are the quick ones.",
            "a run-up at one speed does not load anything"),
        Cue("consistency", "Same number of steps, same foot pattern, every "
                           "time.",
            "a hitter whose approach changes cannot be set by anyone"),
        Cue("endurance", "Stop when your landings stop being quiet. That is "
                         "the signal, not your legs.",
            "loud landings are what jumper's knee is made of"),
    ),
    "vb_block_jump": (
        Cue("depth", "Press up and over, not just up. Your hands should "
                     "finish higher than they started by a long way.",
            "a block that goes straight up gets hit through"),
        Cue("tempo", "Straight from a standing start. No dip and no wind-up -- "
                     "at the net you do not get either.",
            "the dip is exactly the time a hitter uses"),
        Cue("consistency", "Land where you took off. Drifting sideways is how "
                           "ankles get rolled on somebody else's foot.",
            "landing on a teammate's foot is the most common injury in the sport"),
        Cue("endurance", "Stop when you start landing flat-footed.",
            "flat landings mean the calves are done, and they cushion the knees"),
    ),
    "bkb_form_shot": (
        Cue("depth", "Dip into the pocket and come all the way up through the "
                     "ball. A shot that starts at your chest has no legs in "
                     "it.",
            "the power comes from the dip, and short shots come from skipping it"),
        Cue("tempo", "One motion, same speed every time. Do not rush it "
                     "because it is close.",
            "a shot you rush up close is the shot you rush in a game"),
        Cue("consistency", "Elbow under the ball, every single rep. The app "
                           "watches this one and will tell you when it drifts "
                           "out.",
            "an elbow that flares sends the ball sideways, and you cannot feel "
            "it happening"),
        Cue("offhand", "Guide hand off the ball entirely. If it is helping, "
                       "you are not learning what your shooting hand does.",
            "a guide hand that pushes is why a shot goes left or right"),
        Cue("endurance", "Stop when the follow-through stops holding, not when "
                         "your arm is tired.",
            "a shoulder that gets tired starts pushing the elbow out sideways"),
    ),
    "bkb_slide": (
        Cue("depth", "Push off the back foot and cover ground. A step that "
                     "does not widen your stance is a step that went nowhere.",
            "the app measures how far your feet get apart, and so does an "
            "offensive player"),
        Cue("tempo", "Push, then let the trail foot catch up. Do not hop -- "
                     "both feet off the floor at once means you cannot change "
                     "direction.",
            "you get beaten in the moment neither foot is down"),
        Cue("consistency", "Never let your feet cross. The app can see it "
                           "happen and will tell you how many times.",
            "crossed feet is how a good defender ends up on the floor"),
        Cue("offhand", "Slide both directions evenly. Almost everybody is "
                       "worse going to their weak side.",
            "an offence finds the side you cannot slide to inside a quarter"),
        Cue("endurance", "Stop when your stance starts standing up, not when "
                         "your legs burn.",
            "a high stance slides slowly, and the legs go before the hands do"),
    ),
    "bkb_crossover": (
        Cue("depth", "Push it across below your knees. A crossover at your "
                     "waist is a ball somebody else is about to have.",
            "the lower it is, the less time a defender has to reach it"),
        Cue("tempo", "Hard and quick. A slow crossover just tells them which "
                     "way you are going.",
            "the point is changing direction before they can react"),
        Cue("consistency", "Same low stance every rep. If you stand up between "
                           "crossovers you have already lost the advantage.",
            "standing up is how a good move becomes a turnover"),
        Cue("offhand", "Do a set where the weak hand is the one receiving. "
                       "That is the half of the move nobody practises.",
            "a one-way crossover gets scouted in a quarter"),
        Cue("endurance", "Stop when your stance creeps up, not when your hands "
                         "get tired.",
            "the legs go first and take the handle with them"),
    ),
    "bkb_between_legs": (
        Cue("depth", "Step into it. The ball goes through as your foot comes "
                     "forward, not while you are standing still.",
            "standing still makes it a trick instead of a move"),
        Cue("tempo", "One motion. If you have to look down and set it up, it "
                     "is too slow to use in a game.",
            "anything you have to set up, a defender has time to take"),
        Cue("consistency", "Both directions, evenly. Most players only ever go "
                           "one way through their legs.",
            "the one you never practise is the one you need under pressure"),
        Cue("offhand", "Lead with the weak hand for a full set.",
            "your weak side is where the ball gets taken"),
        Cue("endurance", "Stop before it gets sloppy. A loose one between the "
                         "legs is a ball off your own shin.",
            "tired hands are how this move ends up in the other team's hands"),
    ),
    "bkb_pound_weak": (
        Cue("depth", "Below your knee, every rep. If it is coming back to your "
                     "waist you are patting it, not pounding it.",
            "a high dribble on your weak hand is a steal waiting to happen"),
        Cue("tempo", "Hard. This should be loud, and it should be tiring "
                     "before you expect it to be.",
            "the strength is the point, not the count"),
        Cue("consistency", "Eyes up the whole time. If you have to look at it, "
                           "the hand is not ready yet.",
            "the whole reason to build this hand is so you can look elsewhere"),
        Cue("offhand", "This drill is already the off-hand. Doing it on your "
                       "strong hand is a different, easier drill.",
            "the hard half is the only half that changes anything"),
        Cue("endurance", "Stop when the ball starts getting away from you, not "
                         "when your forearm burns.",
            "control going is the signal; a burning arm is just the work"),
    ),
    "bkb_pound_low": (
        Cue("depth", "Knee height or lower, both hands. Wide base, chest up.",
            "low is what makes it hard, and hard is what makes it worth doing"),
        Cue("tempo", "Fast enough that you could not talk through it. This "
                     "drill has a speed floor and a slow dribble will not "
                     "count at all.",
            "a slow pound is just a dribble with a different name"),
        Cue("consistency", "Same height on both hands. Most players pound the "
                           "strong hand and pat the other one.",
            "the gap between your two hands is what a defender plays"),
        Cue("offhand", "Alternate sets rather than alternating dribbles, so "
                       "the weak hand gets a real turn.",
            "swapping every rep lets the good hand carry the drill"),
        Cue("endurance", "Stop when your chest drops toward the ball.",
            "standing over the ball is how you lose sight of everything else"),
    ),
    "bkb_wall_pass": (
        Cue("depth", "Step into every pass. Arms alone is a weak pass and a "
                     "sore elbow.",
            "the power comes from the step, not the hands"),
        Cue("tempo", "Catch and release. If you have to gather it, the pass "
                     "was too soft.",
            "in a game the window closes while you are gathering"),
        Cue("consistency", "Same spot on the wall every time. A pass that "
                           "wanders is a pass a teammate has to reach for.",
            "reaching for a pass is how a possession ends"),
        Cue("endurance", "Stop when you start catching with your chest.",
            "catching with the body is what tired hands do"),
    ),
    "bkb_stance": (
        Cue("position", "Hips below your knees, not bent forward at the waist. "
                        "The clock only runs while you are actually down.",
            "bending at the waist looks low and moves like standing up"),
        Cue("endurance", "Stop when your hips rise, not when your legs burn. "
                         "The burn is the drill working.",
            "the moment your hips come up you are training standing, not guarding"),
    ),
    "lax_goalie_saves": (
        Cue("depth", "Both hands, all the way to the spot. A one-armed stab "
                     "does not count -- the app measures your hands together.",
            "a save is made with two hands out, not with one arm and a lean"),
        Cue("tempo", "Move on the call, not after it. The first move is the "
                     "save; everything after it is catching up.",
            "the ball is already past you by the time you have thought about it"),
        Cue("consistency", "Come back to the exact same ready position every "
                           "single time. Every rep should start from the same "
                           "place.",
            "a ready position that drifts is why one corner feels slower"),
        Cue("offhand", "Your off-stick side will be worse. Everyone's is. Do a "
                       "set going only there.",
            "shooters find the weak side in about a quarter"),
        Cue("endurance", "Stop when your stance starts standing up, not when "
                         "your hands slow down.",
            "tired legs raise the stance, and a high stance loses the low "
            "corners first"),
    ),
    "lax_ground_ball": (
        Cue("depth", "Get low -- bend your knees and drop your hips, do not "
                     "just reach down with your hands.",
            "reaching is the single most common way ground balls are lost"),
        Cue("tempo", "Scoop through the ball and keep moving. Do not stop "
                     "over it.",
            "stopping over a ground ball is how you get hit"),
        Cue("consistency", "Same low position every rep. Bottom hand near the "
                           "ground.",
            "the low hand is what gets under the ball"),
        Cue("offhand", "Scoop from your weak side too -- the ball does not "
                       "care which hand you like.",
            "a ground ball you can only take one way is one you often lose"),
        Cue("endurance", "When you stop getting all the way down, the set is "
                         "over.",
            "a shallow scoop is a missed ground ball with extra steps"),
    ),
    "lax_quick_stick": (
        Cue("depth", "Catch and release in one motion, hands soft.",
            "the whole drill is about not winding up"),
        Cue("tempo", "Quick, but not panicked. Let the ball do the work.",
            "panic hands drop balls"),
        Cue("consistency", "Same height, same spot on the wall.",
            "consistency here is what makes it usable in a game"),
        Cue("offhand", "Same count on your weak hand.",
            "quick stick on your weak side is a real advantage"),
    ),
    "soc_juggle": (
        Cue("consistency", "Small touches, ball no higher than your waist.",
            "high touches are hard to control"),
        Cue("tempo", "Keep an even rhythm rather than chasing saves.",
            "rhythm is what lets you keep going"),
        Cue("offhand", "Alternate feet, even though one will feel wrong.",
            "a one-footed juggler is a one-footed player"),
    ),
    "bkb_dribble": (
        Cue("consistency", "Fingertips, not palms, and keep the ball below "
                           "your waist.",
            "a low hard dribble is much harder to steal"),
        Cue("tempo", "Pound it. A soft dribble is a slow dribble.",
            "the speed off the floor is what beats a defender"),
        Cue("offhand", "Same number of reps with your weak hand.",
            "defenders find your weak hand in about one possession"),
    ),
    "vb_set": (
        Cue("consistency", "Hands in a triangle above your forehead, ball "
                           "straight up.",
            "setting it forward is the habit to break early"),
        Cue("tempo", "Quiet hands. Catching and throwing is a different skill.",
            "a set should be one touch"),
    ),
    "bb_wall_throw": (
        Cue("consistency", "Same target on the wall, four seams across.",
            "the grip is what makes it go straight"),
        Cue("tempo", "Do not rush. Set your feet between throws.",
            "footwork is most of throwing accuracy"),
        Cue("offhand", "Glove-side work counts too -- catch cleanly before you "
                       "throw.",
            "the catch is half of every throw you make in a game"),
    ),
    "ten_wall_rally": (
        Cue("consistency", "Aim above the line every time and let it bounce "
                           "once.",
            "a target turns hitting into practice"),
        Cue("tempo", "Recover to the middle between shots.",
            "getting back is what you actually do in a rally"),
        Cue("offhand", "Backhands get the same count as forehands.",
            "everyone hits your backhand until it holds up"),
    ),
}

#: Used when a drill has no bespoke cue for the component that scored lowest.
#: Deliberately vaguer -- a generic sentence is better than nothing but is not
#: a substitute for one that names the body part, so `bespoke` says which it is.
GENERIC: dict[str, Cue] = {
    "consistency": Cue(
        "consistency", "Try to make every rep look like the one before it.",
        "reps that all look different are hard to improve"),
    "depth": Cue(
        "depth", "Take each rep through its full range, both ends.",
        "the ends of the movement are where the work is"),
    "tempo": Cue(
        "tempo", "Slow down and control the movement instead of rushing it.",
        "control is what makes a rep count"),
    "endurance": Cue(
        "endurance", "Finish the set when the reps start getting smaller, "
                     "rather than pushing to failure.",
        "small tired reps teach your body the small version"),
    "position": Cue(
        "position", "Hold the shape you started in for the whole time.",
        "the shape is the exercise"),
    "offhand": Cue(
        "offhand", "Give your weaker side the same number of reps.",
        "the weaker side is usually the fastest thing to improve"),
}


@dataclass
class Trace:
    """The shape of a well-executed rep, for the reference animation.

    Points are (fraction of the cycle, fraction of target range). Drawn rather
    than filmed, and built from the drill's own thresholds so it cannot fall
    out of agreement with the score.
    """

    points: tuple[tuple[float, float], ...]
    target_rom: float
    tempo_ms: int
    units: str
    hold: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "points": [list(p) for p in self.points],
            "target_rom": self.target_rom,
            "tempo_ms": self.tempo_ms,
            "units": self.units,
            "hold": self.hold,
        }


def _trace(drill: DrillSpec) -> Trace | None:
    """A good rep of this drill as a curve.

    A hold is a flat line, which is exactly the point of a hold. Everything
    else is out and back: down-and-up for a squat, up-and-down for a pull-up.
    The asymmetry is real -- the return half is slower on nearly every drill,
    because that is the half people rush.
    """
    quality = drill.quality
    if quality is None:
        return None

    units = "degrees" if drill.signal.kind is SignalKind.JOINT_ANGLE else "frame heights"
    mid = (quality.tempo_min_ms + quality.tempo_max_ms) // 2

    if drill.metric is Metric.HOLD_SECONDS:
        return Trace(
            points=((0.0, 1.0), (1.0, 1.0)),
            target_rom=quality.target_rom, tempo_ms=mid, units="", hold=True,
        )

    # Out fast, hold the end position briefly, come back slower. The pause at
    # the end and the slower return are the two things a rushed rep loses.
    return Trace(
        points=(
            (0.00, 0.0), (0.30, 0.85), (0.40, 1.0), (0.52, 1.0),
            (0.75, 0.35), (1.00, 0.0),
        ),
        target_rom=quality.target_rom, tempo_ms=mid, units=units,
    )


def clip_path(drill_key: str) -> Path:
    return CLIP_DIR / f"{drill_key}.mp4"


def has_clip(drill_key: str) -> bool:
    """Whether a deployment actually dropped a demonstration file in.

    Read from disk rather than declared in a table, so this cannot claim a
    clip exists when the file is not there.
    """
    return clip_path(drill_key).is_file()


def cues_for(drill_key: str) -> tuple[Cue, ...]:
    return CUES.get(drill_key, ())


def fix_for(drill_key: str, component: str) -> dict[str, Any] | None:
    """The cue for one thing that scored low, falling back to a generic one.

    `bespoke` tells the caller which it got. A generic sentence is worth
    showing, but it is not worth pretending it was written for this drill.
    """
    for cue in cues_for(drill_key):
        if cue.component == component:
            return {**cue.to_dict(), "bespoke": True}
    generic = GENERIC.get(component)
    return {**generic.to_dict(), "bespoke": False} if generic else None


def reference(drill_key: str) -> dict[str, Any]:
    """Everything the capture screen needs to show a child how to be right."""
    drill = DRILLS_BY_KEY.get(drill_key)
    if drill is None:
        return {}
    trace = _trace(drill)
    return {
        "drill_key": drill_key,
        "drill_name": drill.name,
        "setup_hint": drill.setup_hint,
        "cues": [c.to_dict() for c in cues_for(drill_key)],
        "trace": trace.to_dict() if trace else None,
        # Self-hosted, and only claimed when the file is actually on disk.
        "clip_url": f"/static/technique/{drill_key}.mp4" if has_clip(drill_key) else "",
        "has_clip": has_clip(drill_key),
    }


def coverage() -> dict[str, Any]:
    """Which drills have bespoke cues, and which are on generic ones.

    Reported rather than hidden: "every drill has a reference" is only true
    in the sense that every drill has *something*, and the difference between
    a sentence written for the squat and one written for anything is the
    difference between advice and filler.
    """
    bespoke = [d.key for d in ALL_DRILLS if CUES.get(d.key)]
    return {
        "drills": len(ALL_DRILLS),
        "with_cues": len(bespoke),
        "without_cues": [d.key for d in ALL_DRILLS if not CUES.get(d.key)],
        "with_trace": sum(1 for d in ALL_DRILLS if _trace(d) is not None),
        "with_clip": [d.key for d in ALL_DRILLS if has_clip(d.key)],
    }
