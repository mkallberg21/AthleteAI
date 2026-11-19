// "Say it in your own words": the fields cannot be edited, only placed.
// Run: node walk-recognition-fields.mjs <base> <out-dir>
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';

const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what, extra = '') => { console.log(`${ok ? 'ok   ' : 'FAIL '}${what} ${extra}`); if (!ok) bad += 1; };
const j = async (path, token, body, method) => {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = 'Bearer ' + token;
  const r = await fetch(base + path, { method: method || (body ? 'POST' : 'GET'), headers, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, json: await r.json().catch(() => ({})) };
};
const made = (await j('/api/orgs', null, { name: 'Nashville Dogs', sport: 'lacrosse', accept_terms: true, director_name: 'Matt Kallberg' })).json;
const dt = made.director.token;
const red = (await j('/api/teams', dt, { name: '2031 Red' })).json.id;
await j('/api/coach/roster/import', dt, { content: 'First Name,Last Name,Birth Year\nDillon,Langdon,2013\n', team_id: red, invite_guardians: false });

const b = await chromium.launch();
const errs = [];
const ctx = await b.newContext({ ...devices['Desktop Chrome'], viewport: { width: 1280, height: 1000 } });
await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: base });
const page = await ctx.newPage();
page.on('pageerror', (e) => errs.push(e.message));
await page.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await page.evaluate((t) => localStorage.setItem('offdays.token', t), dt);
await page.goto(`${base}/app/coach.html`, { waitUntil: 'networkidle' });
if (await page.locator('#wizard-skip').isVisible().catch(() => false)) { await page.click('#wizard-skip'); await page.waitForTimeout(800); }
await page.click('#tabbar [data-tab="settings"]');
await page.evaluate(() => { let e = document.querySelector('#recognition-list'); while (e) { if (e.classList && e.classList.contains('card')) { e.classList.remove('hidden'); e.classList.add('open'); if (e._foldOpen) e._foldOpen(); } e = e.parentElement; } });
await page.waitForSelector('[data-milestone="first_session"] [data-recog-body]', { timeout: 20000 });
const row = page.locator('[data-milestone="first_session"]');
const box = row.locator('[data-recog-body]');
const text = () => box.evaluate((el) => window.__recogText ? window.__recogText(el) : null);
// expose the page's own reader so the walk checks what would actually be saved
await page.evaluate(() => { window.__recogText = (el) => { let o=''; (function w(n){ n.childNodes.forEach((c)=>{ if(c.nodeType===3) o+=c.nodeValue; else if(c.nodeType===1){ if(c.dataset&&c.dataset.token) o+=c.dataset.token; else if(c.tagName==='BR') o+='\n'; else { w(c); } } }); })(el); return o; }; });

const chips = await box.locator('.recog-chip').count();
check(chips >= 1, 'the shipped wording shows its fields as blocks, not text', `(${chips} fields)`);
check(!/\{first_name\}/.test(await box.innerText()), 'the braces are not visible: it reads "first name", not {first_name}');
await row.scrollIntoViewIfNeeded();
await page.screenshot({ path: `${out}/1-editor.png` });

// 1) typing into a field does nothing: click on the first field and type
const before = await text();
await box.locator('.recog-chip').first().click();
await page.keyboard.type('XYZ');
const afterType = await text();
check(!/\{first_name\}XYZ|\{firs.*XYZ.*t_name\}/.test(afterType) && !/first_na/.test(afterType.replace(/\{first_name\}/g, '')), 'typing on a field never changes the field', `(${afterType.slice(0, 60).replace(/\n/g, '/')})`);
check((afterType.match(/\{first_name\}/g) || []).length === (before.match(/\{first_name\}/g) || []).length, 'every field is still intact after typing on it');

// 2) a field is one block: Backspace removes the whole field, never part of it
await box.evaluate((el) => { el.innerHTML = 'Hi <span class="recog-chip" contenteditable="false" data-token="{first_name}">first name</span> well done'; });
await box.evaluate((el) => { const c = el.querySelector('.recog-chip'); const r = document.createRange(); r.setStartAfter(c); r.collapse(true); const s = window.getSelection(); s.removeAllRanges(); s.addRange(r); el.focus(); });
await page.keyboard.press('Backspace');
const afterBs = await text();
check(afterBs === 'Hi  well done' || afterBs === 'Hi  well done'.replace('  ', ' ') || !/first/.test(afterBs), 'Backspace removes the whole field at once, never half of it', `(${JSON.stringify(afterBs)})`);

// 3) the buttons put a real field in
await box.evaluate((el) => { el.innerHTML = 'Well done '; el.focus(); const r = document.createRange(); r.selectNodeContents(el); r.collapse(false); const s = window.getSelection(); s.removeAllRanges(); s.addRange(r); });
await row.locator('[data-recog-insert="{streak}"]').click();
await row.locator('[data-recog-insert="{first_name}"]').click();
const afterInsert = await text();
check(/Well done \{streak\}\s+\{first_name\}/.test(afterInsert.replace(/\u00a0/g, ' ')), 'the field buttons put real fields in, one after the other, where the caret was', `(${JSON.stringify(afterInsert)})`);
check((await box.locator('.recog-chip').count()) === 2, 'and they show as blocks');

// 4) a field typed out by hand with the wrong name is refused with a reason
await box.evaluate((el) => { el.innerHTML = ''; el.focus(); });
await page.keyboard.type('Great work {firstname}!');
await row.locator('[data-recog-save]').click();
await page.waitForFunction(() => /is not a field/.test(document.querySelector('[data-milestone="first_session"] .recog-err')?.innerText || ''), null, { timeout: 15000 });
const errText = (await row.locator('.recog-err').innerText()).replace(/\s+/g, ' ');
check(/\{firstname\} is not a field/.test(errText) && /buttons/.test(errText), 'a field with a different name is refused, and the reason is on the screen', `(${errText})`);
await page.screenshot({ path: `${out}/2-refused.png` });

// 5) a field typed out correctly becomes a real block when the box is left, and saves
await box.evaluate((el) => { el.innerHTML = ''; el.focus(); });
await page.keyboard.type('Great work {first_name}, ');
await page.locator('h1, #whoami').first().click();
await page.waitForTimeout(300);
check((await box.locator('.recog-chip').count()) === 1, 'a field typed correctly turns into a real field when you leave the box');
await row.locator('[data-recog-insert="{streak}"]').click();
await page.keyboard.type('days!');
await row.locator('[data-recog-save]').click();
await page.waitForFunction(() => /Saved/.test(document.querySelector('[data-milestone="first_session"] .recog-err')?.innerText || ''), null, { timeout: 15000 });
const saved = (await j('/api/coach/recognition', dt)).json.milestones.find((m) => m.key === 'first_session');
check((saved.bodies || [saved.body])[0] === 'Great work {first_name}, {streak} days!', 'it saves exactly as written, fields intact', `(${JSON.stringify((saved.bodies || [saved.body])[0])})`);

// 6) the preview fills the fields in with a real name
await row.locator('[data-recog-preview]').click();
await page.waitForFunction(() => /Dillon/.test(document.querySelector('[data-milestone="first_session"] .recog-preview')?.innerText || ''), null, { timeout: 15000 });
check(/Great work Dillon, 10 days!/.test((await row.locator('.recog-preview').innerText()).replace(/\s+/g, ' ')), 'the preview shows the fields filled in for a real player');

// 7) a new line stays a line break, and a blank line still splits wordings
await box.evaluate((el) => { el.innerHTML = ''; el.focus(); });
await page.keyboard.type('First way {first_name}');
await page.keyboard.press('Enter'); await page.keyboard.press('Enter');
await page.keyboard.type('Second way {streak}');
await page.locator('h1, #whoami').first().click();
await row.locator('[data-recog-save]').click();
await page.waitForFunction(() => /Saved/.test(document.querySelector('[data-milestone="first_session"] .recog-err')?.innerText || ''), null, { timeout: 15000 });
const two = (await j('/api/coach/recognition', dt)).json.milestones.find((m) => m.key === 'first_session');
check((two.bodies || []).length === 2, 'Enter twice still means a second wording', `(${(two.bodies || []).length} wordings)`);

check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
