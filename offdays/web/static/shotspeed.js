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
 * **Release** comes from the swing. The ball leaves the pocket without a sound
 * of its own, but the stick does not: a shot is a 60-200ms whoosh, loudest as
 * the ball goes, and the microphone times it to the hop. On four radar-clocked
 * shots filmed from behind the shooter it put the release within 30ms of the
 * frame the ball left the stick (`ShotListener`). Pose -- the frame the stick
 * hand moved fastest -- is the fallback where no swing was heard, and from
 * behind it is poor: it needs to see the hand.
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
  /**
   * The thresholds default to the exported constants. They are options so the
   * calibration bench (`scripts/shotcal/`) can sweep them against radar-gun
   * truth without editing this file; the capture screen never passes any.
   */
  constructor({ minHeight = RELEASE_MIN_HEIGHT, minHandSpeed = RELEASE_MIN_HAND_SPEED,
                minGapMs = MIN_RELEASE_GAP_MS } = {}) {
    this.minHeight = minHeight;
    this.minHandSpeed = minHandSpeed;
    this.minGapMs = minGapMs;
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

    const shooting = height >= this.minHeight && speed >= this.minHandSpeed;
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
    if (!last || this.peak.t - last.t_ms >= this.minGapMs) {
      this.releases.push({ t_ms: Math.round(this.peak.t), hand: this.peak.hand });
    }
    this.peak = null;
  }

  /** Call when the session ends, so a snap still in progress is recorded. */
  finish() { this._close(); }
}

/**
 * How far above the background the stick's swing must sound, as a ratio of
 * energies (5dB), read from a running median over SWING_SMOOTH_HOPS so a
 * single click does not count. The swings in the radar clips peaked 7-12dB
 * over the floor, phone on the ground a few yards behind the shooter.
 */
export const SWING_RATIO = 3.16;

/**
 * A swing lasts at least this long. The radar clips' swings ran 80-190ms on
 * every channel; the loudest thing that was not one -- a step on the follow-
 * through, right by the phone -- ran 50.
 */
export const SWING_MIN_MS = 60;

/** Hops in the running median that swings and sharpness are read against (50ms). */
export const SWING_SMOOTH_HOPS = 5;

/**
 * An impact: a hop at least this far above the background (5dB) ...
 *
 * Lower than the wall-ball detector's ONSET_RATIO on purpose. From 10 yards
 * a ball into a net is a soft sound: one radar clip's sat 6-9dB over the
 * floor, under the wall-ball threshold on either channel alone, and the shot
 * was paired with the ball dropping out of the net half a second later.
 */
export const IMPACT_RATIO = 3.16;

/**
 * ... and either at least this far above its own 50ms (5dB) -- a ball off a
 * pipe or a taut net is one or two hops of edge, where a whoosh or a run past
 * the phone is as loud but sustained ...
 */
export const IMPACT_SHARPNESS = 3.16;

/**
 * ... or a jump of at least this much (12dB) over the 20ms before it. A ball
 * into a slack net is not one hop of edge: on one radar clip it rang for 80ms,
 * and the sharpness test above threw it out. But it arrived from nothing, 16-
 * 17dB up in a single hop, where a swing or a run-past builds over several.
 * The only other sounds that jump like that in the radar clips are steps on
 * the follow-through, and those land too soon after the swing to be a shot.
 */
export const IMPACT_JUMP = 15.8;

/** Two sharp hops closer than this are one hit (the ball and the net's rattle). */
export const IMPACT_DEBOUNCE_MS = 150;

/**
 * The camera must have seen a body in this many frames within
 * BODY_WINDOW_MS of a release for it to be one. An empty field makes noises
 * that hum like a swing, and pose finds a "person" in a frame of one now and
 * then; a run of frames is someone actually there.
 */
export const BODY_MIN_FRAMES = 3;
export const BODY_WINDOW_MS = 100;

/**
 * After a shot lands, the next cannot leave the stick for this long: the
 * athlete has to get another ball into the pocket. Keeps the jog after a
 * shot -- a swing-like rustle and a footstep under a second later, on one
 * radar clip -- from pairing into a shot of its own.
 */
export const RELOAD_MS = 1000;

/** Analysis hop of the impact detector, in ms. */
const HOP_MS = 10;

/**
 * Anything older than this is settled for good: past the longest flight and
 * a reload, nothing heard later can change it.
 */
const SETTLE_MS = 4000;

/**
 * Listens to the shot: the stick swinging through, and the ball hitting.
 * Fed one hop at a time from `ImpactDetector.onHop` -- energies only, never
 * audio.
 *
 *   swings   [{ t_ms, start_ms, end_ms }]  a sustained rise in the high-
 *            passed energy, 60-200ms long; t_ms is its first crest,
 *            which is where the ball left the stick
 *   impacts  [{ t_ms, ratio }]             sharp hops, debounced
 *
 * The release used to come from pose alone, and pose needs the stick hand.
 * From behind the shooter it does not see it: on the first radar clips it
 * put the release 150-300ms out or found none at all, while the swing was
 * audible in every one, within a frame of where the ball left the stick.
 */
export class ShotListener {
  constructor() {
    this.window = [];
    this.current = null;
    this.swings = [];
    this.impacts = [];
    this.lastMs = -Infinity;
  }

  hop(tMs, energy, floor, warm) {
    this.window.push({ t: tMs, e: energy, floor, warm });
    if (this.window.length > SWING_SMOOTH_HOPS) this.window.shift();
    if (this.window.length < SWING_SMOOTH_HOPS) return;
    const mid = this.window[SWING_SMOOTH_HOPS >> 1];
    const sorted = this.window.map((h) => h.e).sort((a, b) => a - b);
    const smooth = sorted[SWING_SMOOTH_HOPS >> 1];
    this.lastMs = mid.t;
    // Judged only once the whole 50ms is past the warm-up: against a window
    // still holding warm-up hops, the first real hop looks like an edge.
    if (this.window.some((h) => h.warm)) return;

    const before = Math.max(this.window[0].e, this.window[1].e);
    const edge = mid.e >= smooth * IMPACT_SHARPNESS || mid.e >= before * IMPACT_JUMP;
    if (mid.e >= mid.floor * IMPACT_RATIO && edge) {
      const last = this.impacts[this.impacts.length - 1];
      if (!last || mid.t - last.t_ms >= IMPACT_DEBOUNCE_MS) {
        this.impacts.push({ t_ms: Math.round(mid.t), ratio: mid.e / mid.floor });
      }
    }

    if (smooth >= mid.floor * SWING_RATIO) {
      if (!this.current) this.current = { start: mid.t, end: mid.t, hops: [] };
      this.current.end = mid.t;
      this.current.hops.push({ t: mid.t, e: smooth });
    } else {
      this._close();
    }
  }

  _close() {
    const c = this.current;
    this.current = null;
    if (!c || c.end - c.start + HOP_MS < SWING_MIN_MS) return;
    this.swings.push({
      t_ms: Math.round(firstCrest(c.hops)), start_ms: Math.round(c.start), end_ms: Math.round(c.end),
    });
  }

  /** Forget what ended before tMs. */
  drop(tMs) {
    while (this.swings.length && this.swings[0].t_ms < tMs) this.swings.shift();
    while (this.impacts.length && this.impacts[0].t_ms < tMs) this.impacts.shift();
  }

  finish() { this._close(); }
}

/**
 * Where in a swing the ball left: the first crest that comes within 3dB of
 * the loudest. The stick is fastest as the ball goes, but it keeps whooshing
 * on the follow-through, and on a run-up the athlete's own noise runs
 * straight into the swing. On one radar clip that made a 180ms hump with two
 * crests, the ball leaving at the first; its middle was 50ms late, which is
 * 20 mph. Over all seven clips and both channels the first crest sat 16ms
 * from the frame the ball left, on average, against 24 for the middle.
 */
function firstCrest(hops) {
  const top = Math.max(...hops.map((h) => h.e));
  let i = 0;
  while (i < hops.length) {
    // A crest may be flat: take the run of equal hops as one, and its middle.
    let j = i;
    while (j + 1 < hops.length && hops[j + 1].e === hops[i].e) j += 1;
    const rose = i === 0 || hops[i - 1].e < hops[i].e;
    const fell = j === hops.length - 1 || hops[j + 1].e < hops[j].e;
    if (rose && fell && hops[i].e >= top / 2) return (hops[i].t + hops[j].t) / 2;
    i = j + 1;
  }
  return hops.find((h) => h.e === top).t;
}

/**
 * Choose the shots: pairs of (release, impact) where the flight is a real
 * shot at the distance set. Two steps.
 *
 * One ball is in the air at a time, so overlapping pairs are rivals, and the
 * tightest flight wins. That is what makes "the ball hits the first thing in
 * its way" hold: a swing pairs with the first hit after it, not the louder
 * rattle of the ball dropping out of the net, and a hit pairs with the swing
 * just before it, not a rustle from the run-up. Every looser pairing on the
 * radar clips overlapped a tighter, true one.
 *
 * Then, in order, a shot released within RELOAD_MS of the last one landing is
 * dropped: that is the jog after a shot, not the next one.
 *
 * `taken` are shots already settled, which new ones must also respect.
 */
export function pairShots(releases, impacts, distanceM, taken = []) {
  const candidates = [];
  for (const r of releases) {
    for (const i of impacts) {
      if (i.t_ms <= r.t_ms) continue;
      const mph = shotSpeedMph(r.t_ms, i.t_ms, distanceM);
      if (mph !== null) {
        candidates.push({ release_ms: r.t_ms, impact_ms: i.t_ms, via: r.via, mph });
      }
    }
  }
  candidates.sort((a, b) => (a.impact_ms - a.release_ms) - (b.impact_ms - b.release_ms));
  const apart = (a, b) => a.impact_ms < b.release_ms || b.impact_ms < a.release_ms;
  const rivals = [];
  for (const c of candidates) {
    if (taken.every((s) => apart(c, s)) && rivals.every((s) => apart(c, s))) rivals.push(c);
  }
  const kept = [];
  const landed = taken.map((s) => s.impact_ms);
  for (const c of rivals.sort((a, b) => a.release_ms - b.release_ms)) {
    const before = landed.concat(kept.map((s) => s.impact_ms)).filter((t) => t <= c.release_ms);
    const last = before.length ? Math.max(...before) : -Infinity;
    if (c.release_ms - last >= RELOAD_MS) kept.push(c);
  }
  return kept;
}

/**
 * The shooting counter. A shot is a swing and then a hit: the stick heard
 * going through (or, where it was not heard, seen), then a sharp impact a
 * believable flight later. Each pair is one shot and its speed.
 *
 * Presents the same surface as the other counters (count, reps, handCounts,
 * meanConfidence, toSubmission) so the capture screen holds it like any other.
 *
 * It does not count with the wall-ball rhythm the sound counter keeps.
 * Shooting has no rhythm -- a run-up, a shot, a jog back -- and on the radar
 * clips that tracker kept footsteps and dropped the net, even when the net
 * was the loudest sound heard. A shot needs both moments: a swing at nothing
 * makes no sound to count it by, and a sound with no swing before it is
 * someone else's noise.
 */
export class ShotSpeedCounter {
  constructor(spec, soundCounter, { distanceYd, release } = {}) {
    this.spec = spec;
    this.sound = soundCounter;
    this.pose = soundCounter.pose;
    this.distanceYd = Number(distanceYd) || (spec.shot && spec.shot.default_distance_yd)
      || DEFAULT_DISTANCE_YD;
    // `release` is the bench's override of the detector thresholds; absent in
    // the product, where the detector runs on its constants.
    this.releases = new ReleaseDetector(release || {});
    this.listener = new ShotListener();
    if (soundCounter.detector) {
      soundCounter.detector.onHop = (t, e, floor, warm) => this.listener.hop(t, e, floor, warm);
    }
    this.bodyAt = [];
    this.settled = [];
    this.cache = null;
  }

  pushAudio(block, tMs) {
    this.sound.pushAudio(block, tMs);
    this.cache = null;
  }

  /** Pose: forwarded to the sound counter, and read for the release. */
  pushPose(landmarks, tMs) {
    this.sound.pushPose(landmarks, tMs);
    this.releases.push({ t: tMs, ...stickHand(landmarks) });
    if (Array.isArray(landmarks) && landmarks.length) this.bodyAt.push(tMs);
    this.cache = null;
  }

  /** Was someone in frame around tMs? */
  bodyNear(tMs) {
    let n = 0;
    for (const t of this.bodyAt) if (Math.abs(t - tMs) <= BODY_WINDOW_MS) n += 1;
    return n >= BODY_MIN_FRAMES;
  }

  /** Every shot so far: { release_ms, impact_ms, via, mph }, oldest first. */
  get shots() {
    if (this.cache) return this.cache;
    const metres = distanceMetres(this.distanceYd);
    const L = this.listener;
    const heard = L.swings.filter((s) => this.bodyNear(s.t_ms))
      .map((s) => ({ t_ms: s.t_ms, via: 'swing' }));
    let fresh = pairShots(heard, L.impacts, metres, this.settled);
    // Hits no heard swing explains may still have a release the camera saw.
    const used = new Set(fresh.map((s) => s.impact_ms));
    const seen = this.releases.releases.filter((r) => this.bodyNear(r.t_ms))
      .map((r) => ({ t_ms: r.t_ms, via: 'pose' }));
    fresh = fresh.concat(pairShots(
      seen, L.impacts.filter((i) => !used.has(i.t_ms)), metres, this.settled.concat(fresh),
    )).sort((a, b) => a.impact_ms - b.impact_ms);

    // Settle what nothing heard from now on could change, and forget what
    // came before it, so a long session costs no more per frame than a short.
    const horizon = L.lastMs - SETTLE_MS;
    while (fresh.length && fresh[0].impact_ms < horizon) this.settled.push(fresh.shift());
    const last = this.settled[this.settled.length - 1];
    if (last) {
      L.drop(last.impact_ms + 1);
      while (this.bodyAt.length && this.bodyAt[0] < last.impact_ms - BODY_WINDOW_MS) {
        this.bodyAt.shift();
      }
    }
    this.cache = this.settled.concat(fresh);
    return this.cache;
  }

  get count() { return this.shots.length; }
  get meanConfidence() { return this.sound.meanConfidence; }

  /** The stick hand for a shot, read the way wall ball reads it. */
  _hand(shot) {
    if (!this.spec.tracks_handedness || typeof this.sound.handFor !== 'function') return 'none';
    return this.sound.handFor(shot.impact_ms);
  }

  handCounts() {
    let left = 0, right = 0;
    for (const s of this.shots) {
      const hand = this._hand(s);
      if (hand === 'left') left += 1;
      else if (hand === 'right') right += 1;
    }
    return { left, right };
  }

  /** The last shot's speed, for the live readout. */
  get lastMph() {
    const s = this.shots;
    return s.length ? s[s.length - 1].mph : null;
  }

  get reps() {
    const confidence = Math.round((this.sound.meanConfidence || 0) * 1000) / 1000;
    // The raw times, never the speed: the server works the speed out again
    // itself from them and the distance.
    return this.shots.map((s) => ({
      t_ms: Math.round(s.impact_ms),
      hand: this._hand(s),
      confidence,
      source: 'sound',
      impact_t_ms: Math.round(s.impact_ms),
      release_t_ms: Math.round(s.release_ms),
    }));
  }

  toSubmission(sessionId, nonce, durationMs, extra = {}) {
    this.releases.finish();
    this.listener.finish();
    this.cache = null;
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
