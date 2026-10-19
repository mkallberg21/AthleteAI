/**
 * Does the camera see the ball leave?
 *
 * Runs the PRODUCTION ball detector (ballvision.js, the one the capture
 * screen runs every frame on a lacrosse drill) over a clip at the size the
 * phone works at, and prints where it saw the ball frame by frame around each
 * heard release. The question it answers is whether a visual "ball departed"
 * signal is available to cross-check a heard swing against -- which is the
 * gate on building that cross-check at all. If the detector does not see the
 * ball in the frames after the swing, there is nothing to build on.
 *
 *   node scripts/shotcal/ballsee.mjs --clip data/shotcal/clips/IMG_1634.mov \
 *        [--in data/shotcal/extracted] [--replayed data/shotcal/work/replay_10yd.json] \
 *        [--window 400] [--colour white]
 *
 * Needs ffmpeg on PATH. Frames come out at the same 30 fps the landmarks were
 * extracted at, scaled to `workSize` of the 1280-wide frame the phone asks
 * for, so the ball is the same number of pixels it would be in the product.
 */
import { spawnSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { basename, join } from 'node:path';
import {
  BallVision, PRESETS, radiusFromPose, workSize, ScaleMemory,
} from '../../offdays/web/static/ballvision.js';
import { BallTracker, LANDMARK_INDEX } from '../../offdays/web/static/ball.js';

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : fallback;
}

const clip = arg('clip');
if (!clip) throw new Error('--clip <video> is required');
const inDir = arg('in', 'data/shotcal/extracted');
const replayed = arg('replayed', 'data/shotcal/work/replay_10yd.json');
const windowMs = Number(arg('window', '400'));
const colours = arg('colour', 'white,yellow,lime').split(',');
const stem = basename(clip).replace(/\.[^.]+$/, '');

const meta = JSON.parse(readFileSync(join(inDir, `${stem}.meta.json`), 'utf8'));
const frames = JSON.parse(readFileSync(join(inDir, `${stem}.landmarks.json`), 'utf8'));
const fps = meta.fps || 30;
// The phone asks for 1280 wide; extraction scaled to that, and the work frame
// is what the detector gets from it.
// meta.width is the EXTRACTION width and meta.height the SOURCE height, so
// the aspect comes from the clip itself.
const probe = spawnSync('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
  '-of', 'csv=p=0', clip], { encoding: 'utf8' });
const [srcW, srcH] = probe.stdout.trim().split(',').map(Number);
const videoW = 1280;
const videoH = Math.round(srcH * videoW / srcW);
const size = workSize(videoW, videoH);
const aspect = videoW / videoH;

const proc = spawnSync('ffmpeg', [
  '-v', 'error', '-i', clip, '-vf', `fps=${fps},scale=${size.width}:${size.height}`,
  '-pix_fmt', 'rgba', '-f', 'rawvideo', '-',
], { maxBuffer: 1 << 30 });
if (proc.status !== 0) throw new Error(`ffmpeg failed: ${proc.stderr}`);
const raw = proc.stdout;
const frameBytes = size.width * size.height * 4;
const nFrames = Math.floor(raw.length / frameBytes);

let releases = [];
if (existsSync(replayed)) {
  const r = JSON.parse(readFileSync(replayed, 'utf8'));
  const c = r.clips.find((x) => x.stem === stem);
  if (c) releases = c.shots.map((s) => ({ release_ms: s.release_ms, impact_ms: s.impact_ms }));
}

const vision = new BallVision({ profiles: colours.map((n) => PRESETS[n]).filter(Boolean) });
const tracker = new BallTracker();
tracker.aspect = aspect;
const scale = new ScaleMemory();

const seen = [];
for (let i = 0; i < nFrames; i += 1) {
  const tMs = Math.round(i * 1000 / fps);
  const data = new Uint8ClampedArray(raw.buffer, raw.byteOffset + i * frameBytes, frameBytes);
  const image = { data, width: size.width, height: size.height };
  const lm = frames[i] && frames[i].landmarks;
  const measured = radiusFromPose(lm, LANDMARK_INDEX, 6.35, aspect);
  const expectedRadius = scale.update(measured, tMs);
  const near = tracker.visible ? { x: tracker.x, y: tracker.y } : null;
  const det = vision.detect(image, { expectedRadius, near });
  const ball = tracker.push(det, tMs);
  seen.push({ tMs, det, ball, expectedRadius });
}

const detected = seen.filter((s) => s.det).length;
const withScale = seen.filter((s) => s.expectedRadius).length;
const tooSmall = seen.filter((s) => s.expectedRadius && vision.tooSmall(s.expectedRadius, size.height)).length;
console.log(`size prior known in ${withScale} frames; ball under the resolvable radius in ${tooSmall} of them`
  + (withScale ? ` (median expected radius ${(seen.filter((s) => s.expectedRadius).map((s) => s.expectedRadius * size.height).sort((a, b) => a - b)[Math.floor(withScale / 2)]).toFixed(1)} px)` : ''));
console.log(`${stem}: ${nFrames} frames at ${size.width}x${size.height}; ball detected in `
  + `${detected} (${(100 * detected / nFrames).toFixed(0)}%); profile locked: `
  + `${vision.locked ? Object.keys(PRESETS).find((k) => PRESETS[k] === vision.profile) : 'no'}`);

const show = (s) => {
  const d = s.det ? `det x=${s.det.x.toFixed(3)} y=${s.det.y.toFixed(3)} r=${(s.det.radius || 0).toFixed(3)}` : 'det -';
  const b = s.ball && typeof s.ball.x === 'number'
    ? `track x=${s.ball.x.toFixed(3)} y=${s.ball.y.toFixed(3)} v=${(s.ball.speed || 0).toFixed(2)}${s.ball.coasting ? ' coast' : ''}`
    : 'track -';
  return `${String(s.tMs).padStart(6)}  ${d.padEnd(34)} ${b}  exp_r=${s.expectedRadius ? s.expectedRadius.toFixed(3) : '-'}`;
};

if (!releases.length) {
  console.log('no heard releases for this clip in the replay; showing every detection');
  for (const s of seen) if (s.det) console.log(show(s));
} else {
  for (const r of releases) {
    console.log(`\nrelease heard at ${r.release_ms} ms, impact at ${r.impact_ms} ms`);
    for (const s of seen) {
      if (s.tMs >= r.release_ms - windowMs / 2 && s.tMs <= r.release_ms + windowMs) {
        const mark = s.tMs >= r.release_ms && s.tMs < r.release_ms + 1000 / fps ? ' <- release' : '';
        console.log(show(s) + mark);
      }
    }
  }
}
