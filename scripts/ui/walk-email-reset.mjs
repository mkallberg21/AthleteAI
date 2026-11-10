// A coach forgets their password and gets back in by email, unattended. Real browser, desktop and phone.
// The server runs with a mail provider pointed at a local file (OFFDAYS_SMTP_HOST=file), so nothing leaves
// the machine; the walk reads the "emails" the server wrote, opens the link from the message, and carries on.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8012';
const MAILDIR = process.argv[3] || 'C:/tmp/er_mail';
const T = path.join(process.env.LOCALAPPDATA || os.tmpdir(), 'Temp', 'pw');
fs.mkdirSync(T, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const j = (u, b, h = {}, m = 'POST') => fetch(base + u, { method: m, headers: { 'Content-Type': 'application/json', ...h }, body: JSON.stringify(b) });

const mails = () => (fs.existsSync(MAILDIR) ? fs.readdirSync(MAILDIR).sort().map((f) => JSON.parse(fs.readFileSync(path.join(MAILDIR, f), 'utf8'))) : []);
const lastTo = (to) => mails().filter((m) => m.to === to).pop();
const linkIn = (m, kind) => (m.text.match(new RegExp(`https?://[^\\s]*\\?${kind}=[A-Za-z0-9_-]+`)) || [])[0];
const local = (u) => u.replace(/^https?:\/\/[^/]+/, base);

// Ask-for-a-link is limited per source address (8 in 15 minutes) and every walk runs from 127.0.0.1,
// so two back-to-back runs would trip the limit that is there to stop a flood. The local test server
// exposes a way to clear it; a real server does not.
await fetch(base + '/api/_test/reset-throttle', { method: 'POST' }).catch(() => {});

const b = await chromium.launch();
for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const stamp = Date.now();
  const EMAIL = `${tag}.coach.${stamp}@example.com`;
  const PW1 = `first-passphrase-${stamp}`, PW2 = `second-passphrase-${stamp}`;
  const org = await (await j('/api/orgs', { name: `Reset ${tag} ${stamp}`, director_name: 'Joel' })).json();
  const dir = { Authorization: `Bearer ${org.director.token}` };

  // --- the director sets a password from Settings and is sent a confirm link
  const set = await (await j('/api/me/password', { email: EMAIL, password: PW1 }, dir, 'PUT')).json();
  check(set.confirm_sent === true && !set.recovery_code, `${tag}: setting a password emails a confirm link and hands out no recovery code`);
  const confirmMail = lastTo(EMAIL);
  check(!!confirmMail && /not monitored/i.test(confirmMail.text), `${tag}: the message says nobody reads replies`);
  check(!(confirmMail.headers || {})['Reply-To'], `${tag}: and carries no Reply-To`);

  // --- before confirming: asking for a link sends nothing
  const before = mails().length;
  await j('/api/login/forgot', { email: EMAIL });
  check(mails().length === before, `${tag}: an unconfirmed address is sent no reset link`);

  // --- open the confirm link in the browser
  const ctx = await b.newContext(opts);
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.log('PAGE ERROR', e.message.slice(0, 160)));
  await page.goto(local(linkIn(confirmMail, 'confirm')), { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#confirmed-step:not(.hidden)', { timeout: 8000 }).catch(() => {});
  check(await page.locator('#confirmed-step').isVisible(), `${tag}: the confirm link says "your email is confirmed"`);
  check(!page.url().includes('confirm='), `${tag}: and the secret is gone from the address bar`);
  await page.screenshot({ path: path.join(T, `${tag}-10-confirmed.png`) });

  // --- forgot: from the sign-in page
  await page.goto(base + '/app/index.html#coach', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(600);
  await page.locator('#panel-coach .pw-forgot').click();
  check(await page.locator('#forgot-step').isVisible() && await page.locator('#code-step').isHidden(), `${tag}: "Forgot your password?" offers email-me-a-link first`);
  await page.fill('#forgot-email', EMAIL);
  const sentBefore = mails().length;
  await page.click('#forgot-form button[type=submit]');
  await page.waitForSelector('#forgot-done:not(.hidden)', { timeout: 8000 }).catch(() => {});
  const said = await page.locator('#forgot-done').innerText();
  check(/check your email/i.test(said), `${tag}: it says to check email (${said.slice(0, 50).replace(/\n/g, ' ')}...)`);
  check(mails().length === sentBefore + 1, `${tag}: exactly one email went out`);
  await page.screenshot({ path: path.join(T, `${tag}-11-forgot.png`) });

  // --- an address that does not exist gets the SAME words and no email
  await page.fill('#forgot-email', `nobody.${stamp}@example.com`);
  const n0 = mails().length;
  await page.click('#forgot-form button[type=submit]');
  await page.waitForTimeout(900);
  const said2 = await page.locator('#forgot-done').innerText();
  check(said2 === said && mails().length === n0, `${tag}: an unknown address gets the identical reply and no email`);

  // --- open the reset link, choose a password
  const resetMail = lastTo(EMAIL);
  check(/reset/i.test(resetMail.subject), `${tag}: the email is a reset link (${resetMail.subject.slice(0, 40)})`);
  await page.goto(local(linkIn(resetMail, 'reset')), { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#link-step:not(.hidden)', { timeout: 8000 }).catch(() => {});
  check(await page.locator('#link-step').isVisible() && !page.url().includes('reset='), `${tag}: the link opens "Choose a new password" and the secret leaves the address bar`);
  await page.fill('#link-new', 'short');
  await page.click('#link-form button[type=submit]'); await page.waitForTimeout(700);
  check(/at least 10/i.test(await page.locator('#link-err').innerText()), `${tag}: a weak password is refused with a reason`);
  check(await page.locator('#link-step').isVisible(), `${tag}: and the link is still good`);
  await page.screenshot({ path: path.join(T, `${tag}-12-choose.png`) });
  await page.fill('#link-new', PW2);
  await page.click('#link-form button[type=submit]');
  await page.waitForURL(/coach\.html/, { timeout: 10000 }).catch(() => {});
  check(/coach\.html/.test(page.url()), `${tag}: choosing a password signs them straight in to the dashboard`);
  check(mails().filter((m) => m.to === EMAIL).pop().subject.toLowerCase().includes('changed'), `${tag}: a "your password was changed" notice goes to the same address`);

  // --- the old password is dead, the new works, the link cannot be used again
  check((await j('/api/login/password', { email: EMAIL, password: PW1 })).status === 401, `${tag}: the old password no longer works`);
  check((await j('/api/login/password', { email: EMAIL, password: PW2 })).status === 200, `${tag}: the new one does`);
  await page.goto(local(linkIn(resetMail, 'reset')), { waitUntil: 'domcontentloaded' });
  await page.fill('#link-new', 'yet-another-passphrase-9').catch(() => {});
  await page.click('#link-form button[type=submit]').catch(() => {});
  await page.waitForTimeout(900);
  check(/expired|already used/i.test(await page.locator('#forgot-err').innerText().catch(() => '')), `${tag}: opening the same link again says it was already used`);
  await ctx.close();
}
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good'); process.exit(bad ? 1 : 0);
