// The roster step: four buttons for where the roster lives. Each shows only
// its own steps. TeamSnap is switched on locally by faking the status call,
// because the real thing needs a live TeamSnap login.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8000';
const out = process.argv[3] || path.join(process.env.LOCALAPPDATA || os.tmpdir(), 'Temp', 'sources');
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();

  await page.goto(`${base}/`);
  await page.locator('.role-btn', { hasText: /director/i }).first().click();
  await page.fill('#org-name', 'Sources FC'); await page.fill('#org-director', 'Joel');
  await page.click('#create-org');
  await page.waitForURL(/coach\.html/);
  await page.waitForSelector('#wizard-skip');
  await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));  // cards start folded
  await page.evaluate(() => document.querySelectorAll('.tab-off').forEach((c) => c.classList.remove('tab-off')));  // all tabs shown
  await page.click('#wizard-skip');
  await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));  // cards start folded
  await page.evaluate(() => document.querySelectorAll('.tab-off').forEach((c) => c.classList.remove('tab-off')));  // all tabs shown
  await page.fill('#new-team', '2031 Red'); await page.waitForTimeout(400);
  await page.fill('#new-team-coach', 'Sam Hill'); await page.fill('#new-team-coach-email', 'sam@example.com');
  await page.click('#add-team'); await page.waitForTimeout(1000);
  await page.reload(); await page.waitForTimeout(1500);
  await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));  // cards start folded
  await page.evaluate(() => document.querySelectorAll('.tab-off').forEach((c) => c.classList.remove('tab-off')));  // all tabs shown

  const vis = async () => ({
    teamsnap: await page.locator('#src-teamsnap').isVisible(),
    sync: await page.locator('#src-sync').isVisible(),
    file: await page.locator('#src-file').isVisible(),
    dropzone: await page.locator('#dropzone').isVisible(),
  });
  await page.locator('.source-pick').scrollIntoViewIfNeeded();
  console.log(tag, 'start      ', JSON.stringify(await vis()));
  await page.screenshot({ path: `${out}/${tag}-1-buttons.png` });

  await page.click('[data-source=teamsnap]');
  console.log(tag, 'TeamSnap   ', JSON.stringify(await vis()), '| button:', (await page.locator('#teamsnap-connect').textContent()).trim());
  await page.screenshot({ path: `${out}/${tag}-2-teamsnap.png` });

  await page.click('[data-source=sportsengine]');
  console.log(tag, 'SportsEngine', JSON.stringify(await vis()), '| provider:', await page.locator('#sync-provider').inputValue(), '| asks:', (await page.locator('#sync-ref-label').textContent()).trim());
  await page.screenshot({ path: `${out}/${tag}-3-sportsengine.png` });

  await page.click('[data-source=link]');
  console.log(tag, 'Another    ', JSON.stringify(await vis()), '| provider:', await page.locator('#sync-provider').inputValue(), '| asks:', (await page.locator('#sync-ref-label').textContent()).trim());
  await page.screenshot({ path: `${out}/${tag}-4-another.png` });

  await page.click('[data-source=file]');
  console.log(tag, 'File       ', JSON.stringify(await vis()));
  await ctx.close();
}
await browser.close();
