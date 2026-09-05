"""Short film study: the part of the game that is learned by watching.

Reps build hands. Watching builds the other half -- reading a slide, seeing a
cut two passes early, knowing where the help is coming from. That half is
normally only available to a kid whose coach happens to run film sessions, and
short clips with a coach's voice over them are the cheapest way to give it to
everyone.

Three things shape this module, and none of them is "show more video".

**The clip is not ours and the athlete's browser fetches it.** Nothing is
downloaded, re-hosted, or stripped of its ads: a clip is a provider and an id,
played in the provider's own embedded player, which is what embedding is for.
That is a genuine change of posture from the capture side of this product,
where video never leaves the phone -- here the athlete's browser talks to
YouTube and YouTube knows about it. The privacy-enhanced host is used, the
README says so plainly, and a program that cannot accept that should host its
own clips and use the `link` provider.

**Attention is the thing being measured, not playback.** A tab left running in
the background is not film study, and neither is a muted clip -- the coaching
is in the audio. So a watch is scored on what was audible and focused, and
playback that outruns the wall clock is scrubbing, not watching. The client is
untrusted here exactly as it is for rep counting.

**Minutes are capped hard, by age.** A daily film budget is a screen-time
budget dressed up as training, and it would be very easy for this to become the
thing a kid does for forty minutes because it is easier than going outside.
Clips are capped at a couple of minutes, the daily allowance is single digits
for the youngest, and when it is spent the app says so and stops.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Beats arrive every few seconds. Anything much longer is a tab that was
#: backgrounded or a connection that dropped, and the gap is not credited.
MAX_BEAT_GAP_S = 20.0

#: Playback is allowed to run slightly ahead of the wall clock -- timers drift
#: and beats are not instant -- but not by much. Beyond this it is a seek.
PACING_TOLERANCE = 1.35

#: Above this the athlete is skimming rather than listening. 1.25x is a normal
#: way to watch; 2x is reading the subtitles of a coach's voice.
MAX_CREDITED_RATE = 1.5


@dataclass(frozen=True)
class FilmBand:
    """How much watching is reasonable at an age, and how long a clip can be.

    Much smaller than the physical training budget, and deliberately so. Film
    is cheap to consume and easy to overdo, and a twelve-year-old with twenty
    minutes of video a day has been given homework, not an advantage.
    """

    label: str
    min_age: int
    max_age: int
    clip_max_s: int       # longest single clip that will be shown
    daily_minutes: int    # the whole day's allowance
    daily_clips: int      # a second cap, because clip count is what tires

    def contains(self, age: int) -> bool:
        return self.min_age <= age <= self.max_age

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "clip_max_s": self.clip_max_s,
            "daily_minutes": self.daily_minutes,
            "daily_clips": self.daily_clips,
        }


BANDS: tuple[FilmBand, ...] = (
    FilmBand("Under 11", 0, 10, clip_max_s=75, daily_minutes=4, daily_clips=2),
    FilmBand("11-12", 11, 12, clip_max_s=100, daily_minutes=6, daily_clips=3),
    FilmBand("13-14", 13, 14, clip_max_s=140, daily_minutes=9, daily_clips=4),
    FilmBand("15-16", 15, 16, clip_max_s=170, daily_minutes=12, daily_clips=5),
    FilmBand("17-18", 17, 18, clip_max_s=200, daily_minutes=15, daily_clips=6),
    FilmBand("19 and over", 19, 200, clip_max_s=240, daily_minutes=20, daily_clips=8),
)

#: Unknown or estimated age, same as everywhere else: guess low.
DEFAULT_BAND = BANDS[1]


def band_for(age: int | None, estimated: bool = False) -> FilmBand:
    if age is None or estimated:
        return DEFAULT_BAND
    for band in BANDS:
        if band.contains(age):
            return band
    return BANDS[-1]


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------

PROVIDERS = ("youtube", "link")

#: YouTube ids are a fixed alphabet and length. Validated rather than trusted
#: because this string is interpolated into an embed URL.
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

_YOUTUBE_URL = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})"
)


def parse_youtube_id(raw: str) -> str | None:
    """Pull a video id out of whatever a coach pasted.

    Coaches paste watch links, share links, shorts links, and occasionally a
    bare id. Refusing all but one shape would mean the feature is used once.
    """
    text = (raw or "").strip()
    if _YOUTUBE_ID.match(text):
        return text
    found = _YOUTUBE_URL.search(text)
    return found.group(1) if found else None


def embed_url(provider: str, video_id: str, start_s: int, end_s: int | None) -> str:
    """Where the player points.

    `youtube-nocookie.com` is YouTube's privacy-enhanced host: it does not set
    tracking cookies until playback starts. It is a mitigation, not a fix --
    the request still goes to Google and still comes from a child's browser --
    and the README says so rather than implying this makes it private.
    """
    if provider != "youtube":
        return video_id
    params = [
        f"start={max(0, int(start_s))}",
        "rel=0",            # no "recommended" grid of unrelated video after it
        "modestbranding=1",
        "playsinline=1",
        "enablejsapi=1",    # required to know what was actually watched
    ]
    if end_s:
        params.append(f"end={int(end_s)}")
    return f"https://www.youtube-nocookie.com/embed/{video_id}?" + "&".join(params)


# ---------------------------------------------------------------------------
# Keeping the shelf full of the right thing
# ---------------------------------------------------------------------------

#: What a clip on this shelf is for, in one sentence a coach can act on.
WHAT_TO_CUT = (
    "Cut the two seconds before the play and the two seconds after it. A clip "
    "here should show a decision -- where the slide came from, when the cut "
    "was made, who was left open and why -- not the finish. If the interesting "
    "part is the shot, it is the wrong clip."
)

#: Titles that give away a highlight reel.
#:
#: This is the only check available: nobody here can watch the video, so the
#: coach's own title is the entire evidence. It is a weak signal and a
#: deliberately narrow list -- multi-word phrases rather than single words,
#: because lacrosse is full of terms ("top of the fan", "X", "the crease")
#: that a keen filter would eat.
#:
#: A highlight reel is not a bad video. It is a video that teaches nothing
#: while looking exactly like film study, which is worse: it fills the shelf,
#: it earns the XP, and the athlete comes away having watched somebody else be
#: good at lacrosse for four minutes.
HIGHLIGHT_MARKERS = (
    "highlight", "top 10", "top ten", "top 5", "top five", "best of",
    "best goals", "best plays", "top plays", "mixtape", "mix tape",
    "compilation", "hype", "pump up", "sick shots", "nasty shots",
    "filthy", "insane goals", "crazy goals", "goals of the",
)


def looks_like_highlights(title: str) -> str | None:
    """The marker that gives a title away, or None.

    Matched against the coach's own title rather than anything fetched from the
    provider, so the fix is always within reach: rename it. And if a clip that
    genuinely teaches something cannot be described without calling it a
    highlight reel, the title was the problem to begin with -- that is the text
    the athlete sees above the video.
    """
    low = (title or "").lower()
    for marker in HIGHLIGHT_MARKERS:
        if marker in low:
            return marker
    return None


@dataclass(frozen=True)
class Question:
    """A single check that the clip was understood, not merely played.

    One question, a handful of options, asked after the clip rather than
    before, so it reads as a coach turning round and asking rather than a quiz
    the athlete is being graded on. Getting it wrong costs nothing.
    """

    prompt: str
    options: tuple[str, ...]
    answer: int
    because: str = ""

    def to_dict(self, include_answer: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {"prompt": self.prompt, "options": list(self.options)}
        if include_answer:
            out["answer"] = self.answer
            out["because"] = self.because
        return out


@dataclass
class Clip:
    id: int
    org_id: int
    provider: str
    video_id: str
    title: str
    #: What to watch for. The difference between film study and watching telly.
    focus: str
    start_s: int = 0
    end_s: int | None = None
    positions: tuple[str, ...] = ()
    min_age: int = 0
    max_age: int = 200
    question: Question | None = None
    active: bool = True

    @property
    def length_s(self) -> int:
        if self.end_s is None:
            return 0
        return max(0, self.end_s - self.start_s)

    def suits(self, age: int | None, band: FilmBand) -> bool:
        if self.length_s and self.length_s > band.clip_max_s:
            return False
        if age is None:
            return True
        return self.min_age <= age <= self.max_age

    def to_dict(self, include_answer: bool = False) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "video_id": self.video_id,
            "title": self.title,
            "focus": self.focus,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "length_s": self.length_s,
            "positions": list(self.positions),
            "min_age": self.min_age,
            "max_age": self.max_age,
            "embed_url": embed_url(self.provider, self.video_id, self.start_s, self.end_s),
            "question": self.question.to_dict(include_answer) if self.question else None,
        }


# ---------------------------------------------------------------------------
# Did they actually watch it?
# ---------------------------------------------------------------------------

class Verdict:
    WATCHED = "watched"        # saw it, heard it, at a human speed
    PARTIAL = "partial"        # stopped early
    SKIMMED = "skimmed"        # covered the clip, but scrubbed or raced it
    BACKGROUND = "background"  # played to an empty room, or muted


@dataclass
class WatchState:
    """Running totals for one athlete watching one clip.

    Kept as a pure value updated by `apply_beat` so the integrity rules can be
    tested without a database or a browser, the same way the rep counter's
    thresholds are.
    """

    length_s: int
    position_s: float = 0.0
    watched_s: float = 0.0
    audible_s: float = 0.0
    focused_s: float = 0.0
    wall_s: float = 0.0
    seeks: int = 0
    max_rate: float = 1.0
    #: Which whole seconds of the clip have been seen, so that rewatching the
    #: first ten seconds forty times does not read as having watched it.
    seen: set[int] = field(default_factory=set)

    @property
    def coverage(self) -> float:
        if not self.length_s:
            return 0.0
        return min(1.0, len(self.seen) / self.length_s)

    @property
    def audible_share(self) -> float:
        return self.audible_s / self.watched_s if self.watched_s else 0.0

    @property
    def focused_share(self) -> float:
        return self.focused_s / self.watched_s if self.watched_s else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "position_s": round(self.position_s, 1),
            "watched_s": round(self.watched_s, 1),
            "coverage": round(self.coverage, 3),
            "audible_share": round(self.audible_share, 3),
            "focused_share": round(self.focused_share, 3),
            "seeks": self.seeks,
            "max_rate": round(self.max_rate, 2),
        }


def apply_beat(
    state: WatchState,
    position_s: float,
    wall_gap_s: float,
    *,
    muted: bool = False,
    hidden: bool = False,
    rate: float = 1.0,
) -> WatchState:
    """Fold one heartbeat into a watch.

    The only thing credited is playback that advanced no faster than the wall
    clock allows. A position that jumps forward is a seek and earns nothing;
    time while the tab is hidden or the sound is off is recorded but does not
    count toward having listened to it.
    """
    state.max_rate = max(state.max_rate, float(rate or 1.0))

    # A gap this long means the tab was suspended or the network dropped. The
    # position may be honest, but nobody was watching for most of it.
    gap = min(max(0.0, wall_gap_s), MAX_BEAT_GAP_S)
    state.wall_s += gap

    advance = float(position_s) - state.position_s
    allowed = gap * max(1.0, float(rate or 1.0)) * PACING_TOLERANCE

    if advance < 0 or advance > allowed:
        # Backwards is a rewind, too-far-forward is a skip. Both are seeks;
        # neither is time spent watching.
        state.seeks += 1
    elif advance > 0:
        state.watched_s += advance
        if not muted:
            state.audible_s += advance
        if not hidden:
            state.focused_s += advance
        for second in range(int(state.position_s), int(position_s)):
            state.seen.add(second)

    state.position_s = max(0.0, float(position_s))
    return state


def assess(state: WatchState) -> str:
    """What this watch amounts to.

    Ordered so the least flattering true answer wins: a clip that was covered
    but muted is `background`, not `watched`, because the coaching is in the
    audio and a silent clip is a moving picture.
    """
    if state.coverage < 0.85:
        return Verdict.PARTIAL
    if state.max_rate > MAX_CREDITED_RATE or state.seeks > max(2, state.length_s // 30):
        return Verdict.SKIMMED
    if state.audible_share < 0.75 or state.focused_share < 0.75:
        return Verdict.BACKGROUND
    return Verdict.WATCHED


#: XP is small and capped, and it is the same whether the answer was right. The
#: reward is for turning up and paying attention, which is the behaviour worth
#: building; being wrong about a slide is the entire reason to watch film.
XP_PER_WATCH = 12
XP_DAILY_CAP = 40


@dataclass
class DayState:
    """An athlete's film day, against the allowance for their age."""

    band: FilmBand
    minutes: float = 0.0
    clips: int = 0

    @property
    def minutes_left(self) -> float:
        return max(0.0, self.band.daily_minutes - self.minutes)

    @property
    def clips_left(self) -> int:
        return max(0, self.band.daily_clips - self.clips)

    @property
    def spent(self) -> bool:
        return self.minutes_left <= 0 or self.clips_left <= 0

    def message(self) -> str:
        if self.spent:
            return (
                "That is your film for today. It is meant to be a few minutes, "
                "not an evening, because the rest of the learning happens with a stick "
                "in your hands and in actual games."
            )
        if self.clips == 0:
            return (
                f"A couple of clips is plenty: about {self.band.daily_minutes} "
                "minutes a day at your age. Watch, listen, then go and play."
            )
        return (
            f"{self.clips_left} left in today's allowance"
            f"{'' if self.clips_left == 1 else ''}. No need to use them."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "band": self.band.to_dict(),
            "minutes": round(self.minutes, 1),
            "minutes_left": round(self.minutes_left, 1),
            "clips": self.clips,
            "clips_left": self.clips_left,
            "spent": self.spent,
            "message": self.message(),
        }
