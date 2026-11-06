// Team standings on a 360px phone: can a director read every team's numbers
// without scrolling the table sideways? Exits 1 if not.
//   node scripts/ui/walk-standings-phone.mjs <base> <outdir>
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const post = async (path, body, token) => (await fetch(`${base}${path}`, { method: 'POST',
  headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  body: JSON.stringify(body) })).json();
const made = await post('/api/orgs', { name: 'Standings Phone Check', sport: 'lacrosse', director_name: 'Pat Lee' });
const tok = made.director.token;
for (const name of ['2031 Red', '2029 Navy Blue Academy Select']) {
  const team = await post('/api/teams', { name }, tok);
  await post('/api/athletes', { display_name: `Player ${name}`, birth_year: 2013, join_code: team.join_code }, tok);
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
  await page.waitForSelector('#standings tr td.rank', { timeout: 8000 });
  await page.waitForTimeout(400);
  const card = page.locator('#standings').locator('xpath=ancestor::div[contains(@class,"card")][1]');
  await card.scrollIntoViewIfNeeded();
  const r = await page.evaluate((vw) => {
    const table = document.querySelector('#standings').closest('table');
    const box = table.parentElement.getBoundingClientRect();
    const right = Math.min(vw, box.right);
    const vis = (el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.left >= box.left - 1 && b.right <= right + 1; };
    const rows = [...document.querySelectorAll('#standings tr')];
    const cells = rows.flatMap((tr) => [...tr.children]);
    const head = getComputedStyle(table.querySelector('thead')).display;
    const labels = rows[0] ? [...rows[0].children].slice(2).map((td) => getComputedStyle(td, '::before').content) : [];
    // A label wider than its cell runs into the next one ("PARTICIPATIONTOTAL XP").
    const spill = cells.filter((td) => td.scrollWidth > td.clientWidth + 1).length;
    return { table: Math.round(table.getBoundingClientRect().width), box: Math.round(box.width), n: rows.length,
      vis: cells.map(vis), head, labels, spill };
  }, width);
  console.log(`${width}px table ${r.table}px in a ${r.box}px box | ${r.n} teams | cells on screen: ${r.vis.filter(Boolean).length}/${r.vis.length} | labels ${r.labels.join(' ')}`);
  if (r.n !== 2) { console.log(`FAIL ${width}px: expected 2 teams, saw ${r.n}`); bad++; }
  if (r.table > r.box + 1) { console.log(`FAIL ${width}px: the table is wider than its box and scrolls sideways`); bad++; }
  if (r.vis.some((v) => !v)) { console.log(`FAIL ${width}px: a standings number is off screen`); bad++; }
  if (width < 560 && r.labels.some((c) => !c || c === 'none' || c === 'normal')) { console.log(`FAIL ${width}px: a stacked number has no label`); bad++; }
  if (r.spill) { console.log(`FAIL ${width}px: ${r.spill} cell(s) spill into the next one`); bad++; }
  if (width >= 900 && r.head === 'none') { console.log(`FAIL ${width}px: the laptop table lost its header`); bad++; }
  await card.screenshot({ path: `${out}/standings-${width}.png` });
  await ctx.close();
}
await browser.close();
console.log(bad ? `FAILED ${bad}` : 'OK');
process.exit(bad ? 1 : 0);
