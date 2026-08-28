/**
 * A detector built for a lacrosse ball specifically.
 *
 * The general object detector knows "sports ball" from photographs of
 * basketballs and tennis balls. It does not reliably see a 6cm ball moving at
 * speed against a wall, which left wall-ball confirmation firing only
 * sometimes.
 *
 * **This is classical computer vision, not a trained model.** No network was
 * trained here and none is downloaded. That is a deliberate choice rather than
 * a shortcut: training one needs thousands of labelled frames of real athletes,
 * which do not exist for this product and could not be collected without
 * uploading exactly the footage the whole architecture promises never to
 * upload. What follows instead exploits four things about a lacrosse ball that
 * a general model has no way to know.
 *
 * **Its size is regulated.** A lacrosse ball is 6.2-6.5cm across, always. Pose
 * gives the athlete's torso length in the same frame, and a torso is roughly
 * 45cm on a youth player -- so the ball's expected radius in pixels is
 * *computable* rather than guessed, and anything twice or half that size is
 * not the ball. This is the single strongest filter here and a general
 * detector cannot use it, because it does not know how far away anything is.
 *
 * **Its colour is regulated too.** Rules require high-visibility white, yellow
 * or orange. Better still, the athlete can show the app their actual ball for a
 * second before starting, which beats any preset because it captures their ball
 * under their light.
 *
 * **It is a solid disc**, so the matched pixels should fill a circle rather
 * than sprawl the way a yellow jacket or a patch of sunlight does.
 *
 * **It flies ballistically.** That check already exists in `ball.js` -- a
 * candidate that does not fall like a ball is rejected by the tracker.
 *
 * The honest trade: a white ball against a white wall is genuinely hard, and
 * the motion gate is what carries that case. Everything here is validated
 * against synthetically rendered frames rather than real footage, which is the
 * same limitation the pose thresholds carry and is stated in the README.
 */

/**
 * Working width, in pixels.
 *
 * 480 rather than something smaller, and this is the crux of why a lacrosse
 * ball is hard. At a realistic framing the athlete's torso spans about 30% of
 * frame height, and a 6.35cm ball is 14% of a 45cm torso -- so at a 192-wide
 * working image the ball is **two pixels across**. Nothing can find that
 * reliably, which is a large part of why the general detector could not.
 *
 * At 480 the same ball is roughly six pixels across, which is findable. The
 * cost is 130k pixels of cheap arithmetic per frame, a millisecond or so --
 * still far below the general detector, and it runs every frame rather than
 * every fourth. Once there is a track the search is a small window, so most
 * frames cost a fraction of that.
 */
export const WORK_WIDTH = 480;

/**
 * Pixel budget for the working image, whichever way the phone is held.
 *
 * Sizing by width alone meant a phone in portrait produced a 480x854 working
 * image -- three times the pixels and three times the cost -- purely because
 * the athlete turned it. Budgeting on area keeps the cost flat and the ball
 * the same size in working pixels in both orientations.
 */
export const WORK_PIXELS = 480 * 270;

/**
 * Working dimensions for a video of any shape.
 *
 * Never upscales: a small camera feed is used as it comes rather than
 * interpolated into looking like more information than it is.
 */
export function workSize(videoWidth, videoHeight) {
  if (!videoWidth || !videoHeight) return { width: 0, height: 0 };
  const scale = Math.min(1, Math.sqrt(WORK_PIXELS / (videoWidth * videoHeight)));
  return {
    width: Math.max(1, Math.round(videoWidth * scale)),
    height: Math.max(1, Math.round(videoHeight * scale)),
  };
}

/**
 * A ball smaller than this in working pixels cannot be resolved.
 *
 * Reported rather than silently returning nothing, so the app can tell the
 * athlete to move the phone closer instead of counting zero and saying
 * nothing about why.
 */
export const MIN_RESOLVABLE_RADIUS_PX = 2.2;

/** A youth torso, shoulder to hip. Every size prior is measured against it. */
export const TORSO_CM = 45;

/** A lacrosse ball is 6.35cm. Kept for callers that predate the registry. */
export const BALL_TO_TORSO = 6.35 / TORSO_CM;

/**
 * Regulated ball diameters, in centimetres.
 *
 * This table is the reason a purpose-built detector beats a general one. Every
 * one of these is fixed by rule, so combined with the athlete's torso in the
 * same frame the ball's size in pixels is *computed* rather than guessed --
 * and a basketball that measures the size of a lacrosse ball is not a
 * basketball, it is something orange in the background.
 *
 * Where a sport has youth sizes the middle one is used; the spread across
 * sizes is about ten percent, which the radius tolerance absorbs several
 * times over.
 */
export const BALLS = {
  lacrosse: { diameterCm: 6.35, colour: 'white' },
  // Sizes 5-7 run 22.0 to 24.3cm.
  basketball: { diameterCm: 23.0, colour: 'basketball' },
  // Sizes 3-5 run 18.5 to 22.0cm.
  soccer: { diameterCm: 20.5, colour: 'white' },
  volleyball: { diameterCm: 21.0, colour: 'white' },
  baseball: { diameterCm: 7.4, colour: 'white' },
  softball: { diameterCm: 9.7, colour: 'optic' },
  tennis: { diameterCm: 6.7, colour: 'optic' },
};

/** Accept a blob between these multiples of the radius the pose implies. */
export const RADIUS_TOLERANCE = [0.45, 2.2];

/** Matched pixels must fill at least this much of the circle they imply. */
export const MIN_FILL = 0.45;

/** Below this share of the search area matching, there is nothing there. */
export const MIN_PIXELS = 6;

/**
 * Colour presets, in illumination-normalised chroma.
 *
 * Normalised chroma -- each channel over the sum -- is used rather than raw
 * RGB because a ball in shade and the same ball in sun have very different
 * brightness and almost identical chroma. White has no chroma at all, so it
 * is matched on brightness and low saturation instead, and leans on motion.
 */
//
// The centroids are measured from real ball colours in sun and in shade rather
// than picked by eye, and the tolerances are set from the distance to the
// nearest thing that is not a ball. Yellow's nearest distractor is skin at
// 0.134 away; orange's is brick at 0.120. Both tolerances leave better than
// twice that margin, and there is a test asserting the separation holds.
export const PRESETS = {
  yellow: { kind: 'chroma', nr: 0.468, ng: 0.445, tol: 0.055, minLuma: 60 },
  orange: { kind: 'chroma', nr: 0.635, ng: 0.300, tol: 0.050, minLuma: 60 },
  // White has no chroma at all -- a white ball and a grey wall are the same
  // point in this space -- so it is matched on brightness and leans entirely
  // on the motion gate to tell it from the wall behind it.
  white: { kind: 'bright', minLuma: 170, maxSpread: 0.055 },
  // A basketball is orange-brown and so is brick, which sits only 0.056 away
  // -- the tightest separation in this table by some margin. The tolerance is
  // set to half that, and the size, shape and motion gates carry the rest.
  basketball: { kind: 'chroma', nr: 0.565, ng: 0.304, tol: 0.030, minLuma: 45 },
  // Tennis and softball optic yellow, which is greener than a yellow lacrosse
  // ball and needs its own centroid rather than a widened one.
  optic: { kind: 'chroma', nr: 0.418, ng: 0.446, tol: 0.050, minLuma: 55 },
  // Neon lime, which lacrosse balls are increasingly sold in.
  //
  // The tightest fit in this table after basketball, and for a worse reason:
  // its nearest distractor is GRASS, which is the surface the sport is played
  // on. Sunlit grass sits 0.101 away and the tolerance is half of that, which
  // leaves exactly 0.002 of slack over the most neon ball sampled. The centre
  // was solved for rather than eyeballed -- moved off the sample mean towards
  // yellow-green until every ball fitted inside half the grass distance.
  //
  // minLuma does the second half of the work. Shaded grass reads about 82 and
  // a lime ball in shade about 150, so the brightness floor rejects the dark
  // green a chroma match would otherwise argue about.
  //
  // A ball this close to its distractor is exactly the case calibration exists
  // for: two seconds pointed at the actual ball beats any preset here.
  lime: { kind: 'chroma', nr: 0.422, ng: 0.514, tol: 0.050, minLuma: 95 },
};

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** How well one pixel matches a profile. 0 is no match, 1 is exact. */
export function matchPixel(r, g, b, profile) {
  const sum = r + g + b;
  if (sum <= 0) return 0;
  const luma = 0.299 * r + 0.587 * g + 0.114 * b;
  if (luma < (profile.minLuma ?? 0)) return 0;

  if (profile.kind === 'bright') {
    // White: bright, and all three channels close together.
    const nr = r / sum, ng = g / sum, nb = b / sum;
    const spread = Math.max(nr, ng, nb) - Math.min(nr, ng, nb);
    if (spread > profile.maxSpread) return 0;
    return 1 - spread / profile.maxSpread;
  }

  const nr = r / sum, ng = g / sum;
  const distance = Math.hypot(nr - profile.nr, ng - profile.ng);
  if (distance > profile.tol) return 0;
  return 1 - distance / profile.tol;
}

/**
 * Learn a profile from the ball the athlete is actually holding.
 *
 * Two seconds of setup buys more than any preset can: it captures this ball,
 * in this light, in this gym. A yellow ball under sodium floodlights is not
 * the yellow in a rulebook.
 */
export function calibrate(image, box) {
  const { data, width } = image;
  const x0 = Math.max(0, Math.floor(box.x));
  const y0 = Math.max(0, Math.floor(box.y));
  const x1 = Math.min(width, Math.ceil(box.x + box.w));
  const y1 = Math.min(image.height, Math.ceil(box.y + box.h));

  let sr = 0, sg = 0, sb = 0, n = 0;
  for (let y = y0; y < y1; y += 1) {
    for (let x = x0; x < x1; x += 1) {
      const i = (y * width + x) * 4;
      sr += data[i]; sg += data[i + 1]; sb += data[i + 2];
      n += 1;
    }
  }
  if (!n) return null;

  const r = sr / n, g = sg / n, b = sb / n;
  const sum = r + g + b || 1;
  const nr = r / sum, ng = g / sum, nb = b / sum;
  const spread = Math.max(nr, ng, nb) - Math.min(nr, ng, nb);
  const luma = 0.299 * r + 0.587 * g + 0.114 * b;

  // A ball with no colour to speak of is a white one, and gets the brightness
  // profile rather than a chroma centroid that would match every grey thing
  // in the frame.
  if (spread < 0.045) {
    return { kind: 'bright', minLuma: Math.max(120, luma * 0.72), maxSpread: 0.06 };
  }
  return {
    kind: 'chroma',
    nr, ng,
    tol: 0.07,
    minLuma: Math.max(40, luma * 0.45),
    source: 'calibrated',
  };
}

/**
 * Ball radius implied by the athlete's own body, in normalised frame units.
 *
 * The filter a general detector cannot apply, because it has no idea how far
 * away anything is. Returns null when the pose is not usable, and the caller
 * then falls back to an unconstrained search rather than a wrong constraint.
 */
/**
 * Body references for scale, best first.
 *
 * More than one, deliberately. Requiring shoulder *and* hip meant an athlete
 * framed from the chest up -- which is most of them, because a phone propped
 * against a bag points at whatever it points at -- lost the size prior
 * entirely and with it the detector's strongest filter. Shoulder width works
 * when the hips are out of shot, and head-to-shoulder works when it is just a
 * head and shoulders.
 */
const SCALE_REFERENCES = [
  { a: 'left_shoulder', b: 'left_hip', cm: TORSO_CM },
  { a: 'right_shoulder', b: 'right_hip', cm: TORSO_CM },
  { a: 'left_shoulder', b: 'right_shoulder', cm: 36 },
  { a: 'nose', b: 'left_shoulder', cm: 28 },
  { a: 'nose', b: 'right_shoulder', cm: 28 },
  { a: 'left_hip', b: 'left_knee', cm: 40 },
];

/**
 * Ball radius implied by the athlete's own body, in frame heights.
 *
 * Tries each reference in turn, so a partly-framed athlete still gets a size
 * prior. Returns null only when nothing usable is visible, and the caller
 * then falls back to an unconstrained search rather than a wrong constraint.
 */
export function radiusFromPose(landmarks, index, diameterCm = 6.35, aspect = 1) {
  if (!landmarks) return null;
  for (const ref of SCALE_REFERENCES) {
    const a = landmarks[index[ref.a]];
    const b = landmarks[index[ref.b]];
    if (!a || !b) continue;
    if ((a.visibility ?? 1) < 0.5 || (b.visibility ?? 1) < 0.5) continue;
    const span = Math.hypot((a.x - b.x) * aspect, a.y - b.y);
    if (span < 0.04) continue;
    return (span * (diameterCm / ref.cm)) / 2;
  }
  return null;
}

/**
 * Remembers the last usable scale.
 *
 * An athlete who turns, steps out of shot for a second, or is briefly
 * occluded by their own stick should not lose the size prior and with it the
 * detector's selectivity. Body scale barely changes within a session, so the
 * last good reading stays valid far longer than the pose that produced it.
 */
export class ScaleMemory {
  constructor(holdMs = 4000) {
    this.holdMs = holdMs;
    this.value = null;
    this.at = -Infinity;
  }

  update(radius, tMs) {
    if (radius) {
      // Blended rather than replaced, so one bad frame cannot move it far.
      this.value = this.value === null ? radius : this.value + 0.25 * (radius - this.value);
      this.at = tMs;
    }
    return this.get(tMs);
  }

  get(tMs) {
    if (this.value === null) return null;
    return tMs - this.at <= this.holdMs ? this.value : null;
  }
}

/**
 * Finds a small, fast, known-coloured ball.
 *
 * Keeps the previous frame so a static object of the right colour -- a yellow
 * bin, a white line on the wall -- can be told from a ball, which is what
 * makes the white case workable at all.
 */
export class BallVision {
  constructor(options = {}) {
    // Most balls come in one colour and this is a list of one. A lacrosse ball
    // is sold in white, yellow and lime, and which one an athlete owns is
    // whatever their club bought -- so the drill names every plausible preset
    // and the first seconds of the session decide between them.
    this.candidates = (options.profiles && options.profiles.length)
      ? [...options.profiles]
      : [options.profile || PRESETS.yellow];
    this.profile = this.candidates[0];
    this.useMotion = options.useMotion !== false;
    this.motionThreshold = options.motionThreshold ?? 18;
    this.previous = null;
    /** Gated match score per pixel, reused between frames to avoid churn. */
    this.mask = null;
    // Trying every candidate on every frame would multiply the cost of the
    // most expensive stage in the pipeline on the cheapest phone, and a ball
    // does not change colour mid-session. So candidates compete over an
    // opening window and the winner is locked for the rest of it.
    this.locked = this.candidates.length === 1;
    this.trials = new Map(this.candidates.map((p) => [p, 0]));
    this.settleFrames = options.settleFrames ?? 45;
    this.seen = 0;
  }

  setProfile(profile) {
    this.profile = profile;
    this.candidates = [profile];
    this.locked = true;
    this.previous = null;
  }

  /**
   * Which preset is winning, and whether the choice has been made. Surfaced
   * so the capture screen can say "looking for a white ball" and then say
   * which one it settled on, rather than silently picking.
   */
  get chosen() {
    const name = Object.keys(PRESETS).find((k) => PRESETS[k] === this.profile);
    return { profile: this.profile, name: name || 'custom', locked: this.locked };
  }

  /**
   * Score one frame against every candidate still in the running.
   *
   * Called by detect() while unlocked. The winner is the preset that found the
   * ball most often, not the one that found it first: a single lucky frame on
   * the wrong preset would otherwise decide the whole session.
   */
  _compete(detectWith) {
    let best = null;
    for (const candidate of this.candidates) {
      const found = detectWith(candidate);
      if (!found) continue;
      this.trials.set(candidate, this.trials.get(candidate) + 1);
      if (!best || this.trials.get(candidate) > this.trials.get(best.profile)) {
        best = { profile: candidate, found };
      }
    }
    this.seen += 1;
    // Set explicitly in every branch rather than left wherever the loop above
    // finished. The loop assigns `this.profile` per candidate as it goes, so
    // without this a frame where nothing was found leaves the last candidate
    // tried standing -- which is how "no ball anywhere" quietly became "this
    // drill is looking for a lime one now".
    if (this.seen >= this.settleFrames) {
      const ranked = [...this.trials.entries()].sort((a, b) => b[1] - a[1]);
      // Nothing found anything: keep the drill's first guess rather than
      // locking onto a preset that never worked.
      this.profile = ranked[0][1] > 0 ? ranked[0][0] : this.candidates[0];
      this.locked = true;
    } else {
      this.profile = best ? best.profile : this.candidates[0];
    }
    return best ? best.found : null;
  }

  /**
   * Whether the ball is even big enough to find at this framing.
   *
   * The honest failure. A ball two pixels across is not a detection problem,
   * it is a "stand closer to the phone" problem, and saying so beats
   * returning nothing for ten minutes.
   */
  tooSmall(expectedRadius, height) {
    if (!expectedRadius) return false;
    return expectedRadius * height < MIN_RESOLVABLE_RADIUS_PX;
  }

  /**
   * Whether a measured blob is shaped and sized like the ball.
   *
   * Shared by both refinement attempts so the colour-first and motion-only
   * measurements are judged identically -- otherwise the fallback could be
   * accepted on terms the primary was refused on.
   */
  _accept(blob, { reach, cx, cy, width, height, expectedRadius }) {
    const { count, minX, maxX, minY, maxY } = blob;
    const boxW = maxX - minX + 1, boxH = maxY - minY + 1;

    // Measured across the blob rather than from the matched-pixel count. A
    // panelled ball -- a soccer ball's black hexagons, a baseball's stitching
    // -- matches on maybe 70% of its own area, and a count-derived radius
    // would report it 16% small every time. The panels still reach the edges,
    // so the box spans the real ball.
    const radiusPx = Math.max(boxW, boxH) / 2;

    // Pixels running to the edge of the search window mean the object
    // continues past it, so its size is unknown and larger than measured.
    const edge = 1;
    if (expectedRadius && (
      minX <= clamp(cx - reach, 0, width) + edge
      || maxX >= clamp(cx + reach, 0, width) - 1 - edge
      || minY <= clamp(cy - reach, 0, height) + edge
      || maxY >= clamp(cy + reach, 0, height) - 1 - edge)) {
      return false;
    }

    // A disc fills its own circle. A jacket sleeve or a strip of sunlight of
    // the same colour does not.
    if (count / (Math.PI * radiusPx * radiusPx) < MIN_FILL) return false;
    if (Math.min(boxW, boxH) / Math.max(boxW, boxH) < 0.55) return false;

    if (expectedRadius) {
      const ratio = (radiusPx / height) / expectedRadius;
      // The filter no general detector can apply: a ball's diameter is fixed
      // by rule, and the athlete's own torso says how big that is here.
      if (ratio < RADIUS_TOLERANCE[0] || ratio > RADIUS_TOLERANCE[1]) return false;
    }
    return true;
  }

  /**
   * One frame.
   *
   * `expectedRadius` comes from the pose; `near` is where the tracker thinks
   * the ball is, which narrows the search to a window and makes a false
   * positive across the room impossible.
   */
  /**
   * Find the ball. Runs the chosen preset once the choice is made, and every
   * candidate until then.
   *
   * Each candidate has to see the same motion history, so the previous frame
   * is restored before each attempt -- without that the second candidate
   * compares this frame against itself, finds no motion, and loses a contest
   * it should have won.
   */
  detect(image, options = {}) {
    if (this.locked) return this._detectOnce(image, options);
    const baseline = this.previous;
    return this._compete((candidate) => {
      this.previous = baseline;
      this.profile = candidate;
      return this._detectOnce(image, options);
    });
  }

  _detectOnce(image, { expectedRadius = null, near = null } = {}) {
    const { data, width, height } = image;
    if (this.tooSmall(expectedRadius, height)) {
      this.previous = null;
      return null;
    }
    const previous = this.previous;
    this.previous = this.useMotion ? Uint8ClampedArray.from(data) : null;

    // Search window. Full frame on acquisition, a box around the prediction
    // once there is a track -- cheaper, and it cannot latch onto something
    // three metres away between frames.
    let x0 = 0, y0 = 0, x1 = width, y1 = height;
    if (near) {
      const span = Math.max(18, (expectedRadius || 0.03) * height * 7);
      x0 = clamp(Math.floor(near.x * width - span), 0, width);
      x1 = clamp(Math.ceil(near.x * width + span), 0, width);
      y0 = clamp(Math.floor(near.y * height - span), 0, height);
      y1 = clamp(Math.ceil(near.y * height + span), 0, height);
    }

    // One pass: score every pixel into a mask, and accumulate into coarse
    // cells so the brightest region can be found without a full
    // connected-component pass.
    //
    // The mask is kept rather than re-scoring during refinement. Re-scoring
    // was a real bug: the motion gate applied to the accumulation pass only,
    // so refinement re-absorbed every static wall pixel of the right colour
    // and measured the ball as the size of the wall.
    if (!this.mask || this.mask.length !== width * height) {
      this.mask = new Float32Array(width * height);
      this.moved = new Uint8Array(width * height);
    }
    const mask = this.mask;
    const moved = this.moved;
    mask.fill(0);
    moved.fill(0);

    const cell = 4;
    const cols = Math.ceil(width / cell);
    const grid = new Float32Array(cols * Math.ceil(height / cell));

    for (let y = y0; y < y1; y += 1) {
      for (let x = x0; x < x1; x += 1) {
        const i = (y * width + x) * 4;
        const score = matchPixel(data[i], data[i + 1], data[i + 2], this.profile);
        if (score <= 0) continue;
        // Colour and motion are recorded separately rather than combined.
        // Combining them broke large balls: a basketball moving at a normal
        // speed overlaps itself almost completely between frames, so only a
        // thin crescent changes and the ball measured as a sliver. Motion is
        // for working out *where* to look; colour and shape are for measuring
        // what is there.
        mask[y * width + x] = score;
        let changed = true;
        if (previous && this.useMotion) {
          // A ball is moving. A painted line of the same colour is not, and
          // this is the only thing separating them for a white ball.
          if (this.profile.kind === 'bright') {
            // Directional, because a plain magnitude test lights up the place
            // the ball *left* as brightly as where it arrived -- and against a
            // pale wall the vacated spot still matches the profile, so the
            // detector followed the hole instead of the ball.
            const lumaNow = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
            const lumaWas = 0.299 * previous[i] + 0.587 * previous[i + 1]
              + 0.114 * previous[i + 2];
            changed = lumaNow - lumaWas >= this.motionThreshold;
          } else {
            const delta = Math.abs(data[i] - previous[i])
              + Math.abs(data[i + 1] - previous[i + 1])
              + Math.abs(data[i + 2] - previous[i + 2]);
            changed = delta >= this.motionThreshold;
          }
        }
        if (changed) {
          moved[y * width + x] = 1;
          // Only moving pixels vote for where to look.
          grid[((y / cell) | 0) * cols + ((x / cell) | 0)] += score;
        }
      }
    }

    let peak = -1, peakIndex = -1;
    for (let i = 0; i < grid.length; i += 1) {
      if (grid[i] > peak) { peak = grid[i]; peakIndex = i; }
    }
    if (peakIndex < 0 || peak <= 0) return null;

    // Refine around the peak: weighted centroid and a pixel count, which gives
    // the radius directly since area is pi r squared.
    const cx = ((peakIndex % cols) + 0.5) * cell;
    const cy = ((peakIndex / cols | 0) + 0.5) * cell;
    // Wide enough that an object at the upper size bound still fits entirely
    // inside it. Too tight a window crops a beach ball down to ball-sized and
    // hands it the very test that was meant to reject it -- a yellow bucket
    // measured 2.19 against a 2.2 limit before this was widened.
    const reach = Math.max(
      8, Math.round((expectedRadius || 0.03) * height * RADIUS_TOLERANCE[1] * 1.6),
    );

    // Measure the whole blob by colour first. If colour alone over-segments --
    // a white ball in front of a white wall, where everything matches -- fall
    // back to the moving pixels only. Preferring colour is what keeps a large
    // ball from being measured as the crescent that changed; the fallback is
    // what keeps a white ball findable against a wall.
    const measure = (motionOnly) => {
      let sx = 0, sy = 0, weight = 0, count = 0;
      let minX = width, maxX = 0, minY = height, maxY = 0;
      for (let y = clamp(cy - reach, 0, height); y < clamp(cy + reach, 0, height); y += 1) {
        for (let x = clamp(cx - reach, 0, width); x < clamp(cx + reach, 0, width); x += 1) {
          const at = (y | 0) * width + (x | 0);
          const score = mask[at];
          if (score <= 0) continue;
          if (motionOnly && !moved[at]) continue;
          sx += x * score; sy += y * score; weight += score; count += 1;
          if (x < minX) minX = x; if (x > maxX) maxX = x;
          if (y < minY) minY = y; if (y > maxY) maxY = y;
        }
      }
      return { sx, sy, weight, count, minX, maxX, minY, maxY };
    };

    const attempts = this.useMotion && previous ? [false, true] : [false];
    let chosen = null;
    for (const motionOnly of attempts) {
      const blob = measure(motionOnly);
      if (blob.count < MIN_PIXELS || blob.weight <= 0) continue;
      if (this._accept(blob, { reach, cx, cy, width, height, expectedRadius })) {
        chosen = blob;
        break;
      }
    }
    if (!chosen) return null;
    const { sx, sy, weight, count, minX, maxX, minY, maxY } = chosen;

    const boxW = maxX - minX + 1, boxH = maxY - minY + 1;
    // Measured across the blob rather than from the matched-pixel count.
    // A panelled ball -- a soccer ball's black hexagons, a baseball's
    // stitching -- matches on maybe 70% of its own area, and a count-derived
    // radius would report it 16% small every time. The white panels still
    // reach the edges, so the box spans the real ball.
    const radiusPx = Math.max(boxW, boxH) / 2;

    // Matched pixels running to the edge of the search window mean the object
    // continues beyond it, so its real size is unknown and larger than this.
    // Belt and braces with the widened window above.
    const edge = 1;
    if (minX <= clamp(cx - reach, 0, width) + edge
      || maxX >= clamp(cx + reach, 0, width) - 1 - edge
      || minY <= clamp(cy - reach, 0, height) + edge
      || maxY >= clamp(cy + reach, 0, height) - 1 - edge) {
      if (expectedRadius) return null;
    }

    // A disc fills its own circle. A jacket sleeve or a strip of sunlight of
    // the same colour does not, and this is what rejects them.
    const fill = count / (Math.PI * radiusPx * radiusPx);
    if (fill < MIN_FILL) return null;
    const aspect = Math.min(boxW, boxH) / Math.max(boxW, boxH);
    if (aspect < 0.55) return null;

    if (expectedRadius) {
      const ratio = (radiusPx / height) / expectedRadius;
      // The filter no general detector can apply: a lacrosse ball is always
      // 6.35cm, and the athlete's own torso says how big that is here.
      if (ratio < RADIUS_TOLERANCE[0] || ratio > RADIUS_TOLERANCE[1]) return null;
    }

    return {
      x: (sx / weight) / width,
      y: (sy / weight) / height,
      r: radiusPx / height,
      score: clamp(weight / count, 0, 1),
      pixels: count,
      source: 'vision',
    };
  }
}
