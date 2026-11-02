// Torso scale over time from extracted landmarks: shoulder-hip span as a
// fraction of frame height. A kid walking to the phone grows in frame fast.
// node scripts/shotcal/bodyscale.mjs data/wallcal/extracted/IMG_5062.landmarks.json
import { readFileSync } from 'node:fs';
const frames = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const span = (l) => {
  const sh = (l[11].y + l[12].y) / 2, hp = (l[23].y + l[24].y) / 2;
  return Math.abs(hp - sh);
};
const sec = new Map();
for (const f of frames) {
  if (!f.landmarks) continue;
  const s = Math.floor(f.t_ms / 1000);
  if (!sec.has(s)) sec.set(s, []);
  sec.get(s).push(span(f.landmarks));
}
const rows = [...sec.entries()].map(([s, v]) => [s, v.sort((a, b) => a - b)[Math.floor(v.length / 2)]]);
const base = rows.slice(2, 10).map((r) => r[1]).sort((a, b) => a - b)[3];
console.log(rows.map(([s, v]) => `${s}s:${(v / base).toFixed(2)}`).join(' '));
