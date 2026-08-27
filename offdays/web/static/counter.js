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
  // A reach drill names no landmarks in its spec, but the wrists are what it
  // is actually measuring -- and on a cued drill they also decide the zone, so
  // a frame that has lost them is worth much less than the shoulder-only
  // fallback would suggest.
  if (spec.signal.kind === 'save_reach' || spec.signal.kind === 'hand_sweep') {
    ['left_wrist', 'right_wrist'].forEach((n) => names.add(n));
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

  if (kind === 'shooting_arm') {
    return shootingArmSignal(landmarks);
  }

  if (kind === 'stance_width') {
    return stanceWidthSignal(landmarks);
  }

  if (kind === 'save_reach') {
    return saveReachSignal(landmarks);
  }

  if (kind === 'hand_sweep') {
    return handSweepSignal(landmarks);
  }

  if (kind === 'wall_ball_cycle') {
    return wallBallSignal(landmarks);
  }

  return null;
}

/** Which arm is shooting this frame: the one whose wrist is higher. */
function shootingSide(landmarks) {
  const lw = lm(landmarks, 'left_wrist');
  const rw = lm(landmarks, 'right_wrist');
  if (!lw && !rw) return null;
  // Smaller y is higher on screen.
  if (!lw) return 'right';
  if (!rw) return 'left';
  return rw.y < lw.y ? 'right' : 'left';
}

/**
 * Elbow angle of whichever arm is actually shooting.
 *
 * A plain joint_angle names one side in the spec and only swaps when that side
 * leaves the frame, so a left-handed shooter with both arms visible would be
 * measured on the arm that is not shooting. Handedness cannot live in the spec
 * either -- one record is shared by every athlete. Picking the arm from the
 * frame, by whichever wrist is higher, is the only version of this that works
 * for a lefty, and it records which hand shot as a side effect.
 */
export function shootingArmSignal(landmarks) {
  const side = shootingSide(landmarks);
  if (!side) return null;
  const pts = [
    lm(landmarks, `${side}_shoulder`),
    lm(landmarks, `${side}_elbow`),
    lm(landmarks, `${side}_wrist`),
  ];
  if (!pts.every(Boolean)) return null;
  const angle = jointAngle(pts[0], pts[1], pts[2]);
  return angle === null ? null : { value: angle, hand: side };
}

/**
 * How far the shooting elbow sits out to the side of the wrist, in torso
 * lengths.
 *
 * "Elbow under the ball" is the first thing any shooting coach says, and this
 * is what it means geometrically: at release the elbow should be beneath the
 * wrist rather than flared out. Measured along the shoulder axis so it does not
 * matter which way the athlete faces, and as a magnitude because a flare is a
 * flare whichever side it goes.
 *
 * Null when the athlete is side-on -- from there the elbow is behind the wrist
 * rather than beside it, and the projection would report a perfect shot for
 * any shot at all.
 */
export function elbowFlare(landmarks) {
  const side = shootingSide(landmarks);
  if (!side) return null;
  const ls = lm(landmarks, 'left_shoulder');
  const rs = lm(landmarks, 'right_shoulder');
  const elbow = lm(landmarks, `${side}_elbow`);
  const wrist = lm(landmarks, `${side}_wrist`);
  const torso = torsoLength(landmarks);
  if (!ls || !rs || !elbow || !wrist || !torso) return null;

  const ax = rs.x - ls.x;
  const ay = rs.y - ls.y;
  const span = Math.hypot(ax, ay);
  if (span < 0.35 * torso) return null;

  const offset = ((elbow.x - wrist.x) * ax + (elbow.y - wrist.y) * ay) / span / torso;
  return Math.abs(offset);
}

/**
 * How far apart the feet are, along the athlete's own left-right axis, in
 * torso lengths.
 *
 * The first horizontal signal in this file. Everything else measures a height
 * or an angle, which is the whole reason a defensive slide -- the most common
 * footwork in basketball, tennis, soccer defending and goaltending -- had no
 * drill in any sport.
 *
 * Measured along the shoulder axis rather than the picture's x, so it does not
 * matter which way the athlete faces or how square they are to the phone. And
 * it is SIGNED, which is the point: a shuffle keeps the feet apart and the
 * value stays positive, and the moment the feet cross the ankles swap sides of
 * the axis and it goes negative. That is the one error every defensive coach
 * spends a season shouting about, and this is the only thing here that sees it.
 *
 * Returns null rather than a guess when the athlete is side-on. The shoulder
 * axis collapses in that view, and a projection onto a collapsed axis reports
 * a crossed step for a perfectly good one.
 */
export function stanceWidthSignal(landmarks) {
  const ls = lm(landmarks, 'left_shoulder');
  const rs = lm(landmarks, 'right_shoulder');
  const la = lm(landmarks, 'left_ankle');
  const ra = lm(landmarks, 'right_ankle');
  const torso = torsoLength(landmarks);
  if (!ls || !rs || !la || !ra || !torso) return null;

  // Unit vector along the shoulders, pointing to the athlete's right.
  const ax = rs.x - ls.x;
  const ay = rs.y - ls.y;
  const span = Math.hypot(ax, ay);
  if (span < 0.35 * torso) return null;

  const value = ((ra.x - la.x) * ax + (ra.y - la.y) * ay) / span / torso;
  // Which foot is leading, for drills that care which way the athlete slid.
  return { value, hand: value >= 0 ? 'right' : 'left' };
}

/**
 * Which side of the body the hands are on -- in torso lengths, signed.
 *
 * The horizontal companion to `saveReachSignal`. Reach asks how far the hands
 * left the chest; this asks which way they went. Everything a hockey stick
 * does off the ice is that question: stickhandling is the hands crossing the
 * body and coming back, and a wrist shot is the same crossing done once,
 * slowly and hard. None of it moves the hands up or down enough for a height
 * signal to see, which is why the sport had no skill drill anywhere.
 *
 * Projected onto the shoulder axis rather than read off the picture's x, so
 * the numbers are the athlete's own left and right however they are stood, and
 * null rather than a guess when that axis has collapsed -- side-on, a sweep to
 * the forehand and a sweep to the backhand project onto the same tiny span and
 * the drill would count a player waving the stick in one place.
 *
 * Taken from the MIDPOINT of the wrists and null unless both are visible.
 * A stick is held in two hands. The single-wrist version of this paid a
 * one-handed reach exactly what it paid a real handle, and taking the midpoint
 * fixes that arithmetically rather than by detecting it: reach out with one
 * hand and the midpoint travels half as far, which does not clear the
 * threshold, so the rep simply is not there.
 *
 * Returns a bare number rather than a {value, hand} pair on purpose. The sign
 * IS the side, and a rep fires at the positive extreme every time, so a `hand`
 * read at that extreme would say "right" for every rep ever counted -- and,
 * because handed reps carry an off-hand premium, would have paid it on all of
 * them. Which side came up short is recovered afterwards from `peak` and
 * `rom`, which are already on every rep.
 */
export function handSweepSignal(landmarks) {
  const ls = lm(landmarks, 'left_shoulder');
  const rs = lm(landmarks, 'right_shoulder');
  const lw = lm(landmarks, 'left_wrist');
  const rw = lm(landmarks, 'right_wrist');
  const torso = torsoLength(landmarks);
  if (!ls || !rs || !lw || !rw || !torso) return null;

  // Unit vector along the shoulders, pointing to the athlete's right.
  const ax = rs.x - ls.x;
  const ay = rs.y - ls.y;
  const span = Math.hypot(ax, ay);
  if (span < 0.35 * torso) return null;

  const hands = midpoint(lw, rw);
  const chest = midpoint(ls, rs);
  return ((hands.x - chest.x) * ax + (hands.y - chest.y) * ay) / span / torso;
}

/**
 * How far the hands, together, are from the chest -- in torso lengths.
 *
 * Cued drills send the athlete somewhere different every rep, which breaks
 * every height signal in this file: a high save drives the hands up and a low
 * save drives them down, so no single pair of thresholds counts both. Reach
 * does not care which way the hands went -- it rises when they leave the ready
 * position and falls when they come back, whatever the target was.
 *
 * Measured from the MIDPOINT of the two wrists, and null unless both are
 * visible. That is the whole two-handed requirement, and it is deliberately
 * expressed as a measurement rather than as a rule that rejects reps.
 *
 * A goalie makes saves with both hands on the stick. Throwing one arm at the
 * ball is the habit every goalie coach spends the season removing, and the
 * first version of this signal took whichever wrist was further out -- so it
 * paid a one-armed flail exactly the same as a proper save, and paid it at
 * full marks.
 *
 * Using the midpoint fixes that arithmetically: reach out with one hand and
 * the midpoint travels half as far, which does not clear the firing threshold,
 * so the rep simply does not count. Nothing has to detect "that was
 * one-handed" and argue about it.
 */
export function saveReachSignal(landmarks) {
  const lw = lm(landmarks, 'left_wrist');
  const rw = lm(landmarks, 'right_wrist');
  const shoulders = midpoint(lm(landmarks, 'left_shoulder'), lm(landmarks, 'right_shoulder'));
  const torso = torsoLength(landmarks);
  // Both hands, or nothing. One wrist out of frame is not a save this drill
  // is willing to score.
  if (!shoulders || !torso || !lw || !rw) return null;

  const hands = midpoint(lw, rw);
  const value = Math.hypot(hands.x - shoulders.x, hands.y - shoulders.y) / torso;

  // Which hand led is still worth recording -- it is the top hand on the
  // stick, and it is what the off-hand accounting reads.
  const reach = (w) => Math.hypot(w.x - shoulders.x, w.y - shoulders.y);
  return { value, hand: reach(rw) > reach(lw) ? 'right' : 'left' };
}

/**
 * Which of the nine cells the hands are in.
 *
 * Reach counts the rep; this recovers the direction the rep went, which on a
 * cued drill is the entire point. Read at the extreme of the movement rather
 * than at the threshold crossing, so it reports where the hands *arrived*
 * rather than where they were passing through.
 *
 * Sides are anatomical -- the athlete's own left and right -- rather than
 * left and right of the picture, so it does not matter which way they face.
 * That is done by projecting onto the shoulder axis instead of using raw x.
 * Returns 'unknown' rather than a guess whenever the geometry cannot support
 * an answer: an unreadable rep and a wrong rep are different facts about the
 * athlete and the scorer keeps them apart.
 */
export function saveZone(landmarks, cues) {
  if (!cues) return null;
  const ls = lm(landmarks, 'left_shoulder');
  const rs = lm(landmarks, 'right_shoulder');
  const lw = lm(landmarks, 'left_wrist');
  const rw = lm(landmarks, 'right_wrist');
  const torso = torsoLength(landmarks);
  if (!ls || !rs || !torso || (!lw && !rw)) return 'unknown';

  const shoulders = midpoint(ls, rs);
  const reach = (w) => (w ? Math.hypot(w.x - shoulders.x, w.y - shoulders.y) : -Infinity);
  const w = reach(rw) > reach(lw) ? rw : lw;
  if (!w) return 'unknown';

  // Height above the shoulder line. Hips sit about one torso below, so a
  // hand at knee height reads around -1.5.
  const v = -(w.y - shoulders.y) / torso;
  const band = v >= cues.high_above ? 'high' : v <= cues.low_below ? 'low' : 'mid';

  // Shoulder axis, pointing toward the athlete's right.
  const ax = rs.x - ls.x;
  const ay = rs.y - ls.y;
  const span = Math.hypot(ax, ay);
  // Turned side-on, the shoulders collapse onto each other and this projection
  // stops meaning anything. Better to say the rep was unreadable than to call
  // a stick-side save an off-stick one.
  if (span < 0.35 * torso) return 'unknown';
  const h = ((w.x - shoulders.x) * ax + (w.y - shoulders.y) * ay) / span / torso;
  const side = h >= cues.side_beyond ? 'right' : h <= -cues.side_beyond ? 'left' : 'centre';

  return `${band}_${side}`;
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
    // Where the hands were at the furthest point of the cycle, and the raw
    // reading that furthest point was. Only tracked on cued drills, where the
    // direction the rep went is the measurement rather than a detail.
    //
    // Tracked against the RAW signal on purpose. Smoothing lags by a few
    // frames, so the smoothed peak arrives after the hands have already turned
    // around and started back -- following it files a low save as a hip save,
    // every time, because the hip is where the hands were when the smoothed
    // value finally caught up.
    this.pendingZone = null;
    this.pendingRawPeak = null;
    // Stance-width drills only: whether the feet crossed at any point during
    // this rep. A signed signal makes this free to detect -- crossing is the
    // value going negative -- and it is the one thing a defensive coach
    // actually wants to know.
    this.pendingCrossed = false;
    // Shooting drills only: how far the elbow sat out from the wrist at the
    // moment of release. Captured at the extreme rather than at the threshold
    // crossing, because release is the top of the extension and the threshold
    // is somewhere on the way there.
    this.pendingFlare = null;
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
    // Only computed on cued drills. Everywhere else it is dead weight on
    // every frame, and `saveZone` returns null so nothing downstream fires.
    const zone = this.spec.cues ? saveZone(landmarks, this.spec.cues) : null;
    const flare = this.spec.signal.kind === 'shooting_arm'
      ? elbowFlare(landmarks) : null;

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

    // Crossed feet, watched on every frame because the trail foot swings
    // through partway into the recovery -- after the rep has already fired.
    //
    // Which rep it belongs to needs care. A cross drives the signal to its
    // minimum, and the minimum is exactly where the next rep arms, so the naive
    // version tagged two steps for one mistake. The rule that works: while the
    // signal is still down at the arming end, we are between steps and the
    // cross belongs to the one that just finished. Once it has risen away from
    // there the new push has begun and the cross is the new step's.
    if (this.spec.signal.kind === 'stance_width' && value < 0) {
      const betweenSteps = rising ? s <= armThreshold : s >= armThreshold;
      if (betweenSteps) {
        // Belongs to the step that just finished, or to nothing at all. It is
        // deliberately not passed along to the step about to start: `lastRep`
        // is cleared the moment that step arms, and falling through to the new
        // one is what made a single mistake tag two of them.
        if (this.lastRep) this.lastRep.crossed = true;
      } else {
        this.pendingCrossed = true;
      }
    }
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
        this.pendingRawPeak = value;
        // Deliberately NOT seeded with this frame's zone. Arming happens at
        // the *closest* point of the cycle -- the ready position -- so its
        // zone is never a target. Seeding it means a save whose every
        // extended frame was unreadable reports the ready position instead,
        // which the server would score as "drifted to the middle": a miss
        // invented out of a camera problem.
        this.pendingZone = null;
        // Deliberately not seeded from this frame: a cross still showing at the
        // moment the next step arms belonged to the step that just finished,
        // and has already been recorded against it.
        this.pendingCrossed = false;
        this.pendingFlare = null;
        this.lastRep = null;
      } else if (this.lastRep) {
        // Still following through on the rep just emitted. Extend its span so
        // the peak of the movement is captured, not the threshold crossing.
        this.extendSpan(s);
        this.lastRep.rom = round3(Math.abs(this.cycleMax - this.cycleMin));
        this.lastRep.peak = round3(rising ? this.cycleMax : this.cycleMin);
        // The rep fires on a threshold crossing, but the hands often keep
        // going for a frame or two afterwards. That overshoot is where they
        // actually arrived, so the zone follows it.
        if (this.pendingRawPeak !== null && zone && zone !== 'unknown'
            && (rising ? value > this.pendingRawPeak : value < this.pendingRawPeak)) {
          this.pendingRawPeak = value;
          this.lastRep.zone = zone;
        }
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
      // Release is the top of the extension, which is exactly this extreme.
      if (flare !== null) this.pendingFlare = flare;
    }

    // Separate from the peak above, and against the raw value: this is asking
    // where the hands got to, and the smoothed signal answers that question
    // several frames late.
    if (this.pendingRawPeak === null
        || (rising ? value > this.pendingRawPeak : value < this.pendingRawPeak)) {
      this.pendingRawPeak = value;
      if (zone && zone !== 'unknown') this.pendingZone = zone;
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
        // Cued drills only. 'unknown' is sent rather than omitted: the server
        // needs to tell "we could not see the hands" apart from "the hands
        // went to the wrong place", and a missing field cannot say which.
        ...(this.spec.cues ? { zone: this.pendingZone || 'unknown' } : {}),
        // Stance-width drills only. Sent as a flag rather than inferred from
        // `peak`, because the crossing is usually not at the extreme of the
        // rep and would be invisible in a min/max.
        ...(this.spec.signal.kind === 'stance_width'
            ? { crossed: this.pendingCrossed } : {}),
        // Shooting drills only. Null rather than absent when the athlete was
        // side-on: "we could not see the elbow" and "the elbow was under the
        // ball" are different facts and must not collapse into one.
        ...(this.spec.signal.kind === 'shooting_arm'
            ? { flare: this.pendingFlare === null
                       ? null : round3(this.pendingFlare) } : {}),
      };
      this.reps.push(rep);
      this.lastRepAt = tMs;
      this.armed = false;
      this.armedAt = null;
      this.pendingHand = 'none';
      this.pendingZone = null;
      this.pendingCrossed = false;
      this.pendingFlare = null;
      // Deliberately not cleared with the zone: the follow-through frames
      // after this point still belong to this rep and may yet find its real
      // furthest reach.
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
