// Ball skill work card on a phone: can a coach see, for every player,
// touches, sessions, how well the phone sees the ball and which drills,
// without scrolling sideways? Exits 1 if not.
//   node scripts/ui/walk-ball-phone.mjs <base> <outdir>
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const post = async (path, body, token) => {
  const r = await fetch(`${base}${path}`, { method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
    body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) throw new Error(`${path} ${r.status} ${JSON.stringify(j)}`);
  return j;
};
const made = await post('/api/orgs', { name: 'Ball Phone Check', sport: 'soccer', director_name: 'Pat Lee' });
const tok = made.director.token;
const team = await post('/api/teams', { name: 'U13 Blue' }, tok);
const quality = { 'Bo Short': 0.62, 'Alexandra Montgomery-Smith': 0.1, 'Kai Ito': 0.5 };
for (const [name, q] of Object.entries(quality)) {
  const a = await post('/api/athletes', { display_name: name, birth_year: 2013, join_code: team.join_code }, tok);
  for (let s = 0; s < 2; s++) {
    const st = await post('/api/sessions/start', { drill_key: 'soc_juggle' }, a.token);
    const reps = Array.from({ length: 30 }, (_, i) => ({ t_ms: i * 900 + (i % 3) * 70,
      hand: i % 3 ? 'left' : 'right', confidence: q, speed: 1.2, part: 'left_ankle' }));
    await post('/api/sessions/submit', { session_id: st.session_id, nonce: st.nonce, duration_ms: 28000,
      reps, mean_confidence: q, track_quality: q }, a.token);
  }
}

const browser = await chromium.launch();
let bad = 0;
for (const width of [360, 390, 1280]) {
  const ctx = await browser.newContext({ viewport: { width, height: 800 }, deviceScaleFactor: 2, isMobile: width < 900, hasTouch: width < 900 });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => { console.log('PAGEERROR', e.message); bad++; });
  await page.goto(`${base}/app/index.html?code=${tok}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);
  await page.locator('#wizard-skip').click({ timeout: 1500 }).catch(() => {});
  await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));
  await page.waitForSelector('#ball-athletes table tbody tr', { timeout: 8000 });
  await page.waitForTimeout(400);
  const card = page.locator('#ball-card');
  await card.scrollIntoViewIfNeeded();
  const r = await page.evaluate((vw) => {
    const table = document.querySelector('#ball-athletes table');
    const box = document.querySelector('#ball-athletes').getBoundingClientRect();
    const right = Math.min(vw, box.right);
    const rows = [...table.querySelectorAll('tbody tr')];
    const cells = rows.flatMap((tr) => [...tr.children]);
    const vis = (el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.left >= box.left - 1 && b.right <= right + 1; };
    const headless = getComputedStyle(table.querySelector('thead')).display === 'none';
    // A number on a phone with no header above it is a number nobody can read.
    const labelled = !headless || cells.filter((td, i) => i % 5 !== 0).every((td) =>
      (getComputedStyle(td, '::before').content || '').replace(/"/g, '').trim().length > 0);
    return { table: Math.round(table.getBoundingClientRect().width), box: Math.round(box.width), n: rows.length,
      vis: cells.map(vis), labelled, headless };
  }, width);
  console.log(`${width}px table ${r.table}px in a ${r.box}px box | ${r.n} players | on screen ${r.vis.filter(Boolean).length}/${r.vis.length} | header ${r.headless ? 'hidden' : 'shown'}`);
  if (r.n !== 3) { console.log(`FAIL ${width}px: expected 3 players, saw ${r.n}`); bad++; }
  if (r.table > r.box + 1) { console.log(`FAIL ${width}px: the table is wider than its card and scrolls sideways`); bad++; }
  if (r.vis.some((v) => !v)) { console.log(`FAIL ${width}px: something is off screen`); bad++; }
  if (!r.labelled) { console.log(`FAIL ${width}px: a number has no label`); bad++; }
  if (width >= 900 && r.headless) { console.log(`FAIL ${width}px: the laptop table lost its header`); bad++; }
  await card.screenshot({ path: `${out}/ball-phone-${width}.png` });
  await ctx.close();
}
await browser.close();
console.log(bad ? `FAILED ${bad}` : 'OK');
process.exit(bad ? 1 : 0);
