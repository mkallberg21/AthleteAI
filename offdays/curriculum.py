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
            "college here -- the calls are louder and clearer."
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
            "feed. Look for one where the defender relaxes after the pass -- "
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
            "A defender closing out on a ball carrier -- one clip where he "
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
            "scoops second. Slow motion helps -- the box-out happens fast and "
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
                "loses the play. Position beats attention -- stand where both "
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
            "audible communication. Wide angle throughout -- a tight shot on "
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
            "The rotation after a slide -- who fills the sliding defender's "
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
                "it is the rotation behind it -- and it has to happen before "
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
            "let it run -- clears are about the shape of five players, not one "
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
            "used as an extra defender -- that is the concept most young "
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
            "wings in frame from the whistle -- most face-off footage cuts "
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
                "leaves somebody genuinely open -- the extra pass is what finds "
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
                "None -- it tries to cover everything",
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
                "Dodge -- you have the ball, so it is your turn",
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
            "built and the age caps apply -- what is missing is somebody who "
            "coaches the sport writing the topics."
        ),
        # Carried on the response a coach reads immediately before going to
        # find footage, which is the only moment this advice can still change
        # what they pick. The same rule is enforced on the way back in.
        "what_to_cut": film.WHAT_TO_CUT,
        "not_this": (
            "Not highlight reels. A montage of finishes teaches nothing while "
            "looking exactly like film study -- it fills the shelf, it earns "
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
            "back. Youth footage is better here -- the mistake is more obvious."
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
                "A passer throws to a target. No target, no pass -- and a late "
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
            "enough to see the helper *before* they move -- the interesting "
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
            "Pause on the frame where the window was actually open -- that is "
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
            "roller before recovering. Cut it wide -- the whole point is what "
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
                "Look up -- you are attacking four against three",
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
            "Two shots from similar spots -- one early in the clock with a "
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
            "better -- the silence is more obvious."
        ),
        ask=Ask(
            prompt="A ball is coming down between you and a teammate. What do you do?",
            options=(
                "Call for it loudly and early, before it gets there",
                "Wait to see if they call it first",
                "Go for it -- whoever gets there first takes it",
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
            "A hit that comes off the block and drops. Cut it wide -- the clip "
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
                "Where it lands -- a seam, a weak passer, or deep in a corner",
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
            "footage helps -- the intent is only visible if you can see the "
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
                "first, read second, move third -- in that order every time."
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
            "centre back. The trigger is the clip -- what happened just before "
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
            "onto it. Cut it wide -- the runner is the clip and they start off "
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
                "Wherever they left somebody unmarked to press with -- usually the far side",
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
                "Pass -- two defenders on you means one is off them",
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


BY_SPORT.update({
    "lacrosse": TOPICS,
    "basketball": BKB_TOPICS,
    "volleyball": VB_TOPICS,
    "soccer": SOC_TOPICS,
})
BY_KEY = {t.key: t for topics in BY_SPORT.values() for t in topics}
