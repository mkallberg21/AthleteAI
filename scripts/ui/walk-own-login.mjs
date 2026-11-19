// Everyone makes their own email and password login, and a director removes and replaces a coach.
// Run: node walk-own-login.mjs <base> <out-dir> <mail-file>
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
const lastLink = () => { const m = [...mail().matchAll(/create=([A-Za-z0-9_-]+)/g)]; return m.length ? m[m.length - 1][1] : ''; };
const stamp = Date.now();
const PW = 'sunny-orange-bicycle-77';
const JOEL = `joel.${stamp}@example.com`, SAM = `sam.${stamp}@example.com`, PARENT = `robert.${stamp}@example.com`, KID = `dillon.${stamp}@example.com`;

const made = (await j('/api/orgs', null, { name: 'Nashville Dogs', sport: 'lacrosse', accept_terms: true, director_name: 'Matt Kallberg' })).json;
const dtoken = made.director.token;
await j('/api/org/mail-hold', dtoken, { held: false }, 'PUT');
const red = (await j('/api/teams', dtoken, { name: '2031 Red' })).json.id;
const joel = (await j('/api/coach/staff', dtoken, { display_name: 'Joel White', email: JOEL, team_ids: [red] })).json;
const sam = (await j('/api/coach/staff', dtoken, { display_name: 'Sam Lee', email: SAM, team_ids: [] })).json;
await new Promise((r) => setTimeout(r, 1500));
check(/You are on 2031 Red/.test(mail()), 'adding a coach to a team emails them, naming the team');

const b = await chromium.launch();
const errs = [];
const ctx = await b.newContext({ ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
page.on('pageerror', (e) => errs.push(e.message));
page.on('dialog', (d) => d.accept());
await page.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); localStorage.setItem('offdays.awizard', 'done'); localStorage.setItem('offdays.pwizard', 'done'); } catch (e) {} });

// ---- a coach creates a login from the front page
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await page.click('.role-btn[data-role="coach"]');
await page.click('#coa-create-card summary');
await page.fill('#coa-create-email', JOEL);
const before = mail().length;
await page.click('#coa-create button[type="submit"]');
await page.waitForFunction(() => /is on its way/.test(document.querySelector('#coa-create-msg').innerText), null, { timeout: 15000 });
await page.screenshot({ path: `${out}/1-coach-create.png` });
await page.fill('#coa-create-email', `nobody.${stamp}@example.com`);
await page.click('#coa-create button[type="submit"]');
await page.waitForTimeout(800);
const reply2 = (await page.locator('#coa-create-msg').innerText()).trim();
check(/is on its way/.test(reply2), 'an unknown address gets the same reply');
await new Promise((r) => setTimeout(r, 1200));
const tok = lastLink();
check(tok.length > 20 && mail().length > before, 'an email with a link went to the coach');
check(!mail().includes(`nobody.${stamp}`), 'and none to the unknown address');
await page.goto(`${base}/app/index.html?create=${tok}`, { waitUntil: 'networkidle' });
await page.waitForSelector('#create-card:not(.hidden)');
await page.screenshot({ path: `${out}/2-choose-password.png` });
await page.fill('#create-pw', 'short');
await page.click('#create-go');
await page.waitForSelector('#create-err:not(.hidden)');
check(/at least 10/i.test(await page.locator('#create-err').innerText()), 'a short password is refused with a plain reason');
await page.fill('#create-pw', PW);
await Promise.all([page.waitForURL(/coach\.html/, { timeout: 20000 }), page.click('#create-go')]);
check(true, 'choosing a password signs the coach in and opens their dashboard');
await page.waitForTimeout(1500);

// ---- later: sign in with email and password, no link
await page.evaluate(() => localStorage.clear());
await page.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); } catch (e) {} });
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await page.click('.role-btn[data-role="coach"]');
await page.fill('#coach-email', JOEL);
await page.fill('#coach-pw', PW);
await Promise.all([page.waitForURL(/coach\.html/, { timeout: 20000 }), page.click('#panel-coach form.pw-signin button[type="submit"]')]);
check(true, 'the coach signs in later with just email and password');

// ---- the director removes Joel and gives his team to Sam
await page.evaluate(() => localStorage.clear());
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await page.evaluate((t) => localStorage.setItem('offdays.token', t), dtoken);
await page.goto(`${base}/app/coach.html`, { waitUntil: 'networkidle' });
if (await page.locator('#wizard-skip').isVisible().catch(() => false)) { await page.click('#wizard-skip'); await page.waitForTimeout(800); }
await page.click('#tabbar [data-tab="teams"]');
await page.evaluate(() => { let e = document.querySelector('#staff-list'); while (e) { if (e.classList && e.classList.contains('card')) { e.classList.remove('hidden'); e.classList.add('open'); if (e._foldOpen) e._foldOpen(); } e = e.parentElement; } });
await page.waitForSelector('[data-remove-coach]');
const joelSession = (await j('/api/login/password', null, { email: JOEL, password: PW })).json.token;
check((await j('/api/coach/teams', joelSession)).status === 200, 'Joel can reach his teams before he is removed');
const before2 = mail().length;
await page.locator('[data-remove-coach]').first().scrollIntoViewIfNeeded();
const joelBtn = page.locator('.staff-row', { hasText: 'Joel White' }).locator('[data-remove-coach]');
await joelBtn.click();
const box = page.locator('.staff-row', { hasText: 'Joel White' }).locator('[data-remove-box]');
await box.locator('[data-remove-heir]').selectOption({ label: 'Sam Lee' });
await page.screenshot({ path: `${out}/3-remove-box.png` });
await box.locator('[data-remove-go]').click();
await page.waitForFunction(() => /Joel White was removed/.test(document.querySelector('#staff-list').innerText), null, { timeout: 15000 });
const note = (await page.locator('#staff-list [role=status]').first().innerText()).replace(/\s+/g, ' ');
check(/2031 Red now belongs to Sam Lee, who was emailed/.test(note), 'the screen says who took over the team and that they were told', `(${note})`);
await page.screenshot({ path: `${out}/4-removed.png` });
check((await j('/api/coach/teams', joelSession)).status === 401, 'Joel\'s open session ended at once');
check((await j('/api/login/password', null, { email: JOEL, password: PW })).status === 401, 'and his password no longer signs him in');
check((await j('/api/coach/teams', joel.code)).status === 401, 'nor does his old link');
await new Promise((r) => setTimeout(r, 1200));
check(/now coaching 2031 Red/.test(mail().slice(before2)) && mail().slice(before2).includes(SAM), 'Sam was emailed that he now coaches 2031 Red');

// ---- a parent and a child
const csv = `First Name,Last Name,Birth Year,Parent Email\nDillon,Langdon,2013,${PARENT}\n`;
const imp = (await j('/api/coach/roster/import', dtoken, { content: csv, team_id: red })).json;
const red2 = (await j('/api/guardians/redeem', null, { code: imp.guardian_invites[0].code, display_name: 'Robert Langdon', email: PARENT, phone: '615-555-0101' })).json;
const kids = (await j('/api/coach/team-ranking?team_id=' + red, dtoken)).json.rows;
const kidId = kids[0].athlete_id;
await j('/api/guardians/consent', red2.token, { athlete_id: kidId, scope: 'participation', granted: true });
const kidLink = (await j(`/api/guardians/athlete-link/${kidId}`, red2.token, {})).json.link;
const kidCode = /code=([A-Za-z0-9]+)/.exec(kidLink)[1];

const ctx2 = await b.newContext({ ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } });
const p2 = await ctx2.newPage();
p2.on('pageerror', (e) => errs.push(e.message));
p2.on('dialog', (d) => d.accept());
await p2.addInitScript(() => { try { localStorage.setItem('offdays.pwizard', 'done'); } catch (e) {} });
await p2.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await p2.click('.role-btn[data-role="parent"]');
await p2.click('#par-create-card summary');
await p2.fill('#par-create-email', PARENT);
await p2.click('#par-create button[type="submit"]');
await p2.waitForFunction(() => /is on its way/.test(document.querySelector('#par-create-msg').innerText), null, { timeout: 15000 });
await new Promise((r) => setTimeout(r, 1200));
const ptok = lastLink();
await p2.goto(`${base}/app/index.html?create=${ptok}`, { waitUntil: 'networkidle' });
await p2.fill('#create-pw', PW);
await Promise.all([p2.waitForURL(/parent\.html/, { timeout: 20000 }), p2.click('#create-go')]);
check(true, 'a parent creates a login from the front page and lands in their account');
await p2.waitForSelector('#mylogin-card:not(.hidden)', { timeout: 15000 });
await p2.waitForFunction(() => /can sign in with/.test(document.querySelector('#mylogin').innerText), null, { timeout: 15000 });
await p2.screenshot({ path: `${out}/5-parent.png` });

// the child, signed in by the parent's link, makes their own login
const ctx3 = await b.newContext({ ...devices['iPad (gen 7)'] });
const p3 = await ctx3.newPage();
p3.on('pageerror', (e) => errs.push(e.message));
await p3.addInitScript(() => { try { localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
await p3.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await p3.evaluate((t) => localStorage.setItem('offdays.token', t), kidCode);
await p3.goto(`${base}/app/capture.html`, { waitUntil: 'networkidle' });
await p3.waitForSelector('#mylogin [data-ml-email]', { timeout: 20000 });
await p3.locator('#mylogin-card').scrollIntoViewIfNeeded();
await p3.fill('#mylogin [data-ml-email]', KID);
await p3.click('#mylogin [data-ml-go]');
await p3.waitForFunction(() => /We sent a link/.test(document.querySelector('#mylogin [data-ml-msg]').innerText), null, { timeout: 15000 });
await p3.screenshot({ path: `${out}/6-athlete-make.png` });
await new Promise((r) => setTimeout(r, 1200));
const ktok = lastLink();
await p3.goto(`${base}/app/index.html?create=${ktok}`, { waitUntil: 'networkidle' });
await p3.fill('#create-pw', PW);
await Promise.all([p3.waitForURL(/capture\.html/, { timeout: 20000 }), p3.click('#create-go')]);
check(true, 'the athlete finishes the link, chooses a password and lands on their training page');

await p3.evaluate(() => localStorage.clear());
await p3.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await p3.click('.role-btn[data-role="athlete"]');
await p3.fill('#ath-email', KID);
await p3.fill('#ath-pw', PW);
await Promise.all([p3.waitForURL(/capture\.html/, { timeout: 20000 }), p3.click('#ath-signin button[type="submit"]')]);
check(true, 'later the athlete signs in with email and password, no link');

// the parent can see it and switch it off
await p2.reload({ waitUntil: 'networkidle' });
await p2.waitForSelector('[data-kid-off]', { timeout: 15000 });
await p2.locator('#kidlogins').scrollIntoViewIfNeeded();
await p2.screenshot({ path: `${out}/7-parent-kid-login.png` });
check(/Dillon signs in with/.test(await p2.locator('#kidlogins').innerText()), 'the parent sees that Dillon signs in by email');
await p2.click('[data-kid-off]');
await p2.waitForFunction(() => /Turned off/.test(document.querySelector('#kidlogins').innerText), null, { timeout: 15000 });
check((await j('/api/login/password', null, { email: KID, password: PW })).status === 401, 'and turning it off ends it');
check((await j('/api/me', kidCode)).status === 200, 'while the link the parent sent still works');

check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
