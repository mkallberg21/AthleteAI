// The click that did nothing: pick a TeamSnap team, press "Pull this roster
// and preview", and see the preview. Needs scripts/dev_fake_teamsnap.py on :8001.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8001';
const out = process.argv[3] || path.join(process.env.LOCALAPPDATA || os.tmpdir(), 'Temp', 'ts-pull');
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const page = await (await browser.newContext(opts)).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(`${base}/`);
  await page.locator('.role-btn', { hasText: /director/i }).first().click();
  await page.fill('#org-name', 'Pull FC'); await page.fill('#org-director', 'Joel');
  await page.click('#create-org');
  await page.waitForURL(/coach\.html/);
  await page.waitForSelector('#wizard-skip'); await page.click('#wizard-skip');
  await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));  // cards start folded
  await page.fill('#new-team', '2031 Red'); await page.waitForTimeout(400);
  await page.fill('#new-team-coach', 'Sam Hill'); await page.fill('#new-team-coach-email', 'sam@example.com');
  await page.click('#add-team'); await page.waitForTimeout(1000);
  await page.reload(); await page.waitForTimeout(1500);
  await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));  // cards start folded

  await page.click('[data-source=teamsnap]');
  await page.waitForSelector('#teamsnap-pick:not(.hidden)');
  console.log(tag, 'state:', (await page.locator('#teamsnap-state').textContent()).trim());
  console.log(tag, 'teams offered:', (await page.locator('#teamsnap-remote option').allTextContents()).join(' | '));
  await page.screenshot({ path: `${out}/${tag}-1-picked.png` });

  await page.click('#teamsnap-link');
  await page.waitForTimeout(2500);
  const shown = await page.locator('#sync-result').isVisible();
  console.log(tag, 'preview visible after click:', shown);
  if (shown) console.log(tag, 'preview says:', (await page.locator('#sync-result').innerText()).replace(/\s*\n\s*/g, ' | ').slice(0, 330));
  console.log(tag, 'error box:', (await page.locator('#teamsnap-err').textContent()).trim() || '(none)');
  if (errors.length) console.log(tag, 'PAGE ERRORS:', errors.join(' || '));
  await page.screenshot({ path: `${out}/${tag}-2-preview.png` });

  // apply it: the players arrive, with their parents, and the Families card knows
  const apply = page.locator('#sync-apply');
  console.log(tag, 'apply button:', (await apply.textContent()).trim());
  await apply.click();
  await page.waitForFunction(() => /Applied/.test(document.getElementById('sync-result').innerText), null, { timeout: 15000 });
  await page.waitForTimeout(1500);
  const resultText = (await page.locator('#sync-result').innerText()).split(/\r?\n/).map((x) => x.trim()).filter(Boolean).join(' | ');
  console.log(tag, 'after apply:', resultText.slice(0, 120));
  const fam = await page.locator('#families').innerText().catch(() => '');
  console.log(tag, 'Families card has Mason Reed:', /Mason/.test(fam), '| Owen Hale:', /Owen/.test(fam));
  const parents = await page.locator('#parents-card').innerText().catch(() => '');
  console.log(tag, 'Parents card:', (parents.match(/[0-9]+ parents?: [^.]*[.]/) || ['(no summary)'])[0]);
  await page.screenshot({ path: `${out}/${tag}-3-applied.png` });
  await page.context().close();
}
await browser.close();
