/**
 * Shooting distance from everything the phone has.
 *
 * One scene is pinned against tests/test_distance.py so the phone's preview
 * and the server's answer cannot drift. The rest checks each factor earns
 * its place: refused when unreadable, named when it disagrees, weighed by
 * its own error when it is used.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import {
  estimateDistance, fuse, torsoForAge, GOAL_WIDTH_M, DEFAULT_FOCAL, YD_PER_M, TYPED_SIGMA_M,
} from '../../offdays/web/static/distance.js';
import { SceneWatcher, findGoal, GoalColour, GOAL_SEEDS, inWindow } from '../../offdays/web/static/scene.js';
import { LANDMARKS } from '../../offdays/web/static/counter.js';

const PARITY_SCENE = {
  typed_yd: 10, view_w: 720, view_h: 1280,
  goal: { w: 0.24, h: 0.22, cx: 0.15, base_y: 0.05, seen: 40, of: 50 },
  athlete: { torso: 0.20, cx: -0.3, feet_y: 0.6 }, pitch_deg: 8,
};

test('matches the server on the pinned scene', () => {
  const r = estimateDistance(PARITY_SCENE, { age: 13 });
  assert.strictEqual(r.source, 'camera+set');
  assert.ok(Math.abs(r.distance_m * YD_PER_M - 9.25) < 0.02, String(r.distance_m * YD_PER_M));
  assert.ok(Math.abs(r.plus_minus_m * YD_PER_M - 0.81) < 0.02, String(r.plus_minus_m * YD_PER_M));
  assert.deepStrictEqual(r.factors.map((f) => f.name),
    ['set', 'goal width', 'goal height', 'shooter size', 'placement', 'ground plane', 'camera']);
});

test('goal width alone is the lens times six feet', () => {
  const r = estimateDistance({ view_w: 720, view_h: 1280, goal: { w: 0.2, seen: 5, of: 5 } });
  assert.strictEqual(r.source, 'camera');
  assert.ok(Math.abs(r.distance_m - DEFAULT_FOCAL * GOAL_WIDTH_M / 0.2) < 0.02);
});

test('no goal means the set distance, about a yard', () => {
  const r = estimateDistance({ typed_yd: 8, view_w: 720, view_h: 1280, goal: { w: 0.02, seen: 5, of: 5 } });
  assert.strictEqual(r.source, 'set');
  assert.ok(Math.abs(r.plus_minus_m - TYPED_SIGMA_M) < 0.01);
  assert.ok(r.factors.some((f) => f.name === 'goal width' && !f.used));
});

test('a camera that disagrees loses to the pace and says so', () => {
  const r = estimateDistance({ typed_yd: 7, view_w: 720, view_h: 1280, goal: { w: 0.12, cx: 0, seen: 50, of: 50 } });
  assert.strictEqual(r.source, 'set');
  assert.match(r.note, /Check the spot/);
  assert.strictEqual(r.focal_hint, null);
});

test('inverse-variance fusion believes the surer one more', () => {
  const r = fuse([{ value: 10, sigma: 1 }, { value: 20, sigma: 3 }]);
  assert.ok(r.value > 10 && r.value < 12, String(r.value));
  assert.ok(r.sigma < 1);
});

test('unknown age takes the twelve-year-old torso', () => {
  assert.strictEqual(torsoForAge(undefined), torsoForAge(12));
  assert.ok(torsoForAge(16) > torsoForAge(10));
});

/** A synthetic frame: grass with a square goal outline and net, in a colour. */
const ORANGE = [235, 110, 30], FADED = [200, 150, 60], WHITE = [240, 240, 236], BLACK = [25, 25, 28];
function frame(width, height, goal, rgb = ORANGE, grass = [40, 120, 40]) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i += 1) { data[i * 4] = grass[0]; data[i * 4 + 1] = grass[1]; data[i * 4 + 2] = grass[2]; data[i * 4 + 3] = 255; }
  if (goal) {
    const { x, y, w, h } = goal;
    for (let yy = y; yy < y + h; yy += 1) {
      for (let xx = x; xx < x + w; xx += 1) {
        const edge = xx - x < 3 || x + w - xx <= 3 || yy - y < 3;
        const net = (xx + yy) % 5 === 0;
        if (edge || net) { const i = (yy * width + xx) * 4; data[i] = rgb[0]; data[i + 1] = rgb[1]; data[i + 2] = rgb[2]; }
      }
    }
  }
  return { data, width, height };
}

test('the colour is learned: orange, faded, white and black goals are all found', () => {
  for (const rgb of [ORANGE, FADED, WHITE, BLACK]) {
    const c = new GoalColour();
    const g = c.find(frame(320, 180, { x: 100, y: 40, w: 60, h: 56 }, rgb));
    assert.ok(g, `not found for ${rgb}`);
    assert.ok(Math.abs(g.w - 60) <= 2, JSON.stringify(g));
    assert.ok(c.window && c.window.learned, 'window not learned');
  }
});

test('a learned window is tighter than its seed and still fits the posts', () => {
  const c = new GoalColour();
  c.find(frame(320, 180, { x: 100, y: 40, w: 60, h: 56 }));
  const seed = GOAL_SEEDS[0], w = c.window;
  assert.ok(w.sat[1] - w.sat[0] < seed.sat[1] - seed.sat[0]);
  assert.ok(inWindow(20, 0.87, 0.92, w), 'the goal colour fell out of its own window');
  assert.ok(!inWindow(20, 0.3, 0.5, w), 'a dull orange should be outside the tightened window');
});

test('a change of light widens the window and then reseeds rather than losing the goal', () => {
  const c = new GoalColour();
  const bright = frame(320, 180, { x: 100, y: 40, w: 60, h: 56 }, ORANGE);
  for (let i = 0; i < 3; i += 1) assert.ok(c.find(bright));
  // The floodlights go off: same goal, much dimmer and duller.
  const dim = frame(320, 180, { x: 100, y: 40, w: 60, h: 56 }, [120, 60, 20], [15, 45, 15]);
  let found = null;
  for (let i = 0; i < 12 && !found; i += 1) found = c.find(dim);
  assert.ok(found, 'goal lost after the light changed');
  assert.ok(Math.abs(found.w - 60) <= 2);
});

test('the goal finder boxes an orange square and ignores grass', () => {
  const g = findGoal(frame(320, 180, { x: 100, y: 40, w: 60, h: 56 }));
  assert.ok(g, 'goal not found');
  assert.ok(Math.abs(g.w - 60) <= 2 && Math.abs(g.h - 56) <= 2, JSON.stringify(g));
  assert.strictEqual(findGoal(frame(320, 180, null)), null);
});

test('a goal at the frame edge is refused, not measured', () => {
  assert.strictEqual(findGoal(frame(320, 180, { x: 0, y: 40, w: 60, h: 56 })), null);
});

test('the watcher medians the goal and the shooter into a scene', () => {
  const w = new SceneWatcher({ typedYd: 9 });
  w.setFrame(1280, 720);
  for (let t = 0; t < 5000; t += 450) w.pushImage(frame(320, 180, { x: 100, y: 40, w: 60, h: 56 }), t);
  const IDX = Object.fromEntries(LANDMARKS.map((n, i) => [n, i]));
  const p = LANDMARKS.map(() => ({ x: 0.5, y: 0.5, visibility: 0.1 }));
  p[IDX.left_shoulder] = { x: 0.2, y: 0.3, visibility: 0.9 }; p[IDX.right_shoulder] = { x: 0.24, y: 0.3, visibility: 0.9 };
  p[IDX.left_hip] = { x: 0.2, y: 0.5, visibility: 0.9 }; p[IDX.right_hip] = { x: 0.24, y: 0.5, visibility: 0.9 };
  p[IDX.left_ankle] = { x: 0.2, y: 0.85, visibility: 0.9 }; p[IDX.right_ankle] = { x: 0.24, y: 0.85, visibility: 0.9 };
  for (let i = 0; i < 30; i += 1) w.pushPose(p);
  w.pushPitch(6);
  const s = w.scene();
  assert.strictEqual(s.typed_yd, 9);
  assert.ok(s.goal.seen >= 10 && s.goal.of === s.goal.seen, JSON.stringify(s.goal));
  assert.ok(Math.abs(s.goal.w - 60 / 180) < 0.02);
  assert.ok(Math.abs(s.athlete.torso - 0.2) < 0.01);
  assert.ok(s.athlete.cx < 0, 'shooter is left of centre');
  assert.strictEqual(s.pitch_deg, 6);
  const r = estimateDistance(s, { age: 12 });
  assert.ok(['camera+set', 'set'].includes(r.source));
});
