// The drill screen has no stick figure: shooting, and both wall balls.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const T = path.join(process.env.LOCALAPPDATA, 'Temp');
const base = process.argv[2] || 'http://127.0.0.1:8008';
const seed = fs.readFileSync(path.join(T, 'busy_seed.txt'), 'utf8');
const kid = (seed.match(/Ryder Kallberg\s+(\S{6})\s*$/m) || [])[1];
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const b = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
const ctx = await b.newContext({ ...devices['iPhone 13'], permissions: ['camera', 'microphone'] });
const page = await ctx.newPage();
page.on('pageerror', (e) => console.log('PAGE ERROR', e.message.slice(0, 160)));
await page.goto(base + '/app/capture.html', { waitUntil: 'domcontentloaded' });
await page.evaluate((t) => { localStorage.setItem('offdays.token', t); localStorage.setItem('offdays.awizard', 'done'); }, kid);
await page.goto(base + '/app/capture.html', { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(3500);
for (const name of [/Shooting/i, /Wall Ball.*Strong/i, /Wall Ball.*Off/i]) {
  await page.goto(base + '/app/capture.html', { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(2500);
  const btn = page.locator('#drill-list button, #drill-list .drill-btn').filter({ hasText: name }).first();
  if (!(await btn.count())) { console.log('no button for', String(name)); continue; }
  await btn.click(); await page.waitForTimeout(2500);
  const svgs = await page.locator('#view-capture svg').count();
  const demo = await page.locator('#demo, #demo-fig').count();
  const label = await page.locator('#drill-title, #view-capture h2').first().innerText().catch(() => String(name));
  check(svgs === 0 && demo === 0, `${label.trim().slice(0, 28)}: no figure (svgs ${svgs}, demo elements ${demo})`);
  if (/shooting/i.test(String(name))) await page.screenshot({ path: path.join(T, 'drill-shooting.png'), fullPage: false });
}
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good'); process.exit(bad ? 1 : 0);
