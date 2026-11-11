// Roster table on a 360px phone: can a coach read every player's status and
// reach "Email parent" without scrolling the table sideways? Exits 1 if not.
//   node scripts/ui/walk-roster-phone.mjs <base> <outdir>
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const post = async (path, body, token) => (await fetch(`${base}${path}`, { method: 'POST',
  headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  body: JSON.stringify(body) })).json();
const made = await post('/api/orgs', { name: 'Roster Phone Check', sport: 'lacrosse', accept_terms: true, director_name: 'Pat Lee' });
const tok = made.director.token;
const team = await post('/api/teams', { name: '2031 Red' }, tok);
for (const [name, jersey] of [['Alexandria Montgomery-Whitfield', '22'], ['Sam Ortiz', '7'], ['Jo Park', '']]) {
  await post('/api/athletes', { display_name: name, birth_year: 2013, jersey, join_code: team.join_code }, tok);
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
  await page.waitForSelector('#roster [data-invite]', { timeout: 8000 });
  await page.waitForTimeout(400);
  await page.locator('#roster-card table').scrollIntoViewIfNeeded();
  const r = await page.evaluate((vw) => {
    const box = document.querySelector('#roster-card table').parentElement.getBoundingClientRect();
    const right = Math.min(vw, box.right);
    const vis = (el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.left >= box.left - 1 && b.right <= right + 1; };
    const table = document.querySelector('#roster-card table').getBoundingClientRect();
    const rows = [...document.querySelectorAll('#roster tr')];
    const status = rows.map((tr) => tr.lastElementChild);
    const invites = [...document.querySelectorAll('#roster [data-invite]')];
    const aligns = rows[0] ? [...rows[0].children].map((td) => getComputedStyle(td).textAlign) : [];
    return { table: Math.round(table.width), box: Math.round(box.width), aligns, n: rows.length,
      status: status.map(vis), invites: invites.map(vis) };
  }, width);
  console.log(`${width}px table ${r.table}px in a ${r.box}px box | ${r.n} players | status on screen: ${r.status.join(',')} | Email parent on screen: ${r.invites.join(',')}`);
  if (r.n !== 3) { console.log(`FAIL ${width}px: expected 3 players, saw ${r.n}`); bad++; }
  if (r.table > r.box + 1) { console.log(`FAIL ${width}px: the table is wider than its box and scrolls sideways`); bad++; }
  if (width < 560 && r.aligns.some((a) => a === 'right')) { console.log(`FAIL ${width}px: a stacked value is pushed to the right, away from its label`); bad++; }
  if (r.status.some((v) => !v)) { console.log(`FAIL ${width}px: a player's status is off screen`); bad++; }
  if (r.invites.some((v) => !v)) { console.log(`FAIL ${width}px: an Email parent button is off screen`); bad++; }
  await page.locator('#roster-card').screenshot({ path: `${out}/roster-${width}.png` });
  await ctx.close();
}
await browser.close();
console.log(bad ? `FAILED ${bad}` : 'OK');
process.exit(bad ? 1 : 0);
