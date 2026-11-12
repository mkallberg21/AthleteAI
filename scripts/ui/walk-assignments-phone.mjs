// Assignments card on a phone: can a coach see, for every player, sessions,
// reps, off-hand and whether the targets are met, without scrolling sideways?
// Exits 1 if not.
//   node scripts/ui/walk-assignments-phone.mjs <base> <outdir>
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
const made = await post('/api/orgs', { name: 'Assignments Phone Check', sport: 'lacrosse', accept_terms: true, director_name: 'Pat Lee' });
const tok = made.director.token;
const team = await post('/api/teams', { name: '2031 Red' }, tok);
for (const name of ['Bo Short', 'Alexandra Montgomery-Smith', 'Kai Ito']) {
  await post('/api/athletes', { display_name: name, birth_year: 2013, join_code: team.join_code }, tok);
}
const today = new Date().toISOString().slice(0, 10);
const due = new Date(Date.now() + 6 * 864e5).toISOString().slice(0, 10);
await post('/api/coach/assignments', { team_id: team.id, drill_key: 'lax_wall_ball_offhand', title: 'Week 1 Wall Ball',
  starts_on: today, due_on: due, target_reps: 300, target_sessions: 3, min_offhand: 0.4 }, tok);

const browser = await chromium.launch();
let bad = 0;
for (const width of [360, 390, 1280]) {
  const ctx = await browser.newContext({ viewport: { width, height: 800 }, deviceScaleFactor: 2, isMobile: width < 900, hasTouch: width < 900 });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => { console.log('PAGEERROR', e.message); bad++; });
  await page.goto(`${base}/app/index.html?code=${tok}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);
  await page.locator('#wizard-skip').click({ timeout: 1500 }).catch(() => {});
  await page.click('#tabbar [data-tab="today"]'); await page.waitForTimeout(400);   // the dashboard opens on Home
  await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));
  await page.waitForSelector('#assignments table.compliance tbody tr', { timeout: 8000 });
  await page.waitForTimeout(400);
  const card = page.locator('#assignments');
  await card.scrollIntoViewIfNeeded();
  const r = await page.evaluate((vw) => {
    const table = document.querySelector('#assignments table.compliance');
    const box = document.querySelector('#assignments > div').getBoundingClientRect();
    const right = Math.min(vw, box.right);
    const rows = [...table.querySelectorAll('tbody tr')];
    const cells = rows.flatMap((tr) => [...tr.children]);
    const vis = (el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.left >= box.left - 1 && b.right <= right + 1; };
    // A number on a phone with no header above it is a number nobody can read.
    const labelled = cells.slice(0).filter((td, i) => i % 5 !== 0).every((td) => {
      if (getComputedStyle(table.querySelector('thead')).display !== 'none') return true;
      return (getComputedStyle(td, '::before').content || '').replace(/"/g, '').trim().length > 0;
    });
    return { table: Math.round(table.getBoundingClientRect().width), box: Math.round(box.width), n: rows.length,
      vis: cells.map(vis), labelled, widths: cells.map((c) => Math.round(c.getBoundingClientRect().width)) };
  }, width);
  console.log(`${width}px table ${r.table}px in a ${r.box}px box | ${r.n} players | on screen ${r.vis.filter(Boolean).length}/${r.vis.length} | cell widths ${r.widths.join(',')}`);
  if (r.n !== 3) { console.log(`FAIL ${width}px: expected 3 players, saw ${r.n}`); bad++; }
  if (r.table > r.box + 1) { console.log(`FAIL ${width}px: the table is wider than its card and scrolls sideways`); bad++; }
  if (r.vis.some((v) => !v)) { console.log(`FAIL ${width}px: something is off screen`); bad++; }
  if (!r.labelled) { console.log(`FAIL ${width}px: a number has no label`); bad++; }
  await card.screenshot({ path: `${out}/assignments-phone-${width}.png` });
  await ctx.close();
}
await browser.close();
console.log(bad ? `FAILED ${bad}` : 'OK');
process.exit(bad ? 1 : 0);
