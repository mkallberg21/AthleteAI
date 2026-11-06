// Red stars on the cards that still need the director's input, and Families folded.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8005';
const out = process.argv[3] || path.join(process.env.LOCALAPPDATA || os.tmpdir(), 'Temp', 'todo');
fs.mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const starred = (page) => page.evaluate(() => [...document.querySelectorAll('.todo-star')].map((n) => n.closest('.card')?.id));

const browser = await chromium.launch();
for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const page = await (await browser.newContext(opts)).newPage();
  await page.goto(`${base}/`);
  await page.locator('.role-btn', { hasText: /director/i }).first().click();
  await page.fill('#org-name', `Star FC ${tag}`); await page.fill('#org-director', 'Joel');
  await page.click('#create-org'); await page.waitForURL(/coach\.html/);
  await page.waitForSelector('#wizard-skip'); await page.click('#wizard-skip'); await page.waitForTimeout(1800);

  let s = await starred(page);
  console.log(tag, 'starred:', JSON.stringify(s));
  check(s.includes('contact-card') && s.includes('season-card') && s.includes('teams-card'), `${tag}: contact, season and teams are starred`);
  check(!s.includes('import-card'), `${tag}: roster is not starred until a team exists`);
  check(await page.locator('#families-card.open').count() === 0, `${tag}: Families starts folded`);
  check(await page.evaluate(() => [...document.querySelectorAll('.todo-star')].every((n) => n.offsetParent !== null)), `${tag}: every star is visible while folded`);
  await page.locator('#teams-card').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${out}/${tag}-1-stars.png` });

  // add a team: teams loses its star, the roster gains one
  await page.locator('#teams-card > .fold-head, #teams-card > h2').first().click();
  await page.fill('#new-team', '2031 Red'); await page.waitForTimeout(500);
  await page.fill('#new-team-coach', 'Sam Hill'); await page.fill('#new-team-coach-email', 'sam@example.com');
  await page.click('#add-team'); await page.waitForTimeout(1200);
  await page.reload(); await page.waitForTimeout(1800);
  s = await starred(page);
  console.log(tag, 'after a team:', JSON.stringify(s));
  check(!s.includes('teams-card') && s.includes('import-card'), `${tag}: team done, roster now starred`);
  await page.screenshot({ path: `${out}/${tag}-2-after-team.png` });
}
await browser.close();
console.log(bad ? `${bad} FAILED` : 'all good'); process.exit(bad ? 1 : 0);
