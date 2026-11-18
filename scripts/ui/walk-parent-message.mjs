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
check(/Add yours under Settings/.test(from), 'and tells a director with no email how replies would reach them');
await page.locator('#msg-box').scrollIntoViewIfNeeded();
await page.screenshot({ path: `${out}/1-box-held.png` });

// the director gives an email, releases the hold
await j('/api/me/password', dtoken, { password: 'a-long-password-9', email: DIR_EMAIL }, 'PUT');
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
