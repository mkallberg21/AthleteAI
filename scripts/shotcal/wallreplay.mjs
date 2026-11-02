/**
 * Replay an extracted clip through the production WALL BALL counters.
 *
 * Same frames and samples `extract.py` produced, pushed through
 * RepCounter -> SoundRepCounter exactly as `capture.html` builds them for a
 * wall-ball drill (no ShotSpeedCounter: wall ball has no ShotSpec). Prints
 * what the app would have recorded -- pose count, heard count, per-hand
 * split, cycle period -- plus the raw onset and release timelines so a
 * miscount can be diagnosed rather than guessed at.
 *
 *   node scripts/shotcal/wallreplay.mjs --specs specs.json --in data/wallcal/extracted \
 *        [--drill lax_wall_ball_strong] [--clip IMG_5058] [--out data/wallcal/replayed.json]
 *
 * The ball tracker is not driven here: it reads pixels, which the extraction
 * does not keep (landmarks are footage of kids; pixels more so).
 */
import { readFileSync, readdirSync, writeFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { RepCounter } from '../../offdays/web/static/counter.js';
import { SoundRepCounter } from '../../offdays/web/static/sound.js';

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : fallback;
}

const specsPath = arg('specs');
const inDir = arg('in', 'data/wallcal/extracted');
const outPath = arg('out', 'data/wallcal/replayed.json');
const drillKey = arg('drill', 'lax_wall_ball_strong');
const only = arg('clip', null);
if (!specsPath) throw new Error('--specs <drill specs json> is required');

const specs = JSON.parse(readFileSync(specsPath, 'utf8'));
const drill = (Array.isArray(specs) ? specs : specs.drills).find((d) => d.key === drillKey);
if (!drill) throw new Error(`no drill ${drillKey} in ${specsPath}`);

const metas = readdirSync(inDir).filter((f) => f.endsWith('.meta.json'));
const out = { drill: drillKey, clips: [] };

for (const metaFile of metas) {
  const stem = metaFile.replace(/\.meta\.json$/, '');
  if (only && stem !== only) continue;
  const meta = JSON.parse(readFileSync(join(inDir, metaFile), 'utf8'));
  const frames = JSON.parse(readFileSync(join(inDir, `${stem}.landmarks.json`), 'utf8'));
  const audioPath = join(inDir, `${stem}.audio.f32`);
  const hasAudio = existsSync(audioPath) && meta.samples > 0;

  const pose = new RepCounter(drill);
  const sound = new SoundRepCounter(drill, pose, { sampleRate: meta.sample_rate || 48000 });

  if (hasAudio) {
    const buf = readFileSync(audioPath);
    const samples = new Float32Array(buf.buffer, buf.byteOffset, buf.byteLength / 4);
    const sr = meta.sample_rate || 48000;
    const block = 128;
    let fi = 0;
    for (let i = 0; i < samples.length; i += block) {
      const tMs = (i / sr) * 1000;
      while (fi < frames.length && frames[fi].t_ms <= tMs) {
        const f = frames[fi++];
        if (f.landmarks) sound.pushPose(f.landmarks, f.t_ms);
      }
      sound.pushAudio(samples.subarray(i, i + block), tMs);
    }
    while (fi < frames.length) {
      const f = frames[fi++];
      if (f.landmarks) sound.pushPose(f.landmarks, f.t_ms);
    }
  } else {
    for (const f of frames) if (f.landmarks) pose.push(f.landmarks, f.t_ms);
  }

  const reps = sound.reps.map((r, i) => ({
    rep_no: i + 1,
    t_ms: Math.round(r.t_ms),
    hand: r.hand,
    release_ms: r.release_ms === undefined ? null : Math.round(r.release_ms),
  }));
  const hands = sound.handCounts();
  const poseReps = pose.reps.map((r) => ({ t_ms: Math.round(r.t_ms), hand: r.hand }));
  const poseHands = { left: 0, right: 0 };
  for (const r of pose.reps) if (r.hand === 'left' || r.hand === 'right') poseHands[r.hand] += 1;

  out.clips.push({
    clip: meta.clip || stem,
    stem,
    duration_ms: Math.round(frames.length ? frames[frames.length - 1].t_ms : 0),
    frames: frames.length,
    frames_with_pose: frames.filter((f) => f.landmarks).length,
    has_audio: hasAudio,
    pose_count: pose.count,
    pose_hands: poseHands,
    pose_mean_confidence: Math.round(pose.meanConfidence * 1000) / 1000,
    sounds_heard: sound.detector.onsets.length,
    folded: sound.grouping.folded.length,
    period_ms: sound.grouping.periodMs,
    heard_count: sound.count,
    heard_hands: hands,
    catch_coverage: Math.round(sound.catchCoverage * 100) / 100,
    onsets_ms: sound.detector.onsets.map((o) => Math.round(o.t_ms)),
    onset_strengths: sound.detector.onsets.map((o) => Math.round(o.strength * 10) / 10),
    pose_reps: poseReps,
    reps,
    debug: sound.debug,
  });

  console.log(`${stem}: ${(frames.length / 30).toFixed(1)} s, pose in ${out.clips.at(-1).frames_with_pose}/${frames.length} frames`);
  console.log(`  pose counter : ${pose.count} reps (L ${poseHands.left} / R ${poseHands.right}), confidence ${out.clips.at(-1).pose_mean_confidence}`);
  console.log(`  sound counter: ${sound.count} reps (L ${hands.left} / R ${hands.right}) from ${sound.detector.onsets.length} sounds, `
    + `${sound.grouping.folded.length} folded, period ${sound.grouping.periodMs === null ? 'n/a' : Math.round(sound.grouping.periodMs) + ' ms'}, `
    + `catches heard ${Math.round(sound.catchCoverage * 100)}%`);
}

writeFileSync(outPath, JSON.stringify(out, null, 1));
console.log(`wrote ${outPath}`);
