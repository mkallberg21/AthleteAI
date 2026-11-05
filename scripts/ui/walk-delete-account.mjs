// A parent deletes their own account from inside the app, then cannot get back in.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8000';
const out = process.argv[3] || path.join(process.env.LOCALAPPDATA || os.tmpdir(), 'Temp', 'delete-account');
fs.mkdirSync(out, { recursive: true });

// set up a program and a parent through the real API
const j = async (url, body, headers = {}) => (await fetch(base + url, { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(body) })).json();
const org = await j('/api/orgs', { name: 'Delete Me FC', sport: 'lacrosse', director_name: 'Joel' });
const dh = { Authorization: `Bearer ${org.director.token}` };
const team = await j('/api/teams', { name: '2031 Red' }, dh);
const imp = await j('/api/coach/roster/import', { content: 'First Name,Last Name,Birth Year,Parent Email,Parent Phone\nMason,Reed,2013,dana@example.com,615-555-0100\n', team_id: team.id }, dh);
const reg = await j('/api/guardians/redeem', { code: imp.guardian_invites[0].code, display_name: 'Dana Reed', email: 'dana@example.com', relationship: 'parent', phone: '615-555-0100' });
console.log('parent signed up; athlete:', reg.athlete_name);

const browser = await chromium.launch();
for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const page = await (await browser.newContext(opts)).newPage();
  const dialogs = [];
  page.on('dialog', async (d) => { dialogs.push(d.message().split('\n')[0]); await d.accept(d.type() === 'prompt' ? 'DELETE' : undefined); });
  // each pass needs its own parent: the first deletes theirs
  const inv = tag === 'desktop' ? null : (await j('/api/coach/roster/import', { content: 'First Name,Last Name,Birth Year,Parent Email,Parent Phone\nOwen,Hale,2014,pat@example.com,615-555-0101\n', team_id: team.id }, dh));
  const token = tag === 'desktop' ? reg.token : (await j('/api/guardians/redeem', { code: inv.guardian_invites[0].code, display_name: 'Pat Hale', email: 'pat@example.com', relationship: 'parent', phone: '615-555-0101' })).token;

  await page.goto(`${base}/app/parent.html`);
  await page.evaluate((t) => { for (const k of ['offdays.token', 'token']) localStorage.setItem(k, t); }, token);
  await page.goto(`${base}/app/parent.html`);
  await page.waitForTimeout(2000);
  await page.locator('#pwizard-skip').click({ timeout: 3000 }).catch(() => {});
  await page.waitForTimeout(600);
  await page.locator('#account-card').scrollIntoViewIfNeeded();
  console.log(tag, 'card visible:', await page.locator('#account-card').isVisible(), '| button:', (await page.locator('#account-delete').textContent()).trim());
  await page.screenshot({ path: `${out}/${tag}-1-card.png` });

  await page.click('#account-delete');
  await page.waitForTimeout(2500);
  console.log(tag, 'dialogs:', dialogs.map((d) => d.slice(0, 70)).join(' || '));
  console.log(tag, 'after deleting, url:', page.url().replace(base, ''));
  const me = await fetch(`${base}/api/guardians/me`, { headers: { Authorization: `Bearer ${token}` } });
  console.log(tag, 'old sign-in now:', me.status);
  await page.close();
}
const kids = await (await fetch(`${base}/api/coach/families`, { headers: dh })).json();
console.log('program still has:', (kids.athletes || []).map((a) => `${a.display_name} [${a.stage}]`).join(', '));
await browser.close();
