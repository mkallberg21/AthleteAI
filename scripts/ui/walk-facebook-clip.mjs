// A coach pastes a Facebook share link; a 15 year old watches it inside 0FFDAYS in Facebook's own player; an 11 year old is not offered it.
// Needs a browser with H.264 (Edge), a scratch server with POST /__athlete/{org}/{team}/{name}/{age}, and the internet.
//   node walk-facebook-clip.mjs <base> <out-dir>
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';

const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what, extra = '') => { console.log(`${ok ? 'ok   ' : 'FAIL '}${what} ${extra}`); if (!ok) bad += 1; };
const j = async (path, token, body) => {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = 'Bearer ' + token;
  const r = await fetch(base + path, { method: body ? 'POST' : 'GET', headers, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, json: await r.json().catch(() => ({})) };
};
const SHARE = 'https://www.facebook.com/share/r/1A2kybptam/?mibextid=wwXIfr';
const made = (await j('/api/orgs', null, { name: 'Nashville Dogs', sport: 'lacrosse', accept_terms: true, director_name: 'Matt Kallberg' })).json;
const dt = made.director.token;
const red = (await j('/api/teams', dt, { name: '2031 Red' })).json.id;
const joel = (await j('/api/coach/staff', dt, { display_name: 'Joel White', email: 'joel@example.com', team_ids: [red] })).json;
const teen = (await j(`/__athlete/${made.org_id}/${red}/Teen/15`, null, {})).json;
const kid = (await j(`/__athlete/${made.org_id}/${red}/Kid/11`, null, {})).json;

const b = await chromium.launch({ channel: 'msedge' });
const errs = [];
const open = async (token, pageName, device) => {
  const ctx = await b.newContext(device);
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errs.push(`${pageName}: ${e.message}`));
  await page.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
  await page.goto(`${base}/app/index.html`, { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => localStorage.setItem('offdays.token', t), token);
  await page.goto(`${base}/app/${pageName}`, { waitUntil: 'networkidle' });
  return page;
};

// ---------------------------------------------------------------- the coach
const coach = await open(joel.code, 'coach.html', { viewport: { width: 1280, height: 1200 } });
if (await coach.locator('#wizard-skip').isVisible().catch(() => false)) { await coach.click('#wizard-skip'); await coach.waitForTimeout(800); }
await coach.click('#tabbar [data-tab="today"]');
if (!(await coach.locator('#film-card.open').count())) await coach.click('#film-card > h2');
await coach.click('#film-card details > summary');
await coach.fill('#clip-url', SHARE);
check(await coach.locator('#clip-ig-note').isVisible(), 'pasting a Facebook share link shows what a Facebook clip cannot do');
const note = (await coach.locator('#clip-ig-note').innerText()).replace(/\s+/g, ' ');
check(/A clip from Facebook works differently/.test(note) && !/Instagram/.test(note), 'and the note names Facebook, not Instagram', note.slice(0, 90));
check(/does not copy or keep the video/.test(note) && /View Video/.test(note), 'it says the video is not copied, and warns about iPhones');
check(!(await coach.locator('#clip-times').isVisible()), 'start and end are hidden');
await coach.screenshot({ path: `${out}/1-coach-form.png` });
await coach.fill('#clip-title', 'Seven defense tips');
await coach.fill('#clip-focus', 'Where his eyes are');
await coach.click('#clip-save');
await coach.waitForFunction(() => /Added|could not|would not|not look/i.test(document.getElementById('clip-status').textContent), null, { timeout: 25000 });
const status = await coach.locator('#clip-status').innerText();
check(/Added/.test(status), 'the share link is resolved and the clip is added', status);
const list = (await coach.locator('#clip-list').innerText()).replace(/\s+/g, ' ');
check(/Seven defense tips .*ages 13\+ .*Facebook/.test(list), 'it is listed as ages 13+, from Facebook', list.slice(0, 120));
const pageLink = await coach.locator('#clip-list a:has-text("Open on Facebook")').getAttribute('href');
check(pageLink === 'https://www.facebook.com/reel/1805786367298615/', 'with a link to the reel on Facebook', pageLink);
await coach.screenshot({ path: `${out}/2-coach-list.png` });

// ---------------------------------------------------------------- the 15 year old
const t = await open(teen.token, 'capture.html', { ...devices['Pixel 7'] });
await t.waitForSelector('#film-list [data-clip]', { timeout: 20000 });
const teenList = (await t.locator('#film-list').innerText()).replace(/\s+/g, ' ');
check(/Seven defense tips/.test(teenList) && /From Facebook/.test(teenList), 'a 15 year old is offered it, marked "From Facebook"', teenList.slice(0, 100));
const fbCalls = [];
t.on('request', (r) => { if (/facebook\.com|fbcdn\.net/.test(r.url())) fbCalls.push(r.url().slice(0, 60)); });
check(fbCalls.length === 0, 'nothing has talked to Facebook before the clip is opened');
await t.locator('#film-list [data-clip]', { hasText: 'Seven defense tips' }).click();
await t.waitForSelector('#film-frame iframe', { timeout: 15000 });
const src = await t.locator('#film-frame iframe').getAttribute('src');
check(/^https:\/\/www\.facebook\.com\/plugins\/video\.php\?href=https%3A%2F%2Fwww\.facebook\.com%2Freel%2F1805786367298615%2F/.test(src), 'it opens in Facebook\'s own player', src.slice(0, 80));
const told = (await t.locator('#film-untracked').innerText()).replace(/\s+/g, ' ');
check(/plays in Facebook's own player/.test(told) && /opened it, not how much you watched/.test(told), 'the athlete is told what the coach can see', told.slice(0, 110));
check(await t.locator('#film-page').getAttribute('href') === 'https://www.facebook.com/reel/1805786367298615/', 'and is offered the reel on Facebook if the player only shows a button');
check(!(await t.locator('.film-bar').isVisible()), 'there is no progress bar pretending to track it');
await t.waitForTimeout(7000);
const frame = t.frames().find((f) => /facebook\.com\/plugins/.test(f.url()));
const box = await t.locator('#film-frame iframe').boundingBox();
await t.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
await t.waitForTimeout(6000);
const v = frame ? await frame.evaluate(() => { const e = document.querySelector('video'); return e ? { t: e.currentTime, paused: e.paused, dur: Math.round(e.duration) } : null; }).catch(() => null) : null;
check(!!v && v.t > 1 && !v.paused, 'the video plays inside 0FFDAYS with nobody signed in to Facebook', JSON.stringify(v));
await t.screenshot({ path: `${out}/3-athlete-playing.png` });
const ours = fbCalls.filter((u) => u.startsWith(base));
check(ours.length === 0 && fbCalls.length > 0, 'the video comes from Facebook, not from 0FFDAYS', `${fbCalls.length} requests to Facebook`);

// ---------------------------------------------------------------- the 11 year old
const k = await open(kid.token, 'capture.html', { ...devices['Pixel 7'] });
await k.waitForTimeout(2500);
const kidList = (await k.locator('#film-list').innerText().catch(() => '')).replace(/\s+/g, ' ');
check(!/Seven defense tips|Facebook/.test(kidList), 'an 11 year old is not offered it', kidList.slice(0, 80));

// ---------------------------------------------------------------- what the coach then sees
const cov = (await j('/api/coach/film/coverage', joel.code)).json.clips.find((c) => c.title === 'Seven defense tips');
check(cov.tracked === false && cov.watched_count === 0 && cov.started.length === 1, 'the coach sees one athlete opened it, and nobody "watched"');

check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
