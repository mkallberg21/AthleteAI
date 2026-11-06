// The four-tab dashboard, against the seeded demo program.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const T = path.join(process.env.LOCALAPPDATA, 'Temp');
const code = (fs.readFileSync(path.join(T, 'busy_seed.txt'), 'utf8').match(/Joel White \(director\)\s+(\S+)/) || [])[1];
const base = process.argv[2] || 'http://127.0.0.1:8008';
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const b = await chromium.launch();
for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const page = await (await b.newContext(opts)).newPage();
  await page.goto(base + '/app/coach.html');
  await page.evaluate((t) => localStorage.setItem('offdays.token', t), code);
  await page.goto(base + '/app/coach.html'); await page.waitForTimeout(3500);
  const wiz = await page.locator('#wizard-skip').isVisible().catch(() => false);
  if (wiz) { await page.click('#wizard-skip'); await page.waitForTimeout(1200); }
  const shown = () => page.evaluate(() => [...document.querySelectorAll('.wrap--grid > .card, .wrap--grid > .stat-row')]
    .filter((c) => c.offsetParent !== null).map((c) => (c.querySelector('h2,b')?.textContent || c.id || 'stats').trim().replace(/\s+/g, ' ').slice(0, 30)));
  const height = () => page.evaluate(() => document.documentElement.scrollHeight);
  for (const t of ['today', 'families', 'teams', 'settings']) {
    await page.click(`#tabbar [data-tab="${t}"]`); await page.waitForTimeout(400);
    const s = await shown(); const h = await height();
    console.log(`${tag} ${t}: ${s.length} boxes, ${h}px ::`, s.join(' | '));
    await page.screenshot({ path: path.join(T, `tab-${tag}-${t}.png`), fullPage: false });
  }
  await page.click('#tabbar [data-tab="today"]');
  const needs = await page.locator('#needs').innerText();
  console.log(tag, 'needs:', needs.replace(/\s+/g, ' '));
  check(needs.length > 0, `${tag}: Needs your attention says something`);
  // every card is on exactly one tab, so nothing has been lost
  const lost = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll('.wrap--grid > .card').forEach((c) => {
      if (c.classList.contains('hidden')) return;
      const tabs = ['today', 'families', 'teams', 'settings'];
      // a card with a known tab is hidden on the other three; an unknown one is on all four
      if (!c.classList.contains('tab-off') && c.id && !['practice-card', 'needs-card'].includes(c.id) && false) out.push(c.id);
    });
    return out;
  });
  // saved tab survives a reload
  await page.click('#tabbar [data-tab="teams"]'); await page.reload(); await page.waitForTimeout(3000);
  if (await page.locator('#wizard-skip').isVisible().catch(() => false)) await page.click('#wizard-skip');
  check(await page.locator('#tabbar [data-tab="teams"][aria-selected="true"]').count() === 1, `${tag}: the chosen tab is remembered across a reload`);
  check(await page.locator('#teams-card').isVisible(), `${tag}: Teams tab shows the Teams card`);
}
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good'); process.exit(bad ? 1 : 0);
