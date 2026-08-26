/**
 * On-device rep counting.
 *
 * Consumes MediaPipe Pose landmarks frame by frame and emits rep events. This
 * runs entirely in the athlete's browser -- no frame, image, or landmark ever
 * leaves the device. Only the rep events this module produces are uploaded.
 *
 * The counter is driven by the same DrillSpec JSON the server serves, so the
 * client and server can never disagree about what a rep is.
 *
 * Coordinate note: MediaPipe y increases *downward*. Every height signal below
 * is negated so that "up" is positive, which makes the thresholds in the drill
 * catalog read the way a human would expect.
 */

export const LANDMARKS = [
  'nose', 'left_eye_inner', 'left_eye', 'left_eye_outer', 'right_eye_inner',
  'right_eye', 'right_eye_outer', 'left_ear', 'right_ear', 'mouth_left',
  'mouth_right', 'left_shoulder', 'right_shoulder', 'left_elbow',
  'right_elbow', 'left_wrist', 'right_wrist', 'left_pinky', 'right_pinky',
  'left_index', 'right_index', 'left_thumb', 'right_thumb', 'left_hip',
  'right_hip', 'left_knee', 'right_knee', 'left_ankle', 'right_ankle',
  'left_heel', 'right_heel', 'left_foot_index', 'right_foot_index',
];

const INDEX = Object.fromEntries(LANDMARKS.map((name, i) => [name, i]));

/** Landmarks below this visibility are treated as missing rather than trusted. */
const MIN_VISIBILITY = 0.5;

function lm(landmarks, name) {
  const point = landmarks[INDEX[name]];
  if (!point) return null;
  const vis = point.visibility ?? point.score ?? 1;
  if (vis < MIN_VISIBILITY) return null;
  return { x: point.x, y: point.y, z: point.z ?? 0, v: vis };
}

function midpoint(a, b) {
  if (!a || !b) return a || b || null;
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, v: Math.min(a.v, b.v) };
}

/**
 * Shoulder-to-hip distance, used to normalize every height signal.
 *
 * Without this, the same drill reads completely differently depending on how
 * far the athlete stands from the phone -- which is exactly the variable you
 * cannot control when a 13-year-old props a phone against a water bottle.
 */
function torsoLength(landmarks) {
  const shoulders = midpoint(lm(landmarks, 'left_shoulder'), lm(landmarks, 'right_shoulder'));
  const hips = midpoint(lm(landmarks, 'left_hip'), lm(landmarks, 'right_hip'));
  if (!shoulders || !hips) return null;
  const d = Math.hypot(shoulders.x - hips.x, shoulders.y - hips.y);
  return d > 0.02 ? d : null;
}

/** Interior angle at `b`, in degrees. */
function jointAngle(a, b, c) {
  if (!a || !b || !c) return null;
  const abx = a.x - b.x, aby = a.y - b.y;
  const cbx = c.x - b.x, cby = c.y - b.y;
  const dot = abx * cbx + aby * cby;
  const mag = Math.hypot(abx, aby) * Math.hypot(cbx, cby);
  if (mag === 0) return null;
  return (Math.acos(Math.max(-1, Math.min(1, dot / mag))) * 180) / Math.PI;
}

/**
 * Mirror-aware joint selection.
 *
 * Drill specs name one side (`left_elbow`), but athletes set the phone up
 * however they like and half of them will be facing the other way. When the
 * named side is not visible, fall back to its mirror rather than silently
 * counting nothing -- a drill that reports zero reps because the athlete stood
 * the other way round is a drill nobody uses twice.
 */
function mirror(name) {
  if (name.startsWith('left_')) return `right_${name.slice(5)}`;
  if (name.startsWith('right_')) return `left_${name.slice(6)}`;
  return name;
}

function resolveSided(landmarks, names) {
  const direct = names.map((n) => lm(landmarks, n));
  if (direct.every(Boolean)) return direct;
  const flipped = names.map((n) => lm(landmarks, mirror(n)));
  if (flipped.every(Boolean)) return flipped;
  return null;
}

/** Mean visibility of the landmarks a drill actually depends on. */
export function frameConfidence(landmarks, spec) {
  const names = new Set();
  for (const j of spec.signal.joints || []) names.add(j);
  if (spec.signal.landmark) names.add(spec.signal.landmark);
  if (spec.signal.reference) names.add(spec.signal.reference);
  if (names.size === 0) {
    ['left_shoulder', 'right_shoulder', 'left_hip', 'right_hip'].forEach((n) => names.add(n));
  }
  let sum = 0, n = 0;
  for (const name of names) {
    const p = landmarks[INDEX[name]];
    if (p) { sum += p.visibility ?? p.score ?? 0; n += 1; }
  }
  return n ? sum / n : 0;
}

/**
 * Collapses a frame of landmarks into the single number the drill thresholds
 * against. Returns null when the athlete is not adequately in frame.
 */
export function computeSignal(landmarks, spec) {
  const kind = spec.signal.kind;

  if (kind === 'joint_angle') {
    const pts = resolveSided(landmarks, spec.signal.joints);
    return pts ? jointAngle(pts[0], pts[1], pts[2]) : null;
  }

  if (kind === 'relative_height') {
    const pts = resolveSided(landmarks, [spec.signal.landmark, spec.signal.reference]);
    const torso = torsoLength(landmarks);
    if (!pts || !torso) return null;
    return -(pts[0].y - pts[1].y) / torso;
  }

  if (kind === 'body_height') {
    // Hip height above the lowest visible foot, in torso lengths. Standing is
    // ~1.0, a burpee floor position is near 0.
    const hips = midpoint(lm(landmarks, 'left_hip'), lm(landmarks, 'right_hip'));
    const torso = torsoLength(landmarks);
    if (!hips || !torso) return null;
    const feet = [lm(landmarks, 'left_ankle'), lm(landmarks, 'right_ankle')].filter(Boolean);
    if (!feet.length) return null;
    const ground = Math.max(...feet.map((f) => f.y));
    return (ground - hips.y) / torso;
  }

  if (kind === 'wall_ball_cycle') {
    return wallBallSignal(landmarks);
  }

  return null;
}

/**
 * Wall ball needs its own signal because a single threshold cannot tell a throw
 * from a catch -- both involve the stick moving.
 *
 * What is actually tracked is the *top hand on the stick*: the wrist nearer the
 * head. Through a throw-catch cycle that hand rises above the shoulder line to
 * cock and release, then drops back toward the shoulder to receive. Measuring
 * its height above the shoulder line (in torso lengths) gives a clean
 * oscillation, and whichever wrist is on top at the peak is the hand the rep
 * gets credited to -- which is the whole point for lacrosse.
 */
export function wallBallSignal(landmarks) {
  const lw = lm(landmarks, 'left_wrist');
  const rw = lm(landmarks, 'right_wrist');
  const shoulders = midpoint(lm(landmarks, 'left_shoulder'), lm(landmarks, 'right_shoulder'));
  const torso = torsoLength(landmarks);
  if (!shoulders || !torso || (!lw && !rw)) return null;

  // Smaller y is higher on screen, so the top hand is the min.
  let top = lw, hand = 'left';
  if (!lw || (rw && rw.y < lw.y)) { top = rw; hand = 'right'; }
  if (!top) return null;

  return { value: -(top.y - shoulders.y) / torso, hand };
}

/**
 * Two-threshold state machine converting a signal stream into reps.
 *
 * Hysteresis matters more than it sounds: with a single threshold, a signal
 * hovering at the boundary sprays dozens of phantom reps in a second. The
 * signal must cross *all the way* down and *all the way* back up to count once.
 */
function round3(value) {
  return Math.round(value * 1000) / 1000;
}

export class RepCounter {
  constructor(spec) {
    this.spec = spec;
    this.counter = spec.counter;
    this.smoothing = spec.signal.smoothing ?? 0.35;
    this.reset();
  }

  reset() {
    this.smoothed = null;
    this.armed = false;         // signal has reached the far threshold
    this.lastRepAt = -Infinity;
    this.armedAt = null;
    this.reps = [];
    this.confidenceSum = 0;
    this.confidenceFrames = 0;
    this.holdMs = 0;
    this.lastFrameAt = null;
    this.lastRaw = null;
    this.pendingHand = 'none';
    this.peakValue = null;
    // Per-cycle extremes. The span between them is the rep's range of motion,
    // which is what form quality is measured from -- counting reps throws this
    // away, and it is the more interesting half of the signal.
    //
    // Tracking continues *past* the point the rep fires, because the rep fires
    // when the signal crosses a threshold, not when the movement finishes. A
    // wall-ball throw crosses the firing line on the way up and keeps going;
    // stopping at the crossing would measure every rep as the same minimum
    // span and make range of motion useless for scoring form.
    this.cycleMin = null;
    this.cycleMax = null;
    this.lastRep = null;
  }

  get count() { return this.reps.length; }

  /**
   * Everything needed to diagnose why this drill is or is not counting.
   *
   * A named surface rather than the UI reaching into internals, because a
   * debug panel that reads private fields becomes the reason those fields
   * cannot be renamed. Numbers only -- no landmarks, no frames. What makes
   * this useful is that a rep either crosses two thresholds or it does not,
   * and seeing the signal against those two lines answers the question in a
   * glance where a video would need watching frame by frame.
   */
  get debug() {
    const rising = this.counter.rising_completes !== false;
    const hold = this.spec.metric === 'hold';
    return {
      drill: this.spec.key,
      metric: this.spec.metric,
      signal: this.spec.signal.kind,
      units: this.spec.signal.kind === 'joint_angle' ? 'deg' : 'frame heights',
      raw: this.lastRaw,
      smoothed: this.smoothed,
      smoothing: this.smoothing,
      // The two lines that decide everything. Arm first, then fire.
      armAt: hold ? null : (rising ? this.counter.down_threshold
                                   : this.counter.up_threshold),
      fireAt: hold ? null : (rising ? this.counter.up_threshold
                                    : this.counter.down_threshold),
      rising,
      armed: this.armed,
      count: this.reps.length,
      frames: this.confidenceFrames,
      confidence: this.confidenceFrames
        ? this.confidenceSum / this.confidenceFrames : 0,
      lastRep: this.lastRep
        ? { rom: this.lastRep.rom, cycle_ms: this.lastRep.cycle_ms,
            hand: this.lastRep.hand }
        : null,
      // Excursion of the cycle in progress: if this never spans the gap
      // between the two thresholds, the drill can never fire and the reason
      // is the threshold, not the athlete.
      cycleMin: this.cycleMin,
      cycleMax: this.cycleMax,
    };
  }

  get meanConfidence() {
    return this.confidenceFrames ? this.confidenceSum / this.confidenceFrames : 0;
  }

  handCounts() {
    let left = 0, right = 0;
    for (const r of this.reps) {
      if (r.hand === 'left') left += 1;
      else if (r.hand === 'right') right += 1;
    }
    return { left, right };
  }

  /** Widen the current cycle's excursion to include this sample. */
  extendSpan(value) {
    if (this.cycleMin === null || value < this.cycleMin) this.cycleMin = value;
    if (this.cycleMax === null || value > this.cycleMax) this.cycleMax = value;
  }

  /**
   * Feed one frame. Returns a rep object when this frame completed a rep,
   * otherwise null.
   */
  push(landmarks, tMs) {
    const conf = frameConfidence(landmarks, this.spec);
    this.confidenceSum += conf;
    this.confidenceFrames += 1;

    const raw = computeSignal(landmarks, this.spec);
    const dt = this.lastFrameAt === null ? 0 : tMs - this.lastFrameAt;
    this.lastFrameAt = tMs;
    if (raw === null) return null;

    let value = raw;
    let hand = 'none';
    if (typeof raw === 'object') { value = raw.value; hand = raw.hand; }
    if (value === null || Number.isNaN(value)) return null;
    // Kept for the debug readout: seeing raw against smoothed is how you tell
    // a jittery landmark from a smoothing constant that has flattened the
    // excursion below the threshold.
    this.lastRaw = value;

    // Exponential smoothing. Pose landmarks jitter frame to frame; without
    // this every drill double-counts on the noise alone.
    this.smoothed = this.smoothed === null
      ? value
      : this.smoothing * value + (1 - this.smoothing) * this.smoothed;
    const s = this.smoothed;

    if (this.spec.metric === 'hold') return this._pushHold(s, dt);

    const { down_threshold: down, up_threshold: up, min_rep_ms, max_rep_ms } = this.counter;
    const rising = this.counter.rising_completes !== false;
    const armThreshold = rising ? down : up;
    const fireThreshold = rising ? up : down;
    const reachedArm = rising ? s <= armThreshold : s >= armThreshold;
    const reachedFire = rising ? s >= fireThreshold : s <= fireThreshold;

    if (!this.armed) {
      if (reachedArm) {
        this.armed = true;
        this.armedAt = tMs;
        this.peakValue = s;
        // The excursion restarts here, which is also what finalizes the
        // previous rep's measurement.
        this.cycleMin = s;
        this.cycleMax = s;
        this.pendingHand = hand;
        this.lastRep = null;
      } else if (this.lastRep) {
        // Still following through on the rep just emitted. Extend its span so
        // the peak of the movement is captured, not the threshold crossing.
        this.extendSpan(s);
        this.lastRep.rom = round3(Math.abs(this.cycleMax - this.cycleMin));
        this.lastRep.peak = round3(rising ? this.cycleMax : this.cycleMin);
      }
      return null;
    }

    // Track the full excursion of this cycle, not just the firing direction.
    this.extendSpan(s);

    // Track the extreme of the cycle so handedness is read at the peak of the
    // throw rather than wherever the threshold happened to be crossed.
    if (rising ? s > this.peakValue : s < this.peakValue) {
      this.peakValue = s;
      if (hand !== 'none') this.pendingHand = hand;
    }

    // A cycle that has taken too long is a pause, not a rep.
    if (tMs - this.armedAt > max_rep_ms) {
      this.armed = false;
      this.armedAt = null;
      return null;
    }

    if (reachedFire && tMs - this.lastRepAt >= min_rep_ms) {
      const rom = (this.cycleMax === null || this.cycleMin === null)
        ? null
        : Math.abs(this.cycleMax - this.cycleMin);
      const rep = {
        t_ms: Math.round(tMs),
        hand: this.spec.tracks_handedness ? this.pendingHand : 'none',
        confidence: Math.round(conf * 1000) / 1000,
        // Shape of the rep, for server-side form scoring. Rounded hard: the
        // server only needs the distribution, and full float precision would
        // triple the payload for no gain.
        peak: this.peakValue === null ? null : round3(this.peakValue),
        rom: rom === null ? null : round3(rom),
        cycle_ms: this.armedAt === null ? null : Math.round(tMs - this.armedAt),
      };
      this.reps.push(rep);
      this.lastRepAt = tMs;
      this.armed = false;
      this.armedAt = null;
      this.pendingHand = 'none';
      // Deliberately not clearing the span: the follow-through after this
      // point still belongs to this rep.
      this.lastRep = rep;
      return rep;
    }
    return null;
  }

  /**
   * Hold drills (plank) accumulate time rather than reps, and the clock only
   * runs while the body stays inside the valid band -- so sagging out of
   * position pauses it instead of quietly counting.
   */
  _pushHold(value, dt) {
    const { down_threshold: lo, up_threshold: hi } = this.counter;
    if (value >= lo && value <= hi && dt > 0 && dt < 1000) {
      this.holdMs += dt;
    }
    return null;
  }

  /** The payload posted to /api/sessions/submit. Counts only. */
  toSubmission(sessionId, nonce, durationMs, extra = {}) {
    return {
      session_id: sessionId,
      nonce,
      duration_ms: Math.round(durationMs),
      reps: this.reps,
      hold_ms: Math.round(this.holdMs),
      mean_confidence: Math.round(this.meanConfidence * 1000) / 1000,
      ...extra,
    };
  }
}
