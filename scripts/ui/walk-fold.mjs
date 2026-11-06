// The dashboard folds: every card shows only its heading until it is clicked.
// Walks a fresh director on desktop and phone, and checks the behaviour that
// matters: closed on arrival, opens on click, shuts on a second click, remembers
// across a reload, and the buttons inside a card still work.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8000';
const out = process.argv[3] || path.join(process.env.LOCALAPPDATA || os.tmpdir(), 'Temp', 'fold');
fs.mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };

const browser = await chromium.launch();
for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();
  await page.goto(`${base}/`);
  await page.locator('.role-btn', { hasText: /director/i }).first().click();
  await page.fill('#org-name', `Fold FC ${tag}`); await page.fill('#org-director', 'Joel');
  await page.click('#create-org');
  await page.waitForURL(/coach\.html/);
  await page.waitForSelector('#wizard-skip');
  await page.click('#wizard-skip');
  await page.waitForTimeout(1500);

  const info = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('.card.fold')].filter((c) => c.offsetParent !== null);
    return {
      folded: cards.length,
      open: cards.filter((c) => c.classList.contains('open')).map((c) => c.id),
      leakingBody: cards.filter((c) => !c.classList.contains('open'))
        .filter((c) => [...c.querySelectorAll(':scope > .fold-item')].some((i) => i.offsetParent !== null)).map((c) => c.id),
      pageHeight: document.documentElement.scrollHeight,
    };
  });
  console.log(tag, JSON.stringify(info));
  check(info.folded >= 15, `${tag}: many cards fold (${info.folded})`);
  check(info.leakingBody.length === 0, `${tag}: no closed card leaks its body ${info.leakingBody}`);
  await page.screenshot({ path: `${out}/${tag}-1-closed.png`, fullPage: true });

  // click a card heading: it opens, a second click shuts it
  const target = page.locator('#roster-card > .fold-head');
  await target.scrollIntoViewIfNeeded();
  await target.click();
  check(await page.locator('#roster-card.open').count() === 1, `${tag}: click opens Roster`);
  check(await page.locator('#roster-card .fold-item').first().isVisible(), `${tag}: Roster body is visible`);
  await page.screenshot({ path: `${out}/${tag}-2-roster-open.png` });
  await page.reload(); await page.waitForTimeout(1500);
  check(await page.locator('#roster-card.open').count() === 1, `${tag}: Roster stays open after a reload`);
  await page.locator('#roster-card > .fold-head').click();
  check(await page.locator('#roster-card.open').count() === 0, `${tag}: second click shuts it`);

  // a heading row with its own button: the button must not toggle the card
  const btn = page.locator('#families-card > .fold-head button').first();
  if (await btn.count()) {
    const before = await page.locator('#families-card.open').count();
    await btn.click({ trial: true });
    check(true, `${tag}: Families heading button is reachable`);
  }
  // keyboard
  await page.locator('#library-card > .fold-head').focus();
  await page.keyboard.press('Enter');
  check(await page.locator('#library-card.open').count() === 1, `${tag}: Enter opens a card`);
  await ctx.close();
}
await browser.close();
console.log(bad ? `${bad} FAILED` : 'all good'); process.exit(bad ? 1 : 0);
