// Teams table on a 360px phone: can the director see the join code and the
// Remove button without hunting sideways? Exits 1 if either is off screen.
//   node scripts/ui/walk-teams-phone.mjs <base> <outdir>
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const post = async (path, body, token) => (await fetch(`${base}${path}`, { method: 'POST',
  headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  body: JSON.stringify(body) })).json();
const made = await post('/api/orgs', { name: 'Teams Phone Check', sport: 'lacrosse', accept_terms: true, director_name: 'Pat Lee' });
const tok = made.director.token;
await post('/api/teams', { name: '2031 Red', coach_name: 'Sam Hill', coach_email: 'sam@example.com' }, tok);
await post('/api/teams', { name: 'U9 Blue' }, tok);
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
  await page.waitForSelector('#teams tr', { timeout: 8000 });
  await page.waitForTimeout(400);
  await page.locator('#teams-card table').scrollIntoViewIfNeeded();
  const r = await page.evaluate((vw) => {
    const box = document.querySelector('#teams-card table').parentElement.getBoundingClientRect();
    const right = Math.min(vw, box.right);
    const vis = (el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.left >= box.left - 1 && b.right <= right + 1; };
    const table = document.querySelector('#teams-card table').getBoundingClientRect();
    const codes = [...document.querySelectorAll('#teams tr')].map((tr) => tr.lastElementChild);
    const removes = [...document.querySelectorAll('#teams [data-del-team]')];
    const firstRow = document.querySelector('#teams tr');
    const aligns = firstRow ? [...firstRow.children].map((td) => getComputedStyle(td).textAlign) : [];
    return { table: Math.round(table.width), box: Math.round(box.width), aligns,
      codes: codes.map(vis), removes: removes.map(vis), nRemove: removes.length };
  }, width);
  console.log(`${width}px table ${r.table}px in a ${r.box}px box | join code on screen: ${r.codes.join(',')} | Remove buttons ${r.nRemove} on screen: ${r.removes.join(',')}`);
  if (width < 560 && r.aligns.some((a) => a === 'right')) { console.log(`FAIL ${width}px: a stacked value is pushed to the right, away from its label`); bad++; }
  if (r.codes.some((v) => !v)) { console.log(`FAIL ${width}px: a join code is off screen`); bad++; }
  if (!r.nRemove) { console.log(`FAIL ${width}px: no Remove button for the empty team`); bad++; }
  if (r.removes.some((v) => !v)) { console.log(`FAIL ${width}px: a Remove button is off screen`); bad++; }
  await page.locator('#teams-card').screenshot({ path: `${out}/teams-${width}.png` });
  await ctx.close();
}
await browser.close();
console.log(bad ? `FAILED ${bad}` : 'OK');
process.exit(bad ? 1 : 0);
