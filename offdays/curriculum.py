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


def catalogue() -> dict[str, Any]:
    """The whole curriculum, for a coach deciding what to film or find."""
    return {
        "sport": "lacrosse",
        "topics": [t.to_dict() for t in TOPICS],
        "count": len(TOPICS),
        "note": (
            "Every topic here is ready except its video. Clip length caps are "
            "enforced per age band, so target_s is already inside the ceiling "
            "for each topic's minimum age."
        ),
        # Carried on the response a coach reads immediately before going to
        # find footage, which is the only moment this advice can still change
        # what they pick. The same rule is enforced on the way back in.
        "what_to_cut": film.WHAT_TO_CUT,
        "not_this": (
            "Not highlight reels. A montage of finishes teaches nothing while "
            "looking exactly like film study -- it fills the shelf, it earns "
            "the same XP, and the athlete comes away having watched somebody "
            "else be good at lacrosse. Clips whose titles read as highlight "
            "reels are refused."
        ),
    }


def install(
    store,
    org_id: int,
    video_ids: dict[str, str],
    *,
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
    for topic in TOPICS:
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
