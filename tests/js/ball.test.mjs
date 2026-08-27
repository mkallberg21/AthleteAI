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
  BallTracker, ContactDetector, BallRepCounter, LANDMARK_INDEX, metricDistance,
} from '../../offdays/web/static/ball.js';
import { LANDMARKS } from '../../offdays/web/static/counter.js';
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
  // The lacrosse family is covered as a family below rather than one name at
  // a time: they all share LACROSSE_BALL, so listing each key here would grow
  // a rubber-stamp list while the loop is what actually exercises them.
  //
  // Basketball is covered the same way for the same reason: every one of its
  // ball drills shares BASKETBALL, and the loop below drives all of them.
  //
  // Volleyball is covered as a family too, for the same reason: every one of
  // its ball drills shares VOLLEYBALL, and the loop below drives all of them.
  const covered = new Set(['soc_juggle', 'bkb_dribble', 'vb_set',
                           'bb_wall_throw', 'ten_wall_rally']);
  const missing = SPECS
    .filter((d) => d.ball && !covered.has(d.key)
                && !['lacrosse', 'basketball', 'volleyball', 'soccer',
                     'tennis', 'baseball'].includes(d.sport))
    .map((d) => d.key);
  assert.deepEqual(missing, [], `untested ball drills: ${missing.join(', ')}`);
});

// Lacrosse drills that legitimately have no ball, listed rather than inferred:
// a drill quietly losing its ball must still fail the guard below. Goalie save
// positions has no shooter and no ball by design -- the app calls a spot and
// the athlete reacts to it.
const BALLLESS_LAX = new Set(['lax_goalie_saves']);

test('only the deliberately ball-free lacrosse drills lack a ball', () => {
  const found = SPECS
    .filter((d) => d.sport === 'lacrosse' && !d.ball)
    .map((d) => d.key)
    .sort();
  assert.deepEqual(found, [...BALLLESS_LAX].sort());
});

test('every lacrosse drill shares one ball', () => {
  // A lacrosse ball is a lacrosse ball. If a pattern ever drifts to its own
  // size or colour the detector's size prior silently stops matching it.
  const lax = SPECS.filter((d) => d.sport === 'lacrosse' && !BALLLESS_LAX.has(d.key));
  assert.ok(lax.length >= 9, 'expected the full wall ball routine');
  for (const drill of lax) {
    assert.ok(drill.ball, `${drill.key} has no ball`);
    assert.equal(drill.ball.diameter_cm, 6.35, `${drill.key} ball size drifted`);
    assert.equal(drill.ball.colour, 'white', `${drill.key} ball colour drifted`);
    assert.equal(drill.ball.detector, 'vision', `${drill.key} uses the general model`);
  }
});

test('no lacrosse drill can be blocked by an unseen ball', () => {
  // The ball is the detector's weakest subject -- smallest and fastest in the
  // catalogue. Requiring it anywhere would punish a child for our blind spot.
  for (const drill of SPECS.filter(
    (d) => d.sport === 'lacrosse' && !BALLLESS_LAX.has(d.key))) {
    assert.equal(drill.ball.mode, 'confirm', `${drill.key} counts on the ball`);
    assert.equal(drill.ball.required, false, `${drill.key} requires the ball`);
  }
});

test('every lacrosse drill corroborates from a real throw', () => {
  // The loop that makes the coverage exemption above honest.
  for (const drill of SPECS.filter(
    (d) => d.sport === 'lacrosse' && !BALLLESS_LAX.has(d.key))) {
    const counter = new BallRepCounter(drill);
    run(counter, bounce({ floor: 0.45, apex: 1.5, every: 2, frames: 300 }),
        pose({ left_wrist: { x: 0.52, y: 0.45 },
               right_wrist: { x: 0.60, y: 0.45 } }));
    const confirmation = counter.confirmation();
    assert.ok(confirmation.ball_contacts > 0,
      `${drill.key} saw no contacts in a clean throw sequence`);
    assert.ok(confirmation.track_quality > 0, `${drill.key} tracked nothing`);
  }
});

test('the fast patterns gate contacts tighter than the slow ones', () => {
  // Quick stick and one-handed reps arrive faster than the standard 400ms
  // window assumes; a gate longer than the rep it polices would throw away
  // every second contact.
  const gap = (key) => spec(key).ball.min_gap_ms;
  assert.ok(gap('lax_quick_stick') < gap('lax_wall_ball'));
  assert.ok(gap('lax_wall_ball_one_hand') < gap('lax_wall_ball'));
  for (const key of ['lax_quick_stick', 'lax_wall_ball_one_hand']) {
    assert.ok(gap(key) < spec(key).counter.min_rep_ms,
      `${key} gates contacts slower than its own fastest legal rep`);
  }
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
    // Some drills also gate on where the hands are -- a volleyball set only
    // counts above the shoulders, a forearm pass only below. The shoulders are
    // staged to satisfy whichever gate this drill declares, because the
    // question here is whether a drill can count through its OWN spec.
    const gate = drill.ball.hands ?? 'any';
    if (gate !== 'any') {
      const wristY = parts.left_wrist ? parts.left_wrist.y : floor;
      const shoulderY = gate === 'above_shoulders' ? wristY + 0.2 : wristY - 0.2;
      parts.left_wrist = parts.left_wrist ?? { x: 0.50, y: wristY };
      parts.right_wrist = parts.right_wrist ?? { x: 0.54, y: wristY };
      parts.left_shoulder = { x: 0.46, y: shoulderY };
      parts.right_shoulder = { x: 0.54, y: shoulderY };
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


test('a distance means the same thing whichever way up the phone is', () => {
  // Normalised coordinates are anisotropic: in 16:9 one x-unit is 1.78 times
  // wider on the ground than one y-unit, and in portrait it is the reverse.
  // Every radius in this module is a real distance, so measuring in raw
  // normalised units meant turning the phone changed what "next to the ball"
  // meant.
  const acrossLandscape = metricDistance(0.5, 0.5, 0.6, 0.5, 16 / 9);
  const down = metricDistance(0.5, 0.5, 0.5, 0.6, 16 / 9);
  assert.ok(acrossLandscape > down, 'x must be scaled by the aspect ratio');
  assert.ok(Math.abs(acrossLandscape - 0.1 * (16 / 9)) < 1e-9);
  assert.ok(Math.abs(down - 0.1) < 1e-9);
});

test('the same physical contact is classified the same in both orientations', () => {
  // The bug this guards: a foot 0.1 across from the ball counted as a touch in
  // portrait and not in landscape, purely from frame shape.
  function ran(aspect, dx) {
    const counter = new BallRepCounter(spec('soc_juggle'));
    counter.setAspect(aspect);
    // A foot offset sideways from where the ball bounces.
    const landmarks = pose({ left_ankle: { x: 0.52 + dx, y: 0.88 } });
    run(counter, bounce({ every: 2, x: 0.52 }), landmarks);
    return counter.count;
  }
  // Well inside the part radius in real terms: counted either way up.
  assert.ok(ran(16 / 9, 0.02) > 0);
  assert.ok(ran(9 / 16, 0.02) > 0);
  // Far away in real terms: counted in neither.
  assert.equal(ran(16 / 9, 0.45), 0);
  assert.equal(ran(9 / 16, 0.45), 0);
});

test('setting the aspect reaches the tracker and the contact detector', () => {
  const counter = new BallRepCounter(spec('soc_juggle'));
  counter.setAspect(16 / 9);
  assert.equal(counter.tracker.aspect, 16 / 9);
  assert.equal(counter.detector.aspect, 16 / 9);
  // Junk from a camera that has not reported dimensions yet is ignored.
  counter.setAspect(0);
  counter.setAspect(NaN);
  assert.equal(counter.tracker.aspect, 16 / 9);
});


/* -------------------------------------------------------------------------
 * Basketball
 *
 * Every ball drill in the sport shares one BASKETBALL spec, so these are
 * driven as a family -- the honest version of the coverage exemption above.
 * ---------------------------------------------------------------------- */

const BKB = () => SPECS.filter((d) => d.sport === 'basketball' && d.ball);

test('every basketball drill counts a real bounce sequence', () => {
  for (const drill of BKB()) {
    const counter = new BallRepCounter(drill);
    // Same geometry the single-drill dribble test above uses: a floor bounce
    // with the hands above it, which is what separates a dribble from a juggle.
    run(counter, bounce({ floor: 0.95, apex: 1.2, frames: 400 }),
        pose({ left_wrist: { x: 0.48, y: 0.55 },
               right_wrist: { x: 0.56, y: 0.55 } }));
    const seen = counter.count || counter.confirmation().ball_contacts;
    assert.ok(seen > 0, `${drill.key} saw nothing in a clean dribble sequence`);
  }
});

test('every basketball drill uses the same ball', () => {
  // A drifted size silently stops the detector's strongest filter matching,
  // and nothing else in either suite would notice.
  for (const drill of BKB()) {
    assert.equal(drill.ball.diameter_cm, 23, `${drill.key} ball size drifted`);
    assert.equal(drill.ball.colour, 'basketball', `${drill.key} colour drifted`);
    assert.equal(drill.ball.detector, 'vision', `${drill.key} uses the general model`);
  }
});

test('the ball spec carries its alternation rule to the browser', () => {
  // The client needs it to tell an athlete what the drill is asking of their
  // hands; the server enforces it. Both read the same field.
  const rules = new Map(BKB().map((d) => [d.key, d.ball.alternation]));
  assert.equal(rules.get('bkb_crossover'), 'alternating');
  assert.equal(rules.get('bkb_pound_weak'), 'same_hand');
  assert.equal(rules.get('bkb_dribble'), 'any');
});

test('a drill asking something of the hands also attributes them', () => {
  for (const drill of BKB()) {
    if (drill.ball.alternation !== 'any') {
      assert.ok(drill.ball.attribute_side,
        `${drill.key} has an alternation rule and no hands to check it against`);
    }
  }
});

test('the fast basketball patterns gate contacts tighter than the slow ones', () => {
  // A pound arrives faster than a standing dribble; a gate longer than the rep
  // it polices throws away every second bounce.
  const gap = (key) => spec(key).ball.min_gap_ms;
  assert.ok(gap('bkb_pound_low') < gap('bkb_dribble'));
  assert.ok(gap('bkb_wall_pass') > gap('bkb_dribble'));
});


/* -------------------------------------------------------------------------
 * Volleyball
 *
 * The sport where contact location does the most work: a set above the head,
 * a forearm pass below the shoulders, a hit off one hand. The hands gate is
 * what turns the first two from one event into two.
 * ---------------------------------------------------------------------- */

const VB = () => SPECS.filter((d) => d.sport === 'volleyball' && d.ball);

/** A bounce off the hands, with the shoulders staged above or below them. */
function volley({ handsAbove }) {
  const wristY = 0.55;
  const shoulderY = handsAbove ? wristY + 0.18 : wristY - 0.18;
  return pose({
    left_wrist: { x: 0.50, y: wristY },
    right_wrist: { x: 0.54, y: wristY },
    nose: { x: 0.52, y: wristY - 0.02 },
    left_elbow: { x: 0.48, y: wristY + 0.02 },
    right_elbow: { x: 0.56, y: wristY + 0.02 },
    left_shoulder: { x: 0.46, y: shoulderY },
    right_shoulder: { x: 0.58, y: shoulderY },
  });
}

test('every volleyball drill uses the same ball', () => {
  for (const drill of VB()) {
    assert.equal(drill.ball.diameter_cm, 21, `${drill.key} ball size drifted`);
    assert.equal(drill.ball.detector, 'vision', `${drill.key} uses the general model`);
  }
});

test('a set counts with the hands up and nothing with them down', () => {
  const up = new BallRepCounter(spec('vb_set'));
  run(up, bounce({ floor: 0.55, apex: 1.4, every: 2, frames: 360 }),
      volley({ handsAbove: true }));
  assert.ok(up.count > 0, 'a set above the shoulders should count');

  const down = new BallRepCounter(spec('vb_set'));
  run(down, bounce({ floor: 0.55, apex: 1.4, every: 2, frames: 360 }),
      volley({ handsAbove: false }));
  assert.equal(down.count, 0, 'hands below the shoulders is a pass, not a set');
});

test('a forearm pass counts with the hands down and nothing with them up', () => {
  const down = new BallRepCounter(spec('vb_pass'));
  run(down, bounce({ floor: 0.55, apex: 1.4, every: 2, frames: 360 }),
      volley({ handsAbove: false }));
  assert.ok(down.count > 0, 'a pass below the shoulders should count');

  const up = new BallRepCounter(spec('vb_pass'));
  run(up, bounce({ floor: 0.55, apex: 1.4, every: 2, frames: 360 }),
      volley({ handsAbove: true }));
  assert.equal(up.count, 0, 'hands above the shoulders is a set, not a pass');
});

test('the gate is permissive when it cannot see the shoulders', () => {
  // Tested with the wrists present and the shoulders missing, because that is
  // the only place the permissiveness is observable: a body-contact drill needs
  // pose to find a contact at all, so with no skeleton there is nothing for the
  // gate to allow or refuse either way.
  //
  // A half-resolved skeleton should cost a contact its attribution, not its
  // existence -- otherwise the drill silently counts nothing and the athlete
  // is told they did no work.
  const counter = new BallRepCounter(spec('vb_set'));
  const half = pose({ left_wrist: { x: 0.50, y: 0.55 },
                      right_wrist: { x: 0.54, y: 0.55 },
                      nose: { x: 0.52, y: 0.53 } });
  // `pose` fills every landmark, so the shoulders have to be knocked out
  // explicitly to model a skeleton that has only half resolved.
  for (const name of ['left_shoulder', 'right_shoulder']) {
    half[LANDMARK_INDEX[name]] = { x: 0.5, y: 0.5, z: 0, visibility: 0.1 };
  }
  run(counter, bounce({ floor: 0.55, apex: 1.4, every: 2, frames: 360 }), half);
  assert.ok(counter.count > 0);
});

test('the hands gate reaches the browser on every volleyball drill', () => {
  const gates = new Map(VB().map((d) => [d.key, d.ball.hands]));
  assert.equal(gates.get('vb_set'), 'above_shoulders');
  assert.equal(gates.get('vb_pass'), 'below_shoulders');
  assert.equal(gates.get('vb_serve'), 'above_shoulders');
});


/* -------------------------------------------------------------------------
 * Soccer
 *
 * The first sport here played with the feet. `attribute_side` reads a foot the
 * same way it reads a hand, so the alternation rules written for basketball
 * carry over unchanged -- and contact location does the rest.
 * ---------------------------------------------------------------------- */

const SOC = () => SPECS.filter((d) => d.sport === 'soccer' && d.ball);

test('every soccer drill counts a real touch', () => {
  for (const drill of SOC()) {
    const counter = new BallRepCounter(drill);
    // Off the foot rather than the floor, which is what a juggle is.
    const parts = {};
    for (const name of drill.ball.parts) parts[name] = { x: 0.52, y: 0.88 };
    run(counter, bounce({ floor: 0.88, apex: 1.5, every: 2, frames: 360 }),
        pose(parts));
    assert.ok(counter.count > 0, `${drill.key} saw nothing off a clean touch`);
  }
});

test('every soccer drill uses the same ball', () => {
  for (const drill of SOC()) {
    assert.equal(drill.ball.diameter_cm, 20.5, `${drill.key} ball size drifted`);
    assert.equal(drill.ball.detector, 'vision', `${drill.key} uses the general model`);
  }
});

test('no soccer drill counts a touch off the head', () => {
  // The head was in the juggling parts list, so a child heading a ball in a
  // garden was counted and paid for it, with no age floor anywhere. A header
  // now simply does not register.
  for (const drill of SOC()) {
    assert.ok(!drill.ball.parts.includes('nose'),
      `${drill.key} still counts head contacts`);
  }
});

test('thigh juggling ignores a touch off the foot', () => {
  // Contact location is the whole discrimination: an ankle is nowhere near a
  // knee, so a ball off the laces is not a contact for this drill at all.
  const counter = new BallRepCounter(spec('soc_thigh'));
  run(counter, bounce({ floor: 0.88, apex: 1.5, every: 2, frames: 360 }),
      pose({ left_ankle: { x: 0.52, y: 0.88 },
             right_ankle: { x: 0.56, y: 0.88 },
             left_knee: { x: 0.52, y: 0.55 },
             right_knee: { x: 0.56, y: 0.55 } }));
  assert.equal(counter.count, 0);
});

test('the alternation rules read a foot the same way they read a hand', () => {
  const rules = new Map(SOC().map((d) => [d.key, d.ball.alternation]));
  assert.equal(rules.get('soc_juggle_weak'), 'same_hand');
  assert.equal(rules.get('soc_juggle_alt'), 'alternating');
  assert.equal(rules.get('soc_juggle'), 'any');
});

test('wall passing gates on strike speed, not on the foot', () => {
  const pass = spec('soc_wall_pass');
  assert.ok(pass.ball.min_speed > spec('soc_juggle').ball.min_speed * 2);
});


/* -------------------------------------------------------------------------
 * Tennis
 *
 * The one sport here where the ball never touches the athlete -- it comes off
 * a racket head well beyond the hand, and the detector attributes the contact
 * to the nearest wrist. Enough to tell one wing from the other, not enough to
 * tell which is which.
 * ---------------------------------------------------------------------- */

const TEN = () => SPECS.filter((d) => d.sport === 'tennis' && d.ball);

test('every tennis drill uses the same ball', () => {
  for (const drill of TEN()) {
    assert.equal(drill.ball.diameter_cm, 6.7, `${drill.key} ball size drifted`);
    assert.equal(drill.ball.colour, 'optic', `${drill.key} colour drifted`);
  }
});

test('every count-mode tennis drill counts a struck ball', () => {
  for (const drill of TEN()) {
    if (drill.ball.mode !== 'count') continue;
    const counter = new BallRepCounter(drill);
    run(counter, bounce({ floor: 0.70, apex: 1.6, every: 2, frames: 400 }),
        pose({ left_wrist: { x: 0.44, y: 0.70 },
               right_wrist: { x: 0.60, y: 0.70 } }));
    assert.ok(counter.count > 0, `${drill.key} saw nothing off a struck ball`);
  }
});

test('the wing rules read a racket hand the same way they read any hand', () => {
  const rules = new Map(TEN().map((d) => [d.key, d.ball.alternation]));
  assert.equal(rules.get('ten_alternate'), 'alternating');
  assert.equal(rules.get('ten_one_wing'), 'same_hand');
  assert.equal(rules.get('ten_wall_rally'), 'any');
});

test('volleys gate contacts tighter than a groundstroke rally', () => {
  assert.ok(spec('ten_volley').ball.min_gap_ms
            < spec('ten_wall_rally').ball.min_gap_ms);
});

test('the serve confirms rather than counting', () => {
  // Its reps come from the arm, so the ball's only job is to establish there
  // was one -- the same rule every lacrosse drill follows.
  assert.equal(spec('ten_serve').ball.mode, 'confirm');
  assert.equal(spec('ten_serve').ball.required, false);
});


/* -------------------------------------------------------------------------
 * Baseball and softball
 *
 * Every ball drill shares BASEBALL_BALL, so they are driven as a family. The
 * windmill is not here because it needs no ball at all -- it is counted from
 * the pitching arm, which is what makes it work with or without one.
 * ---------------------------------------------------------------------- */

const DIAMOND = () => SPECS.filter((d) => d.sport === 'baseball' && d.ball);

test('every baseball ball drill counts a thrown ball', () => {
  for (const drill of DIAMOND()) {
    const counter = new BallRepCounter(drill);
    run(counter, bounce({ floor: 0.62, apex: 1.8, every: 2, frames: 500 }),
        pose({ left_wrist: { x: 0.46, y: 0.62 },
               right_wrist: { x: 0.58, y: 0.62 } }));
    assert.ok(counter.count > 0, `${drill.key} saw nothing off a thrown ball`);
  }
});

test('every baseball drill uses the same ball', () => {
  for (const drill of DIAMOND()) {
    assert.equal(drill.ball.diameter_cm, 7.4, `${drill.key} ball size drifted`);
    assert.equal(drill.ball.detector, 'vision', `${drill.key} uses the general model`);
  }
});

test('a long toss gates far wider than a quick transfer', () => {
  // The two are separated by nothing else, so the gap between them has to be
  // large enough that neither can be mistaken for the other.
  assert.ok(spec('bb_long_toss').ball.min_gap_ms
            > spec('bb_quick_hands').ball.min_gap_ms * 3);
  assert.ok(spec('bb_long_toss').ball.min_speed
            > spec('bb_quick_hands').ball.min_speed);
});

test('the windmill needs no ball, which is why it works without one', () => {
  assert.equal(spec('sb_windmill').ball, null);
});
