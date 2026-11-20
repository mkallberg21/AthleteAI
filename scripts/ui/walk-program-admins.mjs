// A director gives someone else director access, and can hand the program over.
// Run: node walk-program-admins.mjs <base> <out-dir>   (against a scratch server; the email hold stays on)
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';

const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what, extra = '') => { console.log(`${ok ? 'ok   ' : 'FAIL '}${what} ${extra}`); if (!ok) bad += 1; };
const j = async (path, token, body) => {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = 'Bearer ' + token;
  const r = await fetch(base + path, { method: body ? 'POST' : 'GET', headers, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, json: await r.json().catch(() => ({})) };
};
const made = (await j('/api/orgs', null, { name: 'Nashville Dogs', sport: 'lacrosse', accept_terms: true, director_name: 'Matt Kallberg' })).json;
const owner = made.director.token;
await j('/api/teams', owner, { name: '2031 Red' });

const b = await chromium.launch();
const errs = [];
const openAs = async (token) => {
  const ctx = await b.newContext({ ...devices['Desktop Chrome'], viewport: { width: 1280, height: 1200 } });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errs.push(e.message));
  page.on('dialog', (d) => d.accept());
  await page.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
  await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
  await page.evaluate((t) => localStorage.setItem('offdays.token', t), token);
  await page.goto(`${base}/app/coach.html`, { waitUntil: 'networkidle' });
  if (await page.locator('#wizard-skip').isVisible().catch(() => false)) { await page.click('#wizard-skip'); await page.waitForTimeout(800); }
  // The card lives on one of the tabs; find it.
  for (const tab of await page.locator('#tabbar [data-tab]').evaluateAll((els) => els.map((e) => e.dataset.tab))) {
    await page.click(`#tabbar [data-tab="${tab}"]`);
    if (await page.locator('#admins-card').isVisible()) break;
  }
  if (!(await page.locator('#admins-card.open').count())) await page.click('#admins-card > h2');
  await page.waitForTimeout(300);
  return page;
};

// ---- the owner
let page = await openAs(owner);
const card = page.locator('#admins-card');
check(await card.isVisible(), 'the owner sees the Administrators card');
check(/owner/.test(await card.locator('#admins-list').innerText()) && /you/.test(await card.locator('#admins-list').innerText()), 'Matt is shown as owner and you');
check(await page.locator('#admins-add').isVisible(), 'the owner sees the add form');
await page.fill('#admin-name', 'Dana Park');
await page.fill('#admin-email', 'dana@example.com');
await page.click('#admin-add');
await page.waitForSelector('#admin-out:not(.hidden)', { timeout: 15000 });
const outText = (await page.locator('#admin-out').innerText()).replace(/\s+/g, ' ');
check(/Dana Park is now an administrator/.test(outText) && /on hold/.test(outText), 'with email on hold the owner is told, and gets the link', outText.slice(0, 120));
const link = await page.locator('#admin-out code').innerText();
check(/index\.html\?code=/.test(link), 'the sign-in link is shown to pass on');
check((await card.locator('#admins-list').innerText()).includes('Dana Park'), 'Dana appears in the list');
await page.screenshot({ path: `${out}/1-owner.png`, fullPage: false });
const danaCode = new URL(link, base).searchParams.get('code');

// ---- the administrator
const adminPage = await openAs(danaCode);
const aCard = adminPage.locator('#admins-card');
check(await aCard.isVisible(), 'the administrator sees the card');
check(!(await adminPage.locator('#admins-add').isVisible()), 'but not the add form');
check((await aCard.locator('[data-admin-owner], [data-admin-remove]').count()) === 0, 'and no hand over or remove buttons');
check(/Only Matt Kallberg/.test((await adminPage.locator('#admins-blurb').innerText())), 'the card says who the owner is');
check(await adminPage.locator('#staff-card').isVisible(), 'they have the coaches card, like any director');
await adminPage.screenshot({ path: `${out}/2-admin.png` });

// ---- hand over
page = await openAs(owner);
await page.click('[data-admin-owner]');
await page.fill('[data-ho-name]', 'Wrong Club');
await page.click('[data-ho-go]');
await page.waitForFunction(() => document.querySelector('[data-ho-msg]')?.textContent.trim().length > 0);
check(/name exactly/.test(await page.locator('[data-ho-msg]').innerText()), 'a wrong program name does not hand over');
await page.fill('[data-ho-name]', 'Nashville Dogs');
await page.screenshot({ path: `${out}/3-handover.png` });
await page.click('[data-ho-go]');
await page.waitForFunction(() => !document.querySelector('[data-admin-owner]'), null, { timeout: 15000 });
const after = (await page.locator('#admins-list').innerText()).replace(/\s+/g, ' ');
check(/Dana Park owner/.test(after) && /Matt Kallberg administrator you/.test(after), 'Dana is now the owner and Matt an administrator', after.slice(0, 140));
check(!(await page.locator('#admins-add').isVisible()), 'Matt no longer sees the add form');
await page.screenshot({ path: `${out}/4-after.png` });
const danaAgain = await openAs(danaCode);
check(await danaAgain.locator('#admins-add').isVisible(), 'Dana now sees the add form');

check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
