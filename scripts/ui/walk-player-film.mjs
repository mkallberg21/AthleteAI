// A coach opens a player and sees which clips they watched and how many times.
// Run: node walk-player-film.mjs <base> <out-dir>   (against fw_server.py, which has the /__film seed route)
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
const joel = (await j('/api/coach/staff', dt, { display_name: 'Joel White', email: 'joel@example.com', team_ids: [red] })).json;
await j('/api/coach/roster/import', dt, { content: 'First Name,Last Name,Birth Year\nRyder,Cole,2013\nSam,Mate,2013\n', team_id: red, invite_guardians: false });
const rows = (await j('/api/coach/team-ranking', dt)).json.rows;
const ryder = rows.find((r) => r.display_name.startsWith('Ryder')).athlete_id;
const sam = rows.find((r) => r.display_name.startsWith('Sam')).athlete_id;
await j(`/__film/${ryder}`, null, {});

const b = await chromium.launch();
const errs = [];
const ctx = await b.newContext({ ...devices['Desktop Chrome'], viewport: { width: 1280, height: 1100 } });
const page = await ctx.newPage();
page.on('pageerror', (e) => errs.push(e.message));
await page.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await page.evaluate((t) => localStorage.setItem('offdays.token', t), joel.code);
await page.goto(`${base}/app/coach.html`, { waitUntil: 'networkidle' });
if (await page.locator('#wizard-skip').isVisible().catch(() => false)) { await page.click('#wizard-skip'); await page.waitForTimeout(800); }
const open = async (id) => {
  await page.click('#tabbar [data-tab="teams"]');
  if (await page.locator('[data-open-team]').first().isVisible()) await page.click('[data-open-team]');
  await page.locator(`[data-open-athlete="${id}"]:visible`).first().click();
  await page.waitForSelector('#athlete-dd h3', { timeout: 20000 });
};
await open(ryder);
const panel = page.locator('#athlete-dd');
check(await panel.getByText('Film watched').isVisible(), 'the player panel has a Film watched section');
const text = (await panel.innerText()).replace(/\s+/g, ' ');
check(/3 clips, 8 views, 2 watched more than once/.test(text), 'the summary counts clips, views and repeats', '');
const rowsText = await panel.locator('h3:has-text("Film watched") + p + div table tbody tr').allInnerTexts();
check(rowsText.length === 3, 'one row per clip', `(${rowsText.length})`);
check(/Face Off Clamp Technique\s+4 times/.test(rowsText[0].replace(/\s+/g, ' ')), 'newest first, with how many times (4 times)', rowsText[0].replace(/\s+/g, ' '));
check(/Sliding and Recovery.*3 times/.test(rowsText.join(' | ').replace(/\s+/g, ' ')), 'a clip watched on two days adds up (3 times)');
check(/Clearing Under Pressure\s+1\s/.test(rowsText[2].replace(/\s+/g, ' ')) && /stopped early/.test(rowsText[2]), 'a single view shows 1 and how it went');
check(/From Lacrosse Film Room/.test(text), 'the clip credit shows');
await panel.locator('h3:has-text("Film watched")').scrollIntoViewIfNeeded();
await page.screenshot({ path: `${out}/1-film.png` });
await page.keyboard.press('Escape');
await open(sam);
check(/No film watched in this window/.test(await page.locator('#athlete-dd').innerText()), 'a player with no film says so');
check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
