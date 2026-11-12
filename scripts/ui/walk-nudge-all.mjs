// Needs a nudge: message everyone on the list, from the card.
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
  let asked = '';
  page.on('dialog', async (d) => { asked = d.message(); await d.accept(); });
  await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => localStorage.setItem('offdays.token', t), code);
  await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(3500);
  if (await page.locator('#wizard-skip').isVisible().catch(() => false)) { await page.click('#wizard-skip'); await page.waitForTimeout(1000); }
  await page.click('#tabbar [data-tab="today"]'); await page.waitForTimeout(400);   // the dashboard opens on Home
  // the card sits behind the Open button on the attention summary
  await page.click('#needs [data-open="attention-card"]'); await page.waitForTimeout(500);
  const label = await page.locator('#nudge-open').innerText();
  console.log(tag, 'button:', label);
  check(/all \d+ of them|this athlete/.test(label), `${tag}: the button says how many`);
  await page.click('#nudge-open');
  check(await page.locator('#nudge-form').isVisible(), `${tag}: the form opens`);
  console.log(tag, 'who:', (await page.locator('#nudge-who').innerText()).slice(0, 200));
  await page.locator('#attention-card').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(T, `nudge-${tag}.png`) });
  await page.fill('#nudge-title', '');
  await page.click('#nudge-send');
  check(/title first/i.test(await page.locator('#nudge-note').innerText()), `${tag}: an empty title is refused, nothing sent`);
  await page.fill('#nudge-title', 'Ten minutes today?');
  await page.click('#nudge-send'); await page.waitForTimeout(1500);
  const note = await page.locator('#nudge-note').innerText();
  console.log(tag, 'confirm asked:', asked, '| result:', note);
  check(/Sent to \d+/.test(note), `${tag}: it reports how many it sent`);
  check(await page.locator('#nudge-form').isHidden(), `${tag}: the form closes after sending`);
}
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good'); process.exit(bad ? 1 : 0);
