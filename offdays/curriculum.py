"""A lacrosse IQ film curriculum, ready for a coach to hang clips on.

The film module has always shipped empty. That was the largest gap in the
product for a lacrosse program: the machinery to teach the half of the game
that is learned by watching -- reading a slide, seeing a cut two passes early,
knowing where help is coming from -- existed, and nothing had been loaded into
it.

**What this file is, and what it deliberately is not.**

It is the curriculum: what to teach, at what age, to which positions, how long
the cut should be, and the comprehension question with the reason its answer
is right. That is the part that needs somebody who has coached the sport, and
it is the part that takes an evening to write properly.

It is **not a list of video links**, and that omission is on purpose. Picking
real clips means watching them, and a catalogue of plausible-looking YouTube
ids that turn out to be dead, wrong, or somebody's unrelated highlight reel
would be far worse than an empty shelf -- it would look full. So each topic
carries a `find` note describing exactly what footage to cut, and a coach
supplies the id. That is a few minutes per clip against an evening of writing
the questions.

**On length.** Clip caps are enforced per age band, not advisory: a clip
longer than the band's ceiling is filtered out and the athlete never sees it.
So every topic's `target_s` is checked against the ceiling of its own
`min_age`, and a test enforces it. The practical consequence is worth stating
plainly -- a four-minute clip is visible only to nineteen-year-olds, and
anything for under-13s has to come in under 75 seconds. The bulk of this
curriculum therefore sits at two to three minutes for 13+ and 15+, with a
short fundamentals set for the youngest athletes who otherwise get nothing.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from . import film


@dataclass(frozen=True)
class Ask:
    """The comprehension question, and why the answer is the answer."""

    prompt: str
    options: tuple[str, ...]
    answer: int
    because: str


@dataclass(frozen=True)
class Topic:
    key: str
    title: str
    focus: str
    positions: tuple[str, ...]
    min_age: int
    max_age: int
    #: Seconds. Checked against the ceiling for `min_age` -- see the docstring.
    target_s: int
    ask: Ask
    #: What footage to cut. Written for whoever is holding the scrub bar.
    find: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "focus": self.focus,
            "positions": list(self.positions),
            "min_age": self.min_age,
            "max_age": self.max_age,
            "target_s": self.target_s,
            "find": self.find,
            "question": {
                "prompt": self.ask.prompt,
                "options": list(self.ask.options),
                "answer": self.ask.answer,
                "because": self.ask.because,
            },
        }


FIELD = ("attack", "midfield", "defense", "lsm")
OFFENSE = ("attack", "midfield")
DEFENCE = ("defense", "lsm", "midfield")

# ---------------------------------------------------------------------------
# Youngest athletes. Under 75 seconds, because that is the ceiling for the
# Under-11 band and these are the only clips they can see at all.
# ---------------------------------------------------------------------------

FUNDAMENTALS: tuple[Topic, ...] = (
    Topic(
        key="lax_iq_space_without_ball",
        title="Where to stand when you don't have it",
        focus="Spacing",
        positions=OFFENSE, min_age=0, max_age=200, target_s=70,
        find=(
            "Any settled six-on-six possession. Cut a clip where the offence "
            "is spread and one where three players have collapsed to the same "
            "spot, back to back."
        ),
        ask=Ask(
            prompt="Two teammates are standing near each other. What happens?",
            options=(
                "One defender can guard both of them",
                "They can pass to each other faster",
                "It confuses the defence",
            ),
            answer=0,
            because=(
                "Standing close together lets one defender cover two players. "
                "Spreading out means every defender has their own job."
            ),
        ),
    ),
    Topic(
        key="lax_iq_call_ground_ball",
        title="Calling for a ground ball",
        focus="Ground balls",
        positions=FIELD, min_age=0, max_age=200, target_s=65,
        find=(
            "A loose ball where one player calls 'ball' and a teammate calls "
            "'release' or 'help'. Youth or high school footage is better than "
            "college here, the calls are louder and clearer."
        ),
        ask=Ask(
            prompt="Your teammate yells \"ball!\" on a loose ball. What is your job?",
            options=(
                "Go for the ball too, in case they miss",
                "Push the nearest opponent away from them",
                "Stand still and watch",
            ),
            answer=1,
            because=(
                "One player picks it up, everyone else clears a path. Two "
                "teammates diving at the same ball is how the other team gets it."
            ),
        ),
    ),
    Topic(
        key="lax_iq_back_up_shot",
        title="Backing up a shot",
        focus="Off-ball",
        positions=OFFENSE, min_age=0, max_age=200, target_s=70,
        find=(
            "A shot that misses wide with an attacker already moving behind "
            "the goal to retrieve it. Contrast with one where nobody backs it "
            "up and the ball goes out of bounds."
        ),
        ask=Ask(
            prompt="A teammate shoots and misses. Why run behind the goal?",
            options=(
                "To celebrate if it goes in",
                "Because the ball goes to whoever is closest when it leaves the field",
                "To hide from your defender",
            ),
            answer=1,
            because=(
                "On a missed shot, possession goes to whoever is nearest the "
                "ball when it crosses the line. Backing up turns a turnover "
                "back into your ball."
            ),
        ),
    ),
)

# ---------------------------------------------------------------------------
# 13 and up. Ceiling is 140 seconds, so nothing here runs past 2:20.
# ---------------------------------------------------------------------------

CORE: tuple[Topic, ...] = (
    Topic(
        key="lax_iq_cut_on_head_turn",
        title="Cut when his head turns",
        focus="Off-ball movement",
        positions=OFFENSE, min_age=13, max_age=200, target_s=120,
        find=(
            "Slow-motion of an off-ball defender turning to watch the ball, "
            "with the attacker breaking backdoor in the same beat. Two or "
            "three examples is better than one long possession."
        ),
        ask=Ask(
            prompt="When is the best moment to cut backdoor?",
            options=(
                "When your defender is watching you closely",
                "The instant your defender turns his head to the ball",
                "As soon as your team crosses midfield",
            ),
            answer=1,
            because=(
                "A defender cannot watch you and the ball at once. The moment "
                "his head turns is the moment he has lost you, and it lasts "
                "about a second."
            ),
        ),
    ),
    Topic(
        key="lax_iq_give_and_go",
        title="The give-and-go",
        focus="Two-man game",
        positions=OFFENSE, min_age=13, max_age=200, target_s=115,
        find=(
            "A pass followed immediately by a cut to the goal and a return "
            "feed. Look for one where the defender relaxes after the pass, "
            "that relaxation is the whole lesson."
        ),
        ask=Ask(
            prompt="What makes a give-and-go work?",
            options=(
                "Throwing the pass as hard as you can",
                "The defender relaxing the moment you give up the ball",
                "Having the fastest player on the field",
            ),
            answer=1,
            because=(
                "Most defenders loosen up the instant their man passes. Cutting "
                "in that half-second is what beats them, not speed."
            ),
        ),
    ),
    Topic(
        key="lax_iq_approach_breakdown",
        title="Approach and break down",
        focus="On-ball defence",
        positions=DEFENCE, min_age=13, max_age=200, target_s=125,
        find=(
            "A defender closing out on a ball carrier, one clip where he "
            "breaks down under control, one where he runs through and gets "
            "beaten. The contrast carries the point."
        ),
        ask=Ask(
            prompt="Why break down before you reach the ball carrier?",
            options=(
                "To look organised to your coach",
                "Because a defender at full speed can only go one direction",
                "To give your teammates time to arrive",
            ),
            answer=1,
            because=(
                "Momentum is the dodger's best friend. A defender still "
                "sprinting can be beaten with one change of direction; a "
                "defender broken down can react either way."
            ),
        ),
    ),
    Topic(
        key="lax_iq_ground_ball_box_out",
        title="Box out before you scoop",
        focus="Ground balls",
        positions=FIELD, min_age=13, max_age=200, target_s=110,
        find=(
            "A ground ball scrum where one player moves the opponent first and "
            "scoops second. Slow motion helps, the box-out happens fast and "
            "is easy to miss at speed."
        ),
        ask=Ask(
            prompt="Two players arrive at a ground ball together. Who gets it?",
            options=(
                "Whoever reaches down first",
                "Whoever moves the other player first",
                "Whoever has the longer stick",
            ),
            answer=1,
            because=(
                "Reaching first with someone on your hip means you scoop into "
                "contact and lose it. Move them, then scoop into space."
            ),
        ),
    ),
    Topic(
        key="lax_iq_crease_positioning",
        title="Off-ball defence and the crease",
        focus="Team defence",
        positions=DEFENCE, min_age=13, max_age=200, target_s=130,
        find=(
            "An off-ball defender in a position to see both his man and the "
            "ball, then one caught ball-watching while his man cuts. Freeze "
            "frames on head position are ideal."
        ),
        ask=Ask(
            prompt="Where should an off-ball defender be looking?",
            options=(
                "At the ball, so he can react to a shot",
                "At his own man, so he never loses him",
                "Positioned so he can see both without turning his head",
            ),
            answer=2,
            because=(
                "Watching only the ball loses your man; watching only your man "
                "loses the play. Position beats attention, stand where both "
                "are in front of you."
            ),
        ),
    ),
    Topic(
        key="lax_iq_faceoff_whistle",
        title="What a fast clamp looks like",
        focus="Face-offs",
        positions=("fogo",), min_age=13, max_age=200, target_s=110,
        find=(
            "Slow motion of a clamp from the whistle. Ideally two clips: one "
            "won on speed and one lost by a fraction, so the difference is "
            "visible rather than described."
        ),
        ask=Ask(
            prompt="Where is a face-off usually decided?",
            options=(
                "In the first half second, on the clamp",
                "In the wrestling that comes after",
                "By whichever wing player is fastest",
            ),
            answer=0,
            because=(
                "The clamp happens in roughly the time it takes to blink. "
                "Everything after it is trying to recover from what already "
                "happened."
            ),
        ),
    ),
    Topic(
        key="lax_iq_goalie_arc",
        title="Arc and depth",
        focus="Goaltending",
        positions=("goalie",), min_age=13, max_age=200, target_s=125,
        find=(
            "A goalie moving on his arc as the ball moves around the perimeter. "
            "An overhead or elevated angle shows the arc far better than a "
            "sideline camera."
        ),
        ask=Ask(
            prompt="Why does a goalie move on an arc instead of standing still?",
            options=(
                "To stay warm during slow possessions",
                "To keep the same angle on the goal as the ball moves",
                "To make the shooter nervous",
            ),
            answer=1,
            because=(
                "Standing still means every pass changes the angle you are "
                "covering. Moving on the arc keeps the same amount of net "
                "hidden no matter where the ball is."
            ),
        ),
    ),
)

# ---------------------------------------------------------------------------
# 15 and up. Ceiling is 170 seconds -- these are the concepts that need the
# extra minute to show properly.
# ---------------------------------------------------------------------------

ADVANCED: tuple[Topic, ...] = (
    Topic(
        key="lax_iq_read_the_slide",
        title="Seeing the slide before it comes",
        focus="Dodging",
        positions=OFFENSE, min_age=15, max_age=200, target_s=165,
        find=(
            "A dodge from up top with the crease defender's first step visible "
            "in frame. The lesson is in the slider's feet, not the dodger's, so "
            "the cut has to keep both on screen."
        ),
        ask=Ask(
            prompt="A dodger should be watching which player?",
            options=(
                "The defender guarding him",
                "The goalie, to pick a corner",
                "The next defender over, who will slide",
            ),
            answer=2,
            because=(
                "Your own defender tells you nothing you cannot feel. The "
                "slide is what decides whether this becomes a shot or a pass, "
                "and it starts before it arrives."
            ),
        ),
    ),
    Topic(
        key="lax_iq_slide_package",
        title="Who is hot",
        focus="Team defence",
        positions=DEFENCE, min_age=15, max_age=200, target_s=170,
        find=(
            "A full defensive possession with an adjacent slide, ideally with "
            "audible communication. Wide angle throughout, a tight shot on "
            "the ball destroys this clip."
        ),
        ask=Ask(
            prompt="What does calling \"I'm hot\" mean?",
            options=(
                "You are the next defender to slide to the ball",
                "You have been beaten and need help",
                "You want the ball on the clear",
            ),
            answer=0,
            because=(
                "Hot is a promise to the on-ball defender that somebody is "
                "coming. Defences break down when nobody says it, or when two "
                "players say it at once."
            ),
        ),
    ),
    Topic(
        key="lax_iq_recover_after_slide",
        title="Recovering after a slide",
        focus="Team defence",
        positions=DEFENCE, min_age=15, max_age=200, target_s=160,
        find=(
            "The rotation after a slide, who fills the sliding defender's "
            "spot. Follow the second and third rotation, not the slide itself; "
            "that is where possessions are actually lost."
        ),
        ask=Ask(
            prompt="After a defender slides, what has to happen?",
            options=(
                "Everyone returns to their original man",
                "The next defender fills his spot and the whole defence rotates",
                "The goalie calls a timeout",
            ),
            answer=1,
            because=(
                "A slide always leaves someone open. Defence is not the slide, "
                "it is the rotation behind it, and it has to happen before "
                "the extra pass arrives."
            ),
        ),
    ),
    Topic(
        key="lax_iq_feeding_from_x",
        title="Feeding from X",
        focus="Attack",
        positions=("attack",), min_age=15, max_age=200, target_s=155,
        find=(
            "An attacker behind the goal drawing a slide and finding the crease. "
            "Include one clip where the feed goes early and is intercepted."
        ),
        ask=Ask(
            prompt="What makes a feed from behind the goal dangerous?",
            options=(
                "The goalie cannot see the ball and the crease at once",
                "It is a shorter pass than from up top",
                "Defenders are not allowed behind the goal",
            ),
            answer=0,
            because=(
                "A goalie facing you cannot also watch the crease behind him. "
                "The feed arrives in the half second his head has to turn."
            ),
        ),
    ),
    Topic(
        key="lax_iq_clearing",
        title="Clearing: outlet and fill",
        focus="Transition",
        positions=DEFENCE + ("goalie",), min_age=15, max_age=200, target_s=165,
        find=(
            "A clear from a goalie save to the offensive end. Wide angle, and "
            "let it run, clears are about the shape of five players, not one "
            "good pass."
        ),
        ask=Ask(
            prompt="What is the first job after a save?",
            options=(
                "Run the ball up the field yourself",
                "Get wide and give the goalie two outlets",
                "Substitute as fast as possible",
            ),
            answer=1,
            because=(
                "A goalie with one option is a goalie under pressure. Two "
                "outlets on opposite sides means the ride has to choose, and "
                "whichever it chooses is wrong."
            ),
        ),
    ),
    Topic(
        key="lax_iq_riding",
        title="Riding: turning the ball back",
        focus="Transition",
        positions=OFFENSE, min_age=15, max_age=200, target_s=150,
        find=(
            "A successful ride that forces a turnover. Show the sideline being "
            "used as an extra defender, that is the concept most young "
            "players miss."
        ),
        ask=Ask(
            prompt="What is a rider actually trying to do?",
            options=(
                "Check the ball out of the carrier's stick",
                "Force the ball toward a sideline and take away half the field",
                "Cover the man closest to the goal",
            ),
            answer=1,
            because=(
                "Rides rarely win the ball with a check. They win by making "
                "the field smaller, until the only pass available is the one "
                "you are waiting for."
            ),
        ),
    ),
    Topic(
        key="lax_iq_faceoff_exit",
        title="Exit and the wings",
        focus="Face-offs",
        positions=("fogo", "midfield"), min_age=15, max_age=200, target_s=155,
        find=(
            "A won face-off followed by the exit and the wing play. Keep the "
            "wings in frame from the whistle, most face-off footage cuts "
            "them out entirely, which is why nobody learns this."
        ),
        ask=Ask(
            prompt="A face-off man wins the clamp. What decides possession?",
            options=(
                "Whether he can outrun everybody",
                "Where he exits, and whether a wing is there to receive",
                "The referee's positioning",
            ),
            answer=1,
            because=(
                "Winning the clamp only starts the play. A clamp with nowhere "
                "to put the ball becomes a scrum, and scrums are a coin flip."
            ),
        ),
    ),
    Topic(
        key="lax_iq_man_up_spacing",
        title="Man-up: the extra pass",
        focus="Special teams",
        positions=OFFENSE, min_age=15, max_age=200, target_s=160,
        find=(
            "An extra-man possession that scores on the second or third pass "
            "after the slide. Contrast with one that shoots the first look and "
            "gives it back."
        ),
        ask=Ask(
            prompt="Why does man-up offence make the extra pass?",
            options=(
                "To use up the penalty time",
                "Because a defence short one player cannot rotate twice",
                "Because coaches ask for five passes",
            ),
            answer=1,
            because=(
                "Five defenders can cover one rotation. The second one always "
                "leaves somebody genuinely open, the extra pass is what finds "
                "them."
            ),
        ),
    ),
    Topic(
        key="lax_iq_man_down",
        title="Man-down: protect the pipe",
        focus="Special teams",
        positions=DEFENCE + ("goalie",), min_age=15, max_age=200, target_s=155,
        find=(
            "A man-down defence conceding an outside shot rather than a crease "
            "look. The best clip is one where the defence 'loses' the "
            "possession on paper and still gets the stop."
        ),
        ask=Ask(
            prompt="A man-down defence gives up which shot on purpose?",
            options=(
                "The one from the crease, because it is quicker",
                "The outside shot, because the goalie can see it",
                "None, it tries to cover everything",
            ),
            answer=1,
            because=(
                "You cannot cover everything with five. So you concede the "
                "shot your goalie can actually save and take away the one he "
                "cannot see."
            ),
        ),
    ),
    Topic(
        key="lax_iq_when_to_dodge",
        title="When to dodge, when to move it",
        focus="Decision-making",
        positions=OFFENSE, min_age=15, max_age=200, target_s=165,
        find=(
            "Two possessions side by side: one where a dodge is the right call "
            "against an isolated defender, one where the ball should have moved "
            "and the dodge died in a double team."
        ),
        ask=Ask(
            prompt="You catch the ball up top with a defender set and help nearby. What now?",
            options=(
                "Dodge, you have the ball, so it is your turn",
                "Move it and make the defence shift first",
                "Shoot from where you are",
            ),
            answer=1,
            because=(
                "Dodging into a set defence with help waiting is how "
                "possessions end. Move the ball, make them slide, then dodge "
                "the defender who is late."
            ),
        ),
    ),
)

TOPICS: tuple[Topic, ...] = FUNDAMENTALS + CORE + ADVANCED
BY_KEY = {t.key: t for t in TOPICS}


#: Sports with a syllabus. Looked up rather than branched on, so a third sport
#: is a data change here and nothing else.
BY_SPORT: dict[str, tuple[Topic, ...]] = {}


def topics_for(sport: str) -> tuple[Topic, ...]:
    """The syllabus for a sport, or empty if it has none yet.

    Empty rather than an error on purpose: most sports have no curriculum, and
    a coach asking about one should be told there is nothing yet rather than
    shown a stack trace.
    """
    return BY_SPORT.get(sport, ())


def catalogue(sport: str = "lacrosse") -> dict[str, Any]:
    """The whole curriculum, for a coach deciding what to film or find."""
    topics = topics_for(sport)
    return {
        "sport": sport,
        "topics": [t.to_dict() for t in topics],
        "count": len(topics),
        "note": (
            "Every topic here is ready except its video. Clip length caps are "
            "enforced per age band, so target_s is already inside the ceiling "
            "for each topic's minimum age."
        ) if topics else (
            f"There is no film curriculum for {sport} yet. The module is "
            "built and the age caps apply, what is missing is somebody who "
            "coaches the sport writing the topics."
        ),
        # Carried on the response a coach reads immediately before going to
        # find footage, which is the only moment this advice can still change
        # what they pick. The same rule is enforced on the way back in.
        "what_to_cut": film.WHAT_TO_CUT,
        "not_this": (
            "Not highlight reels. A montage of finishes teaches nothing while "
            "looking exactly like film study, it fills the shelf, it earns "
            "the same XP, and the athlete comes away having watched somebody "
            f"else be good at {sport}. Clips whose titles read as highlight "
            "reels are refused."
        ),
    }


def install(
    store,
    org_id: int,
    video_ids: dict[str, str],
    *,
    sport: str = "lacrosse",
    provider: str = "youtube",
    created_by: int | None = None,
) -> dict[str, Any]:
    """Create clips for the topics a coach has supplied a video for.

    Silent about the rest rather than creating placeholders. A clip row with
    no working video is a broken clip an athlete gets assigned, and the whole
    reason this file ships without ids is to avoid exactly that -- so a topic
    without one simply does not become a clip, and is reported back so the
    coach can see what is still outstanding.

    Idempotent by title: running it again after adding three more links adds
    three clips rather than duplicating the whole curriculum.
    """
    existing = {
        row["title"]
        for row in store.conn.execute(
            "SELECT title FROM clips WHERE org_id = ?", (org_id,)
        )
    }

    made, awaiting, failed, already = [], [], [], []
    for topic in topics_for(sport):
        raw = (video_ids.get(topic.key) or "").strip()
        if not raw:
            awaiting.append(topic.key)
            continue
        if topic.title in existing:
            already.append(topic.key)
            continue
        try:
            store.create_clip(
                org_id,
                raw,
                topic.title,
                focus=topic.focus,
                provider=provider,
                end_s=topic.target_s,
                positions=list(topic.positions),
                min_age=topic.min_age,
                max_age=topic.max_age,
                question={
                    "prompt": topic.ask.prompt,
                    "options": list(topic.ask.options),
                    "answer": topic.ask.answer,
                    "because": topic.ask.because,
                },
                created_by=created_by,
            )
            made.append(topic.key)
        except Exception as exc:  # noqa: BLE001 - one bad link must not stop the rest
            failed.append({"topic": topic.key, "reason": str(exc)})

    return {
        "installed": made,
        "already_present": already,
        "awaiting_video": awaiting,
        "failed": failed,
        "topics_total": len(TOPICS),
    }


# ---------------------------------------------------------------------------
# Basketball
#
# Same rules as the lacrosse syllabus above: no video ids, every target length
# inside the ceiling for its own minimum age, and a comprehension question with
# the reason its answer is right. What differs is where the decisions live --
# lacrosse IQ is mostly about a slide and who is hot; basketball IQ is mostly
# about spacing and what the second defender does.
# ---------------------------------------------------------------------------

GUARDS = ("guard",)
PERIMETER = ("guard", "wing")
BIGS = ("post",)
ALL_BKB = ("guard", "wing", "post")

BKB_FUNDAMENTALS: tuple[Topic, ...] = (
    Topic(
        key="bkb_iq_spacing",
        title="Stand further apart than feels right",
        focus="Spacing",
        positions=ALL_BKB, min_age=0, max_age=200, target_s=70,
        find=(
            "Any half-court possession. Cut one where the offence is spread "
            "and one where two players have drifted to the same side, back to "
            "back. Youth footage is better here, the mistake is more obvious."
        ),
        ask=Ask(
            prompt="Two teammates end up on the same side of the floor. What happens?",
            options=(
                "One defender can guard both of them",
                "They can pass to each other more easily",
                "It drags the defence out of position",
            ),
            answer=0,
            because=(
                "Standing close together lets one defender cover two players. "
                "Spreading out means every defender has their own job."
            ),
        ),
    ),
    Topic(
        key="bkb_iq_hands_ready",
        title="Hands ready before the pass comes",
        focus="Catching",
        positions=ALL_BKB, min_age=0, max_age=200, target_s=65,
        find=(
            "A possession with two or three passes. Look for one player "
            "already showing their hands and one who reaches late. The "
            "difference in what happens next is the clip."
        ),
        ask=Ask(
            prompt="Why show your hands before the ball is thrown?",
            options=(
                "So the passer knows you want it and can hit you on time",
                "So the defender cannot see the pass coming",
                "It makes the catch look better",
            ),
            answer=0,
            because=(
                "A passer throws to a target. No target, no pass, and a late "
                "reach turns a good pass into a fumble."
            ),
        ),
    ),
    Topic(
        key="bkb_iq_box_out",
        title="Find a body before you find the ball",
        focus="Rebounding",
        positions=ALL_BKB, min_age=0, max_age=200, target_s=70,
        find=(
            "Two rebounds side by side: one where a player turns and makes "
            "contact first, one where everybody watches the shot. The second "
            "is easy to find in any youth game."
        ),
        ask=Ask(
            prompt="A shot goes up. What is the first thing you do?",
            options=(
                "Turn and put your body on the player you are guarding",
                "Jump straight away so you are highest",
                "Watch where the ball is going to bounce",
            ),
            answer=0,
            because=(
                "Whoever gets a body on someone first decides who can jump. "
                "Watching the ball is how the other team gets the rebound."
            ),
        ),
    ),
)

BKB_CORE: tuple[Topic, ...] = (
    Topic(
        key="bkb_iq_help_side",
        title="Where the second defender comes from",
        focus="Team defence",
        positions=ALL_BKB, min_age=13, max_age=200, target_s=125,
        find=(
            "A drive from the wing where a help defender steps in. Cut it wide "
            "enough to see the helper *before* they move, the interesting "
            "part is where they were standing."
        ),
        ask=Ask(
            prompt="You are guarding someone on the weak side. Where do you stand?",
            options=(
                "Off your player, where you can see them and the ball",
                "Right next to your player so they cannot get open",
                "Under the basket where the rebound will come",
            ),
            answer=0,
            because=(
                "Help defence is about being able to see both. Standing on your "
                "player means you never see the drive coming, and by the time "
                "you do it is a layup."
            ),
        ),
    ),
    Topic(
        key="bkb_iq_screen_read",
        title="Reading a ball screen",
        focus="Two-man game",
        positions=PERIMETER, min_age=13, max_age=200, target_s=130,
        find=(
            "One possession with a high ball screen. Cut three versions if you "
            "can find them: the defender goes over, goes under, and switches. "
            "The read is different every time."
        ),
        ask=Ask(
            prompt="Your defender goes under the screen. What should you do?",
            options=(
                "Shoot, because they have given you the space",
                "Drive hard to the rim anyway",
                "Pass it and reset the offence",
            ),
            answer=0,
            because=(
                "Going under is a defender saying they will live with the shot. "
                "If you never take it, they will do it every time and you have "
                "lost the screen."
            ),
        ),
    ),
    Topic(
        key="bkb_iq_pass_early",
        title="The pass one beat early",
        focus="Passing",
        positions=ALL_BKB, min_age=13, max_age=200, target_s=115,
        find=(
            "A possession where a cutter is open and the pass arrives late. "
            "Pause on the frame where the window was actually open, that is "
            "the whole lesson."
        ),
        ask=Ask(
            prompt="A teammate cuts open. When do you throw it?",
            options=(
                "As they start to get open, so it arrives as they get there",
                "Once they are clearly open and you can see it",
                "After you have faked to move the defender",
            ),
            answer=0,
            because=(
                "The window closes while you are deciding. A pass thrown when "
                "you can see they are open is a pass the help defender can see too."
            ),
        ),
    ),
    Topic(
        key="bkb_iq_close_out",
        title="Closing out without flying past",
        focus="On-ball defence",
        positions=ALL_BKB, min_age=13, max_age=200, target_s=120,
        find=(
            "A defender running at a shooter. Find one who breaks down under "
            "control and one who runs straight past. Both happen every game."
        ),
        ask=Ask(
            prompt="You run at a shooter. What do you do in the last two steps?",
            options=(
                "Short choppy steps with a hand up, under control",
                "Keep sprinting and jump at the shot",
                "Stop early and give them the shot",
            ),
            answer=0,
            because=(
                "A closeout that arrives out of control is a drive waiting to "
                "happen. The hand bothers the shot; the feet stop the drive."
            ),
        ),
    ),
    Topic(
        key="bkb_iq_transition",
        title="Running the floor in the right lane",
        focus="Transition",
        positions=ALL_BKB, min_age=13, max_age=200, target_s=120,
        find=(
            "A fast break with three players filling three lanes, and a second "
            "one where everybody runs to the ball. The second is much easier to "
            "find."
        ),
        ask=Ask(
            prompt="Your team gets a rebound and goes. Where do you run?",
            options=(
                "Wide, to your own lane, and all the way to the rim",
                "To the ball, to give the rebounder an option",
                "Behind the play as the safety",
            ),
            answer=0,
            because=(
                "Three players in three lanes stretches two defenders past "
                "breaking point. Everybody running to the ball turns a break "
                "into a crowd."
            ),
        ),
    ),
    Topic(
        key="bkb_iq_post_seal",
        title="Sealing before the ball moves",
        focus="Post play",
        positions=BIGS, min_age=13, max_age=200, target_s=115,
        find=(
            "A post player establishing position as the ball is swung, not "
            "after. The timing is the lesson, so cut it from before the pass."
        ),
        ask=Ask(
            prompt="When do you fight for post position?",
            options=(
                "While the ball is still being passed around the perimeter",
                "Once the ball reaches the player who will feed you",
                "After you see the defender relax",
            ),
            answer=0,
            because=(
                "Position won after the ball arrives is position won too late. "
                "The seal has to already be there when the passer looks."
            ),
        ),
    ),
)

BKB_ADVANCED: tuple[Topic, ...] = (
    Topic(
        key="bkb_iq_tag_the_roller",
        title="Tagging the roller",
        focus="Team defence",
        positions=ALL_BKB, min_age=15, max_age=200, target_s=160,
        find=(
            "A pick and roll where the low defender steps across to touch the "
            "roller before recovering. Cut it wide, the whole point is what "
            "the third and fourth defenders do."
        ),
        ask=Ask(
            prompt="A screener rolls to the rim. Whose job is it to stop them?",
            options=(
                "The nearest weak-side defender, who tags then recovers",
                "The defender who was guarding the screener",
                "Whoever is closest to the basket",
            ),
            answer=0,
            because=(
                "The screener's defender is usually behind the play. Stopping "
                "the roll is a weak-side job, and it is a tag and recover, not "
                "a switch."
            ),
        ),
    ),
    Topic(
        key="bkb_iq_short_roll",
        title="The short roll and the four-on-three",
        focus="Two-man game",
        positions=ALL_BKB, min_age=15, max_age=200, target_s=165,
        find=(
            "A trapped ball handler passing to the screener in the middle of "
            "the floor. The clip is what the screener does next, not the pass."
        ),
        ask=Ask(
            prompt="You catch it in the middle with two defenders on the ball. What now?",
            options=(
                "Look up, you are attacking four against three",
                "Drive straight to the rim before they recover",
                "Pass it straight back out to reset",
            ),
            answer=0,
            because=(
                "Two defenders on the ball means three defenders on four "
                "players. Driving into that is the one way to waste it."
            ),
        ),
    ),
    Topic(
        key="bkb_iq_gap_help",
        title="One pass away, two feet in the gap",
        focus="Team defence",
        positions=ALL_BKB, min_age=15, max_age=200, target_s=155,
        find=(
            "A defender sitting in the driving lane while their player has the "
            "ball one pass away. Look for the moment they recover on the catch."
        ),
        ask=Ask(
            prompt="Your player is one pass away from the ball. Where are your feet?",
            options=(
                "In the gap, close enough to recover when they catch it",
                "Denying the pass with a hand in the lane",
                "Level with your player so they cannot go backdoor",
            ),
            answer=0,
            because=(
                "Full denial one pass away gets beaten backdoor and leaves no "
                "help. Sitting in the gap stops the drive and still lets you "
                "close out."
            ),
        ),
    ),
    Topic(
        key="bkb_iq_shot_selection",
        title="A good shot, and a shot you can make",
        focus="Decision-making",
        positions=ALL_BKB, min_age=15, max_age=200, target_s=160,
        find=(
            "Two shots from similar spots, one early in the clock with a "
            "defender closing, one after a pass with feet set. Same distance, "
            "different shots."
        ),
        ask=Ask(
            prompt="What makes a shot a good shot?",
            options=(
                "Feet set, in your range, and nobody is more open",
                "It is a shot you have made before",
                "It is early in the shot clock so there is time to rebound",
            ),
            answer=0,
            because=(
                "Being able to make a shot is not the same as it being the "
                "right one. The question is always whether a teammate has a "
                "better one."
            ),
        ),
    ),
    Topic(
        key="bkb_iq_late_clock",
        title="Late clock, and what changes",
        focus="Decision-making",
        positions=ALL_BKB, min_age=15, max_age=200, target_s=150,
        find=(
            "A possession that reaches the last eight seconds of the clock. "
            "The clip is how the shape of the offence changes, not the shot."
        ),
        ask=Ask(
            prompt="Eight seconds left on the shot clock and nothing is open. What now?",
            options=(
                "Get to a shot you can make, and get bodies to the glass",
                "Swing it around the perimeter until something opens",
                "Drive it and try to draw a foul",
            ),
            answer=0,
            because=(
                "Late clock, a contested shot with three players rebounding "
                "beats a turnover or a heave. The offensive rebound is the "
                "second chance."
            ),
        ),
    ),
)

BKB_TOPICS: tuple[Topic, ...] = BKB_FUNDAMENTALS + BKB_CORE + BKB_ADVANCED


# Registered at the end, once both syllabuses exist. A sport is a key here and
# nothing else -- there is no branch anywhere that names one.


# ---------------------------------------------------------------------------
# Volleyball
#
# Same rules again: no video ids, every target length inside the ceiling for its
# own minimum age, a question with the reason its answer is right. What differs
# is where the decisions live. Volleyball IQ is mostly about *reading a set
# before it is set* and about where the six of you are standing -- the sport is
# played in a small box and almost every error is a positioning error.
# ---------------------------------------------------------------------------

VB_ALL = ("setter", "hitter", "middle", "libero")
VB_FRONT = ("hitter", "middle")
VB_BACK = ("setter", "libero")

VB_FUNDAMENTALS: tuple[Topic, ...] = (
    Topic(
        key="vb_iq_call_it",
        title="Call it before you touch it",
        focus="Communication",
        positions=VB_ALL, min_age=0, max_age=200, target_s=65,
        find=(
            "Any rally with a ball dropping between two players. Cut one where "
            "somebody calls early and one where nobody does. Youth footage is "
            "better, the silence is more obvious."
        ),
        ask=Ask(
            prompt="A ball is coming down between you and a teammate. What do you do?",
            options=(
                "Call for it loudly and early, before it gets there",
                "Wait to see if they call it first",
                "Go for it, whoever gets there first takes it",
            ),
            answer=0,
            because=(
                "Two players both going is how the ball lands between them, and "
                "how ankles get rolled. The early call decides it while there "
                "is still time to move."
            ),
        ),
    ),
    Topic(
        key="vb_iq_ready_early",
        title="Be stopped before the ball is hit",
        focus="Ready position",
        positions=VB_ALL, min_age=0, max_age=200, target_s=70,
        find=(
            "A serve receive. Look for a passer who is already set and still "
            "when contact happens, and one who is still shuffling. The "
            "difference in the pass is the clip."
        ),
        ask=Ask(
            prompt="When should you be in your ready position?",
            options=(
                "Before the other team contacts the ball",
                "As soon as you see where the ball is going",
                "While you are moving toward the ball",
            ),
            answer=0,
            because=(
                "You cannot change direction while you are already moving. "
                "Being stopped first is what lets you go either way."
            ),
        ),
    ),
    Topic(
        key="vb_iq_three_touches",
        title="Why three touches beats one",
        focus="Team offence",
        positions=VB_ALL, min_age=0, max_age=200, target_s=70,
        find=(
            "Two rallies side by side: one where the team passes, sets and "
            "hits, and one where somebody sends the first ball straight back "
            "over. Both happen constantly at youth level."
        ),
        ask=Ask(
            prompt="The ball comes over. Why not just send it straight back?",
            options=(
                "Three touches let you attack instead of just returning it",
                "It is against the rules to send it back on one",
                "It gives your team time to rest",
            ),
            answer=0,
            because=(
                "A first-ball return arrives slow and easy to read. Three "
                "touches are what turn a defence into an attack."
            ),
        ),
    ),
)

VB_CORE: tuple[Topic, ...] = (
    Topic(
        key="vb_iq_read_the_setter",
        title="Reading the setter's hands",
        focus="Blocking",
        positions=VB_FRONT, min_age=13, max_age=200, target_s=125,
        find=(
            "A setter releasing the ball, cut from before their hands move. "
            "The clip is the shoulders and hands, not where the ball ends up."
        ),
        ask=Ask(
            prompt="What tells you where a set is going before it gets there?",
            options=(
                "The setter's shoulders and where their hands are pointing",
                "Which hitter starts their approach first",
                "Where the setter is looking",
            ),
            answer=0,
            because=(
                "Good setters hide their eyes but cannot hide their platform. "
                "The shoulders have to face where the ball is going."
            ),
        ),
    ),
    Topic(
        key="vb_iq_seams",
        title="Passing the seam",
        focus="Serve receive",
        positions=VB_ALL, min_age=13, max_age=200, target_s=115,
        find=(
            "A serve landing between two passers. Cut it wide enough to see "
            "both of them and who moved."
        ),
        ask=Ask(
            prompt="A serve is coming down the seam between you and a teammate. Whose is it?",
            options=(
                "Whoever the ball is moving toward takes it",
                "The stronger passer of the two",
                "Whoever is closest when it lands",
            ),
            answer=0,
            because=(
                "Passing across your body sends the ball sideways. The player "
                "the ball is coming to can play it in front of them."
            ),
        ),
    ),
    Topic(
        key="vb_iq_block_shape",
        title="Taking a line and trusting the defence",
        focus="Blocking",
        positions=VB_FRONT, min_age=13, max_age=200, target_s=130,
        find=(
            "A block where the outside blocker holds the line and a digger "
            "covers the angle. Look for one where the blocker chases the ball "
            "instead and leaves both open."
        ),
        ask=Ask(
            prompt="You are blocking the outside hitter. What is your job?",
            options=(
                "Take away one shot and let the defence have the other",
                "Move to wherever the hitter is swinging",
                "Get your hands on every ball you can reach",
            ),
            answer=0,
            because=(
                "A block that chases covers nothing. Taking one shot away is "
                "what lets six players cover the court instead of one."
            ),
        ),
    ),
    Topic(
        key="vb_iq_transition",
        title="Getting off the net after you block",
        focus="Transition",
        positions=VB_FRONT, min_age=13, max_age=200, target_s=120,
        find=(
            "A blocker landing and pulling straight off for their approach, "
            "next to one who stays flat at the net and gets set anyway."
        ),
        ask=Ask(
            prompt="You land from a block and your team digs it. What now?",
            options=(
                "Pull straight off the net so you can approach",
                "Stay at the net in case it comes back over",
                "Turn and watch where the dig goes first",
            ),
            answer=0,
            because=(
                "A hitter who is still under the net has no approach, and a "
                "set arriving to a standing player is a free ball for them."
            ),
        ),
    ),
    Topic(
        key="vb_iq_cover_your_hitter",
        title="Covering your own hitter",
        focus="Team offence",
        positions=VB_ALL, min_age=13, max_age=200, target_s=115,
        find=(
            "A hit that comes off the block and drops. Cut it wide, the clip "
            "is the three players around the hitter, not the swing."
        ),
        ask=Ask(
            prompt="Your teammate is about to hit. Where do you go?",
            options=(
                "Low and close, ready for the ball to rebound off the block",
                "Back, in case the other team counter-attacks",
                "Stay where you are so you do not get in the way",
            ),
            answer=0,
            because=(
                "Most blocked balls drop within a couple of metres of the "
                "hitter. Nobody is standing there unless they went there on "
                "purpose."
            ),
        ),
    ),
    Topic(
        key="vb_iq_serve_target",
        title="Serving at somebody, not just over",
        focus="Serving",
        positions=VB_ALL, min_age=13, max_age=200, target_s=110,
        find=(
            "A server aiming at a seam or a weak passer, next to one hitting "
            "the middle of the court. The receiving team's shape is the clip."
        ),
        ask=Ask(
            prompt="What makes a serve difficult, other than speed?",
            options=(
                "Where it lands, a seam, a weak passer, or deep in a corner",
                "How hard it is hit",
                "How much spin is on it",
            ),
            answer=0,
            because=(
                "A hard serve straight at a good passer is an easy pass. A "
                "slow one at a seam is not."
            ),
        ),
    ),
)

VB_ADVANCED: tuple[Topic, ...] = (
    Topic(
        key="vb_iq_tempo",
        title="Set tempo and what it does to a block",
        focus="Team offence",
        positions=VB_ALL, min_age=15, max_age=200, target_s=160,
        find=(
            "A quick middle attack and a high outside set from the same match. "
            "The clip is the blockers' feet, not the hitters."
        ),
        ask=Ask(
            prompt="Why run a quick set to the middle?",
            options=(
                "It commits the middle blocker and leaves the outside one-on-one",
                "It is harder for the defence to dig",
                "It is the fastest way to score",
            ),
            answer=0,
            because=(
                "The quick is usually not the attack. It is what stops the "
                "middle blocker helping outside, which is where the point "
                "actually comes from."
            ),
        ),
    ),
    Topic(
        key="vb_iq_out_of_system",
        title="Out of system, and what changes",
        focus="Decision-making",
        positions=VB_ALL, min_age=15, max_age=200, target_s=155,
        find=(
            "A bad pass and what the team does next. Look for a high ball to "
            "the outside rather than an attempt to run the offence anyway."
        ),
        ask=Ask(
            prompt="The pass is bad and your setter cannot get to it. What should happen?",
            options=(
                "A high ball to the outside, and everybody covers",
                "Run the same play a bit slower",
                "Send it straight over on two",
            ),
            answer=0,
            because=(
                "Out of system, the goal is a swing somebody can cover, not a "
                "point. Forcing the offence from a bad pass is how a rally "
                "becomes a free ball for them."
            ),
        ),
    ),
    Topic(
        key="vb_iq_hitter_tools",
        title="Tooling the block and hitting the seam",
        focus="Attacking",
        positions=VB_FRONT, min_age=15, max_age=200, target_s=155,
        find=(
            "A hitter using the blocker's outside hand deliberately. Slow "
            "footage helps, the intent is only visible if you can see the "
            "arm change late."
        ),
        ask=Ask(
            prompt="There is a big block in front of you. What is the highest-percentage swing?",
            options=(
                "Off the blocker's outside hand, or into the seam between them",
                "Hard and straight down the line",
                "Tip it over into the middle",
            ),
            answer=0,
            because=(
                "A block is a wall with edges. Hitting through the middle of "
                "it is the one place it is strongest."
            ),
        ),
    ),
    Topic(
        key="vb_iq_base_positions",
        title="Base, then read, then go",
        focus="Team defence",
        positions=VB_ALL, min_age=15, max_age=200, target_s=150,
        find=(
            "A full defensive rotation from base position to the read. Cut it "
            "wide enough to see all six players move together."
        ),
        ask=Ask(
            prompt="When do you leave your base defensive position?",
            options=(
                "Once you have read where the set is going",
                "As soon as the ball crosses the net",
                "When the hitter starts their approach",
            ),
            answer=0,
            because=(
                "Leaving early on a guess opens the court you just left. Base "
                "first, read second, move third, in that order every time."
            ),
        ),
    ),
    Topic(
        key="vb_iq_free_ball",
        title="The free ball nobody converts",
        focus="Transition",
        positions=VB_ALL, min_age=15, max_age=200, target_s=150,
        find=(
            "A free ball coming over and what the receiving team does with it. "
            "Find one converted into a proper attack and one played back over "
            "casually."
        ),
        ask=Ask(
            prompt="A free ball is floating over. What is the biggest mistake?",
            options=(
                "Treating it casually instead of running your best play",
                "Passing it too tight to the net",
                "Not calling for it early enough",
            ),
            answer=0,
            because=(
                "A free ball is the easiest chance you get to run exactly what "
                "you practise. Teams lose more points relaxing on these than "
                "on hard-served ones."
            ),
        ),
    ),
)

VB_TOPICS: tuple[Topic, ...] = VB_FUNDAMENTALS + VB_CORE + VB_ADVANCED




# ---------------------------------------------------------------------------
# Soccer
#
# Same rules again. What differs is that soccer IQ is mostly about *what happens
# before you get the ball* -- the scan over the shoulder, the body shape you
# receive in, the run that drags a defender somewhere useful. Almost none of the
# thinking in this sport happens while you have possession.
# ---------------------------------------------------------------------------

SOC_ALL = ("goalkeeper", "defender", "midfielder", "forward")
SOC_OUT = ("defender", "midfielder", "forward")
SOC_ATT = ("midfielder", "forward")

SOC_FUNDAMENTALS: tuple[Topic, ...] = (
    Topic(
        key="soc_iq_look_before",
        title="Look over your shoulder before it arrives",
        focus="Scanning",
        positions=SOC_OUT, min_age=0, max_age=200, target_s=70,
        find=(
            "A midfielder checking their shoulder twice before receiving, next "
            "to one who does not. The clip is the head turn, so cut from before "
            "the pass is played."
        ),
        ask=Ask(
            prompt="When should you look around for space?",
            options=(
                "Before the ball reaches you, while it is still travelling",
                "As you take your first touch",
                "Once you have the ball under control",
            ),
            answer=0,
            because=(
                "Looking after you receive means deciding while a defender is "
                "already on you. The players who always seem to have time are "
                "the ones who looked before it arrived."
            ),
        ),
    ),
    Topic(
        key="soc_iq_open_body",
        title="Receive side-on, not facing your own goal",
        focus="First touch",
        positions=SOC_OUT, min_age=0, max_age=200, target_s=65,
        find=(
            "Two receptions from the same match: one player half-turned and "
            "able to see the whole pitch, one square and facing backwards."
        ),
        ask=Ask(
            prompt="A pass is coming to you from behind. How do you stand?",
            options=(
                "Side-on, so you can see forwards and backwards",
                "Square to the passer, so the touch is easier",
                "Facing your own goal, so nobody can tackle you",
            ),
            answer=0,
            because=(
                "Square means your only option is backwards. Half-turned, the "
                "same pass gives you the whole pitch."
            ),
        ),
    ),
    Topic(
        key="soc_iq_spread_out",
        title="Stop running to the ball",
        focus="Spacing",
        positions=SOC_ALL, min_age=0, max_age=200, target_s=70,
        find=(
            "Any youth game. Cut a passage where six players converge on the "
            "ball, and one where a team keeps its shape. The first is easy to "
            "find."
        ),
        ask=Ask(
            prompt="Your teammate has the ball. Where should you be?",
            options=(
                "Spread out, in space they can pass into",
                "Close to them, so the pass is short and safe",
                "Between them and the goal, ready for a rebound",
            ),
            answer=0,
            because=(
                "Everybody around the ball means one defender covers three "
                "players and there is nowhere to pass. Spreading out is what "
                "makes a pass exist."
            ),
        ),
    ),
)

SOC_CORE: tuple[Topic, ...] = (
    Topic(
        key="soc_iq_first_touch_away",
        title="First touch away from pressure",
        focus="First touch",
        positions=SOC_OUT, min_age=13, max_age=200, target_s=120,
        find=(
            "A receiving player taking their first touch into space rather "
            "than under their own feet, with a defender arriving. Cut it wide "
            "enough to see where the defender is coming from."
        ),
        ask=Ask(
            prompt="A defender is closing you down as the ball arrives. Where does your first touch go?",
            options=(
                "Into the space away from them",
                "Straight down under your feet so you can control it",
                "Back the way it came, first time",
            ),
            answer=0,
            because=(
                "A touch under your feet leaves you exactly where the defender "
                "expected. The first touch is where you decide the next two "
                "seconds."
            ),
        ),
    ),
    Topic(
        key="soc_iq_pressing_trigger",
        title="When to press and when to hold",
        focus="Defending",
        positions=SOC_OUT, min_age=13, max_age=200, target_s=125,
        find=(
            "A team pressing on a bad touch, and another chasing a settled "
            "centre back. The trigger is the clip, what happened just before "
            "they went."
        ),
        ask=Ask(
            prompt="When is the right moment to press?",
            options=(
                "On a bad touch, a backwards pass, or a player facing their own goal",
                "As soon as the other team gets the ball",
                "Whenever you are closest to the ball",
            ),
            answer=0,
            because=(
                "Pressing a player who is comfortable just moves your team out "
                "of shape. Pressing a bad touch is when they cannot punish it."
            ),
        ),
    ),
    Topic(
        key="soc_iq_jockey",
        title="Jockeying instead of diving in",
        focus="Defending",
        positions=SOC_OUT, min_age=13, max_age=200, target_s=115,
        find=(
            "A one-on-one where the defender stays side-on and shows the "
            "attacker outside, next to one who lunges and is beaten. Both "
            "happen every game."
        ),
        ask=Ask(
            prompt="You are last defender, one-on-one. What do you do?",
            options=(
                "Stay side-on, slow them down, and show them away from goal",
                "Tackle as soon as you can reach the ball",
                "Back off and wait for help to arrive",
            ),
            answer=0,
            because=(
                "A tackle you miss takes you out of the game entirely. Delaying "
                "gives your teammates time to get back."
            ),
        ),
    ),
    Topic(
        key="soc_iq_third_man",
        title="The third-man run",
        focus="Team offence",
        positions=SOC_ATT, min_age=13, max_age=200, target_s=125,
        find=(
            "A pass in to a player who lays it off, and a third player running "
            "onto it. Cut it wide, the runner is the clip and they start off "
            "screen."
        ),
        ask=Ask(
            prompt="Why is the third player often the one who gets free?",
            options=(
                "The defenders are watching the first two, so nobody tracks them",
                "They have more time to build up speed",
                "They are usually the fastest player",
            ),
            answer=0,
            because=(
                "Defenders follow the ball. The player two passes away is the "
                "one nobody is looking at."
            ),
        ),
    ),
    Topic(
        key="soc_iq_switch",
        title="Switching the play",
        focus="Team offence",
        positions=SOC_OUT, min_age=13, max_age=200, target_s=120,
        find=(
            "A side crowded on one flank and a long ball to the other. The "
            "clip is the far winger standing alone before the switch."
        ),
        ask=Ask(
            prompt="Your team is stuck on one side of the pitch. What is the answer?",
            options=(
                "Switch it to the other side, where the defence is not",
                "Keep passing until a gap appears on this side",
                "Play it long towards the striker",
            ),
            answer=0,
            because=(
                "A defence that has shifted across cannot shift back as fast as "
                "the ball travels. The space is always on the far side."
            ),
        ),
    ),
    Topic(
        key="soc_iq_run_the_channel",
        title="Running the channel, not the centre back",
        focus="Attacking",
        positions=SOC_ATT, min_age=13, max_age=200, target_s=110,
        find=(
            "A striker running into the gap between a full back and a centre "
            "back, next to one running straight at a defender's chest."
        ),
        ask=Ask(
            prompt="Where should a striker run in behind?",
            options=(
                "Into the gap between two defenders, so neither one owns them",
                "Straight at the centre back to hold them off",
                "Wide, away from everyone",
            ),
            answer=0,
            because=(
                "A run at one defender is a run they can handle alone. Between "
                "two, each waits for the other and the gap opens."
            ),
        ),
    ),
)

SOC_ADVANCED: tuple[Topic, ...] = (
    Topic(
        key="soc_iq_cover_balance",
        title="Press, cover and balance",
        focus="Team defence",
        positions=SOC_OUT, min_age=15, max_age=200, target_s=160,
        find=(
            "A back four with one pressing, one covering behind and the far "
            "side tucked in. Cut it wide enough to see all four at once."
        ),
        ask=Ask(
            prompt="Your teammate presses the ball. What is your job?",
            options=(
                "Cover behind them, so a beaten press is not a chance",
                "Press the nearest opponent as well",
                "Drop back to the goal line",
            ),
            answer=0,
            because=(
                "One presser and nobody covering is a defence that loses "
                "everything the moment the press is beaten. The cover is what "
                "makes pressing safe to do."
            ),
        ),
    ),
    Topic(
        key="soc_iq_offside_line",
        title="Holding a line together",
        focus="Team defence",
        positions=SOC_OUT, min_age=15, max_age=200, target_s=155,
        find=(
            "A back line stepping up as one, and one where a single defender "
            "stays deep and plays everybody on. Both are clear in wide footage."
        ),
        ask=Ask(
            prompt="Your back line steps up. What happens if one player does not?",
            options=(
                "They play the whole attack onside on their own",
                "The attacker has more space to run into",
                "The goalkeeper has to come further out",
            ),
            answer=0,
            because=(
                "Offside is measured from the last defender. One player deep "
                "makes the other three irrelevant."
            ),
        ),
    ),
    Topic(
        key="soc_iq_build_from_back",
        title="Building out under a press",
        focus="Team offence",
        positions=SOC_ALL, min_age=15, max_age=200, target_s=165,
        find=(
            "A goalkeeper and back line playing through a press rather than "
            "over it. The clip is where the free player is, which is usually "
            "not who gets the ball first."
        ),
        ask=Ask(
            prompt="The other team presses your goalkeeper. Where is the free player?",
            options=(
                "Wherever they left somebody unmarked to press with, usually the far side",
                "Up front, because everybody has come forward",
                "There is not one, so it should go long",
            ),
            answer=0,
            because=(
                "A press has to leave somebody. Finding them is the whole point "
                "of playing out rather than kicking it away."
            ),
        ),
    ),
    Topic(
        key="soc_iq_counter_shape",
        title="The first three seconds after losing it",
        focus="Transition",
        positions=SOC_OUT, min_age=15, max_age=200, target_s=155,
        find=(
            "A turnover and what the team does immediately. Find one that "
            "presses instantly and one that jogs back into shape."
        ),
        ask=Ask(
            prompt="You lose the ball in their half. What is the first thing to do?",
            options=(
                "Press immediately, before they can turn and pick a pass",
                "Sprint back to your own half and get organised",
                "Stay where you are and wait for the ball to come back",
            ),
            answer=0,
            because=(
                "A player who has just won it is facing the wrong way and not "
                "yet settled. Those few seconds are the easiest time to win it "
                "back all game."
            ),
        ),
    ),
    Topic(
        key="soc_iq_when_not_to_dribble",
        title="When the pass is better than the dribble",
        focus="Decision-making",
        positions=SOC_ATT, min_age=15, max_age=200, target_s=150,
        find=(
            "A player taking on two defenders with a teammate free, and one "
            "who plays the simple pass into a better position."
        ),
        ask=Ask(
            prompt="You are one-on-two with a teammate free beside you. What now?",
            options=(
                "Pass, two defenders on you means one is off them",
                "Take them on, because you are past one already",
                "Shield the ball and wait for support",
            ),
            answer=0,
            because=(
                "Two defenders on the ball is the definition of somebody else "
                "being free. Dribbling into that is the one way to waste it."
            ),
        ),
    ),
)

SOC_TOPICS: tuple[Topic, ...] = SOC_FUNDAMENTALS + SOC_CORE + SOC_ADVANCED




# ---------------------------------------------------------------------------
# Tennis
#
# The only sport in this file with no teammates, and the syllabus reflects it.
# There is nothing here about where to stand relative to five other people --
# tennis IQ is about *patterns*: what you are trying to make happen over the
# next three balls, and what your own body language is telling the other end.
# ---------------------------------------------------------------------------

TEN_ALL = ("singles", "doubles")
TEN_SINGLES = ("singles",)
TEN_DOUBLES = ("doubles",)

TEN_FUNDAMENTALS: tuple[Topic, ...] = (
    Topic(
        key="ten_iq_recover",
        title="Get back to the middle before the next ball",
        focus="Movement",
        positions=TEN_ALL, min_age=0, max_age=200, target_s=70,
        find=(
            "A rally where one player recovers to the middle after every shot "
            "and the other admires theirs. Cut it wide enough to see the whole "
            "court and both players' feet."
        ),
        ask=Ask(
            prompt="You hit a good shot to the corner. What do you do next?",
            options=(
                "Move back towards the middle straight away",
                "Watch to see whether it lands in",
                "Stay where you are in case they hit it back there",
            ),
            answer=0,
            because=(
                "Standing still after a good shot is how a good shot becomes a "
                "lost point. The court you have just left is the one they will "
                "aim at."
            ),
        ),
    ),
    Topic(
        key="ten_iq_high_net",
        title="Aim higher over the net than feels right",
        focus="Margin",
        positions=TEN_ALL, min_age=0, max_age=200, target_s=65,
        find=(
            "Two rallies from the same match: one with balls crossing well "
            "above the net, one skimming it. Count the errors in each."
        ),
        ask=Ask(
            prompt="Why aim a metre above the net rather than just over it?",
            options=(
                "Almost every miss goes into the net, not long",
                "It gives the ball more topspin",
                "It makes the ball land deeper",
            ),
            answer=0,
            because=(
                "The net is the only thing on court that never moves and never "
                "misses. Most points are lost to it rather than to the back "
                "line."
            ),
        ),
    ),
    Topic(
        key="ten_iq_ready_early",
        title="Racket back before the ball bounces",
        focus="Preparation",
        positions=TEN_ALL, min_age=0, max_age=200, target_s=70,
        find=(
            "A player turning and preparing as the ball crosses the net, next "
            "to one starting their swing after the bounce. Slow footage helps."
        ),
        ask=Ask(
            prompt="When should your racket be back?",
            options=(
                "Before the ball bounces on your side",
                "As you start to swing",
                "Once you know where the ball is going",
            ),
            answer=0,
            because=(
                "After the bounce there is about half a second left. Everything "
                "that has to happen before the swing has to have happened "
                "already."
            ),
        ),
    ),
)

TEN_CORE: tuple[Topic, ...] = (
    Topic(
        key="ten_iq_cross_court",
        title="Why the cross-court ball is the safe one",
        focus="Patterns",
        positions=TEN_ALL, min_age=13, max_age=200, target_s=120,
        find=(
            "A baseline exchange where both players hit cross-court until one "
            "changes direction. The clip is what happens on the ball that goes "
            "down the line."
        ),
        ask=Ask(
            prompt="Why do rallies stay cross-court so often?",
            options=(
                "The net is lower there and the court is longer diagonally",
                "It is easier to hit a forehand cross-court",
                "It keeps the ball away from the opponent's forehand",
            ),
            answer=0,
            because=(
                "More margin over a lower net and more court to land in. "
                "Changing direction is the riskier shot, which is why it should "
                "be a choice rather than a habit."
            ),
        ),
    ),
    Topic(
        key="ten_iq_change_direction",
        title="Changing direction on the right ball",
        focus="Patterns",
        positions=TEN_ALL, min_age=13, max_age=200, target_s=125,
        find=(
            "A player going down the line off a short, high ball, and another "
            "trying it off a deep one at their shoelaces."
        ),
        ask=Ask(
            prompt="When is it right to change direction and go down the line?",
            options=(
                "On a short ball you can step into",
                "When the rally has gone on too long",
                "Whenever the opponent is out of position",
            ),
            answer=0,
            because=(
                "Direction changes need time and a comfortable contact point. "
                "Trying one off a deep ball on the stretch is the highest-risk "
                "shot in the sport."
            ),
        ),
    ),
    Topic(
        key="ten_iq_serve_placement",
        title="Serving to a place, not just in",
        focus="Serving",
        positions=TEN_ALL, min_age=13, max_age=200, target_s=115,
        find=(
            "A server going wide to open the court, and the same player hitting "
            "the middle of the box. What the returner does next is the clip."
        ),
        ask=Ask(
            prompt="What does a wide serve do beyond winning the point outright?",
            options=(
                "It drags the returner off court and opens the other side",
                "It is harder to return than a fast serve",
                "It stops them attacking your second serve",
            ),
            answer=0,
            because=(
                "Most serves come back. The question is what the court looks "
                "like when they do, and a wide serve answers it before the "
                "rally starts."
            ),
        ),
    ),
    Topic(
        key="ten_iq_second_serve_return",
        title="Standing in on a second serve",
        focus="Returning",
        positions=TEN_ALL, min_age=13, max_age=200, target_s=110,
        find=(
            "A returner stepping inside the baseline on a second serve, next to "
            "one standing three metres back for both."
        ),
        ask=Ask(
            prompt="Where do you stand for a second serve?",
            options=(
                "Closer in, to take time away and attack it",
                "The same place as the first serve, for consistency",
                "Further back, because second serves have more spin",
            ),
            answer=0,
            because=(
                "A second serve is the one ball in the sport the server has to "
                "make safe. Standing back turns their problem into a free "
                "start."
            ),
        ),
    ),
    Topic(
        key="ten_iq_net_position",
        title="Closing after you approach",
        focus="Net play",
        positions=TEN_DOUBLES, min_age=13, max_age=200, target_s=120,
        find=(
            "An approach followed by two more steps forward, next to one where "
            "the player stops on the service line and gets passed."
        ),
        ask=Ask(
            prompt="You hit an approach shot. Where do you stop?",
            options=(
                "Keep moving forward, the service line is the worst place to stand",
                "On the service line, where you can cover both a lob and a pass",
                "Halfway, so you can react to whatever comes",
            ),
            answer=0,
            because=(
                "The service line is where every ball lands at your feet. "
                "Committing forward is what makes the volley easy."
            ),
        ),
    ),
    Topic(
        key="ten_iq_body_language",
        title="What the other end can see",
        focus="Competing",
        positions=TEN_ALL, min_age=13, max_age=200, target_s=110,
        find=(
            "A player between points after an error, one walking to the towel "
            "with their head up, one dropping their shoulders. Both are easy to "
            "find in any junior match."
        ),
        ask=Ask(
            prompt="Why does what you do between points matter?",
            options=(
                "Your opponent is watching, and it tells them how you are feeling",
                "The umpire can penalise you for it",
                "It affects how the crowd reacts",
            ),
            answer=0,
            because=(
                "There is nobody else on your side of the net. The only "
                "information your opponent gets about how you are doing is what "
                "you show them."
            ),
        ),
    ),
)

TEN_ADVANCED: tuple[Topic, ...] = (
    Topic(
        key="ten_iq_serve_plus_one",
        title="Serve plus one",
        focus="Patterns",
        positions=TEN_ALL, min_age=15, max_age=200, target_s=155,
        find=(
            "A serve wide followed by the first ball into the open court. Cut "
            "from the toss so the whole pattern is visible as one idea."
        ),
        ask=Ask(
            prompt="What is the most important shot after the serve?",
            options=(
                "The first ball, hit to the space the serve opened",
                "The second serve, because it decides the pressure",
                "Whichever one ends the point",
            ),
            answer=0,
            because=(
                "The serve is chosen for what it opens up. A player who serves "
                "well and then rallies neutrally has thrown away the advantage "
                "they just built."
            ),
        ),
    ),
    Topic(
        key="ten_iq_neutral_ball",
        title="Knowing when you are neutral",
        focus="Decision-making",
        positions=TEN_ALL, min_age=15, max_age=200, target_s=160,
        find=(
            "A rally where one player attacks a neutral ball and misses, next "
            "to one who resets and wins the point three shots later."
        ),
        ask=Ask(
            prompt="You are behind the baseline and the ball is deep. What is the right shot?",
            options=(
                "A high, deep, safe ball to get back to neutral",
                "A winner, because you have to end the point sometime",
                "A drop shot to change the pattern",
            ),
            answer=0,
            because=(
                "Attacking from a defensive position is the most common way "
                "juniors lose points. Getting back to neutral is a skill, not "
                "an absence of one."
            ),
        ),
    ),
    Topic(
        key="ten_iq_return_position",
        title="Reading a serve before it is struck",
        focus="Returning",
        positions=TEN_ALL, min_age=15, max_age=200, target_s=150,
        find=(
            "A server whose toss changes between wide and body serves. Slow "
            "footage of two or three service motions from the same player."
        ),
        ask=Ask(
            prompt="What can tell you where a serve is going before contact?",
            options=(
                "The toss position and the server's shoulder line",
                "How fast they bounce the ball beforehand",
                "Which side of the court they stand on",
            ),
            answer=0,
            because=(
                "A toss further to the side has to produce a wider serve. Most "
                "juniors have a different toss for each serve and do not know "
                "it."
            ),
        ),
    ),
    Topic(
        key="ten_iq_doubles_movement",
        title="Moving as a pair, not a pair of players",
        focus="Doubles",
        positions=TEN_DOUBLES, min_age=15, max_age=200, target_s=155,
        find=(
            "A doubles pair shifting across together, next to one where a gap "
            "opens up the middle. Wide footage only, the shape is the clip."
        ),
        ask=Ask(
            prompt="Your partner is pulled wide. Where do you go?",
            options=(
                "Across with them, so the gap between you does not open",
                "Stay covering your own half of the court",
                "Back, to cover the lob over their head",
            ),
            answer=0,
            because=(
                "Two players who defend their own halves leave a gap down the "
                "middle that grows every shot. Doubles is played on a piece of "
                "elastic."
            ),
        ),
    ),
    Topic(
        key="ten_iq_score_pressure",
        title="The points that are not worth the same",
        focus="Competing",
        positions=TEN_ALL, min_age=15, max_age=200, target_s=150,
        find=(
            "A game reaching 30-30 or deuce. The clip is what both players "
            "choose to do on the big point rather than how it ends."
        ),
        ask=Ask(
            prompt="It is 30-30. How should you play the point?",
            options=(
                "Your best pattern, played with margin, not something new",
                "More aggressively, to take the initiative",
                "More safely, and wait for a mistake",
            ),
            answer=0,
            because=(
                "Big points are the worst moment to try something you have not "
                "practised. Doing your ordinary thing well is what holds up "
                "under pressure."
            ),
        ),
    ),
)

TEN_TOPICS: tuple[Topic, ...] = TEN_FUNDAMENTALS + TEN_CORE + TEN_ADVANCED




# ---------------------------------------------------------------------------
# Baseball and softball
#
# One syllabus, registered under both sports. Almost every decision in these two
# games is identical -- where to be before the pitch, what to do on a ball not
# hit to you, when the runner goes -- and the two that are not (the windmill,
# and the shorter basepaths) are drill and rule differences rather than
# thinking differences.
#
# What is distinctive here is that this sport's IQ is mostly about *the pitch
# before the pitch*: knowing the count, the outs and where you are going with
# the ball before it is hit anywhere near you.
# ---------------------------------------------------------------------------

DIAMOND = ("pitcher", "catcher", "infield", "outfield")
DEFENCE = ("catcher", "infield", "outfield")

BB_FUNDAMENTALS: tuple[Topic, ...] = (
    Topic(
        key="bb_iq_know_before",
        title="Know what you are doing before it is hit",
        focus="Situations",
        positions=DIAMOND, min_age=0, max_age=200, target_s=70,
        find=(
            "A fielder who clearly already knows where the throw is going, "
            "next to one who catches it and then looks up. Youth footage makes "
            "the second one very easy to find."
        ),
        ask=Ask(
            prompt="Before every pitch, what should you already have decided?",
            options=(
                "Where you are throwing if the ball comes to you",
                "Which way you will dive",
                "Whether the batter is any good",
            ),
            answer=0,
            because=(
                "There is about a second between fielding a ball and needing to "
                "throw it. Anyone deciding in that second is already late."
            ),
        ),
    ),
    Topic(
        key="bb_iq_back_up",
        title="Backing up the throw",
        focus="Situations",
        positions=DEFENCE, min_age=0, max_age=200, target_s=65,
        find=(
            "An overthrow at a base with somebody behind it, and one with "
            "nobody. What the runners do next is the whole clip."
        ),
        ask=Ask(
            prompt="The ball is thrown to first and you are nowhere near it. Where do you go?",
            options=(
                "Behind the base, in case the throw gets away",
                "Stay at your position in case the ball comes back",
                "Towards the ball, to help",
            ),
            answer=0,
            because=(
                "Every overthrow that nobody backed up is an extra base. It is "
                "the least glamorous run in the sport and the one that saves "
                "the most."
            ),
        ),
    ),
    Topic(
        key="bb_iq_two_hands",
        title="Getting in front of it",
        focus="Fielding",
        positions=DEFENCE, min_age=0, max_age=200, target_s=70,
        find=(
            "A grounder fielded with the body squared behind the glove, and one "
            "reached at sideways. Look for what happens on the bad hop in each."
        ),
        ask=Ask(
            prompt="A ground ball is coming straight at you. What do you do with your body?",
            options=(
                "Get it in front of the ball, so a bad hop still hits you",
                "Reach out with the glove so you can get to it sooner",
                "Stay tall so you can see the hop better",
            ),
            answer=0,
            because=(
                "The glove misses bad hops. A chest does not, and a ball that "
                "hits your chest is still in front of you."
            ),
        ),
    ),
)

BB_CORE: tuple[Topic, ...] = (
    Topic(
        key="bb_iq_count_leverage",
        title="What the count is telling you",
        focus="Hitting",
        positions=DIAMOND, min_age=13, max_age=200, target_s=125,
        find=(
            "The same batter at 2-0 and at 0-2. The clip is the pitch selection "
            "and the swing decision, not the result."
        ),
        ask=Ask(
            prompt="You are ahead in the count 2-0. What changes?",
            options=(
                "You can wait for a pitch in your zone rather than protect",
                "You should swing at the next pitch before it gets to 2-1",
                "Nothing, hit the ball hard whatever the count",
            ),
            answer=0,
            because=(
                "Ahead in the count, the pitcher has to come to you. Being "
                "choosy is the entire advantage, and swinging at a bad one "
                "gives it straight back."
            ),
        ),
    ),
    Topic(
        key="bb_iq_cut_off",
        title="Hitting the cut-off",
        focus="Situations",
        positions=DEFENCE, min_age=13, max_age=200, target_s=120,
        find=(
            "An outfielder throwing through the cut-off man to the plate while "
            "the batter takes second, next to one who hits the relay."
        ),
        ask=Ask(
            prompt="You field a ball in the outfield with a runner rounding third. Where do you throw?",
            options=(
                "To the cut-off man, who can still make a play on the batter",
                "All the way home on the fly",
                "To the base ahead of the lead runner",
            ),
            answer=0,
            because=(
                "A throw over everybody's head is one play at best and usually "
                "none. Hitting the cut-off keeps two outs available instead of "
                "one long throw."
            ),
        ),
    ),
    Topic(
        key="bb_iq_outs_matter",
        title="The number of outs changes everything",
        focus="Situations",
        positions=DIAMOND, min_age=13, max_age=200, target_s=115,
        find=(
            "A fly ball caught with one out and a runner on third, and the same "
            "situation with two. What every player does differs completely."
        ),
        ask=Ask(
            prompt="Runner on third, fly ball to the outfield. Why does the number of outs matter?",
            options=(
                "With fewer than two outs the runner can tag and score",
                "With two outs the outfielder has more time",
                "It changes where the infield stands",
            ),
            answer=0,
            because=(
                "Every player on the field is doing something different "
                "depending on the outs. Not knowing them is the most common "
                "mental error in the sport."
            ),
        ),
    ),
    Topic(
        key="bb_iq_secondary_lead",
        title="The secondary lead",
        focus="Baserunning",
        positions=DIAMOND, min_age=13, max_age=200, target_s=110,
        find=(
            "A runner shuffling off as the pitch is delivered, next to one "
            "standing still until the ball is hit."
        ),
        ask=Ask(
            prompt="You are on first. What should you be doing as the pitch is thrown?",
            options=(
                "Shuffling off into a secondary lead, moving as it crosses",
                "Standing still so you can react either way",
                "Getting back towards the base in case of a pick-off",
            ),
            answer=0,
            because=(
                "Two shuffles is most of a stolen base and all of the "
                "difference on a ball in the gap. Standing still means starting "
                "from zero."
            ),
        ),
    ),
    Topic(
        key="bb_iq_pitch_recognition",
        title="Deciding early and being right",
        focus="Hitting",
        positions=DIAMOND, min_age=13, max_age=200, target_s=125,
        find=(
            "Slow footage of a batter tracking a breaking ball out of the hand. "
            "The decision point, not the swing, is the clip."
        ),
        ask=Ask(
            prompt="When do you have to decide whether to swing?",
            options=(
                "About halfway to the plate, well before you can see it break",
                "As it crosses the front of the plate",
                "As soon as it leaves the hand",
            ),
            answer=0,
            because=(
                "There is not enough time to see the whole flight and then "
                "decide. Good hitters commit early on where it started and "
                "adjust, which is why a pitch that starts in the zone and "
                "leaves it works."
            ),
        ),
    ),
    Topic(
        key="bb_iq_pitcher_fielder",
        title="A pitcher is a fielder too",
        focus="Situations",
        positions=("pitcher",), min_age=13, max_age=200, target_s=110,
        find=(
            "A pitcher covering first on a ground ball to the right side, next "
            "to one still standing on the mound watching it."
        ),
        ask=Ask(
            prompt="A ground ball goes to the first baseman's right. What is the pitcher's job?",
            options=(
                "Break for first immediately to take the throw",
                "Back up second base",
                "Stay on the mound and let them handle it",
            ),
            answer=0,
            because=(
                "The first baseman cannot field it and cover the bag. A pitcher "
                "who does not move turns a routine out into an infield hit."
            ),
        ),
    ),
)

BB_ADVANCED: tuple[Topic, ...] = (
    Topic(
        key="bb_iq_infield_depth",
        title="Where the infield stands, and why",
        focus="Team defence",
        positions=DEFENCE, min_age=15, max_age=200, target_s=155,
        find=(
            "The infield playing in with a runner on third, and back in a "
            "double-play situation. Wide footage of both, from before the pitch."
        ),
        ask=Ask(
            prompt="Runner on third, one out, close game. Why does the infield come in?",
            options=(
                "To cut the run off at the plate, accepting less range",
                "To turn a double play more easily",
                "Because the batter is likely to bunt",
            ),
            answer=0,
            because=(
                "Playing in trades range for a play at the plate. It is a bet "
                "on the run mattering more than the base, and it is only right "
                "some of the time."
            ),
        ),
    ),
    Topic(
        key="bb_iq_sequencing",
        title="Sequencing, not just stuff",
        focus="Pitching",
        positions=("pitcher", "catcher"), min_age=15, max_age=200, target_s=160,
        find=(
            "An at-bat where the pitcher sets up a strikeout with an earlier "
            "pitch. The clip is the whole at-bat, not the last pitch."
        ),
        ask=Ask(
            prompt="What makes a good put-away pitch work?",
            options=(
                "The pitches before it, which set up what the hitter expects",
                "How much it moves",
                "How hard it is thrown",
            ),
            answer=0,
            because=(
                "A hitter swings at what they expect. The pitch that gets them "
                "out is usually decided two pitches earlier."
            ),
        ),
    ),
    Topic(
        key="bb_iq_relay",
        title="The relay nobody practises",
        focus="Team defence",
        positions=DEFENCE, min_age=15, max_age=200, target_s=150,
        find=(
            "A ball in the gap and the full relay, outfielder to middle "
            "infielder to base. Cut wide enough to see all three plus the "
            "trailer."
        ),
        ask=Ask(
            prompt="A ball rolls to the wall. What makes the relay work?",
            options=(
                "The relay man lining up between the ball and the base, calling loudly",
                "The outfielder throwing as hard as possible",
                "Everybody converging on the ball",
            ),
            answer=0,
            because=(
                "The outfielder is throwing to a voice and a position, not to a "
                "person they can see. The relay man has to be in line before "
                "the ball is picked up."
            ),
        ),
    ),
    Topic(
        key="bb_iq_first_third",
        title="First and third, and the decision nobody makes in time",
        focus="Situations",
        positions=DEFENCE, min_age=15, max_age=200, target_s=155,
        find=(
            "A first-and-third situation with a runner going. The clip is what "
            "the catcher and middle infielders do, not the steal."
        ),
        ask=Ask(
            prompt="Runners on first and third, the runner on first takes off. What decides the play?",
            options=(
                "Whether the runner on third is far enough off to be caught",
                "How fast the runner going to second is",
                "Whether there are two outs",
            ),
            answer=0,
            because=(
                "The throw to second is the bait. The whole play turns on what "
                "the runner at third does while the ball is in the air, and "
                "somebody has to be watching them."
            ),
        ),
    ),
    Topic(
        key="bb_iq_arm_care",
        title="Knowing when your arm has had enough",
        focus="Staying healthy",
        positions=DIAMOND, min_age=15, max_age=200, target_s=150,
        find=(
            "A pitcher whose mechanics change late in an outing, arm slot "
            "dropping, front side flying open. Compare the first inning with "
            "the fifth."
        ),
        ask=Ask(
            prompt="What is the first sign that an arm has had enough?",
            options=(
                "Command going, and the mechanics changing to compensate",
                "The arm starting to ache",
                "Velocity dropping off",
            ),
            answer=0,
            because=(
                "Pain is a late signal. Losing the strike zone and reaching for "
                "the ball come first, and they are the ones to stop on, for "
                "yourself as much as for whoever is counting."
            ),
        ),
    ),
)

BB_IQ_TOPICS: tuple[Topic, ...] = BB_FUNDAMENTALS + BB_CORE + BB_ADVANCED


# ---------------------------------------------------------------------------
# Hockey
#
# Same rules as every syllabus above: no video ids, every target length inside
# the ceiling for its own minimum age, and a comprehension question with the
# reason its answer is right.
#
# What is distinctive here is that hockey IQ is mostly about **support and
# gaps** -- where to be relative to the puck and to the man you are
# responsible for -- and that it is the only sport in this catalogue where two
# of the topics are about not getting hurt and not hurting anybody else. That
# is not editorialising. Head contact is this sport's defining risk in the way
# throwing volume is the diamond's, and a syllabus that taught positioning and
# said nothing about the boards would be teaching the easy half.
# ---------------------------------------------------------------------------

HOC_ALL = ("centre", "winger", "defence", "goaltender")
HOC_SKATERS = ("centre", "winger", "defence")
HOC_FORWARDS = ("centre", "winger")
HOC_D = ("defence",)
HOC_G = ("goaltender",)

HOC_FUNDAMENTALS: tuple[Topic, ...] = (
    Topic(
        key="hoc_iq_head_up",
        title="Skate with your head up",
        focus="Puck handling",
        positions=HOC_SKATERS, min_age=0, max_age=200, target_s=70,
        find=(
            "A player carrying the puck who is clearly looking at the ice, "
            "next to one staring at their own stick. What happens to each of "
            "them at the blue line is the whole clip."
        ),
        ask=Ask(
            prompt="Why practise stickhandling without looking at the puck?",
            options=(
                "So you can see what is happening while you carry it",
                "Because it looks better",
                "So you can skate faster",
            ),
            answer=0,
            because=(
                "A player looking down cannot see a pass, a hit or a gap. "
                "Everything useful on the ice is somewhere other than the puck."
            ),
        ),
    ),
    Topic(
        key="hoc_iq_support",
        title="Give the puck somewhere to go",
        focus="Support",
        positions=HOC_SKATERS, min_age=0, max_age=200, target_s=72,
        find=(
            "A carrier in the corner with a teammate available above them, and "
            "the same situation with everybody standing still. Cut wide enough "
            "to see all five skaters, not the puck."
        ),
        ask=Ask(
            prompt="Your teammate has the puck in the corner. Where should you be?",
            options=(
                "Somewhere they can actually pass it to you",
                "As close to them as possible",
                "In front of the net waiting",
            ),
            answer=0,
            because=(
                "A player with the puck and nobody to pass to is a player "
                "about to lose it. Being open is a job, and it is yours."
            ),
        ),
    ),
    Topic(
        key="hoc_iq_short_shifts",
        title="Get off on time",
        focus="Shifts",
        positions=HOC_SKATERS, min_age=0, max_age=200, target_s=68,
        find=(
            "A long shift where the same player is visibly slower at the end "
            "than at the start. Youth footage makes this extremely easy to "
            "find, which is the point."
        ),
        ask=Ask(
            prompt="You have been on for a minute and the puck is deep. What now?",
            options=(
                "Change, a tired player is worse than a fresh one",
                "Stay on, because you are near the puck",
                "Stay on until you touch it once more",
            ),
            answer=0,
            because=(
                "Nothing good happens on the second half of a long shift. The "
                "goals against in youth hockey are mostly scored on tired legs."
            ),
        ),
    ),
)

HOC_CORE: tuple[Topic, ...] = (
    Topic(
        key="hoc_iq_boards_safety",
        title="Numbers on the boards",
        focus="Staying safe",
        positions=HOC_SKATERS, min_age=11, max_age=200, target_s=95,
        find=(
            "A player pulling out of a hit because the other one turned, next "
            "to a check into the boards from behind. Use footage where the "
            "second one was called, the whistle is part of the lesson."
        ),
        ask=Ask(
            prompt="You are about to finish a check and the player turns their back. What do you do?",
            options=(
                "Pull up. There is no hit there any more",
                "Finish it, they turned late",
                "Hit them lower instead",
            ),
            answer=0,
            because=(
                "A player facing the boards cannot protect themselves at all. "
                "Every serious injury in this sport starts with somebody "
                "deciding the hit was still on."
            ),
        ),
    ),
    Topic(
        key="hoc_iq_gap",
        title="Closing the gap on a rush",
        focus="Defending",
        positions=HOC_D, min_age=13, max_age=200, target_s=125,
        find=(
            "Two rushes against the same defender: one where they close early "
            "and one where they back in to the hash marks. Cut from the red "
            "line so the gap is visible the whole way."
        ),
        ask=Ask(
            prompt="A forward is coming at you with speed. Where do you want to meet them?",
            options=(
                "Early, before they get to your blue line",
                "At the top of the circles, so you have room",
                "In front of your net, where help is",
            ),
            answer=0,
            because=(
                "Every metre you give them is a metre of speed they get to "
                "keep. Backing in turns one attacker into a two-on-one."
            ),
        ),
    ),
    Topic(
        key="hoc_iq_stick_lane",
        title="Stick in the lane, not at the puck",
        focus="Defending",
        positions=HOC_SKATERS, min_age=13, max_age=200, target_s=120,
        find=(
            "A defender with their stick flat in the passing lane, and one "
            "reaching to poke at the puck. The pass that goes through the "
            "second one is the clip."
        ),
        ask=Ask(
            prompt="You are defending a passer. What should your stick be doing?",
            options=(
                "Lying in the lane they want to pass through",
                "Reaching for the puck to knock it away",
                "Held up so you can react quicker",
            ),
            answer=0,
            because=(
                "Reaching moves your feet out of position and misses most of "
                "the time. A stick in the lane takes the pass away without you "
                "having to do anything."
            ),
        ),
    ),
    Topic(
        key="hoc_iq_net_front",
        title="Get to the net and stay there",
        focus="Attacking",
        positions=HOC_FORWARDS, min_age=13, max_age=200, target_s=118,
        find=(
            "Two shots from the point: one with somebody in front of the "
            "goalie and one with nobody. Watch the goalie's eyes rather than "
            "the puck."
        ),
        ask=Ask(
            prompt="A teammate is winding up from the point. What is your job?",
            options=(
                "Stand where the goalie cannot see through you, and stay",
                "Get out of the way so the shot has a lane",
                "Skate towards the shot to tip it",
            ),
            answer=0,
            because=(
                "A goalie who sees the puck the whole way stops nearly all of "
                "them. Most goals from distance are scored by whoever is "
                "standing in front, not by whoever shot."
            ),
        ),
    ),
    Topic(
        key="hoc_iq_breakout",
        title="The first pass out of your zone",
        focus="Breakouts",
        positions=HOC_SKATERS, min_age=13, max_age=200, target_s=130,
        find=(
            "A clean breakout beside one where the defender rings it round the "
            "boards under no pressure. Cut both from the retrieval, not from "
            "the pass."
        ),
        ask=Ask(
            prompt="You pick the puck up behind your own net with time. What is the priority?",
            options=(
                "Find a teammate, even if it takes an extra second",
                "Get it out any way you can",
                "Skate it out yourself",
            ),
            answer=0,
            because=(
                "A puck rung round the boards is a fifty-fifty you have given "
                "away in your own end. With time, a pass is not the risky "
                "option, it is the safe one."
            ),
        ),
    ),
)

HOC_ADVANCED: tuple[Topic, ...] = (
    Topic(
        key="hoc_iq_delay",
        title="Slowing down to let help arrive",
        focus="Attacking",
        positions=HOC_FORWARDS, min_age=15, max_age=200, target_s=155,
        find=(
            "A carrier entering the zone alone who curls back towards the "
            "boards instead of driving, and the late players arriving behind "
            "them. Compare with the same entry taken straight into two "
            "defenders."
        ),
        ask=Ask(
            prompt="You enter the zone with the puck and nobody with you. What is usually best?",
            options=(
                "Protect it and delay until your teammates arrive",
                "Take it to the net yourself",
                "Put it in deep and go and chase it",
            ),
            answer=0,
            because=(
                "One attacker against two defenders loses. Three seconds of "
                "holding it turns that into three against two, and the delay "
                "costs nothing."
            ),
        ),
    ),
    Topic(
        key="hoc_iq_forecheck",
        title="First one in, second one in",
        focus="Forechecking",
        positions=HOC_FORWARDS, min_age=15, max_age=200, target_s=150,
        find=(
            "A forecheck where the first forward takes the body and the second "
            "arrives for the loose puck, next to one where both go for the "
            "puck and neither gets it."
        ),
        ask=Ask(
            prompt="You are the second forward in on the forecheck. What are you doing?",
            options=(
                "Reading where the puck will pop out and being there",
                "Going for the same puck as the first player",
                "Covering the point in case it comes out",
            ),
            answer=0,
            because=(
                "Two players chasing the same puck is one player wasted. The "
                "first one makes it loose; the second one is why that matters."
            ),
        ),
    ),
    Topic(
        key="hoc_iq_dzone_low",
        title="Cover the player, not the puck",
        focus="Defending",
        positions=HOC_SKATERS, min_age=15, max_age=200, target_s=148,
        find=(
            "A defensive-zone sequence where three players collapse to the "
            "puck in the corner and the pass goes to the man alone in the "
            "slot. Cut it wide, the mistake is off-puck."
        ),
        ask=Ask(
            prompt="The puck is in the corner and your man is alone in the slot. Where do you go?",
            options=(
                "Stay with your man",
                "Help in the corner, it is two on one down there",
                "Between them, so you can do both",
            ),
            answer=0,
            because=(
                "Almost every goal is scored from the slot, not the corner. "
                "Four players around one puck is a goal waiting to happen at "
                "the other end of the pass."
            ),
        ),
    ),
    Topic(
        key="hoc_iq_goalie_depth",
        title="How far out to come",
        focus="Goaltending",
        positions=HOC_G, min_age=15, max_age=200, target_s=160,
        find=(
            "The same goalie on a shot from the top of the circle and on a "
            "pass across the crease. What their depth does between the two is "
            "the clip, freeze frames help more than motion here."
        ),
        ask=Ask(
            prompt="A pass goes from one side of the slot to the other. What should your depth do?",
            options=(
                "Come back towards the post so you can get across in time",
                "Stay out, to keep taking away the angle",
                "Push further out to meet the new shooter",
            ),
            answer=0,
            because=(
                "Out at the top of the crease you cover more of the net and "
                "have further to travel. On a pass across, the travel is the "
                "thing you have run out of."
            ),
        ),
    ),
    Topic(
        key="hoc_iq_head_injury",
        title="What a head injury looks like from the bench",
        focus="Staying safe",
        positions=HOC_ALL, min_age=15, max_age=200, target_s=165,
        find=(
            "A player who takes a hit, gets up slowly and goes straight back "
            "out. Coaching-education footage is better here than game footage, "
            "and it does not need to be a bad one to make the point."
        ),
        ask=Ask(
            prompt="A teammate takes a hit, gets up slowly and says they are fine. What do you do?",
            options=(
                "Tell an adult anyway",
                "Believe them, they know how they feel",
                "Watch them for a shift and see",
            ),
            answer=0,
            because=(
                "Somebody with a head injury is using the injured part to "
                "decide whether they are injured. Being wrong about this once "
                "costs a season, and telling somebody costs nothing."
            ),
        ),
    ),
)

HOC_TOPICS: tuple[Topic, ...] = HOC_FUNDAMENTALS + HOC_CORE + HOC_ADVANCED


# ---------------------------------------------------------------------------
# Gymnastics, cheer and dance
#
# One syllabus registered under three sports, for the same reason baseball and
# softball share one: the decisions are the same decisions. What these three
# have in common is not an apparatus, it is that **they are judged on how the
# movement looks** -- and that produces a specific set of risks the other
# thirteen sports in this catalogue do not have in the same way.
#
# So this syllabus is deliberately not about technique. 0FFDAYS has no opinion
# on a tumbling pass, a stunt or a combination, and putting a number on how a
# child's body looked is the most dangerous thing this product could do. What
# these topics teach is **training sense**: why the conditioning is the part
# that makes the skill possible, what pain is worth telling somebody about,
# and how to keep training when the sport is scored on appearance.
#
# The health topics follow the same rule the wellness module follows: nothing
# names a condition, nothing reads as a diagnosis, and every answer is either
# something to do or something to notice. The thing to do is almost always
# "tell an adult", because at this age that is genuinely the whole skill.
# ---------------------------------------------------------------------------

JUDGED_ALL = (
    "all_around", "bars", "floor_vault", "beam",
    "base", "flyer", "backspot", "tumbler",
    "ballet", "contemporary", "hip_hop", "pom",
)
TUMBLING = ("all_around", "bars", "floor_vault", "beam", "tumbler", "backspot", "base")
STUNTING = ("base", "flyer", "backspot")

JDG_FUNDAMENTALS: tuple[Topic, ...] = (
    Topic(
        key="jdg_iq_strong_first",
        title="The conditioning is not the boring bit",
        focus="Training sense",
        positions=JUDGED_ALL, min_age=0, max_age=200, target_s=70,
        find=(
            "A coach's conditioning session next to the skill session it feeds "
            "-- ideally the same athletes on the same day. Look for footage "
            "where somebody explains what a particular exercise is for."
        ),
        ask=Ask(
            prompt="Why spend an hour on strength instead of practising the skill?",
            options=(
                "Because the skill needs strength you do not have yet",
                "Because coaches like conditioning",
                "Because it is safer than practising",
            ),
            answer=0,
            because=(
                "Almost every skill somebody cannot do is a skill they are not "
                "yet strong enough for. Repeating it does not make you "
                "stronger; the boring hour does."
            ),
        ),
    ),
    Topic(
        key="jdg_iq_tell_somebody",
        title="Sore is not the same as hurt",
        focus="Staying safe",
        positions=JUDGED_ALL, min_age=0, max_age=200, target_s=72,
        find=(
            "Coaching-education footage on the difference between muscle "
            "soreness and joint pain. This does not need to be dramatic "
            "footage and is better if it is not."
        ),
        ask=Ask(
            prompt="Something hurts in the same spot every session. What do you do?",
            options=(
                "Tell an adult, even though you can still train on it",
                "Warm up for longer and see if it settles",
                "Wait until it stops you training, then say something",
            ),
            answer=0,
            because=(
                "The same spot every time is the one worth mentioning. Waiting "
                "until it stops you is waiting until the easy fix has gone."
            ),
        ),
    ),
    Topic(
        key="jdg_iq_never_alone",
        title="New skills need somebody watching",
        focus="Staying safe",
        positions=TUMBLING, min_age=0, max_age=200, target_s=68,
        find=(
            "A skill being learned with a coach spotting, next to somebody "
            "trying one alone on a garden trampoline. Youth footage of the "
            "second is unfortunately not hard to find."
        ),
        ask=Ask(
            prompt="You have nearly got a new skill and nobody is at the gym. Do you try it?",
            options=(
                "No. A new skill is the one thing that needs somebody there",
                "Yes, if you are on something soft",
                "Yes, if you have done it before with a spot",
            ),
            answer=0,
            because=(
                "The skills people get hurt on are the ones they almost have. "
                "Nearly is exactly the point at which somebody needs to be "
                "watching."
            ),
        ),
    ),
)

JDG_CORE: tuple[Topic, ...] = (
    Topic(
        key="jdg_iq_ankles",
        title="It usually ends at the ankle",
        focus="Staying safe",
        positions=JUDGED_ALL, min_age=13, max_age=200, target_s=125,
        find=(
            "Landings in slow motion, from the floor upwards. The clip is what "
            "the ankle and the calf are doing on contact, not what the rest of "
            "the body is doing."
        ),
        ask=Ask(
            prompt="Why is calf and ankle work worth as much of your hour as anything else?",
            options=(
                "It is the last thing to touch the floor on every landing",
                "It makes your legs look better",
                "It is easy to do at home",
            ),
            answer=0,
            because=(
                "Every jump leaves from the ankle and every landing arrives "
                "there. It is the most-used joint in these three sports and the "
                "one most often trained by accident."
            ),
        ),
    ),
    Topic(
        key="jdg_iq_bail",
        title="How to come out of one that is going wrong",
        focus="Staying safe",
        positions=TUMBLING, min_age=13, max_age=200, target_s=130,
        find=(
            "A coach teaching a bail-out, how to land safely on a skill that "
            "has already gone wrong. Training footage, not competition."
        ),
        ask=Ask(
            prompt="A skill is going wrong halfway through. What is the goal now?",
            options=(
                "Land any way that is safe, even if it looks terrible",
                "Try to finish it so you do not learn a bad habit",
                "Stop moving",
            ),
            answer=0,
            because=(
                "Half-committing is how people land on their head or their "
                "wrists. A bail-out that looks awful and costs nothing is a "
                "skill in itself, and it is worth practising."
            ),
        ),
    ),
    Topic(
        key="jdg_iq_tired_reps",
        title="The last twenty minutes",
        focus="Training sense",
        positions=JUDGED_ALL, min_age=13, max_age=200, target_s=120,
        find=(
            "The same athlete doing the same skill at the start of a session "
            "and at the end of a long one. The difference is the clip."
        ),
        ask=Ask(
            prompt="You are tired and the last few attempts have got worse. What now?",
            options=(
                "Stop that skill. Tired reps teach the tired version",
                "Push through, that is where the improvement is",
                "Do a few more slowly",
            ),
            answer=0,
            because=(
                "Your body learns whatever you repeat, including the sloppy "
                "one. The last twenty minutes of a long session is where most "
                "bad habits and a lot of injuries come from."
            ),
        ),
    ),
    Topic(
        key="jdg_iq_growth",
        title="Why a skill you had last month has gone",
        focus="Training sense",
        positions=JUDGED_ALL, min_age=13, max_age=200, target_s=128,
        find=(
            "Coaching-education footage about training through a growth spurt. "
            "Anything that shows a coach adjusting expectations rather than "
            "an athlete being told to try harder."
        ),
        ask=Ask(
            prompt="You have grown and a skill you used to have now feels wrong. Why?",
            options=(
                "Your levers changed, so the timing has to be relearned",
                "You have got lazy",
                "You have lost your talent for it",
            ),
            answer=0,
            because=(
                "A longer body turns at a different speed. The skill is not "
                "gone, the timing is out, and being told that is the "
                "difference between a hard month and quitting."
            ),
        ),
    ),
    Topic(
        key="jdg_iq_fuel",
        title="You cannot train hard on not enough food",
        focus="Staying safe",
        positions=JUDGED_ALL, min_age=13, max_age=200, target_s=135,
        find=(
            "Sports-dietitian or governing-body education footage aimed at "
            "young athletes about eating enough to train. Choose something "
            "that talks about fuel and performance, not about weight."
        ),
        ask=Ask(
            prompt="What happens to training when an athlete is not eating enough?",
            options=(
                "They get weaker, break more easily and heal slower",
                "They get lighter and everything gets easier",
                "Nothing, as long as they feel fine",
            ),
            answer=0,
            because=(
                "Hard training on too little fuel takes it out of muscle and "
                "bone. It shows up as strength that stops improving and "
                "injuries that keep coming back, long before it feels like "
                "anything is wrong."
            ),
        ),
    ),
    Topic(
        key="jdg_iq_spot",
        title="What a good spot is, and when to say no",
        focus="Staying safe",
        positions=STUNTING, min_age=13, max_age=200, target_s=125,
        find=(
            "A stunt going up with a proper backspot, and one where the "
            "spotter is out of position or looking elsewhere. Watch the "
            "spotter, not the flyer."
        ),
        ask=Ask(
            prompt="You are asked to put up a stunt and the spot does not feel right. What do you do?",
            options=(
                "Say so and do not go up",
                "Go up, but come down quickly",
                "Go up, everybody else is ready",
            ),
            answer=0,
            because=(
                "Somebody is trusting you with the fall. The only person who "
                "can stop an unsafe stunt is whoever notices first, and there "
                "is no version of this where being the one who spoke is wrong."
            ),
        ),
    ),
)

JDG_ADVANCED: tuple[Topic, ...] = (
    Topic(
        key="jdg_iq_scored_on_looks",
        title="The routine is scored. You are not.",
        focus="Training sense",
        positions=JUDGED_ALL, min_age=15, max_age=200, target_s=160,
        find=(
            "A judge or a senior coach explaining what a score is actually "
            "made of, the elements, the deductions, the execution. The point "
            "is how specific and how technical it is."
        ),
        ask=Ask(
            prompt="A score in this sport is a judgement about what?",
            options=(
                "The elements you performed and how you executed them",
                "How you look",
                "How hard you have worked this season",
            ),
            answer=0,
            because=(
                "A score is a list of elements and deductions. The lever you "
                "actually control is being strong enough to hit them, which is "
                "the only thing this app measures and the only thing it has an "
                "opinion about."
            ),
        ),
    ),
    Topic(
        key="jdg_iq_comments",
        title="When a comment is about your body",
        focus="Staying safe",
        positions=JUDGED_ALL, min_age=15, max_age=200, target_s=150,
        find=(
            "Safeguarding or governing-body education footage on what is and "
            "is not acceptable for an adult in the sport to say to a young "
            "athlete. Official material is better here than anything else."
        ),
        ask=Ask(
            prompt="An adult in your sport makes a comment about your body or your weight. What do you do?",
            options=(
                "Tell another adult you trust, even if it seemed like a joke",
                "Ignore it, it is part of the sport",
                "Change what you are doing so it stops",
            ),
            answer=0,
            because=(
                "You do not have to decide whether it was meant badly, and you "
                "should not have to. Telling somebody is the whole action, and "
                "it is theirs to sort out from there."
            ),
        ),
    ),
    Topic(
        key="jdg_iq_back",
        title="Back pain that keeps coming back",
        focus="Staying safe",
        positions=JUDGED_ALL, min_age=15, max_age=200, target_s=155,
        find=(
            "Coaching-education footage on back pain in young athletes who "
            "bend backwards a lot. Look for material that says plainly when to "
            "stop and see somebody."
        ),
        ask=Ask(
            prompt="Your lower back has ached after every session for two weeks. What is the move?",
            options=(
                "Tell an adult and get it looked at properly",
                "Stretch it more before and after",
                "Strengthen your core and it will settle",
            ),
            answer=0,
            because=(
                "Back pain in a young athlete that keeps returning is one to "
                "have looked at rather than to train around. Stretching "
                "something that hurts every session is how two weeks becomes a "
                "season."
            ),
        ),
    ),
    Topic(
        key="jdg_iq_wrists",
        title="Wrists take everything you do",
        focus="Staying safe",
        positions=TUMBLING, min_age=15, max_age=200, target_s=145,
        find=(
            "Slow-motion of a hand contact in tumbling or vaulting. The clip "
            "is how much load goes through the wrist and how briefly."
        ),
        ask=Ask(
            prompt="Your wrists hurt when you put weight on them. What does that change?",
            options=(
                "Say something and swap to work that does not load them",
                "Tape them and carry on",
                "Do fewer repetitions of the same thing",
            ),
            answer=0,
            because=(
                "In these sports the wrist is a weight-bearing joint that was "
                "never designed to be one. There is always conditioning that "
                "does not go through your hands, and taping over it is how you "
                "find that out the slow way."
            ),
        ),
    ),
    Topic(
        key="jdg_iq_one_sport",
        title="Twelve months of the same thing",
        focus="Training sense",
        positions=JUDGED_ALL, min_age=15, max_age=200, target_s=150,
        find=(
            "Coaching-education footage on year-round single-sport training in "
            "young athletes. Look for material that talks about what a break "
            "is for rather than simply warning about it."
        ),
        ask=Ask(
            prompt="Why does the app ask what else you play and when your season ends?",
            options=(
                "Because doing one thing all year loads the same tissue all year",
                "To compare you with other athletes",
                "To fill in your profile",
            ),
            answer=0,
            because=(
                "It is the same joints, in the same directions, with no off "
                "season. The answer changes how much solo work this app will "
                "suggest, which is the only reason it asks."
            ),
        ),
    ),
)

JDG_TOPICS: tuple[Topic, ...] = JDG_FUNDAMENTALS + JDG_CORE + JDG_ADVANCED


# ---------------------------------------------------------------------------
# Football
#
# The sport where the syllabus has the least excuse to be about anything else.
# Football IQ is real -- leverage, keys, where help is -- and it is taught here,
# but head contact is this sport's defining risk in a way hockey's is not even
# close to, and a syllabus that covered coverage shells and said nothing about
# tackling with your head up would be teaching the easy half.
#
# So four of these are about the head and the neck, they start at the youngest
# band rather than the oldest, and they are aimed at every position rather than
# only at the ones who tackle.
# ---------------------------------------------------------------------------

FB_ALL = ("quarterback", "skill", "line", "linebacker", "defensive_back", "specialist")
FB_TACKLERS = ("line", "linebacker", "defensive_back", "skill")
FB_BALL = ("quarterback", "skill")
FB_BACK = ("linebacker", "defensive_back")

FB_FUNDAMENTALS: tuple[Topic, ...] = (
    Topic(
        key="fb_iq_head_up",
        title="See what you hit",
        focus="Staying safe",
        positions=FB_TACKLERS, min_age=0, max_age=200, target_s=72,
        find=(
            "Coaching-education footage of a tackle with the head up and to the "
            "side, next to one where the crown goes in first. Official "
            "governing-body material is better here than game footage."
        ),
        ask=Ask(
            prompt="Where should your head be when you make a tackle?",
            options=(
                "Up, with your eyes on what you are hitting",
                "Tucked down, so your helmet takes it",
                "Turned away at the last moment",
            ),
            answer=0,
            because=(
                "Your neck is only strong in the position it can see from. A "
                "head that goes down first is a neck taking a load it was "
                "never built for."
            ),
        ),
    ),
    Topic(
        key="fb_iq_say_something",
        title="After a big hit, say something",
        focus="Staying safe",
        positions=FB_ALL, min_age=0, max_age=200, target_s=70,
        find=(
            "Sideline footage of a player being checked after a collision, and "
            "one jogging straight back to the huddle. What happens on the next "
            "series is the clip."
        ),
        ask=Ask(
            prompt="You took a big hit and your head feels odd, but you can play. What now?",
            options=(
                "Tell an adult before the next snap",
                "Get through the series and see how you feel",
                "Ask a teammate whether you seem alright",
            ),
            answer=0,
            because=(
                "You are using the injured part to decide whether you are "
                "injured. One snap is not worth a season, and the person who "
                "tells somebody has done the whole job."
            ),
        ),
    ),
    Topic(
        key="fb_iq_know_the_down",
        title="Know the down and the distance",
        focus="Situations",
        positions=FB_ALL, min_age=0, max_age=200, target_s=68,
        find=(
            "A third-and-two next to a third-and-nine from the same team. The "
            "clip is what everybody does before the snap, not after it."
        ),
        ask=Ask(
            prompt="Why does the down and distance change what you do before the snap?",
            options=(
                "It tells you what the other team is most likely to try",
                "It tells you how much time is left",
                "It decides where the ball is placed",
            ),
            answer=0,
            because=(
                "Everybody on the field is guessing, and the down is the "
                "biggest clue anybody gets. Guessing better is most of what "
                "good players do."
            ),
        ),
    ),
)

FB_CORE: tuple[Topic, ...] = (
    Topic(
        key="fb_iq_neck",
        title="Why your neck is training equipment",
        focus="Staying safe",
        positions=FB_ALL, min_age=13, max_age=200, target_s=125,
        find=(
            "Coaching or sports-science education footage on neck strength in "
            "collision sports. Anything that shows what a head does on impact "
            "with a braced neck against a loose one."
        ),
        ask=Ask(
            prompt="What does a stronger neck actually do for you?",
            options=(
                "It slows how fast your head moves when you get hit",
                "It stops you getting hit as hard",
                "It protects your helmet",
            ),
            answer=0,
            because=(
                "Nothing stops the hit. What a braced neck changes is how "
                "violently your head travels afterwards, and that is the part "
                "that matters."
            ),
        ),
    ),
    Topic(
        key="fb_iq_leverage",
        title="Low man wins, and why",
        focus="Technique sense",
        positions=("line", "linebacker"), min_age=13, max_age=200, target_s=120,
        find=(
            "Two blocks from the same game: one where the lower player moves "
            "the higher one, and one the other way round. Watch the hips, not "
            "the hands."
        ),
        ask=Ask(
            prompt="Two players hit each other with the same effort. Who usually wins?",
            options=(
                "The one with their hips lower and their feet still moving",
                "The heavier one",
                "The one who arrives first",
            ),
            answer=0,
            because=(
                "Leverage beats size at this age nearly every time, and it is "
                "the only one of the two you can do anything about this week."
            ),
        ),
    ),
    Topic(
        key="fb_iq_eyes",
        title="Look at the right thing",
        focus="Situations",
        positions=FB_BACK, min_age=13, max_age=200, target_s=128,
        find=(
            "A defender whose eyes are in the backfield on a play-action, next "
            "to one reading their key. The clip is where they are standing two "
            "seconds later."
        ),
        ask=Ask(
            prompt="On a play fake, what should a defender's eyes be on?",
            options=(
                "Their key, the player their job says to read",
                "The ball",
                "The quarterback's eyes",
            ),
            answer=0,
            because=(
                "The ball is exactly what the offence wants you looking at. "
                "Your key does not lie, and a play fake only works on people "
                "watching the wrong thing."
            ),
        ),
    ),
    Topic(
        key="fb_iq_throw_it_away",
        title="The best throw is sometimes no throw",
        focus="Situations",
        positions=FB_BALL, min_age=13, max_age=200, target_s=122,
        find=(
            "A quarterback taking a sack or forcing one into coverage, next to "
            "one throwing it away and living to the next down."
        ),
        ask=Ask(
            prompt="The play has broken down and nobody is open. What is the best outcome?",
            options=(
                "Throw it away and play the next down",
                "Force it to your best receiver",
                "Run until something opens up",
            ),
            answer=0,
            because=(
                "Second and ten is a bad down. An interception is a worse one, "
                "and so is a hit you did not have to take."
            ),
        ),
    ),
    Topic(
        key="fb_iq_arm_count",
        title="Nobody counts a quarterback's throws",
        focus="Staying safe",
        positions=FB_BALL, min_age=13, max_age=200, target_s=130,
        find=(
            "A quarterback through a full practice, individual period, "
            "seven-on-seven, team. Count the throws. That number is the clip."
        ),
        ask=Ask(
            prompt="Roughly how many throws does a quarterback make in a normal week?",
            options=(
                "Far more than anybody has ever counted",
                "About as many as a pitcher throws in a game",
                "It depends on how many passes are called",
            ),
            answer=0,
            because=(
                "Baseball counts pitches down to the last one. Football counts "
                "nothing, and the same shoulder and the same elbow are doing "
                "the work. The app counts what it can see, the rest is on "
                "you to notice."
            ),
        ),
    ),
)

FB_ADVANCED: tuple[Topic, ...] = (
    Topic(
        key="fb_iq_targeting",
        title="The hit you have to pull out of",
        focus="Staying safe",
        positions=FB_TACKLERS, min_age=15, max_age=200, target_s=160,
        find=(
            "Officiating or governing-body education footage on targeting and "
            "defenceless players. Use material where the call is explained, "
            "because the explanation is the lesson."
        ),
        ask=Ask(
            prompt="A receiver is stretched out for a catch and you can get there. What do you do?",
            options=(
                "Pull up or hit low. They cannot protect themselves at all",
                "Finish it, they chose to go up for it",
                "Lead with your shoulder and aim high",
            ),
            answer=0,
            because=(
                "A player in the air with their arms up has no way to brace. "
                "Every serious injury in this sport starts with somebody "
                "deciding the hit was still available."
            ),
        ),
    ),
    Topic(
        key="fb_iq_help",
        title="Knowing where your help is",
        focus="Situations",
        positions=FB_BACK, min_age=15, max_age=200, target_s=155,
        find=(
            "The same corner with a safety over the top and without one. How "
            "differently they play the same route is the whole clip."
        ),
        ask=Ask(
            prompt="You have a safety over the top. How does that change how you cover?",
            options=(
                "You can play the short route harder and let help take the deep one",
                "You play further off, because deep is still yours",
                "It does not change anything you do",
            ),
            answer=0,
            because=(
                "Coverage is a group of people dividing up the field. Playing "
                "as though you are alone when you are not gives away the "
                "throw underneath for nothing."
            ),
        ),
    ),
    Topic(
        key="fb_iq_specialist_reps",
        title="A kicker's season is a repetition count",
        focus="Staying safe",
        positions=("specialist",), min_age=15, max_age=200, target_s=150,
        find=(
            "A kicker's ordinary practice, uncut if you can get it. What you "
            "are counting is swings, including the ones with no ball."
        ),
        ask=Ask(
            prompt="What is the risk in a kicker's week that nobody watches?",
            options=(
                "The sheer number of full-effort swings, all on one hip",
                "Kicking in bad weather",
                "Not stretching enough",
            ),
            answer=0,
            because=(
                "It is the same hip, the same range, at full effort, hundreds "
                "of times, alone. Nobody is counting because nobody has ever "
                "had to, and it is the reason this app counts swings at all."
            ),
        ),
    ),
    Topic(
        key="fb_iq_offseason",
        title="What an off season is actually for",
        focus="Training sense",
        positions=FB_ALL, min_age=15, max_age=200, target_s=158,
        find=(
            "Coaching-education footage on year-round football and what a real "
            "break does. Look for material about tissue and recovery rather "
            "than about burnout alone."
        ),
        ask=Ask(
            prompt="Why does the app ask when your season ends and what else you play?",
            options=(
                "Because the same tissue needs a stretch of the year off it",
                "To compare you with other players",
                "To work out which drills to show you",
            ),
            answer=0,
            because=(
                "Collision, throwing and sprinting all load something that has "
                "to be given time back. Twelve months of football is twelve "
                "months of the same load on the same places."
            ),
        ),
    ),
)

FB_IQ_TOPICS: tuple[Topic, ...] = FB_FUNDAMENTALS + FB_CORE + FB_ADVANCED


# ---------------------------------------------------------------------------
# Rugby
#
# Same rules as every syllabus here. What is distinctive is that this sport has
# spent the last decade actively changing its own laws about where a tackle may
# land, because the answer turned out to matter more than anybody thought -- so
# the safety half of this syllabus is teaching a moving target, and it says so
# rather than presenting one country's current law as physics.
#
# Five topics are about contact and the head. That is not editorialising: the
# tackle is the single most common event in the game and the single most common
# way anybody gets hurt in it.
# ---------------------------------------------------------------------------

RUG_ALL = ("front_row", "second_row", "half_back", "backs")
RUG_FORWARDS = ("front_row", "second_row")
RUG_BACKS = ("half_back", "backs")

RUG_FUNDAMENTALS: tuple[Topic, ...] = (
    Topic(
        key="rug_iq_low_tackle",
        title="Tackle low, and look at what you are tackling",
        focus="Staying safe",
        positions=RUG_ALL, min_age=0, max_age=200, target_s=72,
        find=(
            "Governing-body coaching footage of a tackle around the thighs "
            "with the head to the side, next to an upright one. Official "
            "material is much better here than match footage."
        ),
        ask=Ask(
            prompt="Where should your head go when you tackle?",
            options=(
                "To the side of them, with your eyes open and on the target",
                "Straight into the contact, so you take it evenly",
                "Tucked down and away so it is out of the way",
            ),
            answer=0,
            because=(
                "A head that goes into the contact is a head and neck taking a "
                "load nothing about a fourteen-year-old is built for. To the "
                "side and eyes open is the whole technique."
            ),
        ),
    ),
    Topic(
        key="rug_iq_say_something",
        title="After a knock, say something",
        focus="Staying safe",
        positions=RUG_ALL, min_age=0, max_age=200, target_s=70,
        find=(
            "Sideline footage of a player being assessed after contact, and "
            "one who gets up and plays on. What they do over the next two "
            "minutes is the clip."
        ),
        ask=Ask(
            prompt="You took a knock to the head and you feel a bit off, but you can carry on. What now?",
            options=(
                "Come off and tell an adult straight away",
                "Play the rest of the passage and reassess",
                "Ask a teammate whether you look alright",
            ),
            answer=0,
            because=(
                "You are using the injured part to decide whether you are "
                "injured. Nobody has ever regretted coming off, and the person "
                "who says something has done the entire job."
            ),
        ),
    ),
    Topic(
        key="rug_iq_both_hands",
        title="A pass off one hand is half a player",
        focus="Skills",
        positions=RUG_ALL, min_age=0, max_age=200, target_s=68,
        find=(
            "A back line moving the ball both ways, next to one where a player "
            "has to turn their whole body to pass left. Watch the defence read "
            "the second one."
        ),
        ask=Ask(
            prompt="Why does it matter that you can pass off both hands?",
            options=(
                "Because a defence works out which way you cannot pass",
                "Because it looks better",
                "Because coaches ask for it",
            ),
            answer=0,
            because=(
                "Everybody watching can see which side you turn to. Once they "
                "know, half the field stops being available to your team."
            ),
        ),
    ),
)

RUG_CORE: tuple[Topic, ...] = (
    Topic(
        key="rug_iq_tackle_height_law",
        title="The legal height keeps moving, and why",
        focus="Staying safe",
        positions=RUG_ALL, min_age=13, max_age=200, target_s=130,
        find=(
            "Your own union's current guidance on tackle height for this age "
            "group. This one has to be re-cut when the law changes, which it "
            "has done repeatedly, do not use footage from another country or "
            "another season."
        ),
        ask=Ask(
            prompt="Why has rugby kept lowering where a tackle is allowed to land?",
            options=(
                "Because lower tackles produce fewer head collisions",
                "To make the game faster",
                "To make it harder to defend",
            ),
            answer=0,
            because=(
                "Most head-to-head contact in this sport happens when the "
                "tackler is upright. Lowering the target lowers both heads, "
                "which is the only part of it anybody can control."
            ),
        ),
    ),
    Topic(
        key="rug_iq_scrum_safety",
        title="A scrum is not a thing to practise alone",
        focus="Staying safe",
        positions=RUG_FORWARDS, min_age=13, max_age=200, target_s=125,
        find=(
            "Coaching-education footage on the scrum sequence and why it is "
            "called. The clip is the setup and the call, not the shove."
        ),
        ask=Ask(
            prompt="Why is every scrum called in the same sequence, every single time?",
            options=(
                "So nobody's neck is loaded before they are ready for it",
                "To give the referee time to get into position",
                "To slow the game down",
            ),
            answer=0,
            because=(
                "The sequence exists because front rows get hurt when the "
                "engagement is early or uneven. It is the one part of this "
                "sport where the ritual is the safety measure."
            ),
        ),
    ),
    Topic(
        key="rug_iq_support",
        title="The pass is only half of it",
        focus="Support",
        positions=RUG_ALL, min_age=13, max_age=200, target_s=120,
        find=(
            "A carrier going into contact with two players arriving behind "
            "them, and the same carrier arriving alone. Cut wide enough to see "
            "who is running and who is watching."
        ),
        ask=Ask(
            prompt="Your teammate is about to be tackled. Where should you be?",
            options=(
                "Close enough behind them to arrive before the defence does",
                "Wide, in case the ball comes out",
                "Back, in case it goes wrong",
            ),
            answer=0,
            because=(
                "A carrier with nobody behind them loses the ball. Most turnovers "
                "at this level are not tackles, they are a carrier arriving "
                "alone."
            ),
        ),
    ),
    Topic(
        key="rug_iq_depth",
        title="Standing flat gives you nothing",
        focus="Attack",
        positions=RUG_BACKS, min_age=13, max_age=200, target_s=126,
        find=(
            "A back line taking the ball flat and one taking it with depth. "
            "The clip is where each receiver is standing when the ball leaves, "
            "not where they end up."
        ),
        ask=Ask(
            prompt="Why do backs stand deeper than feels necessary?",
            options=(
                "So you are moving at speed when the ball arrives",
                "To give the passer an easier target",
                "To stay away from the defence",
            ),
            answer=0,
            because=(
                "Standing flat means catching it standing still, a metre from "
                "somebody who is not. Depth is how you get to be the one "
                "arriving at pace."
            ),
        ),
    ),
    Topic(
        key="rug_iq_never_sideways",
        title="Running across the field helps the defence",
        focus="Attack",
        positions=RUG_BACKS, min_age=13, max_age=200, target_s=118,
        find=(
            "A back line drifting sideways until it runs out of pitch, next to "
            "one attacking straight and passing late. Watch the touchline in "
            "the first one."
        ),
        ask=Ask(
            prompt="What happens when an attack runs sideways?",
            options=(
                "The defence gets to slide across and nobody has to beat anyone",
                "It creates space on the outside",
                "It buys time for support to arrive",
            ),
            answer=0,
            because=(
                "Running sideways gives the defence exactly what they want: "
                "time, and a touchline to push you into. Straight first, then "
                "the pass."
            ),
        ),
    ),
)

RUG_ADVANCED: tuple[Topic, ...] = (
    Topic(
        key="rug_iq_head_on_head",
        title="The collision nobody meant",
        focus="Staying safe",
        positions=RUG_ALL, min_age=15, max_age=200, target_s=160,
        find=(
            "Officiating or union education footage explaining head-on-head "
            "contact and how it is judged. Material where the decision is "
            "talked through is worth far more than the incident."
        ),
        ask=Ask(
            prompt="Most head-to-head contact in a tackle happens because of what?",
            options=(
                "A tackler upright and a carrier dipping into them",
                "Two players running very fast",
                "A player not being strong enough",
            ),
            answer=0,
            because=(
                "Two heads end up in the same place because one player stayed "
                "tall and the other dropped. Both of those are decisions, which "
                "is why both are coached."
            ),
        ),
    ),
    Topic(
        key="rug_iq_ruck_arrival",
        title="Arriving at a ruck on your feet",
        focus="Staying safe",
        positions=RUG_ALL, min_age=15, max_age=200, target_s=150,
        find=(
            "A player arriving low, square and on their feet, and one diving "
            "off their feet into the side. The penalty in the second one is "
            "part of the lesson, and so is the neck position."
        ),
        ask=Ask(
            prompt="Why does the law insist you stay on your feet at a ruck?",
            options=(
                "Because a player off their feet cannot protect their own neck",
                "To keep the ball available",
                "To make it easier to referee",
            ),
            answer=0,
            because=(
                "A player diving in headfirst has no way to brace and nowhere "
                "to go. The law is a safety rule that happens to also keep the "
                "ball moving."
            ),
        ),
    ),
    Topic(
        key="rug_iq_kick_choice",
        title="When to kick and when not to",
        focus="Decisions",
        positions=("half_back",), min_age=15, max_age=200, target_s=158,
        find=(
            "Two kicks from the same match: one that puts a side into a good "
            "position and one that hands the ball back with the field open. "
            "The clip is the four seconds before each."
        ),
        ask=Ask(
            prompt="You have the ball in your own half with defenders up fast. What is the question?",
            options=(
                "Whether kicking gets you more than keeping it does",
                "Whether you can kick it far enough",
                "Whether your winger is fast enough to chase",
            ),
            answer=0,
            because=(
                "A kick gives the ball away on purpose. That is sometimes the "
                "best decision on the field and sometimes the worst one, and "
                "the difference is what you get back for it."
            ),
        ),
    ),
    Topic(
        key="rug_iq_neck",
        title="Your neck is training equipment",
        focus="Staying safe",
        positions=RUG_ALL, min_age=15, max_age=200, target_s=155,
        find=(
            "Sports-science or union education footage on neck strength in "
            "contact sports. Anything showing what a head does on impact with "
            "a braced neck against a loose one."
        ),
        ask=Ask(
            prompt="What does a stronger neck actually do for you?",
            options=(
                "It slows how fast your head moves when you get hit",
                "It stops you getting hit as hard",
                "It prevents you being tackled",
            ),
            answer=0,
            because=(
                "Nothing stops the contact. What a braced neck changes is how "
                "violently your head travels afterwards, and that is the part "
                "that matters. This app cannot count neck work, a good "
                "isometric hold does not move, so it is coached rather than "
                "scored."
            ),
        ),
    ),
    Topic(
        key="rug_iq_offseason",
        title="Twelve months of contact",
        focus="Training sense",
        positions=RUG_ALL, min_age=15, max_age=200, target_s=152,
        find=(
            "Coaching-education footage on year-round contact loading in young "
            "players. Look for material about what a real break gives back "
            "rather than only warning about burnout."
        ),
        ask=Ask(
            prompt="Why does the app ask when your season ends and what else you play?",
            options=(
                "Because contact loads something that needs a stretch of the year off",
                "To compare you with other players",
                "To pick which drills to show you",
            ),
            answer=0,
            because=(
                "Every collision is absorbed by something, and that something "
                "repairs on a timescale nobody sees. The answer changes how "
                "much solo work this app will suggest, which is the only "
                "reason it asks."
            ),
        ),
    ),
)

RUG_IQ_TOPICS: tuple[Topic, ...] = RUG_FUNDAMENTALS + RUG_CORE + RUG_ADVANCED


# ---------------------------------------------------------------------------
# Track and cross country
#
# One syllabus under both, on the same reasoning that gave baseball and softball
# one: the decisions are the same decisions. A cross country runner and a track
# distance runner are usually the same child in a different season.
#
# What makes this syllabus different from every other one here is that almost
# none of it is about how to do the thing. These are TIMED sports. There is no
# read, no coverage, no defender -- the skill is pacing, and everything else
# that decides a season is load, fuel and knowing when a niggle is not a niggle.
# So the syllabus is mostly about training rather than competing, and it says so.
# ---------------------------------------------------------------------------

TRK_ALL = ("sprints", "middle_distance", "distance", "jumps", "throws")
TRK_RUN = ("sprints", "middle_distance", "distance")
TRK_ENDURANCE = ("middle_distance", "distance")
TRK_FIELD = ("jumps", "throws")

TRK_FUNDAMENTALS: tuple[Topic, ...] = (
    Topic(
        key="trk_iq_even_pace",
        title="The first lap is the one that ruins races",
        focus="Racing",
        positions=TRK_ENDURANCE, min_age=0, max_age=200, target_s=70,
        find=(
            "Two runners in the same race: one who goes out with the leaders "
            "and fades, one who runs even splits and passes them. Youth "
            "footage makes the first one very easy to find."
        ),
        ask=Ask(
            prompt="You feel great in the first minute of a race. What does that mean?",
            options=(
                "Nothing yet, everybody feels great in the first minute",
                "You are having a good day and should push",
                "You went out too slow",
            ),
            answer=0,
            because=(
                "Feeling good early is what running too fast feels like. The "
                "runners who pass you at the end are the ones who did not "
                "trust that feeling."
            ),
        ),
    ),
    Topic(
        key="trk_iq_niggle",
        title="A niggle that keeps coming back",
        focus="Staying safe",
        positions=TRK_ALL, min_age=0, max_age=200, target_s=72,
        find=(
            "Coaching-education footage about running injuries that build up "
            "slowly. Anything that shows a runner training through the same "
            "pain for weeks is better than a dramatic injury."
        ),
        ask=Ask(
            prompt="The same spot in your shin or foot has hurt for two weeks. What do you do?",
            options=(
                "Tell an adult and get it looked at properly",
                "Run easier for a few days and see",
                "Change your shoes",
            ),
            answer=0,
            because=(
                "Pain in the same spot that will not settle is the one to have "
                "looked at rather than run through. Running injuries do not "
                "announce themselves, they build for weeks and then stop you "
                "for months."
            ),
        ),
    ),
    Topic(
        key="trk_iq_easy_easy",
        title="Easy days have to be actually easy",
        focus="Training sense",
        positions=TRK_ENDURANCE, min_age=0, max_age=200, target_s=68,
        find=(
            "A squad on a recovery run where half the group is racing it. The "
            "clip is the conversation, who can talk and who cannot."
        ),
        ask=Ask(
            prompt="How fast should an easy run be?",
            options=(
                "Slow enough to hold a conversation the whole way",
                "A bit slower than race pace",
                "Whatever feels comfortable that day",
            ),
            answer=0,
            because=(
                "Every easy run done a little too hard turns a week into one "
                "long medium effort. The hard days then are not hard, and the "
                "easy days never repaired anything."
            ),
        ),
    ),
)

TRK_CORE: tuple[Topic, ...] = (
    Topic(
        key="trk_iq_mileage_jump",
        title="Adding too much, too quickly",
        focus="Staying safe",
        positions=TRK_ALL, min_age=13, max_age=200, target_s=128,
        find=(
            "Coaching-education footage on building weekly volume in young "
            "runners. Material that talks about bone rather than only about "
            "fitness is worth much more here."
        ),
        ask=Ask(
            prompt="Why does adding a lot of running in one week cause problems weeks later?",
            options=(
                "Bone adapts more slowly than muscle and lungs do",
                "Your muscles need longer to recover",
                "You get tired and your form goes",
            ),
            answer=0,
            because=(
                "Fitness arrives before the skeleton has caught up, so you "
                "feel able to do more at exactly the point your bones are "
                "furthest behind. That gap is where stress injuries live."
            ),
        ),
    ),
    Topic(
        key="trk_iq_fuel",
        title="You cannot train on not enough food",
        focus="Staying safe",
        positions=TRK_ALL, min_age=13, max_age=200, target_s=135,
        find=(
            "Sports-dietitian or governing-body education footage aimed at "
            "young endurance athletes about eating enough to train. Choose "
            "material about fuel and performance, not about weight."
        ),
        ask=Ask(
            prompt="What happens to a runner who is not eating enough for their training?",
            options=(
                "They get slower, break more easily and heal more slowly",
                "They get lighter and races get easier",
                "Nothing, as long as they feel fine",
            ),
            answer=0,
            because=(
                "Endurance training on too little fuel takes it out of bone "
                "and muscle. It shows up as times that stop improving and "
                "injuries that keep returning, long before it feels like "
                "anything is wrong."
            ),
        ),
    ),
    Topic(
        key="trk_iq_rest_day",
        title="What a rest day is actually for",
        focus="Training sense",
        positions=TRK_ALL, min_age=13, max_age=200, target_s=120,
        find=(
            "Coaching-education footage on recovery and adaptation. Look for "
            "material that explains what happens on the day off rather than "
            "only warning about overtraining."
        ),
        ask=Ask(
            prompt="When does training actually make you fitter?",
            options=(
                "On the days off, while your body repairs the damage",
                "During the hard sessions",
                "Over the whole week evenly",
            ),
            answer=0,
            because=(
                "The session is the stimulus; the adaptation happens after it. "
                "A week with no rest day is a week of stimulus with nothing "
                "built on top of it."
            ),
        ),
    ),
    Topic(
        key="trk_iq_pack",
        title="Racing the runners, not the clock",
        focus="Racing",
        positions=TRK_ENDURANCE, min_age=13, max_age=200, target_s=125,
        find=(
            "A cross country race where somebody sits on a shoulder for two "
            "miles and goes past at the top of a hill. Cut it wide enough to "
            "see the pack rather than only the leader."
        ),
        ask=Ask(
            prompt="You are in a pack halfway through a cross country race. What is the job?",
            options=(
                "Stay in it and use it, running alone costs you",
                "Get clear of it so you have space",
                "Drop back and save energy",
            ),
            answer=0,
            because=(
                "A pack drags you along at a pace you would not hold on your "
                "own, and it does it for free. Runners who break away early "
                "usually spend the rest of the race being caught."
            ),
        ),
    ),
    Topic(
        key="trk_iq_hills",
        title="How to run a hill without paying for it",
        focus="Racing",
        positions=TRK_ENDURANCE, min_age=13, max_age=200, target_s=122,
        find=(
            "The same hill taken two ways: one runner charging it and blowing "
            "up over the top, one keeping effort even and going past them on "
            "the flat afterwards."
        ),
        ask=Ask(
            prompt="Going up a steep hill in a race, what should stay the same?",
            options=(
                "Your effort, which means your pace slows",
                "Your pace, which means your effort rises",
                "Your stride length",
            ),
            answer=0,
            because=(
                "Holding pace up a hill spends far more than the time it saves. "
                "The place to take it back is the thirty seconds over the top, "
                "when everybody who charged it is recovering."
            ),
        ),
    ),
    Topic(
        key="trk_iq_field_approach",
        title="The run-up is most of the event",
        focus="Technique sense",
        positions=TRK_FIELD, min_age=13, max_age=200, target_s=118,
        find=(
            "A jumper or thrower whose approach is identical every attempt "
            "next to one adjusting on the way in. Watch the feet, not the "
            "landing."
        ),
        ask=Ask(
            prompt="Why do jumpers count their approach steps?",
            options=(
                "So the takeoff happens in the same place every time",
                "To build up more speed",
                "To help with concentration",
            ),
            answer=0,
            because=(
                "Everything after the takeoff depends on hitting it right. A "
                "run-up that changes every attempt makes the rest of the event "
                "a different event each time."
            ),
        ),
    ),
)

TRK_ADVANCED: tuple[Topic, ...] = (
    Topic(
        key="trk_iq_season_shape",
        title="Why nobody is fast all year",
        focus="Training sense",
        positions=TRK_ALL, min_age=15, max_age=200, target_s=158,
        find=(
            "Coaching-education footage on periodisation for young athletes. "
            "Look for material that explains why the base phase looks slow on "
            "purpose."
        ),
        ask=Ask(
            prompt="Why does a season have a base phase where nothing is fast?",
            options=(
                "Because the fast work later only works on top of it",
                "To keep training interesting",
                "Because it is the off season",
            ),
            answer=0,
            because=(
                "Sharpness lasts weeks, not months. Trying to hold it all year "
                "means arriving at the races that matter already flat, and "
                "usually already injured."
            ),
        ),
    ),
    Topic(
        key="trk_iq_two_seasons",
        title="Cross country and track are one long year",
        focus="Training sense",
        positions=TRK_ALL, min_age=15, max_age=200, target_s=150,
        find=(
            "Anything that lays a school cross country season next to the "
            "indoor and outdoor track seasons on one calendar. The gap between "
            "them is the clip."
        ),
        ask=Ask(
            prompt="You run cross country in autumn and track in spring. How many seasons is that?",
            options=(
                "One, unless somebody deliberately puts a break in it",
                "Two, with a natural break between them",
                "Three, counting indoors",
            ),
            answer=0,
            because=(
                "The calendar has gaps; the legs do not notice them unless you "
                "take one. Running through from September to June is a single "
                "unbroken block, and it is the most common way a promising "
                "young runner ends up hurt."
            ),
        ),
    ),
    Topic(
        key="trk_iq_log_honestly",
        title="Why the app asks how long you ran",
        focus="Training sense",
        positions=TRK_ALL, min_age=15, max_age=200, target_s=145,
        find=(
            "Not footage, a coach explaining a training log to a squad, or "
            "a screen recording of one being filled in. The point is what the "
            "log is FOR."
        ),
        ask=Ask(
            prompt="What does logging your runs in this app get you?",
            options=(
                "Nothing, except a load model that can see your actual week",
                "Points and a longer streak",
                "A place on the leaderboard",
            ),
            answer=0,
            because=(
                "It is worth no XP on purpose. Nothing you type can earn you "
                "anything, which is exactly why the app is willing to believe "
                "it, and why over-stating it only buys you a warning you did "
                "not need."
            ),
        ),
    ),
    Topic(
        key="trk_iq_shoes",
        title="What shoes can and cannot do",
        focus="Staying safe",
        positions=TRK_RUN, min_age=15, max_age=200, target_s=140,
        find=(
            "Governing-body or coaching-education material on footwear for "
            "young runners. Avoid anything produced by a shoe company."
        ),
        ask=Ask(
            prompt="A shoe that feels great is doing what, exactly?",
            options=(
                "Changing where the load goes, not how much of it there is",
                "Reducing the impact on your body",
                "Preventing injuries",
            ),
            answer=0,
            because=(
                "The load is your bodyweight and your mileage. A different "
                "shoe moves it around, sometimes helpfully, but the way to "
                "have less of it is to run less of it."
            ),
        ),
    ),
)

TRK_IQ_TOPICS: tuple[Topic, ...] = TRK_FUNDAMENTALS + TRK_CORE + TRK_ADVANCED


# ---------------------------------------------------------------------------
# Swimming
#
# The last sport, and the one whose syllabus has the least to say about
# tactics. A swimming race has no opponent to read -- everybody is in their own
# lane looking at a black line -- so what is left is technique sense, pacing,
# and the two things that end more age-group careers than anything else:
# shoulders, and the sheer number of hours.
#
# Nothing here teaches a stroke. That is a pool deck job, done by somebody who
# can see the athlete under the water, and a phone in a garden has no business
# in it.
# ---------------------------------------------------------------------------

SWM_ALL = ("sprint", "distance", "stroke")
SWM_RACE = ("sprint", "distance")

SWM_FUNDAMENTALS: tuple[Topic, ...] = (
    Topic(
        key="swm_iq_streamline",
        title="The fastest you go is off the wall",
        focus="Technique sense",
        positions=SWM_ALL, min_age=0, max_age=200, target_s=70,
        find=(
            "Underwater footage of a push-off held in a tight streamline next "
            "to one that opens up early. The clip is the first five metres, "
            "not the length."
        ),
        ask=Ask(
            prompt="When are you moving fastest in a race?",
            options=(
                "Just after you push off the wall",
                "In the middle of a length",
                "On the finish",
            ),
            answer=0,
            because=(
                "Nothing you do with your arms is as fast as the wall already "
                "made you. Every stroke you take early is you slowing yourself "
                "down on purpose."
            ),
        ),
    ),
    Topic(
        key="swm_iq_shoulder_ache",
        title="A shoulder that aches every session",
        focus="Staying safe",
        positions=SWM_ALL, min_age=0, max_age=200, target_s=72,
        find=(
            "Coaching-education footage on shoulder pain in age-group "
            "swimmers. Material about what to do rather than what it is "
            "called."
        ),
        ask=Ask(
            prompt="Your shoulder has ached at the same point in every session for two weeks. What do you do?",
            options=(
                "Tell an adult, even though you can still swim on it",
                "Swim more with a pull buoy so your legs rest",
                "Stretch it more before practice",
            ),
            answer=0,
            because=(
                "A shoulder that hurts in the same place every time is the one "
                "to have looked at. It is the most common reason a swimmer "
                "stops being a swimmer, and it is very fixable early."
            ),
        ),
    ),
    Topic(
        key="swm_iq_count",
        title="Count your strokes",
        focus="Technique sense",
        positions=SWM_ALL, min_age=0, max_age=200, target_s=68,
        find=(
            "Two swimmers covering a length in the same time, one taking "
            "noticeably fewer strokes. Count them out loud over the clip."
        ),
        ask=Ask(
            prompt="Two swimmers finish a length together, one taking 14 strokes and one taking 20. What does that tell you?",
            options=(
                "The first one is getting more out of each stroke",
                "The first one is faster",
                "The second one is working harder",
            ),
            answer=0,
            because=(
                "Same time, fewer strokes means every pull did more. It is the "
                "single easiest thing to measure about your own swimming and "
                "almost nobody does it."
            ),
        ),
    ),
)

SWM_CORE: tuple[Topic, ...] = (
    Topic(
        key="swm_iq_yardage",
        title="Why the app asks how long you were in the water",
        focus="Training sense",
        positions=SWM_ALL, min_age=13, max_age=200, target_s=128,
        find=(
            "Not footage, a coach going through a training log with a squad, "
            "or a screen recording of one being filled in. The point is what "
            "the log is FOR."
        ),
        ask=Ask(
            prompt="What does logging your pool time in this app get you?",
            options=(
                "Nothing, except a load model that can see your actual week",
                "Points and a longer streak",
                "A place on the leaderboard",
            ),
            answer=0,
            because=(
                "It is worth no XP on purpose. Nothing you type can earn you "
                "anything, which is exactly why the app is willing to believe "
                "it, and why over-stating it only buys you a warning you did "
                "not need."
            ),
        ),
    ),
    Topic(
        key="swm_iq_dryland",
        title="What dryland is actually for",
        focus="Training sense",
        positions=SWM_ALL, min_age=13, max_age=200, target_s=120,
        find=(
            "A dryland session next to the pool session it feeds. Look for "
            "footage where somebody explains what a particular exercise is "
            "protecting."
        ),
        ask=Ask(
            prompt="Why do swimmers do strength work out of the water?",
            options=(
                "So the shoulders can take the yardage the sport asks for",
                "To swim faster straight away",
                "Because there is not enough pool time",
            ),
            answer=0,
            because=(
                "The pull is the point in the water; out of it the point is "
                "everything holding that shoulder together. It is the least "
                "glamorous hour of a swimmer's week and the one that keeps "
                "them in the sport."
            ),
        ),
    ),
    Topic(
        key="swm_iq_pull_buoy",
        title="The pull buoy is not a rest",
        focus="Staying safe",
        positions=SWM_ALL, min_age=13, max_age=200, target_s=118,
        find=(
            "A set done with a pull buoy and paddles, and a coach explaining "
            "what it is doing to the shoulder load. Education material rather "
            "than a training montage."
        ),
        ask=Ask(
            prompt="Your shoulders are sore, so you grab a pull buoy. What have you actually done?",
            options=(
                "Given your legs a rest and your shoulders more work",
                "Given everything a rest",
                "Made the set easier",
            ),
            answer=0,
            because=(
                "The buoy takes the kick away, so the arms do all of it. It is "
                "the most common way a sore shoulder becomes an injured one."
            ),
        ),
    ),
    Topic(
        key="swm_iq_negative_split",
        title="Coming home faster than you went out",
        focus="Racing",
        positions=SWM_RACE, min_age=13, max_age=200, target_s=125,
        find=(
            "A distance race with splits on screen. Compare somebody who goes "
            "out hard and dies with somebody whose second half is quicker."
        ),
        ask=Ask(
            prompt="In a distance race, what should the second half look like?",
            options=(
                "As fast as the first, or faster",
                "Slightly slower, that is normal",
                "Much faster, saving everything for the end",
            ),
            answer=0,
            because=(
                "Going out too fast costs far more later than it gains early. "
                "Nearly every best time anybody swims is evenly paced or "
                "slightly negative."
            ),
        ),
    ),
    Topic(
        key="swm_iq_fuel",
        title="You cannot train on not enough food",
        focus="Staying safe",
        positions=SWM_ALL, min_age=13, max_age=200, target_s=135,
        find=(
            "Sports-dietitian or governing-body education footage aimed at "
            "young swimmers about eating enough to train. Choose material "
            "about fuel and performance, not about weight."
        ),
        ask=Ask(
            prompt="What happens to a swimmer who is not eating enough for their training?",
            options=(
                "They get slower, break more easily and heal more slowly",
                "They get lighter and the water feels easier",
                "Nothing, as long as they feel fine",
            ),
            answer=0,
            because=(
                "Twenty hours a week in the water on too little fuel takes it "
                "out of muscle and bone. It shows up as times that stop "
                "improving long before it feels like anything is wrong."
            ),
        ),
    ),
)

SWM_ADVANCED: tuple[Topic, ...] = (
    Topic(
        key="swm_iq_specialise_late",
        title="Swimming all four strokes for as long as you can",
        focus="Training sense",
        positions=SWM_ALL, min_age=15, max_age=200, target_s=155,
        find=(
            "Coaching-education footage on early specialisation in age-group "
            "swimming. Look for material about what an IM background gives a "
            "swimmer later rather than only warnings."
        ),
        ask=Ask(
            prompt="Why do coaches push young swimmers to keep doing all four strokes?",
            options=(
                "Different strokes load different things, and nobody knows yet what you will be",
                "It makes training more interesting",
                "It is required at meets",
            ),
            answer=0,
            because=(
                "A twelve-year-old specialist is doing one shoulder movement "
                "twenty hours a week, and is usually a specialist because they "
                "grew early rather than because that is their event."
            ),
        ),
    ),
    Topic(
        key="swm_iq_double_days",
        title="Two sessions a day, and what they cost",
        focus="Staying safe",
        positions=SWM_ALL, min_age=15, max_age=200, target_s=150,
        find=(
            "Coaching-education footage on training volume in age-group "
            "swimming. Anything that talks about what the second session of "
            "the day is actually adding."
        ),
        ask=Ask(
            prompt="When does a second session in one day stop being useful?",
            options=(
                "When you are too tired to hold the technique you came for",
                "When you stop enjoying it",
                "It does not, more work is more fitness",
            ),
            answer=0,
            because=(
                "Yardage swum with a stroke falling apart teaches the stroke "
                "that is falling apart. It is the most expensive way there is "
                "to get slower."
            ),
        ),
    ),
    Topic(
        key="swm_iq_taper",
        title="Why the fast weeks are the easy ones",
        focus="Training sense",
        positions=SWM_ALL, min_age=15, max_age=200, target_s=148,
        find=(
            "Coaching-education footage on taper. Look for material that "
            "explains why the work stops before the meet rather than only "
            "that it does."
        ),
        ask=Ask(
            prompt="Why does training volume drop right before a big meet?",
            options=(
                "Because the fitness is already built and the fatigue is not gone",
                "To keep swimmers fresh mentally",
                "Because there is no time left to improve",
            ),
            answer=0,
            because=(
                "Everything you gained in the hard months is sitting under a "
                "layer of tiredness. A taper does not add fitness, it takes "
                "the tiredness off the top of it."
            ),
        ),
    ),
    Topic(
        key="swm_iq_lane_etiquette",
        title="The lane is shared",
        focus="Training sense",
        positions=SWM_ALL, min_age=15, max_age=200, target_s=140,
        find=(
            "A busy lane circle-swimming well, and one where somebody leaves "
            "on the wrong interval and everybody behind them has a worse set."
        ),
        ask=Ask(
            prompt="Somebody faster is right behind you at the wall. What do you do?",
            options=(
                "Let them go first at the next wall",
                "Speed up so they do not catch you",
                "Stay where you are, you were there first",
            ),
            answer=0,
            because=(
                "A lane where nobody moves over is a lane where nobody gets "
                "the set they came for, including you. It costs one push-off "
                "to fix."
            ),
        ),
    ),
)

SWM_IQ_TOPICS: tuple[Topic, ...] = (
    SWM_FUNDAMENTALS + SWM_CORE + SWM_ADVANCED
)


# ---------------------------------------------------------------------------
# Golf
# ---------------------------------------------------------------------------
# Individual sport; one syllabus for everyone. The ideas are the same across
# the age range -- setup, short game, choosing targets, managing the course --
# and the pieces that end more junior careers than anything else are backs and
# overdoing it on the range. Under-11s only see the fundamentals clips.

GOLF_ALL = ("player",)

GOLF_FUNDAMENTALS: tuple[Topic, ...] = (
    Topic(
        key="golf_iq_setup_every_time",
        title="How you stand every time beats how hard you swing",
        focus="Setup",
        positions=GOLF_ALL,
        min_age=0,
        max_age=200,
        target_s=60,
        find=(
            "Side-on footage of a golfer setting up to two different shots, one "
            "where the stance and grip are the same both times, one where they shift "
            "between them. Short clip; the point is the feet, not the swing."
        ),
        ask=Ask(
            prompt="Why do coaches care so much about how you stand before you swing?",
            options=(
                "The same setup is what lets you repeat a shot",
                "It makes the club look longer",
                "It is just a rule to follow",
            ),
            answer=0,
            because=(
                "A shot you only hit once because your feet move every time is a "
                "guess. Repetition is the whole point of practice, and repetition "
                "starts before the club moves."
            ),
        ),
    ),
    Topic(
        key="golf_iq_most_shots_are_short",
        title="Most of your shots are close to the hole",
        focus="Short game",
        positions=GOLF_ALL,
        min_age=0,
        max_age=200,
        target_s=65,
        find=(
            "A round where the short-game shots, chips, pitches, putts, are shown "
            "with a visible count of how many there were. Youth or club footage works; "
            "the point is the count, not the quality."
        ),
        ask=Ask(
            prompt="Where do most of the shots in a round actually happen?",
            options=(
                "Close to the green and on it",
                "From the tee",
                "From the longest part of the course",
            ),
            answer=0,
            because=(
                "A full round has far more short shots than long ones, and that is "
                "true even for good players. The shots that cost you the most are "
                "the ones you do the most, so the ones near the hole are worth the "
                "most practice."
            ),
        ),
    ),
)

GOLF_CORE: tuple[Topic, ...] = (
    Topic(
        key="golf_iq_small_target",
        title="Pick a small target, not a big one",
        focus="Course management",
        positions=GOLF_ALL,
        min_age=13,
        max_age=200,
        target_s=110,
        find=(
            "Footage of a golfer picking a specific landing spot, a tree, a bunker "
            "edge, a patch of fairway, rather than aiming vaguely at the hole. Two "
            "versions: one with a target, one without."
        ),
        ask=Ask(
            prompt="When you have a shot to hit, what should you aim at?",
            options=(
                "A specific, small target you can see",
                "The hole, no matter how far away",
                "Just somewhere in the fairway",
            ),
            answer=0,
            because=(
                "A big target is no target, 'somewhere in the middle' is a guess "
                "before you start. A small target gives you something real to judge "
                "the shot against afterwards."
            ),
        ),
    ),
    Topic(
        key="golf_iq_plan_for_the_miss",
        title="Plan for the shot you will not hit",
        focus="Course management",
        positions=GOLF_ALL,
        min_age=13,
        max_age=200,
        target_s=115,
        find=(
            "A club-selection moment where the player has a safe place to miss, a "
            "wide side of the fairway, a putt rather than a bunker shot. Contrast "
            "with one where the same distance leaves a hazard in play."
        ),
        ask=Ask(
            prompt="Before you choose a club for a shot, what should you have already decided?",
            options=(
                "Where the ball goes if you do not hit it perfectly",
                "The longest club you have in your bag",
                "What your playing partners will think",
            ),
            answer=0,
            because=(
                "You will not hit every shot perfectly. The smart shot is the one "
                "where the miss is still a manageable next shot, not one that turns "
                "a simple hole into two or three extra shots."
            ),
        ),
    ),
    Topic(
        key="golf_iq_distance_first",
        title="How far the ball goes matters more than how straight it goes",
        focus="Club selection",
        positions=GOLF_ALL,
        min_age=13,
        max_age=200,
        target_s=120,
        find=(
            "Footage or a demo of two shots, one that goes the right distance but "
            "curves a little, and one that is dead straight but the wrong distance. "
            "The second one is the worse of the two."
        ),
        ask=Ask(
            prompt="Which is usually the bigger problem on a real hole?",
            options=(
                "The ball going the wrong distance",
                "The ball not going perfectly straight",
                "Both are equally bad",
            ),
            answer=0,
            because=(
                "Golf holes are a series of distances you have to hit, carry over "
                "a bunker, reach a green, leave yourself a putt. A shot that is a "
                "little offline is usually still in play; a shot that is ten yards "
                "short or long often is not."
            ),
        ),
    ),
)

GOLF_ADVANCED: tuple[Topic, ...] = (
    Topic(
        key="golf_iq_when_to_be_aggressive",
        title="Knowing when to be aggressive and when not to be",
        focus="Course management",
        positions=GOLF_ALL,
        min_age=15,
        max_age=200,
        target_s=150,
        find=(
            "A decision point on a course, a forced carry over water, a risky pin "
            "attack, a lay-up on a par five. Two versions: one where the player takes "
            "the shot, one where they play to a safer place."
        ),
        ask=Ask(
            prompt="When should you try to hit a shot through a small gap?",
            options=(
                "When the reward is real and the penalty for missing is something you can recover from",
                "Whenever you feel confident, no matter the risk",
                "Never, you should always play the safe shot",
            ),
            answer=0,
            because=(
                "Aggression is not a mood, it is a calculation. The right aggressive "
                "shot is one where missing still leaves you a playable next shot, "
                "not one where a small mistake costs you the hole."
            ),
        ),
    ),
    Topic(
        key="golf_iq_play_the_course",
        title="Playing the course, not just the shot",
        focus="Course management",
        positions=GOLF_ALL,
        min_age=15,
        max_age=200,
        target_s=155,
        find=(
            "A full hole from tee to green with a smart route, maybe laying up on a "
            "par five, aiming away from a bad bunker, leaving an uphill putt. Wide "
            "enough to show the shape of the hole, not just the swing."
        ),
        ask=Ask(
            prompt="What is good course management?",
            options=(
                "Making each shot set up an easier next shot, even if it means a less exciting play now",
                "Trying to hit every shot as close to the hole as possible",
                "Always playing for the lowest score on the next shot only",
            ),
            answer=0,
            because=(
                "A golf hole is a sequence, not a single shot. The best shot is "
                "often not the one that looks best right now, it is the one that "
                "leaves you an easier shot, or no penalty, on the next one."
            ),
        ),
    ),
    Topic(
        key="golf_iq_up_and_down_first_shot",
        title="Getting up and down starts with the first shot",
        focus="Short game",
        positions=GOLF_ALL,
        min_age=15,
        max_age=200,
        target_s=160,
        find=(
            "A sequence: a chip or pitch to a good position, then a makeable putt. "
            "Contrast with one where the first shot leaves a bad angle or a long "
            "putt. Two or three examples."
        ),
        ask=Ask(
            prompt="What is the first job when your ball is off the green?",
            options=(
                "Get the ball on the green with the right speed, so the next shot is a putt you can make",
                "Get it in the hole in one shot, no matter how risky",
                "Hit it as hard as you can back toward the hole",
            ),
            answer=0,
            because=(
                "An up-and-down is two shots, the chip or pitch, then the putt. "
                "The chip is not about getting it close in one impossible shot; "
                "it is about leaving a putt you can actually make. A simple chip to "
                "a flat putt beats a heroic flop that leaves a three-footer every time."
            ),
        ),
    ),
)

GOLF_IQ_TOPICS: tuple[Topic, ...] = (
    GOLF_FUNDAMENTALS + GOLF_CORE + GOLF_ADVANCED
)


# ---------------------------------------------------------------------------
# Martial arts
# ---------------------------------------------------------------------------
# One syllabus for the whole sport. The same ideas apply whether a kid trains
# karate, taekwondo, judo, jiu-jitsu or something in between. This is a phone-in-
# a-garden curriculum, so it stays on safety, respect, training sense and mindset
# rather than any one style's technique.

MA_ALL = ("practitioner",)

MA_FUNDAMENTALS: tuple[Topic, ...] = (
    Topic(
        key="ma_iq_the_bow_is_a_habit",
        title="The bow is a habit, not a rule for its own sake",
        focus="Etiquette",
        positions=MA_ALL,
        min_age=0,
        max_age=200,
        target_s=60,
        find=(
            "Footage of a class bowing in and out, ideally at the start and end of a "
            "session. Youth or school footage is fine, what matters is that the bow "
            "is visible and repeated, not how fancy it is."
        ),
        ask=Ask(
            prompt="Why does a martial arts class usually start and end with a bow?",
            options=(
                "It is a way of saying \"I am here to learn and to do it safely\"",
                "It is a way of showing who is the best in the room",
                "It is just a rule that has to be done",
            ),
            answer=0,
            because=(
                "The bow is not about rank or who wins, it is about the agreement "
                "a class makes: that everyone here is training, that they will look "
                "out for each other, and that leaving the mat is leaving the room "
                "you were just in."
            ),
        ),
    ),
    Topic(
        key="ma_iq_tap_is_how_you_keep_training",
        title="Tapping is how you stay training, not how you lose",
        focus="Safety",
        positions=MA_ALL,
        min_age=0,
        max_age=200,
        target_s=65,
        find=(
            "Ground-work footage where one person taps and the other lets go straight "
            "away, ideally two takes, one good and one where the release is a beat "
            "late. The second one is the lesson."
        ),
        ask=Ask(
            prompt="When you are caught and you tap, what should your partner do?",
            options=(
                "Let go immediately, every time",
                "Hold on a little longer to teach you something",
                "Ignore it and keep going",
            ),
            answer=0,
            because=(
                "A tap is a stop sign, and it goes both ways. The person applying "
                "the hold is responsible for letting go, and the person tapping is "
                "responsible for tapping early enough that it is still a choice, not "
                "an injury. Both sides of that are what let you come back next session."
            ),
        ),
    ),
    Topic(
        key="ma_iq_gear_is_for_the_work_not_the_look",
        title="The right gear is what lets you train hard safely",
        focus="Staying safe",
        positions=MA_ALL,
        min_age=0,
        max_age=200,
        target_s=70,
        find=(
            "A class where the gear is noticeably right for the activity, mats, "
            "mouthguards, gloves, protective cups, next to one where it is casual. "
            "Ideally the two are shown doing the same drill."
        ),
        ask=Ask(
            prompt="Why do different martial arts need different gear?",
            options=(
                "Because each one asks your body to do different things, and the gear matches the things that can go wrong",
                "Because it is a tradition and every school has to wear the same thing",
                "Because the gear makes you hit harder",
            ),
            answer=0,
            because=(
                "The gear is not costume, it is the answer to whatever the training "
                "is about. Striking needs headgear and mouthguards; throwing needs mats "
                "and a clear space; groundwork needs something for the skin. The right "
                "gear is the one that matches the risk of the session."
            ),
        ),
    ),
    Topic(
        key="ma_iq_getting_thrown_is_part_of_it",
        title="Getting thrown or submitted is part of the lesson",
        focus="Mindset",
        positions=MA_ALL,
        min_age=0,
        max_age=200,
        target_s=72,
        find=(
            "Training footage where a practitioner gets countered or submitted and then "
            "resets, ideally with a brief exchange between partners. The point is the "
            "reset, not the mistake."
        ),
        ask=Ask(
            prompt="What should you take from a session where you got tapped a lot?",
            options=(
                "Which positions and techniques caught you, and what to ask about next time",
                "That you are not good at the sport",
                "That your partner is too strong for you",
            ),
            answer=0,
            because=(
                "Getting caught is not a verdict on you, it is information. Every "
                "tap or throw is a specific thing that happened in a specific position, "
                "and the next session is a chance to ask about that one thing. The "
                "feeling of being outclassed is temporary; the lesson is what stays."
            ),
        ),
    ),
)

MA_CORE: tuple[Topic, ...] = (
    Topic(
        key="ma_iq_training_looks_different_at_sixteen_than_at_eight",
        title="A good training week looks different at sixteen than at eight",
        focus="Training sense",
        positions=MA_ALL,
        min_age=13,
        max_age=200,
        target_s=115,
        find=(
            "A coaching-education clip or a coach going over a training plan with a "
            "class, something about how often a young athlete should train, what they "
            "should and should not be doing, and that more is not always better."
        ),
        ask=Ask(
            prompt="Why does a training plan for a younger athlete look different from one for an older athlete?",
            options=(
                "Because younger bodies are still growing and need rest and variety, not just more training",
                "Because younger athletes cannot learn the technique",
                "Because the sport does not matter until you are older",
            ),
            answer=0,
            because=(
                "A growing body is not a small adult body, it needs recovery, variety, "
                "and time to develop. Training more is not automatically training better, "
                "and overtraining a young athlete is how they stop enjoying it, or get "
                "hurt, long before they have a chance to get good at it."
            ),
        ),
    ),
    Topic(
        key="ma_iq_a_good_opponent_is_your_coach_in_the_room",
        title="A good opponent is the best coach you have in the room",
        focus="Mindset",
        positions=MA_ALL,
        min_age=13,
        max_age=200,
        target_s=120,
        find=(
            "Sparring or randori footage where partners are clearly listening to each "
            "other, helping with a correction, resetting after a good exchange. The "
            "point is the tone of the interaction, not the technique."
        ),
        ask=Ask(
            prompt="When someone gives you a hard fight in training, what is the best way to think about it?",
            options=(
                "They just showed you something real about your game, thank them for it",
                "They are trying to beat you and you should try harder next time",
                "It means you need a different partner",
            ),
            answer=0,
            because=(
                "A training partner who pushes you is giving you the closest thing to "
                "real resistance you will get short of a competition. That is valuable "
                "on its own, and it is also information, about what works, what does "
                "not, and what you need to work on. Treating it as a lesson rather than "
                "a loss is what lets you come back better."
            ),
        ),
    ),
)

MA_ADVANCED: tuple[Topic, ...] = (
    Topic(
        key="ma_iq_competition_is_a_whole_day_problem",
        title="Competition day is a whole-day problem, not a fifteen-minute one",
        focus="Competition sense",
        positions=MA_ALL,
        min_age=15,
        max_age=200,
        target_s=155,
        find=(
            "A coaching-education or athlete-student clip about preparing for a "
            "tournament or grading, what to eat, how to warm up, what to bring, how "
            "to handle being there. Something that treats the day as a day, not just "
            "the match."
        ),
        ask=Ask(
            prompt="What is the biggest mistake people make on a competition day?",
            options=(
                "Treating only the match as the day, and forgetting to eat, warm up, and pace themselves",
                "Turning up too early",
                "Trying too hard to win",
            ),
            answer=0,
            because=(
                "A competition is a long day in a strange place with your adrenaline "
                "on. The people who do well are usually the ones who planned the whole "
                "day, food, warm-up, rest between fights or matches, and not just "
                "the ones who walked on cold and hoped."
            ),
        ),
    ),
    Topic(
        key="ma_iq_good_at_this_is_a_years_thing",
        title="Getting good at this is a years thing, not a months thing",
        focus="Training sense",
        positions=MA_ALL,
        min_age=15,
        max_age=200,
        target_s=145,
        find=(
            "A clip or short piece about how long it takes to develop real skill in a "
            "martial art, belt progressions, the idea that strength and speed come "
            "later, or a coach talking about what they were like when they started."
        ),
        ask=Ask(
            prompt="What is the most realistic way to think about getting good at a martial art?",
            options=(
                "It is a long path, and progress comes in seasons, some fast, some slow, not in a straight line",
                "If you are not improving fast, you are doing it wrong",
                "The goal is to get a belt as quickly as possible",
            ),
            answer=0,
            because=(
                "Real skill is built by showing up over a long time, with bad days and "
                "plateaus and sudden jumps mixed together. Treat it like that and the "
                "slow parts are not a failure, they are the path. Treat it like a race "
                "and you will probably end up somewhere else."
            ),
        ),
    ),
    Topic(
        key="ma_iq_rest_is_part_of_training",
        title="Rest is part of training, even in a sport that rewards showing up",
        focus="Staying safe",
        positions=MA_ALL,
        min_age=15,
        max_age=200,
        target_s=140,
        find=(
            "A coach or athlete talking about rest, recovery, or overtraining, "
            "ideally in a martial-arts context, but any sport where showing up is the "
            "point works too. The idea is the part about recovery being part of it."
        ),
        ask=Ask(
            prompt="Why is rest a real part of training, not the opposite of it?",
            options=(
                "Because the body gets stronger during recovery, and without it the work just stacks up as tiredness and injury",
                "Because there are only so many hours in the day",
                "Because coaches like to tell you to rest",
            ),
            answer=0,
            because=(
                "Training is the thing that asks your body to adapt; rest is the thing "
                "that lets it. Without enough of both, you do not get fitter or better "
                "-- you get tired, then hurt, then stopped. A martial artist who never "
                "rests is not dedicated, they are borrowing against a withdrawal they will "
                "have to make later."
            ),
        ),
    ),
    Topic(
        key="ma_iq_other_sports_help_this_one",
        title="Doing other sports helps you in this one too",
        focus="Training sense",
        positions=MA_ALL,
        min_age=15,
        max_age=200,
        target_s=142,
        find=(
            "A short piece, coaching education, athlete interview, or similar, about "
            "how other kinds of movement (running, gymnastics, swimming, team sports) "
            "help a martial artist. The point is the crossover, not any one sport."
        ),
        ask=Ask(
            prompt="Why can doing another sport make you better at martial arts?",
            options=(
                "Because different sports build different parts of your body and your brain, and a more complete athlete is a better martial artist",
                "Because it means you spend less time on martial arts and that is somehow good",
                "Because coaches want you to do whatever you want",
            ),
            answer=0,
            because=(
                "Martial arts use your whole body and your whole attention, balance, "
                "stamina, coordination, timing. Other sports train pieces of that in "
                "different ways, and a body and mind that are good at more than one thing "
                "usually come into the mat better than one that only ever knows one thing."
            ),
        ),
    ),
)

MA_IQ_TOPICS: tuple[Topic, ...] = (
    MA_FUNDAMENTALS + MA_CORE + MA_ADVANCED
)


# ---------------------------------------------------------------------------
# Rowing
# ---------------------------------------------------------------------------
# One syllabus for a sport whose two career-enders are backs and doing too much too
# young. The same ideas apply across the age range -- clean blade work, sequencing,
# pacing the piece, reading the water -- and the advanced band is where the back and
# volume questions move from abstract to real.

ROW_ALL = ("rower",)

ROW_FUNDAMENTALS: tuple[Topic, ...] = (
    Topic(
        key="row_iq_the_handle_moves_the_boat",
        title="The handle is what moves the boat, the blade is what lets it",
        focus="Technique sense",
        positions=ROW_ALL,
        min_age=0,
        max_age=200,
        target_s=65,
        find=(
            "Footage of a rower from the side, ideally slow motion, where the "
            "blade goes in cleanly, pulls, and comes out cleanly, next to one where "
            "it catches bad or checks out early. The first five strokes of a piece "
            "are often the most readable."
        ),
        ask=Ask(
            prompt="What is the job of the blade in the water?",
            options=(
                "To hold the water so the boat can move past it",
                "To splash as much water as possible",
                "To make the stroke look long",
            ),
            answer=0,
            because=(
                "A rowing stroke is the boat moving away from a blade that is not "
                "moving through the water. A clean catch and a clean finish are what "
                "make that work, the middle is the part everyone watches, but the "
                "two ends are what decide whether it was a good stroke."
            ),
        ),
    ),
    Topic(
        key="row_iq_the_recovery_is_half_the_stroke",
        title="The recovery is what makes the next stroke possible",
        focus="Technique sense",
        positions=ROW_ALL,
        min_age=0,
        max_age=200,
        target_s=68,
        find=(
            "Side-on footage of the recovery, body coming forward before the catch, "
            "sequencing from arms to body to slide. Contrast with a rower diving "
            "head-first into the catch."
        ),
        ask=Ask(
            prompt="What should happen during the recovery?",
            options=(
                "The body should move toward the catch in a controlled sequence, so the next stroke starts ready",
                "You should rush to get back to the catch as fast as possible",
                "Nothing, the recovery is the easy part and does not matter",
            ),
            answer=0,
            because=(
                "A rushed or collapsed recovery gives away the run the drive just "
                "earned and leaves you reaching at the catch. Good recovery is what "
                "lets the drive be good too, it is not rest, it is the other half "
                "of the stroke."
            ),
        ),
    ),
    Topic(
        key="row_iq_the_water_is_heavy",
        title="The water is not something you push through lightly",
        focus="Staying safe",
        positions=ROW_ALL,
        min_age=0,
        max_age=200,
        target_s=70,
        find=(
            "Coaching-education or safety-oriented footage about the physical reality "
            "of the water, capsize recovery, being aware of where you are, and the "
            "difference between a training session on a buoyed stretch and open water."
        ),
        ask=Ask(
            prompt="What is the first thing that changes when you go from a boated session on a river to open water?",
            options=(
                "The environment gets bigger and less forgiving, and the things that keep you safe change with it",
                "Nothing changes if you are a good enough rower",
                "Only the scenery changes",
            ),
            answer=0,
            because=(
                "A buoyed stretch is a controlled place to train. Open water is not, "
                "weather, traffic, and distance all matter more than they do on a "
                "practice course, and the skills that keep you safe on one do not "
                "automatically cover the other."
            ),
        ),
    ),
)

ROW_CORE: tuple[Topic, ...] = (
    Topic(
        key="row_iq_power_is_the_wrong_order",
        title="The power comes from the right order, not from pulling harder",
        focus="Technique sense",
        positions=ROW_ALL,
        min_age=13,
        max_age=200,
        target_s=120,
        find=(
            "Side-on slow motion of a strong clean drive, legs, then body, then arms "
            "in sequence, next to one where the arms and back do too much too early. "
            "Two or three strokes is enough."
        ),
        ask=Ask(
            prompt="Where should the power in a rowing stroke start?",
            options=(
                "With the legs driving, then the body opening, then the arms drawing the handle in",
                "With the arms pulling as hard as possible",
                "With the back leaning back at the catch",
            ),
            answer=0,
            because=(
                "The legs are the biggest muscles and they do the biggest part of the "
                "work first. When the arms or back start too early, the rest of the "
                "stroke is starved of the run they should have had, and the stroke is "
                "slower and harder on the back for it."
            ),
        ),
    ),
    Topic(
        key="row_iq_a_good_catch_is_a_quiet_one",
        title="A good catch is a quiet one",
        focus="Technique sense",
        positions=ROW_ALL,
        min_age=13,
        max_age=200,
        target_s=125,
        find=(
            "Footage of a clean, quiet catch next to one where the blade checks the "
            "boat or splashes. Slow motion is ideal, the catch happens fast and the "
            "difference is small."
        ),
        ask=Ask(
            prompt="What does a bad catch look and feel like?",
            options=(
                "The blade hits the water hard, the boat checks, and the rower loses the run",
                "The blade comes in too late and the stroke is short",
                "A bad catch always splashes a lot",
            ),
            answer=0,
            because=(
                "A catch that is too hard or too early hits the water like a brake, "
                "because the blade is still accelerating when it meets it. A good catch "
                "is one where the blade gets in cleanly and starts working without "
                "stopping the boat, quiet is the sign of that."
            ),
        ),
    ),
    Topic(
        key="row_iq_balance_is_part_of_the_speed",
        title="Both sides of the boat have a job, and they are not the same one",
        focus="Technique sense",
        positions=ROW_ALL,
        min_age=13,
        max_age=200,
        target_s=115,
        find=(
            "Footage from a launch or a camera on the bank showing a four or an eight "
            "where one side is clearly doing something different, over-driving, "
            "checking the boat, rushing, and how it affects the run. A single sculler "
            "works too if the point is about balance."
        ),
        ask=Ask(
            prompt="Why does balance matter so much in rowing?",
            options=(
                "Because the boat runs on the line between the two sides, and anything that tilts it wastes the run",
                "Because it looks better",
                "Because coxes like it",
            ),
            answer=0,
            because=(
                "A rowing boat is a thin thing on a thin thing, and it runs on a line "
                "that is easy to lose. A bad side, a late catch on one side, an uneven "
                "finish, all of it tilts the boat and slows it. Balance is not a "
                "nice-to-have, it is part of the speed."
            ),
        ),
    ),
    Topic(
        key="row_iq_the_first_stroke_is_not_the_fastest",
        title="The first stroke is not the fastest one",
        focus="Training sense",
        positions=ROW_ALL,
        min_age=13,
        max_age=200,
        target_s=118,
        find=(
            "A race or time-trial piece where the first ten strokes are clearly set "
            "rather than thrown, ideally with splits or rate visible. Contrast with "
            "one where the rowers sprint at the start and pay for it."
        ),
        ask=Ask(
            prompt="How should a piece usually start?",
            options=(
                "With a controlled build, getting to race pace rather than starting there",
                "As fast as possible from the first stroke",
                "Slowly, then speeding up later",
            ),
            answer=0,
            because=(
                "The first strokes are where the boat is heaviest and the rowers are "
                "cold. Starting at full speed burns the run you will need later and "
                "usually ends as a sprint that dies. Building into the piece is what "
                "lets the whole piece be fast."
            ),
        ),
    ),
)

ROW_ADVANCED: tuple[Topic, ...] = (
    Topic(
        key="row_iq_the_back_you_keep_is_the_one_you_rowing_with",
        title="The back that carries you through this sport is the one you keep for it",
        focus="Staying safe",
        positions=ROW_ALL,
        min_age=15,
        max_age=200,
        target_s=150,
        find=(
            "Coaching-education or sports-medicine footage about backs in rowing, "
            "core support, sequencing, how much is too much, and what overuse looks "
            "like before it becomes an injury. Something aimed at young rowers."
        ),
        ask=Ask(
            prompt="Why does a rower's back need more attention than most?",
            options=(
                "Because the sport asks the back to do a lot of work, over a lot of strokes, in a position where bad technique and too many hours both show up there first",
                "Because rowers are more likely to have bad backs in general",
                "Because the boat is heavy",
            ),
            answer=0,
            because=(
                "Rowing is a repeated extension under load, and a young rower who rows "
                "too much, rows badly, or rows through the pain that should have been a "
                "warning is the one who ends up stopped. Looking after the back, technique, "
                "core, and sensible volume, is what lets a rowing career last long enough to "
                "mean anything."
            ),
        ),
    ),
    Topic(
        key="row_iq_volume_is_a_recipe_not_a_requirement",
        title="Rowing rewards hours, but hours are what hurt you if you treat them badly",
        focus="Training sense",
        positions=ROW_ALL,
        min_age=15,
        max_age=200,
        target_s=155,
        find=(
            "A coach or sports-medicine clip about training volume in rowing, how much "
            "is appropriate for a young rower, what signs to watch for, and why more is "
            "not automatically better. Ideally aimed at a developing athlete."
        ),
        ask=Ask(
            prompt="What is the real risk of treating rowing like a sport where you just do more every week?",
            options=(
                "You build volume faster than your body can adapt, and the back and the rest of you start shutting down the parts you are overloading",
                "You get better faster, so there is no real risk",
                "The only risk is getting tired",
            ),
            answer=0,
            because=(
                "Rowing is one of the sports where volume is part of what you are training "
                "for, but volume without recovery and without good technique is how "
                "overuse happens. A young rower who treats every week as a chance to add "
                "more is one bad back or one overuse injury away from a season that is "
                "gone."
            ),
        ),
    ),
    Topic(
        key="row_iq_fast_water_is_not_fast_boat",
        title="Fast water is not the same as fast boat",
        focus="Technique sense",
        positions=ROW_ALL,
        min_age=15,
        max_age=200,
        target_s=148,
        find=(
            "Side-on footage of a fast, smooth, well-connected stroke next to one that "
            "looks rushed and hard but does not move the boat as well. Rate and split "
            "visible if possible."
        ),
        ask=Ask(
            prompt="What is the difference between rowing fast and rowing hard?",
            options=(
                "Rowing fast is the boat moving well; rowing hard is the rower working hard, and they are not the same thing",
                "They are the same thing",
                "Rowing hard always makes the boat faster",
            ),
            answer=0,
            because=(
                "You can work very hard and still lose the run of the boat, rushing the "
                "recovery, checking at the catch, breaking the connection. Good rowing is "
                "the thing that makes the boat go fast, not the thing that makes the rower "
                "appear to be trying hardest."
            ),
        ),
    ),
    Topic(
        key="row_iq_the_coxswain_steers_the_boat_and_the_attention",
        title="The coxswain is steering the boat and the crew's attention",
        focus="Team boats",
        positions=ROW_ALL,
        min_age=15,
        max_age=200,
        target_s=140,
        find=(
            "Footage from the coxswain's seat or from a launch following a boat, "
            "showing a cox calling a piece, making a correction, and steering. Ideally "
            "something with a clear call and a clear response."
        ),
        ask=Ask(
            prompt="What is the job of a coxswain in a race?",
            options=(
                "To steer the straightest line, call the race plan, and keep the crew organized and motivated, all of it at once",
                "To yell louder than anyone else",
                "To sit at the back and watch",
            ),
            answer=0,
            because=(
                "A coxswain is not a mascot and not just a voice. A good one sets the "
                "line, runs the race, reads the other boat, and keeps the crew doing the "
                "thing they practiced, all while the boat is moving under them. The "
                "crew can only do their job if the cox is doing theirs."
            ),
        ),
    ),
)

ROW_IQ_TOPICS: tuple[Topic, ...] = (
    ROW_FUNDAMENTALS + ROW_CORE + ROW_ADVANCED
)


BY_SPORT.update({
    "lacrosse": TOPICS,
    "basketball": BKB_TOPICS,
    "volleyball": VB_TOPICS,
    "soccer": SOC_TOPICS,
    "tennis": TEN_TOPICS,
    # One syllabus under two keys. Almost every decision in these games is the
    # same one, and the differences that exist are rules and a pitching motion
    # rather than a different way of thinking about the sport.
    "baseball": BB_IQ_TOPICS,
    "softball": BB_IQ_TOPICS,
    "hockey": HOC_TOPICS,
    # One syllabus under three keys. These sports share the property that
    # matters here -- they are judged on how the movement looks -- and the
    # training sense and the hazards that come with it are the same.
    "gymnastics": JDG_TOPICS,
    "cheer": JDG_TOPICS,
    "dance": JDG_TOPICS,
    "football": FB_IQ_TOPICS,
    "rugby": RUG_IQ_TOPICS,
    # One syllabus under both. A cross country runner and a track distance
    # runner are usually the same child in a different season.
    "track": TRK_IQ_TOPICS,
    "cross_country": TRK_IQ_TOPICS,
    "swimming": SWM_IQ_TOPICS,
    # Individual sports added after the first release. Same shape as the rest --
    # age-banded, position-tagged, with a comprehension question whose answer is
    # the point and a `find` note for the coach holding the scrub bar rather than
    # a fabricated video id.
    "golf": GOLF_IQ_TOPICS,
    "martial_arts": MA_IQ_TOPICS,
    "rowing": ROW_IQ_TOPICS,
})
BY_KEY = {t.key: t for topics in BY_SPORT.values() for t in topics}
