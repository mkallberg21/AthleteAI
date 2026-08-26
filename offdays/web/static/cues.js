/**
 * Deterministic cue sequences for prompted drills.
 *
 * This is a deliberate duplicate of `offdays/cues.py`. The two implementations
 * must produce identical output for identical input, because the browser uses
 * this to decide what to show the athlete and the server uses the Python copy
 * to decide what the athlete was asked for -- and neither ever sends the
 * sequence to the other. That is what makes the targets untamperable, and it
 * only holds while the copies agree.
 *
 * `tests/js/cues.test.mjs` and `tests/test_cues.py` check both against the
 * same golden vectors. Do not edit one without running both suites.
 */

const MASK = 0xffffffff;
export const MAX_CUES = 10000;

/** FNV-1a over the nonce's UTF-8 bytes. */
export function seedOf(nonce) {
  let h = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(nonce)) {
    h = Math.imul(h ^ byte, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

/**
 * mulberry32.
 *
 * `Math.imul` is a signed 32-bit multiply; Python mirrors it with a masked
 * unsigned multiply, which produces the same bits. Every consumer reads bits,
 * so the two agree exactly.
 */
export class Random {
  constructor(seed) {
    this.state = seed >>> 0;
  }

  next() {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1) >>> 0;
    t = (((t + (Math.imul(t ^ (t >>> 7), t | 61) >>> 0)) >>> 0) ^ t) >>> 0;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  below(bound) {
    return Math.floor(this.next() * bound);
  }
}

/** Fisher-Yates, walked downward so Python can mirror it exactly. */
function shuffled(zones, rng) {
  const out = zones.slice();
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = rng.below(i + 1);
    const tmp = out[i];
    out[i] = out[j];
    out[j] = tmp;
  }
  return out;
}

/**
 * The first `count` cues for a session.
 *
 * Drawn in bags -- a shuffled copy of the whole vocabulary, then another --
 * rather than by picking each cue independently, so "every seven cues covers
 * every spot once" is a guarantee. The per-spot breakdown this drill exists to
 * produce is worth nothing if some spot never came up.
 *
 * When two bags would put the same spot at the seam, the incoming bag's first
 * two entries swap. Calling the same spot twice running is not noise to be
 * tolerated: the athlete is already standing there, so the rep measures
 * nothing. The swap cannot create a new collision because entries within a bag
 * are distinct.
 */
export function sequence(nonce, count, zones) {
  if (count <= 0) return [];
  if (count > MAX_CUES) throw new Error(`refusing to generate more than ${MAX_CUES} cues`);
  if (zones.length < 2) throw new Error('a cued drill needs at least two zones');

  const rng = new Random(seedOf(nonce));
  const out = [];
  while (out.length < count) {
    const bag = shuffled(zones, rng);
    if (out.length && bag[0] === out[out.length - 1]) {
      const tmp = bag[0];
      bag[0] = bag[1];
      bag[1] = tmp;
    }
    out.push(...bag);
  }
  return out.slice(0, count);
}

/**
 * How many cues fit in a session of this length. The last cue needs a whole
 * period after it to be answered, so a session ending mid-cue does not record
 * that cue as missed.
 */
export function cueCount(durationMs, leadInMs, periodMs) {
  if (periodMs <= 0) throw new Error('periodMs must be positive');
  const usable = durationMs - leadInMs;
  if (usable < periodMs) return 0;
  return Math.min(Math.floor(usable / periodMs), MAX_CUES);
}

/** When cue `index` appears, in milliseconds from the session start. */
export function cueAt(index, leadInMs, periodMs) {
  return leadInMs + index * periodMs;
}

/**
 * The spot in the words a goalie coach uses.
 *
 * Geometry names the regions neutrally (`low_centre`); a coach says "five
 * hole". And "stick side" is not a fixed direction -- it is whichever side the
 * top hand is on, so the same region has two names depending on who is in the
 * goal. Mirrors `label()` in `offdays/goalie.py`.
 */
const BANDS = { high: 'high', mid: 'hip', low: 'low' };

export function label(zone, topHand) {
  const [band, side] = [zone.split('_')[0], zone.split('_')[1]];
  const word = BANDS[band];
  if (side === 'centre') return band === 'low' ? 'five hole' : `${word} middle`;
  if (topHand === 'left' || topHand === 'right') {
    return `${side === topHand ? 'stick-side' : 'off-stick'} ${word}`;
  }
  return `${side} ${word}`;
}
