// What the director sees, step by step: the sign-up page, the form filled,
// the code shown, the dashboard on first sign-in, and the dashboard after
// uploading a badge. Desktop and phone. Screenshots to --out.
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();

for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 860 } }], ['phone', devices['iPhone 13']]]) {
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.log(tag, 'PAGEERROR', e.message));

  await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
  await page.screenshot({ path: `${out}/${tag}-1-landing.png`, fullPage: tag === 'phone' });

  await page.click('.role-btn[data-role="director"]');
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${out}/${tag}-1b-director-open.png`, fullPage: tag === 'phone' });
  const card = page.locator('#org-name').locator('xpath=ancestor::div[contains(@class,"card")][1]');
  await card.scrollIntoViewIfNeeded();
  await page.fill('#org-name', 'Mad Dog Lacrosse');
  await page.selectOption('#org-sport', 'lacrosse');
  await page.fill('#org-director', 'Joel White');
  await card.screenshot({ path: `${out}/${tag}-2-signup-filled.png` });
  await page.click('#create-org');
  await page.waitForURL(/coach\.html/, { timeout: 15000 });

  await page.waitForTimeout(2500);
  console.log(tag, 'first step:', await page.locator('#wizard-title').textContent(), '| code shown:', (await page.locator('#code-value').textContent()).length, 'chars');
  await page.screenshot({ path: `${out}/${tag}-3-code-step.png` });
  await page.locator('#wizard-skip').click({ timeout: 1500 }).catch(() => {}); await page.waitForTimeout(400);
  await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));  // cards start folded
  await page.screenshot({ path: `${out}/${tag}-4-dashboard-first.png`, fullPage: false });

  // Upload the shipped Nashville Dogs crest as the badge, through the real control.
  const chooser = page.waitForEvent('filechooser');
  await page.click('#badge-upload');
  await (await chooser).setFiles('C:/Users/mtkal/AthleteAI/offdays/web/static/teams/nashville-dogs.png');
  await page.waitForFunction(() => /Saved/.test(document.getElementById('badge-status').textContent));
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${out}/${tag}-5-dashboard-badge.png`, fullPage: false });
  console.log(tag, 'badge status:', await page.locator('#badge-status').textContent(),
    '| header img:', await page.locator('#masthead img.club-badge').getAttribute('src'));
  await ctx.close();
}
await browser.close();
