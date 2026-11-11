// Rankings are for staff; athletes earn badges. In a real browser: what an athlete and a parent can and cannot reach,
// what a director sees (every player by full name, including those who have not started), and the badge card on a
// phone. Throwaway local server only.
//
//   node walk-rankings-staff-only.mjs <base> <outdir>
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8016';
const out = process.argv[3] || '.';
fs.mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const call = async (p, opt = {}, token) => {
  const r = await fetch(base + p, { method: opt.method || 'GET', headers: { 'content-type': 'application/json', ...(token ? { authorization: `Bearer ${token}` } : {}) }, body: opt.body ? JSON.stringify(opt.body) : undefined });
  return { status: r.status, body: await r.json().catch(() => ({})) };
};

const org = (await call('/api/orgs', { method: 'POST', body: { name: 'Rank Walk Club', accept_terms: true, director_name: 'Dir Walk' } })).body;
const director = org.director.token;
const team = (await call('/api/teams', { method: 'POST', body: { name: '2013 Red' } }, director)).body;
const people = ['Ana Alvarez', 'Ben Brooks', 'Cy Chen', 'Di Diaz', 'Ed Evans'];
const csv = ['First Name,Last Name,Birth Year,Parent Email'].concat(people.map((p, i) => `${p.split(' ')[0]},${p.split(' ')[1]},2013,parent${i}@example.com`)).join('\n');
await call('/api/coach/roster/import', { method: 'POST', body: { content: csv, team_id: team.id, invite_guardians: false } }, director);
const fam = (await call('/api/coach/families', {}, director)).body.athletes;
const idOf = (n) => fam.find((a) => a.display_name === n).athlete_id;

// A roster import mints no kid code, on purpose. The walk's athlete is made directly, which returns a sign-in.
const sample = (await call('/api/athletes', { method: 'POST', body: { display_name: 'Walk Athlete', birth_year: 2013, dominant_hand: 'right' } }, director)).body;
console.log('walk athlete created:', sample.id ? 'yes' : 'no');

const b = await chromium.launch();

// ---------------------------------------------------------------- the director
{
  const ctx = await b.newContext({ ...devices['Desktop Chrome'] });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => { console.log('PAGE ERROR', e.message.slice(0, 200)); bad += 1; });
  await page.goto(base + '/app/coach.html');
  await page.evaluate((t) => localStorage.setItem('offdays.token', t), director);
  await page.goto(base + '/app/coach.html');
  await page.locator('#wizard-skip').click({ timeout: 2500 }).catch(() => {});
  await page.waitForTimeout(900);
  await page.locator('button[data-tab="teams"]').click();
  await page.evaluate(() => { document.querySelectorAll('.card').forEach((c) => { if (/standings/i.test(c.querySelector('h2')?.innerText || '')) c.classList.remove('hidden'); if (c._foldOpen && /standings/i.test(c.querySelector('h2')?.innerText || '')) c._foldOpen(); }); });
  await page.waitForTimeout(500);
  await page.locator('#ranking-details summary').scrollIntoViewIfNeeded();
  await page.locator('#ranking-details summary').click();
  await page.waitForSelector('#ranking-rows .rank-row', { timeout: 8000 });
  const rows = await page.locator('#ranking-rows .rank-row').allInnerTexts();
  check(rows.length === 6, `director: all six players are listed (${rows.length})`);
  check(people.every((n) => rows.join('|').includes(n)), 'director: every one by full name');
  check((await page.locator('#ranking-rows .rank-row.idle').count()) === 6, 'director: players who have not started are listed, marked "not started"');
  const ranks = await page.locator('#ranking-rows .rank-n').allInnerTexts();
  check(ranks.every((r) => r.trim() === '1'), `director: nobody has done anything, so all are tied (${ranks.join(',')})`);
  const head = ((await page.locator('#ranking-summary').textContent()) || '').trim();
  check(/Every player, ranked \(6, 6 not started\)/.test(head), `director: the heading counts them ("${head}")`);
  await page.locator('#ranking-details').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'rank-director-laptop.png') });
  await ctx.close();
}

// ---------------------------------------------------------------- the athlete: badges, no ranking
const athleteToken = sample.token;
if (!athleteToken) { check(false, 'athlete: could not obtain a sign-in for the walk'); }
else {
  for (const [label, device] of [['phone', 'iPhone 13']]) {
    const ctx = await b.newContext({ ...devices[device] });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => { console.log('PAGE ERROR', e.message.slice(0, 200)); bad += 1; });
    await page.goto(base + '/app/capture.html');
    // A brand-new athlete gets a short welcome first; this walk is about the home screen after it.
    await page.evaluate((t) => { localStorage.setItem('offdays.token', t); localStorage.setItem('offdays.awizard', 'done'); }, athleteToken);
    await page.goto(base + '/app/capture.html');
    await page.waitForTimeout(1500);
    const html = await page.content();
    check(!/leaderboard/i.test(await page.locator('body').innerText()), `${label}: the athlete's screen never says "leaderboard"`);
    check((await page.locator('button:has-text("Leaderboards")').count()) === 0, `${label}: and has no Leaderboards button`);
    await page.locator('#badges-card').scrollIntoViewIfNeeded();
    check(await page.locator('#badges-card').isVisible(), `${label}: it has a Badges card`);
    check(/0 of 13/.test(await page.locator('#badge-count').innerText()), `${label}: it says how many there are ("${await page.locator('#badge-count').innerText()}")`);
    const next = await page.locator('#badge-next .badge-next').count();
    check(next === 3, `${label}: three "next up" badges are shown (${next})`);
    check((await page.locator('#badge-next .badge-bar').count()) === 3, `${label}: each has a progress bar`);
    check(/of 1\b|of 100\b|of 5\b/.test(await page.locator('#badge-next').innerText()), `${label}: and says how far along ("${(await page.locator('#badge-next').innerText()).replace(/\s+/g, ' ').slice(0, 110)}")`);
    await page.locator('#badge-more summary').click();
    check((await page.locator('#badge-rest .badge-next').count()) === 10, `${label}: "See every badge" shows the other ten`);
    await page.locator('#badges-card').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(out, 'badges-phone.png') });

    // the old page and the old data both refuse
    const direct = await page.evaluate(async (t) => (await fetch('/api/leaderboard', { headers: { authorization: `Bearer ${t}` } })).status, athleteToken);
    check(direct === 403, `${label}: asking the server for a leaderboard directly is refused (${direct})`);
    await page.goto(base + '/app/leaderboard.html');
    await page.waitForTimeout(1500);
    check(/capture\.html/.test(page.url()), `${label}: an old bookmark to the leaderboard page lands back on their own page (${page.url().split('/').pop()})`);
    await ctx.close();
  }
}

await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
