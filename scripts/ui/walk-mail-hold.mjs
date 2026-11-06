// The email hold, on the real page. Needs a server with a mail provider set
// (OFFDAYS_SMTP_HOST) so the switch has something to release.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8003';
const out = process.argv[3] || path.join(process.env.LOCALAPPDATA || os.tmpdir(), 'Temp', 'mailhold');
fs.mkdirSync(out, { recursive: true });
const j = async (url, body, h = {}, method = 'POST') => (await fetch(base + url, { method, headers: { 'Content-Type': 'application/json', ...h }, body: JSON.stringify(body) })).json();

const org = await j('/api/orgs', { name: 'Hold FC', sport: 'lacrosse', director_name: 'Joel' });
const dh = { Authorization: `Bearer ${org.director.token}` };
const team = await j('/api/teams', { name: '2031 Red' }, dh);
const csv = (n) => `First Name,Last Name,Birth Year,Parent Email,Parent Phone\n${n},Reed,2013,${n.toLowerCase()}@example.com,615-555-0100\n`;
const outbox = async () => (await (await fetch(base + '/api/coach/outbox', { headers: dh })).json());
const sent = async () => { const o = await outbox(); return (o.recent || []).map((r) => r.to_email); };

const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
page.on('dialog', async (d) => { console.log('confirm asked:', d.message().split('\n')[0]); await d.accept(); });
await page.goto(`${base}/app/coach.html`);
await page.evaluate((t) => localStorage.setItem('offdays.token', t), org.director.token);
await page.goto(`${base}/app/coach.html`); await page.waitForTimeout(1500);
await page.locator('#wizard-skip').click({ timeout: 3000 }).catch(() => {}); await page.waitForTimeout(1500);
await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));  // cards start folded
await page.evaluate(() => document.querySelectorAll('.tab-off').forEach((c) => c.classList.remove('tab-off')));  // all tabs shown

const card = page.locator('#mailhold-card');
await card.scrollIntoViewIfNeeded();
console.log('1. fresh program:', (await page.locator('#mailhold-state').innerText()).replace(/\s+/g, ' '), '| button:', (await page.locator('#mailhold-toggle').textContent()).trim());
await card.screenshot({ path: `${out}/1-held.png` });

// import while held: nobody is emailed
let r = await j('/api/coach/roster/import', { content: csv('Mason'), team_id: team.id }, dh);
console.log('2. imported while held -> emailed:', r.guardian_invites[0].emailed, '| outbox:', JSON.stringify(await sent()));

// release it from the page
await page.click('#mailhold-toggle'); await page.waitForTimeout(1200);
console.log('3. after Start sending:', (await page.locator('#mailhold-state').innerText()).replace(/\s+/g, ' '), '| button:', (await page.locator('#mailhold-toggle').textContent()).trim());
await card.screenshot({ path: `${out}/2-released.png` });

r = await j('/api/coach/roster/import', { content: csv('Owen'), team_id: team.id }, dh);
console.log('4. imported after release -> emailed:', r.guardian_invites[0].emailed, '| outbox:', JSON.stringify(await sent()));

// hold again
await page.click('#mailhold-toggle'); await page.waitForTimeout(1200);
console.log('5. after Hold all email:', (await page.locator('#mailhold-state').innerText()).replace(/\s+/g, ' '));
r = await j('/api/coach/roster/import', { content: csv('Cal'), team_id: team.id }, dh);
console.log('6. imported after re-hold -> emailed:', r.guardian_invites[0].emailed, '| outbox:', JSON.stringify(await sent()));

// a coach does not see the switch
const coach = await j('/api/coach/staff', { display_name: 'Sam', email: 'sam@example.com', team_ids: [team.id] }, dh);
const cp = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
await cp.goto(`${base}/app/coach.html`);
await cp.evaluate((t) => localStorage.setItem('offdays.token', t), coach.code);
await cp.goto(`${base}/app/coach.html`); await cp.waitForTimeout(1500);
console.log('7. a coach sees the switch:', await cp.locator('#mailhold-card').isVisible());
await browser.close();
