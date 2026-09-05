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
  BallVision, PRESETS, BALLS, calibrate, matchPixel, radiusFromPose,
  workSize, ScaleMemory, WORK_PIXELS,
  BALL_TO_TORSO, TORSO_CM, RADIUS_TOLERANCE, isBright,
  sampleColour, MIN_SAMPLE_SHARE,
} from '../../offdays/web/static/ballvision.js';
import { LANDMARK_INDEX } from '../../offdays/web/static/ball.js';
import { SPECS } from './specs.mjs';

const W = 192, H = 108;


/**
 * A disc cut into wedges of different colours, for the panelled balls. The
 * wedges are equal, which is close to how a competition volleyball's three
 * colours actually divide up its surface.
 */
function panelledFrame({ x, y, r, panels, bg = [70, 90, 70] }) {
  const data = new Uint8ClampedArray(W * H * 4);
  for (let py = 0; py < H; py += 1) {
    for (let px = 0; px < W; px += 1) {
      const i = (py * W + px) * 4;
      let colour = bg;
      if (Math.hypot(px - x, py - y) <= r) {
        const angle = (Math.atan2(py - y, px - x) + Math.PI) / (2 * Math.PI);
        colour = panels[Math.floor(angle * panels.length) % panels.length];
      }
      data[i] = colour[0]; data[i + 1] = colour[1];
      data[i + 2] = colour[2]; data[i + 3] = 255;
    }
  }
  return { data, width: W, height: H };
}

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



/** A ball with panels: a base colour plus darker patches, like a real one. */
function panelled(x, y, r, base, patch) {
  const discs = [{ x, y, r, colour: base }];
  // Three patches, covering roughly a quarter of the face.
  discs.unshift(
    { x: x - r * 0.4, y: y - r * 0.3, r: r * 0.32, colour: patch },
    { x: x + r * 0.45, y: y + r * 0.2, r: r * 0.28, colour: patch },
  );
  return discs;
}

test('every sport in the registry has a regulated diameter and a colour', () => {
  for (const [sport, ball] of Object.entries(BALLS)) {
    assert.ok(ball.diameterCm > 5 && ball.diameterCm < 30, sport);
    assert.ok(PRESETS[ball.colour], `${sport} names an unknown preset`);
  }
});

test('the size prior follows the sport, not a lacrosse ball for everything', () => {
  const landmarks = [];
  landmarks[LANDMARK_INDEX.left_shoulder] = { x: 0.45, y: 0.30, visibility: 0.9 };
  landmarks[LANDMARK_INDEX.left_hip] = { x: 0.45, y: 0.60, visibility: 0.9 };

  const lax = radiusFromPose(landmarks, LANDMARK_INDEX, BALLS.lacrosse.diameterCm);
  const basket = radiusFromPose(landmarks, LANDMARK_INDEX, BALLS.basketball.diameterCm);
  // A basketball is nearly four times a lacrosse ball across, and the gate is
  // only a filter if it filters on the right size.
  assert.ok(basket / lax > 3.5 && basket / lax < 3.9, `ratio ${basket / lax}`);
  assert.ok(Math.abs(basket - (0.30 * (23.0 / TORSO_CM)) / 2) < 1e-9);
});

test('it finds a basketball and is not fooled by brick', () => {
  // The tightest colour separation in the table: basketball orange-brown sits
  // 0.056 from brick, so this one leans hardest on colour precision.
  const vision = new BallVision({ profile: PRESETS.basketball, useMotion: false });
  const expected = 9 / H;

  const ball = vision.detect(
    frame({ bg: [120, 130, 120], discs: [{ x: 96, y: 54, r: 9, colour: [205, 110, 45] }] }),
    { expectedRadius: expected },
  );
  assert.ok(ball, 'lost the basketball');
  assert.ok(Math.abs(ball.x * W - 96) < 4);

  const brickOnly = vision.detect(
    frame({ bg: [150, 80, 60] }), { expectedRadius: expected },
  );
  assert.equal(brickOnly, null, 'a brick wall is not a basketball');
});

test('a panelled soccer ball is measured across the ball, not the white bits', () => {
  // A count-derived radius reports a panelled ball 16% small every time,
  // because the patches match nothing. The box still spans the real ball.
  const vision = new BallVision({ profile: PRESETS.white, useMotion: false });
  const r = 9;
  const found = vision.detect(
    frame({ bg: [70, 110, 70], discs: panelled(96, 54, r, [242, 244, 240], [30, 30, 32]) }),
  );
  assert.ok(found, 'lost a panelled ball entirely');
  const measured = found.r * H;
  assert.ok(measured > r * 0.8 && measured < r * 1.2,
    `measured ${measured.toFixed(1)} for a true ${r}`);
});

test('a stitched baseball is still round enough', () => {
  const vision = new BallVision({ profile: PRESETS.white, useMotion: false });
  const found = vision.detect(
    frame({ bg: [70, 110, 70], discs: panelled(96, 54, 7, [246, 244, 236], [170, 40, 40]) }),
  );
  assert.ok(found, 'stitching should not lose the ball');
});

test('a tennis ball is found on a court and not confused with a lacrosse yellow', () => {
  const vision = new BallVision({ profile: PRESETS.optic, useMotion: false });
  const found = vision.detect(
    frame({ bg: [110, 90, 80], discs: [{ x: 130, y: 60, r: 5, colour: [222, 232, 58] }] }),
  );
  assert.ok(found && Math.abs(found.x * W - 130) < 4);
});

test('each preset separates its own balls from every distractor', () => {
  const balls = {
    yellow: [[245, 220, 30], [180, 165, 35], [230, 220, 40]],
    orange: [[255, 120, 20], [190, 90, 25]],
    white: [[238, 240, 235], [180, 182, 178], [242, 244, 240]],
    basketball: [[205, 110, 45], [180, 95, 40], [225, 125, 60], [160, 85, 35]],
    optic: [[222, 232, 58], [205, 220, 70], [180, 200, 55], [230, 240, 90]],
    lime: [[200, 240, 40], [180, 255, 30], [140, 175, 45], [165, 200, 55],
           [210, 235, 60], [150, 190, 40]],
    // The panels a competition volleyball is matched on. Its blue panels are
    // deliberately not here -- the preset does not claim them, and the blue
    // distractor below asserts it still does not match them.
    volleyball: [[248, 250, 246], [245, 215, 40], [225, 228, 222], [230, 205, 55]],
  };
  const distractors = [
    [60, 120, 50], [210, 160, 130], [40, 60, 200], [200, 40, 40],
    [150, 150, 150], [150, 80, 60], [150, 190, 235], [90, 90, 95],
    // Grass, in four lights. It is the surface lacrosse is played on and the
    // nearest thing in the world to a lime ball, so it is the distractor that
    // decides whether that preset may exist at all.
    [90, 140, 55], [60, 100, 45], [70, 160, 70], [120, 180, 70],
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

test('every ball drill names presets and a diameter that exist', () => {
  for (const drill of SPECS.filter((d) => d.ball && d.ball.detector === 'vision')) {
    assert.ok(drill.ball.colours.length, `${drill.key} names no colour`);
    for (const name of drill.ball.colours) {
      assert.ok(PRESETS[name], `${drill.key} -> ${name}`);
    }
    // The first is the best guess and the one the rest of the product uses.
    assert.equal(drill.ball.colour, drill.ball.colours[0], drill.key);
    assert.ok(drill.ball.diameter_cm > 5, drill.key);
    const known = BALLS[drill.sport];
    if (known) {
      assert.equal(drill.ball.diameter_cm, known.diameterCm, drill.key);
      assert.equal(drill.ball.colours[0], known.colour, drill.key);
    }
  }
});

test('a lacrosse drill looks for all three colours it is sold in', () => {
  const lax = SPECS.filter((d) => d.sport === 'lacrosse' && d.ball);
  assert.ok(lax.length >= 8, 'expected the wall-ball family');
  for (const drill of lax) {
    assert.deepEqual(drill.ball.colours, ['white', 'yellow', 'lime'], drill.key);
  }
});


test('a large slow ball is measured whole, not as the crescent that moved', () => {
  // The regression this guards is subtle and was found end to end, not here:
  // a basketball moving at a normal speed overlaps itself almost completely
  // between frames, so under a pixel-level motion gate only a thin crescent
  // changed and the ball measured as a sliver. Detection was 41%. Motion is
  // now used to decide *where* to look, and colour and shape to measure what
  // is there.
  const vision = new BallVision({ profile: PRESETS.basketball, useMotion: true });
  const r = 20;
  const expected = r / H;
  const ball = (x) => frame({ bg: [95, 120, 95], discs: [{ x, y: 54, r, colour: [205, 110, 45] }] });

  vision.detect(ball(80), { expectedRadius: expected });
  // Moved by a fifth of its own radius: heavy self-overlap.
  const found = vision.detect(ball(84), { expectedRadius: expected });
  assert.ok(found, 'lost a large ball that barely moved');
  const measured = found.r * H;
  assert.ok(measured > r * 0.8 && measured < r * 1.25,
    `measured ${measured.toFixed(1)} for a true ${r}`);
});

test('the white-wall fallback still works after that change', () => {
  // The two requirements pull against each other: measuring by colour first
  // is what fixes the large ball, and falling back to motion is what keeps a
  // white ball findable against a wall that matches it.
  const wall = [200, 201, 199];
  const vision = new BallVision({ profile: PRESETS.white, useMotion: true });
  const ball = (x) => frame({ bg: wall, discs: [{ x, y: 50, r: 4, colour: [248, 250, 246] }] });
  vision.detect(ball(60), { expectedRadius: 4 / H });
  const found = vision.detect(ball(95), { expectedRadius: 4 / H });
  assert.ok(found, 'lost the ball against the wall');
  assert.ok(Math.abs(found.x * W - 95) < 6, `x was ${found.x * W}`);
});


test('the working image costs the same held either way', () => {
  // Sizing by width meant a phone in portrait produced three times the pixels
  // and three times the cost, purely because the athlete turned it.
  const landscape = workSize(1920, 1080);
  const portrait = workSize(1080, 1920);
  assert.ok(Math.abs(landscape.width * landscape.height - WORK_PIXELS) / WORK_PIXELS < 0.05);
  assert.ok(Math.abs(portrait.width * portrait.height - WORK_PIXELS) / WORK_PIXELS < 0.05);
  assert.equal(landscape.width, portrait.height);
  assert.equal(landscape.height, portrait.width);
});

test('a small camera feed is used as it comes, never upscaled', () => {
  const small = workSize(320, 240);
  assert.equal(small.width, 320);
  assert.equal(small.height, 240);
});

test('a ball is the same size in working pixels in either orientation', () => {
  // What the athlete cares about: turning the phone must not change whether
  // the drill works.
  //
  // The comparison has to be the *same physical scene*, which means the same
  // torso in sensor pixels. Fixing the torso at a share of frame height
  // instead describes two different framings -- an easy mistake, and one that
  // makes the pipeline look broken when it is not.
  const torsoSensorPx = 243;
  const sizes = [[1920, 1080], [1080, 1920]].map(([w, h]) => {
    const size = workSize(w, h);
    const landmarks = [];
    const torsoNorm = torsoSensorPx / h;
    landmarks[LANDMARK_INDEX.left_shoulder] = { x: 0.5, y: 0.2, visibility: 0.9 };
    landmarks[LANDMARK_INDEX.left_hip] = { x: 0.5, y: 0.2 + torsoNorm, visibility: 0.9 };
    const r = radiusFromPose(
      landmarks, LANDMARK_INDEX, BALLS.lacrosse.diameterCm, w / h,
    );
    return r * size.height;
  });
  assert.ok(Math.abs(sizes[0] - sizes[1]) < 0.2,
    `landscape ${sizes[0].toFixed(2)}px vs portrait ${sizes[1].toFixed(2)}px`);
  assert.ok(sizes[0] > 3, `only ${sizes[0].toFixed(2)}px, too small to resolve`);
});

test('body scale survives the hips leaving the frame', () => {
  // A phone propped against a bag points where it points. Requiring shoulder
  // *and* hip meant an athlete framed from the chest up lost the size prior
  // entirely, and with it the detector's strongest filter.
  const chestUp = [];
  chestUp[LANDMARK_INDEX.left_shoulder] = { x: 0.42, y: 0.35, visibility: 0.9 };
  chestUp[LANDMARK_INDEX.right_shoulder] = { x: 0.58, y: 0.35, visibility: 0.9 };
  assert.ok(radiusFromPose(chestUp, LANDMARK_INDEX, 6.35, 16 / 9));

  const headOnly = [];
  headOnly[LANDMARK_INDEX.nose] = { x: 0.50, y: 0.20, visibility: 0.9 };
  headOnly[LANDMARK_INDEX.left_shoulder] = { x: 0.44, y: 0.36, visibility: 0.9 };
  assert.ok(radiusFromPose(headOnly, LANDMARK_INDEX, 6.35, 16 / 9));

  assert.equal(radiusFromPose([], LANDMARK_INDEX), null, 'nothing visible is still null');
});

test('the scale is remembered while the athlete turns away', () => {
  const memory = new ScaleMemory(4000);
  assert.equal(memory.update(0.02, 0), 0.02);
  // Pose lost for two seconds -- a turn, a stick across the body.
  assert.ok(memory.update(null, 2000) > 0);
  // Gone long enough that the framing may be different now.
  assert.equal(memory.update(null, 9000), null);
});

test('the remembered scale is blended, so one bad frame cannot move it', () => {
  const memory = new ScaleMemory();
  memory.update(0.02, 0);
  const after = memory.update(0.20, 100);
  assert.ok(after < 0.07, `one wild reading moved it to ${after}`);
});


// ---------------------------------------------------------------------------
// Picking the colour, because a lacrosse ball has three.
//
// White is still the common case, but yellow and neon lime are ordinary now
// and which one an athlete owns is whatever their club bought. Naming only
// white meant a child with a lime ball got a drill that corroborated nothing
// and never said why.
// ---------------------------------------------------------------------------

const LIME = [195, 238, 45];
const laxProfiles = () => [PRESETS.white, PRESETS.yellow, PRESETS.lime];

/** Play `n` frames of one ball moving, so the motion gate has real history. */
function playBall(vision, colour, n, opts = {}) {
  let last = null;
  for (let i = 0; i < n; i += 1) {
    last = vision.detect(
      frame({ discs: [{ x: 40 + i * 2, y: 40, r: 4, colour }] }), opts,
    );
  }
  return last;
}

test('a lacrosse session with a lime ball settles on lime', () => {
  const vision = new BallVision({ profiles: laxProfiles(), settleFrames: 20 });
  playBall(vision, LIME, 24);
  assert.equal(vision.chosen.name, 'lime');
  assert.ok(vision.chosen.locked, 'the choice was never made');
});

test('and one with a yellow ball settles on yellow', () => {
  const vision = new BallVision({ profiles: laxProfiles(), settleFrames: 20 });
  playBall(vision, YELLOW, 24);
  assert.equal(vision.chosen.name, 'yellow');
});

test('once locked it stops trying the others', () => {
  // The reason the competition is time-boxed at all: running three presets on
  // every frame triples the cost of the most expensive stage in the pipeline,
  // on the cheapest phone in the room.
  const vision = new BallVision({ profiles: laxProfiles(), settleFrames: 10 });
  playBall(vision, LIME, 12);
  const calls = [];
  const real = vision._detectOnce.bind(vision);
  vision._detectOnce = (...args) => { calls.push(vision.profile); return real(...args); };
  playBall(vision, LIME, 3);
  assert.equal(new Set(calls).size, 1, 'more than one profile ran after locking');
});

test('every candidate is judged against the same motion history', () => {
  // The bug this guards: detect() consumes the previous frame, so a second
  // candidate run on the same frame would compare it against itself, find no
  // motion, and lose a contest it should have won. Lime is last in the list,
  // so it only wins if the restore works.
  const vision = new BallVision({ profiles: laxProfiles(), settleFrames: 12 });
  playBall(vision, LIME, 14);
  assert.equal(vision.chosen.name, 'lime');
});

test('one lucky frame does not decide the session', () => {
  // The winner is whichever preset found the ball most often, not first.
  const vision = new BallVision({ profiles: laxProfiles(), settleFrames: 30 });
  vision.detect(frame({ discs: [{ x: 60, y: 40, r: 4, colour: WHITE }] }));
  playBall(vision, LIME, 34);
  assert.equal(vision.chosen.name, 'lime');
});

test('finding nothing keeps the drill\'s first guess rather than inventing one', () => {
  const vision = new BallVision({ profiles: laxProfiles(), settleFrames: 8 });
  for (let i = 0; i < 10; i += 1) vision.detect(frame({ discs: [] }));
  assert.equal(vision.chosen.name, 'white', 'drifted off the primary preset');
  assert.ok(vision.chosen.locked);
});

test('a single-colour drill never enters a competition at all', () => {
  const vision = new BallVision({ profile: PRESETS.basketball });
  assert.ok(vision.locked, 'a one-colour ball should be settled from the start');
  assert.equal(vision.chosen.name, 'basketball');
});

test('calibrating on the real ball overrides whatever was picked', () => {
  // Two seconds pointed at the actual ball beats every preset in the table,
  // and that has to hold after the competition as well as before it.
  const vision = new BallVision({ profiles: laxProfiles(), settleFrames: 6 });
  playBall(vision, LIME, 8);
  const learned = calibrate(
    frame({ discs: [{ x: 60, y: 40, r: 8, colour: [255, 140, 20] }] }),
    { x: 52, y: 32, w: 16, h: 16 },
  );
  vision.setProfile(learned);
  assert.equal(vision.profile, learned);
  assert.ok(vision.locked);
});

test('a panel preset only unions presets that already passed separation', () => {
  // A panel profile is exempt from nothing: it is built from members of this
  // same table, so the separation test above covers it by construction. This
  // asserts that stays true and a panel cannot smuggle in a loose centroid.
  const named = new Set(Object.values(PRESETS));
  for (const [name, profile] of Object.entries(PRESETS)) {
    if (profile.kind !== 'panel') continue;
    assert.ok(profile.of.length >= 2, `${name} unions nothing`);
    for (const member of profile.of) {
      assert.ok(named.has(member), `${name} unions an unnamed profile`);
      assert.notEqual(member.kind, 'panel', `${name} nests a panel`);
    }
  }
});

test('a panelled volleyball is invisible to any single centroid', () => {
  // The reason the panel kind exists. A competition ball is roughly equal
  // thirds, so each colour covers about 33% of it against a 45% fill gate --
  // every single-centroid preset measures a wedge and rejects it. If this
  // test ever passes for a single preset the panel machinery is dead weight.
  const WHITE = [248, 250, 246], BLUE = [30, 70, 160], YELLOW = [245, 215, 40];
  const tricolour = [WHITE, BLUE, YELLOW, WHITE, BLUE, YELLOW];
  for (const [name, profile] of Object.entries(PRESETS)) {
    if (profile.kind === 'panel') continue;
    const found = new BallVision({ profile, useMotion: false })
      .detect(panelledFrame({ x: 96, y: 54, r: 7, panels: tricolour }));
    assert.equal(found, null, `${name} should not have found a tri-colour ball`);
  }
});

test('the volleyball preset finds a panelled ball at its true size', () => {
  const WHITE = [248, 250, 246], BLUE = [30, 70, 160], YELLOW = [245, 215, 40];
  const vision = new BallVision({ profile: PRESETS.volleyball, useMotion: false });
  const found = vision.detect(panelledFrame({
    x: 96, y: 54, r: 7, panels: [WHITE, BLUE, YELLOW, WHITE, BLUE, YELLOW],
  }));
  assert.ok(found, 'panel preset missed the ball it exists for');
  // Two thirds of the disc matches, so the radius must still come back close
  // to the true 7px rather than shrinking towards the matched area.
  const radiusPx = found.r * 108;
  assert.ok(radiusPx > 5.5 && radiusPx < 9, `radius was ${radiusPx}`);
});

test('the volleyball preset still finds a plain white ball', () => {
  // Most youth volleyballs are plain, and the panel must not cost that case.
  const found = new BallVision({ profile: PRESETS.volleyball, useMotion: false })
    .detect(panelledFrame({ x: 96, y: 54, r: 7, panels: [[248, 250, 246]] }));
  assert.ok(found, 'panel preset missed a plain white ball');
});

test('a panel counts as bright only when every member is', () => {
  // The directional motion test exists for colourless balls. A volleyball has
  // a yellow third, which is plenty of signal for the ordinary magnitude test.
  assert.equal(isBright(PRESETS.white), true);
  assert.equal(isBright(PRESETS.yellow), false);
  assert.equal(isBright(PRESETS.volleyball), false);
  assert.equal(isBright({ kind: 'panel', of: [PRESETS.white, PRESETS.white] }), true);
});

test('soccer, volleyball and baseball look for the colours they are sold in', () => {
  const expected = {
    soccer: ['white', 'yellow', 'orange'],
    volleyball: ['white', 'volleyball'],
    // Short on purpose. A baseball really is almost always white, and padding
    // this list to match the others would be inventing variety.
    baseball: ['white', 'optic'],
  };
  for (const [sport, colours] of Object.entries(expected)) {
    const drills = SPECS.filter((d) => d.sport === sport && d.ball
      && d.ball.detector === 'vision');
    assert.ok(drills.length, `no ball drills for ${sport}`);
    for (const drill of drills) {
      assert.deepEqual(drill.ball.colours, colours, drill.key);
    }
  }
});

test('every ball drill leads with its most selective colour', () => {
  // The candidate competition settles on whichever preset detects most, so a
  // loose profile listed first would win ties on frames where both fit. White
  // and the panels that contain it are the loose ones, so nothing may list a
  // panel ahead of the plain preset it is built from.
  for (const drill of SPECS.filter((d) => d.ball && d.ball.detector === 'vision')) {
    const profiles = drill.ball.colours.map((n) => PRESETS[n]);
    profiles.forEach((profile, i) => {
      if (profile.kind !== 'panel') return;
      for (const member of profile.of) {
        const at = profiles.indexOf(member);
        assert.ok(at === -1 || at < i,
          `${drill.key} lists a panel before the preset it contains`);
      }
    });
  }
});

test('calibration refuses a ball with no colour big enough to find it by', () => {
  // Averaging a panelled ball gives a centroid matching no part of it, and
  // calibration locks -- so a confident wrong answer here would permanently
  // replace a preset that works. Refusing sends the caller back to the preset.
  const WHITE = [248, 250, 246], BLUE = [30, 70, 160], YELLOW = [245, 215, 40];
  const frame = panelledFrame({ x: 96, y: 54, r: 40, panels: [WHITE, BLUE, YELLOW] });
  const box = { x: 66, y: 24, w: 60, h: 60 };
  assert.ok(sampleColour(frame, box).share < MIN_SAMPLE_SHARE);
  assert.equal(calibrate(frame, box), null);
});

test('calibration fits the dominant colour and ignores the rest', () => {
  // The case that caught the first version of this rule. A two-tone Molten
  // basketball is about a third cream, which read as "more than one colour"
  // and was refused -- even though the basketball preset finds that ball
  // perfectly and two thirds of it is a perfectly good orange to fit.
  //
  // Cream is not, and must never be, a colour anything matches: it sits 0.005
  // from sand and 0.02 from pale wood. So the answer is to fit the orange.
  const ORANGE = [222, 118, 40], CREAM = [226, 206, 164];
  const box = { x: 66, y: 24, w: 60, h: 60 };
  const frame = panelledFrame({
    x: 96, y: 54, r: 40, panels: [ORANGE, ORANGE, CREAM, ORANGE, ORANGE, CREAM],
  });
  const sample = sampleColour(frame, box);
  assert.ok(sample.share > MIN_SAMPLE_SHARE, `share was ${sample.share}`);
  const profile = calibrate(frame, box);
  assert.ok(profile, 'a two-tone basketball was refused');
  assert.equal(profile.kind, 'chroma');
  // It must land on the orange, not somewhere between orange and cream.
  const total = ORANGE[0] + ORANGE[1] + ORANGE[2];
  assert.ok(Math.hypot(profile.nr - ORANGE[0] / total,
                       profile.ng - ORANGE[1] / total) < 0.01,
    `fitted (${profile.nr}, ${profile.ng}), not the orange`);
});

test('calibration still accepts the balls that are one colour', () => {
  // Seams, a logo and half the ball in shadow must all still calibrate. The
  // margin matters more than the pass: these are what the threshold is set
  // against, so the test reports how close each one runs.
  const box = { x: 66, y: 24, w: 60, h: 60 };
  const cases = {
    // Chroma, not brightness, is what is clustered -- so a ball half in
    // shadow is one colour, and so is a black-and-white football, because
    // black and white sit on the same point and differ only in luma.
    'plain white': [[248, 250, 246]],
    'white in patchy sun': [[248, 250, 246], [150, 152, 148]],
    'black-and-white football': [[248, 250, 246], [25, 25, 28],
                                 [248, 250, 246], [248, 250, 246]],
    'optic tennis': [[222, 232, 58]],
    'basketball with seams': [[205, 110, 45], [25, 25, 28], [205, 110, 45],
                              [205, 110, 45], [205, 110, 45], [205, 110, 45],
                              [205, 110, 45], [205, 110, 45]],
  };
  for (const [name, panels] of Object.entries(cases)) {
    const frame = panelledFrame({ x: 96, y: 54, r: 40, panels });
    const { share } = sampleColour(frame, box);
    assert.ok(share >= MIN_SAMPLE_SHARE,
      `${name} read as multi-coloured at ${(share * 100).toFixed(0)}%`);
    assert.ok(calibrate(frame, box), `${name} was refused`);
  }
});

test('no preset matches a gym floor, sand, or a cream ball panel', () => {
  // A deliberate absence, recorded so it is not undone by accident. The
  // two-tone basketball's cream panels have no preset and must not get one:
  // that colour is 0.005 from sand, 0.02 from pale wood and 0.05 from a
  // hardwood court -- the surfaces the sport is played on. The orange two
  // thirds is what finds that ball, and it is enough.
  const surfaces = [
    [226, 206, 164], [200, 180, 140], [205, 175, 135], [190, 150, 100],
  ];
  for (const [name, profile] of Object.entries(PRESETS)) {
    for (const surface of surfaces) {
      assert.equal(matchPixel(...surface, profile), 0,
        `${name} matched ${surface}`);
    }
  }
});

test('an empty sample and a refused one are different answers', () => {
  // The banner says different things for these, so they must be tellable
  // apart: no pixels at all is null, a ball with no dominant colour is a
  // sample with a low share.
  const frame = panelledFrame({ x: 96, y: 54, r: 7, panels: [[248, 250, 246]] });
  assert.equal(sampleColour(frame, { x: 10, y: 10, w: 0, h: 0 }), null);
  assert.ok(sampleColour(frame, { x: 80, y: 40, w: 30, h: 30 }));
});
