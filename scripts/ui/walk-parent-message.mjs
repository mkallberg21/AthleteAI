// A director sends the join email to every parent as a message from 0FFDAYS on their behalf.
// Run: node walk-parent-message.mjs <base> <out-dir> <mail-file>
import { chromium, devices } from 'playwright';
import { mkdirSync, readFileSync } from 'node:fs';

const [base, out, mailFile] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what, extra = '') => { console.log(`${ok ? 'ok   ' : 'FAIL '}${what} ${extra}`); if (!ok) bad += 1; };
const j = async (path, token, body, method) => {
  const r = await fetch(base + path, { method: method || (body ? 'POST' : 'GET'), headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, json: await r.json().catch(() => ({})) };
};
const mail = () => readFileSync(mailFile, 'utf-8').split(String.fromCharCode(13)).join('');
const stamp = Date.now();
const DIR_EMAIL = `matt.${stamp}@nashvilledogs.example`;
const made = (await j('/api/orgs', null, { name: 'Nashville Dogs', sport: 'lacrosse', accept_terms: true, director_name: 'Matt Kallberg' })).json;
const dtoken = made.director.token;
const team = (await j('/api/teams', dtoken, { name: '2031 Red' })).json.id;
// a roster imported while email is on hold: nobody is emailed
const csv = `First Name,Last Name,Birth Year,Parent Email\nDillon,Langdon,2013,robert.${stamp}@example.com\nKillian,Langdon,2015,robert.${stamp}@example.com\nBen,Amden,2013,jess.${stamp}@example.com\nCole,Dretler,2014,adam.${stamp}@example.com\n`;
await j('/api/coach/roster/import', dtoken, { content: csv, team_id: team });
check(mail() === '', 'nothing goes out while email is on hold');

const b = await chromium.launch();
const errs = [];
const ctx = await b.newContext({ ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
page.on('pageerror', (e) => errs.push(e.message));
page.on('dialog', (d) => d.accept());
await page.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await page.evaluate((t) => localStorage.setItem('offdays.token', t), dtoken);
await page.goto(`${base}/app/coach.html`, { waitUntil: 'networkidle' });
await page.evaluate(() => localStorage.setItem('offdays.tab.v2', 'families'));
await page.reload({ waitUntil: 'networkidle' });
const unfold = () => page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));   // cards start folded
await page.waitForSelector('#families-card:not(.hidden)', { timeout: 20000 });
await unfold();
await page.waitForSelector('#msg-from', { timeout: 20000 });
await page.waitForFunction(() => document.querySelector('#msg-from').innerText.length > 10, null, { timeout: 15000 });
let from = (await page.locator('#msg-from').innerText()).replace(/\s+/g, ' ');
check(/Matt Kallberg \(Nashville Dogs\) via 0FFDAYS/.test(from), 'the box says who the email will be from', `(${from.slice(0, 90)}...)`);
check(/on hold/.test(from), 'and that email is on hold');
check(/Confirm your email below/.test(from), 'and tells a director with no confirmed email how replies would reach them');
check(await page.locator('#msg-email-send').isVisible(), 'and offers to email them a confirmation link');
await page.locator('#msg-box').scrollIntoViewIfNeeded();
await page.screenshot({ path: `${out}/1-box-held.png` });

// --- while email is on hold the director sends from their own email: they choose THEIR email service once
await ctx.route(/mail\.google\.com|outlook\.live\.com|outlook\.office\.com|yahoo\.com/, (r) => r.fulfill({ status: 200, body: 'ok' }));
const firstNudge = page.locator('button[data-nudge]').first();
await firstNudge.click();
await page.waitForSelector('#families a.btn-link', { timeout: 15000 });
const popup1 = page.waitForEvent('popup');
await page.locator('#families a.btn-link').first().click();
await page.waitForSelector('[role=dialog]', { timeout: 10000 });
const chooser = (await page.locator('[role=dialog]').innerText()).replace(/\s+/g, ' ');
check(/Which email do you use\?/.test(chooser) && /Gmail/.test(chooser) && /Outlook.com or Hotmail/.test(chooser) && /Microsoft 365/.test(chooser) && /Yahoo/.test(chooser) && /mail app on this computer/.test(chooser), 'a click on Send email asks which email service they use', '');
await page.screenshot({ path: `${out}/1b-chooser.png` });
await page.click('[data-mail-pick="gmail"]');
const pop = await popup1;
await pop.waitForLoadState().catch(() => {});
const gurl = decodeURIComponent(pop.url());
check(gurl.startsWith('https://mail.google.com/mail/?view=cm') && new RegExp(`to=(robert|jess|adam)[.]${stamp}@example[.]com`).test(gurl) && /su=.*set up /.test(gurl) && /invite=[A-Z0-9-]{14}/.test(gurl), 'it opens Gmail in the browser with the parent, the subject and the message filled in', `(${gurl.slice(0, 80)}...)`);
await pop.close();
check(/opens in Gmail/.test((await page.locator('#msg-mailapp').innerText())), 'and remembers Gmail');
const popup2 = page.waitForEvent('popup');
await page.locator('#families a.btn-link').first().click();
const pop2 = await popup2;
check(!(await page.locator('[role=dialog]').count()), 'the next time it goes straight to Gmail without asking');
await pop2.close();
await page.click('#msg-mailapp-change');
check((await page.locator('#msg-mailapp').innerText()).trim() === '', 'and Change forgets the choice');
await page.reload({ waitUntil: 'networkidle' });
await page.waitForSelector('#families-card:not(.hidden)', { timeout: 20000 });
await unfold();
await page.waitForSelector('#msg-from');

// the director gives an email, releases the hold
// --- the director confirms their email: a link arrives, they click it
await page.fill('#msg-email', DIR_EMAIL);
await page.click('#msg-email-send');
await page.waitForSelector('#msg-email-check', { timeout: 15000 });
check(/waiting/.test(await page.locator('#msg-sender').innerText()) && !/Replies come to/.test(await page.locator('#msg-from').innerText()), 'it says it is waiting for the click, and replies are not set up yet');
await new Promise((r) => setTimeout(r, 1500));
const confirmMail = mail().split('-----\n').filter((m) => m.includes(`TO: ${DIR_EMAIL}`)).pop() || '';
check(/confirm your email for 0FFDAYS messages/.test(confirmMail) && /never reads your email/.test(confirmMail), 'a confirmation email arrives at that address');
const sToken = (confirmMail.match(/[?]sender=([A-Za-z0-9_-]+)/) || [])[1];
const other = await ctx.newPage();
await other.goto(`${base}/app/index.html?sender=${sToken}`, { waitUntil: 'networkidle' });
await other.waitForFunction(() => /confirmed/i.test(document.querySelector('#sender-title').innerText), null, { timeout: 15000 });
check(/Your email is confirmed/.test(await other.locator('#sender-title').innerText()) && new RegExp(DIR_EMAIL.replace(/\./g, '\\.')).test(await other.locator('#sender-text').innerText()), 'clicking it shows a confirmation page that names the address');
check(!other.url().includes('sender='), 'and the secret leaves the address bar');
await other.screenshot({ path: `${out}/1c-confirmed-page.png` });
await other.close();
await page.click('#msg-email-check');
await page.waitForFunction(() => /confirmed/.test(document.querySelector('#msg-sender').innerText), null, { timeout: 15000 });
await j('/api/org/mail-hold', dtoken, { held: false }, 'PUT');
await new Promise((r) => setTimeout(r, 1500));
const base0 = mail().length;                       // setting an email sends the director their own confirm link
const fresh = () => mail().slice(base0);
await page.reload({ waitUntil: 'networkidle' });
await page.waitForSelector('#families-card:not(.hidden)', { timeout: 20000 });
await unfold();
await page.waitForSelector('#msg-from');
await page.waitForFunction(() => /Replies come to/.test(document.querySelector('#msg-from').innerText), null, { timeout: 15000 });
from = (await page.locator('#msg-from').innerText()).replace(/\s+/g, ' ');
check(new RegExp(`Replies come to ${DIR_EMAIL.replace(/\./g, '\\.')}`).test(from) && !/on hold/.test(from), 'with an email on file the box says replies come to the director, and email is on', `(${from.slice(0, 110)}...)`);

// write a note, preview it
await page.fill('#msg-intro', 'Hi everyone, this is Matt. We are starting a pilot with 0FFDAYS.\n\nYou will each get your own link.');
await page.click('#msg-preview');
await page.waitForSelector('#msg-out:not(.hidden)');
const prev = (await page.locator('#msg-out').innerText()).replace(/\s+/g, ' ');
check(/From: Matt Kallberg \(Nashville Dogs\) via 0FFDAYS/.test(prev) && new RegExp(`Reply to: ${DIR_EMAIL.replace(/\./g, '\\.')}`).test(prev), 'the preview shows who it is from and where replies go');
check(/Hi everyone, this is Matt/.test(prev) && /Sent by 0FFDAYS on behalf of Matt Kallberg/.test(prev), 'it shows the note and the on-behalf line');
check(fresh() === '', 'a preview sends nothing');
await page.screenshot({ path: `${out}/2-preview.png` });

// a test goes only to the director
await page.click('#msg-test');
await page.waitForFunction(() => /Sent a test to/.test(document.querySelector('#msg-out').innerText), null, { timeout: 15000 });
const tmail = fresh();
check(tmail.includes(`TO: ${DIR_EMAIL}`) && (tmail.match(/^TO: /gm) || []).length === 1, 'a test reaches only the director');
check(/^FROM: "?Matt Kallberg \(Nashville Dogs\) via 0FFDAYS"? <no-reply@mail\.0ffdays\.com>/m.test(tmail) && tmail.includes(`REPLY-TO: ${DIR_EMAIL}`), 'and carries the director as sender and reply address');
check(/SUBJECT: TEST: /.test(tmail), 'and is marked as a test');

// send to all the families that can be invited
await page.waitForSelector('#fam-all');
await page.click('#fam-all');
await page.click('#fam-bulk-send');
await page.waitForSelector('#fam-bulk-result:not(.hidden)', { timeout: 20000 });
const res = (await page.locator('#fam-bulk-result').innerText()).replace(/\s+/g, ' ');
check(/Sent to 3 parents from 0FFDAYS/.test(res) && /Matt Kallberg \(Nashville Dogs\) via 0FFDAYS/.test(res) && res.includes(DIR_EMAIL), 'the result says 3 families were emailed, as whom, and where replies go', `(${res.slice(0, 120)}...)`);
await page.screenshot({ path: `${out}/3-sent.png` });
await new Promise((r) => setTimeout(r, 2000));
const all = fresh();
const msgs = all.split('-----\n').filter((m) => m.trim() && !/SUBJECT: TEST:/.test(m));
check(msgs.length === 3, 'three emails went out, one per family, straight away', `(${msgs.length})`);
check(msgs.every((m) => m.includes(`REPLY-TO: ${DIR_EMAIL}`) && /FROM: "?Matt Kallberg/.test(m)), 'every one is from the director with replies to them');
check(msgs.every((m) => m.includes('Hi everyone, this is Matt.')), "every one carries the director's note");
check(msgs.every((m) => /invite=[A-Z0-9-]{14}/.test(m)), 'every one has its own join link');
const langdon = msgs.find((m) => m.includes(`TO: robert.${stamp}@example.com`));
check(langdon && /Dillon and Killian/.test(langdon), 'the Langdons got one email naming both boys');
const links = msgs.map((m) => (m.match(/invite=([A-Z0-9-]+)/) || [])[1]);
check(new Set(links).size === 3, 'and the three links are different');
check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
