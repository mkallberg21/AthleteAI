// Mid-season: a kid moves to town. Add one player by hand, see the parent's
// invite, see the cost go up, and see the player in the Families card.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8000';
const out = process.argv[3] || path.join(process.env.LOCALAPPDATA || os.tmpdir(), 'Temp', 'add-player');
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();
  await page.goto(`${base}/`);
  await page.locator('.role-btn', { hasText: /director/i }).first().click();
  await page.fill('#org-name', 'Late Joiner FC'); await page.fill('#org-director', 'Joel');
  await page.click('#create-org');
  await page.waitForURL(/coach\.html/);
  await page.waitForSelector('#wizard-skip');
  await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));  // cards start folded
  await page.click('#wizard-skip');
  await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));  // cards start folded
  await page.fill('#new-team', '2031 Red'); await page.waitForTimeout(500);
  await page.fill('#new-team-coach', 'Sam Hill'); await page.fill('#new-team-coach-email', 'sam@example.com');
  await page.click('#add-team'); await page.waitForTimeout(1200);

  await page.locator('#add-player-card').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${out}/${tag}-1-form.png` });

  // an incomplete form says what is missing
  await page.click('#ap-add');
  console.log(tag, 'empty ->', (await page.locator('#ap-err').textContent()).trim());
  await page.fill('#ap-first', 'Mason'); await page.fill('#ap-last', 'Reed'); await page.fill('#ap-year', '2013');
  await page.fill('#ap-email', 'reed.mom@example.com');
  await page.click('#ap-add');
  console.log(tag, 'no phone ->', (await page.locator('#ap-err').textContent()).trim());

  await page.fill('#ap-phone', '615-555-0140');
  await page.click('#ap-add');
  await page.waitForSelector('#ap-ok:not(:empty)');
  console.log(tag, 'added ->', (await page.locator('#ap-ok').textContent()).trim());
  console.log(tag, 'form cleared:', (await page.locator('#ap-first').inputValue()) === '');
  console.log(tag, 'invite block:', (await page.locator('#slips-card').innerText()).replace(/\s*\n\s*/g, ' | ').slice(0, 200));
  await page.locator('#add-player-card').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${out}/${tag}-2-added.png` });

  // the parent is in the funnel, and the program is billed for one athlete
  const fam = await page.locator('#families').innerText().catch(() => '');
  console.log(tag, 'families mentions Mason:', /Mason/.test(fam));
  console.log(tag, 'cost card:', (await page.locator('#billing').innerText().catch(() => '')).replace(/\s*\n\s*/g, ' | ').slice(0, 160));
  await ctx.close();
}
await browser.close();
