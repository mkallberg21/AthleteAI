/**
 * The setup check before Start.
 *
 * One sentence, most important problem first, and "ready" only after the
 * picture has been good for a while. These pin the order and the timing,
 * because a gate that says "hold still" while the feet are out of frame
 * sends the athlete the wrong way.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import { LANDMARKS } from '../../offdays/web/static/counter.js';
import {
  SetupGate, assessFrame, needsFeet, STEADY_MS, STALE_MS, SILENCE_WINDOW_MS,
  TORSO_MIN_FRAC, TORSO_MAX_FRAC, SILENT_RMS,
} from '../../offdays/web/static/setup.js';
import { SPECS } from './specs.mjs';

const IDX = Object.fromEntries(LANDMARKS.map((n, i) => [n, i]));
const spec = (key) => SPECS.find((d) => d.key === key);

/** A whole body, torso `torso` frame-heights tall, feet optional. */
function body({ torso = 0.25, feet = true, hips = true } = {}) {
  const p = LANDMARKS.map(() => ({ x: 0.5, y: 0.5, z: 0, visibility: 0.1 }));
  const hipY = 0.6, shY = hipY - torso;
  p[IDX.left_shoulder] = { x: 0.45, y: shY, z: 0, visibility: 0.95 };
  p[IDX.right_shoulder] = { x: 0.55, y: shY, z: 0, visibility: 0.95 };
  p[IDX.left_hip] = { x: 0.46, y: hipY, z: 0, visibility: hips ? 0.95 : 0.2 };
  p[IDX.right_hip] = { x: 0.54, y: hipY, z: 0, visibility: hips ? 0.95 : 0.2 };
  p[IDX.left_ankle] = { x: 0.46, y: hipY + torso * 1.6, z: 0, visibility: feet ? 0.9 : 0.2 };
  p[IDX.right_ankle] = { x: 0.54, y: hipY + torso * 1.6, z: 0, visibility: feet ? 0.9 : 0.2 };
  return p;
}

test('a good frame has no issue', () => {
  assert.equal(assessFrame(body()).issue, null);
});

test('nobody, then torso, then size, then feet -- in that order', () => {
  assert.equal(assessFrame(null).issue, 'nobody');
  assert.equal(assessFrame(body({ hips: false, feet: false })).issue, 'torso');
  assert.equal(assessFrame(body({ torso: TORSO_MIN_FRAC - 0.01, feet: false })).issue, 'far');
  assert.equal(assessFrame(body({ torso: TORSO_MAX_FRAC + 0.01, feet: false })).issue, 'close');
  assert.equal(assessFrame(body({ feet: false })).issue, 'feet');
});

test('hands-only drills do not ask for the feet', () => {
  assert.equal(needsFeet(spec('lax_wall_ball')), false);
  assert.equal(needsFeet(spec('lax_shooting')), false);
  assert.equal(needsFeet(spec('squat')), true);
  assert.equal(assessFrame(body({ feet: false }), { needsFeet: false }).issue, null);
});

test('ready only after the frame has been good for STEADY_MS', () => {
  const gate = new SetupGate(spec('squat'));
  let t = 0;
  for (; t < STEADY_MS - 100; t += 33) gate.pushFrame(body(), t);
  assert.equal(gate.status(t).ready, false);
  assert.match(gate.status(t).message, /Hold still/);
  for (; t <= STEADY_MS + 100; t += 33) gate.pushFrame(body(), t);
  assert.equal(gate.status(t).ready, true);
});

test('a bad frame resets the steady clock', () => {
  const gate = new SetupGate(spec('squat'));
  let t = 0;
  for (; t < STEADY_MS + 200; t += 33) gate.pushFrame(body(), t);
  assert.equal(gate.status(t).ready, true);
  gate.pushFrame(body({ feet: false }), t);
  assert.equal(gate.status(t).ready, false);
  assert.match(gate.status(t).message, /feet/);
  for (let i = 0; i < 5; i += 1) { t += 33; gate.pushFrame(body(), t); }
  assert.equal(gate.status(t).ready, false, 'five good frames is not steady');
});

test('no frames for STALE_MS reads as nobody in frame', () => {
  const gate = new SetupGate(spec('squat'));
  let t = 0;
  for (; t < STEADY_MS + 200; t += 33) gate.pushFrame(body(), t);
  assert.equal(gate.status(t).ready, true);
  assert.equal(gate.status(t + STALE_MS + 1).ready, false);
  assert.match(gate.status(t + STALE_MS + 1).message, /Nobody/);
});

test('a silent microphone is reported, a quiet field is not', () => {
  const quiet = new Float32Array(128).fill(SILENT_RMS * 3);
  const silent = new Float32Array(128).fill(SILENT_RMS / 10);
  for (const [block, expectReady] of [[quiet, true], [silent, false]]) {
    const gate = new SetupGate(spec('lax_wall_ball'), { listens: true });
    let t = 0;
    for (; t < STEADY_MS + SILENCE_WINDOW_MS + 200; t += 33) {
      gate.pushFrame(body({ feet: false }), t);
      gate.pushAudio(block, t);
    }
    const s = gate.status(t);
    assert.equal(s.ready, expectReady, s.message);
    if (!expectReady) assert.match(s.message, /microphone/);
  }
});

test('a drill that does not listen never complains about the microphone', () => {
  const gate = new SetupGate(spec('squat'));
  let t = 0;
  for (; t < STEADY_MS + SILENCE_WINDOW_MS + 200; t += 33) {
    gate.pushFrame(body(), t);
    gate.pushAudio(new Float32Array(128), t);
  }
  assert.equal(gate.status(t).ready, true);
});

test('silence is not judged before a second of audio has arrived', () => {
  const gate = new SetupGate(spec('lax_wall_ball'), { listens: true });
  let t = 0;
  for (; t < STEADY_MS + 200; t += 33) gate.pushFrame(body({ feet: false }), t);
  gate.pushAudio(new Float32Array(128), t);
  assert.equal(gate.status(t).ready, true);
});
