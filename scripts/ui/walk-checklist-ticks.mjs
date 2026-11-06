// The Getting-set-up checklist and the red stars must follow what the director
// does, with no page reload. Add a team, import a roster, add one player by hand,
// delete the upload: the ticks and stars change each time.
import { chromium } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8007';
const f = path.join(os.tmpdir(), 'roster-tick.csv');
fs.writeFileSync(f, 'Player First,Player Last,Birth Year,Parent Email\nMason,Cole,2013,mom1@example.com\nLiam,Ray,2013,dad2@example.com\n');
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };

const b = await chromium.launch();
const page = await (await b.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
page.on('dialog', (d) => d.accept());
await page.goto(base + '/');
await page.locator('.role-btn', { hasText: /director/i }).first().click();
await page.fill('#org-name', 'Tick FC'); await page.fill('#org-director', 'Joel');
await page.click('#create-org'); await page.waitForURL(/coach\.html/);
await page.waitForSelector('#wizard-skip'); await page.click('#wizard-skip'); await page.waitForTimeout(1500);
await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));
await page.evaluate(() => document.querySelectorAll('.tab-off').forEach((c) => c.classList.remove('tab-off')));  // all tabs shown

const ticked = (title) => page.evaluate((t) => {
  const row = [...document.querySelectorAll('.setup-step')].find((n) => n.querySelector('b').textContent.startsWith(t));
  return !!row && row.classList.contains('done');
}, title);
const stars = () => page.evaluate(() => [...document.querySelectorAll('.todo-star')].map((n) => n.closest('.card')?.id));
const settle = () => page.waitForTimeout(2200);

check(!(await ticked('Import the roster')), 'start: roster step is not ticked');
await page.fill('#new-team', '2031 Red'); await page.waitForTimeout(500);
await page.fill('#new-team-coach', 'Sam Hill'); await page.fill('#new-team-coach-email', 'sam@example.com');
await page.click('#add-team'); await settle();
check(await ticked('Create your teams'), 'a team was added: Create your teams ticks, no reload');
check((await stars()).includes('import-card') && !(await stars()).includes('teams-card'), 'the star moves from Teams to the roster');

await page.setInputFiles('#dropzone input[type=file]', f); await page.waitForTimeout(1500);
await page.click('#confirm-import'); await settle();
check(await ticked('Import the roster'), 'a file was imported: Import the roster ticks, no reload');
check(!(await stars()).includes('import-card'), 'the roster star clears');

// one player added by hand, to a program that has players already
await page.fill('#ap-first', 'Noah'); await page.fill('#ap-last', 'Finn'); await page.fill('#ap-year', '2013');
await page.fill('#ap-email', 'noah.mom@example.com'); await page.fill('#ap-phone', '615-555-0142');
await page.selectOption('#ap-team', { index: 1 }).catch(() => {});
await page.click('#ap-add'); await settle();
check(await page.locator('#ap-ok').innerText().then((t) => /is on the team/.test(t)), 'a player was added by hand');
check(await ticked('Import the roster'), 'still ticked after adding a player');

// delete every upload: the athletes go, so the tick must go
const dels = page.locator('[data-del-import]');
for (let i = await dels.count(); i > 0; i -= 1) { await dels.first().click(); await settle(); }
const left = await page.evaluate(async () => {
  const t = localStorage.getItem('offdays.token');
  const j = await (await fetch('/api/coach/onboarding', { headers: { Authorization: 'Bearer ' + t } })).json();
  return j.steps.find((s) => s.key === 'athletes').done;
});
check((await ticked('Import the roster')) === left, `the checklist agrees with the server after deleting uploads (server says done=${left})`);
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good'); process.exit(bad ? 1 : 0);
