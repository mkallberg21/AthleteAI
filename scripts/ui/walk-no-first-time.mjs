// The athlete home page no longer shows "First time here"; a real blocker still shows.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const T = path.join(process.env.LOCALAPPDATA, 'Temp');
const base = process.argv[2] || 'http://127.0.0.1:8008';
const seed = fs.readFileSync(path.join(T, 'busy_seed.txt'), 'utf8');
const kid = (seed.match(/Ryder Kallberg\s+(\S{6})\s*$/m) || [])[1] || (seed.match(/^\s{4}\S[^\n]*?\s{2,}([A-Z0-9]{6})\s*$/m) || [])[1];
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const b = await chromium.launch();
const page = await (await b.newContext({ ...devices['iPhone 13'] })).newPage();
page.on('pageerror', (e) => console.log('PAGE ERROR', e.message.slice(0, 150)));
await page.goto(base + '/app/capture.html', { waitUntil: 'domcontentloaded' });
await page.evaluate((t) => { localStorage.setItem('offdays.token', t); localStorage.setItem('offdays.awizard', 'done'); }, kid);
await page.goto(base + '/app/capture.html', { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(3500);
const text = await page.locator('body').innerText();
check(!/first time here/i.test(text), 'no "First time here" anywhere on the page');
check(!/a couple more things/i.test(text), 'no "A couple more things" either');
check(await page.locator('#drill-list').isVisible(), 'the drill list is there');
const card = await page.locator('#start-card').isVisible();
console.log('start card visible:', card, card ? '| ' + (await page.locator('#start-card').innerText()).replace(/\s+/g, ' ').slice(0, 140) : '');
await page.screenshot({ path: path.join(T, 'athlete-home.png'), fullPage: false });
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good'); process.exit(bad ? 1 : 0);
