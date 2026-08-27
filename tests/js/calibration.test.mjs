/**
 * Calibration guard.
 *
 * Drives every drill with a synthetic textbook full-range rep and asserts two
 * things: that the drill actually counts those reps, and that the range of
 * motion it reports lands near the `target_rom` its QualitySpec claims.
 *
 * This exists because it caught a real bug. Squat jumps were smoothed so
 * heavily that a one-second cycle lost ~27% of its amplitude, the signal never
 * fell back to the arming threshold, and the drill counted one rep in
 * twenty-four -- in real use, not just here. Nothing else in the suite would
 * have noticed, because every other test drives a drill whose thresholds
 * already worked.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import { RepCounter, LANDMARKS } from '../../offdays/web/static/counter.js';

const IDX = Object.fromEntries(LANDMARKS.map((n, i) => [n, i]));
const SPECS = JSON.parse(process.env.DRILL_SPECS);
const TORSO = 0.25;

function base() {
  const p = LANDMARKS.map(() => ({ x: 0.5, y: 0.5, z: 0, visibility: 0.95 }));
  p[IDX.left_shoulder] = { x: 0.45, y: 0.35, z: 0, visibility: 0.95 };
  p[IDX.right_shoulder] = { x: 0.55, y: 0.35, z: 0, visibility: 0.95 };
  p[IDX.left_hip] = { x: 0.46, y: 0.60, z: 0, visibility: 0.95 };
  p[IDX.right_hip] = { x: 0.54, y: 0.60, z: 0, visibility: 0.95 };
  p[IDX.left_ankle] = { x: 0.46, y: 0.95, z: 0, visibility: 0.95 };
  p[IDX.right_ankle] = { x: 0.54, y: 0.95, z: 0, visibility: 0.95 };
  p[IDX.nose] = { x: 0.50, y: 0.22, z: 0, visibility: 0.95 };
  return p;
}

/** Place a limb end so the angle at `joint` equals `deg`. */
function setAngle(pts, aName, jName, wName, anchor, joint, deg, len) {
  pts[IDX[jName]] = { x: joint.x, y: joint.y, z: 0, visibility: 0.95 };
  const baseAng = Math.atan2(anchor.y - joint.y, anchor.x - joint.x);
  const target = baseAng - (deg * Math.PI) / 180;
  pts[IDX[wName]] = {
    x: joint.x + len * Math.cos(target),
    y: joint.y + len * Math.sin(target), z: 0, visibility: 0.95,
  };
}

// A textbook rep for each drill: the signal sweeps between these two values.
const SWEEP = {
  lax_wall_ball:     { lo: -0.15, hi: 0.40, kind: 'wrist' },
  lax_quick_stick:   { lo: -0.05, hi: 0.30, kind: 'wrist' },
  gen_push_up:       { lo: 70,    hi: 175,  kind: 'elbow' },
  gen_squat:         { lo: 85,    hi: 172,  kind: 'knee' },
  gen_sit_up:        { lo: 55,    hi: 135,  kind: 'hip' },
  gen_pull_up:       { lo: -0.38, hi: 0.04, kind: 'pull' },
  gen_jumping_jack:  { lo: -0.35, hi: 0.30, kind: 'jack' },
  gen_high_knees:    { lo: -0.45, hi: 0.05, kind: 'knee_h' },
  gen_burpee:        { lo: 0.12,  hi: 0.92, kind: 'body' },
  gen_squat_jump:    { lo: 0.38,  hi: 1.05, kind: 'body' },
  gen_lateral_bound: { lo: -0.20, hi: 0.20, kind: 'ankles' },
  gen_lunge:         { lo: 88,    hi: 168,  kind: 'knee' },
  gen_glute_bridge:  { lo: 105,   hi: 172,  kind: 'hip' },
  gen_mountain_climber: { lo: -0.10, hi: 0.34, kind: 'knee_rel' },
  gen_tuck_jump:     { lo: 0.36,  hi: 1.08,  kind: 'body' },
  gen_dead_bug:      { lo: 92,    hi: 168,  kind: 'hip' },
  // Ready position out to a committed save and back, in torso lengths.
  lax_goalie_saves:  { lo: 0.40,  hi: 1.18, kind: 'reach' },
  // Defensive stance out to a full slide step and back, measured at the feet.
  bkb_slide:         { lo: 1.22,  hi: 2.00, kind: 'stance' },
};

// Hold drills score time in a valid band rather than a rep cycle, so a swept
// sine says nothing about them. They are covered by tests/test_drills.py.
const HOLD_DRILLS = new Set(SPECS.filter((d) => d.metric === 'hold').map((d) => d.key));

// Ball drills count contacts, not a pose signal, so sweeping a joint angle
// through them measures nothing. Their equivalent guard is ball.test.mjs,
// which drives synthetic trajectories the same way this drives synthetic reps.
const BALL_DRILLS = new Set(SPECS.filter((d) => d.ball).map((d) => d.key));

function frame(kind, v) {
  const pts = base();
  if (kind === 'wrist') {
    pts[IDX.right_wrist] = { x: 0.58, y: 0.35 - v * TORSO, z: 0, visibility: 0.95 };
    pts[IDX.left_wrist] = { x: 0.42, y: 0.35 - (v - 0.5) * TORSO, z: 0, visibility: 0.95 };
  } else if (kind === 'elbow') {
    setAngle(pts, 'left_shoulder', 'left_elbow', 'left_wrist',
             { x: 0.45, y: 0.35 }, { x: 0.45, y: 0.50 }, v, 0.15);
  } else if (kind === 'knee') {
    setAngle(pts, 'left_hip', 'left_knee', 'left_ankle',
             { x: 0.46, y: 0.60 }, { x: 0.46, y: 0.78 }, v, 0.17);
  } else if (kind === 'hip') {
    setAngle(pts, 'left_shoulder', 'left_hip', 'left_knee',
             { x: 0.45, y: 0.35 }, { x: 0.46, y: 0.60 }, v, 0.18);
  } else if (kind === 'pull') {
    pts[IDX.left_wrist] = { x: 0.42, y: 0.30, z: 0, visibility: 0.95 };
    pts[IDX.right_wrist] = { x: 0.58, y: 0.30, z: 0, visibility: 0.95 };
    pts[IDX.nose] = { x: 0.50, y: 0.30 - v * TORSO, z: 0, visibility: 0.95 };
  } else if (kind === 'jack') {
    pts[IDX.left_wrist] = { x: 0.42, y: 0.35 - v * TORSO, z: 0, visibility: 0.95 };
    pts[IDX.right_wrist] = { x: 0.58, y: 0.35 - v * TORSO, z: 0, visibility: 0.95 };
  } else if (kind === 'knee_h') {
    pts[IDX.left_knee] = { x: 0.46, y: 0.60 - v * TORSO, z: 0, visibility: 0.95 };
  } else if (kind === 'knee_rel') {
    // Knee height measured against the hip rather than the shoulders.
    pts[IDX.left_knee] = { x: 0.46, y: 0.60 - v * TORSO, z: 0, visibility: 0.95 };
  } else if (kind === 'body') {
    const ground = 0.95;
    const hipY = ground - v * TORSO;
    pts[IDX.left_hip] = { x: 0.46, y: hipY, z: 0, visibility: 0.95 };
    pts[IDX.right_hip] = { x: 0.54, y: hipY, z: 0, visibility: 0.95 };
    pts[IDX.left_shoulder] = { x: 0.45, y: hipY - 0.25, z: 0, visibility: 0.95 };
    pts[IDX.right_shoulder] = { x: 0.55, y: hipY - 0.25, z: 0, visibility: 0.95 };
  } else if (kind === 'stance') {
    // Feet apart by v torso lengths, centred under the athlete. The sweep only
    // has to exercise counting and range; the sign -- which is what catches a
    // crossed step -- is tested in counter.test.mjs.
    pts[IDX.left_ankle] = { x: 0.5 - (v * TORSO) / 2, y: 0.95, z: 0, visibility: 0.95 };
    pts[IDX.right_ankle] = { x: 0.5 + (v * TORSO) / 2, y: 0.95, z: 0, visibility: 0.95 };
  } else if (kind === 'reach') {
    // Both hands the same distance from the chest. The sweep only has to
    // exercise counting and range; where the hands went is saveZone's job and
    // is tested in counter.test.mjs.
    pts[IDX.left_wrist] = { x: 0.49, y: 0.35 + v * TORSO, z: 0, visibility: 0.95 };
    pts[IDX.right_wrist] = { x: 0.51, y: 0.35 + v * TORSO, z: 0, visibility: 0.95 };
  } else if (kind === 'ankles') {
    pts[IDX.left_ankle] = { x: 0.46, y: 0.95 - v * TORSO, z: 0, visibility: 0.95 };
    pts[IDX.right_ankle] = { x: 0.54, y: 0.95, z: 0, visibility: 0.95 };
  }
  return pts;
}

// A drill with no sweep entry used to be skipped in silence, which meant a
// newly added drill was unguarded and looked green. Now it fails.
test('every rep-counted drill has a calibration sweep', () => {
  const missing = SPECS
    .filter((d) => !HOLD_DRILLS.has(d.key) && !BALL_DRILLS.has(d.key) && !SWEEP[d.key])
    .map((d) => d.key);
  assert.deepEqual(missing, [],
    `these drills are not calibration-tested: ${missing.join(', ')}`);
});

for (const drill of SPECS) {
  const sweep = SWEEP[drill.key];
  if (!sweep) continue;

  test(`${drill.key}: a textbook rep counts and measures near target_rom`, () => {
  const counter = new RepCounter(drill);
  const mid = (sweep.lo + sweep.hi) / 2;
  const amp = (sweep.hi - sweep.lo) / 2;
  const framesPerRep = 30;
  let t = 0;
  for (let r = 0; r < 24; r += 1) {
    for (let f = 0; f < framesPerRep; f += 1) {
      const v = mid - amp * Math.cos((2 * Math.PI * f) / framesPerRep);
      counter.push(frame(sweep.kind, v), t);
      t += 1000 / 30;
    }
  }
    // At least half the driven reps must register. Anything less means the
    // thresholds and smoothing are fighting each other.
    assert.ok(counter.reps.length >= 12,
      `${drill.key} counted only ${counter.reps.length} of 24 textbook reps`);

    const roms = counter.reps.map((r) => r.rom).filter((r) => r > 0);
    assert.ok(roms.length > 0, `${drill.key} reported no range of motion`);
    roms.sort((a, b) => a - b);
    const median = roms[Math.floor(roms.length / 2)];

    const target = drill.quality.target_rom;
    const ratio = median / target;
    // A textbook rep should score full depth, so the measured range has to sit
    // close to the target rather than merely correlate with it.
    assert.ok(ratio > 0.85 && ratio < 1.2,
      `${drill.key}: textbook rep measured ${median.toFixed(3)} against `
      + `target_rom ${target} (ratio ${ratio.toFixed(2)}) -- recalibrate`);
  });
}
