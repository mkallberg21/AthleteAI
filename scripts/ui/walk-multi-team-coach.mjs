// One coach on several teams: the dashboard offers them in a list, and nobody is entered twice.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8010';
const T = path.join(process.env.LOCALAPPDATA || os.tmpdir(), 'Temp', 'pw');
fs.mkdirSync(T, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const j = (u, b, h = {}, m = 'POST') => fetch(base + u, { method: m, headers: { 'Content-Type': 'application/json', ...h }, body: JSON.stringify(b) });

const b = await chromium.launch();
for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const org = await (await j('/api/orgs', { name: `Multi ${tag} ${Date.now()}`, accept_terms: true, director_name: 'Joel' })).json();
  const auth = { Authorization: `Bearer ${org.director.token}` };
  const page = await (await b.newContext(opts)).newPage();
  page.on('pageerror', (e) => console.log('PAGE ERROR', e.message.slice(0, 150)));
  await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => localStorage.setItem('offdays.token', t), org.director.token);
  await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(3000);
  if (await page.locator('#wizard-skip').isVisible().catch(() => false)) { await page.click('#wizard-skip'); await page.waitForTimeout(800); }
  await page.click('#tabbar [data-tab="teams"]'); await page.waitForTimeout(500);
  const open = async (sel) => { await page.evaluate((q) => { let e = document.querySelector(q); while (e) { if (e.classList && e.classList.contains('card')) e.classList.add('open'); e = e.parentElement; } }, sel); await page.waitForTimeout(200); };
  await open('#new-team'); await open('#staff-list');

  const add = async (team, coach, email) => {
    await page.fill('#new-team', team);
    if (coach !== null) { await page.fill('#new-team-coach', coach); await page.fill('#new-team-coach-email', email); }
    await page.click('#add-team'); await page.waitForTimeout(1500);
    return page.locator('#new-team-out').innerText();
  };

  check(await page.locator('#new-team-pick-wrap').isHidden(), `${tag}: with no coaches yet there is no pick list`);
  let msg = await add('2031 Red', 'Sam Hill', 'sam@example.com');
  check(/Sam Hill/.test(msg), `${tag}: first team with a new coach (${msg.slice(0, 60)}...)`);
  check(await page.locator('#new-team-pick-wrap').isVisible(), `${tag}: now the pick list appears`);
  const optionText = await page.locator('#new-team-pick option').allInnerTexts();
  check(optionText.some((t) => /Sam Hill/.test(t) && /1 team/.test(t)), `${tag}: it lists Sam Hill with how many teams (${optionText.join(' | ')})`);

  await page.fill('#new-team', '2031 Blue');
  await page.selectOption('#new-team-pick', { label: optionText.find((t) => /Sam Hill/.test(t)) });
  check(await page.locator('#new-team-coach').isHidden(), `${tag}: picking a coach hides the name and email boxes`);
  await page.locator('#new-team-pick').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(T, `${tag}-5-pick.png`) });
  await page.click('#add-team'); await page.waitForTimeout(1500);
  msg = await page.locator('#new-team-out').innerText();
  check(/now coaches it too/.test(msg) && !/undefined/.test(msg), `${tag}: says Sam now coaches it, nothing to send (${msg.slice(0, 90)})`);
  check(await page.locator('#new-team-pick').inputValue() === '', `${tag}: the pick resets for the next team`);

  msg = await add('2032 Red', 'Sam Hill', 'SAM@example.com');
  check(/now coaches it too/.test(msg), `${tag}: typing the same email again also reuses him`);

  const staff = (await (await fetch(base + '/api/coach/staff', { headers: auth })).json()).staff.filter((s) => s.role === 'coach');
  check(staff.length === 1 && staff[0].teams.length === 3, `${tag}: ONE coach on THREE teams (${staff.length} coach, ${staff[0]?.teams.length} teams)`);
  await page.locator('#staff-list').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(T, `${tag}-6-staff.png`) });
  await page.context().close();
}
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good'); process.exit(bad ? 1 : 0);
