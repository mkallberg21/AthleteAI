// Leaving the page and coming back (TeamSnap's sign-in, a refresh, a phone
// switching apps) must put the director on the step they were on, not page 1.
import { chromium } from 'playwright';

const base = process.argv[2] || 'http://127.0.0.1:8000';
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
await page.goto(`${base}/`);
await page.locator('.role-btn', { hasText: /director/i }).first().click();
await page.fill('#org-name', 'Resume FC'); await page.fill('#org-director', 'Joel');
await page.check('#org-terms'); await page.click('#create-org');
await page.waitForURL(/coach\.html/);
await page.waitForSelector('#wizard:not(.hidden)');

const title = async () => (await page.locator('#wizard-title').textContent()).trim();
const next = page.locator('#wizard-next');
const unlocked = () => page.waitForFunction(() => !document.getElementById('wizard-next').disabled, null, { timeout: 10000 });
console.log('1.', await title());
await next.click();
await page.fill('#contact-email', 'joel@example.com'); await page.fill('#contact-phone', '615 555 0100');
await page.click('#contact-save'); await unlocked(); await next.click(); await page.waitForTimeout(500);
await next.click(); await page.waitForTimeout(500);
await page.fill('#season-starts', '2027-02-01'); await page.dispatchEvent('#season-starts', 'change'); await page.waitForTimeout(500);
await page.fill('#season-ends', '2027-06-30'); await page.dispatchEvent('#season-ends', 'change');
await unlocked(); await next.click(); await page.waitForTimeout(500);
await page.fill('#bt-names', '2031 Red'); await page.waitForTimeout(500);
await page.click('#bt-add'); await unlocked(); await next.click(); await page.waitForTimeout(700);
const before = await title();
console.log('before leaving:', before);

// what TeamSnap's return does: leave, come back with ?teamsnap=...
await page.goto(`${base}/app/coach.html?teamsnap=connected`);
await page.waitForSelector('#wizard:not(.hidden)'); await page.waitForTimeout(1500);
console.log('after TeamSnap round trip:', await title());
await page.reload(); await page.waitForSelector('#wizard:not(.hidden)'); await page.waitForTimeout(1500);
await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));  // cards start folded
await page.evaluate(() => document.querySelectorAll('.tab-off').forEach((c) => c.classList.remove('tab-off')));  // all tabs shown
console.log('after a plain refresh:    ', await title());

// finishing forgets it, so a later visit does not reopen the walkthrough
await page.click('#wizard-skip'); await page.waitForTimeout(500);
await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));  // cards start folded
await page.evaluate(() => document.querySelectorAll('.tab-off').forEach((c) => c.classList.remove('tab-off')));  // all tabs shown
await page.reload(); await page.waitForTimeout(1500);
await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));  // cards start folded
await page.evaluate(() => document.querySelectorAll('.tab-off').forEach((c) => c.classList.remove('tab-off')));  // all tabs shown
console.log('after Skip + reload, walkthrough hidden:', await page.locator('#wizard').evaluate((e) => e.classList.contains('hidden')));
await browser.close();
