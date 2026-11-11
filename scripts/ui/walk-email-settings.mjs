// Settings: set a password, see "not confirmed", open the emailed link, see "confirmed", resend, change address.
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
const toAddr = (to) => mails().filter((m) => m.to === to);

await fetch(base + '/api/_test/reset-throttle', { method: 'POST' }).catch(() => {});
const b = await chromium.launch();
for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const stamp = Date.now();
  const A = `${tag}.set.${stamp}@example.com`, B = `${tag}.moved.${stamp}@example.com`, PW = `settings-passphrase-${stamp}`;
  const org = await (await j('/api/orgs', { name: `Settings ${tag} ${stamp}`, accept_terms: true, director_name: 'Joel' })).json();
  const ctx = await b.newContext(opts);
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.log('PAGE ERROR', e.message.slice(0, 160)));
  await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => localStorage.setItem('offdays.token', t), org.director.token);
  await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(3000);
  if (await page.locator('#wizard-skip').isVisible().catch(() => false)) { await page.click('#wizard-skip'); await page.waitForTimeout(800); }
  await page.click('#tabbar [data-tab="settings"]'); await page.waitForTimeout(500);
  await page.evaluate(() => { let e = document.querySelector('#password-card'); while (e) { if (e.classList && e.classList.contains('card')) e.classList.add('open'); e = e.parentElement; } });

  await page.fill('#pw-email', A); await page.fill('#pw-new', PW);
  await page.click('#pw-save'); await page.waitForTimeout(1500);
  check(await page.locator('#pw-recovery').isHidden(), `${tag}: with email working no recovery code is shown`);
  check(/emailed you a link/i.test(await page.locator('#pw-note').innerText()), `${tag}: it says a confirm link was emailed`);
  check(await page.locator('#pw-unverified').isVisible() && await page.locator('#pw-verified').isHidden(), `${tag}: the card says "not confirmed yet"`);
  check(toAddr(A).length === 1, `${tag}: one email went to ${A.split('@')[0]}`);
  await page.locator('#password-card').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(T, `${tag}-13-settings-unconfirmed.png`) });

  await page.click('#pw-resend'); await page.waitForTimeout(1200);
  check(toAddr(A).length === 2, `${tag}: "Send the link again" sends another`);

  const link = (toAddr(A).pop().text.match(/https?:\/\/[^\s]*\?confirm=[A-Za-z0-9_-]+/) || [])[0];
  const fresh = await ctx.newPage();
  await fresh.goto(link.replace(/^https?:\/\/[^/]+/, base), { waitUntil: 'domcontentloaded' });
  await fresh.waitForSelector('#confirmed-step:not(.hidden)', { timeout: 8000 }).catch(() => {});
  check(await fresh.locator('#confirmed-step').isVisible(), `${tag}: opening the link confirms it`);
  await fresh.close();

  await page.reload({ waitUntil: 'domcontentloaded' }); await page.waitForTimeout(3000);
  if (await page.locator('#wizard-skip').isVisible().catch(() => false)) { await page.click('#wizard-skip'); await page.waitForTimeout(800); }
  await page.click('#tabbar [data-tab="settings"]'); await page.waitForTimeout(500);
  await page.evaluate(() => { let e = document.querySelector('#password-card'); while (e) { if (e.classList && e.classList.contains('card')) e.classList.add('open'); e = e.parentElement; } });
  check(await page.locator('#pw-verified').isVisible() && await page.locator('#pw-confirm-row').isHidden(), `${tag}: Settings now says "confirmed" and the resend row is gone`);
  await page.locator('#password-card').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(T, `${tag}-14-settings-confirmed.png`) });

  await page.locator('#pw-email-change summary').click();
  await page.fill('#pw-new-email', B); await page.fill('#pw-email-pass', 'not-the-password');
  await page.click('#pw-email-save'); await page.waitForTimeout(900);
  check(/not right/i.test(await page.locator('#pw-note').innerText()), `${tag}: changing the address needs the current password`);
  await page.fill('#pw-email-pass', PW);
  await page.click('#pw-email-save'); await page.waitForTimeout(1500);
  check(toAddr(B).length === 1, `${tag}: the NEW address was emailed a confirm link`);
  check(await page.locator('#pw-unverified').isVisible(), `${tag}: and is "not confirmed yet" until it is opened`);
  const n = mails().length;
  await j('/api/login/forgot', { email: B });
  check(mails().length === n, `${tag}: the unconfirmed new address gets no reset link`);
  await ctx.close();
}
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good'); process.exit(bad ? 1 : 0);
