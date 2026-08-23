/**
 * Counter engine tests, driven by synthetic pose streams.
 *
 * Each test builds a landmark stream describing a known movement, then asserts
 * the counter recovers the rep count it was built from. This is the only way to
 * check the detector without a camera and a lacrosse stick.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import { RepCounter, computeSignal, wallBallSignal, LANDMARKS } from '../../athleteiq/web/static/counter.js';

const IDX = Object.fromEntries(LANDMARKS.map((n, i) => [n, i]));

/** A neutral standing skeleton; individual landmarks get overridden per frame. */
function baseSkeleton() {
  const pts = LANDMARKS.map(() => ({ x: 0.5, y: 0.5, z: 0, visibility: 0.95 }));
  pts[IDX.left_shoulder] = { x: 0.45, y: 0.35, z: 0, visibility: 0.95 };
  pts[IDX.right_shoulder] = { x: 0.55, y: 0.35, z: 0, visibility: 0.95 };
  pts[IDX.left_hip] = { x: 0.46, y: 0.60, z: 0, visibility: 0.95 };
  pts[IDX.right_hip] = { x: 0.54, y: 0.60, z: 0, visibility: 0.95 };
  pts[IDX.left_knee] = { x: 0.46, y: 0.78, z: 0, visibility: 0.95 };
  pts[IDX.right_knee] = { x: 0.54, y: 0.78, z: 0, visibility: 0.95 };
  pts[IDX.left_ankle] = { x: 0.46, y: 0.95, z: 0, visibility: 0.95 };
  pts[IDX.right_ankle] = { x: 0.54, y: 0.95, z: 0, visibility: 0.95 };
  pts[IDX.left_elbow] = { x: 0.42, y: 0.48, z: 0, visibility: 0.95 };
  pts[IDX.right_elbow] = { x: 0.58, y: 0.48, z: 0, visibility: 0.95 };
  pts[IDX.left_wrist] = { x: 0.42, y: 0.58, z: 0, visibility: 0.95 };
  pts[IDX.right_wrist] = { x: 0.58, y: 0.58, z: 0, visibility: 0.95 };
  pts[IDX.nose] = { x: 0.50, y: 0.22, z: 0, visibility: 0.95 };
  return pts;
}

const SPECS = JSON.parse(process.env.DRILL_SPECS);
const spec = (key) => SPECS.find((d) => d.key === key);

// torso length here is 0.25 (shoulder y 0.35 -> hip y 0.60)
const TORSO = 0.25;

test('wall ball: counts one rep per throw-catch cycle, credited to the top hand', () => {
  const drill = spec('lax_wall_ball');
  const counter = new RepCounter(drill);
  const CYCLES = 25, FPS = 30, CYCLE_MS = 900;
  const framesPerCycle = Math.round((CYCLE_MS / 1000) * FPS);

  let t = 0;
  for (let c = 0; c < CYCLES; c += 1) {
    // Alternate which hand is on top, as an athlete alternating hands would.
    const topIsRight = c % 2 === 0;
    for (let f = 0; f < framesPerCycle; f += 1) {
      const phase = f / framesPerCycle;
      // Height above shoulder line, in torso lengths: dips to -0.15 (receive)
      // and peaks at +0.40 (cocked to throw).
      const h = 0.125 - 0.275 * Math.cos(2 * Math.PI * phase);
      const pts = baseSkeleton();
      const topY = 0.35 - h * TORSO;
      const botY = topY + 0.12;
      pts[IDX.right_wrist] = { x: 0.58, y: topIsRight ? topY : botY, z: 0, visibility: 0.95 };
      pts[IDX.left_wrist] = { x: 0.42, y: topIsRight ? botY : topY, z: 0, visibility: 0.95 };
      counter.push(pts, t);
      t += 1000 / FPS;
    }
  }

  // Smoothing costs at most the first cycle before the signal settles.
  assert.ok(counter.count >= CYCLES - 1 && counter.count <= CYCLES,
    `expected ~${CYCLES} reps, got ${counter.count}`);

  const { left, right } = counter.handCounts();
  assert.ok(left > 0 && right > 0, `expected both hands credited, got L${left}/R${right}`);
  assert.ok(Math.abs(left - right) <= 2,
    `alternating hands should split roughly evenly, got L${left}/R${right}`);
});

test('wall ball: a still athlete produces no reps', () => {
  const counter = new RepCounter(spec('lax_wall_ball'));
  for (let t = 0; t < 30000; t += 33) counter.push(baseSkeleton(), t);
  assert.strictEqual(counter.count, 0, 'standing still must not generate reps');
});

test('wall ball: small jitter at the threshold does not spray phantom reps', () => {
  const drill = spec('lax_wall_ball');
  const counter = new RepCounter(drill);
  // Park the signal right at the up_threshold and add noise. Without
  // hysteresis this is where a naive counter invents hundreds of reps.
  for (let t = 0, i = 0; t < 20000; t += 33, i += 1) {
    const pts = baseSkeleton();
    const h = drill.counter.up_threshold + (i % 2 === 0 ? 0.01 : -0.01);
    pts[IDX.right_wrist] = { x: 0.58, y: 0.35 - h * TORSO, z: 0, visibility: 0.95 };
    pts[IDX.left_wrist] = { x: 0.42, y: 0.50, z: 0, visibility: 0.95 };
    counter.push(pts, t);
  }
  assert.strictEqual(counter.count, 0, 'threshold jitter must not count as reps');
});

test('wall ball: respects the refractory period', () => {
  const drill = spec('lax_wall_ball');
  const counter = new RepCounter(drill);
  // Drive full cycles far faster than min_rep_ms (450ms) allows.
  let t = 0;
  for (let c = 0; c < 60; c += 1) {
    for (const h of [-0.15, 0.45]) {
      const pts = baseSkeleton();
      pts[IDX.right_wrist] = { x: 0.58, y: 0.35 - h * TORSO, z: 0, visibility: 0.95 };
      pts[IDX.left_wrist] = { x: 0.42, y: 0.50, z: 0, visibility: 0.95 };
      counter.push(pts, t);
      t += 100;
    }
  }
  const elapsedSec = t / 1000;
  assert.ok(counter.count <= elapsedSec / (drill.counter.min_rep_ms / 1000),
    `refractory period should cap reps at ${elapsedSec / 0.45}, got ${counter.count}`);
});

test('push-ups: elbow angle cycles count as reps', () => {
  const drill = spec('gen_push_up');
  const counter = new RepCounter(drill);
  const REPS = 12, FPS = 30, CYCLE_MS = 1600;
  const framesPerCycle = Math.round((CYCLE_MS / 1000) * FPS);
  let t = 0;

  for (let r = 0; r < REPS; r += 1) {
    for (let f = 0; f < framesPerCycle; f += 1) {
      const phase = f / framesPerCycle;
      // Elbow angle sweeping 70deg (bottom) to 175deg (locked out).
      const angle = 122.5 - 52.5 * Math.cos(2 * Math.PI * phase);
      const pts = baseSkeleton();
      // Place wrist so shoulder-elbow-wrist forms `angle` at the elbow.
      const sh = { x: 0.45, y: 0.35 }, el = { x: 0.45, y: 0.50 };
      const baseAng = Math.atan2(sh.y - el.y, sh.x - el.x);
      const target = baseAng - (angle * Math.PI) / 180;
      pts[IDX.left_elbow] = { x: el.x, y: el.y, z: 0, visibility: 0.95 };
      pts[IDX.left_wrist] = {
        x: el.x + 0.15 * Math.cos(target),
        y: el.y + 0.15 * Math.sin(target),
        z: 0, visibility: 0.95,
      };
      counter.push(pts, t);
      t += 1000 / FPS;
    }
  }
  assert.ok(counter.count >= REPS - 1 && counter.count <= REPS,
    `expected ~${REPS} push-ups, got ${counter.count}`);
});

test('landmarks out of frame yield no signal rather than a wrong one', () => {
  const drill = spec('lax_wall_ball');
  const pts = baseSkeleton();
  // Drop the hips below the visibility floor -- torso length is unmeasurable.
  pts[IDX.left_hip].visibility = 0.1;
  pts[IDX.right_hip].visibility = 0.1;
  assert.strictEqual(wallBallSignal(pts), null);

  const counter = new RepCounter(drill);
  for (let t = 0; t < 5000; t += 33) counter.push(pts, t);
  assert.strictEqual(counter.count, 0);
});

test('plank: hold time accrues only inside the valid body-line band', () => {
  const drill = spec('gen_plank');
  const counter = new RepCounter(drill);
  let t = 0;
  // 10s in a straight line (~180deg), then 10s sagging (~130deg).
  for (const angle of [180, 130]) {
    for (let i = 0; i < 300; i += 1) {
      const pts = baseSkeleton();
      const hip = { x: 0.50, y: 0.50 };
      const sh = { x: 0.35, y: 0.50 };
      const baseAng = Math.atan2(sh.y - hip.y, sh.x - hip.x);
      const target = baseAng - (angle * Math.PI) / 180;
      pts[IDX.left_shoulder] = { x: sh.x, y: sh.y, z: 0, visibility: 0.95 };
      pts[IDX.left_hip] = { x: hip.x, y: hip.y, z: 0, visibility: 0.95 };
      pts[IDX.left_ankle] = {
        x: hip.x + 0.25 * Math.cos(target),
        y: hip.y + 0.25 * Math.sin(target),
        z: 0, visibility: 0.95,
      };
      counter.push(pts, t);
      t += 33;
    }
  }
  // Roughly the first 10s should count, the sagging 10s should not.
  assert.ok(counter.holdMs > 7000 && counter.holdMs < 12000,
    `expected ~10s of valid hold, got ${counter.holdMs}ms`);
});
