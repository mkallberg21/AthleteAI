/**
 * Counter engine tests, driven by synthetic pose streams.
 *
 * Each test builds a landmark stream describing a known movement, then asserts
 * the counter recovers the rep count it was built from. This is the only way to
 * check the detector without a camera and a lacrosse stick.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import { RepCounter, computeSignal, elbowFlare, saveZone, stanceWidthSignal, wallBallSignal, LANDMARKS } from '../../offdays/web/static/counter.js';

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

/** One arm thrown at a point while the other stays at the chest. */
function oneArmedAt(x, y) {
  const pts = baseSkeleton();
  pts[IDX.right_wrist] = { x, y, z: 0, visibility: 0.95 };
  pts[IDX.left_wrist] = { x: 0.50, y: 0.42, z: 0, visibility: 0.95 };
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


/* -------------------------------------------------------------------------
 * Two hands, or it is not a save.
 *
 * Throwing one arm at the ball is the habit every goalie coach spends a
 * season removing. The first version of this signal took whichever wrist was
 * further out, so a one-armed flail scored exactly like a proper save -- at
 * full marks. Reach is now measured from the midpoint of the two wrists,
 * which makes the requirement arithmetic rather than a rule that has to
 * detect and argue about intent.
 * ---------------------------------------------------------------------- */

test('save reach: a one-armed stab measures roughly half a real save', () => {
  const drill = spec('lax_goalie_saves');
  const [x, y] = SPOTS.high_right;
  const both = computeSignal(reachingTo(x, y), drill).value;
  const one = computeSignal(oneArmedAt(x, y), drill).value;
  assert.ok(one < both / 1.9, `one-armed ${one} vs two-handed ${both}`);
  // And specifically: it never reaches the line that fires a rep.
  assert.ok(one < drill.counter.up_threshold, `one-armed ${one} would still fire`);
});

test('save reach: a missing hand is no signal at all, not a smaller one', () => {
  const drill = spec('lax_goalie_saves');
  const pts = reachingTo(...SPOTS.low_left);
  pts[IDX.left_wrist].visibility = 0.1;
  assert.equal(computeSignal(pts, drill), null);
});

test('cued drill: one-armed saves do not count', () => {
  const drill = spec('lax_goalie_saves');
  const counter = new RepCounter(drill);
  let t = 0;
  for (let i = 0; i < 6; i += 1) { counter.push(readySkeleton(), t); t += 33; }

  const [tx, ty] = SPOTS.high_right;
  for (let rep = 0; rep < 6; rep += 1) {
    for (let i = 1; i <= 9; i += 1) {
      const k = i / 9;
      counter.push(oneArmedAt(0.50 + (tx - 0.50) * k, 0.42 + (ty - 0.42) * k), t);
      t += 33;
    }
    for (let i = 8; i >= 0; i -= 1) {
      const k = i / 9;
      counter.push(oneArmedAt(0.50 + (tx - 0.50) * k, 0.42 + (ty - 0.42) * k), t);
      t += 33;
    }
    for (let i = 0; i < 4; i += 1) { counter.push(readySkeleton(), t); t += 33; }
  }
  assert.equal(counter.count, 0);
});

test('cued drill: the same six saves count when both hands go', () => {
  // The other half of the test above -- without it, a signal that counted
  // nothing at all would pass.
  const drill = spec('lax_goalie_saves');
  const counter = new RepCounter(drill);
  let t = 0;
  for (let i = 0; i < 6; i += 1) { counter.push(readySkeleton(), t); t += 33; }
  for (let rep = 0; rep < 6; rep += 1) t = playSave(counter, 'high_right', t);
  assert.equal(counter.count, 6);
});

test('save reach: the leading hand is still reported for off-hand credit', () => {
  const drill = spec('lax_goalie_saves');
  const left = computeSignal(reachingTo(...SPOTS.high_left), drill);
  const right = computeSignal(reachingTo(...SPOTS.high_right), drill);
  assert.equal(left.hand, 'left');
  assert.equal(right.hand, 'right');
});


/* -------------------------------------------------------------------------
 * Stance width: the first horizontal signal in the library.
 *
 * Every other signal here measures a height or an angle, which is why the
 * most common footwork in several sports had no drill anywhere. This one is
 * signed on purpose: a shuffle keeps the feet apart and stays positive, and
 * the moment they cross it goes negative -- so the cardinal error of defensive
 * footwork is a sign change rather than a judgement call about form.
 * ---------------------------------------------------------------------- */

/** Feet at the given frame positions; shoulders and hips left square. */
function standing(leftAnkleX, rightAnkleX) {
  const pts = baseSkeleton();
  pts[IDX.left_ankle] = { x: leftAnkleX, y: 0.95, z: 0, visibility: 0.95 };
  pts[IDX.right_ankle] = { x: rightAnkleX, y: 0.95, z: 0, visibility: 0.95 };
  return pts;
}

/** Feet `width` torso lengths apart, centred. Negative width crosses them. */
function stanceOf(width) {
  return standing(0.5 - (width * TORSO) / 2, 0.5 + (width * TORSO) / 2);
}

test('stance width: measures how far apart the feet are, in torso lengths', () => {
  const drill = spec('bkb_slide');
  for (const want of [0.4, 1.3, 1.8, 2.1]) {
    const got = computeSignal(stanceOf(want), drill).value;
    assert.ok(Math.abs(got - want) < 0.02, `${want} read as ${got}`);
  }
});

test('stance width: goes negative the moment the feet cross', () => {
  const drill = spec('bkb_slide');
  // The whole reason this signal is signed rather than a distance.
  assert.ok(computeSignal(stanceOf(1.4), drill).value > 0);
  assert.ok(computeSignal(standing(0.56, 0.44), drill).value < 0);
});

test('stance width: crossing is read from the athlete, not the picture', () => {
  const drill = spec('bkb_slide');
  // Turn them around. The same screen positions are now an ordinary stance,
  // because left and right have swapped -- a raw x would call this crossed.
  const pts = standing(0.56, 0.44);
  pts[IDX.left_shoulder] = { x: 0.55, y: 0.35, z: 0, visibility: 0.95 };
  pts[IDX.right_shoulder] = { x: 0.45, y: 0.35, z: 0, visibility: 0.95 };
  assert.ok(computeSignal(pts, drill).value > 0);
});

test('stance width: side-on it says nothing rather than reporting a cross', () => {
  const drill = spec('bkb_slide');
  const pts = stanceOf(1.6);
  // Shoulders collapsed: there is no left-right axis left to project onto, and
  // a projection onto a collapsed axis reports a crossed step for a good one.
  pts[IDX.left_shoulder] = { x: 0.495, y: 0.35, z: 0, visibility: 0.95 };
  pts[IDX.right_shoulder] = { x: 0.505, y: 0.35, z: 0, visibility: 0.95 };
  assert.equal(computeSignal(pts, drill), null);
});

test('stance width: a missing foot is no signal at all', () => {
  const drill = spec('bkb_slide');
  const pts = stanceOf(1.6);
  pts[IDX.left_ankle].visibility = 0.1;
  assert.equal(computeSignal(pts, drill), null);
});

/** One slide step: push out to `peak` width and let the trail foot catch up. */
function playSlide(counter, startMs, { peak = 2.05, base = 1.25, cross = false } = {}) {
  let t = startMs;
  const step = 1000 / 30;
  for (let i = 1; i <= 7; i += 1) {
    counter.push(stanceOf(base + (peak - base) * (i / 7)), t);
    t += step;
  }
  for (let i = 6; i >= 0; i -= 1) {
    // A crossed step is the trail foot swinging through the standing one, which
    // happens partway through the recovery -- not at the very end. Modelled at
    // the end it would still be crossed as the next step arms, and the next
    // step really would be starting from crossed feet.
    const w = cross && (i === 4 || i === 3) ? -0.35 : base + (peak - base) * (i / 7);
    counter.push(stanceOf(w), t);
    t += step;
  }
  for (let i = 0; i < 3; i += 1) { counter.push(stanceOf(base), t); t += step; }
  return t;
}

test('defensive slides: counts one rep per push', () => {
  const drill = spec('bkb_slide');
  const counter = new RepCounter(drill);
  let t = 0;
  for (let i = 0; i < 5; i += 1) { counter.push(stanceOf(1.25), t); t += 33; }
  for (let i = 0; i < 8; i += 1) t = playSlide(counter, t);
  assert.equal(counter.count, 8);
});

test('defensive slides: a step that never widens does not count', () => {
  // Shuffling on the spot without covering ground is the failure mode this
  // drill exists to catch, and it should read as nothing rather than as work.
  const drill = spec('bkb_slide');
  const counter = new RepCounter(drill);
  let t = 0;
  for (let i = 0; i < 5; i += 1) { counter.push(stanceOf(1.25), t); t += 33; }
  for (let i = 0; i < 8; i += 1) t = playSlide(counter, t, { peak: 1.55 });
  assert.equal(counter.count, 0);
});

test('defensive slides: a crossed step still counts, and is flagged', () => {
  // Counting it matters: the athlete did the work and a rep quietly vanishing
  // teaches nothing. The flag is what turns it into coaching.
  const drill = spec('bkb_slide');
  const counter = new RepCounter(drill);
  let t = 0;
  for (let i = 0; i < 5; i += 1) { counter.push(stanceOf(1.25), t); t += 33; }
  t = playSlide(counter, t);
  t = playSlide(counter, t, { cross: true });
  t = playSlide(counter, t);
  assert.equal(counter.count, 3);
  assert.deepEqual(counter.reps.map((r) => r.crossed), [false, true, false]);
});

test('defensive slides: the flag resets between reps', () => {
  // A single crossed step must not stain every rep after it.
  const drill = spec('bkb_slide');
  const counter = new RepCounter(drill);
  let t = 0;
  for (let i = 0; i < 5; i += 1) { counter.push(stanceOf(1.25), t); t += 33; }
  t = playSlide(counter, t, { cross: true });
  for (let i = 0; i < 4; i += 1) t = playSlide(counter, t);
  assert.equal(counter.reps.filter((r) => r.crossed).length, 1);
});

test('drills that are not stance-width carry no crossed field', () => {
  const drill = spec('lax_goalie_saves');
  const counter = new RepCounter(drill);
  let t = 0;
  for (let i = 0; i < 6; i += 1) { counter.push(readySkeleton(), t); t += 33; }
  t = playSave(counter, 'high_right', t);
  assert.ok(counter.count > 0);
  for (const rep of counter.reps) assert.ok(!('crossed' in rep));
});


/* -------------------------------------------------------------------------
 * Form shooting.
 *
 * The drill that was called too hard twice, and the reason was never the
 * motion -- it is that the app cannot see whether the ball went in. So it does
 * not try. It reads the elbow, which is what every shooting coach says first
 * and the one part of a shot pose genuinely sees.
 * ---------------------------------------------------------------------- */

/**
 * A shooter with the elbow at a chosen interior angle.
 *
 * The wrist is placed by rotating the forearm off the upper arm, so the angle
 * is the thing being set rather than something that falls out of two guessed
 * positions. `elbowOut` then pushes the elbow sideways from under the wrist,
 * which is the flare this drill exists to catch.
 */
function shooter({ side = 'right', angle = 170, elbowOut = 0.0 } = {}) {
  const pts = baseSkeleton();
  const sign = side === 'right' ? 1 : -1;
  const shoulder = { x: side === 'right' ? 0.55 : 0.45, y: 0.35 };
  const LIMB = 0.125;

  // Upper arm out and slightly up from the shoulder, with the flare applied
  // sideways so the elbow leaves the line between shoulder and wrist.
  const elbow = {
    x: shoulder.x + sign * (0.02 + elbowOut),
    y: shoulder.y - 0.06,
  };

  // Forearm: rotate the elbow-to-shoulder vector by the interior angle.
  const ux = shoulder.x - elbow.x;
  const uy = shoulder.y - elbow.y;
  const mag = Math.hypot(ux, uy) || 1;
  const rad = (angle * Math.PI) / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad) * sign;
  const wrist = {
    x: elbow.x + ((ux * cos - uy * sin) / mag) * LIMB,
    y: elbow.y + ((ux * sin + uy * cos) / mag) * LIMB,
  };

  const put = (name, p) => { pts[IDX[name]] = { x: p.x, y: p.y, z: 0, visibility: 0.95 }; };
  put(`${side}_elbow`, elbow);
  put(`${side}_wrist`, wrist);
  // The other hand stays down and out of the way, so the higher wrist -- and
  // therefore the shooting arm -- is unambiguous.
  const other = side === 'right' ? 'left' : 'right';
  put(`${other}_wrist`, { x: other === 'right' ? 0.62 : 0.38, y: 0.60 });
  return pts;
}

test('form shooting: the shooting arm is picked from the frame, not the spec', () => {
  // The whole reason this is not a plain joint_angle. A left-handed shooter
  // with both arms visible would otherwise be measured on the arm that is not
  // shooting, and handedness cannot live in a spec every athlete shares.
  const drill = spec('bkb_form_shot');
  assert.equal(computeSignal(shooter({ side: 'right' }), drill).hand, 'right');
  assert.equal(computeSignal(shooter({ side: 'left' }), drill).hand, 'left');
});

test('form shooting: a lefty and a righty read the same angle', () => {
  const drill = spec('bkb_form_shot');
  const r = computeSignal(shooter({ side: 'right' }), drill).value;
  const l = computeSignal(shooter({ side: 'left' }), drill).value;
  assert.ok(Math.abs(r - l) < 1, `${r} vs ${l}`);
});

test('elbow flare: an elbow under the ball reads near zero', () => {
  assert.ok(elbowFlare(shooter({ elbowOut: 0.0 })) < 0.2);
});

test('elbow flare: a flared elbow reads high, whichever side it is', () => {
  for (const side of ['right', 'left']) {
    const flared = elbowFlare(shooter({ side, elbowOut: 0.09 }));
    assert.ok(flared > 0.3, `${side} flare read ${flared}`);
  }
});

test('elbow flare: side-on it says nothing rather than a perfect elbow', () => {
  // From the side an elbow is behind the wrist rather than beside it, and the
  // projection would report a perfect shot for any shot at all.
  const pts = shooter({ elbowOut: 0.09 });
  pts[IDX.left_shoulder] = { x: 0.495, y: 0.35, z: 0, visibility: 0.95 };
  pts[IDX.right_shoulder] = { x: 0.505, y: 0.35, z: 0, visibility: 0.95 };
  assert.equal(elbowFlare(pts), null);
});

/** One shot: dip into the pocket, extend through release, recover. */
function playShot(counter, startMs, { elbowOut = 0.0, side = 'right' } = {}) {
  let t = startMs;
  const step = 1000 / 30;
  const DIP = 70, RELEASE = 172;
  for (let i = 0; i < 5; i += 1) {
    counter.push(shooter({ side, angle: DIP, elbowOut }), t); t += step;
  }
  for (let i = 1; i <= 9; i += 1) {
    const a = DIP + (RELEASE - DIP) * (i / 9);
    counter.push(shooter({ side, angle: a, elbowOut }), t); t += step;
  }
  for (let i = 0; i < 5; i += 1) {
    counter.push(shooter({ side, angle: RELEASE, elbowOut }), t); t += step;
  }
  return t;
}

test('form shooting: counts one rep per shot', () => {
  const drill = spec('bkb_form_shot');
  const counter = new RepCounter(drill);
  let t = 0;
  for (let i = 0; i < 6; i += 1) t = playShot(counter, t);
  assert.equal(counter.count, 6);
});

test('form shooting: every rep carries the elbow at release', () => {
  const drill = spec('bkb_form_shot');
  const counter = new RepCounter(drill);
  let t = 0;
  for (let i = 0; i < 4; i += 1) t = playShot(counter, t, { elbowOut: 0.09 });
  assert.equal(counter.count, 4);
  for (const rep of counter.reps) {
    assert.ok(typeof rep.flare === 'number', JSON.stringify(rep));
    assert.ok(rep.flare > 0.3, `flare ${rep.flare}`);
  }
});

test('form shooting: a clean elbow and a flared one are told apart', () => {
  const drill = spec('bkb_form_shot');
  const clean = new RepCounter(drill);
  const flared = new RepCounter(drill);
  let a = 0, b = 0;
  for (let i = 0; i < 4; i += 1) {
    a = playShot(clean, a, { elbowOut: 0.0 });
    b = playShot(flared, b, { elbowOut: 0.09 });
  }
  const median = (c) => c.reps.map((r) => r.flare).sort((x, y) => x - y)[1];
  assert.ok(median(clean) < median(flared) - 0.2,
    `${median(clean)} vs ${median(flared)}`);
});

test('drills that are not shooting carry no flare field', () => {
  const drill = spec('bkb_slide');
  const counter = new RepCounter(drill);
  let t = 0;
  for (let i = 0; i < 5; i += 1) { counter.push(stanceOf(1.25), t); t += 33; }
  t = playSlide(counter, t);
  assert.ok(counter.count > 0);
  for (const rep of counter.reps) assert.ok(!('flare' in rep));
});
