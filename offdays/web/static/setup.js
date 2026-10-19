/**
 * The setup check: is the phone placed so the counters can work?
 *
 * Bad placement is the top reason a session is held for review or counts
 * nothing, and on the reference footage it was never the model's fault: the
 * wall-ball clips the pose counter got 0 of 16 on were filmed with the stick
 * hand hidden and the feet out of frame. Those are fixable in the ten seconds
 * before Start, if the screen says what to fix -- and only then. Once the
 * athlete is working, the live framing banner in capture.html takes over.
 *
 * Nothing here loads a model or reads a pixel. It reads the same landmarks the
 * counters read, and the same audio blocks the sound counter hears, and answers
 * one question at a time, most important first: nobody in frame, then the feet
 * cut off, then too small or too close, then a silent microphone, then "hold
 * still" until the picture has been good for long enough to trust.
 *
 * Advisory, not a lock. The athlete can press Start regardless; the point is
 * that the one sentence on screen is the right one.
 */

import { LANDMARKS } from './counter.js';

const IDX = Object.fromEntries(LANDMARKS.map((n, i) => [n, i]));

/** Landmarks under this are treated as missing, as in counter.js. */
export const MIN_VISIBILITY = 0.5;

/**
 * Torso length (shoulders to hips) as a share of frame height. Under the
 * floor the body is a few dozen pixels tall and the wrists are noise; over
 * the ceiling the athlete fills the frame and any step takes a limb out.
 * Lite pose is reliable on a body roughly a fifth to a half of the frame.
 */
export const TORSO_MIN_FRAC = 0.09;
export const TORSO_MAX_FRAC = 0.45;

/** How long the frame has to stay good before the gate says ready. */
export const STEADY_MS = 1500;

/** A frame older than this is not evidence of anything. */
export const STALE_MS = 700;

/**
 * Audio RMS under this, for the whole of the last second, is a microphone
 * that is open but hearing nothing: muted, grabbed by a headset, or a tablet
 * with its mic taped over. A quiet field still sits well above it.
 */
export const SILENT_RMS = 0.0015;
export const SILENCE_WINDOW_MS = 1000;

function point(landmarks, name) {
  const p = landmarks[IDX[name]];
  if (!p) return null;
  const vis = p.visibility ?? p.score ?? 1;
  return vis >= MIN_VISIBILITY ? p : null;
}

function visible(landmarks, names) {
  return names.every((n) => point(landmarks, n));
}

/**
 * Judge one frame. Returns `{ issue, message }` with `issue` null when the
 * frame is usable. Torso length is measured in normalised frame units, which
 * is what every counter uses too, so "too small" here is "too small to count".
 */
export function assessFrame(landmarks, { needsFeet = true } = {}) {
  if (!landmarks) {
    return { issue: 'nobody', message: 'Nobody in frame. Prop the phone so it can see you.' };
  }
  const shoulders = visible(landmarks, ['left_shoulder', 'right_shoulder']);
  const hips = visible(landmarks, ['left_hip', 'right_hip']);
  if (!shoulders || !hips) {
    return { issue: 'torso', message: 'Step back so your shoulders and hips are both in frame.' };
  }
  const ls = point(landmarks, 'left_shoulder'), rs = point(landmarks, 'right_shoulder');
  const lh = point(landmarks, 'left_hip'), rh = point(landmarks, 'right_hip');
  const torso = Math.hypot(
    (ls.x + rs.x) / 2 - (lh.x + rh.x) / 2,
    (ls.y + rs.y) / 2 - (lh.y + rh.y) / 2,
  );
  if (torso < TORSO_MIN_FRAC) {
    return { issue: 'far', message: 'Too far away. Bring the phone a few steps closer.' };
  }
  if (torso > TORSO_MAX_FRAC) {
    return { issue: 'close', message: 'Too close. Move the phone back so your whole body fits.' };
  }
  if (needsFeet) {
    const feet = point(landmarks, 'left_ankle') || point(landmarks, 'right_ankle');
    if (!feet) {
      return { issue: 'feet', message: 'Your feet are cut off. Tilt the phone down or step back.' };
    }
  }
  return { issue: null, message: '' };
}

/** Whether a drill reads anything below the hips. */
export function needsFeet(spec) {
  const kind = spec && spec.signal && spec.signal.kind;
  // Hands-only signals: the stick, a save, a sweep. The feet do not change
  // the count and demanding them pushes the phone further from the net.
  return !['wall_ball_cycle', 'save_reach', 'hand_sweep', 'shooting_arm'].includes(kind);
}

/**
 * Accumulates frames (and, for a drill counted by ear, audio levels) and says
 * what to fix, or that the picture has been good long enough to go.
 */
export class SetupGate {
  constructor(spec, { listens = false } = {}) {
    this.needsFeet = needsFeet(spec);
    this.listens = listens;
    this.goodSince = null;
    this.lastFrameAt = -Infinity;
    this.lastIssue = null;
    this.loudAt = -Infinity;
    this.firstAudioAt = null;
  }

  /** One pose frame at page time `tMs`; `landmarks` may be null. */
  pushFrame(landmarks, tMs) {
    const { issue, message } = assessFrame(landmarks, { needsFeet: this.needsFeet });
    this.lastFrameAt = tMs;
    this.lastIssue = issue ? { issue, message } : null;
    if (issue) this.goodSince = null;
    else if (this.goodSince === null) this.goodSince = tMs;
  }

  /** One audio block (Float32Array) at page time `tMs`. */
  pushAudio(samples, tMs) {
    if (this.firstAudioAt === null) this.firstAudioAt = tMs;
    let sum = 0;
    for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
    const rms = samples.length ? Math.sqrt(sum / samples.length) : 0;
    if (rms >= SILENT_RMS) this.loudAt = tMs;
  }

  /** `{ ready, message }` as of `tMs`. */
  status(tMs) {
    if (tMs - this.lastFrameAt > STALE_MS) {
      return { ready: false, message: 'Nobody in frame. Prop the phone so it can see you.' };
    }
    if (this.lastIssue) return { ready: false, message: this.lastIssue.message };
    if (this.listens && this.firstAudioAt !== null
        && tMs - this.firstAudioAt >= SILENCE_WINDOW_MS
        && tMs - this.loudAt > SILENCE_WINDOW_MS) {
      return {
        ready: false,
        message: 'The microphone hears nothing. Check it is not muted or on a headset.',
      };
    }
    if (tMs - this.goodSince < STEADY_MS) {
      return { ready: false, message: 'Hold still a moment\u2026' };
    }
    return { ready: true, message: 'Good. Press Start when you are set.' };
  }
}
