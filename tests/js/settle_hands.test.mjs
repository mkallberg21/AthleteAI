/**
 * A strong-hand set is one hand. A rep the camera read as the other hand is a misread, and must not show up as
 * left-handed work (or be paid the off-hand premium).
 */
import assert from 'node:assert';
import { test } from 'node:test';
import { RepCounter, settleHands } from '../../offdays/web/static/counter.js';
import { SPECS } from './specs.mjs';

const spec = (key) => SPECS.find((d) => d.key === key);
const reps = (hands) => hands.map((hand, i) => ({ t_ms: i * 1500, hand, confidence: 0.9 }));
const hands = (rs) => rs.map((r) => r.hand);
const R = 'right', L = 'left', N = 'none';

test('a strong-hand set read mostly right and partly left is all right', () => {
  const out = settleHands(reps([R, R, L, R, R, R, L, R]), spec('lax_wall_ball_strong'));
  assert.deepStrictEqual(hands(out), Array(8).fill(R));
});

test('the same for a left-hander', () => {
  const out = settleHands(reps([L, L, R, L, L]), spec('lax_wall_ball_strong'));
  assert.deepStrictEqual(hands(out), Array(5).fill(L));
});

test('the off-hand drill and the one-hand drill are settled too', () => {
  for (const key of ['lax_wall_ball_offhand', 'lax_wall_ball_one_hand']) {
    assert.deepStrictEqual(hands(settleHands(reps([L, R, L, L]), spec(key))), Array(4).fill(L), key);
  }
});

test('a rep that named no hand is not given one', () => {
  const out = settleHands(reps([R, N, R, L, N]), spec('lax_wall_ball_strong'));
  assert.deepStrictEqual(hands(out), [R, N, R, R, N]);
});

test('an even split is left alone: the set is genuinely mixed', () => {
  const input = reps([R, L, R, L]);
  assert.deepStrictEqual(hands(settleHands(input, spec('lax_wall_ball_strong'))), hands(input));
});

test('drills that change hands on purpose are not touched', () => {
  for (const key of ['lax_wall_ball_cross', 'lax_wall_ball_btb', 'lax_wall_ball_split', 'lax_wall_ball']) {
    const s = spec(key);
    if (!s) continue;
    const input = reps([R, L, R, L, R]);
    assert.deepStrictEqual(hands(settleHands(input, s)), hands(input), key);
  }
});

test('the reps it is given are not changed, and nothing but the hand is', () => {
  const input = reps([R, R, L]);
  const out = settleHands(input, spec('lax_wall_ball_strong'));
  assert.deepStrictEqual(hands(input), [R, R, L]);
  assert.deepStrictEqual(out.map((r) => r.t_ms), input.map((r) => r.t_ms));
  assert.strictEqual(out[2].confidence, 0.9);
});

test('what the screen counts and what is submitted agree, and say right for every rep', () => {
  const c = new RepCounter(spec('lax_wall_ball_strong'));
  c.reps = reps([R, R, L, R, L, R, R, R]);
  assert.deepStrictEqual(c.handCounts(), { left: 0, right: 8 });
  const sent = c.toSubmission('s', 'n', 60000);
  assert.deepStrictEqual(hands(sent.reps), Array(8).fill(R));
});
