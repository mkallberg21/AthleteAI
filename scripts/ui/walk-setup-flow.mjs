// The director's one-step setup with 12 teams: names pasted at once, coaches by email (one coach on three teams is one person),
// roster step, and only the wizard on screen at every step. Run: node walk-setup-flow.mjs <base> <out-dir>
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); if (!ok) bad++; };
const api = async (path, token, body, method) => (await fetch(`${base}${path}`, {
  method: method || (body ? 'POST' : 'GET'),
  headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  body: body ? JSON.stringify(body) : undefined })).json();

const browser = await chromium.launch();
for (const [tag, ctxOpts] of [['laptop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const made = await api('/api/orgs', null, { name: `Setup Club ${tag}`, sport: 'lacrosse', accept_terms: true, director_name: 'Joel White' });
  const ctx = await browser.newContext(ctxOpts);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/status of 400/.test(m.text())) errors.push(m.text()); }); page.on('response', (r) => { if (r.status() >= 400 && !r.url().includes('/api/family/board')) console.log('   HTTP', r.status(), r.request().method(), r.url().replace(base, '')); });
  await page.goto(`${base}/app/index.html?code=${made.director.token}`, { waitUntil: 'networkidle' });
  await page.waitForSelector('#wizard:not(.hidden)', { timeout: 15000 });
  const visible = async () => page.evaluate(() => [...document.querySelectorAll('.wrap > *')].filter((e) => e.offsetParent !== null && e.getBoundingClientRect().height > 0).map((e) => e.id || e.tagName));
  const step = async () => (await page.textContent('#wizard-title')).trim();
  const shot = (n) => page.screenshot({ path: `${out}/${tag}-${n}.png`, fullPage: false });

  // walk past the steps that already existed
  const seen = [];
  for (let guard = 0; guard < 8; guard++) {
    const t = await step();
    seen.push(t);
    if (t === 'Your teams') break;
    if (t === 'How the program reaches you') {
      await api('/api/me/contact', made.director.token, { email: 'joel@example.com', phone: '615-555-0100' }, 'PUT').catch(() => {});
    }
    if (t === 'When the season runs') {
      await api('/api/org/season', made.director.token, { starts_on: '2026-12-01', ends_on: '2027-05-31' }, 'PUT').catch(() => {});
    }
    await page.waitForTimeout(400);
    const next = page.locator('#wizard-next');
    if (await next.isDisabled()) {
      // let the page re-read what we just saved
      await page.reload({ waitUntil: 'networkidle' }); await page.waitForSelector('#wizard:not(.hidden)');
      if (await page.locator('#wizard-next').isDisabled()) { console.log('stuck on', t); break; }
    }
    await page.locator('#wizard-next').click(); await page.waitForTimeout(400);
  }
  console.log(tag, 'steps seen:', seen.join(' > '));
  check(await step() === 'Your teams', `${tag}: reaches the teams step`);

  // one thing at a time: only the wizard is on screen
  let v = await visible();
  check(v.length === 1 && v[0] === 'wizard', `${tag}: only the wizard is on screen (${v.join(',')})`);
  const slotCards = await page.evaluate(() => [...document.querySelectorAll('#wizard-slot > *')].filter((e) => e.offsetParent !== null).map((e) => e.id));
  check(slotCards.length === 1 && slotCards[0] === 'bulk-teams-card', `${tag}: the slot holds just the teams box (${slotCards})`);
  check(await page.locator('#wizard-next').isDisabled(), `${tag}: Next waits for a team`);
  await shot('1-teams-empty');

  // 12 teams, pasted, with a repeat and a blank line
  const names = ['2031 Red', '2031 Blue', '2032 Red', '2032 Blue', '2033 Red', '2033 Blue', 'U9 Gold', 'U9 Black', 'U11 A', 'U11 B', 'U13 A', 'U13 B'];
  await page.fill('#bt-names', names.join('\n') + '\n\n2031 red\n');
  await page.waitForTimeout(700);
  const prev = (await page.textContent('#bt-preview')).trim();
  check(/12 to add/.test(prev) && /twice/.test(prev), `${tag}: preview counts 12 and flags the repeat (${prev})`);
  check((await page.textContent('#bt-add')).trim() === 'Add 12 teams', `${tag}: button says Add 12 teams`);
  await shot('2-teams-typed');
  await page.click('#bt-add');
  await page.waitForFunction(() => !document.getElementById('bt-out').classList.contains('hidden'), null, { timeout: 30000 });
  await page.waitForTimeout(600);
  const made12 = (await api('/api/coach/teams', made.director.token)).teams;
  check(made12.length === 12, `${tag}: 12 teams exist on the server (${made12.length})`);
  check(made12.every((t) => t.daily_wall_ball === 0 || t.daily_wall_ball > 0), `${tag}: teams created`);
  check(!(await page.locator('#wizard-next').isDisabled()), `${tag}: Next unlocks`);
  check((await page.inputValue('#bt-names')) === '', `${tag}: the box empties after success`);
  await shot('3-teams-added');

  // typing the same names again leaves them out
  await page.fill('#bt-names', '2031 Red\nU15 A'); await page.waitForTimeout(700);
  const again = (await page.textContent('#bt-preview')).trim();
  check(/1 to add/.test(again) && /already a team/.test(again), `${tag}: an existing team is left out (${again})`);
  await page.fill('#bt-names', '');

  // coaches
  await page.click('#wizard-next'); await page.waitForTimeout(800);
  check(await step() === 'Your coaches', `${tag}: the coaches step`);
  v = await visible();
  check(v.length === 1 && v[0] === 'wizard', `${tag}: still only the wizard on screen`);
  const rows = await page.locator('.bc-row').count();
  check(rows === 12, `${tag}: one row per team (${rows})`);
  check(!(await page.locator('#wizard-next').isDisabled()), `${tag}: coaches can wait (Next is open)`);
  const hint = (await page.textContent('#wizard-hint')).trim();
  check(/12 of 12 teams still need a coach/.test(hint), `${tag}: the hint counts them (${hint})`);
  const ids = made12.map((t) => t.id);
  // Sam Hill coaches three teams, five others have their own coach, the rest are left for later; one row is half filled
  const fill = async (i, n, e) => { await page.fill(`#bc-n-${ids[i]}`, n); await page.fill(`#bc-e-${ids[i]}`, e); };
  await fill(0, 'Sam Hill', 'sam@example.com'); await fill(1, 'Sam Hill', 'SAM@example.com'); await fill(2, 'Sam Hill', 'sam@example.com');
  await fill(3, 'Pat Roe', 'pat@example.com'); await fill(4, 'Lee Wu', 'lee@example.com'); await fill(5, 'Ana Cruz', 'ana@example.com');
  await page.fill(`#bc-n-${ids[6]}`, 'Half Done');   // no email
  await shot('4-coaches-typed');
  await page.click('#bc-save');
  await page.waitForFunction(() => !document.getElementById('bc-out').classList.contains('hidden'), null, { timeout: 30000 });
  await page.waitForTimeout(800);
  const why = (await page.locator(`.bc-row[data-team="${ids[6]}"] .bc-why`).textContent()).trim();
  check(/email/i.test(why), `${tag}: the half-filled row says what to add (${why})`);
  const staff = (await api('/api/coach/staff', made.director.token)).staff || (await api('/api/coach/staff', made.director.token));
  const list = Array.isArray(staff) ? staff : (staff.staff || []);
  const coaches = list.filter((u) => u.role ? u.role === 'coach' : true);
  const sam = coaches.filter((u) => /Sam Hill/.test(u.display_name));
  check(sam.length === 1, `${tag}: Sam Hill is one person (${sam.length})`);
  const after = (await api('/api/coach/teams', made.director.token)).teams;
  const with3 = after.filter((t) => /Sam Hill/.test(t.coaches || '')).length;
  check(with3 === 3, `${tag}: Sam Hill has 3 teams (${with3})`);
  check(after.filter((t) => (t.coaches || '').trim()).length === 6, `${tag}: six teams have a coach`);
  const outText = (await page.textContent('#bc-out')).replace(/\s+/g, ' ');
  check(/Sam Hill/.test(outText) && /Pat Roe/.test(outText), `${tag}: each coach is listed with how to reach them`);
  check(/Send email/.test(outText) && /shown once/.test(outText), `${tag}: no email service, so the Send email link and the code are shown`);
  check((await page.locator('.bc-row').count()) === 6, `${tag}: only the six teams without a coach are left`);
  const hint2 = (await page.textContent('#wizard-hint')).trim();
  check(/6 of 12 teams still need a coach/.test(hint2), `${tag}: the hint updates (${hint2})`);
  await shot('5-coaches-saved');

  // rosters
  await page.click('#wizard-next'); await page.waitForTimeout(800);
  check((await step()).startsWith('The rosters'), `${tag}: the rosters step`);
  v = await visible();
  check(v.length === 1 && v[0] === 'wizard', `${tag}: still only the wizard on screen`);
  check(/0 of 12 teams have players/.test(await page.textContent('#wizard-hint')), `${tag}: roster progress starts at 0 of 12`);
  const csv = 'First Name,Last Name,Birth Year,Parent Email\nAva,Moss,2013,ava.mom@example.com\nBen,Cole,2013,ben.dad@example.com\n';
  const prevR = await api('/api/coach/roster/preview', made.director.token, { content: csv });
  check(prevR.summary && prevR.summary.create === 2, `${tag}: the real roster path still previews`);
  await api('/api/coach/roster/import', made.director.token, { content: csv, team_id: ids[0] });
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  // a director with athletes has been set up: the wizard is for first visits, so no longer forced
  const forced = await page.locator('#wizard:not(.hidden)').count();
  console.log(tag, 'after a roster, the forced walkthrough is', forced ? 'still showing' : 'gone');
  await shot('6-after-roster');
  check(errors.length === 0, `${tag}: no script errors (${errors.slice(0, 2).join(' | ')})`);
  await ctx.close();
}
await browser.close();
console.log(bad ? `FAILED: ${bad}` : 'all good');
process.exit(bad ? 1 : 0);
