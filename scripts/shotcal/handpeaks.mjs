// Top-hand speed from extracted landmarks: a throw is the fastest thing the
// hands do in a cycle. Prints speed peaks (frame heights / s) above a floor,
// at least 0.9 s apart. Bench truth for clips where the net is hidden.
// node scripts/shotcal/handpeaks.mjs <landmarks.json> [floor]
import { readFileSync } from 'node:fs';
const frames = JSON.parse(readFileSync(process.argv[2], 'utf8')).filter((f) => f.landmarks);
const floor = Number(process.argv[3] || 2.5);
const pts = frames.map((f) => {
  const l = f.landmarks;
  // both wrists, take whichever moves faster that frame
  return { t: f.t_ms, L: [l[15].x, l[15].y], R: [l[16].x, l[16].y] };
});
const sp = [];
for (let i = 1; i < pts.length; i += 1) {
  const dt = (pts[i].t - pts[i - 1].t) / 1000;
  if (dt <= 0 || dt > 0.2) continue;
  const v = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]) / dt;
  sp.push({ t: pts[i].t, v: Math.max(v(pts[i].L, pts[i - 1].L), v(pts[i].R, pts[i - 1].R)) });
}
// 3-frame smooth
const sm = sp.map((s, i) => ({ t: s.t, v: (sp[Math.max(0, i - 1)].v + s.v + sp[Math.min(sp.length - 1, i + 1)].v) / 3 }));
const peaks = [];
for (let i = 1; i < sm.length - 1; i += 1) {
  if (sm[i].v >= floor && sm[i].v >= sm[i - 1].v && sm[i].v >= sm[i + 1].v) {
    const last = peaks[peaks.length - 1];
    if (last && sm[i].t - last.t < 900) { if (sm[i].v > last.v) peaks[peaks.length - 1] = sm[i]; }
    else peaks.push(sm[i]);
  }
}
console.log(`hand-speed peaks >= ${floor}: ` + peaks.map((p) => `${(p.t / 1000).toFixed(2)}(${p.v.toFixed(1)})`).join(' '));
console.log('count:', peaks.length);
