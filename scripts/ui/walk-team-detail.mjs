// The Teams tab: a Create a team button, and any team opened to see who has a login and what they have been doing.
// Run: node walk-team-detail.mjs <base> <out-dir>   (against dd_server.py, which has the /__seed route)
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
const stamp = Date.now();
const made = (await j('/api/orgs', null, { name: 'Nashville Dogs', sport: 'lacrosse', accept_terms: true, director_name: 'Matt Kallberg' })).json;
const dt = made.director.token;
const red = (await j('/api/teams', dt, { name: '2031 Red' })).json.id;
const csv = `First Name,Last Name,Birth Year,Parent Email\nDillon,Langdon,2013,robert.${stamp}@example.com\nBen,Amden,2013,jess.${stamp}@example.com\nCy,Cole,2013,\n`;
const imp = (await j('/api/coach/roster/import', dt, { content: csv, team_id: red })).json;
const rows = (await j('/api/coach/team-ranking', dt)).json.rows;
const id = (n) => rows.find((r) => r.display_name === n).athlete_id;
await j(`/__seed/${id('Dillon Langdon')}`, null, {});
const parent = (await j('/api/guardians/redeem', null, { code: imp.guardian_invites[0].code, display_name: 'Robert', email: `robert.${stamp}@example.com`, phone: '615-555-0101' })).json;

const b = await chromium.launch();
const errs = [];
const ctx = await b.newContext({ ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
page.on('pageerror', (e) => errs.push(e.message));
page.on('dialog', (d) => d.accept());
await page.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await page.evaluate((t) => localStorage.setItem('offdays.token', t), dt);
await page.goto(`${base}/app/coach.html`, { waitUntil: 'networkidle' });
if (await page.locator('#wizard-skip').isVisible().catch(() => false)) { await page.click('#wizard-skip'); await page.waitForTimeout(800); }
await page.click('#tabbar [data-tab="teams"]');
await page.waitForSelector('#teams-home:not(.tab-off)');

// the Teams tab is just the teams and one button
const visible = await page.evaluate(() => [...document.querySelectorAll('.wrap--grid > .card')].filter((c) => !c.classList.contains('tab-off') && !c.classList.contains('hidden') && c.offsetParent !== null).map((c) => c.id || (c.querySelector('h2')?.textContent || '?')));
check(visible.length === 1 && visible[0] === 'teams-home', 'the Teams tab shows only the teams', `(${visible.join(', ')})`);
check(await page.locator('#tm-create').isVisible(), 'with a Create a team button for the director');
await page.screenshot({ path: `${out}/1-teams.png` });

// open a team that has players
await page.locator('[data-open-team]', { hasText: '2031 Red' }).click();
await page.waitForSelector('#td-body table');
const text = (await page.locator('#td-body').innerText()).replace(/\s+/g, ' ');
check(/3 players/.test(text) && /1 of 3 parents signed up/.test(text), 'the team shows its players and how many parents have signed up', `(${text.slice(0, 120)})`);
const dillon = (await page.locator('#td-body tbody tr', { hasText: 'Dillon Langdon' }).innerText()).replace(/\s+/g, ' ');
check(/signed up/.test(dillon) && /\b8\b/.test(dillon) && /\b15\b/.test(dillon) && /1 logged/.test(dillon), 'Dillon: parent signed up, 8 sessions this week, 15 in 30 days, 1 of them logged', `(${dillon})`);
check(/no parent on file/.test((await page.locator('#td-body tbody tr', { hasText: 'Cy Cole' }).innerText())), 'Cy has no parent on file, and it says so');
check(/not yet/.test((await page.locator('#td-body tbody tr', { hasText: 'Ben Amden' }).innerText())), 'Ben\'s parent has not signed up yet');
check(/No coach on this team yet/.test(text) && /Next steps/.test(text), 'a team with no coach says so and offers next steps');
await page.screenshot({ path: `${out}/2-detail.png` });
await page.click('[data-td-filter="signed"]');
check((await page.locator('#td-body tbody tr').count()) === 1 && /Dillon Langdon/.test(await page.locator('#td-body tbody').innerText()), 'the filter narrows to who has signed in (only Dillon)');
await page.click('[data-td-filter="all"]');
await page.locator('#td-body [data-open-athlete]', { hasText: 'Dillon Langdon' }).click();
await page.waitForSelector('#athlete-dd h2');
check(/Dillon Langdon/.test(await page.locator('#athlete-dd').innerText()), 'a player opens into their full activity');
await page.keyboard.press('Escape');

// add a coach from here
await page.fill('#td-cname', 'Joel White');
await page.fill('#td-cemail', `joel.${stamp}@example.com`);
await page.click('#td-cadd');
await page.waitForTimeout(2500);
console.log('coach msg:', (await page.locator('#td-cmsg').innerText().catch(() => 'none')).replace(/\s+/g, ' ').slice(0, 200), '| errs:', errs.join(' | '), '| add disabled:', await page.locator('#td-cadd').isDisabled(), '| name:', await page.inputValue('#td-cname'));
await page.waitForFunction(() => /Added\./.test(document.querySelector('#td-cmsg')?.innerText || ''), null, { timeout: 15000 });
const after = (await page.locator('#td-body').innerText()).replace(/\s+/g, ' ');
check(/Joel White/.test(after) && /has not signed in yet/.test(after), 'the new coach appears on the team');
check(!/Next steps/.test(after) || /done/.test(after), 'and the coach step is done');

// create a team: the button leads to the next steps
await page.click('#td-back');
await page.click('#tm-create');
await page.fill('#tm-name', '2032 Blue');
await page.click('#tm-create-go');
await page.waitForSelector('#td-body h2');
const fresh = (await page.locator('#td-body').innerText()).replace(/\s+/g, ' ');
check(/2032 Blue/.test(fresh) && /Next steps for 2032 Blue/.test(fresh) && /Add the players/.test(fresh) && /Add a coach/.test(fresh), 'Create a team leads straight to adding players and a coach', `(${fresh.slice(0, 140)})`);
await page.screenshot({ path: `${out}/3-new-team.png` });
await page.click('[data-td-players]');
await page.waitForSelector('#import-card:not(.tab-off)');
check(await page.locator('#import-team').inputValue() !== '', 'Add players opens the roster import with this team already chosen');

check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
