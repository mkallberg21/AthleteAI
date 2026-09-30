/**
 * Sound counting tests, driven by synthetic audio.
 *
 * The shapes here are taken from real footage of a fifteen-year-old on a
 * rebounder: one sharp impact per throw at a steady 1.35-1.45s, a softer catch
 * about 430ms after most impacts when the phone is on the stick side, wind
 * under all of it, and the odd stray knock. The two real clips themselves
 * cannot live in the repo -- they are footage of a minor -- so their impact
 * timings are reproduced as synthetic sound instead.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import {
  ImpactDetector, SoundRepCounter, estimatePeriod, groupCycles, trackBeats,
  catchesFor, releaseTimes, CATCH_MIN_AFTER_MS,
} from '../../offdays/web/static/sound.js';
import { LANDMARKS, RepCounter, wallBallSignal, LONE_WRIST_TOP_MIN } from '../../offdays/web/static/counter.js';
import { SPECS } from './specs.mjs';

const spec = (key) => SPECS.find((d) => d.key === key);
const IDX = Object.fromEntries(LANDMARKS.map((n, i) => [n, i]));

/** Deterministic noise, so a failure is reproducible. */
function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32) * 2 - 1;
}

/**
 * A mono track: low wind noise, plus a decaying burst at each (t_ms, level).
 * Bursts are broadband noise under a fast exponential decay, which is what a
 * ball on a net or a wall sounds like at this resolution.
 */
function track(durationMs, events, { sampleRate = 48000, wind = 0.004, seed = 7 } = {}) {
  const n = Math.round((durationMs / 1000) * sampleRate);
  const out = new Float32Array(n);
  const r = rng(seed);
  // Wind: low-passed noise, so it is mostly below the detector's high-pass.
  let lp = 0;
  for (let i = 0; i < n; i += 1) { lp += 0.02 * (r() - lp); out[i] = lp * wind * 40; }
  for (const { t, level } of events) {
    const start = Math.round((t / 1000) * sampleRate);
    const len = Math.round(0.06 * sampleRate);
    for (let k = 0; k < len && start + k < n; k += 1) {
      out[start + k] += level * r() * Math.exp(-k / (0.008 * sampleRate));
    }
  }
  return out;
}

function detect(samples, sampleRate = 48000) {
  const d = new ImpactDetector({ sampleRate });
  for (let i = 0; i < samples.length; i += 128) {
    d.push(samples.subarray(i, i + 128), (i / sampleRate) * 1000);
  }
  return d;
}

/** Real IMG_6827 impact times, and the catches heard after most of them. */
const IMPACTS = [410, 1890, 3340, 4790, 6270, 7720, 9250, 10710, 12110, 13550, 15000, 16490, 17930, 19380, 20880];
const CATCHES = [860, 2320, 3780, 6720, 8530, 11130, 13960, 16890, 19800];

test('sound: every impact is heard, at the right time, over wind', () => {
  const d = detect(track(21500, IMPACTS.map((t) => ({ t, level: 0.3 }))));
  assert.strictEqual(d.onsets.length, IMPACTS.length);
  d.onsets.forEach((o, i) => assert.ok(Math.abs(o.t_ms - IMPACTS[i]) <= 20,
    `impact ${i} heard at ${o.t_ms}, expected ${IMPACTS[i]}`));
});

test('sound: works at 44.1kHz as well as 48kHz', () => {
  const sr = 44100;
  const d = detect(track(21500, IMPACTS.map((t) => ({ t, level: 0.3 })), { sampleRate: sr }), sr);
  assert.strictEqual(d.onsets.length, IMPACTS.length);
});

test('sound: a quiet yard and a loud one count the same', () => {
  // The threshold is relative to the background, not a fixed level.
  for (const [wind, level] of [[0.001, 0.05], [0.02, 0.9]]) {
    const d = detect(track(21500, IMPACTS.map((t) => ({ t, level })), { wind }));
    assert.strictEqual(d.onsets.length, IMPACTS.length, `wind ${wind}, level ${level}`);
  }
});

test('sound: wind alone is not a rep', () => {
  const d = detect(track(30000, [], { wind: 0.03 }));
  assert.strictEqual(d.onsets.length, 0);
});

test('sound: catches are folded into the throw they end, not counted', () => {
  const events = [
    ...IMPACTS.map((t) => ({ t, level: 0.3 })),
    ...CATCHES.map((t) => ({ t, level: 0.25 })),
  ].sort((a, b) => a.t - b.t);
  const d = detect(track(21500, events));
  assert.strictEqual(d.onsets.length, IMPACTS.length + CATCHES.length);
  const g = groupCycles(d.onsets, 700);
  assert.strictEqual(g.cycles.length, IMPACTS.length);
  assert.strictEqual(g.folded.length, CATCHES.length);
  g.cycles.forEach((c, i) => assert.ok(Math.abs(c.t_ms - IMPACTS[i]) <= 20));
});

test('sound: the rhythm is the throw cycle, not two throws and not throw-to-catch', () => {
  const onsets = [...IMPACTS, ...CATCHES].sort((a, b) => a - b).map((t) => ({ t_ms: t }));
  const p = estimatePeriod(onsets, 700);
  assert.ok(p > 1350 && p < 1550, `period ${p}`);
});

test('sound: a throw well faster than the athlete\'s pace still counts', () => {
  // One quick one in a steady session: 900ms against a 1450ms rhythm.
  const times = [];
  let t = 500;
  for (let i = 0; i < 20; i += 1) { times.push(t); t += i === 10 ? 900 : 1450; }
  const g = groupCycles(times.map((x) => ({ t_ms: x })), 700);
  assert.strictEqual(g.cycles.length, 20);
});

test('sound: before the rhythm is known, the drill\'s own minimum keeps catches out', () => {
  // Three throws and their catches: too few to measure a rhythm.
  const onsets = [0, 430, 1450, 1880, 2900, 3330].map((t) => ({ t_ms: t }));
  assert.strictEqual(groupCycles(onsets, 700).cycles.length, 3);
});

/**
 * A brick wall, from IMG_9808 and IMG_9809: the ball comes back slower, so
 * the catch lands 60% of the way to the next throw, and a wind-up can knock
 * the stick. Onset strengths are as measured (multiples of the background).
 */
const WALL_9808 = [
  [1000, 152.8], [3020, 8.9], [4820, 14.7], [6600, 44.1], [8500, 75.4], [9280, 8],
  [10260, 46.9], [12190, 23.2], [13370, 9.7], [14220, 25.6], [16120, 36],
  [18420, 31.3], [20250, 22.2],
].map(([t_ms, strength]) => ({ t_ms, strength }));
const WALL_9808_THROWS = [1000, 3020, 4820, 6600, 8500, 10260, 12190, 14220, 16120, 18420, 20250];

const WALL_9809 = [
  [580, 52], [2870, 8.2], [5180, 85.5], [6300, 9.8], [7450, 14.1], [8140, 8.7],
  [8980, 7.6], [9990, 13.3], [12180, 31.9], [12360, 9.6], [14740, 506.9], [17010, 57.2],
].map(([t_ms, strength]) => ({ t_ms, strength }));
const WALL_9809_THROWS = [580, 2870, 5180, 7450, 9990, 12180, 14740, 17010];

test('sound: on a brick wall, a catch late in the cycle is not taken for the throw', () => {
  // A first-sound-after-a-gate rule took the 13.37s catch here and folded
  // the real impact at 14.22s behind it. Right count, wrong rep.
  const g = groupCycles(WALL_9808, 700);
  assert.deepStrictEqual(g.cycles.map((c) => c.t_ms), WALL_9808_THROWS);
});

test('sound: a stick knocked in the wind-up is not taken for the throw', () => {
  // 8.98s is the stick tapped on the way back; 9.99s is the ball on the wall.
  const g = groupCycles(WALL_9809, 700);
  assert.deepStrictEqual(g.cycles.map((c) => c.t_ms), WALL_9809_THROWS);
});

test('sound: a pause does not cost the reps before it', () => {
  const times = [];
  for (let i = 0; i < 10; i += 1) times.push(500 + i * 1450);
  for (let i = 0; i < 10; i += 1) times.push(40000 + i * 1450);   // after a drink
  const onsets = times.map((t_ms) => ({ t_ms, strength: 20 }));
  assert.strictEqual(trackBeats(onsets, 1450, 700).length, 20);
});

test('sound: nothing heard, nothing counted', () => {
  assert.strictEqual(groupCycles([], 700).cycles.length, 0);
});

// --- hands --------------------------------------------------------------------

/** A skeleton with shoulders at y=0.35 and torso 0.25, wrists as given. */
function skeleton({ left = null, right = null } = {}) {
  const pts = LANDMARKS.map(() => ({ x: 0.5, y: 0.5, z: 0, visibility: 0.95 }));
  pts[IDX.left_shoulder] = { x: 0.45, y: 0.35, z: 0, visibility: 0.95 };
  pts[IDX.right_shoulder] = { x: 0.55, y: 0.35, z: 0, visibility: 0.95 };
  pts[IDX.left_hip] = { x: 0.46, y: 0.60, z: 0, visibility: 0.95 };
  pts[IDX.right_hip] = { x: 0.54, y: 0.60, z: 0, visibility: 0.95 };
  // A wrist given as a height is visible; null is hidden behind the body.
  const at = (h) => 0.35 - h * 0.25;
  pts[IDX.left_wrist] = { x: 0.42, y: left === null ? 0.5 : at(left), z: 0, visibility: left === null ? 0.1 : 0.95 };
  pts[IDX.right_wrist] = { x: 0.58, y: right === null ? 0.5 : at(right), z: 0, visibility: right === null ? 0.1 : 0.95 };
  return pts;
}

test('hands: a lone wrist low down is not assumed to be the top hand', () => {
  // Filmed from behind: the stick-side wrist is hidden and the bottom hand is
  // what the camera sees. This used to credit every rep to the wrong hand.
  const sig = wallBallSignal(skeleton({ left: -0.5 }));
  assert.strictEqual(sig.hand, 'none');
  assert.ok(sig.value < LONE_WRIST_TOP_MIN);
});

test('hands: a lone wrist up at the shoulder line is the top hand', () => {
  assert.strictEqual(wallBallSignal(skeleton({ left: 0.05 })).hand, 'left');
  assert.strictEqual(wallBallSignal(skeleton({ right: 0.3 })).hand, 'right');
});

test('hands: with both wrists visible the higher one is on top, as before', () => {
  assert.strictEqual(wallBallSignal(skeleton({ left: -0.6, right: 0.2 })).hand, 'right');
  assert.strictEqual(wallBallSignal(skeleton({ left: 0.2, right: -0.6 })).hand, 'left');
});

/** Run a sound counter over impacts with pose frames showing `hand` throwing. */
function session(hand, { hidden = false } = {}) {
  const drill = spec('lax_wall_ball_offhand');
  const sr = 48000;
  const sc = new SoundRepCounter(drill, new RepCounter(drill), { sampleRate: sr });
  const audio = track(21500, IMPACTS.map((t) => ({ t, level: 0.3 })));
  for (let i = 0; i < audio.length; i += 128) sc.pushAudio(audio.subarray(i, i + 128), (i / sr) * 1000);
  for (let t = 0; t < 21500; t += 33) {
    // Top hand peaks ~500ms before each impact, dips to catch in between.
    const next = IMPACTS.find((x) => x >= t) ?? 99999;
    const h = next - t < 700 ? 0.2 : -0.4;
    const top = hidden ? null : h;
    const bottom = h - 0.6;
    sc.pushPose(skeleton(hand === 'left' ? { left: top, right: bottom } : { right: top, left: bottom }), t);
  }
  return sc;
}

test('hands: each sound rep takes the top hand from the throw before it', () => {
  const sc = session('left');
  assert.strictEqual(sc.count, IMPACTS.length);
  assert.deepStrictEqual(sc.handCounts(), { left: IMPACTS.length, right: 0 });
  assert.ok(sc.reps.every((r) => r.source === 'sound'));
});

test('hands: when the camera cannot see the top hand, the rep counts but no hand is claimed', () => {
  const sc = session('right', { hidden: true });
  assert.strictEqual(sc.count, IMPACTS.length);
  assert.deepStrictEqual(sc.handCounts(), { left: 0, right: 0 });
});

test('submission: only timestamps, hands and a confidence leave the phone', () => {
  const payload = session('left').toSubmission(1, 'n', 21500);
  assert.strictEqual(payload.reps.length, IMPACTS.length);
  for (const r of payload.reps) {
    assert.deepStrictEqual(Object.keys(r).sort(), ['confidence', 'hand', 'source', 't_ms']);
  }
  assert.ok(!JSON.stringify(payload).match(/sample|audio|wav/i));
});

test('sound: a microphone that opens on silence does not count its own start', () => {
  // Found on the live path: a few blocks of digital zeros, then the yard.
  // Judged against a floor of zero, the yard arriving was itself an impact.
  const sr = 48000;
  const yard = track(23000, IMPACTS.map((t) => ({ t: t + 1000, level: 0.3 })), { wind: 0.01 });
  const samples = new Float32Array(yard.length + sr / 10);   // 100ms of zeros first
  samples.set(yard, sr / 10);
  const d = detect(samples, sr);
  assert.strictEqual(d.onsets.length, IMPACTS.length);
  assert.ok(d.onsets[0].t_ms > 1000, `first onset at ${d.onsets[0].t_ms}`);
});

// --- release time -------------------------------------------------------------

/** A sound counter fed onsets directly, as the detector would have heard them. */
function counterFor(onsets) {
  const drill = spec('lax_wall_ball_offhand');
  const sc = new SoundRepCounter(drill, new RepCounter(drill), { sampleRate: 48000 });
  sc.detector.onsets.push(...onsets.map((o) => ({ ...o })));
  return sc;
}

/** Impacts every `period` ms, loud; optional softer extras at `offsets` after each. */
function steady(n, period, offsets = [], { start = 500, impact = 30, extra = 10 } = {}) {
  const out = [];
  for (let i = 0; i < n; i += 1) {
    const t = start + i * period;
    out.push({ t_ms: t, strength: impact });
    for (const off of offsets) if (i < n - 1) out.push({ t_ms: Math.round(t + off), strength: extra });
  }
  return out.sort((a, b) => a.t_ms - b.t_ms);
}

test('release: rebounder, catch 430ms after each impact -> ~970ms release on every rep', () => {
  const sc = counterFor(steady(15, 1400, [430]));
  assert.strictEqual(sc.count, 15);
  const reps = sc.reps;
  assert.ok(!('release_ms' in reps[0]), 'the first rep has no catch before it');
  for (const r of reps.slice(1)) assert.ok(Math.abs(r.release_ms - 970) <= 5, `release ${r.release_ms}`);
  reps.slice(1).forEach((r) => assert.ok(Number.isInteger(r.release_ms)));
  assert.ok(sc.catchCoverage >= 14 / 15 - 1e-9, `coverage ${sc.catchCoverage}`);
});

test('release: brick wall, catch 60% of the way through the cycle', () => {
  const sc = counterFor(steady(12, 1400, [840]));
  assert.strictEqual(sc.count, 12);
  for (const r of sc.reps.slice(1)) assert.ok(Math.abs(r.release_ms - 560) <= 5, `release ${r.release_ms}`);
  assert.ok(sc.catchCoverage > 0.9);
});

test('release: real brick-wall onsets (IMG_9808) give releases without changing the count', () => {
  const sc = counterFor(WALL_9808);
  assert.deepStrictEqual(sc.reps.map((r) => r.t_ms), WALL_9808_THROWS);
  // 9.28s is the catch before 10.26s; 13.37s before 14.22s.
  const at = Object.fromEntries(sc.reps.map((r) => [r.t_ms, r.release_ms]));
  assert.strictEqual(at[10260], 980);
  assert.strictEqual(at[14220], 850);
});

test('release: no catches heard -> no release_ms, coverage 0', () => {
  const sc = counterFor(steady(10, 1400));
  assert.strictEqual(sc.count, 10);
  assert.ok(sc.reps.every((r) => !('release_ms' in r)));
  assert.strictEqual(sc.catchCoverage, 0);
  assert.strictEqual(counterFor([]).catchCoverage, 0);
});

test('release: a stick tap just after the impact is not the catch', () => {
  // Tap only: nothing else between the throws, so no catch at all.
  const tapOnly = steady(10, 1400, [CATCH_MIN_AFTER_MS - 50], { extra: 25 });
  const g = groupCycles(tapOnly, 700);
  assert.strictEqual(g.cycles.length, 10);
  assert.ok(catchesFor(g.cycles, g.folded, g.periodMs).every((c) => c === null));
  assert.strictEqual(counterFor(tapOnly).catchCoverage, 0);
  // Tap plus a real catch: the catch is taken even though the tap is louder.
  const both = steady(10, 1400, [100, 430], { extra: 10 });
  for (const o of both) if ((o.t_ms - 500) % 1400 === 100) o.strength = 25;
  const sc = counterFor(both);
  assert.strictEqual(sc.count, 10);
  for (const r of sc.reps.slice(1)) assert.strictEqual(r.release_ms, 970);
});

test('release: a stick tapped late in the wind-up is not the catch either', () => {
  // 150ms before the next impact is the throw itself, not the ball arriving.
  const g = groupCycles(steady(10, 1400, [1250], { extra: 25 }), 700);
  assert.ok(catchesFor(g.cycles, g.folded, g.periodMs).every((c) => c === null));
});

test('release: of two sounds in the window the louder is the catch', () => {
  const cycles = [{ t_ms: 0 }, { t_ms: 1400 }];
  const folded = [{ t_ms: 500, strength: 6 }, { t_ms: 700, strength: 12 }];
  assert.deepStrictEqual(catchesFor(cycles, folded, 1400), [700, null]);
  // Unknown strengths: the earliest.
  assert.deepStrictEqual(catchesFor(cycles, [{ t_ms: 700 }, { t_ms: 500 }], 1400), [500, null]);
});

test('release: a pause between throws gives no release for the rep after it', () => {
  const cycles = [{ t_ms: 0 }, { t_ms: 1400 }, { t_ms: 9000 }];
  const folded = [{ t_ms: 430, strength: 9 }, { t_ms: 1830, strength: 9 }];
  const catches = catchesFor(cycles, folded, 1400);
  assert.deepStrictEqual(catches, [430, null, null]);
  assert.deepStrictEqual(releaseTimes(cycles, catches), [null, 970, null]);
});

test('release: hearing catches does not change the count or the reps chosen', () => {
  // The same impacts with and without catches: identical throws either way.
  const bare = counterFor(steady(15, 1400));
  const heard = counterFor(steady(15, 1400, [430]));
  assert.deepStrictEqual(heard.reps.map((r) => r.t_ms), bare.reps.map((r) => r.t_ms));
  assert.strictEqual(heard.count, bare.count);
  // And from real audio: the IMG_6827 impacts with their catches.
  const events = [
    ...IMPACTS.map((t) => ({ t, level: 0.3 })),
    ...CATCHES.map((t) => ({ t, level: 0.25 })),
  ].sort((a, b) => a.t - b.t);
  const sr = 48000;
  const drill = spec('lax_wall_ball_offhand');
  const sc = new SoundRepCounter(drill, new RepCounter(drill), { sampleRate: sr });
  const audio = track(21500, events);
  for (let i = 0; i < audio.length; i += 128) sc.pushAudio(audio.subarray(i, i + 128), (i / sr) * 1000);
  const g = groupCycles(sc.detector.onsets, 700);
  assert.strictEqual(sc.count, IMPACTS.length);
  assert.deepStrictEqual(sc.reps.map((r) => r.t_ms), g.cycles.map((c) => c.t_ms));
  // Every catch in CATCHES lands before a next throw except none; each gives one release.
  const withRelease = sc.reps.filter((r) => 'release_ms' in r);
  assert.strictEqual(withRelease.length, CATCHES.length);
  for (const r of withRelease) {
    const prevCatch = Math.max(...CATCHES.filter((c) => c < r.t_ms));
    assert.ok(Math.abs(r.release_ms - (r.t_ms - prevCatch)) <= 25, `release ${r.release_ms}`);
  }
  assert.ok(Math.abs(sc.catchCoverage - CATCHES.length / IMPACTS.length) < 1e-9);
});

test('submission: a release time is a number, and still nothing audio-shaped leaves', () => {
  const sc = counterFor(steady(10, 1400, [430]));
  const payload = sc.toSubmission(1, 'n', 15000);
  for (const r of payload.reps.slice(1)) {
    assert.deepStrictEqual(Object.keys(r).sort(), ['confidence', 'hand', 'release_ms', 'source', 't_ms']);
    assert.strictEqual(typeof r.release_ms, 'number');
  }
  assert.ok(!JSON.stringify(payload).match(/sample|audio|wav/i));
});

// --- where a heard rep's hand comes from ---------------------------------------

/** A sound counter on any drill, fed onsets directly, with an optional ball tracker. */
function heardOn(key, onsets, ballCounter = null) {
  const drill = spec(key);
  const sc = new SoundRepCounter(drill, new RepCounter(drill), { sampleRate: 48000, ballCounter });
  sc.detector.onsets.push(...onsets.map((o) => ({ ...o })));
  return sc;
}

test('hand_from ball: each heard dribble takes the side of the nearest tracked contact', () => {
  const drill = spec('bkb_crossover');
  assert.strictEqual(drill.sound.hand_from, 'ball');
  // Crossovers at 400ms, alternating hands; the camera times each contact a
  // frame or so off the sound, as a 30fps tracker would.
  const bounces = steady(20, 400);
  const tracked = { reps: bounces.map((o, i) => ({ t_ms: o.t_ms + (i % 2 ? 33 : -40), hand: i % 2 ? 'left' : 'right' })) };
  const sc = heardOn('bkb_crossover', bounces, tracked);
  assert.strictEqual(sc.count, 20);
  const hands = sc.reps.map((r) => r.hand);
  assert.deepStrictEqual(hands.slice(0, 4), ['right', 'left', 'right', 'left']);
  assert.deepStrictEqual(sc.handCounts(), { left: 10, right: 10 });
  assert.ok(sc.reps.every((r) => r.source === 'sound'));
});

test('hand_from ball: a bounce the camera never saw has no hand rather than a guessed one', () => {
  const bounces = steady(12, 400);
  // The tracker only caught every third bounce, and one far off in time.
  const tracked = { reps: [
    ...bounces.filter((_, i) => i % 3 === 0).map((o) => ({ t_ms: o.t_ms, hand: 'right' })),
    { t_ms: bounces[1].t_ms + 250, hand: 'left' }, // outside the window
  ] };
  const sc = heardOn('bkb_dribble', bounces, tracked);
  assert.strictEqual(sc.count, 12);
  const hands = sc.reps.map((r) => r.hand);
  assert.strictEqual(hands.filter((h) => h === 'right').length, 4);
  assert.strictEqual(hands.filter((h) => h === 'left').length, 0);
  assert.ok(hands.filter((h) => h === 'none').length >= 8);
});

test('hand_from none: jump rope never claims a hand, whatever pose sees', () => {
  const drill = spec('gen_jump_rope');
  assert.strictEqual(drill.sound.hand_from, 'none');
  const sc = heardOn('gen_jump_rope', steady(30, 420));
  // Feeding pose must not start collecting a stick signal it would misuse.
  sc.pushPose(skeleton({ right: 0.3 }), 1000);
  assert.strictEqual(sc.frames.length, 0);
  assert.strictEqual(sc.count, 30);
  assert.ok(sc.reps.every((r) => r.hand === 'none'));
  assert.deepStrictEqual(sc.handCounts(), { left: 0, right: 0 });
});

test('hand_from wall_ball is still the default for lacrosse', () => {
  assert.strictEqual(spec('lax_wall_ball').sound.hand_from, 'wall_ball');
  const sc = heardOn('lax_wall_ball', steady(6, 1400));
  assert.strictEqual(sc.handFrom, 'wall_ball');
});
