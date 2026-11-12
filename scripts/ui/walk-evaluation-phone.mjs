// Evaluation export on a phone: after "Show", can a director read every
// player's Weeks trained, Participation, Form and Trend without scrolling the
// table sideways? Exits 1 if not.
//   node scripts/ui/walk-evaluation-phone.mjs <base> <outdir>
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const post = async (path, body, token) => (await fetch(`${base}${path}`, { method: 'POST',
  headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
  body: JSON.stringify(body) })).json();
const made = await post('/api/orgs', { name: 'Evaluation Phone Check', sport: 'lacrosse', accept_terms: true, director_name: 'Pat Lee' });
const tok = made.director.token;
const team = await post('/api/teams', { name: '2031 Red' }, tok);
for (const n of ['Bo Short', 'Alexandra Montgomery-Smith']) {
  await post('/api/athletes', { display_name: n, birth_year: 2013, join_code: team.join_code }, tok);
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
  await page.click('#tabbar [data-tab="teams"]'); await page.waitForTimeout(400);   // the dashboard opens on Home
  await page.click('#ev-build');
  await page.waitForSelector('#ev-out tbody tr', { timeout: 8000 });
  await page.waitForTimeout(400);
  const card = page.locator('#evaluation-card');
  await card.scrollIntoViewIfNeeded();
  const r = await page.evaluate((vw) => {
    const table = document.querySelector('#ev-out table');
    const box = table.parentElement.getBoundingClientRect();
    const right = Math.min(vw, box.right);
    const vis = (el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.left >= box.left - 1 && b.right <= right + 1; };
    const rows = [...table.querySelectorAll('tbody tr')];
    const cells = rows.flatMap((tr) => [...tr.children]);
    const head = getComputedStyle(table.querySelector('thead')).display;
    const labels = rows[0] ? [...rows[0].children].slice(1).map((td) => getComputedStyle(td, '::before').content) : [];
    const spill = cells.filter((td) => td.scrollWidth > td.clientWidth + 1).length;
    return { table: Math.round(table.getBoundingClientRect().width), box: Math.round(box.width), n: rows.length,
      vis: cells.map(vis), head, labels, spill };
  }, width);
  console.log(`${width}px table ${r.table}px in a ${r.box}px box | ${r.n} players | cells on screen: ${r.vis.filter(Boolean).length}/${r.vis.length} | labels ${r.labels.join(' ')}`);
  if (r.n !== 2) { console.log(`FAIL ${width}px: expected 2 players, saw ${r.n}`); bad++; }
  if (r.table > r.box + 1) { console.log(`FAIL ${width}px: the table is wider than its box and scrolls sideways`); bad++; }
  if (r.vis.some((v) => !v)) { console.log(`FAIL ${width}px: a value is off screen`); bad++; }
  if (width < 560 && r.labels.some((c) => !c || c === 'none' || c === 'normal')) { console.log(`FAIL ${width}px: a stacked value has no label`); bad++; }
  if (r.spill) { console.log(`FAIL ${width}px: ${r.spill} cell(s) spill into the next one`); bad++; }
  if (width >= 900 && r.head === 'none') { console.log(`FAIL ${width}px: the laptop table lost its header`); bad++; }
  await card.screenshot({ path: `${out}/evaluation-phone-${width}.png` });
  await ctx.close();
}
await browser.close();
console.log(bad ? `FAILED ${bad}` : 'OK');
process.exit(bad ? 1 : 0);
