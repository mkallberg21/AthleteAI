// A director resends a coach (Joel White, 2031 Red) a new sign-in link from the Teams tab.
// Run: node walk-coach-resend-link.mjs <base> <out-dir> <mail-file>
import { chromium, devices } from 'playwright';
import { mkdirSync, readFileSync } from 'node:fs';

const [base, out, mailFile] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what, extra = '') => { console.log(`${ok ? 'ok   ' : 'FAIL '}${what} ${extra}`); if (!ok) bad += 1; };
const j = async (path, token, body, method) => {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = 'Bearer ' + token;
  const r = await fetch(base + path, { method: method || (body ? 'POST' : 'GET'), headers, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, json: await r.json().catch(() => ({})) };
};
const mail = () => readFileSync(mailFile, 'utf-8').split(String.fromCharCode(13)).join('');
const stamp = Date.now();
const made = (await j('/api/orgs', null, { name: 'Nashville Dogs', sport: 'lacrosse', accept_terms: true, director_name: 'Matt Kallberg' })).json;
const dtoken = made.director.token;
const red = (await j('/api/teams', dtoken, { name: '2031 Red' })).json.id;
const joel = (await j('/api/coach/staff', dtoken, { display_name: 'Joel White', email: `joel.${stamp}@example.com`, team_ids: [red] })).json;
const oldCode = joel.code;

const b = await chromium.launch();
const errs = [];
const ctx = await b.newContext({ ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
page.on('pageerror', (e) => errs.push(e.message));
const dialogs = [];
page.on('dialog', (d) => { dialogs.push(d.message()); d.accept(); });
await page.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await page.evaluate((t) => localStorage.setItem('offdays.token', t), dtoken);
await page.goto(`${base}/app/coach.html`, { waitUntil: 'networkidle' });
await page.evaluate(() => localStorage.setItem('offdays.tab.v2', 'teams'));
await page.reload({ waitUntil: 'networkidle' });
await page.waitForSelector('[data-resend-link]', { state: 'attached', timeout: 20000 });
if (await page.locator('#wizard-skip').isVisible().catch(() => false)) { await page.click('#wizard-skip'); await page.waitForTimeout(800); }
await page.click('#tabbar [data-tab="settings"]');
await page.evaluate(() => { let e = document.querySelector('#staff-list'); while (e) { if (e.classList && e.classList.contains('card')) { e.classList.remove('hidden'); e.classList.add('open'); if (e._foldOpen) e._foldOpen(); } e = e.parentElement; } });
await page.waitForSelector('[data-resend-link]', { timeout: 20000 });
const rows = await page.locator('[data-resend-link]').count();
check(rows === 1, 'one Resend sign-in link button, on the coach and not the director', `(${rows})`);

// 1) while email is on hold: nothing is sent, the director gets the link to pass on
await page.locator('[data-resend-link]').scrollIntoViewIfNeeded();
await page.locator('[data-resend-link]').click();
await page.waitForSelector('[data-resend-out] code', { timeout: 15000 });
let outText = (await page.locator('[data-resend-out]').innerText()).replace(/\s+/g, ' ');
check(dialogs.some((m) => /Send Joel White a new sign-in link/.test(m) && /old link stops working/.test(m)), 'it asks first, and says the old link stops working');
check(/Email is on hold, so nothing was sent/.test(outText) && /invite=|code=|\?/.test(outText), 'on hold it sends nothing and shows the link to pass on', `(${outText.slice(0, 90)})`);
check(mail() === '', 'no email went out');
await page.screenshot({ path: `${out}/1-held.png` });
const mid = await fetch(base + '/api/me', { headers: { Authorization: 'Bearer ' + oldCode } });
check(mid.status === 401, 'Joel\'s first link no longer works');

// 2) with email on: it is emailed straight away, naming the team
await j('/api/org/mail-hold', dtoken, { held: false }, 'PUT');
await page.locator('[data-resend-link]').click();
await page.waitForFunction(() => /Sent to/.test(document.querySelector('[data-resend-out]').innerText), null, { timeout: 15000 });
outText = (await page.locator('[data-resend-out]').innerText()).replace(/\s+/g, ' ');
check(/Sent to joel\./.test(outText) && /2031 Red/.test(outText), 'with email on it says it sent, and which team it names', `(${outText})`);
await page.screenshot({ path: `${out}/2-sent.png` });
await new Promise((r) => setTimeout(r, 1500));
const m = mail();
check(/To: joel\./i.test(m) || m.includes(`joel.${stamp}@example.com`), 'the email went to Joel');
check(/You are on 2031 Red/.test(m) && /new sign-in link/.test(m), 'it names 2031 Red and says the link is new');
check(/choose the team's drills and add video clips/.test(m), 'and says he can choose drills and add video clips');
check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
