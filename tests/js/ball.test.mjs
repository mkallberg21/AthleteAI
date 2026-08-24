/**
 * Ball tracking.
 *
 * Driven with synthetic trajectories rather than footage, for the same reason
 * the pose calibration harness is: a physics model that only works on one
 * video is not a physics model. Every test here fixes a bug found while
 * building it, or a way of not-really-doing-the-drill that has to score zero.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import {
  BallTracker, ContactDetector, BallRepCounter, LANDMARK_INDEX,
} from '../../athleteiq/web/static/ball.js';
import { LANDMARKS } from '../../athleteiq/web/static/counter.js';
const SPECS = JSON.parse(process.env.DRILL_SPECS);
const spec = (key) => SPECS.find((d) => d.key === key);
const FPS = 30, DT = 1 / FPS;

function pose(points = {}) {
  const arr = LANDMARKS.map(() => ({ x: 0.5, y: 0.5, z: 0, visibility: 0.95 }));
  for (const [name, p] of Object.entries(points)) {
    arr[LANDMARK_INDEX[name]] = { x: p.x, y: p.y, z: 0, visibility: 0.95 };
  }
  return arr;
}

/** A ball bouncing off a fixed height, struck back up each time. */
function bounce({ g = 2.4, apex = 1.35, floor = 0.88, every = 3, frames = 300,
                  jitter = 0, x = 0.52 } = {}) {
  const out = [];
  let y = floor, vy = -apex, t = 0, seed = 7, hits = 0;
  for (let f = 0; f < frames; f += 1) {
    vy += g * DT; y += vy * DT;
    if (y >= floor && vy > 0) { y = floor; vy = -apex; hits += 1; }
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    const noise = jitter ? ((seed / 0x7fffffff) - 0.5) * jitter : 0;
    out.push({
      t,
      detection: f % every === 0
        ? { x: x + noise, y: y + noise, r: 0.03, score: 0.8 } : null,
    });
    t += DT * 1000;
  }
  return { frames: out, hits };
}

function run(counter, path, landmarks) {
  for (const { t, detection } of path.frames) counter.push(detection, landmarks, t);
  return counter;
}

test('gravity is learned from the footage, not assumed', () => {
  // A phone held close sees a ball accelerate across far more of the frame per
  // second than one filming from the sideline. Hard-coding it would make the
  // contact detector depend on camera distance.
  for (const g of [1.6, 2.4, 4.0, 6.0]) {
    const tracker = new BallTracker();
    for (const { t, detection } of bounce({ g, frames: 200 }).frames) {
      tracker.push(detection, t);
    }
    const ratio = tracker.gravity / g;
    assert.ok(ratio > 0.8 && ratio < 1.25,
      `learned ${tracker.gravity.toFixed(2)} for a true ${g}`);
  }
});

test('a contact is found for every strike, at any detection rate', () => {
  for (const every of [1, 2, 3]) {
    const path = bounce({ every });
    const counter = new BallRepCounter(spec('soc_juggle'));
    const landmarks = pose({ left_ankle: { x: 0.50, y: 0.88 } });
    run(counter, path, landmarks);
    assert.equal(counter.count, path.hits, `at 1-in-${every} detection`);
  }
});

test('a ball that is just sitting there counts nothing', () => {
  const counter = new BallRepCounter(spec('soc_juggle'));
  const landmarks = pose({ left_ankle: { x: 0.50, y: 0.88 } });
  for (let f = 0; f < 200; f += 1) {
    counter.push({ x: 0.5, y: 0.9, r: 0.03, score: 0.9 }, landmarks, f * DT * 1000);
  }
  assert.equal(counter.count, 0);
});

test('a ball in flight when recording starts is not a contact', () => {
  // The first measured velocity is compared against a standing start of zero,
  // which read as an impulse and added a phantom rep to every session.
  const counter = new BallRepCounter(spec('soc_juggle'));
  const landmarks = pose({ left_ankle: { x: 0.50, y: 0.88 } });
  let y = 0.3, vy = 0.9, t = 0;
  for (let f = 0; f < 20; f += 1) {
    vy += 2.4 * DT; y += vy * DT;
    counter.push({ x: 0.5, y, r: 0.03, score: 0.9 }, landmarks, t);
    t += DT * 1000;
  }
  assert.equal(counter.count, 0);
});

test('no detections means no reps, however long the recording', () => {
  const counter = new BallRepCounter(spec('soc_juggle'));
  const landmarks = pose({ left_ankle: { x: 0.50, y: 0.88 } });
  for (let f = 0; f < 600; f += 1) counter.push(null, landmarks, f * DT * 1000);
  assert.equal(counter.count, 0);
  assert.equal(counter.trusted, false);
});

test('a sparse, flickering track is reported as untrustworthy', () => {
  // The honest failure mode. Half a dozen glimpses of a ball is not a session,
  // and the drill has to say so rather than counting what it happened to see.
  const path = bounce({ every: 25 });
  const counter = new BallRepCounter(spec('soc_juggle'));
  run(counter, path, pose({ left_ankle: { x: 0.50, y: 0.88 } }));
  assert.ok(counter.trackQuality < 0.35);
  assert.equal(counter.trusted, false);
});

test('a clean track is trusted', () => {
  const counter = new BallRepCounter(spec('soc_juggle'));
  run(counter, bounce({ every: 2 }), pose({ left_ankle: { x: 0.50, y: 0.88 } }));
  assert.ok(counter.trusted, `quality ${counter.trackQuality}`);
});

test('the same bounce is a juggle or a dribble depending on what is next to it', () => {
  // The whole difference between the two drills, and the reason the classifier
  // checks landmarks before it checks the floor.
  const path = bounce({ floor: 0.95, apex: 1.2 });

  const dribble = new BallRepCounter(spec('bkb_dribble'));
  run(dribble, path, pose({ left_wrist: { x: 0.52, y: 0.55 },
                            right_wrist: { x: 0.62, y: 0.55 } }));
  assert.ok(dribble.count > 0, 'floor bounce with hands up is a dribble');

  const juggle = new BallRepCounter(spec('soc_juggle'));
  run(juggle, path, pose({ left_ankle: { x: 0.52, y: 0.95 } }));
  assert.ok(juggle.count > 0, 'the same bounce with a foot there is a juggle');

  const noFoot = new BallRepCounter(spec('soc_juggle'));
  run(noFoot, path, pose({ left_ankle: { x: 0.10, y: 0.95 } }));
  assert.equal(noFoot.count, 0, 'and nothing at all with the foot elsewhere');
});

test('juggling attributes the foot that took it', () => {
  const counter = new BallRepCounter(spec('soc_juggle'));
  run(counter, bounce({ x: 0.40 }),
      pose({ left_ankle: { x: 0.40, y: 0.88 }, right_ankle: { x: 0.70, y: 0.88 } }));
  const hands = counter.handCounts();
  assert.ok(hands.left > 0 && hands.right === 0, JSON.stringify(hands));
});

test('a side too close to call is recorded as neither', () => {
  // A fabricated left/right split feeds straight into the off-hand balance
  // score, so a coin flip here would show up as a real finding about a child.
  const counter = new BallRepCounter(spec('bkb_dribble'));
  run(counter, bounce({ floor: 0.95, x: 0.5 }),
      pose({ left_wrist: { x: 0.49, y: 0.6 }, right_wrist: { x: 0.51, y: 0.6 } }));
  assert.ok(counter.count > 0);
  assert.ok(counter.reps.every((r) => r.hand === 'none'));
});

test('the tracker ignores a second ball on the far side of the frame', () => {
  const tracker = new BallTracker();
  let t = 0, y = 0.5;
  for (let f = 0; f < 40; f += 1) {
    // The real ball, plus an occasional decoy well outside the gate. Starts on
    // the real ball, because a first frame that catches the decoy is the
    // re-acquisition case and is tested separately below.
    const decoy = f > 0 && f % 5 === 0;
    tracker.push(decoy ? { x: 0.05, y: 0.05, r: 0.03 } : { x: 0.5, y, r: 0.03 }, t);
    y += 0.004; t += DT * 1000;
  }
  assert.ok(Math.abs(tracker.x - 0.5) < 0.1, `track wandered to ${tracker.x}`);
});

test('a track that vanishes is dropped rather than extrapolated', () => {
  const tracker = new BallTracker();
  let t = 0;
  for (let f = 0; f < 10; f += 1) { tracker.push({ x: 0.5, y: 0.5, r: 0.03 }, t); t += DT * 1000; }
  assert.ok(tracker.visible);
  for (let f = 0; f < 30; f += 1) { tracker.push(null, t); t += DT * 1000; }
  assert.equal(tracker.visible, false, 'a ball is not invented through a gap');
});

test('every ball drill declares parts and a quality floor', () => {
  const ballDrills = SPECS.filter((d) => d.ball);
  assert.ok(ballDrills.length >= 6);
  for (const drill of ballDrills) {
    assert.ok(drill.ball.min_track_quality > 0, drill.key);
    assert.ok(drill.ball.parts.length > 0, drill.key);
    // Count mode cannot work without the ball; confirm mode must never
    // require it, because not seeing one proves nothing.
    assert.equal(drill.ball.required, drill.ball.mode === 'count', drill.key);
  }
});


test('a track that locked onto the wrong thing re-acquires', () => {
  // The first frame catches a ball lying on the grass behind the athlete. If
  // the tracker could not let go, every real detection afterwards would be
  // rejected as a decoy and the session would count nothing.
  const tracker = new BallTracker();
  let t = 0;
  tracker.push({ x: 0.05, y: 0.05, r: 0.03 }, t);
  t += DT * 1000;
  for (let f = 0; f < 30; f += 1) {
    tracker.push({ x: 0.6, y: 0.4, r: 0.03 }, t);
    t += DT * 1000;
  }
  assert.ok(Math.abs(tracker.x - 0.6) < 0.1,
    `never found the real ball, stuck at ${tracker.x}`);
});


test('every ball drill is exercised by this file', () => {
  // The mirror of the calibration harness rule: a ball drill added without a
  // test here would be unguarded in both files and look green in both.
  const covered = new Set(['soc_juggle', 'bkb_dribble', 'vb_set',
                           'bb_wall_throw', 'ten_wall_rally', 'lax_wall_ball']);
  const missing = SPECS.filter((d) => d.ball && !covered.has(d.key)).map((d) => d.key);
  assert.deepEqual(missing, [], `untested ball drills: ${missing.join(', ')}`);
});

test('every count-mode drill can actually count through its own spec', () => {
  for (const drill of SPECS.filter((d) => d.ball && d.ball.mode === 'count')) {
    const counter = new BallRepCounter(drill);
    const ground = drill.ball.contact === 'ground';
    // A dribble bounces off the actual floor with the hands up above it; a
    // juggle or a set bounces off the body part itself. Staging them the same
    // way would make a dribble read as a body contact and count nothing --
    // which is the drills behaving correctly, not a bug.
    const floor = ground ? 0.96 : 0.88;
    const parts = {};
    for (const name of drill.ball.parts) {
      parts[name] = ground ? { x: 0.52, y: 0.55 } : { x: 0.52, y: floor };
    }
    const path = bounce({ floor, apex: 1.4, every: 2, frames: 360 });
    run(counter, path, pose(parts));
    assert.ok(counter.count > 0, `${drill.key} counted nothing from a real bounce`);
  }
});


test('wall ball corroborates rather than counting', () => {
  // Its reps come from the pose counter, so the ball counter's job is to
  // report how much it saw -- not to produce a number of its own.
  const drill = spec('lax_wall_ball');
  assert.equal(drill.ball.mode, 'confirm');

  const counter = new BallRepCounter(drill);
  run(counter, bounce({ floor: 0.45, apex: 1.5, every: 2, frames: 300 }),
      pose({ left_wrist: { x: 0.52, y: 0.45 }, right_wrist: { x: 0.60, y: 0.45 } }));

  const confirmation = counter.confirmation();
  assert.ok(confirmation.ball_contacts > 0, 'saw the ball being thrown');
  assert.ok(confirmation.track_quality > 0);
  assert.deepEqual(Object.keys(confirmation).sort(),
    ['ball_contacts', 'ball_travel', 'track_quality']);
});

test('a wall ball session with no ball reports zero contacts, not zero reps', () => {
  // The whole point of confirm mode. The pose counter is untouched by any of
  // this; the ball counter simply reports that it saw nothing.
  const counter = new BallRepCounter(spec('lax_wall_ball'));
  const landmarks = pose({ left_wrist: { x: 0.52, y: 0.45 } });
  for (let f = 0; f < 600; f += 1) counter.push(null, landmarks, f * DT * 1000);
  assert.equal(counter.confirmation().ball_contacts, 0);
  assert.equal(counter.confirmation().track_quality, 0);
});


test('travel separates a throw from a wave, where contacts cannot', () => {
  // Both produce contacts. Only one sends the ball anywhere.
  const drill = spec('lax_wall_ball');
  const shoulder = { x: 0.35, y: 0.30 }, hip = { x: 0.36, y: 0.60 };

  function session(thrown) {
    const counter = new BallRepCounter(drill);
    let t = 0;
    for (let rep = 0; rep < 12; rep += 1) {
      for (let f = 0; f < 30; f += 1) {
        const phase = f / 30;
        const hand = { x: 0.36, y: 0.34 - Math.sin(phase * Math.PI * 2) * 0.09 };
        const landmarks = pose({
          left_shoulder: shoulder, left_hip: hip,
          left_wrist: hand, right_wrist: { x: hand.x + 0.02, y: hand.y },
        });
        // Thrown: the ball crosses the frame to the wall and back. Waved: it
        // stays exactly where the hand is.
        const ball = thrown
          ? { x: 0.36 + Math.sin(phase * Math.PI) * 0.58, y: hand.y, r: 0.02, score: 0.8 }
          : { x: hand.x, y: hand.y, r: 0.02, score: 0.8 };
        counter.push(ball, landmarks, t);
        t += 1000 / 30;
      }
    }
    return counter.confirmation();
  }

  const real = session(true);
  const fake = session(false);
  assert.ok(real.ball_travel > 0.15, `real travelled ${real.ball_travel}`);
  assert.equal(fake.ball_travel, 0, `fake travelled ${fake.ball_travel}`);
});

test('travel is zero rather than undefined when there is no pose', () => {
  const counter = new BallRepCounter(spec('lax_wall_ball'));
  for (let f = 0; f < 60; f += 1) {
    counter.push({ x: 0.5, y: 0.5, r: 0.02, score: 0.8 }, null, f * DT * 1000);
  }
  assert.equal(counter.confirmation().ball_travel, 0);
});
