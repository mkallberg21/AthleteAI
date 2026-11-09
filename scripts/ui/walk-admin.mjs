// The operator dashboard in a real browser, against a local server with a FAKE Stripe.
// Nothing leaves the machine. Run: node walk-admin.mjs <base> <operator key>
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8011';
const KEY = process.argv[3] || 'operator-key-for-the-walk-0000000000';
const T = path.join(process.env.LOCALAPPDATA || os.tmpdir(), 'Temp', 'pw');
fs.mkdirSync(T, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const j = (u, b, h = {}) => fetch(base + u, { method: 'POST', headers: { 'Content-Type': 'application/json', ...h }, body: JSON.stringify(b) }).then((r) => r.json());

// three programs in three states
const stamp = Date.now();
const mk = async (name, kids, season) => {
  const org = await j('/api/orgs', { name: `${name} ${stamp}`, director_name: `${name} Director` });
  const dir = { Authorization: `Bearer ${org.director.token}` };
  const team = await j('/api/teams', { name: '2031 Red' }, dir);
  for (let i = 0; i < kids; i++) await j('/api/athletes', { display_name: `Kid ${i}`, join_code: team.join_code }, dir);
  if (season) await fetch(base + '/api/org/season', { method: 'PUT', headers: { 'Content-Type': 'application/json', ...dir }, body: JSON.stringify({ starts_on: season.season_starts_on, ends_on: season.season_ends_on }) });
  return org;
};
const iso = (d) => new Date(Date.now() + d * 864e5).toISOString().slice(0, 10);
await mk('Ready FC', 12, { season_starts_on: iso(-3), season_ends_on: iso(96) });
await mk('NoSeason FC', 5, null);
await mk('NoRoster FC', 0, { season_starts_on: iso(-3), season_ends_on: iso(96) });

const b = await chromium.launch();
for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const ctx = await b.newContext(opts);
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.log('PAGE ERROR', e.message.slice(0, 160)));
  await page.goto(base + '/admin', { waitUntil: 'domcontentloaded' });
  check(page.url().endsWith('/app/admin.html'), `${tag}: /admin is a short link to the page`);
  check(await page.locator('#door').isVisible() && await page.locator('#app').isHidden(), `${tag}: nothing but the door shows before the key`);
  await page.fill('#key', 'not-the-key'); await page.click('#enter'); await page.waitForTimeout(800);
  check(/not the key/i.test(await page.locator('#door-err').innerText()), `${tag}: a wrong key is told so`);
  check(await page.locator('#app').isHidden(), `${tag}: and still sees nothing`);
  await page.fill('#key', KEY); await page.click('#enter'); await page.waitForTimeout(1500);
  check(await page.locator('#app').isVisible(), `${tag}: the right key opens it`);
  check(!page.url().includes(KEY) && !(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).includes(KEY), `${tag}: the key is in neither the address nor storage`);

  const money = (await page.locator('#money').innerText()).replace(/\s+/g, ' ');
  check(/READY TO INVOICE/i.test(money) && /PAID/i.test(money) && /OVERDUE/i.test(money), `${tag}: four money boxes (${money.slice(0, 80)})`);
  const ready = page.locator('.prog', { hasText: 'Ready FC' });
  check(await ready.locator('.pill').innerText() === 'Ready to invoice', `${tag}: Ready FC is Ready to invoice`);
  check(/\$/.test(await ready.locator('.money').innerText()), `${tag}: with an amount`);
  check(/Waiting on season/i.test(await page.locator('.prog', { hasText: 'NoSeason FC' }).locator('.pill').innerText()), `${tag}: NoSeason FC says it is waiting on season dates`);
  check(/Waiting on roster/i.test(await page.locator('.prog', { hasText: 'NoRoster FC' }).locator('.pill').innerText()), `${tag}: NoRoster FC says it is waiting on a roster`);
  check(await page.locator('.prog', { hasText: 'NoSeason FC' }).locator('[data-act]').count() === 0, `${tag}: a program that is not ready offers no button`);
  await page.screenshot({ path: path.join(T, `${tag}-9-admin.png`), fullPage: tag === 'phone' });

  await page.click('#filter [data-f="todo"]'); await page.waitForTimeout(300);
  const todo = await page.locator('.prog').allInnerTexts();
  check(todo.some((t) => t.includes('Ready FC')) && !todo.some((t) => t.includes('NoSeason FC')), `${tag}: "Needs me" shows only what I can act on`);
  await page.click('#filter [data-f="all"]');

  // Stripe is not connected on this local server: the page says so and the press fails politely.
  check(await page.locator('#setup').isVisible(), `${tag}: it says Stripe is not fully connected`);
  await ready.locator('input[type=email]').fill('treasurer@ready.example');
  await ready.locator('[data-act="invoice"]').click(); await page.waitForTimeout(1200);
  const msg = (await ready.locator('[id^=msg-]').innerText());
  check(/not connected/i.test(msg), `${tag}: with no Stripe key, pressing Create invoice explains why (${msg.slice(0, 60)})`);
  check(await ready.locator('.pill').innerText() === 'Ready to invoice', `${tag}: and nothing was created`);
  await page.locator('#signout').click();
  check(await page.locator('#door').isVisible() && await page.locator('#app').isHidden(), `${tag}: Lock puts the door back`);
  await ctx.close();
}
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good'); process.exit(bad ? 1 : 0);
