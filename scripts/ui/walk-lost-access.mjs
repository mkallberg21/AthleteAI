// A parent sends their athlete a new sign-in link after the athlete loses access. Run: node walk-lost-access.mjs <base> <out-dir>
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); if (!ok) bad++; };
const j = async (p, t, b, m) => { const r = await fetch(base + p, { method: m || (b ? 'POST' : 'GET'), headers: { 'Content-Type': 'application/json', ...(t ? { Authorization: `Bearer ${t}` } : {}) }, body: b ? JSON.stringify(b) : undefined }); return { status: r.status, body: await r.json().catch(() => ({})) }; };
const abs = (u) => (u.startsWith('http') ? u : base + u);

const made = (await j('/api/orgs', null, { name: 'Lost Access FC', sport: 'lacrosse', accept_terms: true, director_name: 'Joel' })).body;
const D = made.director.token;
const team = (await j('/api/teams', D, { name: 'U12' })).body.id;
await j('/api/coach/roster/import', D, { content: 'First Name,Last Name,Birth Year,Parent Email\nSam,Lost,2014,sam.mom@example.com\n', team_id: team });
const kid = (await j(`/api/coach/team-ranking?team_id=${team}`, D)).body.rows[0].athlete_id;
const inv = (await j('/api/coach/guardian-invites', D, { athlete_id: kid, email: 'sam.mom@example.com' })).body;
const parent = (await j('/api/guardians/redeem', null, { code: inv.code, display_name: 'Pat Lost', email: 'sam.mom@example.com', phone: '615-555-0101' })).body;
const P = parent.token || parent.code;
await j('/api/guardians/consent', P, { athlete_id: kid, scope: 'participation', granted: true });
const old = (await j(`/api/guardians/athlete-link/${kid}`, P, {})).body;   // the link the athlete had, now lost

const browser = await chromium.launch();
// the athlete's phone: signed in once with the first link
const kidCtx = await browser.newContext({ ...devices['iPhone 13'] });
const kidPage = await kidCtx.newPage();
await kidPage.goto(abs(old.link), { waitUntil: 'networkidle' }); await kidPage.waitForTimeout(1500);
check(kidPage.url().includes('capture.html'), 'the athlete was signed in with the first link');

// ... and has now lost access: their phone forgot the sign-in
await kidPage.evaluate(() => localStorage.clear());

// the PARENT opens their portal on a phone
const parentPage = await (await browser.newContext({ ...devices['iPhone 13'] })).newPage();
await parentPage.goto(`${base}/app/index.html?code=${P}`, { waitUntil: 'networkidle' }); await parentPage.waitForTimeout(2500);
if (await parentPage.locator('#pwizard-skip').isVisible().catch(() => false)) { await parentPage.click('#pwizard-skip'); await parentPage.waitForTimeout(800); }
const btn = parentPage.locator('[data-signin]');
check(await btn.count() === 1, 'the parent portal has one "new sign-in link" button');
check(/new sign-in link/i.test(await btn.innerText()), `its label says what it is for (${(await btn.innerText()).trim().replace(/\s+/g, ' ')})`);
const top = await btn.evaluate((e) => Math.round(e.getBoundingClientRect().top + window.scrollY));
const stats = await btn.evaluate((b) => Math.round(b.closest('.card').querySelector('.stat-row').getBoundingClientRect().top + window.scrollY));
check(top < stats, `the button sits above the weekly numbers (${top}px vs ${stats}px)`);
await btn.scrollIntoViewIfNeeded();
await parentPage.screenshot({ path: `${out}/parent-button.png` });
await btn.click(); await parentPage.waitForTimeout(1200);
const link = await parentPage.locator('[data-link-field]').inputValue().catch(() => '');
check(/\?code=/.test(link), 'one tap gives a link');
check(await parentPage.locator('[data-copy]').count() === 1 && await parentPage.locator('a[href^="sms:"]').count() === 1 && await parentPage.locator('a[href^="mailto:"]').count() === 1, 'Copy, Text and Email are offered');
await parentPage.screenshot({ path: `${out}/parent-link.png` });

// the athlete taps the OLD link (the one they lost): told what to do
await kidPage.goto(abs(old.link), { waitUntil: 'networkidle' }); await kidPage.waitForTimeout(1500);
const said = (await kidPage.locator('#err:not(.hidden)').innerText().catch(() => '')).trim();
check(/ask your parent to send you a new one/i.test(said), `the old link tells the child what to do ("${said}")`);
check(!/athlete code again/i.test(said), 'and does not ask a child for a code they do not have');
await kidPage.screenshot({ path: `${out}/kid-dead-link.png` });

// typing a wrong code still gets the ordinary message
await kidPage.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await kidPage.evaluate(() => localStorage.clear());
await kidPage.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await kidPage.locator('.role-btn', { hasText: /athlete/i }).first().click(); await kidPage.waitForTimeout(500);
await kidPage.fill('#token', 'ZZZZZZ'); await kidPage.click('#signin-form button[type=submit]'); await kidPage.waitForTimeout(1200);
const typed = (await kidPage.locator('#err:not(.hidden)').innerText().catch(() => '')).trim();
check(typed.length > 0 && !/ask your parent to send you a new one/i.test(typed), `a wrongly typed code gets the ordinary message ("${typed}")`);

// the NEW link signs the athlete back in, and it is the same athlete
await kidPage.goto(abs(link), { waitUntil: 'networkidle' }); await kidPage.waitForTimeout(2000);
check(kidPage.url().includes('capture.html'), 'the new link signs the athlete back in');
const me = await kidPage.evaluate(async () => (await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('offdays.token') } })).json());
check(me.athlete_id === kid, 'and it is the same athlete, with their history');

// the lost link stays dead
const oldAgain = await j('/api/me', old.code);
check(oldAgain.status === 401, 'the lost link no longer works anywhere');
await browser.close();
console.log(bad ? `FAILED: ${bad}` : 'all good');
process.exit(bad ? 1 : 0);
