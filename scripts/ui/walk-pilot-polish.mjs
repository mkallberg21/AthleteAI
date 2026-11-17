import { chromium, devices } from 'playwright';
const [base, out] = process.argv.slice(2);
const j = async (path, token, body, method) => (await fetch(base + path, { method: method || (body ? 'POST' : 'GET'), headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: body ? JSON.stringify(body) : undefined })).json().catch(() => ({}));
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const b = await chromium.launch();

// a director signs up in the browser (so the sign-in link box is on screen), then the coach and the other tabs
const dp = await (await b.newContext({ ...devices['iPhone 13'] })).newPage();
const refused = [];
dp.on('response', (r) => { if (r.status() >= 400 && !/family\/board/.test(r.url())) refused.push(`${r.status()} ${new URL(r.url()).pathname}`); });
await dp.goto(base + '/app/index.html', { waitUntil: 'networkidle' });
await dp.locator('.role-btn', { hasText: /director/i }).first().click();
await dp.fill('#org-name', 'Polish FC'); await dp.fill('#org-director', 'Matt Kallberg'); await dp.check('#org-terms'); await dp.click('#create-org');
await dp.waitForURL(/coach\.html/); await dp.waitForSelector('#code-link', { state: 'visible' });
const val = await dp.inputValue('#code-link');
check(/^https?:\/\/[^/]+\/app\/index\.html\?code=[A-Z0-9]+$/.test(val), `the sign-in link is a whole address in a box (${val.replace(/code=.*/, 'code=[hidden]')})`);
const box = await dp.locator('#code-link').boundingBox();
const vw = dp.viewportSize().width;
check(box && box.x >= 0 && box.x + box.width <= vw, `the box fits the phone (${Math.round(box.x)}..${Math.round(box.x + box.width)} of ${vw})`);
check(await dp.locator('#code-link').evaluate((e) => e.readOnly), 'it is read only');
await dp.screenshot({ path: `${out}/polish-1-link.png` });
const D = await dp.evaluate(() => localStorage.getItem('offdays.token'));
const team = (await j('/api/teams', D, { name: '2031 Red' })).id;
await j('/api/coach/roster/import', D, { content: 'First Name,Last Name,Birth Year,Parent Email\nSam,Hill,2013,\nAva,Moss,2013,moss@example.com\n', team_id: team });
const coach = await j('/api/coach/staff', D, { display_name: 'Coach Sam', email: 'coach.sam@example.com', team_ids: [team] });

// Settings no longer shows the filter; Teams still does
await dp.locator('#wizard-skip').click({ timeout: 2000 }).catch(() => {});
await dp.waitForTimeout(800);
await dp.click('#tabbar [data-tab="settings"]'); await dp.waitForTimeout(700);
check(!(await dp.locator('#filter-card').isVisible()), 'Settings does not show the Showing / Window filter');
await dp.screenshot({ path: `${out}/polish-2-settings.png` });
for (const t of ['today', 'families', 'teams']) { await dp.click(`#tabbar [data-tab="${t}"]`); await dp.waitForTimeout(500); check(await dp.locator('#filter-card').isVisible(), `${t} still shows the filter`); }

// a player with no parent name: the email stands alone, no bare word "Parent" twice
await dp.click('#tabbar [data-tab="home"]'); await dp.waitForTimeout(700);
await dp.locator('#home-body .home-row').first().click(); await dp.waitForTimeout(1200);
await dp.locator('#home-body [data-player]').first().click().catch(async () => { await dp.locator('#home-body button').nth(1).click(); }); await dp.waitForTimeout(1500);
const box2 = (await dp.locator('#home-body').innerText());
await dp.screenshot({ path: `${out}/polish-3-player.png` });
check(!/Parent\s*\n\s*Parent/.test(box2), 'the word Parent is not repeated');

// a coach is not refused anything
const cp = await (await b.newContext({ ...devices['iPhone 13'] })).newPage();
const crefused = [];
cp.on('response', (r) => { if (r.status() >= 400 && !/family\/board/.test(r.url())) crefused.push(`${r.status()} ${new URL(r.url()).pathname}`); });
await cp.goto(`${base}/app/index.html?code=${coach.token || coach.code}`, { waitUntil: 'networkidle' });
await cp.waitForTimeout(2500);
await cp.locator('#wizard-skip').click({ timeout: 1500 }).catch(() => {});
for (const t of ['today', 'families', 'teams', 'settings', 'home']) { await cp.click(`#tabbar [data-tab="${t}"]`).catch(() => {}); await cp.waitForTimeout(700); }
check(crefused.length === 0, `the coach's page is refused nothing (${crefused.join(' | ') || 'none'})`);
check(refused.length === 0, `the director's page is refused nothing (${refused.join(' | ') || 'none'})`);
await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
