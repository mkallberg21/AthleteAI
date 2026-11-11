// Evaluation card: does "Show" (All teams, the page default) put the squad on
// screen? It used to answer "Request failed (500)" for every director.
//   node scripts/ui/walk-evaluation.mjs <base> <outdir>
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const post = async (path, body, token) => (await fetch(`${base}${path}`, { method: 'POST',
  headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
  body: JSON.stringify(body) })).json();
const made = await post('/api/orgs', { name: 'Evaluation Check', sport: 'lacrosse', accept_terms: true, director_name: 'Pat Lee' });
const tok = made.director.token;
const team = await post('/api/teams', { name: '2031 Red' }, tok);
for (const n of ['Bo Short', 'Alexandra Montgomery-Smith']) {
  await post('/api/athletes', { display_name: n, birth_year: 2013, join_code: team.join_code }, tok);
}
const browser = await chromium.launch();
let bad = 0;
for (const width of [390, 1280]) {
  const ctx = await browser.newContext({ viewport: { width, height: 800 }, deviceScaleFactor: 2, isMobile: width < 900, hasTouch: width < 900 });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => { console.log('PAGEERROR', e.message); bad++; });
  await page.goto(`${base}/app/index.html?code=${tok}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);
  await page.locator('#wizard-skip').click({ timeout: 1500 }).catch(() => {});
  await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));
  const status = page.waitForResponse((r) => r.url().includes('/api/coach/evaluation'), { timeout: 8000 }).then((r) => r.status());
  await page.click('#ev-build');
  const code = await status;
  await page.waitForTimeout(600);
  const r = await page.evaluate(() => ({
    err: document.querySelector('#ev-err').classList.contains('hidden') ? '' : document.querySelector('#ev-err').textContent,
    names: [...document.querySelectorAll('#ev-out tbody tr td:first-child')].map((td) => td.textContent.trim()),
  }));
  console.log(`${width}px: HTTP ${code} | error "${r.err}" | rows ${r.names.join(', ')}`);
  if (code !== 200) { console.log(`FAIL ${width}px: the report request answered ${code}`); bad++; }
  if (r.err) { console.log(`FAIL ${width}px: the card shows an error`); bad++; }
  if (r.names.join('|') !== 'Alexandra Montgomery-Smith|Bo Short') { console.log(`FAIL ${width}px: expected both players, alphabetical`); bad++; }
  const card = page.locator('#ev-out').locator('xpath=ancestor::div[contains(@class,"card")][1]');
  await card.scrollIntoViewIfNeeded();
  await card.screenshot({ path: `${out}/evaluation-${width}.png` });
  await ctx.close();
}
await browser.close();
console.log(bad ? `FAILED ${bad}` : 'OK');
process.exit(bad ? 1 : 0);
