/**
 * Counter engine tests, driven by synthetic pose streams.
 *
 * Each test builds a landmark stream describing a known movement, then asserts
 * the counter recovers the rep count it was built from. This is the only way to
 * check the detector without a camera and a lacrosse stick.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import { RepCounter, computeSignal, saveZone, wallBallSignal, LANDMARKS } from '../../offdays/web/static/counter.js';

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

test('reps carry the shape data form scoring needs', () => {
  const drill = spec('lax_wall_ball');
  const counter = new RepCounter(drill);
  const CYCLES = 20, FPS = 30, CYCLE_MS = 900;
  const framesPerCycle = Math.round((CYCLE_MS / 1000) * FPS);

  let t = 0;
  for (let c = 0; c < CYCLES; c += 1) {
    for (let f = 0; f < framesPerCycle; f += 1) {
      const phase = f / framesPerCycle;
      const h = 0.125 - 0.275 * Math.cos(2 * Math.PI * phase);
      const pts = baseSkeleton();
      pts[IDX.right_wrist] = { x: 0.58, y: 0.35 - h * TORSO, z: 0, visibility: 0.95 };
      pts[IDX.left_wrist] = { x: 0.42, y: 0.35 - (h - 0.5) * TORSO, z: 0, visibility: 0.95 };
      counter.push(pts, t);
      t += 1000 / FPS;
    }
  }

  assert.ok(counter.reps.length >= 15, `expected reps, got ${counter.reps.length}`);
  for (const rep of counter.reps) {
    assert.ok(typeof rep.rom === 'number' && rep.rom > 0, `rep has no range of motion: ${JSON.stringify(rep)}`);
    assert.ok(typeof rep.cycle_ms === 'number' && rep.cycle_ms > 0, 'rep has no cycle duration');
    assert.ok(typeof rep.peak === 'number', 'rep has no peak');
  }

  // The synthetic motion swings a fixed distance, so measured range of motion
  // must be stable across reps -- this is what a consistency score reads.
  const roms = counter.reps.map((r) => r.rom);
  const mean = roms.reduce((a, b) => a + b, 0) / roms.length;
  const spread = Math.sqrt(roms.reduce((a, b) => a + (b - mean) ** 2, 0) / roms.length) / mean;
  assert.ok(spread < 0.15, `constant motion should give consistent ROM, got spread ${spread.toFixed(3)}`);
});

test('a shallower movement reports a smaller range of motion', () => {
  const drill = spec('lax_wall_ball');

  function run(amplitude) {
    const counter = new RepCounter(drill);
    let t = 0;
    for (let c = 0; c < 20; c += 1) {
      for (let f = 0; f < 27; f += 1) {
        const phase = f / 27;
        // Centre stays put; only the swing size changes.
        const h = 0.125 - amplitude * Math.cos(2 * Math.PI * phase);
        const pts = baseSkeleton();
        pts[IDX.right_wrist] = { x: 0.58, y: 0.35 - h * TORSO, z: 0, visibility: 0.95 };
        pts[IDX.left_wrist] = { x: 0.42, y: 0.35 - (h - 0.5) * TORSO, z: 0, visibility: 0.95 };
        counter.push(pts, t);
        t += 1000 / 30;
      }
    }
    const roms = counter.reps.map((r) => r.rom).filter((r) => r > 0);
    return {
      reps: counter.reps.length,
      rom: roms.length ? roms.reduce((a, b) => a + b, 0) / roms.length : 0,
    };
  }

  const full = run(0.275);
  const shallow = run(0.235);

  // Both movements have to actually count, or this is comparing nothing.
  assert.ok(full.reps >= 15 && shallow.reps >= 15,
    `both amplitudes must count: full=${full.reps} shallow=${shallow.reps}`);
  assert.ok(full.rom > shallow.rom * 1.08,
    `shallower reps must report less range: full=${full.rom.toFixed(3)} shallow=${shallow.rom.toFixed(3)}`);
});

test('a movement too small to cross the thresholds is not a rep', () => {
  // Hysteresis is what makes range of motion meaningful: anything counted has
  // crossed the full span, so a twitch cannot register as a shallow rep.
  const drill = spec('lax_wall_ball');
  const counter = new RepCounter(drill);
  let t = 0;
  for (let c = 0; c < 20; c += 1) {
    for (let f = 0; f < 27; f += 1) {
      const h = 0.125 - 0.05 * Math.cos((2 * Math.PI * f) / 27);
      const pts = baseSkeleton();
      pts[IDX.right_wrist] = { x: 0.58, y: 0.35 - h * TORSO, z: 0, visibility: 0.95 };
      pts[IDX.left_wrist] = { x: 0.42, y: 0.50, z: 0, visibility: 0.95 };
      counter.push(pts, t);
      t += 1000 / 30;
    }
  }
  assert.strictEqual(counter.count, 0, 'a small twitch must not count as a rep');
});

/* -------------------------------------------------------------------------
 * Cued drills: reach counts the rep, the zone recovers where it went.
 *
 * These use their own skeletons rather than `baseSkeleton`, whose arms hang by
 * the hips -- a goalie starts with the hands up in front of the chest, and the
 * whole measurement is the distance between those two positions.
 * ---------------------------------------------------------------------- */

/** Goalie ready: both hands up in front of the chest, elbows bent. */
function readySkeleton() {
  const pts = baseSkeleton();
  pts[IDX.left_wrist] = { x: 0.46, y: 0.42, z: 0, visibility: 0.95 };
  pts[IDX.right_wrist] = { x: 0.54, y: 0.42, z: 0, visibility: 0.95 };
  return pts;
}

/** Hands driven out to a point, as they are on a save. */
function reachingTo(x, y) {
  const pts = baseSkeleton();
  pts[IDX.left_wrist] = { x: x - 0.01, y, z: 0, visibility: 0.95 };
  pts[IDX.right_wrist] = { x: x + 0.01, y, z: 0, visibility: 0.95 };
  return pts;
}

// Chosen against the base skeleton's geometry: shoulders at y 0.35, hips at
// 0.60, so a torso is 0.25 and the shoulder midpoint is (0.50, 0.35).
const SPOTS = {
  high_right: [0.76, 0.20],
  high_left: [0.24, 0.20],
  mid_right: [0.76, 0.50],
  mid_left: [0.24, 0.50],
  low_right: [0.70, 0.68],
  low_left: [0.30, 0.68],
  low_centre: [0.50, 0.68],
};

test('save zone: every named spot classifies as itself', () => {
  const cues = spec('lax_goalie_saves').cues;
  for (const [zone, [x, y]] of Object.entries(SPOTS)) {
    assert.equal(saveZone(reachingTo(x, y), cues), zone, zone);
  }
});

test('save zone: hands left in front of the chest read as the middle, not as a corner', () => {
  const cues = spec('lax_goalie_saves').cues;
  // The failure this catches is a goalie who never really extends still being
  // credited with reaching whichever corner was called.
  assert.equal(saveZone(readySkeleton(), cues), 'mid_centre');
});

test('save zone: sides are the athlete\'s own, not the picture\'s', () => {
  const cues = spec('lax_goalie_saves').cues;
  const pts = reachingTo(...SPOTS.high_right);
  // Turn the athlete around: their shoulders swap sides of the frame, and a
  // hand at the same screen position is now their LEFT hand.
  pts[IDX.left_shoulder] = { x: 0.55, y: 0.35, z: 0, visibility: 0.95 };
  pts[IDX.right_shoulder] = { x: 0.45, y: 0.35, z: 0, visibility: 0.95 };
  assert.equal(saveZone(pts, cues), 'high_left');
});

test('save zone: turned side-on it says it cannot tell rather than guessing', () => {
  const cues = spec('lax_goalie_saves').cues;
  const pts = reachingTo(...SPOTS.low_left);
  // Shoulders collapsed onto each other: there is no left-right axis left to
  // project onto, and a guess here would teach the wrong corner.
  pts[IDX.left_shoulder] = { x: 0.495, y: 0.35, z: 0, visibility: 0.95 };
  pts[IDX.right_shoulder] = { x: 0.505, y: 0.35, z: 0, visibility: 0.95 };
  assert.equal(saveZone(pts, cues), 'unknown');
});

test('save zone: hands out of frame report unknown, not a zone', () => {
  const cues = spec('lax_goalie_saves').cues;
  const pts = reachingTo(...SPOTS.high_left);
  pts[IDX.left_wrist].visibility = 0.1;
  pts[IDX.right_wrist].visibility = 0.1;
  assert.equal(saveZone(pts, cues), 'unknown');
});

test('save zone: a self-paced drill gets no zone at all', () => {
  assert.equal(saveZone(readySkeleton(), spec('gen_push_up').cues), null);
});

test('save reach: rises leaving ready and falls coming back, whichever way the hands went', () => {
  const drill = spec('lax_goalie_saves');
  const ready = computeSignal(readySkeleton(), drill).value;
  // The point of measuring reach rather than height: a high save and a low
  // save both have to read as the same rep, and a height signal cannot do
  // that because they move in opposite directions.
  const high = computeSignal(reachingTo(...SPOTS.high_right), drill).value;
  const low = computeSignal(reachingTo(...SPOTS.low_left), drill).value;
  assert.ok(ready < drill.counter.down_threshold, `ready ${ready}`);
  assert.ok(high > drill.counter.up_threshold, `high ${high}`);
  assert.ok(low > drill.counter.up_threshold, `low ${low}`);
});

/** Drive one save out to `zone` and back to ready, feeding the counter. */
function playSave(counter, zone, startMs, { fps = 30 } = {}) {
  const [tx, ty] = SPOTS[zone];
  const step = 1000 / fps;
  let t = startMs;
  const OUT = 9, BACK = 9;
  for (let i = 1; i <= OUT; i += 1) {
    const k = i / OUT;
    counter.push(reachingTo(0.50 + (tx - 0.50) * k, 0.42 + (ty - 0.42) * k), t);
    t += step;
  }
  for (let i = BACK - 1; i >= 0; i -= 1) {
    const k = i / BACK;
    counter.push(reachingTo(0.50 + (tx - 0.50) * k, 0.42 + (ty - 0.42) * k), t);
    t += step;
  }
  for (let i = 0; i < 4; i += 1) { counter.push(readySkeleton(), t); t += step; }
  return t;
}

test('cued drill: counts one rep per save and tags it with the spot reached', () => {
  const drill = spec('lax_goalie_saves');
  const counter = new RepCounter(drill);
  const played = ['high_right', 'low_left', 'low_centre', 'mid_left', 'high_left'];

  let t = 0;
  for (let i = 0; i < 6; i += 1) { counter.push(readySkeleton(), t); t += 33; }
  for (const zone of played) t = playSave(counter, zone, t);

  assert.equal(counter.count, played.length);
  assert.deepEqual(counter.reps.map((r) => r.zone), played);
});

test('cued drill: the zone follows the furthest point, not the threshold crossing', () => {
  // The rep fires as the hands cross the firing line, which on a low save is
  // still up around hip height. Freezing the zone there would file every low
  // save as a hip save.
  const drill = spec('lax_goalie_saves');
  const counter = new RepCounter(drill);
  let t = 0;
  for (let i = 0; i < 6; i += 1) { counter.push(readySkeleton(), t); t += 33; }
  playSave(counter, 'low_left', t);
  assert.equal(counter.count, 1);
  assert.equal(counter.reps[0].zone, 'low_left');
});

test('cued drill: a save the camera could not read is marked unknown, never omitted', () => {
  const drill = spec('lax_goalie_saves');
  const counter = new RepCounter(drill);
  let t = 0;
  for (let i = 0; i < 6; i += 1) { counter.push(readySkeleton(), t); t += 33; }

  // Same movement, but turned side-on the whole way through.
  const [tx, ty] = SPOTS.high_right;
  const sideOn = (x, y) => {
    const pts = reachingTo(x, y);
    pts[IDX.left_shoulder] = { x: 0.495, y: 0.35, z: 0, visibility: 0.95 };
    pts[IDX.right_shoulder] = { x: 0.505, y: 0.35, z: 0, visibility: 0.95 };
    return pts;
  };
  for (let i = 1; i <= 9; i += 1) {
    counter.push(sideOn(0.50 + (tx - 0.50) * (i / 9), 0.42 + (ty - 0.42) * (i / 9)), t);
    t += 33;
  }
  for (let i = 8; i >= 0; i -= 1) {
    counter.push(sideOn(0.50 + (tx - 0.50) * (i / 9), 0.42 + (ty - 0.42) * (i / 9)), t);
    t += 33;
  }
  assert.equal(counter.count, 1);
  // The rep happened -- it just cannot be attributed. Omitting the field would
  // leave the server unable to tell this from a wrong corner.
  assert.equal(counter.reps[0].zone, 'unknown');
});

test('self-paced drills carry no zone field at all', () => {
  const drill = spec('gen_push_up');
  const counter = new RepCounter(drill);
  let t = 0;
  for (let i = 0; i < 60; i += 1) {
    const pts = baseSkeleton();
    // Elbow angle swinging between locked out and well below 90.
    const down = Math.floor(i / 10) % 2 === 1;
    pts[IDX.left_elbow] = down
      ? { x: 0.30, y: 0.48, z: 0, visibility: 0.95 }
      : { x: 0.42, y: 0.48, z: 0, visibility: 0.95 };
    pts[IDX.left_wrist] = { x: 0.42, y: 0.58, z: 0, visibility: 0.95 };
    counter.push(pts, t);
    t += 60;
  }
  for (const r of counter.reps) assert.ok(!('zone' in r));
});
