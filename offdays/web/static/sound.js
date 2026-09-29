/**
 * Counting wall ball by ear, on the phone.
 *
 * Pose counts a throw by watching the top hand rise above the shoulder line,
 * and the first real footage showed how badly that travels. A fifteen-year-old
 * filmed from behind got 0 of 16 reps counted, because his body hid the stick
 * hand for the whole clip; the same player throwing off-hand from behind and to
 * the side got 3 of 15, because his releases peak at shoulder height and the
 * threshold wants a textbook overhead one. Both clips were obvious to a person,
 * and just as obvious to the ear: every throw ends in a thump on the rebounder,
 * one per rep, evenly spaced, well clear of everything else in the yard.
 *
 * So for wall ball the count comes from sound and the body supplies the rest:
 * which hand was on top, and whether anyone was in frame throwing at all.
 * Three things shape it.
 *
 * **Nothing is recorded.** Samples are reduced to one energy figure per 10ms as
 * they arrive and discarded. No audio is buffered, and nothing audio-shaped is
 * ever sent anywhere -- a rep is a timestamp, exactly as it is for pose. The
 * microphone is opened as its own stream, never added to the camera's, so the
 * one clip an athlete may choose to send a coach stays as silent as it was.
 *
 * **The threshold is relative to the yard, not absolute.** A rebounder in a
 * quiet garden and a brick wall next to a road differ by more than any fixed
 * level could span, so an onset is judged against a running estimate of the
 * background that follows wind and traffic up and down.
 *
 * **A rep is a cycle, not a sound.** Where the phone is near the stick side the
 * catch is audible too: a softer knock about 430ms after nearly every impact
 * on a net, and on a brick wall -- where the ball comes back slower -- about
 * 60% of the way to the next throw, alongside the odd stick tap in a wind-up.
 * Counting sounds would double those reps. So the athlete's rhythm is learned
 * from the session and the throws are chosen as the loud, evenly spaced
 * subsequence of everything heard (`trackBeats`).
 *
 * Pure apart from `openMicrophone`: `ImpactDetector` and `groupCycles` take
 * numbers and return numbers, so they run the same in a page, on the
 * calibration bench and in a Node test.
 */

import { wallBallSignal } from './counter.js';

/** Analysis hop. Short enough to time an impact to within a video frame. */
export const HOP_MS = 10;

/**
 * How far above the background an onset must rise, as a ratio of energies
 * (about 9dB). Impacts in the reference clips sat at 8-37x a floor that
 * already includes the wind, so this is the lowest value that still keeps
 * the quietest of them.
 */
export const ONSET_RATIO = 7;

/** And how sharply: energy against the mean of the preceding 50ms. */
export const RISE_RATIO = 4;

/**
 * Background estimate time constants. Falls fast and rises slowly, so a quiet
 * moment is believed at once and a run of impacts cannot talk it up.
 */
export const FLOOR_FALL_MS = 200;
export const FLOOR_RISE_MS = 1500;

/**
 * The background is learned for this long before anything can count. A
 * microphone often opens on a few blocks of digital silence, or partway into
 * a sound; judged against a floor of zero, the moment the real signal starts
 * is itself an "impact", and it took the first rep's place when the live path
 * was tested.
 */
export const WARMUP_MS = 300;

/**
 * The floor never drops below this (energy of the first-differenced signal,
 * full scale = 1). A muted or dead-silent input otherwise drives it to zero,
 * and against zero every rustle is a hundred times the background.
 */
export const MIN_FLOOR = 1e-9;

/**
 * Two sounds closer than this are one event: a ball rattling in the net, or
 * the stick knocking the frame on the way through.
 */
export const DEBOUNCE_MS = 150;

/** Cycles needed before the athlete's own rhythm replaces the drill default. */
export const RHYTHM_MIN = 4;

/**
 * How long before an impact the throw that caused it is looked for, when
 * working out which hand was on top. Ball flight to a rebounder a few metres
 * away is a few hundred milliseconds; the release is somewhere in this window.
 */
export const THROW_WINDOW_MS = 1100;

// ---------------------------------------------------------------------------

/**
 * Finds sharp sounds in a stream of audio samples.
 *
 *   const d = new ImpactDetector({ sampleRate: 48000 });
 *   d.push(float32Block, blockStartMs);   // repeatedly, any block length
 *   d.onsets                              // [{ t_ms, strength }]
 */
export class ImpactDetector {
  constructor({ sampleRate } = {}) {
    if (!sampleRate) throw new Error('ImpactDetector needs a sampleRate');
    this.sampleRate = sampleRate;
    this.hop = Math.max(1, Math.round((sampleRate * HOP_MS) / 1000));
    this.acc = 0;
    this.accN = 0;
    this.prev = 0;
    this.floor = null;
    this.startMs = null;
    this.warm = [];
    this.recent = [];
    this.lastOnsetMs = -Infinity;
    this.onsets = [];
  }

  /** Samples arrive in blocks of any length; tMs is the time of block[0]. */
  push(block, tMs) {
    const msPerSample = 1000 / this.sampleRate;
    for (let i = 0; i < block.length; i += 1) {
      // First difference: a cheap high-pass. Wind rumble and the thud of the
      // phone being handled live below a few hundred hertz; a ball on a net or
      // a wall has its edge well above that.
      const d = block[i] - this.prev;
      this.prev = block[i];
      this.acc += d * d;
      this.accN += 1;
      if (this.accN >= this.hop) {
        this._hop(tMs + i * msPerSample);
        this.acc = 0;
        this.accN = 0;
      }
    }
  }

  _hop(tMs) {
    const e = this.acc / this.accN + 1e-12;
    const before = this.recent.length
      ? this.recent.reduce((s, v) => s + v, 0) / this.recent.length : e;
    this.recent.push(e);
    if (this.recent.length > 5) this.recent.shift();

    if (this.startMs === null) this.startMs = tMs;
    if (tMs - this.startMs < WARMUP_MS) {
      // The median of the warm-up, so a sound landing in it cannot set the
      // floor on its own.
      this.warm.push(e);
      const sorted = [...this.warm].sort((a, b) => a - b);
      this.floor = Math.max(MIN_FLOOR, sorted[Math.floor(sorted.length / 2)]);
      return;
    }
    const loud = e > this.floor * ONSET_RATIO && e > before * RISE_RATIO;
    if (loud && tMs - this.lastOnsetMs >= DEBOUNCE_MS) {
      this.lastOnsetMs = tMs;
      this.onsets.push({
        // The hop that crossed started one hop earlier.
        t_ms: Math.max(0, Math.round(tMs - HOP_MS)),
        strength: Math.round((e / this.floor) * 10) / 10,
      });
    }
    if (!loud) {
      const tau = e < this.floor ? FLOOR_FALL_MS : FLOOR_RISE_MS;
      this.floor += (1 - Math.exp(-HOP_MS / tau)) * (e - this.floor);
      this.floor = Math.max(MIN_FLOOR, this.floor);
    }
  }
}

/**
 * Group onsets into throw cycles. Returns `{ cycles, folded, periodMs }`,
 * where `cycles` are the onsets chosen as throws and `folded` everything else
 * heard (catches, bounces, a stick knocking the frame).
 *
 * Until the athlete's rhythm is known, a sound opens a cycle once the drill's
 * minimum cycle has passed since the last one. After that the choice is made
 * over the whole session at once, by `trackBeats`.
 */
export function groupCycles(onsets, minCycleMs) {
  const period = estimatePeriod(onsets, minCycleMs);
  if (!period) {
    const cycles = [], folded = [];
    for (const o of onsets) {
      const last = cycles[cycles.length - 1];
      if (last && o.t_ms - last.t_ms < minCycleMs) folded.push(o);
      else cycles.push(o);
    }
    return { cycles, folded, periodMs: null };
  }
  const chosen = trackBeats(onsets, period, minCycleMs);
  const keep = new Set(chosen);
  return {
    cycles: chosen,
    folded: onsets.filter((o) => !keep.has(o)),
    periodMs: period,
  };
}

/**
 * How hard the tracker holds to the athlete's rhythm: the cost of a gap of
 * r periods is RHYTHM_WEIGHT * ln(r)^2. At 3, taking a catch as a rep costs
 * more than the loudest catch in the reference clips is worth, whether it
 * lands 30% of the way through a cycle (a net, phone on the stick side) or
 * 60% (a brick wall, where the ball comes back slower) -- the case a simple
 * "first sound after the gate" rule got wrong on both brick-wall clips.
 */
export const RHYTHM_WEIGHT = 3;

/**
 * The most a single gap can cost. A pause for a drink is a long gap, not
 * evidence against the reps either side of it, and uncapped it would make
 * the tracker cheaper to start afresh than to keep what came before.
 */
export const MAX_GAP_COST = 2;

/**
 * The most a sound's loudness can add to its worth. Taking a catch as a rep
 * costs at least RHYTHM_WEIGHT * 1.03 in broken spacing (a catch 30-60% of
 * the way through a cycle), so this must stay under about 2 for loudness to
 * choose between sounds without ever overruling the rhythm.
 */
export const MAX_LOUDNESS_BONUS = 1.5;

/**
 * Choose the throws: the subsequence of sounds that best combines loud with
 * evenly spaced. Dynamic programming in the manner of Ellis's beat tracker.
 *
 * Each sound is worth more the louder it is -- in every reference clip the
 * ball hitting the wall or net was the loudest sound of its cycle -- and each
 * step from one chosen sound to the next costs according to how far the gap
 * is from the athlete's period, on a log scale so that half a period and
 * double a period are penalised alike. A catch taken as a rep splits one
 * cheap gap into two expensive ones; a genuine quick throw only swaps one
 * mild irregularity for another, and its own loudness pays for it.
 */
export function trackBeats(onsets, period, minGapMs) {
  const n = onsets.length;
  if (!n) return [];
  // Loudness against the session's own typical sound, not the background: a
  // yard can be quiet enough that every sound is hundreds of times the floor,
  // and a sound's worth growing without limit let one loud catch outvote the
  // rhythm. Bounded so the loudest impact can never pay for a catch.
  const strengths = onsets.map((o) => o.strength || ONSET_RATIO).sort((a, b) => a - b);
  const typical = strengths[Math.floor(strengths.length / 2)];
  const worth = onsets.map((o) => 1 + Math.min(MAX_LOUDNESS_BONUS,
    Math.max(-0.5, Math.log((o.strength || ONSET_RATIO) / typical))));
  const score = new Array(n);
  const back = new Array(n).fill(-1);
  for (let i = 0; i < n; i += 1) {
    score[i] = worth[i];
    for (let j = i - 1; j >= 0; j -= 1) {
      const gap = onsets[i].t_ms - onsets[j].t_ms;
      if (gap < minGapMs) continue;
      const r = Math.log(gap / period);
      const cost = Math.min(MAX_GAP_COST, RHYTHM_WEIGHT * r * r);
      const s = score[j] + worth[i] - cost;
      if (s > score[i]) { score[i] = s; back[i] = j; }
      // Anything further back than a long pause is reached through a later
      // sound more cheaply, so there is no need to look.
      if (gap > period * 4) break;
    }
  }
  let best = 0;
  for (let i = 1; i < n; i += 1) if (score[i] > score[best]) best = i;
  const path = [];
  for (let i = best; i >= 0; i = back[i]) path.push(onsets[i]);
  return path.reverse();
}

/** Longest cycle considered when looking for the athlete's rhythm. */
export const MAX_PERIOD_MS = 4000;

/**
 * Two gaps within this many milliseconds are the same spacing. Absolute, not a
 * share of the gap: a proportional window is wider for longer gaps, collects
 * more chance pairs the longer it gets, and on real footage voted for two
 * throws apart over one. Athletes' cycle-to-cycle wobble in the reference
 * clips was 30-80ms.
 */
export const PERIOD_TOLERANCE_MS = 100;

/**
 * The athlete's cycle length, from the spacing that best explains the sounds.
 *
 * Every pair of sounds up to MAX_PERIOD_MS apart votes for its gap. Impact to
 * next impact and catch to next catch both vote for the true cycle, so it
 * collects the most support; impact-to-catch is shorter than any real cycle
 * and is never a candidate, and catch-to-next-impact collects only the catches.
 * The obvious alternative -- the median gap between provisional cycles --
 * falls apart in exactly the case that matters: on a phone close enough to
 * hear catches well, enough of them slip through the opening gate to drag the
 * median down to the gate itself, and every catch after that counts as a rep.
 *
 * Whole multiples of the cycle (two throws apart) vote too, and on a session
 * with a missed impact or two can come close, so the shortest candidate with
 * nearly the most support wins. Null until there are enough sounds to say.
 */
export function estimatePeriod(onsets, minCycleMs) {
  if (onsets.length < RHYTHM_MIN + 1) return null;
  const gaps = [];
  for (let i = 0; i < onsets.length; i += 1) {
    for (let j = i + 1; j < onsets.length; j += 1) {
      const g = onsets[j].t_ms - onsets[i].t_ms;
      if (g > MAX_PERIOD_MS) break;
      if (g >= minCycleMs) gaps.push(g);
    }
  }
  if (!gaps.length) return null;
  gaps.sort((a, b) => a - b);
  // Support for each gap: how many gaps fall within tolerance of it. Two
  // pointers over the sorted list keeps this linear in the number of gaps.
  const support = new Array(gaps.length);
  let lo = 0, hi = 0;
  for (let i = 0; i < gaps.length; i += 1) {
    const g = gaps[i];
    while (gaps[lo] < g - PERIOD_TOLERANCE_MS) lo += 1;
    while (hi + 1 < gaps.length && gaps[hi + 1] <= g + PERIOD_TOLERANCE_MS) hi += 1;
    support[i] = hi - lo + 1;
  }
  const best = Math.max(...support);
  if (best < RHYTHM_MIN) return null;
  const i = support.findIndex((s) => s >= best * 0.8);
  // Centre of that cluster, not its edge.
  const g = gaps[i];
  const cluster = gaps.filter((x) => x >= g && x <= g + 2 * PERIOD_TOLERANCE_MS);
  return cluster[Math.floor(cluster.length / 2)];
}

/**
 * The wall-ball counter when a microphone is available.
 *
 * Wraps the ordinary pose `RepCounter` rather than replacing it: pose still
 * runs on every frame, still supplies the session's confidence and still
 * counts on its own if the microphone is lost. What changes is where reps come
 * from -- sound cycles -- and where each rep's hand comes from: the top hand
 * seen during the throw that ended in that impact.
 *
 * Presents the same surface as `RepCounter` (count, reps, handCounts,
 * meanConfidence, toSubmission) so the capture screen does not need to know
 * which one it is holding.
 */
export class SoundRepCounter {
  constructor(spec, poseCounter, { sampleRate }) {
    this.spec = spec;
    this.pose = poseCounter;
    this.detector = new ImpactDetector({ sampleRate });
    this.minCycleMs = (spec.sound && spec.sound.min_cycle_ms) || 700;
    // Recent top-hand readings, only as far back as a throw window reaches.
    // Each sound's hand is decided once, from these, and then kept on the
    // sound -- the live screen asks for the count every frame, and rescanning
    // a whole session's frames for every rep each time does not survive a
    // long session on a phone.
    this.frames = [];
    this.cached = null;
  }

  /** Audio: a block of samples starting at tMs on the session clock. */
  pushAudio(block, tMs) {
    const before = this.detector.onsets.length;
    this.detector.push(block, tMs);
    if (this.detector.onsets.length !== before) this.cached = null;
  }

  /** Video: one frame of landmarks at tMs on the session clock. */
  pushPose(landmarks, tMs) {
    this.pose.push(landmarks, tMs);
    const sig = wallBallSignal(landmarks);
    this.frames.push({ t: tMs, hand: sig ? sig.hand : 'none', value: sig ? sig.value : null });
    // A sound is settled once the video has caught up with it.
    for (const o of this.detector.onsets) {
      if (o.hand === undefined && o.t_ms <= tMs) o.hand = this.handFor(o.t_ms);
    }
    const keepFrom = tMs - THROW_WINDOW_MS - 2000;
    let drop = 0;
    while (drop < this.frames.length && this.frames[drop].t < keepFrom) drop += 1;
    if (drop) this.frames.splice(0, drop);
  }

  /**
   * Which hand was on top for the throw that produced an impact at tMs: the
   * hand at the highest top-hand reading in the window before it. 'none' when
   * no frame in the window could say.
   */
  handFor(tMs) {
    let best = null;
    for (const f of this.frames) {
      if (f.t > tMs) break;
      if (f.t < tMs - THROW_WINDOW_MS || f.hand === 'none' || f.value === null) continue;
      if (!best || f.value > best.value) best = f;
    }
    return best ? best.hand : 'none';
  }

  get grouping() {
    if (!this.cached) this.cached = groupCycles(this.detector.onsets, this.minCycleMs);
    return this.cached;
  }

  /** A sound's hand, settling it now if the video never caught up with it. */
  _hand(o) {
    if (!this.spec.tracks_handedness) return 'none';
    if (o.hand === undefined) o.hand = this.handFor(o.t_ms);
    return o.hand;
  }

  get reps() {
    const confidence = Math.round(this.pose.meanConfidence * 1000) / 1000;
    return this.grouping.cycles.map((c) => ({
      t_ms: c.t_ms, hand: this._hand(c), confidence, source: 'sound',
    }));
  }

  get count() { return this.grouping.cycles.length; }

  get meanConfidence() { return this.pose.meanConfidence; }

  handCounts() {
    let left = 0, right = 0;
    for (const c of this.grouping.cycles) {
      // Unsettled sounds are not counted for a side yet rather than guessed.
      const hand = this.spec.tracks_handedness ? c.hand : 'none';
      if (hand === 'left') left += 1;
      else if (hand === 'right') right += 1;
    }
    return { left, right };
  }

  get debug() {
    const g = this.grouping;
    return {
      ...this.pose.debug,
      source: 'sound',
      count: g.cycles.length,
      sounds: this.detector.onsets.length,
      folded: g.folded.length,
      period_ms: g.periodMs,
    };
  }

  toSubmission(sessionId, nonce, durationMs, extra = {}) {
    return this.pose.toSubmission(sessionId, nonce, durationMs, {
      reps: this.reps,
      ...extra,
    });
  }
}

/**
 * Open the microphone and deliver sample blocks to `onBlock(float32, tMs)`,
 * where tMs is on the `performance.now()` clock the pose loop uses.
 *
 * Its own stream, never mixed into the camera's. Echo cancellation, noise
 * suppression and auto gain are all switched off: each of them is built to
 * remove exactly the short sharp transients this is listening for.
 *
 * Resolves to `{ sampleRate, stop }`. Rejects if the microphone is refused or
 * missing, and the caller falls back to counting from pose.
 */
export async function openMicrophone(onBlock) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    video: false,
  });
  const ctx = new AudioContext();
  await ctx.audioWorklet.addModule(new URL('./sound-worklet.js', import.meta.url));
  const source = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, 'offdays-blocks');
  // The worklet stamps each block with the audio clock; this maps it onto the
  // page clock once, which is accurate to well within a video frame for a
  // session's length.
  const offsetMs = performance.now() - ctx.currentTime * 1000;
  node.port.onmessage = (e) => onBlock(e.data.samples, e.data.t * 1000 + offsetMs);
  source.connect(node);
  // Not connected to the speakers: nothing is played back, and a node that
  // goes nowhere still runs because the worklet keeps itself alive.
  return {
    sampleRate: ctx.sampleRate,
    // Browsers start an AudioContext suspended unless a tap is recent enough,
    // and the camera and pose model take long enough to load that it often
    // is not. Called again from the Start tap, which always is.
    resume() { return ctx.state === 'suspended' ? ctx.resume() : Promise.resolve(); },
    stop() {
      node.port.onmessage = null;
      source.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      ctx.close();
    },
  };
}
