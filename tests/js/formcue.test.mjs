/**
 * Form cues during a hold: one short instruction at a time, and never about form when the camera angle is the problem.
 *
 * There is no real video behind these yet. The athlete here is a skeleton with ordinary proportions, placed in a wall
 * sit and photographed from any angle by a pinhole camera, then fed through the same knee-angle code the clock uses.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import { LANDMARKS, computeSignal } from '../../offdays/web/static/counter.js';
import { FACING, FORM_CUES, FormCoach, TIMING, shoulderRatio, viewOf } from '../../offdays/web/static/formcue.js';
import { SPECS } from './specs.mjs';

const WALL_SIT = SPECS.find((d) => d.key === 'gen_wall_sit');
const PORTRAIT = 9 / 16, LANDSCAPE = 16 / 9;

/** A wall sit with the knee at `knee` degrees, seen from `yaw` (90 = side-on, 0 = facing the athlete). */
function frame({ knee = 90, yaw = 90, aspect = PORTRAIT, camHeight = 0.6, dist = 3 } = {}) {
  const drop = ((knee - 90) * Math.PI) / 180;
  const body = {};
  for (const [side, z] of [['left', 1], ['right', -1]]) {
    const kneeAt = [0.42, 0.50, 0.10 * z];
    const hip = [kneeAt[0] - 0.42 * Math.cos(drop), kneeAt[1] + 0.42 * Math.sin(drop), 0.12 * z];
    body[`${side}_ankle`] = [0.42, 0.08, 0.10 * z];
    body[`${side}_knee`] = kneeAt;
    body[`${side}_hip`] = hip;
    body[`${side}_shoulder`] = [hip[0], hip[1] + 0.50, 0.19 * z];
  }
  const a = (yaw * Math.PI) / 180;
  const cam = [dist * Math.cos(a), camHeight, dist * Math.sin(a)];
  const fwd = [-Math.cos(a), -Math.sin(a)], right = [Math.sin(a), -Math.cos(a)];
  const out = LANDMARKS.map(() => ({ x: 0.5, y: 0.5, z: 0, visibility: 0 }));
  for (const [name, p] of Object.entries(body)) {
    const dx = p[0] - cam[0], dy = p[1] - cam[1], dz = p[2] - cam[2];
    const depth = dx * fwd[0] + dz * fwd[1];
    const u = (dx * right[0] + dz * right[1]) / depth, v = -dy / depth;
    out[LANDMARKS.indexOf(name)] = { x: 0.5 + (1.2 * u) / aspect, y: 0.5 + 1.2 * v, z: 0, visibility: 0.99 };
  }
  return out;
}

/** Run the coach over a script of [seconds, pose] stretches at ten frames a second. Returns every frame's cue. */
function run(script, aspect = PORTRAIT) {
  const coach = new FormCoach(WALL_SIT);
  const seen = [];
  let t = 0;
  for (const [seconds, pose] of script) {
    for (let i = 0; i < seconds * 10; i += 1, t += 100) {
      const landmarks = pose === null ? null : frame({ ...pose, aspect });
      const value = landmarks ? computeSignal(landmarks, WALL_SIT) : null;
      seen.push({ t, cue: coach.update({ landmarks, value, aspect, now: t }) });
    }
  }
  return { seen, coach };
}
const keys = (seen) => seen.map((f) => (f.cue ? f.cue.key : null));
const changes = (seen) => keys(seen).reduce((acc, k, i) => (i && acc[acc.length - 1][1] === k ? acc : [...acc, [seen[i].t, k]]), []);
const spoken = (seen) => seen.filter((f) => f.cue && f.cue.say).map((f) => [f.t, f.cue.key]);

test('which way the athlete faces is read from the shoulders, the same upright or sideways', () => {
  for (const aspect of [PORTRAIT, LANDSCAPE, 1]) {
    const at = (yaw) => shoulderRatio(frame({ yaw, aspect }), aspect);
    assert.ok(at(90) < 0.15, `side-on ${at(90)}`);
    assert.ok(Math.abs(at(0) - 0.76) < 0.08, `front-on ${at(0)}`);
    assert.strictEqual(viewOf(at(90)), 'side');
    assert.strictEqual(viewOf(at(70)), 'side');
    assert.strictEqual(viewOf(at(45)), 'between');
    assert.strictEqual(viewOf(at(20)), 'front');
    assert.strictEqual(viewOf(at(0)), 'front');
  }
});

test('an upright phone that ignored its shape would call side-on front-on', () => {
  const landmarks = frame({ yaw: 60, aspect: PORTRAIT });
  assert.strictEqual(viewOf(shoulderRatio(landmarks, PORTRAIT)), 'side');
  assert.notStrictEqual(viewOf(shoulderRatio(landmarks, 1)), 'side');
});

test('no shoulders or hips in view means no reading', () => {
  assert.strictEqual(shoulderRatio(null), null);
  const hidden = frame({});
  hidden[LANDMARKS.indexOf('left_shoulder')].visibility = 0.2;
  assert.strictEqual(shoulderRatio(hidden), null);
  assert.strictEqual(viewOf(null), null);
});

test('a good wall sit from the side is left alone', () => {
  const { seen } = run([[20, { knee: 90 }]]);
  assert.deepStrictEqual(changes(seen), [[0, null]]);
});

test('sitting too high from the side: told to bend, once, then praised when it is fixed', () => {
  const { seen, coach } = run([[5, { knee: 150 }], [6, { knee: 92 }]]);
  assert.deepStrictEqual(changes(seen), [[0, null], [1500, 'high'], [6000, 'good'], [9000, null]]);
  assert.deepStrictEqual(spoken(seen), [[1500, 'high'], [6000, 'good']]);
  assert.strictEqual(seen[20].cue.text, FORM_CUES.gen_wall_sit.high);
  assert.deepStrictEqual(coach.log.map((l) => l.key), ['high', 'good']);
});

test('sitting too low is told to come up', () => {
  const { seen } = run([[4, { knee: 55 }]]);
  assert.deepStrictEqual(changes(seen), [[0, null], [1500, 'low']]);
  assert.strictEqual(seen[30].cue.text, FORM_CUES.gen_wall_sit.low);
});

test('a cue that is ignored is said again, but not nagged', () => {
  const { seen } = run([[20, { knee: 150 }]]);
  assert.deepStrictEqual(spoken(seen), [[1500, 'high'], [9500, 'high'], [17500, 'high']]);
});

test('a wobble shorter than the wait says nothing', () => {
  const { seen } = run([[3, { knee: 90 }], [1.2, { knee: 150 }], [5, { knee: 90 }]]);
  assert.deepStrictEqual(changes(seen), [[0, null]]);
});

test('a perfect wall sit filmed from the front is told to turn, never to bend', () => {
  for (const camHeight of [0.2, 1.0]) {
    const { seen } = run([[10, { knee: 90, yaw: 0, camHeight }]]);
    const said = new Set(keys(seen).filter(Boolean));
    assert.deepStrictEqual([...said], ['turn'], `phone ${camHeight} m up`);
    assert.strictEqual(seen[30].cue.text, FORM_CUES.gen_wall_sit.turn);
  }
});

test('turning to the side after being told to is praised', () => {
  const { seen } = run([[4, { knee: 90, yaw: 0 }], [5, { knee: 90, yaw: 90 }]]);
  const order = changes(seen).map(([, k]) => k);
  assert.deepStrictEqual(order, [null, 'turn', 'good', null]);
});

test('form is only ever talked about from the side, whatever the pose and angle', () => {
  for (const yaw of [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]) {
    for (const knee of [50, 70, 90, 110, 130, 150, 170]) {
      for (const camHeight of [0.2, 0.6, 1.2]) {
        const { seen, coach } = run([[4, { knee, yaw, camHeight }]]);
        const said = new Set(keys(seen).filter(Boolean));
        if (said.has('high') || said.has('low')) {
          assert.strictEqual(viewOf(coach.ratio), 'side', `yaw ${yaw} knee ${knee} cam ${camHeight}`);
        }
      }
    }
  }
});

test('it never corrects an athlete while the clock is running', () => {
  for (const yaw of [0, 15, 30, 45, 60, 75, 90]) {
    for (const knee of [60, 75, 90, 105, 120, 135]) {
      const landmarks = frame({ knee, yaw });
      const value = computeSignal(landmarks, WALL_SIT);
      const running = value >= WALL_SIT.counter.down_threshold && value <= WALL_SIT.counter.up_threshold;
      const { seen } = run([[4, { knee, yaw }]]);
      if (running) assert.deepStrictEqual(changes(seen), [[0, null]], `yaw ${yaw} knee ${knee} reads ${value}`);
    }
  }
});

test('from the side, the direction of the cue is the direction of the mistake', () => {
  for (const aspect of [PORTRAIT, LANDSCAPE]) {
    // Well outside the band on either phone orientation. (The clock's knee angle reads differently on an upright and a
    // sideways phone, so a sit only a little off can be inside the band on one and outside on the other.)
    for (const knee of [150, 165]) assert.ok(keys(run([[3, { knee }]], aspect).seen).includes('high'), `${knee}`);
    for (const knee of [40, 50]) assert.ok(keys(run([[3, { knee }]], aspect).seen).includes('low'), `${knee}`);
  }
});

test('stepping out of frame keeps the last cue and does not crash', () => {
  const { seen } = run([[3, { knee: 150 }], [2, null], [1, { knee: 150 }]]);
  assert.deepStrictEqual(changes(seen), [[0, null], [1500, 'high']]);
});

test('two spoken cues are never closer than the minimum gap', () => {
  const { seen } = run([[2, { knee: 150 }], [1.2, { knee: 90 }], [3, { knee: 50 }], [3, { knee: 90 }], [3, { knee: 150 }]]);
  const times = spoken(seen).map(([t]) => t);
  for (let i = 1; i < times.length; i += 1) assert.ok(times[i] - times[i - 1] >= TIMING.MIN_GAP_MS, `${times}`);
  assert.ok(times.length >= 2);
});

test('only drills with cues and a band are coached', () => {
  assert.ok(FormCoach.supports(WALL_SIT));
  assert.ok(!FormCoach.supports(SPECS.find((d) => d.key === 'lax_wall_ball_strong')));
  assert.ok(!FormCoach.supports(null));
  for (const key of Object.keys(FORM_CUES)) assert.ok(SPECS.find((d) => d.key === key), `${key} is a real drill`);
});

test('the words follow the house rules', () => {
  for (const words of Object.values(FORM_CUES)) {
    assert.deepStrictEqual(Object.keys(words).sort(), ['good', 'high', 'low', 'turn']);
    for (const text of Object.values(words)) {
      assert.ok(!/[\u2013\u2014]| - /.test(text), text);
      assert.ok(!/\b(he|she|his|her|him)\b/i.test(text), text);
      assert.ok(text.length <= 60, `short enough to say in one breath: ${text}`);
    }
  }
});

test('the thresholds are in a sane order', () => {
  assert.ok(FACING.SIDE_MAX < FACING.FRONT_MIN && FACING.FRONT_MIN < 0.78);
  assert.ok(TIMING.MIN_GAP_MS < TIMING.REPEAT_MS && TIMING.SETTLE_MS <= TIMING.DWELL_MS);
});
