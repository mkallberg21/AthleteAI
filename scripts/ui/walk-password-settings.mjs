// Inside the dashboard: set a password, see the recovery code once, change it, and a
// director hands a coach a reset code that the coach then spends.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8010';
const T = path.join(process.env.LOCALAPPDATA || os.tmpdir(), 'Temp', 'pw');
fs.mkdirSync(T, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const j = (u, b, h = {}, m = 'POST') => fetch(base + u, { method: m, headers: { 'Content-Type': 'application/json', ...h }, body: JSON.stringify(b) });
const stamp = Date.now();
const DIR_EMAIL = `dir.${stamp}@example.com`, COACH_EMAIL = `coach.${stamp}@example.com`;

const org = await (await j('/api/orgs', { name: 'Settings FC', director_name: 'Joel' })).json();
const dirAuth = { Authorization: `Bearer ${org.director.token}` };
await j('/api/teams', { name: '2031 Red' }, dirAuth);
const staff = await (await j('/api/coach/staff', { display_name: 'Sam Hill', email: COACH_EMAIL, team_ids: [] }, dirAuth)).json();
const coachCode = staff.code;
// the coach chooses a password
const coachSet = await (await j('/api/me/password', { email: COACH_EMAIL, password: 'sams-first-passphrase' }, { Authorization: `Bearer ${coachCode}` }, 'PUT')).json();

const b = await chromium.launch();
for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const page = await (await b.newContext(opts)).newPage();
  page.on('pageerror', (e) => console.log('PAGE ERROR', e.message.slice(0, 150)));
  await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => { localStorage.setItem('offdays.token', t); localStorage.setItem(`offdays.wizard.${1}.d`, 'done'); }, org.director.token);
  await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(3000);
  if (await page.locator('#wizard-skip').isVisible().catch(() => false)) { await page.click('#wizard-skip'); await page.waitForTimeout(1000); }
  await page.evaluate(() => { document.querySelectorAll('.tab-off').forEach((c) => c.classList.remove('tab-off')); document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()); });

  check(await page.locator('#password-card').isVisible(), `${tag}: the Sign in with a password card is on the dashboard`);
  if (await page.locator('#pw-set').isVisible()) {
    await page.fill('#pw-email', `${tag}.${DIR_EMAIL}`); await page.fill('#pw-new', 'short');
    await page.click('#pw-save'); await page.waitForTimeout(700);
    check(/at least 10/i.test(await page.locator('#pw-note').innerText()), `${tag}: a weak password is refused with a reason`);
    await page.fill('#pw-new', 'violet-anchor-march-42');
    await page.click('#pw-save'); await page.waitForTimeout(1200);
    const code = await page.locator('#pw-recovery-code').innerText();
    check(/^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(code), `${tag}: the recovery code is shown (${code})`);
    check(await page.locator('#pw-change').isHidden(), `${tag}: no second password form while the recovery code is up`);
    await page.screenshot({ path: path.join(T, `${tag}-3-settings.png`) });
    await page.click('#pw-recovery-done'); await page.waitForTimeout(500);
    check(await page.locator('#pw-recovery').isHidden() && await page.locator('#pw-change').isVisible(), `${tag}: after I have written it down, the code goes and Change password appears`);
    await page.locator('#password-card').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(T, `${tag}-3-settings.png`) });
    await page.fill('#pw-current', 'wrong-current-password'); await page.fill('#pw-next', 'another-long-passphrase-1');
    await page.click('#pw-change-save'); await page.waitForTimeout(700);
    check(/not right/i.test(await page.locator('#pw-note').innerText()), `${tag}: changing needs the current password`);
  }

  // the director issues the coach a reset code
  await page.locator('#staff-card').scrollIntoViewIfNeeded();
  const btn = page.locator('[data-reset-code]').first();
  check(await btn.count() > 0, `${tag}: the coach list offers "Give a reset code"`);
  await btn.click(); await page.waitForTimeout(1000);
  const shown = await page.locator('[data-reset-out]').first().innerText();
  const reset = (shown.match(/[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}/) || [])[0];
  check(!!reset, `${tag}: a one-time code appears for the director to read out (${reset ? 'ok' : shown.slice(0, 60)})`);
  await page.screenshot({ path: path.join(T, `${tag}-4-reset-code.png`) });
  // the coach spends it
  const done = await j('/api/login/reset', { email: COACH_EMAIL, code: reset, new_password: `new-${tag}-passphrase-77` });
  check(done.status === 200, `${tag}: the coach spends it and chooses a new password`);
  const again = await j('/api/login/reset', { email: COACH_EMAIL, code: reset, new_password: 'a-second-try-passphrase' });
  check(again.status === 401, `${tag}: the same code does not work twice`);
  const old = await j('/api/login/password', { email: COACH_EMAIL, password: 'sams-first-passphrase' });
  check(old.status === 401, `${tag}: the coach's old password is gone`);
  // put the coach back for the next viewport
  await j('/api/coach/staff/' + staff.id + '/reset-code', {}, dirAuth).then(async (r) => {
    const c = (await r.json()).reset_code;
    await j('/api/login/reset', { email: COACH_EMAIL, code: c, new_password: 'sams-first-passphrase' });
  });
  await page.context().close();
}
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good'); process.exit(bad ? 1 : 0);
