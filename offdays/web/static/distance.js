/**
 * How far from the goal was the shooter? Every factor the phone has, fused.
 *
 * The typed distance is the largest error in a shot speed: one pace short at
 * 8 yards is 12% of the distance and 12% of every speed in the session, and
 * because every shot shares it the session median cannot wash it out. So the
 * distance is estimated from everything the phone can see and know, each
 * factor as its own estimate with its own error bar, and the estimates are
 * combined by how much each one deserves to be believed (inverse-variance
 * weighting). A factor that disagrees with the rest beyond reason is named and
 * dropped, never silently averaged in.
 *
 * The factors, and what each one knows:
 *
 *   goal width      A goal is 6 ft between the posts by rule. Its width in the
 *                   frame, with the lens's focal length, is the camera's
 *                   distance to the goal plane. The strongest factor there is.
 *   goal height     The crossbar is 6 ft off the ground by the same rule. A
 *                   second, nearly independent reading of the same distance,
 *                   so pixel quantisation on one is halved by the other.
 *   athlete size    The shooter's torso in the frame, against what a torso
 *                   measures at their age, is the camera's distance to the
 *                   SHOOTER. The phone is seldom exactly at the shooting spot,
 *                   and this is what tells the two apart.
 *   ground plane    Both the goal's base and the shooter's feet are on the
 *                   ground. With the phone's tilt (its accelerometer), where
 *                   each sits in the frame says how far along the ground each
 *                   is. A second reading of the shooter's distance that owes
 *                   nothing to the age table.
 *   bearings        Where the goal and the shooter sit left-right in the frame
 *                   are their directions from the camera, so the shooter-to-
 *                   goal distance is a triangle with the camera at the vertex
 *                   rather than a subtraction along one line -- which makes a
 *                   phone beside the shooter and a phone behind them the same
 *                   maths.
 *   typed distance  What the athlete paced out. One pace is about a yard, so
 *                   it is believed to about a yard. It is also the only factor
 *                   that needs no goal in frame, and it is what calibrates the
 *                   lens (below).
 *   focal length    Not a distance, but the one number every camera factor
 *                   scales with. Unknown on a new phone to about 15%; learned
 *                   from sessions where the camera and the typed distance
 *                   agreed, to about 5%.
 *
 * All image measurements are in SHORT-SIDE units (pixels divided by the
 * shorter side of the frame) so a phone upright and a phone on its side, and
 * a 720p and a 1080p stream, mean the same thing. Positions are relative to
 * the frame centre, right and down positive.
 *
 * The same maths runs in `offdays/distance.py`; the server recomputes from
 * the raw observations and never trusts the phone's answer, exactly as it
 * does for speed. tests pin the two on one case.
 */

/** Regulation goal mouth, posts outside-to-outside: 6 ft plus a 2 in pipe. */
export const GOAL_WIDTH_M = (6 * 12 + 2) * 0.0254;
/** Crossbar top to the ground, the same 6 ft plus the pipe. */
export const GOAL_HEIGHT_M = GOAL_WIDTH_M;

/**
 * Focal length of a phone's main camera as a share of the frame's short
 * side, when nothing better is known. Fitted on the radar clips (1.16-1.18
 * on one phone); a wide range of phones sit 1.0-1.4. The 15% is what that
 * ignorance costs, and why the lens gets learned.
 */
export const DEFAULT_FOCAL = 1.15;
export const DEFAULT_FOCAL_REL_SIGMA = 0.15;
/** A learned lens is good to about this, from paced distances. */
export const LEARNED_FOCAL_REL_SIGMA = 0.05;
/** A lens outside this is a bad calibration, not a camera. */
export const FOCAL_RANGE = [0.5, 2.5];

/** One pace: what a typed distance is believed to, in metres. */
export const TYPED_SIGMA_M = 0.9;

/**
 * Torso (shoulder midpoint to hip midpoint) by age, in metres: about 0.30 of
 * stature at the 50th percentile. The ball detector's 45 cm is the 12 row.
 * Individual spread is about 12%, and that is this factor's floor.
 */
export const TORSO_M_BY_AGE = [[9, 0.39], [10, 0.41], [11, 0.43], [12, 0.45],
  [13, 0.47], [14, 0.49], [15, 0.51], [16, 0.52], [17, 0.53], [200, 0.53]];
export const TORSO_REL_SIGMA = 0.20;
/**
 * Pose on a shooter seen from behind or the side reads the torso short, and
 * the shooter at the near edge of the frame is often part cut off. Measured,
 * not guessed: on the seven radar clips this factor put the camera 3-4 yd
 * from a shooter the goal said it was about 1 yd from -- a factor of two.
 * Priced at that. It still tells a phone beside the shooter from one left
 * ten yards behind, which is the mistake it exists to catch.
 */
export const TORSO_POSE_REL_SIGMA = 0.55;
/**
 * Where the phone is told to stand: beside the shooter, level with the
 * spot. That instruction is a measurement too -- the camera-to-shooter
 * distance is about a yard, give or take a couple -- and it is what keeps
 * one rough pose reading from dragging a good goal reading around.
 */
export const PLACEMENT_M = 0.9;
export const PLACEMENT_SIGMA_M = 2.0;
/** Age to assume when none is known: the same 11-12 band used everywhere. */
export const DEFAULT_AGE = 12;

/** Pixel error on a goal edge, in pixels of a 720-short-side frame. */
export const EDGE_PX_720 = 2;
/**
 * Goal height is the weaker twin: the box runs to the bottom of the net,
 * which sags below the ground line, and the tilt foreshortens it. On the
 * radar clips it read 30% over the width, every clip. Priced so it adds a
 * little to the width and cannot pull it.
 */
export const HEIGHT_EXTRA_REL_SIGMA = 0.30;
/** The ground-plane reading is unverified on a real phone; priced accordingly. */
export const GROUND_REL_SIGMA = 0.5;
/** Under this angle below the horizon the ground-plane maths is a lottery. */
export const MIN_GROUND_ANGLE_RAD = 2 * Math.PI / 180;

/** A goal narrower than this share of the short side is too small to measure. */
export const MIN_GOAL_WIDTH = 0.06;
/** The goal must have been seen in this share of the frames it was looked for. */
export const MIN_GOAL_SEEN = 0.3;

/** Beyond this many combined sigmas the camera and the typed distance disagree. */
export const DISAGREE_SIGMAS = 3;

export const YD_PER_M = 1 / 0.9144;

export function torsoForAge(age) {
  const a = Number.isFinite(age) ? age : DEFAULT_AGE;
  for (const [max, m] of TORSO_M_BY_AGE) if (a <= max) return m;
  return TORSO_M_BY_AGE[TORSO_M_BY_AGE.length - 1][1];
}

/** Inverse-variance combination of { value, sigma } estimates. */
export function fuse(estimates) {
  const usable = estimates.filter((e) => e && Number.isFinite(e.value) && e.sigma > 0);
  if (!usable.length) return null;
  let w = 0, s = 0;
  for (const e of usable) { const k = 1 / (e.sigma * e.sigma); w += k; s += k * e.value; }
  return { value: s / w, sigma: Math.sqrt(1 / w) };
}

function factor(name, m, sigma, used, why = '') {
  return { name, yd: round2(m * YD_PER_M), plus_minus_yd: round2(sigma * YD_PER_M), used, why };
}
const round2 = (x) => Math.round(x * 100) / 100;

/**
 * Estimate the shooting distance.
 *
 * scene: {
 *   typed_yd, view_w, view_h, focal,
 *   goal:    { w, h, cx, base_y, seen, of }      short-side units, centre-relative
 *   athlete: { torso, cx, feet_y, seen }
 *   pitch_deg                                    camera tilt below horizontal
 * }
 * options: { age }
 *
 * Returns { distance_m, plus_minus_m, source, factors, note, focal_hint }.
 */
export function estimateDistance(scene, { age } = {}) {
  const s = scene || {};
  const factors = [];
  const short = Math.min(s.view_w || 0, s.view_h || 0);
  const edge = short > 0 ? EDGE_PX_720 * (720 / short) / 720 : 0;  // in short-side units

  // --- the lens -------------------------------------------------------------
  let f = DEFAULT_FOCAL, fRel = DEFAULT_FOCAL_REL_SIGMA, learned = false;
  if (Number.isFinite(s.focal) && s.focal >= FOCAL_RANGE[0] && s.focal <= FOCAL_RANGE[1]) {
    f = s.focal; fRel = LEARNED_FOCAL_REL_SIGMA; learned = true;
  }

  // --- the typed distance ---------------------------------------------------
  const typed = Number.isFinite(s.typed_yd) && s.typed_yd > 0
    ? { value: s.typed_yd / YD_PER_M, sigma: TYPED_SIGMA_M } : null;
  if (typed) factors.push(factor('set', typed.value, typed.sigma, true, 'paced out, about a yard'));

  // --- camera to goal -------------------------------------------------------
  const g = s.goal;
  const goalOk = g && short > 0 && Number.isFinite(g.w) && g.w >= MIN_GOAL_WIDTH
    && (g.of ? (g.seen || 0) / g.of >= MIN_GOAL_SEEN : true);
  let zg = null;
  if (goalOk) {
    // Relative sigmas here EXCLUDE the lens: everything the camera measures
    // scales with f together, so its error is applied once, at the end.
    const byW = { value: f * GOAL_WIDTH_M / g.w, sigma: 0 };
    byW.sigma = byW.value * (edge / g.w);
    factors.push(factor('goal width', byW.value, byW.value * Math.hypot(edge / g.w, fRel), true,
      'posts are 6 ft apart'));
    const ests = [byW];
    if (Number.isFinite(g.h) && g.h >= MIN_GOAL_WIDTH) {
      const byH = { value: f * GOAL_HEIGHT_M / g.h, sigma: 0 };
      byH.sigma = byH.value * Math.hypot(edge / g.h, HEIGHT_EXTRA_REL_SIGMA);
      factors.push(factor('goal height', byH.value, byH.value * Math.hypot(edge / g.h, HEIGHT_EXTRA_REL_SIGMA, fRel),
        true, 'crossbar is 6 ft up'));
      ests.push(byH);
    }
    zg = fuse(ests);
  } else if (g && g.of) {
    factors.push({ name: 'goal width', yd: null, plus_minus_yd: null, used: false,
      why: g.w < MIN_GOAL_WIDTH ? 'goal too small in frame' : 'goal not seen enough' });
  }

  // --- camera to shooter ----------------------------------------------------
  const a = s.athlete;
  let za = null;
  if (zg && a && Number.isFinite(a.torso) && a.torso > 0) {
    const torsoM = torsoForAge(age);
    const byTorso = { value: f * torsoM / a.torso, sigma: 0 };
    byTorso.sigma = byTorso.value * Math.hypot(TORSO_REL_SIGMA, TORSO_POSE_REL_SIGMA);
    factors.push(factor('shooter size', byTorso.value, byTorso.value * Math.hypot(TORSO_REL_SIGMA, TORSO_POSE_REL_SIGMA, fRel),
      true, `torso about ${Math.round(torsoM * 100)} cm at this age`));
    const placed = { value: PLACEMENT_M, sigma: PLACEMENT_SIGMA_M };
    factors.push(factor('placement', placed.value, placed.sigma, true, 'phone beside the shooter, as asked'));
    const ests = [byTorso, placed];
    // Ground plane: camera height from the goal's base, then the feet.
    if (Number.isFinite(s.pitch_deg) && Number.isFinite(g.base_y) && Number.isFinite(a.feet_y)) {
      const p = s.pitch_deg * Math.PI / 180;
      const angGoal = p + Math.atan2(g.base_y, f);
      const angFeet = p + Math.atan2(a.feet_y, f);
      if (angGoal > MIN_GROUND_ANGLE_RAD && angFeet > MIN_GROUND_ANGLE_RAD) {
        const camH = zg.value * Math.tan(angGoal);
        const byGround = { value: camH / Math.tan(angFeet), sigma: 0 };
        byGround.sigma = byGround.value * Math.hypot(GROUND_REL_SIGMA, zg.sigma / zg.value);
        factors.push(factor('ground plane', byGround.value, byGround.value * Math.hypot(GROUND_REL_SIGMA, fRel),
          true, `phone tilted ${Math.round(s.pitch_deg)} deg, camera about ${round2(camH)} m up`));
        ests.push(byGround);
      } else {
        factors.push({ name: 'ground plane', yd: null, plus_minus_yd: null, used: false,
          why: 'too close to the horizon to read' });
      }
    }
    za = fuse(ests);
  }

  // --- the triangle ---------------------------------------------------------
  let camera = null;
  if (zg) {
    let d = zg.value, sigma = zg.sigma;
    if (za) {
      const bg = Math.atan2(g.cx || 0, f), ba = Math.atan2(a.cx || 0, f);
      const cosD = Math.cos(ba - bg);
      d = Math.sqrt(Math.max(0, zg.value ** 2 + za.value ** 2 - 2 * zg.value * za.value * cosD));
      const dZg = d > 0 ? (zg.value - za.value * cosD) / d : 1;
      const dZa = d > 0 ? (za.value - zg.value * cosD) / d : 1;
      sigma = Math.hypot(dZg * zg.sigma, dZa * za.sigma);
    }
    // The lens, once, on the whole camera answer.
    sigma = Math.hypot(sigma, d * fRel);
    camera = { value: d, sigma };
    factors.push(factor('camera', d, sigma, true, za ? 'goal and shooter, by triangle' : 'goal only; shooter not sized'));
  }

  // --- agree or not ---------------------------------------------------------
  let out, source, note = '', focalHint = null;
  if (camera && typed) {
    const gap = Math.abs(camera.value - typed.value);
    const together = Math.hypot(camera.sigma, typed.sigma);
    if (gap > DISAGREE_SIGMAS * together) {
      // Never let a mis-seen goal overrule a kid who paced it out; say so.
      out = typed; source = 'set';
      factors.find((x) => x.name === 'camera').used = false;
      note = `The camera makes it ${round2(camera.value * YD_PER_M).toFixed(1)} yards, not `
        + `${round2(typed.value * YD_PER_M).toFixed(1)}. Check the spot, or that the whole goal is in view.`;
    } else {
      out = fuse([camera, typed]); source = 'camera+set';
      // Every camera factor scales with f, so the lens that would have made
      // the camera agree exactly with the pace is f times their ratio. Worth
      // remembering only while the two are within reason of each other.
      focalHint = round2(f * typed.value / camera.value * 1000) / 1000;
      note = `Distance measured from the goal in view: about ${round2(out.value * YD_PER_M).toFixed(1)} yards`
        + ` (you set ${round2(typed.value * YD_PER_M).toFixed(1)}).`;
    }
  } else if (camera) {
    out = camera; source = 'camera';
    note = `Distance measured from the goal in view: about ${round2(camera.value * YD_PER_M).toFixed(1)} yards.`;
  } else if (typed) {
    out = typed; source = 'set';
    note = g && g.of ? 'The goal was not in view, so the distance is the one you set.' : '';
  } else {
    return { distance_m: null, plus_minus_m: null, source: 'none', factors, note: '', focal_hint: null };
  }
  return {
    distance_m: out.value, plus_minus_m: out.sigma, source, factors, note,
    focal_hint: focalHint, focal_learned: learned,
  };
}

export function toYards(m) { return m === null ? null : round2(m * YD_PER_M); }
