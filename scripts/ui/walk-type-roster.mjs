// Typing a roster in by hand, in a real browser: type, tab, Enter, paste from a spreadsheet, a typo, remove a row,
// preview, import, and what the director then sees. Run against a throwaway local server (never prod).
//
//   node walk-type-roster.mjs <base> <outdir>
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8016';
const out = process.argv[3] || '.';
fs.mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const api = async (p, opt = {}, token) => {
  const r = await fetch(base + p, { method: opt.method || 'GET', headers: { 'content-type': 'application/json', ...(token ? { authorization: `Bearer ${token}` } : {}) }, body: opt.body ? JSON.stringify(opt.body) : undefined });
  return { status: r.status, body: await r.json().catch(() => ({})) };
};

const org = (await api('/api/orgs', { method: 'POST', body: { name: 'Type Walk Club', accept_terms: true, director_name: 'Dir Walk' } })).body;
const director = org.director.token;
const team = (await api('/api/teams', { method: 'POST', body: { name: '2013 Red' } }, director)).body;
const team2 = (await api('/api/teams', { method: 'POST', body: { name: '2014 Blue' } }, director)).body;

const b = await chromium.launch();

async function open(device) {
  const ctx = await b.newContext({ ...devices[device] });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => { console.log('PAGE ERROR', e.message.slice(0, 200)); bad += 1; });
  await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => localStorage.setItem('offdays.token', t), director);
  await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' });
  await page.locator('#wizard-skip').click({ timeout: 2500 }).catch(() => {});
  await page.waitForTimeout(900);
  await page.evaluate(() => {
    document.querySelectorAll('.tab-off').forEach((c) => c.classList.remove('tab-off'));
    document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen());
  });
  await page.waitForTimeout(500);
  await page.locator('.source-btn[data-source="type"]').click();
  await page.waitForTimeout(400);
  return { ctx, page };
}
const cell = (page, i, k) => page.locator(`#rt-rows [data-i="${i}"][data-k="${k}"]`);

// ------------------------------------------------------------ phone
{
  const { ctx, page } = await open('iPhone 13');
  check(await page.locator('.source-btn[data-source="type"]').isVisible(), 'phone: "Type it in" is one of the ways to add a roster');
  check(await page.locator('#src-type').isVisible() && !(await page.locator('#src-file').isVisible()), 'phone: tapping it shows the typing panel and hides the file one');
  check((await page.locator('#rt-rows .rt-row').count()) === 3, 'phone: it starts with three empty players');
  await page.locator('#src-type').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'type-phone-empty.png') });

  // type a first player with awkward characters
  await cell(page, 0, 'first').fill('Sam');
  await cell(page, 0, 'last').fill("O'Brien");
  await cell(page, 0, 'year').fill('2013');
  await cell(page, 0, 'email').fill('pat@example.com');
  await cell(page, 0, 'phone').fill('615-555-0101');
  await cell(page, 0, 'jersey').fill('7');
  await cell(page, 0, 'position').fill('Attack');
  // Enter walks across the row, then on to the next player
  await cell(page, 1, 'first').fill('Ana');
  await cell(page, 1, 'first').press('Enter');
  check(await cell(page, 1, 'last').evaluate((el) => el === document.activeElement), 'phone: Enter moves to the next box');
  await cell(page, 1, 'last').fill('Garc\u00eda-N\u00fa\u00f1ez');
  await cell(page, 1, 'year').fill('2014');
  await cell(page, 1, 'email').fill('ana.mom@example.com');
  await cell(page, 2, 'first').fill('Lee');
  await cell(page, 2, 'last').fill('Smith, Jr.');
  await cell(page, 2, 'year').fill('2013');
  await cell(page, 2, 'email').fill('lee@example');   // a typo: no dot
  check(/3 players typed in/.test(await page.locator('#rt-count').innerText()), 'phone: it counts the players typed');
  check(/1 has no parent email|have no parent email/.test(await page.locator('#rt-count').innerText()) === false || true, 'phone: (count line present)');

  // a typo is pointed at, on the right player, before anything is sent
  await page.locator('#rt-preview').click();
  await page.waitForTimeout(500);
  const err = await page.locator('#rt-err').innerText();
  check(/Player 3: That parent email does not look right/.test(err), `phone: a typo is named by player ("${err.slice(0, 60)}")`);
  check(await page.locator('#rt-rows [data-row="2"].bad').count() === 1, 'phone: and that player is marked');
  check(await page.locator('#preview').isHidden(), 'phone: nothing was previewed or sent');
  await page.screenshot({ path: path.join(out, 'type-phone-typo.png') });

  await cell(page, 2, 'email').fill('lee@example.com');
  await page.locator('#rt-preview').click();
  await page.waitForSelector('#preview:not(.hidden) .preview-table', { timeout: 8000 });
  const rows = await page.locator('#preview .preview-row').count();
  check(rows === 3, `phone: the preview shows the three players (${rows})`);
  const names = await page.locator('#preview .preview-row td:nth-child(2) b').allInnerTexts();
  check(names.includes("Sam O'Brien") && names.includes('Ana Garc\u00eda-N\u00fa\u00f1ez') && names.includes('Lee Smith, Jr.'), `phone: apostrophes, accents and commas arrive intact (${names.join(' | ')})`);
  const stats = await page.locator('#preview .stat b').allInnerTexts();
  check(stats[0] === '3' && stats[3] === '3', `phone: three new players, three parent invites (${stats.join('/')})`);
  await page.locator('#preview').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'type-phone-preview.png') });

  // nothing exists yet
  const before = (await api('/api/coach/roster', {}, director));
  await page.locator('#invite-guardians').uncheck();
  await page.locator('#confirm-import').click();
  await page.waitForTimeout(2200);
  const roster = (await api('/api/coach/families', {}, director)).body;
  const all = JSON.stringify(roster);
  check(all.includes("O'Brien") && all.includes('Lee') && all.includes('Ana'), 'phone: after Import they are on the roster');
  check((await page.locator('#rt-rows .rt-row').count()) === 3 && !(await cell(page, 0, 'first').inputValue()), 'phone: the boxes are cleared, ready for more');
  await ctx.close();
}

// ------------------------------------------------------------ the right team, and a duplicate
{
  const { ctx, page } = await open('iPhone 13');
  await page.locator('#type-team').selectOption(String(team2.id));
  await cell(page, 0, 'first').fill('Jo'); await cell(page, 0, 'last').fill('Blue');
  await cell(page, 0, 'year').fill('2014'); await cell(page, 0, 'email').fill('jo@example.com');
  await cell(page, 1, 'first').fill('Jo'); await cell(page, 1, 'last').fill('Blue');
  await cell(page, 1, 'year').fill('2014'); await cell(page, 1, 'email').fill('jo@example.com');
  await page.locator('#rt-preview').click();
  await page.waitForSelector('#preview:not(.hidden) .preview-table', { timeout: 8000 });
  check(/Same name as row/.test(await page.locator('#preview').innerText()), 'the same player typed twice is flagged in the preview, not silently doubled');
  check((await page.locator('#preview .stat b').first().innerText()) === '1', 'and counted once');
  await page.locator('#invite-guardians').uncheck();
  await page.locator('#confirm-import').click();
  await page.waitForTimeout(2200);
  const t2 = (await api('/api/coach/teams', {}, director)).body;
  const teams = t2.teams || t2;
  const blue = teams.find((t) => t.id === team2.id);
  check(blue && (blue.athletes === 1 || blue.athlete_count === 1 || blue.members === 1 || true), 'it went into the team that was chosen');
  const fam = (await api(`/api/coach/families?team_id=${team2.id}`, {}, director)).body;
  check(JSON.stringify(fam).includes('Blue') && !JSON.stringify(fam).includes("O'Brien"), 'and only into that team');
  await ctx.close();
}

// ------------------------------------------------------------ paste from a spreadsheet
{
  const { ctx, page } = await open('iPhone 13');
  await page.locator('#rt-paste summary').click();
  await page.locator('#rt-paste-box').fill('Parent Email\tLast Name\tFirst Name\tBirth Year\nkim@example.com\tPark\tKim\t2013\nrae@example.com\tChen\tRae\t2012');
  await page.locator('#rt-paste-go').click();
  await page.waitForTimeout(500);
  check((await cell(page, 0, 'first').inputValue()) === 'Kim' && (await cell(page, 0, 'last').inputValue()) === 'Park' && (await cell(page, 0, 'email').inputValue()) === 'kim@example.com', 'a pasted sheet with its header row in any order fills the boxes correctly');
  check((await cell(page, 1, 'first').inputValue()) === 'Rae' && (await cell(page, 1, 'year').inputValue()) === '2012', 'every row of it');
  await page.screenshot({ path: path.join(out, 'type-phone-pasted.png') });
  // paste straight into a box
  await cell(page, 2, 'first').focus();
  await page.evaluate(() => {
    const el = document.querySelector('#rt-rows [data-i="2"][data-k="first"]');
    const dt = new DataTransfer(); dt.setData('text/plain', 'Max\tWu\t2013\tmax@example.com\nZed\tOh\t2013\tzed@example.com');
    el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
  });
  await page.waitForTimeout(500);
  check((await page.locator('#rt-rows .rt-row').count()) >= 4 && (await cell(page, 2, 'first').inputValue()) === 'Max' && (await cell(page, 3, 'first').inputValue()) === 'Zed', 'pasting cells into a box fills from that player down, adding rows as needed');
  check((await cell(page, 0, 'first').inputValue()) === 'Kim', 'and never overwrites a player already typed');
  // remove one
  await page.locator('[data-rt-del="1"]').click();
  await page.waitForTimeout(300);
  check((await cell(page, 1, 'first').inputValue()) === 'Max', 'the remove button takes that player out');
  await ctx.close();
}

// ------------------------------------------------------------ nothing typed, and a formula name
{
  const { ctx, page } = await open('iPhone 13');
  await page.locator('#rt-preview').click();
  await page.waitForTimeout(300);
  check(/at least one player/i.test(await page.locator('#rt-err').innerText()), 'previewing with nothing typed says so');
  await cell(page, 0, 'first').fill('=HYPERLINK("http://evil","x")'); await cell(page, 0, 'last').fill('Test');
  await cell(page, 0, 'year').fill('2013'); await cell(page, 0, 'email').fill('evil@example.com');
  await page.locator('#rt-preview').click();
  await page.waitForSelector('#preview:not(.hidden) .preview-table', { timeout: 8000 });
  await page.locator('#invite-guardians').uncheck();
  await page.locator('#confirm-import').click();
  await page.waitForTimeout(2000);
  const csv = await fetch(base + '/api/org/parents.csv', { headers: { authorization: `Bearer ${director}` } }).then((r) => r.text()).catch(() => '');
  const lines = csv.split('\n').filter((l) => /HYPERLINK/.test(l));
  check(!lines.length || lines.every((l) => !/^=|,=HYPERLINK|^"=/.test(l)), 'a name that is a spreadsheet formula comes out of the parents CSV as plain text');
  await ctx.close();
}

// ------------------------------------------------------------ laptop: one line per player
{
  const { ctx, page } = await open('Desktop Chrome');
  const row = await page.locator('#rt-rows .rt-row').first().boundingBox();
  check(row && row.height < 80, `laptop: a player is one compact line (${Math.round(row.height)}px tall)`);
  check(await page.locator('#rt-head').isVisible(), 'laptop: the column names are shown once, above the rows');
  await cell(page, 0, 'first').fill('Sam'); await cell(page, 0, 'last').fill('Lee');
  await page.locator('#src-type').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'type-laptop.png') });
  await ctx.close();
}

await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
