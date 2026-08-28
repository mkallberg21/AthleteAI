"""Reading a calibration set, and refusing to average away where it came from.

Every threshold in the drill catalogue is currently calibrated against a
synthetic textbook rep -- a sine wave driven through the real counter. That
makes each drill self-consistent and says nothing about a thirteen-year-old.
The obvious next step is real footage, and the obvious question about real
footage is where to get it without filming somebody's children.

**Third-party video is genuinely useful and genuinely cannot finish the job**,
and this module is the shape of that distinction.

What a clip of a coach demonstrating a drill on the internet CAN establish:
that the counter fires once per rep, on a real human body, from a camera angle
nobody here chose, against a background nobody here controlled. That is most of
the "does it count at all" question and it is worth a great deal.

What it CANNOT establish is the number the form score depends on. `target_rom`
exists to separate a full rep from a half-hearted one in a tired child. A
demonstration clip is the opposite of that by construction: an adult, rehearsed,
filmed because the rep was good. Calibrating depth against it sets the bar at
somebody's best rep and marks an honest twelve-year-old short -- the mirror of
the failure the synthetic sweeps produce, and no more correct.

So clips are stratified, never pooled. A stratum of demonstration footage can
raise a flag about a drill; only footage of real athletes in real conditions
can settle one. `verdict()` will not certify a drill on demo clips no matter
how many there are, which is the whole point of writing this down as code
rather than as a note in a document nobody re-reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any

#: Where a clip came from. Ordered from least to most like the real thing.
SOURCES: tuple[str, ...] = (
    "third_party_demo",   # a coach or athlete demonstrating, filmed to look good
    "third_party_game",   # match footage: real effort, uncontrolled framing
    "own_adult",          # filmed for this purpose, adult subject
    "own_youth",          # filmed for this purpose, youth subject, with consent
)

#: Conditions the clip was shot in, which is a separate axis from who is in it.
CONDITIONS: tuple[str, ...] = ("studio", "realistic", "poor")

#: Only these can settle a threshold. A demonstration clip is an adult's best
#: rep; a target set against it marks an honest child short.
CERTIFYING_SOURCES: frozenset[str] = frozenset({"own_youth"})

#: And only in conditions the product actually runs in. A youth athlete filmed
#: on a tripod in good light is still not a phone propped on a water bottle.
CERTIFYING_CONDITIONS: frozenset[str] = frozenset({"realistic", "poor"})

#: Below this many clips in a stratum, a median is one athlete's habits.
MIN_CLIPS = 6

#: A counted-to-hand-counted ratio outside this band is a counting problem
#: rather than a threshold problem, and no amount of retuning target_rom fixes
#: it.
RECALL_BAND = (0.95, 1.05)

#: Measured range against the declared target. Same band the synthetic harness
#: uses, so a drill cannot pass one and fail the other on definitions.
RATIO_BAND = (0.85, 1.20)


@dataclass(frozen=True)
class Clip:
    """One video run through the production counter by the bench."""

    drill: str
    source: str
    conditions: str
    counted: int
    truth: int | None = None
    #: Movements that reached the firing threshold and were turned away --
    #: faster than the refractory window allows, or slower than one rep can
    #: be. Without these a sped-up clip is indistinguishable from a broken
    #: counter, and most drill footage on the internet is sped up.
    too_fast: int = 0
    too_slow: int = 0
    median_rom: float | None = None
    target_rom: float | None = None
    band: str = ""
    clip: str = ""
    lost_frames: int = 0
    frames: int = 0

    @property
    def recall(self) -> float | None:
        if not self.truth:
            return None
        return self.counted / self.truth

    @property
    def ratio(self) -> float | None:
        if self.median_rom is None or not self.target_rom:
            return None
        return self.median_rom / self.target_rom

    @property
    def certifying(self) -> bool:
        return (self.source in CERTIFYING_SOURCES
                and self.conditions in CERTIFYING_CONDITIONS)

    @property
    def movements(self) -> int:
        """Everything the counter saw, including what it turned away."""
        return self.counted + self.too_fast + self.too_slow

    @property
    def playback_suspect(self) -> bool:
        """Whether a shortfall is explained by rejections rather than by
        missed movement.

        A clip sped up before it was published produces exactly the shortfall a
        broken counter does. The difference is that the movements were seen and
        refused, which is a fact about the clip and not about the drill.
        """
        if not self.truth or self.counted >= self.truth:
            return False
        rejected = self.too_fast + self.too_slow
        return rejected > 0 and self.movements >= self.truth * RECALL_BAND[0]


@dataclass
class Stratum:
    """Every clip of one drill from one kind of source, in one kind of light."""

    drill: str
    source: str
    conditions: str
    clips: list[Clip] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.clips)

    @property
    def certifying(self) -> bool:
        return bool(self.clips) and self.clips[0].certifying

    def _median(self, attr: str) -> float | None:
        values = [v for v in (getattr(c, attr) for c in self.clips) if v is not None]
        return median(values) if values else None

    @property
    def recall(self) -> float | None:
        return self._median("recall")

    @property
    def ratio(self) -> float | None:
        return self._median("ratio")

    @property
    def suggested_target(self) -> float | None:
        """What target_rom would have to be for this stratum to sit at 1.0."""
        values = [c.median_rom for c in self.clips if c.median_rom is not None]
        return round(median(values), 3) if values else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "drill": self.drill,
            "source": self.source,
            "conditions": self.conditions,
            "clips": self.n,
            "certifying": self.certifying,
            "recall": None if self.recall is None else round(self.recall, 3),
            "ratio": None if self.ratio is None else round(self.ratio, 3),
            "suggested_target_rom": self.suggested_target,
        }


def strata(clips: list[Clip]) -> list[Stratum]:
    """Group clips, and never across a source or a lighting boundary.

    The grouping key is the whole point of this module. Pooling a demo clip
    with a garage clip produces a median that describes neither, and it does it
    silently -- which is worse than having no number, because a number gets
    used.
    """
    out: dict[tuple[str, str, str], Stratum] = {}
    for clip in clips:
        key = (clip.drill, clip.source, clip.conditions)
        out.setdefault(key, Stratum(*key)).clips.append(clip)
    return sorted(out.values(), key=lambda s: (s.drill, s.source, s.conditions))


def verdict(clips: list[Clip], drill_key: str) -> dict[str, Any]:
    """Whether this drill's thresholds can be called measured yet, and why not.

    Deliberately hard to satisfy with borrowed footage. Demonstration clips can
    say a drill is broken; they cannot say one is right.
    """
    mine = [c for c in clips if c.drill == drill_key]
    groups = strata(mine)
    certifying = [s for s in groups if s.certifying and s.n >= MIN_CLIPS]

    # A clip whose shortfall is explained by rejected movements is a clip
    # somebody sped up, not a counter that missed anything. Separating the two
    # matters: pointing an engineer at the counter because a demo video was
    # published at 2x is a day spent fixing code that is correct.
    suspect = [c for c in mine if c.playback_suspect]
    genuine = [c for c in mine if not c.playback_suspect]

    counting_problem = [
        s.to_dict() for s in strata(genuine)
        if s.recall is not None and not (RECALL_BAND[0] <= s.recall <= RECALL_BAND[1])
    ]

    if suspect and not counting_problem:
        return {
            "drill": drill_key,
            "status": "playback_suspect",
            "why": (
                f"{len(suspect)} clip(s) are short on counted reps, but the "
                "movements were seen and turned away rather than missed -- "
                "faster or slower than this drill allows. That is what a clip "
                "published at double speed looks like, which most drill "
                "footage on the internet is. Re-encode at natural speed or "
                "use a different clip; the counter is not the problem."
            ),
            "strata": [s.to_dict() for s in groups],
            "suspect_clips": [c.clip or c.drill for c in suspect],
        }

    if counting_problem:
        return {
            "drill": drill_key,
            "status": "counting_problem",
            "why": (
                "The counter is not finding the same reps a person does. That "
                "is a threshold or a smoothing problem, and retuning the depth "
                "target will not touch it."
            ),
            "strata": [s.to_dict() for s in groups],
            "failing": counting_problem,
        }

    if not certifying:
        have = sum(s.n for s in groups)
        return {
            "drill": drill_key,
            "status": "not_yet_measured",
            "why": (
                f"{have} clip(s) on file, none of them a certifying stratum. "
                f"A threshold is only settled by at least {MIN_CLIPS} clips of "
                "youth athletes in ordinary conditions -- demonstration "
                "footage is an adult's best rep and sets the bar there."
            ),
            "strata": [s.to_dict() for s in groups],
        }

    ratios = [s.ratio for s in certifying if s.ratio is not None]
    if not ratios:
        return {
            "drill": drill_key, "status": "not_yet_measured",
            "why": "No clip in a certifying stratum reported a range of motion.",
            "strata": [s.to_dict() for s in groups],
        }

    worst = min(ratios, key=lambda r: abs(r - 1.0)) if len(ratios) == 1 else median(ratios)
    if RATIO_BAND[0] <= worst <= RATIO_BAND[1]:
        return {
            "drill": drill_key, "status": "measured",
            "why": "Counts match a hand count and the declared range holds.",
            "strata": [s.to_dict() for s in groups],
        }
    suggestion = median([s.suggested_target for s in certifying
                         if s.suggested_target is not None])
    return {
        "drill": drill_key,
        "status": "retune_target_rom",
        "why": (
            f"Counts are right but the declared range is off by {worst:.2f}x. "
            "The target was fitted to a synthetic rep."
        ),
        "suggested_target_rom": round(suggestion, 3),
        "strata": [s.to_dict() for s in groups],
    }


def load(rows: list[dict[str, Any]]) -> list[Clip]:
    """Read the bench's export, ignoring fields it does not need."""
    fields = {f for f in Clip.__dataclass_fields__}
    return [Clip(**{k: v for k, v in row.items() if k in fields}) for row in rows]
