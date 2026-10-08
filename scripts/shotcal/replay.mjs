/**
 * Replay an extracted clip through the production shot-speed counters.
 *
 * `extract.py` turned a clip into the frames and samples the phone would have
 * seen and heard. This pushes them through RepCounter -> SoundRepCounter ->
 * ShotSpeedCounter -- the same three objects `capture.html` builds for the
 * shooting drill, with no bench-only shortcuts -- and writes what came out:
 * one row per heard shot with its impact time, the release it was paired with
 * and the speed the app would have shown.
 *
 *   node scripts/shotcal/replay.mjs --specs specs.json --in data/shotcal/extracted \
 *        --distance 8 [--out data/shotcal/replayed.json] [--params '{"RELEASE_MIN_HAND_SPEED":2}']
 *
 * `--params` overrides the release detector's thresholds (minHeight,
 * minHandSpeed, minGapMs -- the ReleaseDetector constructor options) for a
 * run, so `fit.py` can sweep them against the truth set without editing the
 * product. The maths (sound travel, mph) is pinned by tests on both sides and
 * is not a tuning knob.
 *
 * Also exposes the raw timelines (every onset heard, every release seen, and
 * the stick-hand trace) so a shot the pairing missed can be diagnosed rather
 * than guessed at.
 */
import { readFileSync, readdirSync, writeFileSync, existsSync } from 'node:fs';
import { join, basename } from 'node:path';
import { RepCounter } from '../../offdays/web/static/counter.js';
import { SoundRepCounter } from '../../offdays/web/static/sound.js';
import * as SS from '../../offdays/web/static/shotspeed.js';

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : fallback;
}

const specsPath = arg('specs');
const inDir = arg('in', 'data/shotcal/extracted');
const outPath = arg('out', 'data/shotcal/replayed.json');
const distanceYd = Number(arg('distance', '8'));
const drillKey = arg('drill', 'lax_shooting');
const params = JSON.parse(arg('params', '{}'));
const only = arg('clip', null);
if (!specsPath) throw new Error('--specs <drill specs json> is required (see README: export drill specs)');

const specs = JSON.parse(readFileSync(specsPath, 'utf8'));
const drill = (Array.isArray(specs) ? specs : specs.drills).find((d) => d.key === drillKey);
if (!drill) throw new Error(`no drill ${drillKey} in ${specsPath}`);
if (!drill.shot) throw new Error(`${drillKey} has no ShotSpec; nothing to time`);

// Release-detector overrides for a sweep. Keys are the ReleaseDetector
// constructor options: minHeight, minHandSpeed, minGapMs.
const RELEASE_KEYS = new Set(['minHeight', 'minHandSpeed', 'minGapMs']);
for (const k of Object.keys(params)) {
  if (!RELEASE_KEYS.has(k)) throw new Error(`--params: unknown key ${k}; allowed ${[...RELEASE_KEYS].join(', ')}`);
}
const applied = params;

const metas = readdirSync(inDir).filter((f) => f.endsWith('.meta.json'));
const out = { drill: drillKey, distance_yd: distanceYd, params: applied, clips: [] };

for (const metaFile of metas) {
  const stem = metaFile.replace(/\.meta\.json$/, '');
  if (only && stem !== only) continue;
  const meta = JSON.parse(readFileSync(join(inDir, metaFile), 'utf8'));
  const frames = JSON.parse(readFileSync(join(inDir, `${stem}.landmarks.json`), 'utf8'));
  const audioPath = join(inDir, `${stem}.audio.f32`);
  const hasAudio = existsSync(audioPath) && meta.samples > 0;

  const pose = new RepCounter(drill);
  const sound = new SoundRepCounter(drill, pose, { sampleRate: meta.sample_rate || 48000 });
  const counter = new SS.ShotSpeedCounter(drill, sound, { distanceYd, release: params });

  // Interleave audio and video on one clock, the way the phone delivers them:
  // audio in 128-sample blocks, a pose frame whenever the clock passes one.
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
        if (f.landmarks) counter.pushPose(f.landmarks, f.t_ms);
      }
      counter.pushAudio(samples.subarray(i, i + block), tMs);
    }
    while (fi < frames.length) {
      const f = frames[fi++];
      if (f.landmarks) counter.pushPose(f.landmarks, f.t_ms);
    }
  } else {
    for (const f of frames) if (f.landmarks) counter.pushPose(f.landmarks, f.t_ms);
  }
  counter.releases.finish();
  counter.listener.finish();

  const shots = counter.shots.map((s, i) => ({
    shot_no: i + 1,
    impact_ms: Math.round(s.impact_ms),
    release_ms: s.release_ms === null ? null : Math.round(s.release_ms),
    flight_ms: s.release_ms === null ? null : Math.round(s.impact_ms - s.release_ms),
    mph: s.mph,
    via: s.via,
    hand: counter.reps[i] ? counter.reps[i].hand : 'none',
  }));

  out.clips.push({
    clip: meta.clip || stem,
    stem,
    frames: frames.length,
    frames_with_pose: frames.filter((f) => f.landmarks).length,
    has_audio: hasAudio,
    sounds_heard: sound.detector.onsets.length,
    swings_ms: counter.listener.swings.map((s) => s.t_ms),
    impacts_ms: counter.listener.impacts.map((i) => i.t_ms),
    onsets_ms: sound.detector.onsets.map((o) => Math.round(o.t_ms)),
    onset_strengths: sound.detector.onsets.map((o) => Math.round(o.strength * 10) / 10),
    releases_ms: counter.releases.releases.map((r) => r.t_ms),
    period_ms: sound.grouping.periodMs,
    shots,
  });
  const timed = shots.filter((s) => s.mph !== null);
  console.log(`${stem}: ${shots.length} shots heard (${sound.detector.onsets.length} sounds), `
    + `${counter.releases.releases.length} releases seen, ${timed.length} timed`
    + (timed.length ? `, mph ${timed.map((s) => s.mph).join(' ')}` : ''));
}

writeFileSync(outPath, JSON.stringify(out, null, 1));
console.log(`wrote ${outPath}`);
