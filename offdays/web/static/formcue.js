// Form cues while a drill is being recorded: "bend your knees a little more", "turn so the phone sees you from the side".
//
// The app already measures a body angle on every frame of a timed hold, and used it only to run or pause the clock. This
// turns the same number into one short instruction at a time, said aloud, because nobody reads a phone during a wall sit.
//
// Two rules it is built around:
//
// * A flat picture cannot tell bad form from a bad camera angle. A wall sit filmed from the front reads as "not sitting"
//   however good it is. So the coach first works out which way the athlete is facing, and only talks about form when
//   it is seeing them from the side. Otherwise the one thing it says is to turn.
// * It uses the clock's own number and the clock's own band (the drill's thresholds), so it can never tell an athlete to
//   bend more while the clock is happily running.
//
// NOT SWITCHED ON FOR ATHLETES. The numbers in FACING and TIMING are reasoned from body proportions and a projected
// skeleton (see tests/js/formcue.test.mjs), not yet checked against real video. The capture screen only uses this with
// ?formcues=1, until it has been run against clips.

import { LANDMARKS } from './counter.js';

const INDEX = Object.fromEntries(LANDMARKS.map((name, i) => [name, i]));
const MIN_VISIBILITY = 0.5;

/**
 * Shoulder width over torso length, as the camera sees them.
 *
 * Shoulders are about 0.78 of a torso wide. Seen from the front that whole width shows; from the side the shoulders line
 * up and it shrinks to nothing, while the torso (vertical) looks the same from anywhere. So the ratio is roughly
 * 0.78 x cos(how far round from front-on the camera is).
 *
 *   at or under SIDE_MAX   the camera is within about 35 degrees of side-on: the knee angle can be trusted
 *   at or over FRONT_MIN   within about 35 degrees of front-on: a wall sit cannot be read at all
 *   in between             readable enough to run the clock, not enough to coach form from
 */
export const FACING = { SIDE_MAX: 0.45, FRONT_MIN: 0.62, SMOOTHING: 0.3 };

export const TIMING = {
  DWELL_MS: 1500,       // a problem has to last this long before anything is said: no cue for a wobble
  SETTLE_MS: 1000,      // back in position this long before "that's it"
  PRAISE_MS: 3000,      // how long "that's it" stays up
  REPEAT_MS: 8000,      // an ignored cue is said again after this long
  MIN_GAP_MS: 4000,     // never two spoken cues closer than this
};

/** The words, per drill. `high` is the measured angle above the drill's band, `low` below it. */
export const FORM_CUES = {
  gen_wall_sit: {
    high: 'Bend your knees a little more. Slide down the wall.',
    low: 'Come up a little. Thighs level with the floor.',
    turn: 'Turn so the phone sees you from the side.',
    good: 'That is it. Hold it there.',
  },
};

function point(landmarks, name) {
  const p = landmarks && landmarks[INDEX[name]];
  if (!p) return null;
  return (p.visibility ?? p.score ?? 1) < MIN_VISIBILITY ? null : p;
}

/**
 * Shoulder width over torso length in this frame, or null when the shoulders and hips are not all in view.
 * `aspect` is the picture's width over its height: landmark x and y are each 0..1 of their own side, so on an upright
 * phone a sideways distance has to be scaled down before it can be compared with an up-and-down one.
 */
export function shoulderRatio(landmarks, aspect = 1) {
  const ls = point(landmarks, 'left_shoulder'), rs = point(landmarks, 'right_shoulder');
  const lh = point(landmarks, 'left_hip'), rh = point(landmarks, 'right_hip');
  if (!ls || !rs || !lh || !rh) return null;
  const dist = (a, b) => Math.hypot((a.x - b.x) * aspect, a.y - b.y);
  const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
  const torso = dist(mid(ls, rs), mid(lh, rh));
  return torso > 0.02 ? dist(ls, rs) / torso : null;
}

/** 'side', 'front' or 'between' for a shoulder ratio; null for no ratio. */
export function viewOf(ratio) {
  if (ratio === null || ratio === undefined) return null;
  if (ratio <= FACING.SIDE_MAX) return 'side';
  return ratio >= FACING.FRONT_MIN ? 'front' : 'between';
}

export class FormCoach {
  /** True when this drill has cues and a band to coach against. */
  static supports(spec) {
    return !!(spec && FORM_CUES[spec.key] && spec.counter
      && Number.isFinite(spec.counter.down_threshold) && Number.isFinite(spec.counter.up_threshold));
  }

  constructor(spec) {
    this.words = FORM_CUES[spec.key];
    this.lo = spec.counter.down_threshold;
    this.hi = spec.counter.up_threshold;
    this.ratio = null;          // smoothed shoulder ratio
    this.want = null;           // what this frame calls for: null (fine), 'turn', 'high' or 'low'
    this.wantSince = 0;
    this.active = null;         // the cue being shown
    this.praiseUntil = 0;
    this.saidAt = -Infinity;    // when anything was last spoken
    this.saidKey = null;
    this.log = [];              // every cue given, for checking against video: { t, key, value, ratio }
  }

  /** What this one frame calls for, before any waiting. */
  _read(value, view) {
    if (value >= this.lo && value <= this.hi) return null;
    // Out of the band. From the side that is the athlete; from anywhere else it may just be the camera.
    if (view === 'side') return value > this.hi ? 'high' : 'low';
    return 'turn';
  }

  /**
   * Feed one frame. `value` is the clock's own smoothed number for the drill (the knee angle), `now` a steadily rising
   * time in ms. Returns the cue to show, `{ key, text, say }`, or null. `say` is true on the frames it should be spoken.
   */
  update({ landmarks, value, aspect = 1, now }) {
    const raw = shoulderRatio(landmarks, aspect);
    if (raw !== null) {
      this.ratio = this.ratio === null ? raw : FACING.SMOOTHING * raw + (1 - FACING.SMOOTHING) * this.ratio;
    }
    // Nothing to judge without the angle or the shoulders. Whatever was showing stays until there is something to go on.
    if (value === null || value === undefined || Number.isNaN(value) || this.ratio === null) {
      return this._show(now, value);
    }
    const want = this._read(value, viewOf(this.ratio));
    if (want !== this.want) { this.want = want; this.wantSince = now; }
    const held = now - this.wantSince;

    if (want === null) {
      if (this.active && held >= TIMING.SETTLE_MS) {
        this.active = null;
        this.praiseUntil = now + TIMING.PRAISE_MS;
        this._note(now, 'good', value);
      }
    } else if (want !== this.active && held >= TIMING.DWELL_MS) {
      this.active = want;
      this.praiseUntil = 0;
      this._note(now, want, value);
    }
    return this._show(now, value);
  }

  _note(now, key, value) {
    this.log.push({ t: Math.round(now), key, value: Math.round(value * 10) / 10, ratio: Math.round(this.ratio * 100) / 100 });
  }

  _show(now) {
    const key = this.active || (now < this.praiseUntil ? 'good' : null);
    if (!key) return null;
    const gap = now - this.saidAt;
    const say = gap >= TIMING.MIN_GAP_MS && (key !== this.saidKey || (key !== 'good' && gap >= TIMING.REPEAT_MS));
    if (say) { this.saidAt = now; this.saidKey = key; }
    return { key, text: this.words[key], say };
  }
}
