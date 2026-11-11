// The walkthrough's season step asks for dates only; the phase selector
// lives on the dashboard's "Where the season is" card. Exits 1 if not.
//   node scripts/ui/walk-season-step.mjs <base> <outdir>
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const made = await (await fetch(`${base}/api/orgs`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: 'Season Step Check', sport: 'lacrosse', accept_terms: true, director_name: 'Pat Lee' }) })).json();
const browser = await chromium.launch();
const page = await (await browser.newContext({ ...devices['iPhone 13'] })).newPage();
page.on('pageerror', (e) => console.log('PAGEERROR', e.message));
const phaseShown = () => page.evaluate(() => {
  const s = document.getElementById('season-phase');
  return !!s && s.getClientRects().length > 0;
});
let bad = 0;
await page.goto(`${base}/app/index.html?code=${made.director.token}`, { waitUntil: 'networkidle' });
await page.waitForSelector('#wizard:not(.hidden)', { timeout: 15000 });
await page.fill('#contact-email', 'pat@example.com'); await page.fill('#contact-phone', '615 555 0100');
await page.click('#contact-save');
await page.waitForFunction(() => !document.getElementById('wizard-next').disabled, null, { timeout: 8000 });
await page.click('#wizard-next'); await page.waitForTimeout(700);   // -> badge
await page.click('#wizard-next'); await page.waitForTimeout(900);   // -> season
const title = await page.locator('#wizard-title').textContent();
const inWizard = await phaseShown();
console.log('wizard step:', title, '| phase selector visible:', inWizard);
if (!/season/i.test(title)) { console.log('FAIL: not on the season step'); bad++; }
if (inWizard) { console.log('FAIL: phase selector shows in the walkthrough'); bad++; }
// The step has its own title; the card's heading would say it twice, and a
// line sending the director "to the Season card" while on it is noise.
const extra = await page.evaluate(() => {
  const vis = (el) => !!el && el.getClientRects().length > 0;
  const card = document.getElementById('season-card');
  const h2 = card.querySelector(':scope > h2');
  const said = [...card.querySelectorAll('*')].filter((e) => vis(e) && !e.children.length && /on the Season card/i.test(e.textContent));
  return { heading: vis(h2), seasonCardLine: said.length };
});
console.log('card heading visible:', extra.heading, '| "on the Season card" lines:', extra.seasonCardLine);
if (extra.heading) { console.log('FAIL: card heading repeats the step title'); bad++; }
if (extra.seasonCardLine) { console.log('FAIL: step tells the director to go to the Season card'); bad++; }
await page.screenshot({ path: `${out}/1-wizard-season.png`, fullPage: true });
// Dates still work from the step.
await page.fill('#season-starts', '2027-02-01'); await page.dispatchEvent('#season-starts', 'change'); await page.waitForTimeout(500);
await page.fill('#season-ends', '2027-06-30'); await page.dispatchEvent('#season-ends', 'change');
await page.waitForFunction(() => !document.getElementById('wizard-next').disabled, null, { timeout: 8000 });
console.log('dates saved, Next enabled');
await page.click('#wizard-skip');
await page.waitForTimeout(800);
await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));
await page.waitForTimeout(300);
const onDash = await phaseShown();
console.log('dashboard phase selector visible:', onDash);
if (!onDash) { console.log('FAIL: phase selector missing from the dashboard card'); bad++; }
await page.locator('#season-card').scrollIntoViewIfNeeded();
await page.locator('#season-card').screenshot({ path: `${out}/2-dashboard-season.png` });
await browser.close();
console.log(bad ? `FAILED ${bad}` : 'OK');
process.exit(bad ? 1 : 0);
