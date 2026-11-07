// Team home screens: a director sees every team (and each one on its own); a coach with
// two teams sees those two and never a third.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8010';
const T = path.join(process.env.LOCALAPPDATA || os.tmpdir(), 'Temp', 'pw');
fs.mkdirSync(T, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const j = (u, b, h = {}) => fetch(base + u, { method: 'POST', headers: { 'Content-Type': 'application/json', ...h }, body: JSON.stringify(b) }).then((r) => r.json());

const b = await chromium.launch();
for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const org = await j('/api/orgs', { name: `Homes ${tag} ${Date.now()}`, director_name: 'Joel' });
  const dir = { Authorization: `Bearer ${org.director.token}` };
  const team = {};
  for (const n of ['2031 Red', '2031 Blue', '2032 Green']) team[n] = await j('/api/teams', { name: n }, dir);
  const sam = await j('/api/coach/staff', { display_name: 'Sam Hill', email: `sam.${Date.now()}@example.com`, team_ids: [team['2031 Red'].id, team['2031 Blue'].id] }, dir);
  for (const [t, kid] of [['2031 Red', 'Red Kid'], ['2031 Blue', 'Blue Kid'], ['2032 Green', 'Green Kid']]) {
    await j('/api/athletes', { display_name: kid, join_code: team[t].join_code }, dir);
  }

  async function open(token) {
    const page = await (await b.newContext(opts)).newPage();
    page.on('pageerror', (e) => console.log('PAGE ERROR', e.message.slice(0, 150)));
    await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate((t) => localStorage.setItem('offdays.token', t), token);
    await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(3000);
    if (await page.locator('#wizard-skip').isVisible().catch(() => false)) { await page.click('#wizard-skip'); await page.waitForTimeout(800); }
    return page;
  }
  const families = async (page) => {
    await page.click('#tabbar [data-tab="families"]'); await page.waitForTimeout(600);
    await page.evaluate(() => { let e = document.querySelector('#families'); while (e) { if (e.classList && e.classList.contains('card')) e.classList.add('open'); e = e.parentElement; } });
    await page.waitForTimeout(300);
    return (await page.locator('#families').innerText()).replace(/\s+/g, ' ');
  };
  const options = (page) => page.locator('#team option').allInnerTexts();

  // ---- director
  let page = await open(org.director.token);
  const dOpts = await options(page);
  check(dOpts.length === 4 && dOpts[0] === 'All teams', `${tag}: director's chooser lists All teams + every team (${dOpts.join(' | ')})`);
  let txt = await families(page);
  check(['Red Kid', 'Blue Kid', 'Green Kid'].every((k) => txt.includes(k)), `${tag}: director sees every team's kids on Families`);
  await page.selectOption('#team', { label: '2032 Green' }); await page.waitForTimeout(1500);
  txt = await families(page);
  check(txt.includes('Green Kid') && !txt.includes('Red Kid') && !txt.includes('Blue Kid'), `${tag}: choosing 2032 Green shows only Green Kid`);
  await page.click('#tabbar [data-tab="today"]'); await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(T, `${tag}-7-director-green.png`) });
  await page.reload({ waitUntil: 'domcontentloaded' }); await page.waitForTimeout(3000);
  check(await page.locator('#team').inputValue() === String(team['2032 Green'].id), `${tag}: the chosen team is remembered after a reload`);
  await page.selectOption('#team', ''); await page.waitForTimeout(1500);
  txt = await families(page);
  check(['Red Kid', 'Blue Kid', 'Green Kid'].every((k) => txt.includes(k)), `${tag}: back to All teams shows everyone`);
  await page.context().close();

  // ---- coach on two teams
  page = await open(sam.code);
  const cOpts = await options(page);
  check(cOpts.length === 3 && !cOpts.includes('2032 Green'), `${tag}: Sam's chooser has All + Red + Blue, not Green (${cOpts.join(' | ')})`);
  txt = await families(page);
  check(txt.includes('Red Kid') && txt.includes('Blue Kid') && !txt.includes('Green Kid'), `${tag}: Sam sees Red and Blue kids and never Green`);
  await page.selectOption('#team', { label: '2031 Blue' }); await page.waitForTimeout(1500);
  txt = await families(page);
  check(txt.includes('Blue Kid') && !txt.includes('Red Kid'), `${tag}: choosing 2031 Blue shows only Blue Kid`);
  await page.click('#tabbar [data-tab="today"]'); await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(T, `${tag}-8-sam-blue.png`) });
  await page.context().close();
}
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good'); process.exit(bad ? 1 : 0);
