// The default Lacrosse IQ shelf, in a real browser: a program that added nothing, three ages, the coach's
// card, a video that will not play. Run against a throwaway local server (never prod).
//
//   node walk-default-shelf.mjs <base> <outdir>
//
// YouTube is not reached: the walk answers the player's script request itself, so what is tested is OUR
// page (what is offered, what is drawn, what happens when the player reports an error), not YouTube.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8013';
const out = process.argv[3] || '.';
fs.mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const api = async (p, opt = {}, token) => {
  const r = await fetch(base + p, { method: opt.method || 'GET', headers: { 'content-type': 'application/json', ...(token ? { authorization: `Bearer ${token}` } : {}) }, body: opt.body ? JSON.stringify(opt.body) : undefined });
  return { status: r.status, body: await r.json().catch(() => ({})) };
};

// a brand-new program with nothing added to it
const org = (await api('/api/orgs', { method: 'POST', body: { name: 'Shelf Walk Club', director_name: 'Dir Walk' } })).body;
const director = org.director.token;
const year = new Date().getFullYear();
const kids = {};
for (const [name, age] of [['Nine', 9], ['Twelve', 12], ['Sixteen', 16]]) {
  const r = await api('/api/athletes', { method: 'POST', body: { display_name: name, birth_year: year - age, dominant_hand: 'right', guardian_consent: true } }, director);
  kids[name] = r.body.token;
}

const b = await chromium.launch();
const FAKE_API = `window.YT = { PlayerState: { PLAYING: 1 }, Player: function (id, o) { window.__yt = o; this.destroy = function(){}; this.getPlayerState = function(){ return 0; }; this.getCurrentTime = function(){ return 0; }; this.isMuted = function(){ return false; }; this.getVolume = function(){ return 80; }; this.getPlaybackRate = function(){ return 1; }; } }; if (window.onYouTubeIframeAPIReady) window.onYouTubeIframeAPIReady();`;

async function openAs(name, device = 'iPhone 13') {
  const ctx = await b.newContext({ ...devices[device] });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => { console.log('PAGE ERROR', e.message.slice(0, 200)); bad += 1; });
  await page.route('**/iframe_api', (route) => route.fulfill({ contentType: 'application/javascript', body: FAKE_API }));
  await page.goto(base + '/app/capture.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => { localStorage.setItem('offdays.token', t); localStorage.setItem('offdays.awizard', 'done'); }, kids[name]);
  await page.goto(base + '/app/capture.html', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#film-card:not(.hidden)', { timeout: 8000 }).catch(() => {});
  await page.waitForTimeout(600);
  return { ctx, page };
}

const clipsOf = (page) => page.evaluate(() => JSON.parse(document.getElementById('film-list').dataset.clips || '[]'));

// ---- 1. nothing added, and the kid still has film
for (const [name, ceiling, limit] of [['Nine', 75, 2], ['Twelve', 100, 3], ['Sixteen', 170, 5]]) {
  const { ctx, page } = await openAs(name);
  const shown = await page.locator('#film-card').isVisible();
  const clips = await clipsOf(page);
  check(shown, `${name}: film card is there with nothing added by the program`);
  check(clips.length > 0 && clips.length <= limit, `${name}: ${clips.length} clips offered (daily limit ${limit})`);
  check(clips.every((c) => c.length_s <= ceiling), `${name}: every clip is within ${ceiling}s`);
  const credits = await page.locator('#film-list .transfer-inline').allInnerTexts();
  check(credits.length > 0 && credits.every((t) => /seconds/.test(t) && t.split('\u00b7').length >= 2), `${name}: each clip says its length and whose it is`);
  if (name === 'Nine') {
    const youngest = clips.map((c) => c.min_age);
    check(youngest.every((a) => a <= 9), 'Nine: nothing written for older players');
    await page.screenshot({ path: path.join(out, 'shelf-nine-phone.png') });
  }
  if (name === 'Sixteen') check(clips.every((c) => c.min_age >= 13), 'Sixteen: no beginner basics in front of a sixteen-year-old');
  await ctx.close();
}

// ---- 2. open a clip: title, whose it is, the player is asked for the right video
{
  const { ctx, page } = await openAs('Twelve');
  const first = (await clipsOf(page))[0];
  await page.locator('#film-list [data-clip="0"]').click();
  await page.waitForTimeout(900);
  check(await page.locator('#view-film').isVisible(), 'a tapped clip opens the player screen');
  check((await page.locator('#film-title').innerText()) === first.title, 'the title is the clip\'s');
  check(/From .+Plays in YouTube/.test(await page.locator('#film-credit').innerText()), 'it says whose video it is and that it plays in YouTube\'s own player');
  const asked = await page.evaluate(() => window.__yt && window.__yt.videoId);
  check(asked === first.video_id, 'the player is asked for that clip\'s video id');
  const host = await page.evaluate(() => window.__yt && window.__yt.host);
  check(/youtube-nocookie\.com/.test(host || ''), 'it uses the privacy-enhanced host');
  await page.screenshot({ path: path.join(out, 'shelf-player-phone.png') });

  // ---- 3. the video will not play
  const before = (await api('/api/film', {}, kids.Twelve)).body.day.clips;
  await page.evaluate(() => window.__yt.events.onError({ data: 150 }));
  await page.waitForTimeout(900);
  check(await page.locator('#film-broken').isVisible(), 'a video that will not play says so, in plain words');
  const after = await api('/api/film', {}, kids.Twelve);
  check(before === 1 && after.body.day.clips === 0, `the day's slot was given back (${before} -> ${after.body.day.clips})`);
  check(!after.body.clips.some((c) => c.id === first.id), 'and it is not offered to that kid again');
  await page.screenshot({ path: path.join(out, 'shelf-broken-phone.png') });
  await page.locator('#film-done').click();
  await page.waitForTimeout(700);
  check(await page.locator('#film-card').isVisible(), 'Done goes back to the list');
  await ctx.close();
}

// ---- 4. the watch-again list is drawn
{
  const { ctx, page } = await openAs('Nine');
  const first = (await clipsOf(page))[0];
  const w = (await api(`/api/film/${first.id}/start`, { method: 'POST' }, kids.Nine)).body.watch_id;
  for (let s = 1; s <= first.length_s; s += 1) await api(`/api/film/watches/${w}/beat`, { method: 'POST', body: { position_s: s, muted: false, hidden: false, rate: 1 } }, kids.Nine);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#film-card:not(.hidden)');
  await page.waitForTimeout(700);
  check(await page.locator('#film-again-wrap').isVisible(), 'a clip watched today is listed under "watch again"');
  check(/Going back is the point/.test(await page.locator('#film-again-note').innerText()), 'and going back is encouraged');
  await page.locator('#film-again [data-again="0"]').click();
  await page.waitForTimeout(700);
  check((await page.locator('#film-title').innerText()) === first.title, 'tapping it opens the same clip again');
  await ctx.close();
}

// ---- 5. the director: the card, the list, hide, switch off
for (const [label, device] of [['phone', 'iPhone 13'], ['laptop', 'Desktop Chrome']]) {
  const ctx = await b.newContext({ ...devices[device] });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => { console.log('PAGE ERROR', e.message.slice(0, 200)); bad += 1; });
  await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => { localStorage.setItem('offdays.token', t); }, director);
  await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' });
  await page.locator('#wizard-skip').click({ timeout: 2500 }).catch(() => {});
  await page.waitForTimeout(800);
  await page.evaluate(() => {
    document.querySelectorAll('.tab-off').forEach((c) => c.classList.remove('tab-off'));
    document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen());
  });
  await page.waitForTimeout(600);
  check(await page.locator('#shelf-card').isVisible(), `${label}: the Lacrosse IQ Library card is on the dashboard`);
  const count = await page.locator('#shelf-count').innerText();
  check(/\d+ of \d+ showing/.test(count), `${label}: it says how many clips are showing (${count})`);
  await page.locator('#shelf-details summary').click();
  await page.waitForTimeout(300);
  const rows = await page.locator('#shelf-list .budget-row').count();
  check(rows >= 60, `${label}: it lists every clip (${rows})`);
  const link = await page.locator('#shelf-list a').first().getAttribute('href');
  check(/^https:\/\/www\.youtube\.com\/watch\?v=[\w-]{11}$/.test(link || ''), `${label}: each title links to the real video to preview`);
  await page.locator('#shelf-card').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, `shelf-coach-${label}.png`) });

  if (label === 'phone') {
    await page.locator('#shelf-list [data-shelf-clip]').first().click();
    await page.waitForTimeout(700);
    check(/\d+ of \d+ showing/.test(await page.locator('#shelf-count').innerText()) && /Show/.test(await page.locator('#shelf-list [data-shelf-clip]').first().innerText()), 'Hide hides the clip and the button becomes Show');
    const shelf = (await api('/api/coach/shelf', {}, director)).body;
    check(shelf.visible === shelf.total - 1, 'the server agrees: one hidden');
    await page.locator('#shelf-list [data-shelf-clip]').first().click();
    await page.waitForTimeout(500);

    page.once('dialog', (d) => d.accept());
    await page.locator('#shelf-off').click();
    await page.waitForTimeout(700);
    check(/Switched off/.test(await page.locator('#shelf-use').innerText()), 'Turn the shelf off asks first, then says it is switched off');
    check((await api('/api/film', {}, kids.Twelve)).body.clips.length === 0, 'and the kid now sees nothing from it');
    await page.locator('#shelf-on').click();
    await page.waitForTimeout(600);
    check((await api('/api/film', {}, kids.Sixteen)).body.clips.length > 0, 'turning it back on brings the shelf back');
  }
  await ctx.close();
}

// ---- 6. a coach (not a director) sees the card but not the switch
{
  const asst = (await api('/api/teams', { method: 'POST', body: { name: 'Walk Team', coach_name: 'Asst Coach', coach_email: 'asst@example.invalid' } }, director)).body;
  const code = asst.coach && (asst.coach.token || asst.coach.code);
  if (code) {
    const ctx = await b.newContext({ ...devices['iPhone 13'] });
    const page = await ctx.newPage();
    await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate((t) => { localStorage.setItem('offdays.token', t); }, code);
    await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' });
    await page.locator('#wizard-skip').click({ timeout: 2500 }).catch(() => {});
    await page.waitForTimeout(900);
    await page.evaluate(() => { document.querySelectorAll('.tab-off').forEach((c) => c.classList.remove('tab-off')); document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()); });
    await page.waitForTimeout(400);
    check(await page.locator('#shelf-card').isVisible(), 'a coach sees the shelf');
    check((await page.locator('#shelf-off, #shelf-on').count()) === 0, 'but not the switch to turn it off');
    await ctx.close();
  } else console.log('note: could not mint a coach login here; skipped the coach check');
}

await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
