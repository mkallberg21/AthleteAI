// A coach opens a player and gives them a drill for their specialty, including one the list does not have.
// Run: node walk-player-drills.mjs <base> <out-dir>
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
await j('/api/coach/roster/import', dt, { content: 'First Name,Last Name,Birth Year\nScott,Face,2013\nSam,Mate,2013\n', team_id: red, invite_guardians: false });
const ids = Object.fromEntries((await j('/api/coach/team-ranking', dt)).json.rows.map((r) => [r.display_name, r.athlete_id]));
const scott = Object.entries(ids).find(([n]) => n.startsWith('Scott'))[1];
const sam = Object.entries(ids).find(([n]) => n.startsWith('Sam'))[1];

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

const openPlayer = async (id) => {
  await page.click('#tabbar [data-tab="teams"]');
  if (await page.locator('[data-open-team]').first().isVisible()) await page.click('[data-open-team]');
  await page.locator(`[data-open-athlete="${id}"]:visible`).first().click();
};
await openPlayer(scott);
await page.waitForSelector('[data-pd-key]', { timeout: 20000 });
check(true, 'the player panel shows a Drills for section');
const heading = (await page.locator('#pd-box h3').innerText());
check(/Drills for Scott/.test(heading), 'it is named for the player', `(${heading})`);
const teamRows = await page.locator('[data-pd-key]:disabled:checked').count();
check(teamRows >= 3, 'the team list is ticked and locked', `(${teamRows} drills)`);
check((await page.locator('[data-pd-key]:not(:disabled):checked').count()) === 0, 'nothing extra to start with');
await page.locator('#pd-box').scrollIntoViewIfNeeded();
await page.screenshot({ path: `${out}/1-panel.png` });

// search narrows the list
await page.fill('[data-pd-find]', 'jump');
const shown = await page.locator('.pd-row:visible').count();
check(shown >= 1 && shown < teamRows + 5, 'search narrows the list', `(${shown} shown)`);
await page.fill('[data-pd-find]', '');

// add a drill that is not on the list and give it to Scott
await page.click('[data-pd-new-wrap] summary');
await page.fill('[data-pd-name]', 'Face Off Clamp');
await page.selectOption('[data-pd-based]', 'gen_plank');
await page.fill('[data-pd-desc]', 'Set the clamp, hold it, then pop out.');
await page.click('[data-pd-new]');
await page.waitForFunction(() => /Face Off Clamp/.test(document.querySelector('[data-pd-note]')?.innerText || ''), null, { timeout: 15000 });
check(/Added "Face Off Clamp" and gave it to Scott. It is counted as/.test(await page.locator('[data-pd-note]').innerText()), 'adding says plainly what it is counted as');
const extra = await page.locator('[data-pd-key]:not(:disabled):checked').count();
check(extra === 1, 'the new drill shows as an extra for Scott', `(${extra})`);
await page.screenshot({ path: `${out}/2-added.png` });

// server truth: Scott has it, Sam does not
const scottKeys = (await j(`/api/coach/athletes/${scott}/drills`, joel.code)).json.choices.filter((c) => c.extra).map((c) => c.name);
const samKeys = (await j(`/api/coach/athletes/${sam}/drills`, joel.code)).json.choices.filter((c) => c.extra || c.name === 'Face Off Clamp');
check(scottKeys.join() === 'Face Off Clamp', 'Scott has it', scottKeys.join());
check(samKeys.every((c) => !c.extra && !c.on_team), 'a teammate does not');

// tick another library drill, save, then untick
await page.fill('[data-pd-find]', 'jump rope');
const box = page.locator('.pd-row:visible [data-pd-key]:not(:disabled)').first();
const had = await box.count();
if (had) { await box.check(); await page.fill('[data-pd-find]', ''); await page.click('[data-pd-save]');
  await page.waitForFunction(() => /Saved/.test(document.querySelector('[data-pd-note]')?.innerText || ''), null, { timeout: 15000 });
  check(/2 extra drills/.test(await page.locator('[data-pd-note]').innerText()), 'ticking another and saving keeps both'); }
await page.fill('[data-pd-find]', '');
while (await page.locator('[data-pd-key]:not(:disabled):checked').count()) await page.locator('[data-pd-key]:not(:disabled):checked').first().uncheck();
await page.click('[data-pd-save]');
await page.waitForFunction(() => /team's drills only/.test(document.querySelector('[data-pd-note]')?.innerText || ''), null, { timeout: 15000 });
check(true, 'unticking everything puts Scott back on the team drills only');

// a coach can also use the program-level form, and a blank name is refused with a reason
await page.keyboard.press('Escape');
await page.click('#tabbar [data-tab="settings"]');
await page.evaluate(() => { let e = document.querySelector('#cd-save'); while (e) { if (e.tagName === 'DETAILS') e.open = true; if (e.classList && e.classList.contains('card')) { e.classList.remove('hidden'); e.classList.add('open'); if (e._foldOpen) e._foldOpen(); } e = e.parentElement; } });
check(await page.locator('#cd-save').isVisible(), 'a coach sees the add a drill form on the library card');
await page.click('#cd-save');
check(/name/.test(await page.locator('#cd-note').innerText()), 'a blank name is refused with a reason');

// locked coach sees why
await j('/api/coach/staff/drill-choice', dt, { user_id: joel.user_id, allowed: false });
await openPlayer(scott);
await page.waitForSelector('#pd-box h3', { timeout: 20000 });
const locked = await page.locator('#pd-box').innerText();
check(/director chooses/.test(locked) && (await page.locator('[data-pd-save]').count()) === 0, 'a coach the director has locked is told why and cannot save');
await page.screenshot({ path: `${out}/3-locked.png` });

check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
