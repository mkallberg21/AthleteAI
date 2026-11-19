// A director and a coach drill into a player from the roster and the ranking.
// Run: node walk-athlete-drilldown.mjs <base> <out-dir>
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
const blue = (await j('/api/teams', dt, { name: '2032 Blue' })).json.id;
const joel = (await j('/api/coach/staff', dt, { display_name: 'Joel White', email: `j.${Date.now()}@example.com`, team_ids: [red] })).json;
await j('/api/coach/roster/import', dt, { content: 'First Name,Last Name,Birth Year\nDillon,Langdon,2013\nBen,Amden,2013\n', team_id: red, invite_guardians: false });
await j('/api/coach/roster/import', dt, { content: 'First Name,Last Name,Birth Year\nCole,Dretler,2014\n', team_id: blue, invite_guardians: false });
const rows = (await j('/api/coach/team-ranking', dt)).json.rows;
const id = (n) => rows.find((r) => r.display_name === n).athlete_id;
// seed a month of work through the scratch server's own test-only route
await j(`/__seed/${id('Dillon Langdon')}`, null, {});

const b = await chromium.launch();
const errs = [];
async function asUser(token, label) {
  const ctx = await b.newContext({ ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errs.push(`${label}: ${e.message}`));
  await page.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
  await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
  await page.evaluate((t) => localStorage.setItem('offdays.token', t), token);
  await page.goto(`${base}/app/coach.html`, { waitUntil: 'networkidle' });
  if (await page.locator('#wizard-skip').isVisible().catch(() => false)) { await page.click('#wizard-skip'); await page.waitForTimeout(800); }
  await page.evaluate(() => localStorage.setItem('offdays.tab.v2', 'today'));
  await page.reload({ waitUntil: 'networkidle' });
  return page;
}

// ---- the director, from the roster
let page = await asUser(dt, 'director');
await page.click('#tabbar [data-tab="teams"]');
await page.evaluate(() => { let e = document.querySelector('#roster'); while (e) { if (e.classList && e.classList.contains('card')) { e.classList.remove('hidden'); e.classList.add('open'); if (e._foldOpen) e._foldOpen(); } e = e.parentElement; } });
await page.waitForSelector('#roster [data-open-athlete]', { timeout: 20000 });
await page.locator('#roster [data-open-athlete]', { hasText: 'Dillon Langdon' }).click();
await page.waitForSelector('#athlete-dd h2', { timeout: 15000 });
const text = (await page.locator('#athlete-dd').innerText()).replace(/\s+/g, ' ');
check(/Dillon Langdon/.test(text) && /2031 Red/.test(text), 'the director opens Dillon from the roster', `(${text.slice(0, 110)}...)`);
check(/Wall Ball|wall ball/i.test(text) && /Shooting|shooting/i.test(text), 'it lists what he has done, drill by drill');
check(/logged by player/.test(text) && /Practised with my brother/.test(text), 'work he logged himself is labelled, with his own words');
check(/in review/.test(text), 'a session held for review is shown as held');
check(!/Cole|Ben Amden|Dretler/.test(text), 'no other player appears');
await page.screenshot({ path: `${out}/1-detail.png` });
await page.click('[data-dd-days="7"]');
await page.waitForFunction(() => document.querySelector('[data-dd-days="7"]')?.getAttribute('aria-pressed') === 'true', null, { timeout: 10000 });
check(true, 'the window can be switched to 7 days');
await page.keyboard.press('Escape');
check(await page.locator('#athlete-dd').isHidden(), 'Escape closes it');

// ---- Joel (2031 Red only)
page = await asUser(joel.code, 'coach');
await page.click('#tabbar [data-tab="teams"]');
await page.evaluate(() => { let e = document.querySelector('#roster'); while (e) { if (e.classList && e.classList.contains('card')) { e.classList.remove('hidden'); e.classList.add('open'); if (e._foldOpen) e._foldOpen(); } e = e.parentElement; } });
await page.waitForSelector('#roster [data-open-athlete]', { timeout: 20000 });
const names = await page.locator('#roster [data-open-athlete]').allInnerTexts();
check(names.includes('Dillon Langdon') && !names.includes('Cole Dretler'), 'a coach sees only their own team in the roster', `(${names.join(', ')})`);
check((await j(`/api/coach/athletes/${id('Cole Dretler')}/training`, joel.code)).status === 404, 'and cannot open a player on another team by asking for them');
check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
