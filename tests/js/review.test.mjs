/**
 * Self-review buffering, markers, and the pose track.
 *
 * The recorder itself needs a browser, so these tests drive the parts that can
 * be reasoned about without one: the rolling buffer that stops a long session
 * exhausting memory, the marker selection that saves an athlete scrubbing a
 * ten-minute clip, and the pose lookup behind the overlay.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import {
  MAX_BUFFER_BYTES, POSE_SAMPLE_HZ, SessionRecorder, buildMarkers, formatBytes,
  poseAt,
} from '../../athleteiq/web/static/review.js';

/** A MediaRecorder stand-in that emits chunks on demand. */
class FakeRecorder {
  constructor() { this.state = 'inactive'; }
  start() { this.state = 'recording'; }
  stop() { this.state = 'inactive'; if (this.onstop) this.onstop(); }
}

function recorderWith(maxBytes) {
  const recorder = new SessionRecorder(null, { maxBytes, mimeType: 'video/webm' });
  const fake = new FakeRecorder();
  recorder.recorder = fake;
  fake.ondataavailable = null;
  // Wire the handler the real start() would have attached.
  recorder.recorder.ondataavailable = (event) => {
    if (!event.data || !event.data.size) return;
    recorder.chunks.push(event.data);
    recorder.bytes += event.data.size;
    recorder.trim();
  };
  return recorder;
}

function emit(recorder, size) {
  recorder.recorder.ondataavailable({ data: { size } });
}

test('the buffer drops the oldest footage rather than stopping', () => {
  // An athlete who trains twenty minutes should still be able to review the
  // last ten; the end of a set is the part worth watching.
  const recorder = recorderWith(1000);
  for (let i = 0; i < 5; i += 1) emit(recorder, 300);

  assert.ok(recorder.bytes <= 1000, `buffer grew to ${recorder.bytes}`);
  assert.ok(recorder.droppedBytes > 0, 'nothing was dropped');
  assert.strictEqual(recorder.truncated, true);
});

test('a short session is not truncated', () => {
  const recorder = recorderWith(1_000_000);
  for (let i = 0; i < 5; i += 1) emit(recorder, 1000);
  assert.strictEqual(recorder.truncated, false);
  assert.strictEqual(recorder.bytes, 5000);
});

test('the buffer never empties itself completely', () => {
  // Even a single chunk larger than the cap must leave something to watch.
  const recorder = recorderWith(100);
  emit(recorder, 5000);
  emit(recorder, 5000);
  assert.ok(recorder.chunks.length >= 1, 'buffer discarded everything');
});

test('release drops the recording and everything derived from it', () => {
  const recorder = recorderWith(1_000_000);
  emit(recorder, 5000);
  recorder.poses.push({ t: 0, p: [] });

  recorder.release();

  assert.strictEqual(recorder.chunks.length, 0);
  assert.strictEqual(recorder.bytes, 0);
  assert.strictEqual(recorder.poses.length, 0);
  assert.strictEqual(recorder.recorder, null);
});

test('the pose track is downsampled rather than kept per frame', () => {
  const recorder = recorderWith(1_000_000);
  const landmarks = Array.from({ length: 33 }, () => ({ x: 0.5, y: 0.5, visibility: 0.9 }));

  // 60fps of input over two seconds.
  for (let t = 0; t < 2000; t += 1000 / 60) recorder.samplePose(landmarks, t);

  const expected = (2000 / 1000) * POSE_SAMPLE_HZ;
  assert.ok(
    recorder.poses.length <= expected + 2,
    `kept ${recorder.poses.length} frames, expected about ${expected}`,
  );
  assert.ok(recorder.poses.length >= expected - 2, 'dropped too many frames');
});

test('the pose track stores only body landmarks, never the face', () => {
  const recorder = recorderWith(1_000_000);
  const landmarks = Array.from({ length: 33 }, (_, i) => ({
    x: i / 33, y: 0.5, visibility: 0.9,
  }));
  recorder.samplePose(landmarks, 0);

  // Twelve tracked points: shoulders, elbows, wrists, hips, knees, ankles.
  assert.strictEqual(recorder.poses[0].p.length, 12);
  // Landmark 0 is the nose; its x would be 0.
  assert.ok(!recorder.poses[0].p.some((point) => point && point[0] === 0));
});

test('a landmark that is not visible is stored as absent, not guessed', () => {
  const recorder = recorderWith(1_000_000);
  const landmarks = Array.from({ length: 33 }, () => ({ x: 0.5, y: 0.5, visibility: 0.9 }));
  landmarks[15] = { x: 0.5, y: 0.5, visibility: 0.1 };  // left wrist, out of frame
  recorder.samplePose(landmarks, 0);
  assert.ok(recorder.poses[0].p.includes(null), 'an invisible landmark was invented');
});

// ---------------------------------------------------------------- markers

function reps(spec) {
  return spec.map(([t_ms, rom, hand]) => ({ t_ms, rom, hand: hand || 'none' }));
}

test('markers point at the best and shortest reps', () => {
  const markers = buildMarkers(reps([
    [1000, 0.50], [2000, 0.52], [3000, 0.20], [4000, 0.51], [5000, 0.49],
  ]));
  const kinds = markers.map((m) => m.kind);
  assert.ok(kinds.includes('best'));
  assert.ok(kinds.includes('worst'));
  assert.strictEqual(markers.find((m) => m.kind === 'worst').t_ms, 3000);
});

test('a consistent session is not given a "shortest rep" to feel bad about', () => {
  const markers = buildMarkers(reps([
    [1000, 0.50], [2000, 0.51], [3000, 0.49], [4000, 0.50], [5000, 0.51],
  ]));
  assert.ok(!markers.some((m) => m.kind === 'worst'));
});

test('the moment form slipped is found', () => {
  // Strong early, clearly reduced through the back half.
  const markers = buildMarkers(reps([
    [1000, 0.50], [2000, 0.51], [3000, 0.50], [4000, 0.49], [5000, 0.50], [6000, 0.51],
    [7000, 0.35], [8000, 0.33], [9000, 0.32],
  ]));
  const fatigue = markers.find((m) => m.kind === 'fatigue');
  assert.ok(fatigue, 'no fatigue marker');
  assert.ok(fatigue.t_ms >= 5000, `fatigue marked too early at ${fatigue.t_ms}`);
});

test('handed drills get a best rep per side', () => {
  const markers = buildMarkers(
    reps([
      [1000, 0.50, 'left'], [2000, 0.52, 'right'], [3000, 0.48, 'left'],
      [4000, 0.55, 'right'], [5000, 0.51, 'left'], [6000, 0.53, 'right'],
    ]),
    { tracksHandedness: true },
  );
  assert.ok(markers.some((m) => m.kind === 'left'));
  assert.ok(markers.some((m) => m.kind === 'right'));
});

test('an unhanded drill gets no per-side markers', () => {
  const markers = buildMarkers(reps([
    [1000, 0.5], [2000, 0.5], [3000, 0.5], [4000, 0.5], [5000, 0.5],
  ]));
  assert.ok(!markers.some((m) => m.kind === 'left' || m.kind === 'right'));
});

test('too few reps produces no markers rather than noise', () => {
  assert.deepStrictEqual(buildMarkers(reps([[1000, 0.5], [2000, 0.5]])), []);
});

test('reps without shape data are ignored', () => {
  const markers = buildMarkers([
    { t_ms: 1000, hand: 'none' }, { t_ms: 2000, hand: 'none' },
    { t_ms: 3000, hand: 'none' }, { t_ms: 4000, hand: 'none' },
  ]);
  assert.deepStrictEqual(markers, []);
});

test('markers come back in playback order', () => {
  const markers = buildMarkers(
    reps([
      [9000, 0.55, 'right'], [1000, 0.20, 'left'], [5000, 0.50, 'left'],
      [3000, 0.51, 'right'], [7000, 0.49, 'left'], [2000, 0.50, 'right'],
    ]),
    { tracksHandedness: true },
  );
  const times = markers.map((m) => m.t_ms);
  assert.deepStrictEqual(times, [...times].sort((a, b) => a - b));
});

// ------------------------------------------------------------- pose lookup

const track = [
  { t: 0, p: [] }, { t: 100, p: [] }, { t: 200, p: [] }, { t: 300, p: [] },
];

test('the nearest pose frame is found for a playback position', () => {
  assert.strictEqual(poseAt(track, 110).t, 100);
  assert.strictEqual(poseAt(track, 190).t, 200);
  assert.strictEqual(poseAt(track, 0).t, 0);
  assert.strictEqual(poseAt(track, 300).t, 300);
});

test('a position with no nearby frame draws nothing rather than a stale pose', () => {
  // The athlete stepped out of frame; showing the last known skeleton would
  // claim they were somewhere they were not.
  assert.strictEqual(poseAt(track, 5000), null);
  assert.strictEqual(poseAt([], 100), null);
});

test('byte sizes are formatted for a human', () => {
  assert.strictEqual(formatBytes(512), '1 KB');
  assert.strictEqual(formatBytes(2 * 1024 * 1024), '2.0 MB');
});

test('the buffer cap is a sane default', () => {
  assert.ok(MAX_BUFFER_BYTES >= 10 * 1024 * 1024, 'too small to review a session');
  assert.ok(MAX_BUFFER_BYTES <= 200 * 1024 * 1024, 'too large for a phone');
});
