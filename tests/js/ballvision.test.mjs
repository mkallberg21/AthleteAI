/**
 * The lacrosse-specific detector.
 *
 * Classical CV, not a trained model -- see the module header for why. Driven
 * with synthetically rendered frames: a disc of a known colour on a background,
 * with noise and distractors. That is the same limitation the pose thresholds
 * carry, and it is stated in the README: this proves the logic, not that it
 * survives a real driveway.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import {
  BallVision, PRESETS, calibrate, matchPixel, radiusFromPose,
  BALL_TO_TORSO, RADIUS_TOLERANCE,
} from '../../athleteiq/web/static/ballvision.js';
import { LANDMARK_INDEX } from '../../athleteiq/web/static/ball.js';

const W = 192, H = 108;

/** A frame: flat background, optional discs, optional noise. */
function frame({ bg = [70, 90, 70], discs = [], noise = 0, seed = 1 } = {}) {
  const data = new Uint8ClampedArray(W * H * 4);
  let s = seed;
  const rand = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
  for (let y = 0; y < H; y += 1) {
    for (let x = 0; x < W; x += 1) {
      const i = (y * W + x) * 4;
      let [r, g, b] = bg;
      for (const d of discs) {
        if (Math.hypot(x - d.x, y - d.y) <= d.r) { [r, g, b] = d.colour; break; }
      }
      const n = noise ? (rand() - 0.5) * noise : 0;
      data[i] = r + n; data[i + 1] = g + n; data[i + 2] = b + n; data[i + 3] = 255;
    }
  }
  return { data, width: W, height: H };
}

const YELLOW = [245, 220, 30];
const WHITE = [248, 250, 246];

/** Two frames so the motion gate has something to compare. */
function seeTwice(vision, first, second, opts) {
  vision.detect(first, opts);
  return vision.detect(second, opts);
}

test('it finds a yellow ball on grass', () => {
  const vision = new BallVision({ profile: PRESETS.yellow, useMotion: false });
  const found = vision.detect(frame({ discs: [{ x: 120, y: 40, r: 4, colour: YELLOW }] }));
  assert.ok(found, 'nothing found');
  assert.ok(Math.abs(found.x * W - 120) < 3, `x was ${found.x * W}`);
  assert.ok(Math.abs(found.y * H - 40) < 3, `y was ${found.y * H}`);
});

test('it survives sensor noise', () => {
  const vision = new BallVision({ profile: PRESETS.yellow, useMotion: false });
  const found = vision.detect(
    frame({ discs: [{ x: 60, y: 70, r: 5, colour: YELLOW }], noise: 40 }),
  );
  assert.ok(found && Math.abs(found.x * W - 60) < 4);
});

test('an empty frame finds nothing', () => {
  const vision = new BallVision({ profile: PRESETS.yellow, useMotion: false });
  assert.equal(vision.detect(frame({})), null);
});

test('it is not fooled by skin, brick, cones or grass', () => {
  const vision = new BallVision({ profile: PRESETS.yellow, useMotion: false });
  const distractors = [
    { x: 40, y: 30, r: 9, colour: [210, 160, 130] },   // an arm
    { x: 150, y: 80, r: 12, colour: [150, 80, 60] },   // brick
    { x: 90, y: 20, r: 7, colour: [200, 40, 40] },     // a cone
  ];
  assert.equal(vision.detect(frame({ discs: distractors })), null);
});

test('a yellow jacket sleeve is rejected for not being round', () => {
  // The shape gate. A long streak of the right colour matches on every pixel
  // and still is not a ball.
  const vision = new BallVision({ profile: PRESETS.yellow, useMotion: false });
  const streak = [];
  for (let x = 40; x < 110; x += 1) streak.push({ x, y: 50, r: 2.5, colour: YELLOW });
  assert.equal(vision.detect(frame({ discs: streak })), null);
});

test('the size the pose implies rejects a ball-coloured object too big', () => {
  // The filter a general detector cannot apply: a lacrosse ball is always
  // 6.35cm, and the athlete's torso in the same frame says how big that is.
  const vision = new BallVision({ profile: PRESETS.yellow, useMotion: false });
  const expected = 4 / H;

  const real = vision.detect(frame({ discs: [{ x: 100, y: 50, r: 4, colour: YELLOW }] }),
                             { expectedRadius: expected });
  assert.ok(real, 'the real ball should pass');

  const bucket = vision.detect(frame({ discs: [{ x: 100, y: 50, r: 16, colour: YELLOW }] }),
                               { expectedRadius: expected });
  assert.equal(bucket, null, 'a yellow bucket is not a lacrosse ball');
});

test('radius is computed from the athlete, not guessed', () => {
  const landmarks = [];
  landmarks[LANDMARK_INDEX.left_shoulder] = { x: 0.45, y: 0.30, visibility: 0.9 };
  landmarks[LANDMARK_INDEX.left_hip] = { x: 0.46, y: 0.60, visibility: 0.9 };
  const r = radiusFromPose(landmarks, LANDMARK_INDEX);
  const torso = Math.hypot(0.45 - 0.46, 0.30 - 0.60);
  // A 0.30 torso implies a ball a little over 2% of frame height across.
  assert.ok(Math.abs(r - (torso * BALL_TO_TORSO) / 2) < 1e-9);
  assert.ok(r > 0.015 && r < 0.03, `implausible radius ${r}`);
});

test('an unusable pose gives no constraint rather than a wrong one', () => {
  assert.equal(radiusFromPose(null, LANDMARK_INDEX), null);
  const hidden = [];
  hidden[LANDMARK_INDEX.left_shoulder] = { x: 0.45, y: 0.30, visibility: 0.1 };
  hidden[LANDMARK_INDEX.left_hip] = { x: 0.46, y: 0.60, visibility: 0.1 };
  assert.equal(radiusFromPose(hidden, LANDMARK_INDEX), null);
});

test('a white ball on a white wall needs motion, and gets it', () => {
  // The genuinely hard case, and the reason the motion gate exists: in chroma
  // a white ball and a pale wall are the same point.
  // A real wall, lit but duller than a matte white ball in front of it.
  const wall = [200, 201, 199];
  const vision = new BallVision({ profile: PRESETS.white, useMotion: true });
  const before = frame({ bg: wall, discs: [{ x: 60, y: 50, r: 4, colour: WHITE }] });
  const after = frame({ bg: wall, discs: [{ x: 110, y: 40, r: 4, colour: WHITE }] });
  const found = seeTwice(vision, before, after);
  assert.ok(found, 'lost the ball against the wall');
  assert.ok(Math.abs(found.x * W - 110) < 5, `x was ${found.x * W}`);
});

test('a painted line of the same colour never moves, so it is not the ball', () => {
  const vision = new BallVision({ profile: PRESETS.white, useMotion: true });
  const line = [];
  for (let x = 20; x < 170; x += 1) line.push({ x, y: 80, r: 2, colour: WHITE });
  const still = frame({ bg: [120, 122, 118], discs: line });
  assert.equal(seeTwice(vision, still, still), null);
});

test('the search window keeps the track from jumping across the room', () => {
  const vision = new BallVision({ profile: PRESETS.yellow, useMotion: false });
  const two = frame({
    discs: [
      { x: 30, y: 30, r: 4, colour: YELLOW },    // where the tracker expects it
      { x: 170, y: 90, r: 6, colour: YELLOW },   // a bigger one far away
    ],
  });
  const found = vision.detect(two, { expectedRadius: 4 / H, near: { x: 30 / W, y: 30 / H } });
  assert.ok(found && Math.abs(found.x * W - 30) < 6,
    `followed the wrong ball to ${found && found.x * W}`);
});

test('calibrating on the athlete own ball beats a preset', () => {
  // An unusual ball: a faded lime one that the yellow preset does not match.
  const odd = [200, 235, 90];
  assert.equal(matchPixel(...odd, PRESETS.yellow), 0, 'preset should miss this one');

  const swatch = frame({ discs: [{ x: 96, y: 54, r: 10, colour: odd }] });
  const profile = calibrate(swatch, { x: 90, y: 48, w: 12, h: 12 });
  assert.ok(matchPixel(...odd, profile) > 0, 'calibration should catch it');

  const vision = new BallVision({ profile, useMotion: false });
  const found = vision.detect(frame({ discs: [{ x: 70, y: 60, r: 4, colour: odd }] }));
  assert.ok(found && Math.abs(found.x * W - 70) < 4);
});

test('calibrating on a white ball produces the brightness profile', () => {
  // Not a chroma centroid, which would match every grey thing in frame.
  const swatch = frame({ bg: [40, 40, 40], discs: [{ x: 96, y: 54, r: 12, colour: WHITE }] });
  const profile = calibrate(swatch, { x: 90, y: 48, w: 12, h: 12 });
  assert.equal(profile.kind, 'bright');
});

test('the colour presets separate every ball from every distractor', () => {
  const balls = {
    yellow: [[245, 220, 30], [180, 165, 35], [230, 220, 40], [222, 232, 58]],
    orange: [[255, 120, 20], [190, 90, 25]],
    white: [[238, 240, 235], [180, 182, 178]],
  };
  const distractors = [
    [60, 120, 50], [210, 160, 130], [40, 60, 200], [200, 40, 40],
    [150, 150, 150], [150, 80, 60], [150, 190, 235], [90, 90, 95],
  ];
  for (const [name, profile] of Object.entries(PRESETS)) {
    for (const ball of balls[name]) {
      assert.ok(matchPixel(...ball, profile) > 0, `${name} missed ${ball}`);
    }
    for (const other of distractors) {
      assert.equal(matchPixel(...other, profile), 0, `${name} matched ${other}`);
    }
  }
});
