// The director creates a team the new way: name it, name the coach, watch
// the numbers fill in, create. Screenshots + the table after.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const made = await (await fetch(`${base}/api/orgs`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: 'Mad Dog Lacrosse', sport: 'lacrosse', director_name: 'Joel White' }) })).json();
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
page.on('pageerror', (e) => console.log('PAGEERROR', e.message));
await page.goto(`${base}/app/index.html?code=${made.director.token}`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2000);
await page.locator('#teams-card').scrollIntoViewIfNeeded();
await page.fill('#new-team', '2031 Red');
await page.waitForTimeout(700);
console.log('age line:', await page.locator('#new-team-age').textContent());
console.log('prefilled wall/shots:', await page.inputValue('#new-team-wall'), '/', await page.inputValue('#new-team-shots'));
await page.fill('#new-team-coach', 'Sam Hill');
await page.fill('#new-team-coach-email', 'sam@example.com');
await page.locator('#teams-card').screenshot({ path: `${out}/1-filled.png` });
await page.click('#add-team');
await page.waitForFunction(() => !document.getElementById('new-team-out').classList.contains('hidden'));
await page.waitForTimeout(800);
console.log('result:', (await page.locator('#new-team-out').innerText()).replace(/\s+/g, ' '));
// A second team, younger, to show the numbers differ
await page.fill('#new-team', 'U9');
await page.waitForTimeout(700);
console.log('U9 prefilled wall/shots:', await page.inputValue('#new-team-wall'), '/', await page.inputValue('#new-team-shots'));
await page.click('#add-team');
await page.waitForTimeout(1500);
await page.locator('#teams-card').screenshot({ path: `${out}/2-table.png` });
console.log('table:', (await page.locator('#teams').innerText()).replace(/\s*\n\s*/g, ' | '));
console.log('cost card note:', (await page.locator('#billing-card').innerText()).includes('Never shown to coaches, parents or athletes'));
await browser.close();
