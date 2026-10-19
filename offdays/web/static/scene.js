/**
 * Watches the scene for the things the distance estimate needs.
 *
 * Nothing here decides a distance. It measures -- the goal's size and place
 * in the frame, the shooter's torso and feet, the phone's tilt -- and hands
 * the medians over the session to `distance.js`, where every factor is
 * weighed. Kept separate so the goal finder can be swapped or calibrated
 * without touching the maths, and so the bench (`scripts/shotcal/`) can run
 * the identical finder on a clip.
 *
 * The goal finder is colour-and-shape, the same approach as the ball: an
 * orange, roughly square blob with the right proportions, big enough to be
 * a goal and not touching the frame edge. Found on the downscaled work frame
 * the ball detector already paints, so it costs one scan of ~130k pixels
 * every few frames and no model. Net colour and lighting vary, so the hue
 * window is wide and the SHAPE does the discriminating: a bin is not square,
 * a pinnie is not 6% of the frame, a sideline is not tall.
 *
 * Units out are short-side units relative to the frame centre (see
 * distance.js), so a phone upright and on its side measure the same.
 */

/**
 * Orange, in 0-360 hue. Floodlit night pipes measured 12-30 on the radar
 * clips; sodium-lit trees and a dirt track sit 30-50 and must stay out, or
 * they merge with the goal and drag its box to the frame edge.
 */
export const GOAL_HUE = [8, 32];
export const GOAL_MIN_SAT = 0.22;
export const GOAL_MIN_VAL = 0.35;
/** Goal proportions: square head-on, narrower from an angle. */
export const GOAL_ASPECT = [0.45, 1.8];
/** A goal narrower than this share of the work frame's short side is too far. */
export const GOAL_MIN_SIDE_FRAC = 0.06;
/**
 * A goal wider than this share of the short side is not a goal in a shooting
 * frame (it would be under 3 yards off), and a line across the frame always
 * is. Rows with an orange run longer than this are the sideline.
 */
export const MAX_GOAL_FRAC = 0.6;
/** How often to look, in ms. The goal does not move. */
export const GOAL_EVERY_MS = 400;
/** Medians are taken over this many looks at most. */
export const GOAL_KEEP = 60;

function hsv(r, g, b) {
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const v = max / 255, d = max - min, s = max ? d / max : 0;
  let h = 0;
  if (d) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60; if (h < 0) h += 360;
  }
  return [h, s, v];
}

/**
 * Find the goal in an ImageData. Returns { x, y, w, h } in pixels, or null.
 *
 * Not a blob: on a real field the goal's orange runs into the orange
 * sideline, the orange track and the sodium-lit trees behind it, and a
 * connected-component box reaches the frame edge. What a goal has that none
 * of those have is STRUCTURE -- two tall, thin, vertical posts and a bar
 * joining their tops. So this looks for the posts: columns of the orange
 * mask whose longest vertical run is tall, taken in pairs at a plausible
 * spacing, scored by how much of the bar between their tops is orange and
 * how little orange sits in the columns just outside them.
 */
export function findGoal(image) {
  const { data, width, height } = image;
  const mask = new Uint8Array(width * height);
  for (let i = 0, p = 0; i < width * height; i += 1, p += 4) {
    const [h, s, v] = hsv(data[p], data[p + 1], data[p + 2]);
    if (h >= GOAL_HUE[0] && h <= GOAL_HUE[1] && s >= GOAL_MIN_SAT && v >= GOAL_MIN_VAL) mask[i] = 1;
  }
  const short = Math.min(width, height);
  const minSide = GOAL_MIN_SIDE_FRAC * short;
  const maxSide = MAX_GOAL_FRAC * short;

  // Per column: the longest vertical orange run, and where it starts/ends.
  // A post is a column whose run is tall; the net makes columns inside the
  // goal tall too, so the posts are the OUTERMOST tall columns of a group.
  const runLen = new Int32Array(width), runTop = new Int32Array(width), runBot = new Int32Array(width);
  for (let x = 0; x < width; x += 1) {
    let run = 0, best = 0, bestEnd = -1;
    for (let y = 0; y < height; y += 1) {
      // One-pixel gaps (net mesh) do not break a run.
      const lit = mask[y * width + x] || (y > 0 && y < height - 1 && mask[(y - 1) * width + x] && mask[(y + 1) * width + x]);
      run = lit ? run + 1 : 0;
      if (run > best) { best = run; bestEnd = y; }
    }
    runLen[x] = best; runTop[x] = bestEnd - best + 1; runBot[x] = bestEnd;
  }

  let best = null;
  for (let xl = 1; xl < width - 1; xl += 1) {
    if (runLen[xl] < minSide) continue;
    for (let xr = xl + Math.ceil(minSide); xr < width - 1 && xr - xl <= maxSide; xr += 1) {
      if (runLen[xr] < minSide) continue;
      const w = xr - xl + 1;
      // Both posts about the same height, and the pair about square-ish.
      const h = Math.min(runLen[xl], runLen[xr]);
      if (Math.abs(runLen[xl] - runLen[xr]) > 0.35 * h) continue;
      if (w / h < GOAL_ASPECT[0] || w / h > GOAL_ASPECT[1]) continue;
      // Tops roughly level (a bar joins them).
      const top = Math.round((runTop[xl] + runTop[xr]) / 2);
      if (Math.abs(runTop[xl] - runTop[xr]) > 0.15 * h) continue;
      // The bar: orange along the top row between the posts.
      let bar = 0;
      const band = Math.max(1, Math.round(0.04 * h));
      for (let x = xl; x <= xr; x += 1) {
        for (let dy = -band; dy <= band; dy += 1) {
          const y = top + dy;
          if (y >= 0 && y < height && mask[y * width + x]) { bar += 1; break; }
        }
      }
      const barFrac = bar / w;
      if (barFrac < 0.6) continue;
      // Outside the posts, at mid-height, it should NOT be orange: a goal
      // stands clear; a wall of trees does not. Checked a few pixels out.
      const probe = Math.max(2, Math.round(0.06 * w));
      let out = 0, outN = 0;
      for (let dy = Math.round(0.25 * h); dy <= Math.round(0.75 * h); dy += 1) {
        const y = top + dy;
        if (y < 0 || y >= height) continue;
        for (const x of [xl - probe, xr + probe]) {
          if (x >= 0 && x < width) { outN += 1; if (mask[y * width + x]) out += 1; }
        }
      }
      const clear = outN ? 1 - out / outN : 0;
      if (clear < 0.6) continue;
      const score = w * h * barFrac * clear;
      if (!best || score > best.score) {
        best = { x: xl, y: top, w, h: Math.max(runBot[xl], runBot[xr]) - top + 1, score };
      }
    }
  }
  if (!best) return null;
  // A goal at the edge has no measurable width: a post in the outermost
  // columns is likelier a post half out of shot than one that fits exactly.
  if (best.x <= 1 || best.y <= 1 || best.x + best.w >= width - 1 || best.y + best.h >= height - 1) return null;
  return { x: best.x, y: best.y, w: best.w, h: best.h };
}

function median(values) {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  return s[s.length >> 1];
}

/**
 * Accumulates the scene over a session and produces the `scene` object
 * `distance.js` wants. Feed it the work-frame ImageData every so often, the
 * pose landmarks every frame, and the tilt when the phone offers one.
 */
export class SceneWatcher {
  constructor({ typedYd = null, focal = null } = {}) {
    this.typedYd = typedYd;
    this.focal = focal;
    this.frameW = 0; this.frameH = 0;
    this.goals = [];       // { w, h, cx, base_y } in short-side units, centre-relative
    this.goalLooks = 0;
    this.lastGoalAt = -Infinity;
    this.torsos = []; this.athleteCx = []; this.feetY = [];
    this.pitches = [];
  }

  setFrame(videoW, videoH) { this.frameW = videoW; this.frameH = videoH; }

  /** Look for the goal in a downscaled frame. `image` is ImageData. */
  pushImage(image, tMs) {
    if (tMs - this.lastGoalAt < GOAL_EVERY_MS) return null;
    this.lastGoalAt = tMs;
    this.goalLooks += 1;
    const g = findGoal(image);
    if (!g) return null;
    const short = Math.min(image.width, image.height);
    const rec = {
      w: g.w / short, h: g.h / short,
      cx: (g.x + g.w / 2 - image.width / 2) / short,
      base_y: (g.y + g.h - image.height / 2) / short,
    };
    this.goals.push(rec);
    if (this.goals.length > GOAL_KEEP) this.goals.shift();
    return g;
  }

  /** The shooter: torso length, centre and feet, from pose landmarks. */
  pushPose(landmarks) {
    if (!landmarks || !this.frameW) return;
    const P = (i) => { const p = landmarks[i]; return p && (p.visibility ?? 1) >= 0.5 ? p : null; };
    const ls = P(11), rs = P(12), lh = P(23), rh = P(24);
    if (!ls || !rs || !lh || !rh) return;
    const short = Math.min(this.frameW, this.frameH);
    const sx = this.frameW / short, sy = this.frameH / short;
    const shx = (ls.x + rs.x) / 2 * sx, shy = (ls.y + rs.y) / 2 * sy;
    const hx = (lh.x + rh.x) / 2 * sx, hy = (lh.y + rh.y) / 2 * sy;
    const torso = Math.hypot(shx - hx, shy - hy);
    if (torso < 0.02) return;
    this.torsos.push(torso);
    this.athleteCx.push(hx - this.frameW / short / 2);
    const la = P(27), ra = P(28);
    if (la || ra) {
      const fy = Math.max(la ? la.y : 0, ra ? ra.y : 0) * sy - this.frameH / short / 2;
      this.feetY.push(fy);
    }
    if (this.torsos.length > 600) { this.torsos.shift(); this.athleteCx.shift(); }
    if (this.feetY.length > 600) this.feetY.shift();
  }

  /** Tilt below the horizontal, degrees, from the accelerometer. */
  pushPitch(deg) {
    if (Number.isFinite(deg)) { this.pitches.push(deg); if (this.pitches.length > 200) this.pitches.shift(); }
  }

  /** The scene for `estimateDistance`. Numbers only; no pixels. */
  scene() {
    const out = { typed_yd: this.typedYd, view_w: this.frameW, view_h: this.frameH, focal: this.focal };
    if (this.goalLooks) {
      out.goal = {
        w: median(this.goals.map((g) => g.w)), h: median(this.goals.map((g) => g.h)),
        cx: median(this.goals.map((g) => g.cx)), base_y: median(this.goals.map((g) => g.base_y)),
        seen: this.goals.length, of: this.goalLooks,
      };
    }
    if (this.torsos.length) {
      out.athlete = { torso: median(this.torsos), cx: median(this.athleteCx), feet_y: median(this.feetY), seen: this.torsos.length };
    }
    if (this.pitches.length) out.pitch_deg = median(this.pitches);
    return out;
  }
}

/**
 * Start listening for the phone's tilt. Resolves to a stop function. Asks
 * permission where the browser needs one (iOS), from a user gesture.
 */
export async function watchPitch(onPitch) {
  if (typeof window === 'undefined' || !('DeviceOrientationEvent' in window)) return () => {};
  try {
    if (typeof DeviceOrientationEvent.requestPermission === 'function') {
      const r = await DeviceOrientationEvent.requestPermission();
      if (r !== 'granted') return () => {};
    }
  } catch { return () => {}; }
  const handler = (e) => {
    if (!Number.isFinite(e.beta)) return;
    // beta is the front-back tilt: 90 is upright facing forward. Tilt below
    // the horizon is 90 - beta for an upright phone; on its side, gamma does
    // the same job. The camera faces out the back, so forward is down.
    const upright = Math.abs(e.gamma || 0) < 45;
    const pitch = upright ? 90 - e.beta : (90 - Math.abs(e.gamma || 0)) * Math.sign(e.beta || 1);
    onPitch(pitch);
  };
  window.addEventListener('deviceorientation', handler);
  return () => window.removeEventListener('deviceorientation', handler);
}
