/**
 * Cue sequence tests.
 *
 * The important ones are the golden vectors. `offdays/cues.py` contains the
 * same list, and if these two files ever disagree the browser shows an athlete
 * one spot while the server marks them against another -- silently, on every
 * rep, with no error anywhere. Nothing else in the system catches that, so
 * these vectors are load-bearing rather than decorative.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import { Random, cueAt, cueCount, label, seedOf, sequence } from '../../offdays/web/static/cues.js';

const ZONES = [
  'high_left', 'high_right',
  'mid_left', 'mid_right',
  'low_left', 'low_right', 'low_centre',
];

// Generated once and pasted into both suites by hand. Do not regenerate them
// from either implementation -- that would make the test agree with whatever
// the code currently does, which is the one thing it must not do.
const GOLDEN = {
  a: {
    seed: 3826002220,
    seq: ['high_left', 'low_centre', 'mid_right', 'mid_left', 'low_right', 'high_right',
      'low_left', 'high_right', 'low_centre', 'high_left', 'mid_left', 'low_right'],
  },
  'session-nonce-1': {
    seed: 2073095791,
    seq: ['low_left', 'mid_left', 'low_centre', 'low_right', 'mid_right', 'high_right',
      'high_left', 'high_right', 'mid_right', 'low_right', 'mid_left', 'low_left'],
  },
  ZZZ99: {
    seed: 2661185967,
    seq: ['high_left', 'mid_left', 'low_left', 'mid_right', 'low_centre', 'high_right',
      'low_right', 'low_centre', 'low_right', 'low_left', 'high_left', 'mid_left'],
  },
  '': {
    seed: 2166136261,
    seq: ['low_centre', 'high_left', 'low_right', 'high_right', 'mid_right', 'mid_left',
      'low_left', 'mid_right', 'high_left', 'low_right', 'mid_left', 'low_left'],
  },
};

const GOLDEN_DRAWS = [
  0.594323272817, 0.943420797819, 0.303835050669,
  0.767653154675, 0.472406724002, 0.185853380011,
];

test('the seed matches the Python implementation', () => {
  for (const [nonce, want] of Object.entries(GOLDEN)) {
    assert.equal(seedOf(nonce), want.seed, nonce);
  }
});

test('the random stream matches the Python implementation', () => {
  const rng = new Random(seedOf('golden'));
  for (const want of GOLDEN_DRAWS) {
    assert.equal(Math.round(rng.next() * 1e12) / 1e12, want);
  }
});

test('sequences match the Python implementation', () => {
  for (const [nonce, want] of Object.entries(GOLDEN)) {
    assert.deepEqual(sequence(nonce, 12, ZONES), want.seq, nonce);
  }
});

test('the same nonce always gives the same sequence', () => {
  assert.deepEqual(sequence('abc', 40, ZONES), sequence('abc', 40, ZONES));
});

test('different nonces give different sequences', () => {
  assert.notDeepEqual(sequence('abc', 20, ZONES), sequence('abd', 20, ZONES));
});

test('a longer sequence extends a shorter one rather than replacing it', () => {
  // The browser generates far more cues than a session will use and the server
  // generates exactly as many as the session ran for. They only line up if the
  // short list is a prefix of the long one.
  const long = sequence('abc', 200, ZONES);
  assert.deepEqual(sequence('abc', 31, ZONES), long.slice(0, 31));
});

test('every zone comes up once per bag', () => {
  const seq = sequence('balance', 70, ZONES);
  for (let i = 0; i < 70; i += ZONES.length) {
    assert.deepEqual(seq.slice(i, i + ZONES.length).slice().sort(), ZONES.slice().sort());
  }
});

test('the same spot is never called twice running', () => {
  for (const nonce of ['a', 'b', 'c', 'seam', 'x'.repeat(40)]) {
    const seq = sequence(nonce, 400, ZONES);
    for (let i = 1; i < seq.length; i += 1) {
      assert.notEqual(seq[i], seq[i - 1], `${nonce} at ${i}`);
    }
  }
});

test('a zero or negative count gives nothing', () => {
  assert.deepEqual(sequence('a', 0, ZONES), []);
  assert.deepEqual(sequence('a', -5, ZONES), []);
});

test('an absurd count is refused rather than hanging', () => {
  assert.throws(() => sequence('a', 10001, ZONES));
});

test('cue timing is fixed cadence after the lead-in', () => {
  assert.equal(cueAt(0, 4000, 2400), 4000);
  assert.equal(cueAt(3, 4000, 2400), 11200);
});

test('a session ending mid-cue does not count that cue', () => {
  // Four whole periods fit after the lead-in; the fifth is cut off.
  assert.equal(cueCount(4000 + 2400 * 4 + 900, 4000, 2400), 4);
  assert.equal(cueCount(4000 + 2400 * 5, 4000, 2400), 5);
  assert.equal(cueCount(3000, 4000, 2400), 0);
});

test('labels use the goalie vocabulary', () => {
  assert.equal(label('low_centre', 'right'), 'five hole');
  assert.equal(label('high_right', 'right'), 'stick-side high');
  assert.equal(label('high_left', 'right'), 'off-stick high');
  assert.equal(label('mid_left', 'left'), 'stick-side hip');
});

test('an unknown top hand falls back to plain sides rather than guessing', () => {
  assert.equal(label('high_right', null), 'right high');
  assert.equal(label('mid_left', undefined), 'left hip');
  // Still correct for the one spot that has no side.
  assert.equal(label('low_centre', null), 'five hole');
});
