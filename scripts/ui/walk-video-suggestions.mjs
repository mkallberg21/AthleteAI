// Suggested videos, in a real browser: the card, a preview link, add with a changed line, dismiss, and what the
// athlete then sees. Run against a throwaway local server with a fake YouTube behind the scanner.
//
//   node walk-video-suggestions.mjs <base> <outdir> [expect: on|off]
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8014';
const out = process.argv[3] || '.';
const expectOn = (process.argv[4] || 'on') === 'on';
fs.mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const api = async (p, opt = {}, token) => {
  const r = await fetch(base + p, { method: opt.method || 'GET', headers: { 'content-type': 'application/json', ...(token ? { authorization: `Bearer ${token}` } : {}) }, body: opt.body ? JSON.stringify(opt.body) : undefined });
  return { status: r.status, body: await r.json().catch(() => ({})) };
};

const org = (await api('/api/orgs', { method: 'POST', body: { name: 'Suggest Walk Club', accept_terms: true, director_name: 'Dir Walk' } })).body;
const director = org.director.token;
const year = new Date().getFullYear();
const kid = (await api('/api/athletes', { method: 'POST', body: { display_name: 'Twelve', birth_year: year - 12, dominant_hand: 'right', guardian_consent: true } }, director)).body.token;

async function dashboard(device, label) {
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
  return { ctx, page };
}

const b = await chromium.launch();

if (!expectOn) {
  const { ctx, page } = await dashboard('iPhone 13', 'off');
  check(await page.locator('#suggest-card').isVisible(), 'the card is there even with no key');
  check(/not switched on/i.test(await page.locator('#suggest-note').innerText()), 'and says plainly it is not switched on');
  check((await page.locator('#suggest-list .budget-row').count()) === 0, 'with nothing in it');
  await page.screenshot({ path: path.join(out, 'suggest-off-phone.png') });
  await ctx.close(); await b.close();
  console.log(bad ? `${bad} FAILED` : 'all good'); process.exit(bad ? 1 : 0);
}

// ---- the list
{
  const { ctx, page } = await dashboard('iPhone 13', 'phone');
  check(await page.locator('#suggest-card').isVisible(), 'phone: the Suggested videos card is on the dashboard');
  const rows = await page.locator('#suggest-list [data-sid]').count();
  check(rows === 4, `phone: four suggestions waiting; the highlight reel, the private one and the 15-minute one are not (${rows})`);
  check(/4 waiting/.test(await page.locator('#suggest-count').innerText()), 'phone: it says how many are waiting');
  const titles = await page.locator('#suggest-list a').allInnerTexts();
  check(!titles.some((t) => /highlights|private|very long/i.test(t)), 'phone: nothing it should have turned away');
  const first = await page.locator('#suggest-list a').first().getAttribute('href');
  check(/^https:\/\/www\.youtube\.com\/watch\?v=sug\w{8}$/.test(first || ''), 'phone: the title links to the real video to watch first');
  check(/Nothing reaches a player unless you add it/.test(await page.locator('#suggest-card').innerText()), 'phone: it says nothing reaches a player unless added');
  await page.locator('#suggest-card').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'suggest-phone.png') });
  const btn = await page.locator('#suggest-list [data-add]').first().boundingBox();
  check(btn && btn.height < 60 && btn.width < 300, `phone: buttons are compact, not full-width slabs (${Math.round(btn.width)}x${Math.round(btn.height)})`);
  await ctx.close();
}
{
  const { ctx, page } = await dashboard('Desktop Chrome', 'laptop');
  check((await page.locator('#suggest-list [data-sid]').count()) === 4, 'laptop: the same four');
  await page.locator('#suggest-card').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'suggest-laptop.png') });
  await ctx.close();
}

// ---- add one with a changed line, dismiss one
{
  const { ctx, page } = await dashboard('iPhone 13', 'act');
  const before = (await api('/api/film', {}, kid)).body.clips.map((c) => c.video_id);
  check(!before.some((v) => v.startsWith('sug')), 'before: no player sees any suggestion');

  const row = page.locator('#suggest-list [data-sid]').first();
  const title = await row.locator('a').innerText();
  await row.locator('.suggest-focus').fill('Count how many passes before the slide.');
  await row.locator('[data-add]').click();
  await page.waitForTimeout(1200);
  check((await page.locator('#suggest-list [data-sid]').count()) === 3, 'adding takes it off the list');
  const clips = (await api('/api/coach/clips', {}, director)).body.clips;
  check(clips.length === 1 && clips[0].title === title && clips[0].focus === 'Count how many passes before the slide.', 'it is now one of the program\'s own clips, with the coach\'s line');

  const feed = (await api('/api/film', {}, kid)).body.clips;
  check(feed[0].video_id === clips[0].video_id && feed[0].shelf === '', 'a player now sees it, first, as the program\'s own clip');
  check(feed[0].length_s <= 100, `and it fits the 12-year-old's cap (${feed[0].length_s}s)`);

  const second = page.locator('#suggest-list [data-sid]').first();
  const dismissedTitle = await second.locator('a').innerText();
  await second.locator('[data-no]').click();
  await page.waitForTimeout(1000);
  check((await page.locator('#suggest-list [data-sid]').count()) === 2, 'Not for us takes it off the list');
  const after = (await api('/api/film', {}, kid)).body.clips.map((c) => c.title);
  check(!after.includes(dismissedTitle), 'and a dismissed one never reaches a player');
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('#wizard-skip').click({ timeout: 1500 }).catch(() => {});
  await page.waitForTimeout(900);
  await page.evaluate(() => { document.querySelectorAll('.tab-off').forEach((c) => c.classList.remove('tab-off')); document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()); });
  await page.waitForTimeout(400);
  check((await page.locator('#suggest-list [data-sid]').count()) === 2 && !(await page.locator('#suggest-list').innerText()).includes(dismissedTitle), 'after a reload the dismissed one stays gone');
  await ctx.close();
}

// ---- a different program is not affected by this one's choices
{
  const other = (await api('/api/orgs', { method: 'POST', body: { name: 'Other Club', accept_terms: true, director_name: 'Other Dir' } })).body.director.token;
  const theirs = (await api('/api/coach/suggestions', {}, other)).body.suggestions;
  check(theirs.length === 4, 'another program still sees all four');
}

// ---- a goalie clip is added for goalies, an athlete cannot see the card's routes
{
  const goalie = (await api('/api/coach/suggestions', {}, director)).body.suggestions.find((s) => /goalie/i.test(s.title));
  if (goalie) {
    const made = await api(`/api/coach/suggestions/${goalie.id}/add`, { method: 'POST', body: {} }, director);
    check(made.status === 201 && JSON.stringify(made.body.positions) === '["goalie"]', 'a goalie clip is added for goalies only');
  }
  const asAthlete = await api('/api/coach/suggestions', {}, kid);
  check([401, 403].includes(asAthlete.status), 'an athlete cannot read the suggestions');
}

await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
