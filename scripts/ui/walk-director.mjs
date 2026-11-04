// Director's dashboard at tablet width: screenshot the Families card.
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, token, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ ...devices['iPad (gen 7)'] });
const page = await ctx.newPage();
page.on('pageerror', (e) => console.log('PAGEERROR', e.message));
page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE', m.text().slice(0, 160)); });
await page.goto(`${base}/app/index.html?code=${token}`, { waitUntil: 'networkidle' });
await page.waitForTimeout(3000);
console.log('url:', page.url());
const card = page.locator('#families-card');
console.log('families card visible:', await card.isVisible());
if (await card.isVisible()) {
  console.log('through:', await page.locator('#families-through').textContent());
  console.log('counts:', (await page.locator('#families-counts').innerText()).replace(/\n/g, ' | '));
  console.log('rows (stuck):', await page.locator('#families tr').count());
  await page.selectOption('#families-filter', 'all');
  console.log('rows (all):', await page.locator('#families tr').count());
  await page.selectOption('#families-filter', 'stuck');
  await card.scrollIntoViewIfNeeded();
  await card.screenshot({ path: `${out}/families.png` });
  const nudge = page.locator('#families button[data-nudge]').first();
  if (await nudge.count()) {
    page.once('dialog', (d) => { console.log('DIALOG', d.message()); d.dismiss(); });
    await nudge.click();
    await page.waitForTimeout(2500);
    console.log('after nudge, counts:', (await page.locator('#families-counts').innerText()).replace(/\s*\n\s*/g, ' | '));
    await card.screenshot({ path: `${out}/families-after-nudge.png` });
  }
}
await browser.close();
