// "Another program" roster source, connected the way a director does it on a
// phone: pick the source, paste the export link, leave the token blank (the
// page says it is optional), press Connect and preview. Exits 1 unless the
// preview appears with no error.
//   node scripts/ui/walk-export-link.mjs <base> <outdir>
// Run against scripts/dev_fake_export.py (the export link answers locally).
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
const made = await post('/api/orgs', { name: 'Export Link Check', sport: 'lacrosse', director_name: 'Pat Lee' });
const tok = made.director.token;
await post('/api/teams', { name: '2031 Red' }, tok);

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
const page = await ctx.newPage();
let bad = 0;
page.on('pageerror', (e) => { console.log('PAGEERROR', e.message); bad++; });
await page.goto(`${base}/app/index.html?code=${tok}`, { waitUntil: 'networkidle' });
await page.waitForTimeout(1200);
await page.locator('#wizard-skip').click({ timeout: 1500 }).catch(() => {});
await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));
await page.locator('.source-btn[data-source="link"]').click();
const tokenLabel = await page.locator('#sync-token-label').textContent();
console.log(`token label: "${tokenLabel}"`);
await page.locator('#sync-ref').fill('https://club.example/roster.csv');
await page.locator('#sync-connect').click();
await page.waitForTimeout(1500);
const err = (await page.locator('#sync-err').isVisible()) ? (await page.locator('#sync-err').textContent()).trim() : '';
const preview = (await page.locator('#sync-result').textContent()).replace(/\s+/g, ' ').trim();
const links = await page.locator('#sync-links tbody tr').count();
console.log(`error: "${err}"`);
console.log(`preview: "${preview.slice(0, 160)}"`);
console.log(`connected links listed: ${links}`);
if (err) { console.log('FAIL: connecting with a blank (optional) token showed an error'); bad++; }
if (!/2/.test(preview)) { console.log('FAIL: no preview of the two players'); bad++; }
if (links !== 1) { console.log('FAIL: the link is not listed'); bad++; }
await page.locator('#import-card').screenshot({ path: `${out}/export-link-390.png` });
await browser.close();
console.log(bad ? `FAILED ${bad}` : 'OK');
process.exit(bad ? 1 : 0);
