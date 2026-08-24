/**
 * Ball tracking, on the phone, alongside pose.
 *
 * The rest of this product counts what the *body* did. A wall-ball rep is a
 * throwing motion, a squat is a knee angle -- which is why the catalog has no
 * dribbling or juggling drills, and why the README says a convincing
 * shadow-throw with no ball counts. This module is what closes that.
 *
 * Three things shape it.
 *
 * **It has to run next to pose estimation on a mid-range phone.** A detector
 * heavy enough to find a tennis ball reliably is far too slow to run every
 * frame while MediaPipe is already using the GPU. So detection runs at a low
 * rate and a cheap predictive tracker fills the gaps -- the standard
 * detect-then-track split. Frames the tracker invented are labelled as such and
 * never counted as evidence.
 *
 * **A contact is physics, not a heuristic.** A ball in free flight accelerates
 * downward at a constant rate; anything else is something hitting it. So the
 * detector estimates gravity *from the track itself* -- which makes it
 * independent of how far away the camera is, what the frame height represents,
 * and whether the phone is in portrait -- and flags frames where the velocity
 * change is far larger than gravity explains. That is an impulse, and an
 * impulse is a foot, a floor, or a wall.
 *
 * **When it cannot see the ball it must say so.** Every track reports the
 * share of frames backed by a real observation. A drill that needs a ball
 * refuses to count below the floor rather than degrading quietly into a pose
 * drill that says "42 juggles" when the athlete was standing still. Fabricated
 * counts are worse than no feature.
 */

import { LANDMARKS } from './counter.js';

/**
 * Distance between two normalised points, corrected for frame shape.
 *
 * Pose landmarks and ball positions both arrive normalised 0-1 against their
 * own axis, which makes that space **anisotropic**: in a 16:9 landscape frame
 * one x-unit is 1.78 times wider on the ground than one y-unit, and in
 * portrait it is the other way round. Every radius and gate in this module is
 * a real-world distance, so measuring them in raw normalised units meant a
 * phone turned sideways silently changed what "next to the ball" meant.
 *
 * Everything here is therefore measured in **frame heights**: x is scaled by
 * the aspect ratio, y is left alone, and a distance means the same thing
 * whichever way up the phone is.
 */
export function metricDistance(ax, ay, bx, by, aspect = 1) {
  return Math.hypot((ax - bx) * aspect, ay - by);
}

/** Detections older than this are not worth extrapolating from. */
export const MAX_COAST_MS = 220;

/** Search radius for associating a detection with the existing track. */
export const GATE_RADIUS = 0.18;

/**
 * Consecutive out-of-gate detections before the track gives up and re-acquires.
 *
 * Without this the tracker locks onto whatever it saw first and can never
 * recover -- a ball that leaves the frame and comes back somewhere else, or a
 * first frame that caught a ball lying on the grass behind the athlete, would
 * make the whole session count nothing while the real ball was rejected as a
 * decoy for being too far from a track that was wrong to begin with.
 */
export const REACQUIRE_AFTER = 5;

/** Prior for downward acceleration, in frame-heights per second squared. */
export const GRAVITY_PRIOR = 1.9;

/** An impulse this much larger than gravity predicts is a contact. */
export const IMPULSE_RATIO = 3.0;

/** Minimum outgoing speed for a contact to be real rather than a wobble. */
export const MIN_CONTACT_SPEED = 0.25;

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/**
 * A smoothed ball track built from sparse detections.
 *
 * Deliberately not a full Kalman filter: the state is two-dimensional and the
 * measurement noise is dominated by the detector's own box jitter, so a
 * constant-velocity model with an exponential blend behaves the same and is
 * small enough to read.
 */
export class BallTracker {
  constructor(options = {}) {
    this.gate = options.gate ?? GATE_RADIUS;
    this.reacquireAfter = options.reacquireAfter ?? REACQUIRE_AFTER;
    //: Frame width over height. 1 until the camera reports otherwise.
    this.aspect = options.aspect ?? 1;
    this.maxCoastMs = options.maxCoastMs ?? MAX_COAST_MS;
    this.positionBlend = options.positionBlend ?? 0.55;
    this.velocityBlend = options.velocityBlend ?? 0.45;
    this.reset();
  }

  reset() {
    this.x = null; this.y = null;
    this.vx = 0; this.vy = 0;
    this.r = 0.02;
    this.lastSeenAt = null;
    this.lastAt = null;
    /** The previous *observation*, which is what velocity is measured across. */
    this.lastObs = null;
    this.observed = 0;
    this.frames = 0;
    this.rejected = 0;
    /** Running estimate of gravity in this framing, learned from free flight. */
    this.gravity = GRAVITY_PRIOR;
    this.gravitySamples = 0;
    this.lastObsVy = null;
    /** Raw velocity between the last two observations, before smoothing. */
    this.obsVx = 0;
    this.obsVy = 0;
  }

  /** Share of frames that had a real detection behind them. */
  get quality() {
    return this.frames ? this.observed / this.frames : 0;
  }

  get visible() {
    return this.x !== null;
  }

  /**
   * Fold one frame in.
   *
   * `detection` is `{x, y, r, score}` in normalised frame coordinates, or null
   * on frames where the detector did not run or found nothing.
   */
  push(detection, tMs) {
    const dt = this.lastAt === null ? 0 : (tMs - this.lastAt) / 1000;
    this.lastAt = tMs;
    this.frames += 1;

    if (detection) {
      const outOfGate = this.visible
        && metricDistance(detection.x, detection.y, this.x, this.y, this.aspect) > this.gate
        && (tMs - this.lastSeenAt) < this.maxCoastMs;

      // A detection far from where the ball must be, while the track is still
      // fresh, is another object -- a face, a shoe, a ball on the ground
      // behind the athlete. Ignoring it keeps the track on the real ball.
      // But a run of them means the track itself is the thing that is wrong.
      if (outOfGate && this.rejected < this.reacquireAfter) {
        this.rejected += 1;
      } else {
        if (outOfGate) this._reacquire();
        this.rejected = 0;
        this._observe(detection, tMs);
        return this.state('detect');
      }
    }

    if (!this.visible) return this.state('none');

    if (tMs - this.lastSeenAt > this.maxCoastMs) {
      // Coasted too long. Dropping the track is honest; extrapolating a ball
      // through a second of nothing invents a trajectory.
      this.x = null; this.y = null;
      return this.state('none');
    }

    // Coast on the constant-velocity model, with gravity applied so a ball
    // mid-flight lands where physics says rather than where it was going.
    this.x += this.vx * dt;
    this.y += this.vy * dt + 0.5 * this.gravity * dt * dt;
    this.vy += this.gravity * dt;
    return this.state('predict');
  }

  /** Forget the current track so the next detection starts a fresh one. */
  _reacquire() {
    this.x = null; this.y = null;
    this.vx = 0; this.vy = 0;
    this.lastObs = null;
    this.lastObsVy = null;
  }

  _observe(detection, tMs) {
    // Velocity is measured between observations, never between frames. The
    // difference matters: with the detector at 10fps and the camera at 30,
    // `this.x` has already been coasted forward twice using the current
    // gravity estimate, so dividing by the frame interval measures the
    // tracker's own prediction back to itself. That feedback loop inflated
    // the learned gravity by 50% and manufactured phantom contacts.
    const obs = this.lastObs;
    const dtObs = obs ? (tMs - obs.t) / 1000 : 0;

    if (!obs || dtObs <= 0 || dtObs > this.maxCoastMs / 1000) {
      this.x = detection.x; this.y = detection.y;
      this.vx = 0; this.vy = 0;
      this.obsVx = 0; this.obsVy = 0;
    } else {
      const vx = (detection.x - obs.x) / dtObs;
      const vy = (detection.y - obs.y) / dtObs;
      // Kept unsmoothed. Smoothing exists so the drawn ball does not jitter;
      // running impulse detection on it damps the very spike being looked for
      // -- at a 10fps detection rate that hid eight kicks in nine.
      this.obsVx = vx;
      this.obsVy = vy;
      this._learnGravity(vy, dtObs);
      this.vx += this.velocityBlend * (vx - this.vx);
      this.vy += this.velocityBlend * (vy - this.vy);
      this.x += this.positionBlend * (detection.x - this.x);
      this.y += this.positionBlend * (detection.y - this.y);
    }
    this.lastObs = { x: detection.x, y: detection.y, t: tMs };
    this.r = detection.r ?? this.r;
    this.lastSeenAt = tMs;
    this.observed += 1;
  }

  /**
   * Learn how fast things fall in *this* framing.
   *
   * A phone held close sees a ball accelerate across far more of the frame per
   * second than one filming from the sideline. Estimating it from the athlete's
   * own footage means the contact detector never needs to know the camera
   * distance, the frame height in metres, or the orientation.
   */
  _learnGravity(vy, dt) {
    if (dt <= 0 || dt > 0.2) return;
    if (this.lastObsVy === undefined || this.lastObsVy === null) {
      this.lastObsVy = vy;
      return;
    }
    const accel = (vy - this.lastObsVy) / dt;
    this.lastObsVy = vy;
    // Only free-flight frames teach anything. A contact is a huge acceleration
    // and would drag the estimate up until nothing looked like a contact.
    if (accel <= 0 || accel > 12) return;
    this.gravitySamples += 1;
    const weight = 1 / Math.min(this.gravitySamples, 40);
    this.gravity += weight * (accel - this.gravity);
    this.gravity = clamp(this.gravity, 0.4, 8);
  }

  state(source) {
    return {
      x: this.x, y: this.y, r: this.r,
      vx: this.vx, vy: this.vy,
      obsVx: this.obsVx, obsVy: this.obsVy,
      speed: Math.hypot(this.vx, this.vy),
      obsSpeed: Math.hypot(this.obsVx, this.obsVy),
      source,
      quality: this.quality,
      gravity: this.gravity,
    };
  }
}

/**
 * Turns a ball track plus pose landmarks into contacts.
 *
 * A contact is a velocity change gravity cannot explain. Everything else here
 * is about deciding *what* hit it, which is what makes a juggle different from
 * a dribble.
 */
export class ContactDetector {
  constructor(options = {}) {
    this.minGapMs = options.minGapMs ?? 180;
    this.impulseRatio = options.impulseRatio ?? IMPULSE_RATIO;
    this.minSpeed = options.minSpeed ?? MIN_CONTACT_SPEED;
    this.partRadius = options.partRadius ?? 0.16;
    this.groundBand = options.groundBand ?? 0.12;
    this.aspect = options.aspect ?? 1;
    this.reset();
  }

  reset() {
    this.prev = null;
    this.prevAt = null;
    this.lastContactAt = -Infinity;
    this.contacts = [];
    this.seen = 0;
  }

  /**
   * Feed one tracked frame. Returns a contact when this frame was one.
   *
   * `parts` is a map of name -> {x, y} for the landmarks this drill cares
   * about, already scaled into the same normalised space as the ball.
   */
  push(ball, parts, tMs) {
    if (!ball || ball.x === null) { this.prev = null; return null; }

    // Contacts are only read off frames with a real detection behind them.
    // On a coasted frame the velocity is whatever the model extrapolated, and
    // on the frame an observation lands it takes a corrective step -- which
    // looks exactly like an impulse. Requiring evidence removes both, and is
    // the same rule the rest of this product follows: a count has to be backed
    // by something the camera actually saw.
    if (ball.source !== 'detect') return null;
    this.seen += 1;

    const prev = this.prev;
    const prevAt = this.prevAt;
    this.prev = { vx: ball.obsVx, vy: ball.obsVy, x: ball.x, y: ball.y };
    this.prevAt = tMs;
    if (!prev || prevAt === null) return null;

    const dt = (tMs - prevAt) / 1000;
    if (dt <= 0 || dt > 0.25) return null;
    // The first measured velocity is compared against a standing start of
    // zero, so a ball already in flight when recording began reads as a
    // contact. Two observations are needed before any of this means anything.
    if (this.seen < 3) return null;

    // What the velocity would be if nothing had touched it.
    const expectedVy = prev.vy + ball.gravity * dt;
    const residual = Math.hypot(ball.obsVx - prev.vx, ball.obsVy - expectedVy);
    const explained = Math.abs(ball.gravity * dt);

    if (residual < Math.max(this.minSpeed, explained * this.impulseRatio)) return null;
    if (tMs - this.lastContactAt < this.minGapMs) return null;
    // A ball leaving a contact is going somewhere. This drops the shivers a
    // jittery detection box produces when the ball is nearly still.
    if (ball.obsSpeed < this.minSpeed) return null;

    const contact = {
      t: tMs,
      x: ball.x, y: ball.y,
      impulse: residual,
      speedIn: Math.hypot(prev.vx, prev.vy),
      speedOut: ball.obsSpeed,
      ...this.classify(ball, parts),
    };
    this.lastContactAt = tMs;
    this.contacts.push(contact);
    return contact;
  }

  /** Who or what hit it: the nearest listed landmark, or the floor. */
  classify(ball, parts) {
    let best = null;
    let bestDistance = Infinity;
    for (const [name, point] of Object.entries(parts || {})) {
      if (!point) continue;
      const distance = metricDistance(ball.x, ball.y, point.x, point.y, this.aspect);
      if (distance < bestDistance) { bestDistance = distance; best = name; }
    }

    // Near the bottom of the frame with nothing close by is the floor. Checked
    // after the landmarks so a foot at ground level still reads as a foot,
    // which is the whole difference between a dribble and a juggle.
    if (best !== null && bestDistance <= this.partRadius) {
      return {
        kind: 'body',
        part: best,
        side: best.startsWith('left_') ? 'left'
          : best.startsWith('right_') ? 'right' : 'none',
        distance: bestDistance,
      };
    }
    if (ball.y > 1 - this.groundBand) {
      return { kind: 'ground', part: 'ground', side: 'none', distance: bestDistance };
    }
    return { kind: 'other', part: '', side: 'none', distance: bestDistance };
  }
}

/**
 * Turns ball contacts into reps, per a drill's BallSpec.
 *
 * Deliberately a separate counter from `RepCounter` rather than another branch
 * inside it. The pose counter's whole model is a smoothed signal crossing
 * hysteresis thresholds; a ball rep is a discrete event with no signal and no
 * range of motion. Forcing them together would mean a threshold field that
 * means nothing for half the catalog.
 */
export class BallRepCounter {
  constructor(spec) {
    this.spec = spec;
    this.ball = spec.ball || {};
    this.tracker = new BallTracker();
    this.detector = new ContactDetector({
      minGapMs: this.ball.min_gap_ms ?? 180,
      minSpeed: this.ball.min_speed ?? MIN_CONTACT_SPEED,
    });
    this.aspect = 1;
    this.reset();
  }

  /**
   * Tell the counter what shape the frame is.
   *
   * Set once the camera reports its dimensions, and again if the phone is
   * turned mid-session -- which athletes do, and which used to change the
   * meaning of every distance in here.
   */
  setAspect(aspect) {
    if (!aspect || !Number.isFinite(aspect) || aspect <= 0) return;
    this.aspect = aspect;
    this.tracker.aspect = aspect;
    this.detector.aspect = aspect;
  }

  reset() {
    this.tracker.reset();
    this.detector.reset();
    this.reps = [];
    this.lastAt = null;
    /** Frames where the ball was tracked at all. */
    this.trackedFrames = 0;
    /**
     * Frames where the ball was well clear of both hands.
     *
     * The check that separates wall ball from waving a ball around. An arm
     * whipping through a throwing motion with the ball still in it produces
     * accelerations that read as impulses and a wrist right beside them that
     * reads as a contact -- so contact counting alone scores a fake exactly
     * like the real thing. What it cannot fake is the ball leaving: real wall
     * ball sends it metres away and brings it back, and a ball that never
     * gets more than a hand's width from a wrist never went anywhere.
     */
    this.awayFrames = 0;
  }

  get count() { return this.reps.length; }

  get trackQuality() { return this.tracker.quality; }

  /** Whether this session is trustworthy enough to count at all. */
  get trusted() {
    return this.trackQuality >= (this.ball.min_track_quality ?? 0.35);
  }

  handCounts() {
    let left = 0, right = 0;
    for (const rep of this.reps) {
      if (rep.hand === 'left') left += 1;
      else if (rep.hand === 'right') right += 1;
    }
    return { left, right };
  }

  /**
   * One frame. `detection` may be null on frames the detector skipped;
   * `landmarks` is the pose array, or null if pose has not resolved yet.
   */
  push(detection, landmarks, tMs) {
    this.lastAt = tMs;
    const ball = this.tracker.push(detection, tMs);
    this._measureTravel(ball, landmarks);
    const contact = this.detector.push(ball, this.parts(landmarks), tMs);
    if (!contact) return null;

    // A juggle only counts if a body part took it; a dribble only counts if
    // the floor did. Without this a ball bouncing off a wall behind the
    // athlete would count as a touch.
    const wanted = this.ball.contact ?? 'body';
    if (contact.kind !== wanted) return null;

    const rep = {
      t_ms: Math.round(contact.t),
      hand: this.ball.attribute_side ? sideOf(contact, landmarks, this.aspect) : 'none',
      confidence: Math.min(1, this.tracker.quality + 0.2),
      part: contact.part,
      speed: Number(contact.speedOut.toFixed(3)),
      impulse: Number(contact.impulse.toFixed(3)),
    };
    this.reps.push(rep);
    return rep;
  }

  /** How far the ball gets from the hands, measured in the athlete's torsos. */
  _measureTravel(ball, landmarks) {
    if (!ball || ball.x === null || !landmarks) return;
    const torso = torsoLength(landmarks, this.aspect);
    if (!torso) return;
    this.trackedFrames += 1;

    let nearest = Infinity;
    for (const name of ['left_wrist', 'right_wrist']) {
      const point = landmarks[LANDMARK_INDEX[name]];
      if (!point || (point.visibility ?? 1) < 0.4) continue;
      nearest = Math.min(
        nearest, metricDistance(ball.x, ball.y, point.x, point.y, this.aspect),
      );
    }
    if (nearest === Infinity) return;
    if (nearest / torso > AWAY_FROM_HANDS) this.awayFrames += 1;
  }

  /** Share of tracked frames where the ball was genuinely away from the hands. */
  get travelShare() {
    return this.trackedFrames ? this.awayFrames / this.trackedFrames : 0;
  }

  /**
   * Corroboration for a drill whose reps the *body* counted.
   *
   * Returned as fields to merge into the pose counter's submission rather
   * than a submission of its own: in confirm mode the reps belong to the pose
   * counter and this only ever adds to them.
   */
  confirmation() {
    return {
      track_quality: Math.round(this.trackQuality * 1000) / 1000,
      ball_contacts: this.detector.contacts.length,
      ball_travel: Math.round(this.travelShare * 1000) / 1000,
    };
  }

  /**
   * The payload posted to /api/sessions/submit. Counts only, same as the pose
   * counter -- plus the track quality, which the server checks against the
   * drill's own floor rather than taking the client's word for.
   */
  toSubmission(sessionId, nonce, durationMs, extra = {}) {
    return {
      session_id: sessionId,
      nonce,
      duration_ms: Math.round(durationMs),
      reps: this.reps,
      hold_ms: 0,
      mean_confidence: Math.round(this.trackQuality * 1000) / 1000,
      track_quality: Math.round(this.trackQuality * 1000) / 1000,
      ...extra,
    };
  }

  /** The landmarks this drill treats as able to touch the ball. */
  parts(landmarks) {
    const out = {};
    if (!landmarks) return out;
    for (const name of this.ball.parts || []) {
      const index = LANDMARK_INDEX[name];
      const point = index === undefined ? null : landmarks[index];
      if (point && (point.visibility ?? 1) > 0.4) {
        out[name] = { x: point.x, y: point.y };
      }
    }
    return out;
  }
}

/** Distance from ball to hand, beyond which the ball has actually gone. */
export const AWAY_FROM_HANDS = 1.5;

/** Shoulder-to-hip, the scale everything about a body is measured in. */
function torsoLength(landmarks, aspect = 1) {
  const shoulder = landmarks[LANDMARK_INDEX.left_shoulder]
    || landmarks[LANDMARK_INDEX.right_shoulder];
  const hip = landmarks[LANDMARK_INDEX.left_hip] || landmarks[LANDMARK_INDEX.right_hip];
  if (!shoulder || !hip) return 0;
  const torso = metricDistance(shoulder.x, shoulder.y, hip.x, hip.y, aspect);
  return torso > 0.05 ? torso : 0;
}

/**
 * Which side took the contact.
 *
 * For a body contact the landmark says it directly. For a ground contact --
 * a dribble -- the floor has no side, so it is the nearer wrist that answers.
 */
function sideOf(contact, landmarks, aspect = 1) {
  if (contact.side && contact.side !== 'none') return contact.side;
  if (!landmarks) return 'none';
  const left = landmarks[LANDMARK_INDEX.left_wrist];
  const right = landmarks[LANDMARK_INDEX.right_wrist];
  if (!left || !right) return 'none';
  const dl = metricDistance(contact.x, contact.y, left.x, left.y, aspect);
  const dr = metricDistance(contact.x, contact.y, right.x, right.y, aspect);
  // Too close to call is 'none' rather than a coin flip: a fabricated
  // left/right split would feed straight into the off-hand balance score.
  if (Math.abs(dl - dr) < 0.05) return 'none';
  return dl < dr ? 'left' : 'right';
}

/**
 * Landmark name to array index.
 *
 * Imported from the counter rather than injected by the caller. The injected
 * version was one forgotten call away from an empty map, which would not
 * throw -- it would silently classify every contact as "nothing was near it"
 * and count zero juggles while reporting a healthy track.
 */
export const LANDMARK_INDEX = Object.fromEntries(
  LANDMARKS.map((name, index) => [name, index]),
);
