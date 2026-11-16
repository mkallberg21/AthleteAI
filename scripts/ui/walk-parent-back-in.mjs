// A parent on a new phone gets back in by email, then sends their athlete a new link.
// Run: node walk-parent-back-in.mjs <base> <out-dir> <path-to-mail-file>
// The server is started with a mail provider that writes each message to <mail-file> (see the test harness).
import { chromium, devices } from 'playwright';
import { mkdirSync, readFileSync, existsSync } from 'node:fs';

const [base, out, mailFile] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const checks = [];
const check = (name, ok, extra = '') => { checks.push(ok); console.log(`${ok ? 'PASS' : 'FAIL'} ${name} ${extra}`); };

const post = async (path, body, token) => {
  const r = await fetch(base + path, { method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: JSON.stringify(body) });
  return { status: r.status, json: await r.json().catch(() => ({})) };
};
const get = async (path, token) => {
  const r = await fetch(base + path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  return { status: r.status, json: await r.json().catch(() => ({})) };
};

// --- a club with one family, the way a director would have set it up
const email = 'kathy.walk@example.com';
const made = await post('/api/orgs', { name: 'Walk Dogs', sport: 'lacrosse', accept_terms: true, director_name: 'Joel' });
const dir = made.json.director.token;
const team = (await post('/api/teams', { name: 'U12' }, dir)).json.id;
await post('/api/coach/roster/import', { content: `First Name,Last Name,Birth Year,Parent Email\nSam,Walker,2014,${email}\n`, team_id: team }, dir);
const rows = (await get(`/api/coach/team-ranking?team_id=${team}`, dir)).json.rows;
const kid = rows[0].athlete_id;
const inv = (await post('/api/coach/guardian-invites', { athlete_id: kid, email }, dir)).json;
const parent = (await post('/api/guardians/redeem', { code: inv.code, display_name: 'Kathy Walker', email, phone: '615-555-0101' })).json;
await post('/api/guardians/consent', { athlete_id: kid, scope: 'participation', granted: true }, parent.token);
const held = await fetch(base + '/api/org/mail-hold', { method: 'PUT', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${dir}` }, body: JSON.stringify({ held: false }) });
check('director released the email hold', held.ok);

const browser = await chromium.launch();
const phone = await browser.newContext({ ...devices['iPhone 13'] });      // a NEW phone: nothing saved
const page = await phone.newPage();
await page.goto(base + '/app/index.html', { waitUntil: 'networkidle' });
await page.click('.role-btn[data-role="parent"]');
await page.waitForSelector('#parent-back-open', { state: 'visible' });
check('the parent panel offers "Get back in"', await page.isVisible('#parent-back-open'));
await page.screenshot({ path: `${out}/1-parent-panel.png` });

await page.click('#parent-back-open');
await page.fill('#parent-back-email', email);
await page.screenshot({ path: `${out}/2-ask.png` });
await page.click('#parent-back-send');
await page.waitForSelector('#parent-back-done:not(.hidden)');
const said = await page.textContent('#parent-back-done');
check('the page confirms without saying who is a parent', /on its way/.test(said) && /director/i.test(said), said.slice(0, 60));
await page.screenshot({ path: `${out}/3-sent.png` });

// the same words for a stranger
await page.fill('#parent-back-email', 'nobody@example.com');
await page.click('#parent-back-send');
await page.waitForTimeout(600);
check('a stranger is told exactly the same thing', (await page.textContent('#parent-back-done')) === said);

// open the emailed link on the new phone
await new Promise((r) => setTimeout(r, 1500));
const mail = existsSync(mailFile) ? readFileSync(mailFile, 'utf8') : '';
const m = mail.match(/[?&]parent=([A-Za-z0-9_\-]+)/g);
check('exactly one email went to the real parent (none to the stranger)', !!m && m.length === 1 && !/nobody@/.test(mail), String(m && m.length));
const link = m ? `${base}/app/index.html${m[m.length - 1].replace(/^&/, '?')}` : '';
await page.goto(link, { waitUntil: 'networkidle' });
await page.waitForURL(/parent\.html/, { timeout: 10000 });
check('opening the link lands on the parent portal', /parent\.html/.test(page.url()));
check('the secret is not left in the address bar', !/parent=/.test(page.url()));
// A family that has never made a link sees the first-time step; one that has sees the returning button.
const sendBtn = page.locator("text=/Get Sam's link|Send Sam a new sign-in link/").first();
await sendBtn.waitFor({ state: 'visible', timeout: 10000 });
await page.screenshot({ path: `${out}/4-portal.png` });
check('it is the same parent and sees their child', /Sam/.test(await sendBtn.textContent()));

// the old phone is signed out; the link is dead
const oldPhone = await get('/api/me', parent.token);
check('the old phone was signed out', oldPhone.status === 401, String(oldPhone.status));
const ctx2 = await browser.newContext({ ...devices['iPhone 13'] });
const p2 = await ctx2.newPage();
await p2.goto(link, { waitUntil: 'networkidle' });
await p2.waitForSelector('#parent-back-err:not(.hidden)', { timeout: 10000 });
check('using the link a second time says so and offers to ask again',
  /expired or was already used/.test(await p2.textContent('#parent-back-err')) && (await p2.isVisible('#parent-back-email')));
await p2.screenshot({ path: `${out}/5-dead-link.png` });

// and the whole point: send the athlete a link
await sendBtn.click();
await page.waitForSelector('[data-link-field]', { timeout: 15000 });
await page.screenshot({ path: `${out}/5b-athlete-link.png` });
const href = await page.inputValue('[data-link-field]');
check('the parent gets a whole address to send', /^https?:\/\//.test(href), href.replace(/code=.*/, 'code=[hidden]'));
const kidPhone = await browser.newContext({ ...devices['Pixel 5'] });
const kp = await kidPhone.newPage();
await kp.goto(href, { waitUntil: 'networkidle' });
await kp.waitForURL(/capture\.html|home|athlete/, { timeout: 10000 }).catch(() => {});
await kp.screenshot({ path: `${out}/6-athlete.png` });
const meKid = await kp.evaluate(async () => (await (await fetch('/api/me', { headers: { Authorization: `Bearer ${localStorage.getItem('offdays.token')}` } })).json()));
check('the athlete is signed in as the same athlete', meKid.role === 'athlete' && meKid.athlete_id === kid, `${meKid.display_name}`);

await browser.close();
const failed = checks.filter((x) => !x).length;
console.log(failed ? `${failed} FAILED` : `all ${checks.length} good`);
process.exit(failed ? 1 : 0);
