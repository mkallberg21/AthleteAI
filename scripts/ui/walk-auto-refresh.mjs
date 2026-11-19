// The coach page updates itself every couple of minutes, never while someone is typing, and reloads for a new version.
// Run: node walk-auto-refresh.mjs <base> <out-dir>
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';

const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what, extra = '') => { console.log(`${ok ? 'ok   ' : 'FAIL '}${what} ${extra}`); if (!ok) bad += 1; };
const j = async (path, token, body, method) => {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = 'Bearer ' + token;
  const r = await fetch(base + path, { method: method || (body ? 'POST' : 'GET'), headers, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, json: await r.json().catch(() => ({})) };
};
const stamp = Date.now();
const made = (await j('/api/orgs', null, { name: 'Nashville Dogs', sport: 'lacrosse', accept_terms: true, director_name: 'Matt Kallberg' })).json;
const dt = made.director.token;
const red = (await j('/api/teams', dt, { name: '2031 Red' })).json.id;
const csv = `First Name,Last Name,Birth Year,Parent Email\nDillon,Langdon,2013,robert.${stamp}@example.com\n`;
const imp = (await j('/api/coach/roster/import', dt, { content: csv, team_id: red })).json;

const b = await chromium.launch();
const errs = [];
const ctx = await b.newContext({ ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
page.on('pageerror', (e) => errs.push(e.message));
let sha = 'build-A';
await page.route('**/api/live', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ live: true, git_sha: sha }) }));
await page.clock.install({ time: new Date() });
await page.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await page.evaluate((t) => localStorage.setItem('offdays.token', t), dt);
await page.goto(`${base}/app/coach.html`, { waitUntil: 'networkidle' });
if (await page.locator('#wizard-skip').isVisible().catch(() => false)) { await page.click('#wizard-skip'); await page.waitForTimeout(800); }
await page.click('#tabbar [data-tab="teams"]');
await page.locator('[data-open-team]', { hasText: '2031 Red' }).click();
await page.waitForSelector('#td-body table');
await page.evaluate(() => { window.__marker = 'same page'; });
const summary = async () => (await page.locator('#td-body .small.muted').first().innerText()).replace(/\s+/g, ' ');
check(/0 of 1 parents signed up/.test(await summary()), 'the team opens showing no parent signed up', `(${(await summary()).slice(0, 80)})`);

// 1) a change happens elsewhere: the parent signs up. Two minutes later the open team shows it, with no reload.
await j('/api/guardians/redeem', null, { code: imp.guardian_invites[0].code, display_name: 'Robert', email: `robert.${stamp}@example.com`, phone: '615-555-0101' });
await page.clock.runFor(125_000);
await page.waitForFunction(() => /1 of 1 parents signed up/.test(document.querySelector('#td-body .small.muted')?.innerText || ''), null, { timeout: 15000 });
check(true, 'two minutes later the open team shows the parent signed up');
check((await page.evaluate(() => window.__marker)) === 'same page', 'and the page was not reloaded');
check(/Updated \d/.test(await page.locator('#fresh-note').innerText()), 'a small "Updated" time shows in the corner');
await page.screenshot({ path: `${out}/1-updated.png` });

// 2) someone typing is left alone
await page.fill('#td-cname', 'Joel Wh');
const csv2 = `First Name,Last Name,Birth Year\nBen,Amden,2013\n`;
await j('/api/coach/roster/import', dt, { content: csv2, team_id: red, invite_guardians: false });
await page.clock.runFor(125_000);
await page.waitForTimeout(1500);
check((await page.inputValue('#td-cname')) === 'Joel Wh', 'while someone is typing, nothing is redrawn and their words stay');
check(/\b1 player\b/.test(await summary()) || /1 player/.test(await summary()), 'the new player is not shown yet', `(${(await summary()).slice(0, 40)})`);
// once they stop and clear it, the next refresh catches up
await page.fill('#td-cname', '');
await page.evaluate(() => document.activeElement && document.activeElement.blur());
await page.clock.runFor(30_000);
await page.clock.runFor(125_000);
await page.waitForFunction(() => /2 players/.test(document.querySelector('#td-body .small.muted')?.innerText || ''), null, { timeout: 15000 });
check(true, 'and when they stop, the next refresh catches up (2 players)');

// 3) a dialog open: left alone
await page.locator('#td-body [data-open-athlete]').first().click();
await page.waitForSelector('#athlete-dd h2');
await j('/api/teams', dt, { name: '2033 Gold' });
await page.clock.runFor(125_000);
await page.waitForTimeout(1000);
check(await page.locator('#athlete-dd h2').isVisible(), 'a player panel that is open is not wiped by a refresh');
await page.keyboard.press('Escape');

// 4) a new version of the app: an idle page reloads itself
await page.clock.runFor(30_000);
sha = 'build-B';
await page.clock.runFor(125_000);
await page.waitForFunction(() => window.__marker === undefined, null, { timeout: 20000 });
check(true, 'when the app has been updated, an idle page reloads itself');

// 5) a busy page is offered a button instead
await page.waitForSelector('#tabbar', { timeout: 20000 });
sha = 'build-B';
await page.evaluate(() => { window.__marker = 'second page'; });
await page.click('#tabbar [data-tab="families"]');
await page.waitForTimeout(500);
sha = 'build-C';
const box = page.locator('#msg-intro');
if (await box.count()) {
  await page.evaluate(() => { document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()); });
  await box.fill('Hi everyone, a draft note');
  await page.clock.runFor(125_000);
  await page.waitForSelector('#fresh-banner', { timeout: 10000 });
  check((await page.evaluate(() => window.__marker)) === 'second page' && (await box.inputValue()) === 'Hi everyone, a draft note', 'a page with words typed in is not reloaded: it offers an Update button and keeps the draft');
  await page.screenshot({ path: `${out}/2-banner.png` });
} else { check(false, 'the message box was not found'); }

check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
