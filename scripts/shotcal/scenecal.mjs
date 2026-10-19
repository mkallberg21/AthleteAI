/**
 * The product's distance estimate, run on a clip.
 *
 * Feeds a clip's frames (at the work size the phone uses) and its extracted
 * landmarks through the PRODUCTION scene watcher (scene.js) and the
 * production estimate (distance.js), exactly as capture.html does, and prints
 * every factor next to the tape. The one input the phone has that a clip does
 * not is the tilt; pass --pitch to supply it.
 *
 *   node scripts/shotcal/scenecal.mjs data/shotcal/clips/*.mov [--pitch 5] [--focal 1.17] [--age 13]
 */
import { spawnSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { basename, join } from 'node:path';
import { SceneWatcher } from '../../offdays/web/static/scene.js';
import { estimateDistance, YD_PER_M } from '../../offdays/web/static/distance.js';
import { workSize } from '../../offdays/web/static/ballvision.js';

const args = process.argv.slice(2);
const opt = (name, fallback) => { const i = args.indexOf(`--${name}`); return i >= 0 ? args[i + 1] : fallback; };
const clips = args.filter((a, i) => !a.startsWith('--') && (i === 0 || !args[i - 1].startsWith('--')));
const pitch = opt('pitch', null) === null ? null : Number(opt('pitch'));
const focal = opt('focal', null) === null ? null : Number(opt('focal'));
const age = Number(opt('age', '13'));
const inDir = opt('in', 'data/shotcal/extracted');
const truthPath = opt('truth', 'data/shotcal/truth.csv');

const truth = {};
if (existsSync(truthPath)) {
  for (const line of readFileSync(truthPath, 'utf8').split(/\r?\n/).slice(1)) {
    const [clip, , , dist] = line.split(',');
    if (clip && dist) truth[clip.replace(/\.[^.]+$/, '')] = Number(dist);
  }
}

console.log(`${'clip'.padEnd(10)}${'tape'.padStart(6)}${'est'.padStart(7)}${'+-'.padStart(6)}  source       factors`);
for (const clip of clips) {
  const stem = basename(clip).replace(/\.[^.]+$/, '');
  const meta = JSON.parse(readFileSync(join(inDir, `${stem}.meta.json`), 'utf8'));
  const frames = JSON.parse(readFileSync(join(inDir, `${stem}.landmarks.json`), 'utf8'));
  const fps = meta.fps || 30;
  // meta.width is the EXTRACTION width and meta.height the SOURCE height,
  // so the aspect has to come from the clip itself.
  const probe = spawnSync('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
    '-of', 'csv=p=0', clip], { encoding: 'utf8' });
  const [srcW, srcH] = probe.stdout.trim().split(',').map(Number);
  const videoW = 1280, videoH = Math.round(srcH * videoW / srcW);
  const size = workSize(videoW, videoH);
  const proc = spawnSync('ffmpeg', ['-v', 'error', '-i', clip, '-vf', `fps=${fps},scale=${size.width}:${size.height}`,
    '-pix_fmt', 'rgba', '-f', 'rawvideo', '-'], { maxBuffer: 1 << 30 });
  if (proc.status !== 0) { console.log(`${stem}: ffmpeg failed`); continue; }
  const raw = proc.stdout, frameBytes = size.width * size.height * 4;
  const n = Math.floor(raw.length / frameBytes);
  const w = new SceneWatcher({ typedYd: truth[stem] ?? null, focal });
  w.setFrame(videoW, videoH);
  for (let i = 0; i < n; i += 1) {
    const t = Math.round(i * 1000 / fps);
    const data = new Uint8ClampedArray(raw.buffer, raw.byteOffset + i * frameBytes, frameBytes);
    w.pushImage({ data, width: size.width, height: size.height }, t);
    w.pushPose(frames[i] && frames[i].landmarks);
  }
  if (pitch !== null) w.pushPitch(pitch);
  const s = w.scene();
  const r = estimateDistance(s, { age });
  const f = r.factors.map((x) => `${x.name}=${x.yd === null ? '-' : x.yd.toFixed(1)}${x.used ? '' : '!'}`).join(' ');
  console.log(`${stem.padEnd(10)}${String(truth[stem] ?? '-').padStart(6)}${(r.distance_m === null ? '-' : (r.distance_m * YD_PER_M).toFixed(2)).padStart(7)}`
    + `${(r.plus_minus_m === null ? '-' : (r.plus_minus_m * YD_PER_M).toFixed(2)).padStart(6)}  ${r.source.padEnd(12)} ${f}`
    + `   goal seen ${s.goal ? `${s.goal.seen}/${s.goal.of}` : '-'}`);
}
