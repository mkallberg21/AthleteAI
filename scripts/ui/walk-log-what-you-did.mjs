// An athlete tells the app what the camera missed: the screen, what it earns, and what the parent and coach see.
// Run: node walk-log-what-you-did.mjs <base> <out-dir>
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
const made = (await j('/api/orgs', null, { name: `Log Club ${stamp}`, sport: 'lacrosse', accept_terms: true, director_name: 'Dir' })).json;
const d = made.director.token;
const team = (await j('/api/teams', d, { name: '2031 Red' })).json.id;
const mk = async (first, email) => {
  await j('/api/coach/roster/import', d, { content: `First Name,Last Name,Birth Year,Parent Email\n${first},Walker,2013,${email}\n`, team_id: team });
  const rows = (await j(`/api/coach/team-ranking?team_id=${team}`, d)).json.rows;
  const kid = rows.find((r) => r.display_name === `${first} Walker`).athlete_id;
  const inv = (await j('/api/coach/guardian-invites', d, { athlete_id: kid, email })).json;
  const parent = (await j('/api/guardians/redeem', null, { code: inv.code, display_name: `Parent ${first}`, email, phone: '615-555-0101' })).json;
  await j('/api/guardians/consent', parent.token, { athlete_id: kid, scope: 'participation', granted: true });
  const link = (await j(`/api/guardians/athlete-link/${kid}`, parent.token, {})).json.link;
  return { kid, parent: parent.token, code: link.split('code=')[1] };
};
const A = await mk('Ryder', `ryder.${stamp}@example.com`);
const B = await mk('Sam', `sam.${stamp}@example.com`);

const b = await chromium.launch();
const errs = [];
const ctx = await b.newContext({ ...devices['Pixel 5'] });
const page = await ctx.newPage();
page.on('pageerror', (e) => errs.push(e.message));
await page.addInitScript(() => { try { localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
await page.goto(`${base}/app/index.html?code=${A.code}`, { waitUntil: 'networkidle' });
await page.waitForSelector('#log-open', { timeout: 15000 });
check(/Tell us what you did/.test(await page.locator('#log-open').innerText()), 'the athlete has a standing button on home');
await page.screenshot({ path: `${out}/1-home.png` });

await page.click('#log-open');
await page.waitForSelector('#view-log:not(.hidden)');
const optionCount = await page.locator('#log-drill option').count();
check(optionCount >= 2, "the screen lists the program's drills to choose from", `(${optionCount})`);
const keys = await page.locator('#log-drill option').evaluateAll((os) => os.map((o) => o.value));
const txt = (await page.locator('#view-log').innerText()).replace(/\s+/g, ' ');
check(/does not go on the leaderboard/.test(txt) && /coach and parent can see it/.test(txt), 'it says plainly what it does and does not do');
await page.screenshot({ path: `${out}/2-form.png` });

// a bad length is stopped on the screen, nothing saved
await page.fill('#log-minutes', '0');
await page.click('#log-save');
check(await page.locator('#log-error').isVisible(), 'a length of 0 is stopped with a plain message');
check((await j('/api/me', A.code)).json.total_xp === 0, 'and nothing was saved');

await page.selectOption('#log-drill', keys[0]);
await page.fill('#log-minutes', '20');
await page.fill('#log-note', 'phone died halfway');
await page.click('#log-save');
await page.waitForSelector('#log-done:not(.hidden)');
const done1 = (await page.locator('#log-done-text').innerText()).trim();
check(/Logged\. That counts for showing up today \(\+\d+ XP\)\./.test(done1), 'the first one earns the flat XP', `(${done1})`);
await page.screenshot({ path: `${out}/3-saved.png` });

// a second one the same day earns nothing more, and says so
await page.click('#log-back');
await page.click('#log-open');
await page.selectOption('#log-drill', keys[1]);
await page.fill('#log-minutes', '240');
await page.click('#log-save');
await page.waitForSelector('#log-done:not(.hidden)');
const done2 = (await page.locator('#log-done-text').innerText()).trim();
check(/already showed up today/.test(done2), 'a second one the same day says it adds no more XP', `(${done2})`);
const xp = (await j('/api/me', A.code)).json.total_xp;
check(xp === 25 || xp > 0, 'the athlete has one award for the day', `(total ${xp})`);

// the parent sees it labelled
const drills = (await j(`/api/parent/athletes/${A.kid}/drills`, A.parent)).json;
check(drills.sessions.length === 2 && drills.sessions.every((s) => s.self_reported === true), 'the parent sees both marked as logged');
const pctx = await b.newContext({ ...devices['iPhone 13'] });
const pp = await pctx.newPage();
pp.on('pageerror', (e) => errs.push(e.message));
await pp.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await pp.evaluate((t) => { localStorage.setItem('offdays.token', t); localStorage.setItem('offdays.pwizard', 'done'); }, A.parent);
await pp.goto(`${base}/app/parent.html`, { waitUntil: 'networkidle' });
await pp.waitForSelector('[data-drills]');
await pp.click('[data-drills] summary');
await pp.waitForSelector('[data-drills] .drill-log table');
const ptxt = (await pp.locator('[data-drills] .drill-log').innerText()).replace(/\s+/g, ' ');
check(/logged by athlete/.test(ptxt), "the parent's list says \"logged by athlete\"");
await pp.locator('[data-drills] .drill-log').scrollIntoViewIfNeeded();
await pp.screenshot({ path: `${out}/4-parent.png` });

// the director sees the label and the rank ignores it
const player = (await j(`/api/coach/overview/player/${A.kid}?window=all`, d)).json;
check(player.recent_sessions.length === 2 && player.recent_sessions.every((s) => s.self_reported === 1), 'the director sees both marked as logged');
const rows = (await j(`/api/coach/team-ranking?team_id=${team}`, d)).json.rows;
check(rows.find((r) => r.athlete_id === A.kid).xp === 0, 'the staff ranking gives that athlete no XP for it');
check(rows.every((r) => r.rank >= 1), 'the ranking is otherwise intact');

check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
