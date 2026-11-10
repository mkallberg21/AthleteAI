// A coach or director signs in with email and password, and recovers a forgotten one.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8010';
const T = path.join(process.env.LOCALAPPDATA || os.tmpdir(), 'Temp', 'pw');
fs.mkdirSync(T, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const EMAIL = `joel.${Date.now()}@example.com`;
const PW1 = 'ocean-lamp-seven-pine', PW2 = 'violet-anchor-march-42';

const j = async (url, body, headers = {}, method = 'POST') =>
  (await fetch(base + url, { method, headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(body) }));

// a program and its director, the way a real one starts
const org = await (await j('/api/orgs', { name: 'Password FC', director_name: 'Joel' })).json();
const code = org.director.token;
const auth = { Authorization: `Bearer ${code}` };
const set = await (await j('/api/me/password', { email: EMAIL, password: PW1 }, auth, 'PUT')).json();
check(/^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(set.recovery_code || ''), 'a password is set and a recovery code comes back once');
let recovery = set.recovery_code;

const b = await chromium.launch();
for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const page = await (await b.newContext(opts)).newPage();
  page.on('pageerror', (e) => console.log('PAGE ERROR', e.message.slice(0, 150)));
  await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
  await page.locator('.role-btn', { hasText: /director/i }).first().click();
  const form = page.locator('#panel-director .pw-signin');
  check(await form.isVisible(), `${tag}: the director panel leads with email and password`);
  check(!(await page.locator('#panel-director .code-fallback').evaluate((d) => d.open)), `${tag}: the code form is tucked away`);
  await page.screenshot({ path: path.join(T, `${tag}-1-signin.png`) });

  // wrong password: a plain message, still on the page
  await page.fill('#director-email', EMAIL); await page.fill('#director-pw', 'not-the-password-1');
  await form.locator('button[type=submit]').click(); await page.waitForTimeout(800);
  check(/do not match/i.test(await page.locator('#director-pwerr').innerText()), `${tag}: a wrong password says so`);

  // right password: lands on the dashboard
  await page.fill('#director-pw', PW1);
  await Promise.all([page.waitForURL(/coach\.html/, { timeout: 8000 }), form.locator('button[type=submit]').click()]);
  check(true, `${tag}: the right password reaches the dashboard`);
  await page.waitForTimeout(1500);
  // A brand-new program opens on the first-visit walkthrough, with the tab bar
  // hidden behind it; an older one opens on the tabs. Either means the session worked.
  const shown = (await page.locator('#tabbar').isVisible()) || (await page.locator('#wizard').isVisible());
  check(shown, `${tag}: and the dashboard loads with that session`);

  // forgot: recovery code -> new password -> sign in with it
  await page.evaluate(() => localStorage.clear());
  await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
  await page.locator('.role-btn', { hasText: /director/i }).first().click();
  await page.fill('#director-email', EMAIL);
  await page.locator('#panel-director .pw-forgot').click();
  check(await page.locator('#pw-reset-card').isVisible(), `${tag}: Forgot your password opens the reset form`);
  check((await page.inputValue('#reset-email')) === EMAIL, `${tag}: the email is carried over`);
  await page.fill('#reset-code', 'AAAA-BBBB-CCCC'); await page.fill('#reset-new', PW2);
  await page.locator('#pw-reset-form button[type=submit]').click(); await page.waitForTimeout(800);
  check(/not right|already been used/i.test(await page.locator('#reset-err').innerText()), `${tag}: a wrong code is refused`);
  await page.fill('#reset-code', recovery); await page.fill('#reset-new', 'short');
  await page.locator('#pw-reset-form button[type=submit]').click(); await page.waitForTimeout(800);
  check(/at least 10/i.test(await page.locator('#reset-err').innerText()), `${tag}: a weak new password is refused, the code is kept`);
  await page.fill('#reset-new', PW2);
  await page.locator('#pw-reset-form button[type=submit]').click(); await page.waitForTimeout(1000);
  const done = await page.locator('#reset-done').innerText();
  const fresh = (done.match(/[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}/) || [])[0];
  check(!!fresh && fresh !== recovery, `${tag}: a new recovery code is shown, and it is different`);
  await page.screenshot({ path: path.join(T, `${tag}-2-reset-done.png`) });
  recovery = fresh;
  await page.fill('#director-pw', PW2);
  await Promise.all([page.waitForURL(/coach\.html/, { timeout: 8000 }), page.locator('#panel-director .pw-signin button[type=submit]').click()]);
  check(true, `${tag}: the new password signs in`);

  // the old password is dead; the six-character code still opens the door
  const old = await j('/api/login/password', { email: EMAIL, password: PW1 });
  check(old.status === 401, `${tag}: the old password no longer works`);
  const viaCode = await fetch(base + '/api/me', { headers: auth });
  check(viaCode.status === 200, `${tag}: the six-character code still works`);
  await page.context().close();
  // re-arm for the next viewport: choose the second password back as the first
  const r2 = await j('/api/login/reset', { email: EMAIL, code: recovery, new_password: PW1 });
  recovery = (await r2.json()).recovery_code;
}
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good'); process.exit(bad ? 1 : 0);
