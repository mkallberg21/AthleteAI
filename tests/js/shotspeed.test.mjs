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

test('release: two shots far enough apart are two releases', () => {
  const rd = new ReleaseDetector();
  [...shotFrames(0), ...shotFrames(4000)].forEach((f) => rd.push(f));
  rd.finish();
  assert.strictEqual(rd.releases.length, 2);
  assert.ok(rd.releases[1].t_ms - rd.releases[0].t_ms >= MIN_RELEASE_GAP_MS);
});

/** A sound counter stand-in: the impacts it heard, as `grouping.cycles`. */
function fakeSound(impacts) {
  return {
    pose: { meanConfidence: 0.8 },
    grouping: { cycles: impacts.map((t) => ({ t_ms: t })) },
    get count() { return impacts.length; },
    get meanConfidence() { return 0.8; },
    handCounts: () => ({ left: 0, right: impacts.length }),
    get reps() { return impacts.map((t) => ({ t_ms: t, hand: 'right', confidence: 0.8, source: 'sound' })); },
    pushAudio() {}, pushPose() {},
    toSubmission(sid, nonce, dur, extra) { return { session_id: sid, nonce, duration_ms: dur, ...extra }; },
  };
}

test('counter: each heard shot gets its own release and speed', () => {
  const r1 = 462, r2 = 4462;
  const impacts = [heardAt(r1, 55, EIGHT_YD), heardAt(r2, 65, EIGHT_YD)];
  const c = new ShotSpeedCounter({ shot: { default_distance_yd: 8 } }, fakeSound(impacts), { distanceYd: 8 });
  c.releases.releases.push({ t_ms: r1, hand: 'right' }, { t_ms: r2, hand: 'right' });
  const shots = c.shots;
  assert.strictEqual(Math.round(shots[0].mph), 55);
  assert.strictEqual(Math.round(shots[1].mph), 65);
  assert.strictEqual(Math.round(c.lastMph), 65);
});

test('counter: a shot with no release seen is counted, with no speed', () => {
  const impacts = [heardAt(462, 55, EIGHT_YD)];
  const c = new ShotSpeedCounter({ shot: {} }, fakeSound(impacts), { distanceYd: 8 });
  assert.strictEqual(c.count, 1);
  assert.strictEqual(c.shots[0].mph, null);
  const rep = c.reps[0];
  assert.ok(rep.impact_t_ms > 0);
  assert.strictEqual(rep.release_t_ms, undefined);
});

test('counter: a wide shot (release, no sound) cannot lend its release to the next', () => {
  // Release at 0 hit nothing; the next shot is released at 3000 and heard.
  const impact = heardAt(3000, 60, EIGHT_YD);
  const c = new ShotSpeedCounter({ shot: {} }, fakeSound([impact]), { distanceYd: 8 });
  c.releases.releases.push({ t_ms: 0, hand: 'right' }, { t_ms: 3000, hand: 'right' });
  assert.strictEqual(Math.round(c.shots[0].mph), 60);
});

test('submission: raw times and the distance go up, never a speed', () => {
  const impact = heardAt(462, 55, EIGHT_YD);
  const c = new ShotSpeedCounter({ shot: {} }, fakeSound([impact]), { distanceYd: 9 });
  c.releases.releases.push({ t_ms: 462, hand: 'right' });
  const sub = c.toSubmission(1, 'n', 30000);
  assert.strictEqual(sub.shot_distance_yd, 9);
  assert.strictEqual(sub.reps[0].release_t_ms, 462);
  assert.ok(sub.reps[0].impact_t_ms > 462);
  assert.ok(!('mph' in sub.reps[0]) && !('speed' in sub.reps[0]));
});
