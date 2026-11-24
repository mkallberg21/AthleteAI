// "Forgot your password?" for a director and a coach, start to finish in a browser, reading the real emails.
// Run against ms_server.py started with VERIFIED_SIGNUP=1:  node walk-forgot-password.mjs <base> <out-dir> <mail-file>
import { chromium, devices } from 'playwright';
import { mkdirSync, readFileSync } from 'node:fs';

const [base, out, mailFile] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what, extra = '') => { console.log(`${ok ? 'ok   ' : 'FAIL '}${what} ${extra}`); if (!ok) bad += 1; };
const mails = () => readFileSync(mailFile, 'utf-8').split(/-----\r?\n/).filter((m) => m.trim()).map((m) => ({
  to: (m.match(/^TO: (.*)$/m) || [])[1], subject: (m.match(/^SUBJECT: (.*)$/m) || [])[1], body: m,
  link: (m.match(/https?:\/\/[^\s"]+\?(verify|reset|confirm|create)=[A-Za-z0-9_\-]+/) || [])[0] }));
const settle = () => new Promise((r) => setTimeout(r, 1200));
const j = async (path, token, body, method) => {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = 'Bearer ' + token;
  const r = await fetch(base + path, { method: method || (body ? 'POST' : 'GET'), headers, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, json: await r.json().catch(() => ({})) };
};
const D = 'matt@maddoglacrosse.com', C = 'joel@example.com';
const OLD = 'a-good-pass-phrase-2026', NEW = 'another-good-phrase-2027';

// ---- a director who signed up the normal way (address verified by the sign-up link)
await j('/api/orgs/start', null, { name: 'Nashville Dogs', sport: 'lacrosse', director_name: 'Matt Kallberg', email: D, accept_terms: true });
await settle();
const verify = new URL(mails().find((m) => m.to === D).link).searchParams.get('verify');
const made = await j('/api/orgs/verify', null, { token: verify, password: OLD });
check(made.status === 201, 'the director signs up and verifies', JSON.stringify(made.json).slice(0, 80));
const dt = made.json.token || (made.json.director && made.json.director.token);

// ---- a coach who chose a password from the dashboard (address not confirmed yet)
const team = (await j('/api/teams', dt, { name: '2031 Red' })).json.id;
const coach = (await j('/api/coach/staff', dt, { display_name: 'Joel White', email: C, team_ids: [team] })).json;
const set = await j('/api/me/password', coach.code, { email: C, password: OLD }, 'PUT');
check(set.status === 200, 'the coach chooses a password', JSON.stringify(set.json));
await settle();

const b = await chromium.launch();
const errs = [];
const fresh = async () => {
  const ctx = await b.newContext({ ...devices['Desktop Chrome'], viewport: { width: 1280, height: 1000 } });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errs.push(e.message));
  await page.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); } catch (e) {} });
  return page;
};
const forgot = async (role, email) => {
  const page = await fresh();
  await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
  await page.click(`.role-btn[data-role="${role}"]`);
  await page.locator(`#panel-${role} .pw-forgot`).first().click();
  await page.waitForSelector('#pw-reset-card:not(.hidden)');
  await page.fill('#forgot-email', email);
  const before = mails().length;
  await page.click('#forgot-form button[type="submit"]');
  await page.waitForSelector('#forgot-done:not(.hidden)', { timeout: 15000 });
  const said = (await page.locator('#forgot-done').innerText()).replace(/\s+/g, ' ');
  await settle();
  return { page, said, got: mails().slice(before).filter((m) => m.to === email) };
};
const useLink = async (link, landing) => {
  const page = await fresh();
  await page.goto(link, { waitUntil: 'networkidle' });
  await page.waitForSelector('#link-step:not(.hidden)', { timeout: 15000 });
  await page.fill('#link-new', NEW);
  await page.click('#link-form button[type="submit"]');
  await page.waitForURL(/coach\.html/, { timeout: 20000 });
  await page.waitForLoadState('networkidle');
  check(true, `${landing}: the link lets them choose a new password and signs them in`);
  return page;
};
const login = async (email, password) => (await j('/api/login/password', null, { email, password })).status;

// ---------------------------------------------------------------- director
let r = await forgot('director', D);
check(/Check your email/.test(r.said), 'director: the page says to check email', r.said.slice(0, 90));
check(r.got.length === 1 && /reset=/.test(r.got[0].link || ''), 'director: one email arrives with a reset link', r.got.map((m) => m.subject).join(' | '));
await r.page.screenshot({ path: `${out}/1-director-asked.png` });
if (r.got[0]) {
  const p = await useLink(r.got[0].link, 'director');
  await p.screenshot({ path: `${out}/2-director-in.png` });
  check(await login(D, NEW) === 200 && await login(D, OLD) === 401, 'director: the new password works and the old one does not');
  const again = await fresh();
  await again.goto(r.got[0].link, { waitUntil: 'networkidle' });
  await again.waitForSelector('#link-step:not(.hidden)', { timeout: 15000 }).catch(() => {});
  if (await again.locator('#link-step').isVisible()) {
    await again.fill('#link-new', 'third-good-phrase-2028'); await again.click('#link-form button[type="submit"]');
    await again.waitForTimeout(1500);
  }
  check(await login(D, NEW) === 200, 'director: the link cannot be used a second time');
}

// ---------------------------------------------------------------- coach, address not confirmed
r = await forgot('coach', C);
check(/Check your email/.test(r.said), 'coach (not confirmed): the page still says to check email', r.said.slice(0, 60));
console.log(`info coach (not confirmed): emails that arrived = ${r.got.length} ${r.got.map((m) => m.subject).join(' | ')}`);
const unconfirmedGot = r.got.length;
await r.page.screenshot({ path: `${out}/3-coach-unconfirmed.png` });

// ---------------------------------------------------------------- coach, after confirming
const confirmMail = mails().filter((m) => m.to === C && /confirm=/.test(m.link || '')).pop();
check(!!confirmMail, 'coach: a confirm-your-address email was sent when the password was chosen');
if (confirmMail && !unconfirmedGot) {
  const cp = await fresh();
  await cp.goto(confirmMail.link, { waitUntil: 'networkidle' });
  await cp.waitForTimeout(1500);
  r = await forgot('coach', C);
  check(r.got.length === 1 && /reset=/.test(r.got[0].link || ''), 'coach (confirmed): one email arrives with a reset link', r.got.map((m) => m.subject).join(' | '));
}
if (r.got[0] && /reset=/.test(r.got[0].link || '')) {
  await useLink(r.got[0].link, 'coach');
  check(await login(C, NEW) === 200 && await login(C, OLD) === 401, 'coach: the new password works and the old one does not');
}

check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
