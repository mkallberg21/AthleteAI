/**
 * Self-review: let the athlete watch their own session back.
 *
 * Video is the one thing a rep count cannot give an athlete -- seeing what
 * their own release actually looked like on the rep where the range collapsed.
 * The whole product rests on that footage never leaving the phone, so this
 * feature exists entirely on the device and adds no endpoint, no upload, and
 * no field to any request.
 *
 * Three things it does not do, deliberately:
 *
 *  - **It never uploads.** The recording lives in memory as a Blob and is
 *    released when the athlete leaves the screen. Nothing here can reach the
 *    network; there is no code path that would.
 *  - **The coach never sees it.** There is no share, no link, no server copy.
 *    Only the athlete on the device that recorded it can watch.
 *  - **It does not grow without bound.** A long session is capped, oldest
 *    footage first, so a phone does not run out of memory mid-drill.
 *
 * Alongside the video it keeps a compact pose track -- twelve body landmarks at
 * a reduced frame rate, about 120KB a minute -- so the skeleton can be drawn
 * over playback and scrubbed instantly, rather than re-running detection every
 * time the athlete drags the timeline.
 */

/** Landmarks worth drawing. Faces are not, and not storing them is the point. */
const TRACKED = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28];

const BONES = [
  [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
  [11, 23], [12, 24], [23, 24], [23, 25], [25, 27], [24, 26], [26, 28],
];

/** Cap on buffered video. Roughly ten minutes at the bitrate requested below. */
export const MAX_BUFFER_BYTES = 60 * 1024 * 1024;

/** Pose samples per second kept for the overlay. */
export const POSE_SAMPLE_HZ = 15;

const CANDIDATE_TYPES = [
  'video/mp4;codecs=avc1',
  'video/webm;codecs=vp9',
  'video/webm;codecs=vp8',
  'video/webm',
];

export function pickMimeType() {
  if (typeof MediaRecorder === 'undefined') return null;
  return CANDIDATE_TYPES.find((type) => {
    try {
      return MediaRecorder.isTypeSupported(type);
    } catch {
      return false;
    }
  }) || null;
}

export function isSupported() {
  return typeof MediaRecorder !== 'undefined' && pickMimeType() !== null;
}

/**
 * Records a session to memory, keeping a rolling window if it runs long.
 *
 * Chunks are dropped from the front rather than the recording being stopped:
 * an athlete who trains for twenty minutes should still be able to review the
 * last ten, and the end of a set is the part worth watching anyway.
 */
export class SessionRecorder {
  constructor(stream, { maxBytes = MAX_BUFFER_BYTES, mimeType = null } = {}) {
    this.stream = stream;
    this.maxBytes = maxBytes;
    this.mimeType = mimeType || pickMimeType();
    this.chunks = [];
    this.bytes = 0;
    this.droppedBytes = 0;
    this.recorder = null;
    this.startedAt = 0;
    this.poses = [];
    this.lastPoseAt = -Infinity;
    this.objectUrl = null;
    this.error = null;
  }

  get supported() {
    return this.mimeType !== null;
  }

  get truncated() {
    return this.droppedBytes > 0;
  }

  get durationMs() {
    return this.startedAt ? performance.now() - this.startedAt : 0;
  }

  start(now = performance.now()) {
    if (!this.supported) return false;
    try {
      this.recorder = new MediaRecorder(this.stream, {
        mimeType: this.mimeType,
        // Modest on purpose: this is watched on the phone that shot it, and a
        // higher bitrate only buys memory pressure.
        videoBitsPerSecond: 1_200_000,
      });
    } catch (err) {
      this.error = err && err.message;
      return false;
    }

    this.recorder.ondataavailable = (event) => {
      if (!event.data || !event.data.size) return;
      this.chunks.push(event.data);
      this.bytes += event.data.size;
      this.trim();
    };
    // One-second slices so the rolling window has something to drop.
    this.recorder.start(1000);
    this.startedAt = now;
    return true;
  }

  trim() {
    while (this.bytes > this.maxBytes && this.chunks.length > 1) {
      const dropped = this.chunks.shift();
      this.bytes -= dropped.size;
      this.droppedBytes += dropped.size;
    }
  }

  /** Record one pose sample, downsampled to POSE_SAMPLE_HZ. */
  samplePose(landmarks, tMs) {
    if (!landmarks) return;
    if (tMs - this.lastPoseAt < 1000 / POSE_SAMPLE_HZ) return;
    this.lastPoseAt = tMs;

    const frame = { t: Math.round(tMs), p: [] };
    for (const index of TRACKED) {
      const point = landmarks[index];
      if (!point || (point.visibility ?? 1) < 0.5) {
        frame.p.push(null);
        continue;
      }
      // Rounded hard: three decimals is well past what a phone screen shows,
      // and it keeps the track small enough not to matter.
      frame.p.push([
        Math.round(point.x * 1000) / 1000,
        Math.round(point.y * 1000) / 1000,
      ]);
    }
    this.poses.push(frame);
  }

  stop() {
    return new Promise((resolve) => {
      if (!this.recorder || this.recorder.state === 'inactive') {
        resolve(this.blob());
        return;
      }
      this.recorder.onstop = () => resolve(this.blob());
      try {
        this.recorder.stop();
      } catch {
        resolve(this.blob());
      }
    });
  }

  blob() {
    if (!this.chunks.length) return null;
    return new Blob(this.chunks, { type: this.mimeType || 'video/webm' });
  }

  /** An object URL for playback. Revoked by `release`, never left dangling. */
  url() {
    if (this.objectUrl) return this.objectUrl;
    const blob = this.blob();
    if (!blob) return null;
    this.objectUrl = URL.createObjectURL(blob);
    return this.objectUrl;
  }

  /**
   * Drop everything.
   *
   * Called when the athlete leaves the screen, starts another session, or
   * backgrounds the app. The recording is not meant to outlive the moment.
   */
  release() {
    if (this.objectUrl) {
      URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = null;
    }
    if (this.recorder && this.recorder.state !== 'inactive') {
      try {
        this.recorder.stop();
      } catch { /* already stopping */ }
    }
    this.recorder = null;
    this.chunks = [];
    this.poses = [];
    this.bytes = 0;
    this.droppedBytes = 0;
    this.startedAt = 0;
  }
}

/**
 * The moments worth jumping to.
 *
 * Scrubbing a ten-minute clip to find the rep that went wrong is work nobody
 * does twice. Every marker below comes from rep data the client already has,
 * so this costs no request and no server round trip.
 */
export function buildMarkers(reps, { tracksHandedness = false } = {}) {
  const measured = reps.filter((r) => typeof r.rom === 'number' && r.rom > 0);
  if (measured.length < 4) return [];

  const markers = [];
  const byRom = [...measured].sort((a, b) => b.rom - a.rom);
  const best = byRom[0];
  const worst = byRom[byRom.length - 1];

  markers.push({
    t_ms: best.t_ms, kind: 'best',
    label: 'Your best rep',
    detail: 'Fullest range of the session.',
  });

  // Only worth showing when it is meaningfully different from the best --
  // otherwise it reads as a criticism of a perfectly consistent set.
  if (worst.rom < best.rom * 0.8) {
    markers.push({
      t_ms: worst.t_ms, kind: 'worst',
      label: 'Shortest rep',
      detail: `${Math.round((1 - worst.rom / best.rom) * 100)}% less range than your best.`,
    });
  }

  // Where form started slipping: the first rep in the back half that falls
  // well below what the athlete was doing early on.
  const third = Math.floor(measured.length / 3);
  if (third >= 3) {
    const early = median(measured.slice(0, third).map((r) => r.rom));
    const slip = measured
      .slice(Math.floor(measured.length / 2))
      .find((r) => r.rom < early * 0.85);
    if (slip) {
      markers.push({
        t_ms: slip.t_ms, kind: 'fatigue',
        label: 'Form started slipping',
        detail: 'Range dropped here and did not fully come back.',
      });
    }
  }

  if (tracksHandedness) {
    for (const hand of ['left', 'right']) {
      const side = measured.filter((r) => r.hand === hand);
      if (side.length < 3) continue;
      const bestSide = side.reduce((a, b) => (b.rom > a.rom ? b : a));
      markers.push({
        t_ms: bestSide.t_ms, kind: hand,
        label: `Best ${hand} hand`,
        detail: `Your cleanest ${hand}-handed rep.`,
      });
    }
  }

  return markers.sort((a, b) => a.t_ms - b.t_ms);
}

function median(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** The stored pose frame nearest a playback position. */
export function poseAt(poses, tMs, toleranceMs = 200) {
  if (!poses.length) return null;

  let low = 0;
  let high = poses.length - 1;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (poses[mid].t < tMs) low = mid + 1;
    else high = mid;
  }

  const candidates = [poses[low], poses[low - 1]].filter(Boolean);
  let nearest = null;
  let bestGap = Infinity;
  for (const frame of candidates) {
    const gap = Math.abs(frame.t - tMs);
    if (gap < bestGap) {
      bestGap = gap;
      nearest = frame;
    }
  }
  // Beyond the tolerance there is no pose for this moment -- the athlete
  // stepped out of frame -- and drawing the last known one would be a lie.
  return bestGap <= toleranceMs ? nearest : null;
}

/** Draw a stored pose frame onto a canvas sized to the video. */
export function drawPose(ctx, frame, width, height) {
  ctx.clearRect(0, 0, width, height);
  if (!frame) return;

  const point = (index) => {
    const slot = TRACKED.indexOf(index);
    const value = slot === -1 ? null : frame.p[slot];
    return value ? { x: value[0] * width, y: value[1] * height } : null;
  };

  ctx.lineWidth = Math.max(2, width / 220);
  ctx.strokeStyle = 'rgba(57,217,138,.85)';
  ctx.fillStyle = 'rgba(57,217,138,.95)';

  for (const [a, b] of BONES) {
    const from = point(a);
    const to = point(b);
    if (!from || !to) continue;
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
  }
  for (const index of TRACKED) {
    const at = point(index);
    if (!at) continue;
    ctx.beginPath();
    ctx.arc(at.x, at.y, Math.max(3, width / 180), 0, Math.PI * 2);
    ctx.fill();
  }
}

export function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
