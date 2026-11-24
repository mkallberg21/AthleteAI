// A coach adds an Instagram clip and uploads their own video; athletes of different ages open them.
// Run: node walk-clip-sources.mjs <base> <out-dir> <webm file>   (against a scratch server with the /__athlete route)
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';

const [base, out, webm] = process.argv.slice(2);
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
const teen = (await j(`/__athlete/${made.org_id}/${red}/Teen/15`, null, {})).json;
const kid = (await j(`/__athlete/${made.org_id}/${red}/Kid/11`, null, {})).json;

const b = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
const errs = [];
const open = async (token, pageName, device) => {
  const ctx = await b.newContext(device || { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 1200 } });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errs.push(`${pageName}: ${e.message}`));
  page.on('dialog', (d) => d.accept());
  await page.addInitScript(() => { try { localStorage.setItem('offdays.dwizard', 'done'); localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
  await page.goto(`${base}/app/index.html`, { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => localStorage.setItem('offdays.token', t), token);
  await page.goto(`${base}/app/${pageName}`, { waitUntil: 'networkidle' });
  return page;
};

// ---------------------------------------------------------------- the coach
const coach = await open(joel.code, 'coach.html');
if (await coach.locator('#wizard-skip').isVisible().catch(() => false)) { await coach.click('#wizard-skip'); await coach.waitForTimeout(800); }
await coach.click('#tabbar [data-tab="today"]');
if (!(await coach.locator('#film-card.open').count())) await coach.click('#film-card > h2');
await coach.click('#film-card details > summary');

await coach.fill('#clip-url', 'https://www.instagram.com/reel/Cabc123_-x/?igsh=abc');
check(await coach.locator('#clip-ig-note').isVisible(), 'pasting an Instagram link shows what it cannot do');
check(!(await coach.locator('#clip-times').isVisible()), 'and hides start and end');
await coach.screenshot({ path: `${out}/1-instagram-form.png` });
await coach.fill('#clip-title', 'Reading the slide');
await coach.fill('#clip-focus', 'Watch the crease defender');
await coach.click('#clip-save');
await coach.waitForFunction(() => /Added/.test(document.getElementById('clip-status').textContent), null, { timeout: 15000 });
let list = (await coach.locator('#clip-list').innerText()).replace(/\s+/g, ' ');
check(/Reading the slide .*ages 13\+ .*Instagram/.test(list), 'the Instagram clip is listed as ages 13+', list.slice(0, 120));

await coach.setInputFiles('#clip-file', webm);
check(await coach.locator('#clip-rights-wrap').isVisible(), 'choosing a file shows the box to tick');
check(await coach.locator('#clip-url').isDisabled(), 'and the link field steps aside');
await coach.fill('#clip-title', 'Our ride against a zone');
await coach.fill('#clip-focus', 'Watch the middie');
await coach.click('#clip-save');
await coach.waitForFunction(() => /Tick the box/.test(document.getElementById('clip-status').textContent), null, { timeout: 15000 });
check(true, 'without the tick it is not uploaded');
await coach.check('#clip-rights');
await coach.screenshot({ path: `${out}/2-upload-form.png` });
await coach.click('#clip-save');
await coach.waitForFunction(() => /Uploaded/.test(document.getElementById('clip-status').textContent), null, { timeout: 30000 });
list = (await coach.locator('#clip-list').innerText()).replace(/\s+/g, ' ');
check(/Our ride against a zone .*12s .*your video/.test(list), 'the uploaded clip is listed with the length the browser read (12s)', list.slice(0, 160));
const playHref = await coach.locator('#clip-list a:has-text("Play")').first().getAttribute('href');
const played = await fetch(base + playHref);
check(played.status === 200 && /video\/webm/.test(played.headers.get('content-type')), 'the coach can play it back');
check(/own videos use/.test(await coach.locator('#clip-own-usage').innerText()), 'the program sees how much space its videos use');
await coach.screenshot({ path: `${out}/3-coach-list.png` });

// ---------------------------------------------------------------- the teenager
const phone = devices['iPhone 13'];
const t = await open(teen.token, 'capture.html', { ...phone, defaultBrowserType: undefined });
await t.waitForSelector('#film-list [data-clip]', { timeout: 20000 });
const teenList = (await t.locator('#film-list').innerText()).replace(/\s+/g, ' ');
check(/Reading the slide/.test(teenList) && /From Instagram/.test(teenList), 'a 15 year old is offered the Instagram clip', teenList.slice(0, 140));
check(/Our ride against a zone/.test(teenList) && /from your coach/.test(teenList), 'and the coach\'s own video');

await t.locator('#film-list [data-clip]', { hasText: 'Our ride' }).click();
await t.waitForSelector('#film-frame video', { timeout: 15000 });
await t.evaluate(() => document.querySelector('#film-frame video').play());
await t.waitForFunction(() => document.querySelector('#film-frame video').currentTime > 2, null, { timeout: 15000 });
check(true, 'the uploaded video plays in the app');
await t.screenshot({ path: `${out}/4-athlete-own-video.png` });
await t.waitForFunction(() => /Watched, start to finish/.test(document.getElementById('film-state').textContent), null, { timeout: 40000 });
check(true, 'watching it to the end is counted as watched');
await t.click('#film-done');
await t.waitForSelector('#film-again [data-again]', { timeout: 15000 });

await t.locator('#film-list [data-clip]', { hasText: 'Reading the slide' }).click();
await t.waitForSelector('#film-frame iframe', { timeout: 15000 });
const src = await t.locator('#film-frame iframe').getAttribute('src');
check(src === 'https://www.instagram.com/reel/Cabc123_-x/embed/', 'the Instagram clip opens in Instagram\'s own player', src);
check(await t.locator('#film-untracked').isVisible(), 'the athlete is told the coach sees it was opened, not how much was watched');
check(!(await t.locator('.film-bar').isVisible()), 'and there is no progress bar pretending otherwise');
check((await t.locator('#film-frame video').count()) === 0, 'the earlier video is gone, not playing underneath');
await t.screenshot({ path: `${out}/5-athlete-instagram.png` });
await t.click('#film-done');

// ---------------------------------------------------------------- the eleven year old
const k = await open(kid.token, 'capture.html', { ...phone, defaultBrowserType: undefined });
await k.waitForSelector('#film-list [data-clip]', { timeout: 20000 });
const kidList = (await k.locator('#film-list').innerText()).replace(/\s+/g, ' ');
check(/Our ride against a zone/.test(kidList), 'an 11 year old is offered the coach\'s own video');
check(!/Reading the slide|Instagram/.test(kidList), 'but not the Instagram clip', kidList.slice(0, 120));

// ---------------------------------------------------------------- what the coach then sees
const cov = (await j('/api/coach/film/coverage', joel.code)).json.clips;
const ig = cov.find((c) => c.title === 'Reading the slide'), own = cov.find((c) => c.title === 'Our ride against a zone');
check(ig.tracked === false && ig.watched_count === 0 && ig.started.length === 1, 'Instagram clip: one athlete opened it, nobody "watched"');
check(own.watched_count === 1, 'own video: one athlete watched it');
await coach.reload({ waitUntil: 'networkidle' });
await coach.click('#tabbar [data-tab="today"]');
const covText = (await coach.locator('#iq-coverage').innerText().catch(() => '')).replace(/\s+/g, ' ');
check(/1\/2 opened/.test(covText) && /Opened/.test(covText), 'the coach screen says opened, not watched, for the Instagram clip', covText.slice(0, 200));

check(errs.length === 0, 'no page errors', errs.join(' | '));
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
