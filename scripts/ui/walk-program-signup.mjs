// Starting a program by verifying an email, the login-only role pages, and the one program total.
// Run against ms_server.py started with VERIFIED_SIGNUP=1:  node walk-program-signup.mjs <base> <out-dir> <mail-file>
import { chromium, devices } from 'playwright';
import { mkdirSync, readFileSync } from 'node:fs';

const [base, out, mailFile] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what, extra = '') => { console.log(`${ok ? 'ok   ' : 'FAIL '}${what} ${extra}`); if (!ok) bad += 1; };
const mails = () => readFileSync(mailFile, 'utf-8').split(/-----\r?\n/).filter((m) => m.trim()).map((m) => ({
  to: (m.match(/^TO: (.*)$/m) || [])[1], subject: (m.match(/^SUBJECT: (.*)$/m) || [])[1], body: m,
  link: (m.match(/https?:\/\/[^\s"]+\?(verify|reset)=[A-Za-z0-9_\-]+/) || [])[0] }));
const mailsAfter = async (n) => {            // the mail file is written by the server a moment after the page hears back
  for (let i = 0; i < 50; i += 1) { const all = mails(); if (all.length >= n) return all; await new Promise((r) => setTimeout(r, 100)); }
  return mails();
};
const j = async (path, token, body, method) => {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = 'Bearer ' + token;
  const r = await fetch(base + path, { method: method || (body ? 'POST' : 'GET'), headers, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, json: await r.json().catch(() => ({})) };
};
const EMAIL = 'matt@maddoglacrosse.com';
const PW = 'a-good-pass-phrase-2026';

const b = await chromium.launch();
const errs = [];
const ctx = await b.newContext({ ...devices['Desktop Chrome'], viewport: { width: 1280, height: 1000 } });
const page = await ctx.newPage();
page.on('pageerror', (e) => errs.push(e.message));
await page.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });

// ---- the four buttons
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
const subs = await page.locator('.role-btn span:last-child').allInnerTexts();
check(JSON.stringify(subs) === JSON.stringify(['Sign in', 'Sign in', 'Sign in', 'Start or run a program']), 'the buttons say Sign in for athlete, parent and coach', JSON.stringify(subs));

for (const role of ['athlete', 'parent', 'coach']) {
  await page.click(`.role-btn[data-role="${role}"]`);
  const panel = page.locator(`#panel-${role}`);
  const visibleInputs = await panel.locator('input:visible').count();
  const text = (await panel.innerText()).replace(/\s+/g, ' ');
  check(visibleInputs === 2, `${role}: only an email and a password box`, `(${visibleInputs} boxes)`);
  check(/Forgot your password\?/.test(text), `${role}: Forgot your password is offered`);
  check(!/invite code|your code|claim code|Create my login|First time|paste/i.test(text), `${role}: no codes, no create a login, nothing else`, `(${text.slice(0, 120)})`);
  await page.screenshot({ path: `${out}/1-${role}.png` });
}

// ---- forgot password from each role opens the recovery card and asks for a link
for (const [role, nick] of [['athlete', 'ath'], ['parent', 'par'], ['coach', 'coach']]) {
  await page.click(`.role-btn[data-role="${role}"]`);
  const forgot = nick === 'coach' ? page.locator('#panel-coach .pw-forgot') : page.locator(`#${nick}-forgot`);
  await forgot.click();
  check(await page.locator('#pw-reset-card').isVisible() && await page.locator('#forgot-form').isVisible(), `${role}: Forgot your password opens the recovery form`);
  await page.click('#reset-cancel');
}

// ---- starting a program: the form asks for the email
await page.click('.role-btn[data-role="director"]');
check(await page.locator('#org-email').isVisible(), 'the program form asks for an email address');
await page.click('#create-org');
check(/program name and your name/.test(await page.locator('#oerr').innerText()), 'a blank form says what is missing');
await page.fill('#org-name', 'Nashville Dogs');
await page.fill('#org-director', 'Matt Kallberg');
await page.fill('#org-email', 'not-an-email');
await page.check('#org-terms');
await page.click('#create-org');
check(/Enter your email address/.test(await page.locator('#oerr').innerText()), 'a bad address is refused before anything is sent');
await page.fill('#org-email', EMAIL);
const before = mails().length;
await page.click('#create-org');
await page.waitForSelector('#org-token:not(.hidden)', { timeout: 15000 });
const box = (await page.locator('#org-token').innerText()).replace(/\s+/g, ' ');
check(/Check your email/.test(box) && box.includes(EMAIL) && /Verify email/.test(box), 'Create program says to check the email and verify it', `(${box.slice(0, 90)})`);
check(!(await page.locator('#org-name').isVisible()), 'the form gives way to the message');
await page.screenshot({ path: `${out}/2-check-email.png` });
let m = await mailsAfter(before + 1);
check(m.length === before + 1 && m[m.length - 1].to === EMAIL && /Verify your email/.test(m[m.length - 1].subject) && m[m.length - 1].link, 'one verification email was sent to that address with a link', m[m.length - 1]?.subject);
check(page.url().includes('coach.html') === false, 'the director is not let in yet');
const first = m[m.length - 1].link;

// resend retires the first link
await page.click('#org-resend');
await page.waitForFunction(() => /Check your email/.test(document.querySelector('#org-resend-note')?.innerText || ''), null, { timeout: 15000 });
m = await mailsAfter(before + 2);
const second = m[m.length - 1].link;
check(m.length === before + 2 && second !== first, 'Send it again sends a fresh link');

// the old link no longer works
const stale = await ctx.newPage();
await stale.goto(first, { waitUntil: 'networkidle' });
await stale.waitForFunction(() => /did not work/.test(document.querySelector('#verify-title')?.innerText || ''), null, { timeout: 15000 });
check(/expired or was already used/.test(await stale.locator('#verify-text').innerText()), 'an old link says it has expired and offers to start again');
await stale.close();

// the new one: verified, choose a password
const vp = await ctx.newPage();
vp.on('pageerror', (e) => errs.push(e.message));
await vp.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
await vp.goto(second, { waitUntil: 'networkidle' });
await vp.waitForSelector('#verify-form:not(.hidden)', { timeout: 15000 });
const vt = (await vp.locator('#verify-card').innerText()).replace(/\s+/g, ' ');
check(/your email is verified/.test(vt) && vt.includes(EMAIL) && vt.includes('Nashville Dogs'), 'the link says the email is verified and names the program', `(${vt.slice(0, 120)})`);
check(!vp.url().includes('verify='), 'the secret is out of the address bar');
await vp.screenshot({ path: `${out}/3-verified.png` });
await vp.fill('#verify-pw', 'short');
await vp.click('#verify-go');
await vp.waitForFunction(() => !document.querySelector('#verify-err')?.classList.contains('hidden'), null, { timeout: 15000 });
check(/10 characters|at least/i.test(await vp.locator('#verify-err').innerText()), 'a weak password is refused with a reason and the link still works', (await vp.locator('#verify-err').innerText()));
await vp.fill('#verify-pw', PW);
await Promise.all([vp.waitForURL(/coach\.html/, { timeout: 20000 }), vp.click('#verify-go')]);
await vp.waitForSelector('#wizard:not(.hidden)', { timeout: 20000 });
check(true, 'a good password signs the director in and starts the setup of teams, coaches and rosters');
await vp.waitForTimeout(800);
const wiz = (await vp.locator('#wizard').innerText()).replace(/\s+/g, ' ');
check(/How the program reaches you/.test(wiz), 'the first step is the director contact', `(${wiz.slice(0, 80)})`);
check((await vp.locator('#contact-email').inputValue()) === EMAIL, 'their email is already filled in');
await vp.screenshot({ path: `${out}/4-setup.png` });

// the link cannot be reused, and the login works
const reuse = await j('/api/orgs/verify', null, { token: second.split('verify=')[1], password: PW });
check(reuse.status === 401, 'the link cannot be used twice');
const login = await j('/api/login/password', null, { email: EMAIL, password: PW });
check(login.status === 200 && login.json.role === 'director', 'they can sign in with that email and password');
const dt = login.json.token;

// ---- one program total, however many teams
const t1 = (await j('/api/teams', dt, { name: '2031 Red' })).json.id;
const t2 = (await j('/api/teams', dt, { name: '2032 Blue' })).json.id;
const t3 = (await j('/api/teams', dt, { name: '2033 Gold' })).json.id;
const roster = (n, p) => 'First Name,Last Name,Birth Year\n' + Array.from({ length: n }, (_, i) => `${p}${i},Player,2013`).join('\n') + '\n';
const today = new Date(); const end = new Date(today.getTime() + 99 * 86400000);
const iso = (d) => d.toISOString().slice(0, 10);
await j('/api/org/season', dt, { starts_on: iso(today), ends_on: iso(end) }, 'PUT');

// open the setup on the rosters step while no roster is in yet, then put three rosters in and come back to the step
const wp = await ctx.newPage();
wp.on('pageerror', (e) => errs.push(e.message));
await wp.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); } catch (e) {} });
await wp.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await wp.evaluate(([t]) => { localStorage.setItem('offdays.token', t); sessionStorage.setItem('offdays.wizardStep', 'roster'); Object.keys(localStorage).filter((k) => k.startsWith('offdays.wizard.')).forEach((k) => localStorage.removeItem(k)); }, [dt]);
await wp.goto(`${base}/app/coach.html`, { waitUntil: 'networkidle' });
await wp.waitForSelector('#wizard:not(.hidden)', { timeout: 20000 });
await wp.waitForFunction(() => document.querySelector('#wizard-title')?.innerText.includes('rosters'), null, { timeout: 20000 });
check(await wp.locator('#wizard-total').isHidden(), 'before any roster is in there is no total to show');
await j('/api/coach/roster/import', dt, { content: roster(4, 'Red'), team_id: t1, invite_guardians: false });
await wp.click('#wizard-back'); await wp.waitForTimeout(600);
await wp.click('#wizard-next');
await wp.waitForFunction(() => !document.querySelector('#wizard-total')?.classList.contains('hidden'), null, { timeout: 20000 });
let total = (await wp.locator('#wizard-total').innerText()).replace(/\s+/g, ' ');
check(/4 players on 3 teams/.test(total), 'after the first roster the total is for the whole program', `(${total})`);
await j('/api/coach/roster/import', dt, { content: roster(3, 'Blue'), team_id: t2, invite_guardians: false });
await j('/api/coach/roster/import', dt, { content: roster(5, 'Gold'), team_id: t3, invite_guardians: false });
await wp.click('#wizard-back'); await wp.waitForTimeout(600);
await wp.click('#wizard-next');
await wp.waitForFunction(() => /12 players/.test(document.querySelector('#wizard-total')?.innerText || ''), null, { timeout: 20000 });
const inv = (await j('/api/org/invoice', dt)).json;
total = (await wp.locator('#wizard-total').innerText()).replace(/\s+/g, ' ');
check(total.includes('12 players on 3 teams') && total.includes(inv.total_display) && /not per team/.test(total), 'after three rosters it is one total for all three', `(${total})`);
check(inv.athletes === 12 && inv.total_display && inv.total_display !== '$0.00', 'and it is the real invoice for all 12 players', inv.total_display);
const wizText = await wp.locator('#wizard').innerText();
check((wizText.match(/\$\s?\d/g) || []).length === 1, 'exactly one dollar amount is on the roster step, not one per team', JSON.stringify(wizText.match(/\$\s?[\d,.]+/g)));
await wp.screenshot({ path: `${out}/5-total.png` });

// a coach never sees dollars: the total line is for the director only
const coach = (await j('/api/coach/staff', dt, { display_name: 'Joel White', email: 'joel@example.com', team_ids: [t1] })).json;
const cp = await ctx.newPage();
await cp.addInitScript(() => { try { localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
await cp.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await cp.evaluate(([t]) => localStorage.setItem('offdays.token', t), [coach.code]);
await cp.goto(`${base}/app/coach.html`, { waitUntil: 'networkidle' });
await cp.waitForTimeout(1500);
check(!/\$\s?\d/.test(await cp.locator('body').innerText()), 'a coach sees no dollar amount anywhere');

// ---- recover a forgotten password from the page
const rp = await ctx.newPage();
rp.on('pageerror', (e) => errs.push(e.message));
await rp.goto(`${base}/app/index.html#director`, { waitUntil: 'networkidle' });
await rp.click('#panel-director .pw-forgot');
await rp.fill('#forgot-email', EMAIL);
const mailsBefore = mails().length;
await rp.click('#forgot-form button[type="submit"]');
await rp.waitForSelector('#forgot-done:not(.hidden)', { timeout: 15000 });
m = await mailsAfter(mailsBefore + 1);
const reset = m[m.length - 1];
check(m.length === mailsBefore + 1 && reset.to === EMAIL && /reset/i.test(reset.subject) && reset.link, 'Forgot your password emails a reset link', reset?.subject);
await rp.goto(reset.link, { waitUntil: 'networkidle' });
await rp.fill('#link-new', 'another-good-pass-phrase-77');
await Promise.all([rp.waitForURL(/coach\.html/, { timeout: 20000 }), rp.click('#link-form button[type="submit"]')]);
check(true, 'the link lets them choose a new password and signs them in');
const relog = await j('/api/login/password', null, { email: EMAIL, password: 'another-good-pass-phrase-77' });
check(relog.status === 200, 'the new password works');

check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
