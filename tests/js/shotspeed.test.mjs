/**
 * Shot speed, from release to the sound of the impact.
 *
 * The cases are worked by hand from distance / flight, with the sound's trip
 * back to the phone taken off: at 8 yards (7.315m) that is 21.3ms.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import {
  shotSpeedMph, distanceMetres, ReleaseDetector, ShotSpeedCounter,
  DEFAULT_DISTANCE_YD, SPEED_OF_SOUND_MS, MIN_RELEASE_GAP_MS,
  RELEASE_MIN_HEIGHT, RELEASE_MIN_HAND_SPEED,
} from '../../offdays/web/static/shotspeed.js';

const EIGHT_YD = distanceMetres(8);

/** Impact time heard for a ball at `mph` over `metres`, released at `release`. */
function heardAt(release, mph, metres) {
  const flightMs = (metres / (mph / 2.236936)) * 1000;
  const backMs = (metres / SPEED_OF_SOUND_MS) * 1000;
  return release + flightMs + backMs;
}

test('a 60 mph shot from 8 yards reads 60 mph', () => {
  const impact = heardAt(1000, 60, EIGHT_YD);
  assert.strictEqual(Math.round(shotSpeedMph(1000, impact, EIGHT_YD)), 60);
});

test('the sound travelling back is taken off, not left in', () => {
  // Leaving the ~21ms out at 8 yards would read a 60 mph shot as ~55.
  const impact = heardAt(0, 60, EIGHT_YD);
  const naive = (EIGHT_YD / ((impact - 0) / 1000)) * 2.236936;
  assert.ok(naive < 56);
  assert.ok(Math.abs(shotSpeedMph(0, impact, EIGHT_YD) - 60) < 0.5);
});

test('distance scales: the same flight from further is a faster shot', () => {
  const near = shotSpeedMph(0, heardAt(0, 50, distanceMetres(6)), distanceMetres(6));
  const far = shotSpeedMph(0, heardAt(0, 50, distanceMetres(12)), distanceMetres(12));
  assert.ok(Math.abs(near - 50) < 0.5 && Math.abs(far - 50) < 0.5);
});

test('impossible flights give no speed rather than a wild one', () => {
  assert.strictEqual(shotSpeedMph(1000, 1010, EIGHT_YD), null, 'faster than any shot');
  assert.strictEqual(shotSpeedMph(1000, 900, EIGHT_YD), null, 'impact before release');
  assert.strictEqual(shotSpeedMph(1000, 4000, EIGHT_YD), null, 'a lob into a fence');
  assert.strictEqual(shotSpeedMph(0, 500, 0), null, 'no distance');
});

test('an unset distance falls back to 8 yards', () => {
  assert.strictEqual(distanceMetres(undefined), DEFAULT_DISTANCE_YD * 0.9144);
  assert.strictEqual(distanceMetres(-3), DEFAULT_DISTANCE_YD * 0.9144);
});

/** A stick hand: cradling low, then a snap forward above the shoulder. */
function shotFrames(start, { hand = 'right' } = {}) {
  const frames = [];
  // Cradle: hand at chest height, barely moving.
  for (let i = 0; i < 10; i += 1) frames.push({ t: start + i * 33, height: -0.6, x: 3.0, hand });
  // Load and snap: hand above the shoulder, sweeping forward fast, fastest in
  // the middle (the release), then follow-through drops below.
  const xs = [3.0, 3.1, 3.3, 3.7, 4.3, 4.7, 4.9];
  xs.forEach((x, i) => frames.push({ t: start + 330 + i * 33, height: 0.3, x, hand }));
  for (let i = 0; i < 6; i += 1) frames.push({ t: start + 560 + i * 33, height: -0.8, x: 4.9, hand });
  return frames;
}

test('release: the fastest frame of the snap, once per shot', () => {
  const rd = new ReleaseDetector();
  shotFrames(0).forEach((f) => rd.push(f));
  rd.finish();
  assert.strictEqual(rd.releases.length, 1);
  // Fastest step is 3.7 -> 4.3 at t = 330 + 4*33 = 462.
  assert.strictEqual(rd.releases[0].t_ms, 462);
  assert.strictEqual(rd.releases[0].hand, 'right');
});

test('release: cradling and a low arm swing are not shots', () => {
  const rd = new ReleaseDetector();
  for (let i = 0; i < 60; i += 1) {
    rd.push({ t: i * 33, height: -0.7, x: 3 + Math.sin(i / 3) * 0.4, hand: 'left' });
  }
  rd.finish();
  assert.strictEqual(rd.releases.length, 0);
});

test('release: the product runs on the shipped constants; only the bench overrides them', () => {
  // capture.html passes no options, so the detector must read the constants.
  const rd = new ReleaseDetector();
  assert.strictEqual(rd.minHeight, RELEASE_MIN_HEIGHT);
  assert.strictEqual(rd.minHandSpeed, RELEASE_MIN_HAND_SPEED);
  assert.strictEqual(rd.minGapMs, MIN_RELEASE_GAP_MS);
  // scripts/shotcal/replay.mjs sweeps thresholds through the counter; a snap
  // too slow for the shipped threshold is a release under a lower one.
  const strict = new ShotSpeedCounter({ shot: {} }, fakeSound(), { distanceYd: 8 });
  const loose = new ShotSpeedCounter({ shot: {} }, fakeSound(), { distanceYd: 8,
    release: { minHandSpeed: 0.5 } });
  const slowSnap = [];
  for (let i = 0; i < 8; i += 1) slowSnap.push({ t: i * 33, height: 0.3, x: 3 + i * 0.04, hand: 'right' });
  slowSnap.push({ t: 300, height: -0.8, x: 3.3, hand: 'right' });
  slowSnap.forEach((f) => { strict.releases.push(f); loose.releases.push(f); });
  strict.releases.finish(); loose.releases.finish();
  assert.strictEqual(strict.releases.releases.length, 0);
  assert.strictEqual(loose.releases.releases.length, 1);
});

test('release: two shots far enough apart are two releases', () => {
  const rd = new ReleaseDetector();
  [...shotFrames(0), ...shotFrames(4000)].forEach((f) => rd.push(f));
  rd.finish();
  assert.strictEqual(rd.releases.length, 2);
  assert.ok(rd.releases[1].t_ms - rd.releases[0].t_ms >= MIN_RELEASE_GAP_MS);
});

/**
 * A sound counter stand-in. Holds a detector whose `onHop` the shot counter
 * hooks, so a test can play hop energies straight into the counter -- the
 * same numbers `ImpactDetector` would hand it, without synthesising audio.
 */
function fakeSound() {
  return {
    pose: { meanConfidence: 0.8 },
    detector: { onsets: [], onHop: null },
    get meanConfidence() { return 0.8; },
    pushAudio() {}, pushPose() {},
    toSubmission(sid, nonce, dur, extra) { return { session_id: sid, nonce, duration_ms: dur, ...extra }; },
  };
}

/**
 * A soundtrack, as hop energies over a floor of 1: quiet, with swings (a
 * 100ms hum at 10x, centred on the release) and hits (one 10ms hop at 30x).
 */
function play(counter, { from = 0, until, swings = [], hits = [], hum = [], thuds = [] }) {
  const loud = (t) => {
    if (hits.some((h) => Math.abs(t - h) < 5)) return 30;
    if (thuds.some((h) => t >= h - 5 && t < h + 75)) return 40;
    if (swings.some((r) => t >= r - 50 && t <= r + 50)) return 10;
    if (hum.some(([a, b]) => t >= a && t < b)) return 10;
    return 1;
  };
  for (let t = from; t <= until; t += 10) counter.sound.detector.onHop(t, loud(t), 1, t < 300);
}

/** Someone in frame for the whole of [from, to], at 30fps. */
const BODY = Array.from({ length: 33 }, () => ({ x: 0.5, y: 0.5, z: 0, visibility: 0.2 }));
function inFrame(counter, from, to) {
  for (let t = from; t <= to; t += 33) counter.pushPose(BODY, t);
}

function shooter(distanceYd = 8) {
  return new ShotSpeedCounter({ shot: { default_distance_yd: 8 } }, fakeSound(), { distanceYd });
}

test('counter: a swing and then a hit is a shot, timed from the swing', () => {
  const c = shooter();
  const r1 = 1000, r2 = 5000;
  const hits = [heardAt(r1, 55, EIGHT_YD), heardAt(r2, 65, EIGHT_YD)].map((t) => Math.round(t / 10) * 10);
  inFrame(c, 0, 7000);
  play(c, { until: 7000, swings: [r1, r2], hits });
  assert.strictEqual(c.count, 2);
  // Hits are on a 10ms grid, so within a mph or so.
  assert.ok(Math.abs(c.shots[0].mph - 55) < 2, String(c.shots[0].mph));
  assert.ok(Math.abs(c.shots[1].mph - 65) < 2, String(c.shots[1].mph));
  assert.strictEqual(c.shots[0].via, 'swing');
  assert.ok(Math.abs(c.lastMph - 65) < 2);
});

test('counter: the first hit after the swing is the shot, not the louder rattle after it', () => {
  const c = shooter();
  inFrame(c, 0, 4000);
  // Into the net at 60 mph, then the ball drops and hits a pipe 400ms later.
  const hit = Math.round(heardAt(1000, 60, EIGHT_YD) / 10) * 10;
  play(c, { until: 4000, swings: [1000], hits: [hit, hit + 400] });
  assert.strictEqual(c.count, 1);
  assert.ok(Math.abs(c.shots[0].mph - 60) < 2);
});

test('counter: a rustle on the run-up does not take the swing\'s place', () => {
  const c = shooter();
  inFrame(c, 0, 4000);
  const hit = Math.round(heardAt(1500, 60, EIGHT_YD) / 10) * 10;
  // A swing-like hum 700ms before the real swing could also reach the hit.
  play(c, { until: 4000, swings: [800, 1500], hits: [hit] });
  assert.strictEqual(c.count, 1);
  assert.strictEqual(c.shots[0].release_ms, 1500);
});

test('counter: a swing at nothing, or a bang with no swing, is not a shot', () => {
  const c = shooter();
  inFrame(c, 0, 6000);
  play(c, { until: 6000, swings: [1000], hits: [4800] });
  // The swing at 1000 is 3.8s before the bang: slower than any shot.
  assert.strictEqual(c.count, 0);
});

test('counter: a loud sustained noise is not a hit', () => {
  const c = shooter();
  inFrame(c, 0, 4000);
  // A hum where the hit would be: loud, but no edge.
  play(c, { until: 4000, swings: [1000], hum: [[1300, 1500]] });
  assert.strictEqual(c.count, 0);
});

test('counter: a ball into a slack net -- a ringing thud, not a click -- is a hit', () => {
  const c = shooter();
  inFrame(c, 0, 4000);
  // 80ms at 16dB, straight up from quiet: no single hop stands above its
  // neighbours, but it arrived from nothing.
  const hit = Math.round(heardAt(1000, 60, EIGHT_YD) / 10) * 10;
  play(c, { until: 4000, swings: [1000], thuds: [hit] });
  assert.strictEqual(c.count, 1);
  assert.ok(Math.abs(c.shots[0].mph - 60) < 2);
});

test('counter: a swing that runs on into the follow-through is timed from its first crest', () => {
  const c = shooter();
  inFrame(c, 0, 4000);
  const hit = Math.round(heardAt(1000, 60, EIGHT_YD) / 10) * 10;
  // One unbroken 200ms hum: the run-up into the swing, crest at the release,
  // a dip, then a second crest on the follow-through.
  const level = (t) => {
    if (t >= 900 && t < 960) return 6;
    if (t >= 960 && t <= 1040) return 12;
    if (t > 1040 && t < 1080) return 7;
    if (t >= 1080 && t <= 1140) return 12;
    return 1;
  };
  for (let t = 0; t <= 4000; t += 10) {
    const e = Math.abs(t - hit) < 5 ? 30 : level(t);
    c.sound.detector.onHop(t, e, 1, t < 300);
  }
  assert.strictEqual(c.count, 1);
  assert.ok(Math.abs(c.shots[0].release_ms - 1000) <= 10, String(c.shots[0].release_ms));
});

test('counter: the jog after a shot does not make a second one', () => {
  const c = shooter();
  inFrame(c, 0, 5000);
  const hit = Math.round(heardAt(1000, 60, EIGHT_YD) / 10) * 10;
  // A rustle and a step 700ms after the ball landed: a tight pair on its own.
  play(c, { until: 5000, swings: [1000, hit + 700], hits: [hit, hit + 950] });
  assert.strictEqual(c.count, 1);
  assert.strictEqual(c.shots[0].release_ms, 1000);
});

test('counter: nobody in frame, no shot', () => {
  const c = shooter();
  const hit = Math.round(heardAt(1000, 60, EIGHT_YD) / 10) * 10;
  inFrame(c, 3000, 5000);
  play(c, { until: 5000, swings: [1000], hits: [hit] });
  assert.strictEqual(c.count, 0);
});

test('counter: where the swing is not heard, a release the camera saw times the shot', () => {
  const c = shooter();
  inFrame(c, 0, 4000);
  c.releases.releases.push({ t_ms: 1000, hand: 'right' });
  const hit = Math.round(heardAt(1000, 60, EIGHT_YD) / 10) * 10;
  play(c, { until: 4000, hits: [hit] });
  assert.strictEqual(c.count, 1);
  assert.strictEqual(c.shots[0].via, 'pose');
  assert.ok(Math.abs(c.shots[0].mph - 60) < 2);
});

test('counter: the distance set is the distance timed over', () => {
  const at10 = shooter(10);
  const ten = distanceMetres(10);
  const hit = Math.round(heardAt(1000, 70, ten) / 10) * 10;
  inFrame(at10, 0, 4000);
  play(at10, { until: 4000, swings: [1000], hits: [hit] });
  assert.ok(Math.abs(at10.shots[0].mph - 70) < 2, String(at10.shots[0].mph));
});

test('counter: a long session settles as it goes, and keeps every shot', () => {
  const c = shooter();
  const swings = [], hits = [];
  for (let i = 0; i < 40; i += 1) {
    const r = 1000 + i * 3000;
    swings.push(r);
    hits.push(Math.round(heardAt(r, 50 + (i % 5) * 5, EIGHT_YD) / 10) * 10);
  }
  const end = 1000 + 40 * 3000;
  // Fed a second at a time and asked as it goes, as the live screen does.
  for (let t0 = 0; t0 <= end; t0 += 1000) {
    inFrame(c, t0, t0 + 999);
    play(c, { from: t0, until: t0 + 990, swings, hits });
    void c.count;
  }
  assert.strictEqual(c.count, 40);
  assert.ok(c.shots.every((s, i) => Math.abs(s.mph - (50 + (i % 5) * 5)) < 2));
  // Settled shots are kept; the swings, hits and frames behind them are not
  // (40 shots is 4000 frames; a few seconds of them remain).
  assert.ok(c.listener.swings.length <= 2 && c.listener.impacts.length <= 2,
    `${c.listener.swings.length} swings, ${c.listener.impacts.length} hits kept`);
  assert.ok(c.bodyAt.length < 400, `${c.bodyAt.length} frames kept`);
});

test('submission: raw times and the distance go up, never a speed', () => {
  const c = shooter(9);
  inFrame(c, 0, 4000);
  const hit = Math.round(heardAt(1000, 55, distanceMetres(9)) / 10) * 10;
  play(c, { until: 4000, swings: [1000], hits: [hit] });
  const sub = c.toSubmission(1, 'n', 30000);
  assert.strictEqual(sub.shot_distance_yd, 9);
  assert.strictEqual(sub.reps.length, 1);
  assert.strictEqual(sub.reps[0].release_t_ms, 1000);
  assert.strictEqual(sub.reps[0].impact_t_ms, hit);
  assert.strictEqual(sub.reps[0].source, 'sound');
  assert.ok(!('mph' in sub.reps[0]) && !('speed' in sub.reps[0]));
});
