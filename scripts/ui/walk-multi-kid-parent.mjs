// A parent with two kids on the team: one invite, one account, a link for each child, and a child added later.
// Run: node walk-multi-kid-parent.mjs <base> <out-dir>
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';

const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what, extra = '') => { console.log(`${ok ? 'ok   ' : 'FAIL '}${what} ${extra}`); if (!ok) bad += 1; };
const j = async (path, token, body, method) => {
  const r = await fetch(base + path, { method: method || (body ? 'POST' : 'GET'), headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, json: await r.json().catch(() => ({})) };
};
const stamp = Date.now();
const DAD = `robert.${stamp}@example.com`;
const made = (await j('/api/orgs', null, { name: `Walk Club ${stamp}`, sport: 'lacrosse', accept_terms: true, director_name: 'Matt' })).json;
const d = made.director.token;
const team = (await j('/api/teams', d, { name: '2031 Red' })).json.id;
const csv = (rows) => `First Name,Last Name,Birth Year,Parent Email\n${rows.map((r) => `${r[0]},${r[1]},2013,${r[2]}`).join('\n')}\n`;
const imp = (await j('/api/coach/roster/import', d, { content: csv([['Dillon', 'Langdon', DAD], ['Killian', 'Langdon', DAD], ['Ben', 'Amden', `jess.${stamp}@example.com`]]), team_id: team })).json;
const mine = imp.guardian_invites.filter((i) => i.email === DAD);
check(imp.guardian_invites.length === 2 && mine.length === 1, 'the roster makes one invite for the Langdons and one for the Amdens', `(${imp.guardian_invites.length} invites)`);
check(/Dillon and Killian/.test(mine[0].subject) && /One parent account covers all of them/.test(mine[0].text), 'the Langdon message names both boys and says one account', `("${mine[0].subject}")`);

const b = await chromium.launch();
const errs = [];
const ctx = await b.newContext({ ...devices['iPhone 13'] });
const page = await ctx.newPage();
page.on('pageerror', (e) => errs.push(e.message));

// --- the parent opens the one email's link and signs up
await page.goto(mine[0].link.startsWith('http') ? mine[0].link : base + mine[0].link, { waitUntil: 'networkidle' });
await page.fill('#pname', 'Robert Langdon');
await page.fill('#pemail', DAD);
await page.fill('#pphone', '615-555-0142');
await page.click('#redeem');
await page.waitForURL('**/parent.html', { timeout: 20000 });
await page.waitForSelector('#pwizard:not(.hidden)', { timeout: 20000 });
const count = (await page.locator('#pwizard-count').innerText()).trim();
check(/of 5$/.test(count), 'the walkthrough has a yes and a link for each boy, then done', `(${count})`);
await page.screenshot({ path: `${out}/1-wizard-first.png` });

const links = {};
for (const name of ['Dillon', 'Killian']) {
  await page.waitForFunction((n) => document.querySelector('#pwizard-title').innerText.trim() === `Can ${n} train?`, name, { timeout: 15000 }).catch(() => {});
  const title = (await page.locator('#pwizard-title').innerText()).trim();
  check(title === `Can ${name} train?`, `step asks about ${name}`, `(${title})`);
  await page.click('[data-pw-yes]');
  await page.waitForSelector('#pwizard-next:not([disabled])');
  await page.click('#pwizard-next');
  await page.waitForSelector('[data-pw-link]');
  const t2 = (await page.locator('#pwizard-title').innerText()).trim();
  check(t2 === `Send ${name} their sign-in link`, `then gets ${name}'s own link`, `(${t2})`);
  await page.click('[data-pw-link]');
  await page.waitForSelector('[data-link-field]');
  links[name] = (await page.locator('[data-link-field]').first().inputValue().catch(async () => (await page.locator('[data-link-field]').first().innerText()))).trim();
  if (name === 'Dillon') await page.screenshot({ path: `${out}/2-first-link.png` });
  await page.waitForSelector('#pwizard-next:not([disabled])');
  await page.click('#pwizard-next');
}
check(/code=/.test(links.Dillon) && /code=/.test(links.Killian) && links.Dillon !== links.Killian, 'there are two different links, one per boy');
await page.waitForFunction(() => /everything/i.test(document.querySelector('#pwizard-title').innerText), null, { timeout: 15000 }).catch(() => {});
const finalTitle = (await page.locator('#pwizard-title').innerText()).trim();
check(/everything/i.test(finalTitle), 'the walkthrough ends cleanly', `(${finalTitle})`);
await page.click('#pwizard-next');
await page.waitForSelector('#pwizard.hidden', { state: 'attached' });

// --- one portal, two boys, each with a resend button
await page.waitForFunction(() => document.body.innerText.includes('Dillon') && document.body.innerText.includes('Killian'), null, { timeout: 15000 });
const body = (await page.locator('body').innerText()).replace(/\s+/g, ' ');
check(/Send Dillon a new sign-in link/.test(body) && /Send Killian a new sign-in link/.test(body), 'the portal has a resend button for each boy');
await page.screenshot({ path: `${out}/3-portal.png`, fullPage: true });

// --- each link opens the right boy on a phone
const who = async (link) => {
  const c = await b.newContext({ ...devices['Pixel 5'] });
  const p = await c.newPage();
  p.on('pageerror', (e) => errs.push(e.message));
  await p.addInitScript(() => { try { localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
  await p.goto(link, { waitUntil: 'networkidle' });
  await p.waitForSelector('#drill-list .drill-btn', { timeout: 20000 });
  const me = await p.evaluate(async () => (await (await fetch('/api/me', { headers: { Authorization: `Bearer ${localStorage.getItem('offdays.token')}` } })).json()).display_name);
  await c.close();
  return me;
};
const fix = (l) => (l.startsWith('http') ? l : base + l);
check((await who(fix(links.Dillon))) === 'Dillon Langdon', "Dillon's link opens Dillon");
check((await who(fix(links.Killian))) === 'Killian Langdon', "Killian's link opens Killian");

// --- the director's board: both boys have a parent
const fam = (await j(`/api/coach/families?team_id=${team}`, d)).json;
const row = (n) => fam.athletes.find((a) => a.display_name === n);
check(row('Dillon Langdon').stage === row('Killian Langdon').stage && row('Dillon Langdon').stage !== 'no_parent', 'the director sees both Langdon boys with a parent signed up', `(${row('Dillon Langdon').stage})`);

// --- a third boy is added to the roster later
const late = (await j('/api/coach/roster/import', d, { content: csv([['Sam', 'Langdon', DAD]]), team_id: team })).json;
check(late.guardian_invites.length === 0, 'a late brother needs no new invite');
await page.reload({ waitUntil: 'networkidle' });
await page.waitForSelector('#pwizard:not(.hidden)', { timeout: 20000 });
const lateTitle = (await page.locator('#pwizard-title').innerText()).trim();
check(lateTitle === 'Can Sam train?', 'the walkthrough opens again for the new boy only', `(${lateTitle})`);
await page.screenshot({ path: `${out}/4-late-brother.png` });
check(errs.length === 0, 'no page errors', errs.join(' | '));

await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
