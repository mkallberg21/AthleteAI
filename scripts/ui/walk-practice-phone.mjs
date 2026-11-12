// Before-practice card on a phone: can a coach read each flagged player's
// name, their Not training / Modified / Keep an eye label and what to do,
// without scrolling sideways or reading a word one letter per line?
// Exits 1 if not.
//   node scripts/ui/walk-practice-phone.mjs <base> <outdir>
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
const made = await post('/api/orgs', { name: 'Practice Phone Check', sport: 'lacrosse', accept_terms: true, director_name: 'Pat Lee' });
const tok = made.director.token;
const team = await post('/api/teams', { name: '2031 Red' }, tok);
const players = [
  ['Bo Short', { area: 'head', severity: 'sore' }],
  ['Alexandra Montgomery-Smith', { area: 'shoulder', severity: 'sore' }],
  ['Kai Ito', { area: 'wrist', severity: 'niggle' }],
];
for (const [name, report] of players) {
  const a = await post('/api/athletes', { display_name: name, birth_year: 2013, join_code: team.join_code }, tok);
  const at = a.token || (a.athlete && a.athlete.token);
  await post('/api/wellness/discomfort', report, at);
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
  await page.click('#tabbar [data-tab="today"]'); await page.waitForTimeout(400);   // the dashboard opens on Home
  await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));
  await page.waitForSelector('#practice-people tbody tr', { timeout: 8000 });
  await page.waitForTimeout(400);
  const card = page.locator('#practice-card');
  await card.scrollIntoViewIfNeeded();
  const r = await page.evaluate((vw) => {
    const table = document.querySelector('#practice-people table');
    const box = table.parentElement.getBoundingClientRect();
    const right = Math.min(vw, box.right);
    const rows = [...table.querySelectorAll('tbody tr')];
    const cells = rows.flatMap((tr) => [...tr.children]);
    const vis = (el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.left >= box.left - 1 && b.right <= right + 1; };
    // A name or instruction squeezed so narrow it reads a word or two a line.
    const cramped = rows.flatMap((tr) => [tr.children[0], tr.children[2]]).filter((td) => td && td.getBoundingClientRect().width < 90).length;
    const pills = rows.map((tr) => tr.querySelector('.pill')).filter(Boolean);
    const pillWrap = pills.filter((p) => p.getClientRects().length > 1 || p.getBoundingClientRect().height > 34).length;
    // What to do is the sentence the coach reads; on a phone it gets the row.
    const say = rows.map((tr) => tr.children[2]).filter(Boolean)
      .map((td) => td.getBoundingClientRect().width / box.width);
    return { table: Math.round(table.getBoundingClientRect().width), box: Math.round(box.width), n: rows.length,
      vis: cells.map(vis), cramped, pillWrap, say, widths: cells.map((c) => Math.round(c.getBoundingClientRect().width)) };
  }, width);
  console.log(`${width}px table ${r.table}px in a ${r.box}px box | ${r.n} players | on screen ${r.vis.filter(Boolean).length}/${r.vis.length} | cell widths ${r.widths.join(',')}`);
  if (r.n !== 3) { console.log(`FAIL ${width}px: expected 3 flagged players, saw ${r.n}`); bad++; }
  if (r.table > r.box + 1) { console.log(`FAIL ${width}px: the table is wider than its box and scrolls sideways`); bad++; }
  if (r.vis.some((v) => !v)) { console.log(`FAIL ${width}px: something is off screen`); bad++; }
  if (width < 560 && r.cramped) { console.log(`FAIL ${width}px: ${r.cramped} cell(s) squeezed under 90px wide`); bad++; }
  if (width < 560 && r.say.some((s) => s < 0.9)) { console.log(`FAIL ${width}px: what to do is squeezed into ${Math.round(Math.min(...r.say) * 100)}% of the card`); bad++; }
  if (r.pillWrap) { console.log(`FAIL ${width}px: ${r.pillWrap} label(s) break onto two lines`); bad++; }
  await card.screenshot({ path: `${out}/practice-phone-${width}.png` });
  await ctx.close();
}
await browser.close();
console.log(bad ? `FAILED ${bad}` : 'OK');
process.exit(bad ? 1 : 0);
