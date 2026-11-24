// An athlete with no working link asks to be let in; the coach taps once; the phone is signed in.
// Run against a scratch server that has POST /__athlete/{org}/{team}/{name} (an athlete with a consenting parent):
//   node walk-access-requests.mjs <base> <out-dir> <mail-file>
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
const mails = () => readFileSync(mailFile, 'utf-8').split(/-----\r?\n/).filter((m) => m.trim()).map((m) => ({
  to: (m.match(/^TO: (.*)$/m) || [])[1], subject: (m.match(/^SUBJECT: (.*)$/m) || [])[1], body: m }));

const made = (await j('/api/orgs', null, { name: 'Nashville Dogs', sport: 'lacrosse', accept_terms: true, director_name: 'Matt Kallberg' })).json;
const dt = made.director.token;
const red = (await j('/api/teams', dt, { name: '2031 Red' })).json.id;
const joel = (await j('/api/coach/staff', dt, { display_name: 'Joel White', email: 'joel@example.com', team_ids: [red] })).json;
await j(`/__athlete/${made.org_id}/${red}/${encodeURIComponent('Ryder Cole')}`, null, {});
await j(`/__athlete/${made.org_id}/${red}/${encodeURIComponent('Parker Browne')}`, null, {});

const b = await chromium.launch();
const errs = [];
const phoneCtx = await b.newContext({ ...devices['iPhone 13'] });
const phone = await phoneCtx.newPage();
phone.on('pageerror', (e) => errs.push('phone: ' + e.message));
const deskCtx = await b.newContext({ ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } });
const desk = await deskCtx.newPage();
desk.on('pageerror', (e) => errs.push('coach: ' + e.message));
await desk.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); } catch (e) {} });

// ---------------------------------------------------------------- the athlete, on a link that stopped working
await phone.goto(`${base}/app/index.html?code=Z99999`, { waitUntil: 'networkidle' });
await phone.waitForSelector('#err:not(.hidden)', { timeout: 15000 });
const dead = (await phone.locator('#err').innerText()).replace(/\s+/g, ' ');
check(/Ask your coach to let you in below/.test(dead), 'a dead link points the athlete at the way back in', dead);
check(await phone.locator('#ask-card').isVisible(), 'the "ask your coach" card is on the athlete sign-in page');
const order = await phone.evaluate(() => {
  const a = document.getElementById('ask-card').getBoundingClientRect().top;
  const e = document.getElementById('ath-signin-card').getBoundingClientRect().top;
  return a < e;
});
check(order, 'and it comes before the email and password form, which a child cannot use');
await phone.screenshot({ path: `${out}/1-athlete-ask.png`, fullPage: true });

await phone.fill('#ask-name', 'Ryder');
await phone.click('#ask-go');
check(/first and last name/.test(await phone.locator('#ask-err').innerText()), 'a first name alone is sent back');
await phone.fill('#ask-name', 'ryder cole');
await phone.click('#ask-go');
await phone.waitForSelector('#ask-wait:not(.hidden)', { timeout: 15000 });
const number = (await phone.locator('#ask-number').innerText()).trim();
check(/^\d\d$/.test(number), 'the athlete is shown a two digit number', number);
await phone.screenshot({ path: `${out}/2-athlete-waiting.png`, fullPage: true });

// ---------------------------------------------------------------- the coach
await desk.goto(`${base}/app/index.html`, { waitUntil: 'domcontentloaded' });
await desk.evaluate((t) => localStorage.setItem('offdays.token', t), joel.code);
await desk.goto(`${base}/app/coach.html`, { waitUntil: 'networkidle' });
if (await desk.locator('#wizard-skip').isVisible().catch(() => false)) await desk.click('#wizard-skip');
await desk.waitForSelector('#access-requests .ar-row', { timeout: 20000 });
const row = (await desk.locator('#access-requests .ar-row').first().innerText()).replace(/\s+/g, ' ');
check(/Ryder Cole \(2031 Red\) is asking to be let in/.test(row), 'the coach sees who is asking, and their team', row.slice(0, 140));
check(row.includes(`Number on their screen: ${number}`), 'with the same number the athlete sees');
check((await desk.locator('#access-requests [data-ar-yes]').count()) === 1, 'and one "Let them in" button');
await desk.screenshot({ path: `${out}/3-coach-request.png` });
for (const tab of ['today', 'families', 'teams']) {
  await desk.click(`#tabbar [data-tab="${tab}"]`);
  if (!(await desk.locator('#access-requests .ar-row').first().isVisible())) { check(false, `the request shows on the ${tab} tab`); }
}
check(true, 'the request stays in view on every tab');

await desk.click('#access-requests [data-ar-yes]');
await desk.waitForSelector('#access-requests .ar-done', { timeout: 10000 });
check(/Ryder Cole is in/.test(await desk.locator('#access-requests .ar-done').innerText()), 'one tap, and the coach is told it worked');
await desk.screenshot({ path: `${out}/4-coach-done.png` });

await phone.waitForURL(/capture\.html/, { timeout: 20000 });
await phone.waitForLoadState('networkidle');
const me = await phone.evaluate(async () => {
  const r = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('offdays.token') } });
  return r.json();
});
check(me.role === 'athlete' && me.display_name === 'Ryder Cole', 'the phone that asked is signed in as that athlete, with nothing more to do', `${me.role} ${me.display_name}`);
check(await phone.evaluate(() => localStorage.getItem('offdays.ask')) === null, 'and the phone has forgotten its secret');
await phone.screenshot({ path: `${out}/5-athlete-in.png` });

// ---------------------------------------------------------------- closing the page and coming back; a coach saying no
const phone2Ctx = await b.newContext({ ...devices['iPhone 13'] });
const phone2 = await phone2Ctx.newPage();
phone2.on('pageerror', (e) => errs.push('phone2: ' + e.message));
await phone2.goto(`${base}/app/index.html#athlete`, { waitUntil: 'networkidle' });
await phone2.fill('#ask-name', 'Parker Browne');
await phone2.click('#ask-go');
await phone2.waitForSelector('#ask-wait:not(.hidden)');
const n2 = (await phone2.locator('#ask-number').innerText()).trim();
await phone2.goto('about:blank');
await phone2.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
check(await phone2.locator('#ask-wait').isVisible() && (await phone2.locator('#ask-number').innerText()).trim() === n2,
  'coming back to the page later shows the same number, still waiting');

// the director sees it as well
const dirCtx = await b.newContext({ ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } });
const dir = await dirCtx.newPage();
dir.on('pageerror', (e) => errs.push('director: ' + e.message));
await dir.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); } catch (e) {} });
await dir.goto(`${base}/app/index.html`, { waitUntil: 'domcontentloaded' });
await dir.evaluate((t) => localStorage.setItem('offdays.token', t), dt);
await dir.goto(`${base}/app/coach.html`, { waitUntil: 'networkidle' });
if (await dir.locator('#wizard-skip').isVisible().catch(() => false)) await dir.click('#wizard-skip');
await dir.waitForSelector('#access-requests .ar-row', { timeout: 20000 });
check(/Parker Browne/.test(await dir.locator('#access-requests').innerText()), 'the director sees the request too');
await dir.click('#access-requests [data-ar-no]');
await phone2.waitForSelector('#ask-ended:not(.hidden)', { timeout: 20000 });
const no = (await phone2.locator('#ask-ended-text').innerText()).replace(/\s+/g, ' ');
check(/did not let this one through/.test(no), 'a no is said plainly to the athlete', no);
check(await phone2.evaluate(() => localStorage.getItem('offdays.token')) === null, 'and nobody is signed in');
await phone2.screenshot({ path: `${out}/6-athlete-no.png`, fullPage: true });

// ---------------------------------------------------------------- the emails
await new Promise((r) => setTimeout(r, 800));
const all = mails();
const asked = all.filter((m) => /is asking to be let in/.test(m.subject || ''));
check(asked.some((m) => m.to === 'joel@example.com' && /Ryder Cole/.test(m.subject)), 'the coach was emailed about the request');
check(asked.every((m) => /\/app\/coach\.html/.test(m.body) && !/secret|token=/.test(m.body)), 'the email points at the dashboard and carries no way in');
const told = all.filter((m) => /let Ryder sign in/.test(m.subject || ''));
check(told.length === 1 && told[0].to === 'dana@example.com', 'the parent was told a coach let their child in', told.map((m) => m.subject).join(' | '));
check(!all.some((m) => /Parker/.test(m.subject || '') && /let Parker sign in/.test(m.subject)), 'a no sends the parent nothing');

check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
