/**
 * The diagnostics readout.
 *
 * This exists because footage of a child training must never leave their
 * phone, which rules out the normal way of debugging a detector -- send the
 * developer a video. So the diagnostic is numbers instead: the signal, the two
 * thresholds it has to cross, and whether it crossed them.
 *
 * These tests check the readout tells the truth about the counter's state,
 * because a debug panel that lies is worse than none -- it sends whoever
 * reads it in the wrong direction with confidence.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import { RepCounter, LANDMARKS } from '../../offdays/web/static/counter.js';
import { SPECS } from './specs.mjs';


const spec = (key) => SPECS.find((d) => d.key === key);
const IDX = Object.fromEntries(LANDMARKS.map((n, i) => [n, i]));

/** A skeleton with the knee bent to a given angle, for squat counting. */
function skeletonAtKnee(deg) {
  const pts = LANDMARKS.map(() => ({ x: 0.5, y: 0.5, z: 0, visibility: 0.95 }));
  const rad = (deg * Math.PI) / 180;
  pts[IDX.left_hip] = { x: 0.5, y: 0.50, z: 0, visibility: 0.95 };
  pts[IDX.left_knee] = { x: 0.5, y: 0.65, z: 0, visibility: 0.95 };
  pts[IDX.left_ankle] = {
    x: 0.5 + 0.15 * Math.sin(Math.PI - rad),
    y: 0.65 + 0.15 * Math.cos(Math.PI - rad),
    z: 0, visibility: 0.95,
  };
  return pts;
}

test('the readout names the two thresholds a rep must cross', () => {
  const drill = spec('gen_squat');
  const c = new RepCounter(drill);
  const d = c.debug;
  assert.equal(d.drill, 'gen_squat');
  assert.ok(Number.isFinite(d.armAt), 'arm threshold missing');
  assert.ok(Number.isFinite(d.fireAt), 'fire threshold missing');
  assert.notEqual(d.armAt, d.fireAt);
});

test('it reports raw and smoothed separately', () => {
  // The gap between them is how you tell a jittery landmark from a smoothing
  // constant that has flattened the excursion below the threshold.
  const c = new RepCounter(spec('gen_squat'));
  let t = 0;
  for (const angle of [170, 120, 170, 120]) {
    c.push(skeletonAtKnee(angle), (t += 100));
  }
  const d = c.debug;
  assert.ok(Number.isFinite(d.raw));
  assert.ok(Number.isFinite(d.smoothed));
  assert.notEqual(d.raw, d.smoothed, 'smoothing should lag a changing signal');
});

test('it reports the armed state honestly', () => {
  const c = new RepCounter(spec('gen_squat'));
  let t = 0;
  assert.equal(c.debug.armed, false, 'should start unarmed');
  // Hold deep long enough for smoothing to settle below the arm threshold.
  for (let i = 0; i < 40; i += 1) c.push(skeletonAtKnee(80), (t += 60));
  assert.equal(c.debug.armed, true, 'deep hold should arm the counter');
});

test('the rep count in the readout matches the counter', () => {
  const c = new RepCounter(spec('gen_squat'));
  let t = 0;
  for (let rep = 0; rep < 3; rep += 1) {
    for (let i = 0; i < 25; i += 1) c.push(skeletonAtKnee(80), (t += 40));
    for (let i = 0; i < 25; i += 1) c.push(skeletonAtKnee(175), (t += 40));
  }
  assert.equal(c.debug.count, c.count);
  assert.ok(c.debug.count > 0, 'three deep squats should count');
});

test('the cycle excursion shows whether firing was ever possible', () => {
  // The single most useful number here: if the excursion never spans the gap
  // between the thresholds, the drill cannot fire and the problem is the
  // threshold rather than the athlete.
  const c = new RepCounter(spec('gen_squat'));
  let t = 0;
  for (let i = 0; i < 40; i += 1) c.push(skeletonAtKnee(80), (t += 50));
  const d = c.debug;
  assert.ok(Number.isFinite(d.cycleMin) && Number.isFinite(d.cycleMax));
  assert.ok(d.cycleMax >= d.cycleMin);
});

test('it carries units so a number is interpretable', () => {
  assert.equal(new RepCounter(spec('gen_squat')).debug.units, 'deg');
  assert.equal(new RepCounter(spec('gen_pull_up')).debug.units, 'frame heights');
});

test('a hold drill reports no rep thresholds rather than nonsense', () => {
  const d = new RepCounter(spec('gen_plank')).debug;
  assert.equal(d.metric, 'hold');
  assert.equal(d.armAt, null);
  assert.equal(d.fireAt, null);
});

test('the readout exposes no landmarks or frames', () => {
  // It is a substitute for sending video, so it must not smuggle any. The
  // whole premise is that a diagnostic can be numbers.
  const c = new RepCounter(spec('gen_squat'));
  c.push(skeletonAtKnee(120), 100);
  const dumped = JSON.stringify(c.debug);
  for (const leak of ['x', 'visibility', 'landmark']) {
    assert.ok(
      !JSON.parse(dumped).hasOwnProperty(leak),
      `debug readout exposes ${leak}`,
    );
  }
  // No nested object big enough to be a skeleton.
  for (const value of Object.values(c.debug)) {
    if (value && typeof value === 'object') {
      assert.ok(Object.keys(value).length < 8, 'debug carries a large object');
    }
  }
});

test('every shipped drill produces a readable readout', () => {
  // A panel that throws on some drill is a panel nobody trusts.
  for (const drill of SPECS) {
    const d = new RepCounter(drill).debug;
    assert.equal(d.drill, drill.key);
    assert.ok(d.units);
    assert.equal(typeof d.armed, 'boolean');
  }
});
