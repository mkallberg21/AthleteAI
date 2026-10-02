/**
 * Everyday Ground Balls: a timed footwork drill.
 *
 * The clock runs while the athlete is moving and stops while they stand
 * still; direction changes and ground covered are counted from hip travel
 * across the frame. The motion here is synthetic, built to the ranges measured
 * on reference footage: standing and talking at 0.1-0.4 torso lengths per
 * second, the routine at 0.55 and above.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import {
  RepCounter, LANDMARKS, MOVE_MIN_TORSOS, MOTION_WINDOW_MS,
} from '../../offdays/web/static/counter.js';
import { SPECS } from './specs.mjs';

const IDX = Object.fromEntries(LANDMARKS.map((n, i) => [n, i]));
const spec = SPECS.find((d) => d.key === 'lax_ground_ball_everyday');
const TORSO = 0.25;
const FPS = 30;

/** A body at hip x `hx` (frame widths) with the low hand `hand` torsos below the hips. */
function body(hx, hand, torso = TORSO) {
  const p = LANDMARKS.map(() => ({ x: 0.5, y: 0.5, z: 0, visibility: 0.95 }));
  const hipY = 0.6;
  const shY = hipY - torso;
  p[IDX.left_shoulder] = { x: hx - 0.04, y: shY, z: 0, visibility: 0.95 };
  p[IDX.right_shoulder] = { x: hx + 0.04, y: shY, z: 0, visibility: 0.95 };
  p[IDX.left_hip] = { x: hx - 0.03, y: hipY, z: 0, visibility: 0.95 };
  p[IDX.right_hip] = { x: hx + 0.03, y: hipY, z: 0, visibility: 0.95 };
  p[IDX.left_wrist] = { x: hx - 0.05, y: hipY + hand * torso, z: 0, visibility: 0.95 };
  p[IDX.right_wrist] = { x: hx + 0.05, y: hipY - 0.1, z: 0, visibility: 0.95 };
  p[IDX.left_ankle] = { x: hx - 0.03, y: 0.95, z: 0, visibility: 0.95 };
  p[IDX.right_ankle] = { x: hx + 0.03, y: 0.95, z: 0, visibility: 0.95 };
  return p;
}

/** Drive the counter for `seconds` with a position function f(t) -> [hx, hand]. */
function drive(counter, seconds, f, t0 = 0) {
  let t = t0;
  for (let i = 0; i < seconds * FPS; i += 1) {
    const [hx, hand, torso] = f(t / 1000);
    counter.push(body(hx, hand, torso), t);
    t += 1000 / FPS;
  }
  return t;
}

test('the spec is a timed footwork drill, not a rep counter', () => {
  assert.ok(spec, 'lax_ground_ball_everyday ships to the client');
  assert.strictEqual(spec.metric, 'hold');
  assert.strictEqual(spec.signal.kind, 'footwork_motion');
});

test('standing and talking does not run the clock', () => {
  const c = new RepCounter(spec);
  // Small sways and gestures: the 0.1-0.4 band measured on a player at rest.
  drive(c, 20, (s) => [0.5 + 0.004 * Math.sin(s * 3), 0.1 * Math.sin(s * 2)]);
  assert.ok(c.holdMs < 2000, `idle ran the clock for ${c.holdMs}ms`);
  assert.strictEqual(c.footworkSummary().direction_changes, 0);
});

test('working the ball on the spot runs the clock', () => {
  const c = new RepCounter(spec);
  // Hands dipping to the ball and back about twice a second, small shuffles.
  drive(c, 20, (s) => [0.5 + 0.01 * Math.sin(s * 4), 0.35 + 0.35 * Math.sin(s * 12)]);
  assert.ok(c.holdMs > 17000, `only ${c.holdMs}ms of 20s counted as moving`);
});

test('shuffling side to side counts each change of direction', () => {
  const c = new RepCounter(spec);
  // Back and forth across about two torsos of space, every 2 seconds, eight
  // legs: seven turns between them.
  const legs = 8, legSec = 2, span = 2 * TORSO; // frame widths
  drive(c, legs * legSec, (s) => {
    const leg = Math.min(legs - 1, Math.floor(s / legSec));
    const frac = (s % legSec) / legSec;
    const x = leg % 2 === 0 ? 0.3 + span * frac : 0.3 + span * (1 - frac);
    return [x, 0.3 + 0.3 * Math.sin(s * 10)];
  });
  const f = c.footworkSummary();
  assert.ok(f.direction_changes >= 6 && f.direction_changes <= 7,
    `expected 6-7 direction changes, got ${f.direction_changes}`);
  // Each leg is two torsos; about eight legs of it.
  assert.ok(f.ground_torsos > 12 && f.ground_torsos < 18, `ground ${f.ground_torsos}`);
  assert.ok(c.holdMs > (legs * legSec - 2) * 1000);
});

test('a sway smaller than a step is not a direction change', () => {
  const c = new RepCounter(spec);
  const half = (MOVE_MIN_TORSOS * TORSO) * 0.4;
  drive(c, 20, (s) => [0.5 + half * Math.sin(s * 3), 0.4 + 0.4 * Math.sin(s * 10)]);
  assert.strictEqual(c.footworkSummary().direction_changes, 0);
});

test('a camera cut or the phone being moved is not ground covered', () => {
  const c = new RepCounter(spec);
  let t = drive(c, 3, () => [0.5, 0.0]);
  // The torso doubles in size and the body jumps across the frame in one
  // frame: a cut, not a sprint.
  t = drive(c, 3, () => [0.1, 0.0, TORSO * 2], t);
  assert.ok(c.footworkSummary().ground_torsos < MOVE_MIN_TORSOS);
  assert.ok(c.holdMs < MOTION_WINDOW_MS * 2);
});

test('the summary goes up with the session, as numbers only', () => {
  const c = new RepCounter(spec);
  drive(c, 10, (s) => [0.4 + 0.2 * Math.sin(s), 0.3 + 0.3 * Math.sin(s * 10)]);
  const sub = c.toSubmission(1, 'n', 10000);
  assert.deepStrictEqual(Object.keys(sub.footwork).sort(), ['direction_changes', 'ground_torsos']);
  assert.ok(sub.hold_ms > 0);
  assert.deepStrictEqual(sub.reps, []);
});
