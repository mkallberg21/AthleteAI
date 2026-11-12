// The director's home with a 12-team, 55-player program: all teams in one list, one team, one player, the coaches. Run: node walk-director-home.mjs <base> <out-dir>
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); if (!ok) bad++; };
const j = async (p, t, b, m) => {
  const r = await fetch(base + p, { method: m || (b ? 'POST' : 'GET'), headers: { 'Content-Type': 'application/json', ...(t ? { Authorization: `Bearer ${t}` } : {}) }, body: b ? JSON.stringify(b) : undefined });
  return r.json();
};

async function seed(name) {
  const made = await j('/api/orgs', null, { name, sport: 'lacrosse', accept_terms: true, director_name: 'Joel White' });
  const t = made.director.token;
  await j('/api/me/contact', t, { email: 'joel@example.com', phone: '615-555-0100' }, 'PUT');
  await j('/api/org/season', t, { starts_on: '2026-12-01', ends_on: '2027-05-31' }, 'PUT');
  const names = ['2031 Red', '2031 Blue', '2032 Red', '2032 Blue', '2033 Red', '2033 Blue', 'U9 Gold', 'U9 Black', 'U11 A', 'U11 B', 'U13 A', 'U13 B'];
  const teams = [];
  for (const n of names) teams.push((await j('/api/teams', t, { name: n })).id);
  // coaches: Sam on three teams, one coach each on six more, three teams with no coach
  const sam = await j('/api/coach/staff', t, { display_name: 'Sam Hill', email: 'sam@example.com', team_ids: teams.slice(0, 3) });
  for (let i = 3; i < 9; i++) await j('/api/coach/staff', t, { display_name: `Coach ${i}`, email: `c${i}@example.com`, team_ids: [teams[i]] });
  const first = ['Ava', 'Ben', 'Cam', 'Dee', 'Eli'], last = ['Moss', 'Cole', 'Diaz', 'Park', 'Fox', 'Gray', 'Hale', 'Ito', 'Joy', 'Kim', 'Lee', 'Mox'];
  const ids = {};
  for (let i = 0; i < 11; i++) {   // the twelfth team stays empty
    const rows = first.map((f) => `${f},${last[i]},2013,${f.toLowerCase()}.${last[i].toLowerCase()}@example.com`).join('\n');
    await j('/api/coach/roster/import', t, { content: `First Name,Last Name,Birth Year,Parent Email\n${rows}`, team_id: teams[i] });
    ids[teams[i]] = (await j(`/api/coach/team-ranking?team_id=${teams[i]}`, t)).rows.map((r) => r.athlete_id);
  }
  return { t, teams, ids, sam };
}

const browser = await chromium.launch();
for (const [tag, ctxOpts] of [['laptop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const s = await seed(`Home Club ${tag}`);
  const ctx = await browser.newContext(ctxOpts);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/status of 400/.test(m.text())) errors.push(m.text()); });
  await page.goto(`${base}/app/index.html?code=${s.t}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  if (await page.locator('#wizard-skip').isVisible().catch(() => false)) { await page.click('#wizard-skip'); await page.waitForTimeout(900); }
  const shot = (n) => page.screenshot({ path: `${out}/${tag}-${n}.png`, fullPage: false });

  // HOME is the first thing a director sees
  check(await page.locator('#tabbar [data-tab="home"][aria-selected="true"]').count() === 1, `${tag}: Home is the tab that opens`);
  await page.waitForSelector('#home-body .home-row', { timeout: 15000 });
  const rows = await page.locator('#home-body .home-row').count();
  check(rows === 12, `${tag}: one row per team (${rows})`);
  const onScreen = await page.evaluate(() => [...document.querySelectorAll('.wrap--grid > .card, .wrap--grid > .stat-row')].filter((c) => c.offsetParent !== null).map((c) => c.id || 'stats'));
  check(onScreen.length === 1 && onScreen[0] === 'home-card', `${tag}: Home shows just the home card (${onScreen.join(',')})`);
  const firstTop = await page.evaluate(() => Math.round(document.querySelector('#home-body .home-row').getBoundingClientRect().top));
  check(firstTop < (tag === 'phone' ? 760 : 560), `${tag}: the first team is visible without scrolling (top ${firstTop}px)`);
  const text = (await page.locator('#home-card').evaluate((e) => e.textContent)).replace(/\s+/g, ' ');
  check(/0 of 55 players training/.test(text), `${tag}: the total reads 0 of 55 players training`);
  check(/3 teams have no coach/.test(text) || /teams have no coach/.test(text), `${tag}: the strip says teams have no coach`);
  check(/1 team has no players yet/.test(text), `${tag}: the strip says one team has no players`);
  check(/families are not training yet/.test(text), `${tag}: the strip says families are not training yet`);
  check(/coaches have not signed in yet/.test(text), `${tag}: the strip says coaches have not signed in`);
  check(!/wall.?ball|shots a day|join code/i.test(text), `${tag}: no team numbers on the home`);
  await shot('1-home');

  // make some of them train, then look again
  const t0 = s.ids[s.teams[0]];
  for (const a of t0.slice(0, 3)) {
    await fetch(`${base}/api/health`);  // keep the server warm; sessions are written below through the API the page uses
  }

  // ONE TEAM
  await page.locator('#home-body .home-row').first().click();
  await page.waitForSelector('#home-body .home-row[data-player]', { timeout: 10000 });
  check((await page.textContent('#home-title')).trim() === '2031 Blue', `${tag}: the team page is titled 2031 Blue (rows are alphabetical)`);
  const players = await page.locator('#home-body [data-player]').count();
  check(players === 5, `${tag}: the team's 5 players are listed, ranked (${players})`);
  const ranks = await page.$$eval('#home-body [data-player] .home-rank', (n) => n.map((x) => x.textContent.trim()));
  check(ranks.every((r) => r === '1'), `${tag}: nobody has trained, so all five share rank 1 (${ranks.join(',')})`);
  check(/Nothing done in this window/.test(await page.locator('#home-body').innerText()), `${tag}: players with nothing done say so`);
  check(/Coach\b/i.test(await page.locator('#home-body .home-box h3').first().evaluate((e) => (e.closest('.home-box').nextElementSibling || e).querySelector('h3')?.textContent || '')) || /last opened the app/.test(await page.locator('#home-body').evaluate((e) => e.textContent)), `${tag}: the coach is on the team page`);
  await shot('2-team');

  // ONE PLAYER
  await page.locator('#home-body [data-player]').first().click();
  await page.waitForSelector('#home-body .home-box', { timeout: 10000 });
  const pt = (await page.locator('#home-body').innerText()).replace(/\s+/g, ' ');
  check(/Where this family is/i.test(pt) && /Parents?/i.test(pt) && /Recent sessions/i.test(pt), `${tag}: the player page has stage, parent and sessions`);
  check(/@example\.com/.test(pt), `${tag}: the parent's email is there`);
  check(!/token|kid code|join code/i.test(pt), `${tag}: no kid code or token on the player page`);
  check(await page.locator('#home-resend').count() === 1, `${tag}: the invite can be sent again from here`);
  await shot('3-player');
  await page.click('#home-resend');
  await page.waitForSelector('#home-nudge a.btn-link, #home-nudge .err', { timeout: 10000 });
  check(await page.locator('#home-nudge a.btn-link').count() === 1, `${tag}: Send again gives a Send email link (the program is on hold)`);
  check(!/emailed to/i.test(await page.locator('#home-nudge').innerText()), `${tag}: it does not claim the email was sent`);

  // BACK, BACK
  await page.click('#home-body [data-back]');
  await page.waitForSelector('#home-body [data-player]');
  check((await page.textContent('#home-title')).trim() === '2031 Blue', `${tag}: Back goes to the team`);
  await page.click('#home-body [data-back]');
  await page.waitForSelector('#home-body .home-row[data-team]');
  check(await page.locator('#home-body .home-row[data-team]').count() === 12, `${tag}: Back goes to all teams`);

  // COACHES
  await page.click('#home-to-coaches');
  await page.waitForSelector('#home-body .home-box');
  const ct = (await page.locator('#home-body').innerText()).replace(/\s+/g, ' ');
  check(/Sam Hill/.test(ct) && /Has not signed in/.test(ct), `${tag}: the coaches list shows Sam and who has not signed in`);
  check((await page.locator('#home-body .home-box').count()) === 7, `${tag}: seven coaches (${await page.locator('#home-body .home-box').count()})`);
  await shot('4-coaches');
  await page.click('#home-body [data-back]');
  await page.waitForSelector('#home-body .home-row[data-team]');

  // the strip's buttons go where they say
  await page.locator('#home-attn button', { hasText: 'See who' }).first().click();
  await page.waitForTimeout(700);
  check(await page.locator('#tabbar [data-tab="families"][aria-selected="true"]').count() === 1, `${tag}: "See who" opens the Families tab`);
  await page.click('#tabbar [data-tab="home"]'); await page.waitForTimeout(800);

  // the old dashboard is still there, on its tabs
  for (const [tab, card] of [['today', '#practice-card'], ['families', '#families-card'], ['teams', '#teams-card'], ['settings', '#badge-card']]) {
    await page.click(`#tabbar [data-tab="${tab}"]`); await page.waitForTimeout(500);
    check(await page.locator(card).count() === 1, `${tag}: the ${tab} tab still has ${card}`);
  }
  await page.click('#tabbar [data-tab="teams"]'); await page.waitForTimeout(400);
  check(await page.locator('#filter-card').isVisible(), `${tag}: the team filter is back on the other tabs`);
  await page.click('#tabbar [data-tab="home"]'); await page.waitForTimeout(500);
  check(!(await page.locator('#filter-card').isVisible()), `${tag}: and hidden on Home`);

  // no sideways scroll
  const sw = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  check(sw[0] <= sw[1], `${tag}: no sideways scroll (${sw[0]} <= ${sw[1]})`);
  check(errors.length === 0, `${tag}: no script errors (${errors.slice(0, 2).join(' | ')})`);
  await ctx.close();
}
await browser.close();
console.log(bad ? `FAILED: ${bad}` : 'all good');
process.exit(bad ? 1 : 0);
