/**
 * Approximate shot speed for lacrosse shooting, worked out on the phone.
 *
 * A camera cannot clock a shot directly. A 60mph ball covers about 0.9m between
 * frames at the 30fps a phone browser films at, so it is a blur in two or three
 * frames and then gone. What the phone CAN time well is the flight: the ball
 * leaves the stick, and then it hits something -- the net, a pipe, a rebounder,
 * a wall -- and that hit is loud and sharp. Distance over flight time is the
 * speed.
 *
 *   speed = distance / (impact_heard - release - sound_travel_back)
 *
 * Three things go into it, and each has its own error:
 *
 * **Distance** is the athlete's: they shoot from a spot they marked, and say how
 * far it was. Nothing on the phone can measure it. 8 yards is the default
 * because it is the standard shooting distance in youth practice.
 *
 * **Release** comes from pose. A lacrosse release is nearly silent -- the ball
 * leaves the pocket without a sound worth hearing -- so the moment is taken
 * from the stick hand: the frame where it was highest and moving fastest
 * forward. That is good to about a frame (33ms), which is the biggest single
 * source of error here.
 *
 * **Impact** comes from the microphone, timed to ~10ms, and corrected for the
 * time the sound takes to come back from the goal to a phone standing near the
 * shooter: at 8 yards that is 21ms, which on a 250ms flight is 8% and must not
 * be left in.
 *
 * So the figure is the *average* speed over the flight, a little under what a
 * radar gun reads at the stick. It is honest about that, it compares an athlete
 * with themselves, and it never goes on a leaderboard (that would reward
 * ripping shot after shot, which is how young shoulders get hurt).
 *
 * Nothing audio-shaped and no video leaves the phone. A shot is sent as a
 * timestamp, a flight time and a distance, and the server works out the speed
 * again itself rather than taking the phone's word for it.
 */

/** Metres per second of sound in air at ~20C. */
export const SPEED_OF_SOUND_MS = 343;

/** The default shooting distance, in yards, when the athlete does not set one. */
export const DEFAULT_DISTANCE_YD = 8;

/** Yards -> metres. */
export const YD_TO_M = 0.9144;

/** m/s -> mph. */
export const MS_TO_MPH = 2.236936;

/**
 * Shortest flight that can be a real shot. 8 yards at 110mph -- faster than the
 * fastest shot ever recorded in lacrosse -- is 150ms; anything shorter is a
 * sound that was not the ball arriving (a stick knocking on the follow-through,
 * the pocket rattling).
 */
export const MIN_FLIGHT_MS = 60;

/**
 * Longest flight worth timing. A lob at 8 yards is still under a second; past
 * this the "impact" is something else -- the ball rolling into a fence, the
 * next shot -- and no speed is given.
 */
export const MAX_FLIGHT_MS = 1600;

/**
 * Speeds outside this band, in mph, are not reported. Below is a dropped ball;
 * above is beyond anything a youth player can do and means one of the two
 * moments was wrong. Both still count the shot.
 */
export const MIN_MPH = 15;
export const MAX_MPH = 110;

/**
 * How long before an impact its release may be and still be the same shot.
 * The slowest flight worth timing (MAX_FLIGHT_MS); a release further back
 * than that was a shot that hit nothing.
 */
export const MATCH_WINDOW_MS = MAX_FLIGHT_MS;

/**
 * The fewest frames between two releases, at the 30fps the phone films. A
 * shooter cannot load, shoot and reload in under a second, so a second
 * "release" closer than this is the same shot read twice.
 */
export const MIN_RELEASE_GAP_MS = 900;

/**
 * Height of the stick hand above the shoulder line, in torso lengths, that a
 * shot has to reach to be a shot. An overhand shot releases well above the
 * shoulder; a sidearm one around it. Below this the hands were cradling.
 */
export const RELEASE_MIN_HEIGHT = -0.25;

/**
 * Forward speed of the stick hand at release, in torso lengths per second.
 * A shot snaps the top hand forward; a cradle or a fake drifts. Measured off
 * the same normalised landmarks the rest of the counter uses.
 */
export const RELEASE_MIN_HAND_SPEED = 2.5;

/** Convert a shooting distance to metres. */
export function distanceMetres(yards) {
  const y = Number(yards);
  return (Number.isFinite(y) && y > 0 ? y : DEFAULT_DISTANCE_YD) * YD_TO_M;
}

/**
 * Speed of one shot, in mph, or null when the two moments cannot be a shot.
 *
 * `releaseMs` and `impactMs` are on the same session clock. `distanceM` is the
 * distance from shooter to target. The sound has to come back that same
 * distance to a phone beside the shooter, so its travel time is taken off the
 * heard impact.
 */
export function shotSpeedMph(releaseMs, impactMs, distanceM) {
  if (!(distanceM > 0)) return null;
  const soundBack = (distanceM / SPEED_OF_SOUND_MS) * 1000;
  const flight = impactMs - soundBack - releaseMs;
  if (!(flight >= MIN_FLIGHT_MS && flight <= MAX_FLIGHT_MS)) return null;
  const mph = (distanceM / (flight / 1000)) * MS_TO_MPH;
  return mph >= MIN_MPH && mph <= MAX_MPH ? Math.round(mph * 10) / 10 : null;
}

/**
 * Finds shot releases in a stream of pose frames.
 *
 *   const rd = new ReleaseDetector();
 *   rd.push({ t, height, x, hand });   // per frame: stick-hand height above the
 *                                      // shoulders and horizontal position, in
 *                                      // torso lengths
 *   rd.releases                        // [{ t_ms, hand }]
 *
 * A release is the frame where the stick hand, having come up above
 * RELEASE_MIN_HEIGHT, moves forward fastest. Forward is whichever horizontal
 * direction the hand travels on the snap, so it works whichever way the
 * athlete faces the camera.
 */
export class ReleaseDetector {
  constructor() {
    this.prev = null;
    this.peak = null;       // fastest frame in the current shot so far
    this.releases = [];
  }

  push({ t, height, x, hand }) {
    if (height === null || height === undefined || x === null || x === undefined) {
      this._close();
      this.prev = null;
      return;
    }
    const prev = this.prev;
    this.prev = { t, x, height };
    if (!prev || t <= prev.t) return;
    const speed = Math.abs(x - prev.x) / ((t - prev.t) / 1000);

    const shooting = height >= RELEASE_MIN_HEIGHT && speed >= RELEASE_MIN_HAND_SPEED;
    if (shooting) {
      if (!this.peak || speed > this.peak.speed) this.peak = { t, speed, hand };
    } else {
      this._close();
    }
  }

  /** The snap has ended: record its fastest frame as the release. */
  _close() {
    if (!this.peak) return;
    const last = this.releases[this.releases.length - 1];
    if (!last || this.peak.t - last.t_ms >= MIN_RELEASE_GAP_MS) {
      this.releases.push({ t_ms: Math.round(this.peak.t), hand: this.peak.hand });
    }
    this.peak = null;
  }

  /** Call when the session ends, so a snap still in progress is recorded. */
  finish() { this._close(); }
}

/**
 * The shooting counter. Wraps the sound counter, which already counts each
 * impact and supplies the hand, and adds a speed to every shot it can time.
 *
 * Presents the same surface as the other counters (count, reps, handCounts,
 * meanConfidence, toSubmission) so the capture screen holds it like any other.
 *
 * The count is the number of shots *heard*: a shot that hit nothing is still a
 * shot to the athlete, but with no sound there is nothing to count it by. That
 * is why the setup asks for a net or a wall.
 */
export class ShotSpeedCounter {
  constructor(spec, soundCounter, { distanceYd } = {}) {
    this.spec = spec;
    this.sound = soundCounter;
    this.pose = soundCounter.pose;
    this.distanceYd = Number(distanceYd) || (spec.shot && spec.shot.default_distance_yd)
      || DEFAULT_DISTANCE_YD;
    this.releases = new ReleaseDetector();
  }

  pushAudio(block, tMs) { this.sound.pushAudio(block, tMs); }

  /** Pose: forwarded to the sound counter, and read for the release. */
  pushPose(landmarks, tMs) {
    this.sound.pushPose(landmarks, tMs);
    this.releases.push({ t: tMs, ...stickHand(landmarks) });
  }

  /** Impacts the sound counter kept as shots, with each one's release. */
  get shots() {
    const impacts = this.sound.grouping.cycles.map((c) => c.t_ms);
    const releases = this.releases.releases.map((r) => r.t_ms);
    const metres = distanceMetres(this.distanceYd);
    // Pair from the impact's side: each heard shot looks back for the last
    // release before it, inside the flight window. A release with no sound
    // after it (a wide shot) is simply never claimed.
    return impacts.map((impact) => {
      let release = null;
      for (let i = releases.length - 1; i >= 0; i -= 1) {
        if (releases[i] < impact) {
          if (impact - releases[i] <= MATCH_WINDOW_MS) release = releases[i];
          break;
        }
      }
      const mph = release === null ? null : shotSpeedMph(release, impact, metres);
      return { impact_ms: impact, release_ms: release, mph };
    });
  }

  get count() { return this.sound.count; }
  get meanConfidence() { return this.sound.meanConfidence; }
  handCounts() { return this.sound.handCounts(); }

  /** The last shot's speed, for the live readout. */
  get lastMph() {
    const s = this.shots;
    return s.length ? s[s.length - 1].mph : null;
  }

  get reps() {
    const shots = this.shots;
    return this.sound.reps.map((rep, i) => {
      const shot = shots[i];
      if (!shot) return rep;
      const out = { ...rep, impact_t_ms: Math.round(shot.impact_ms) };
      // The raw release time, not the speed: the server works the speed out
      // again itself, and only a shot with both moments has one.
      if (shot.release_ms !== null) out.release_t_ms = Math.round(shot.release_ms);
      return out;
    });
  }

  toSubmission(sessionId, nonce, durationMs, extra = {}) {
    this.releases.finish();
    return this.sound.toSubmission(sessionId, nonce, durationMs, {
      reps: this.reps,
      shot_distance_yd: this.distanceYd,
      ...extra,
    });
  }
}

/**
 * The stick hand for release detection: the higher wrist, its height above
 * the shoulder line and its horizontal position, both in torso lengths so the
 * thresholds above hold whatever the distance to the phone.
 */
function stickHand(landmarks) {
  const P = (i) => {
    const p = landmarks && landmarks[i];
    return p && (p.visibility ?? 1) >= 0.5 ? p : null;
  };
  // MediaPipe pose indices: shoulders 11/12, hips 23/24, wrists 15/16.
  const ls = P(11), rs = P(12), lh = P(23), rh = P(24), lw = P(15), rw = P(16);
  const mid = (a, b) => (a && b ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : a || b);
  const sh = mid(ls, rs), hip = mid(lh, rh);
  if (!sh || !hip || (!lw && !rw)) return { height: null, x: null, hand: 'none' };
  const torso = Math.hypot(sh.x - hip.x, sh.y - hip.y);
  if (!(torso > 0.02)) return { height: null, x: null, hand: 'none' };
  let top = lw, hand = 'left';
  if (!lw || (rw && rw.y < lw.y)) { top = rw; hand = 'right'; }
  return {
    height: (sh.y - top.y) / torso,
    x: top.x / torso,
    hand,
  };
}
