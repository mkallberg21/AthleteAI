"""Deterministic cue sequences for prompted drills.

Every drill shipped before this one is *self-paced*: the athlete decides when
the next rep happens, and the app's only job is to notice that it did. A goalie
drill cannot work that way. What a goalie actually does is react to a spot
somebody else picked, so the app has to pick the spot -- and the moment the app
picks it, two new problems appear that no other drill has.

The first is fairness. If the sequence were random per device, two athletes on
the same team would face different drills and their numbers would not compare.

The second is trust. Reaction time is measured from the moment the cue appeared,
and if the client both chooses that moment and reports the elapsed time, the
client is grading its own homework.

Both go away if the sequence is a pure function of the session nonce, which the
*server* issues at session start:

  * the browser derives the sequence in order to display it,
  * the server derives the identical sequence in order to mark it,
  * neither one sends the sequence to the other, so there is nothing to tamper
    with in transit,
  * and because cues fire on a fixed cadence, the server knows what time every
    cue appeared without being told.

A hostile client can still lie about where the hands went. That is true of
every count in this system and is what the integrity layer is for. What it
cannot do is invent a friendlier set of targets after the fact.

The generator is duplicated in `static/cues.js`, and `tests/test_cues.py` and
`tests/js/cues.test.mjs` check both against the same golden vectors. Those
vectors are the only thing keeping the two halves honest, so do not edit one
implementation without running both suites.
"""

from __future__ import annotations

MASK = 0xFFFF_FFFF

# Largest sequence anyone can ask for. A cue every couple of seconds for an
# hour is well under this; the bound exists so a malformed period cannot turn
# a request into an unbounded loop.
MAX_CUES = 10_000


def seed_of(nonce: str) -> int:
    """FNV-1a over the nonce's UTF-8 bytes.

    Chosen because it is four lines in both languages and needs no dependency.
    Nothing here is security-sensitive: the nonce is already unguessable, and
    this only has to spread it evenly over the zone vocabulary.
    """
    h = 0x811C_9DC5
    for byte in nonce.encode("utf-8"):
        h = ((h ^ byte) * 0x0100_0193) & MASK
    return h


class Random:
    """mulberry32, transcribed so it matches JavaScript bit for bit.

    Every intermediate is masked to 32 bits. JavaScript's `Math.imul` is a
    *signed* 32-bit multiply, but the bits it produces are identical to an
    unsigned masked multiply, and everything downstream reads bits rather than
    magnitude -- so masking is both sufficient and the form that survives being
    read side by side with `cues.js`.
    """

    __slots__ = ("state",)

    def __init__(self, seed: int) -> None:
        self.state = seed & MASK

    def next(self) -> float:
        """The next value in [0, 1)."""
        self.state = (self.state + 0x6D2B_79F5) & MASK
        t = self.state
        t = (((t ^ (t >> 15)) & MASK) * (t | 1)) & MASK
        t = ((t + ((((t ^ (t >> 7)) & MASK) * (t | 61)) & MASK)) & MASK) ^ t
        return ((t ^ (t >> 14)) & MASK) / 4_294_967_296.0

    def below(self, bound: int) -> int:
        """A whole number in [0, bound)."""
        return int(self.next() * bound)


def _shuffled(zones: tuple[str, ...], rng: Random) -> list[str]:
    """Fisher-Yates, walked downward so JavaScript can mirror it exactly."""
    out = list(zones)
    for i in range(len(out) - 1, 0, -1):
        j = rng.below(i + 1)
        out[i], out[j] = out[j], out[i]
    return out


def sequence(nonce: str, count: int, zones: tuple[str, ...]) -> list[str]:
    """The first `count` cues for a session.

    Drawn in *bags* -- a shuffled copy of the whole zone vocabulary, then
    another -- rather than by picking each cue independently. Independent picks
    would leave a real chance that some spot never came up at all in a short
    session, and the per-zone breakdown this drill exists to produce is worth
    nothing if the zones were not sampled evenly. Bags make "every seven cues
    covers every spot once" a guarantee instead of an expectation.

    Two adjacent bags can still put the same spot at the seam. That is not
    random noise to be tolerated, it is a defective cue: the athlete is already
    standing there, so the rep measures nothing. When it happens the bag's
    first two entries swap, which cannot introduce a new collision because the
    entries within a bag are distinct.
    """
    if count <= 0:
        return []
    if count > MAX_CUES:
        raise ValueError(f"refusing to generate more than {MAX_CUES} cues")
    if len(zones) < 2:
        raise ValueError("a cued drill needs at least two zones to choose between")

    rng = Random(seed_of(nonce))
    out: list[str] = []
    while len(out) < count:
        bag = _shuffled(zones, rng)
        if out and bag[0] == out[-1]:
            bag[0], bag[1] = bag[1], bag[0]
        out.extend(bag)
    return out[:count]


def cue_count(duration_ms: int, lead_in_ms: int, period_ms: int) -> int:
    """How many cues fit in a session of this length.

    The last cue needs a whole period after it for the athlete to answer, so a
    session that ends mid-cue does not count that cue as missed.
    """
    if period_ms <= 0:
        raise ValueError("period_ms must be positive")
    usable = duration_ms - lead_in_ms
    if usable < period_ms:
        return 0
    return min(usable // period_ms, MAX_CUES)


def cue_at(index: int, lead_in_ms: int, period_ms: int) -> int:
    """When cue `index` appeared, in milliseconds from the session start."""
    return lead_in_ms + index * period_ms
