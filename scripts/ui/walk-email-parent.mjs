// Roster: "Email parent" under a player's name makes the invite email to their
// parent, with the player code and sign-up link in the message. Sends nothing.
import { chromium, devices } from 'playwright';

const base = process.argv[2] || 'http://127.0.0.1:8000';
const j = async (url, body, h = {}) => (await fetch(base + url, { method: 'POST', headers: { 'Content-Type': 'application/json', ...h }, body: JSON.stringify(body) })).json();
const org = await j('/api/orgs', { name: 'Email FC', sport: 'lacrosse', director_name: 'Joel' });
const dh = { Authorization: `Bearer ${org.director.token}` };
const team = await j('/api/teams', { name: '2031 Red' }, dh);
await j('/api/coach/roster/import', { content: 'First Name,Last Name,Birth Year,Parent Email,Parent Phone\nMason,Reed,2013,dana@example.com,615-555-0100\n', team_id: team.id, invite_guardians: false }, dh);

const browser = await chromium.launch();
for (const [tag, opts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const page = await (await browser.newContext(opts)).newPage();
  await page.goto(`${base}/app/coach.html`);
  await page.evaluate((t) => localStorage.setItem('offdays.token', t), org.director.token);
  await page.goto(`${base}/app/coach.html`); await page.waitForTimeout(1500);
  await page.locator('#wizard-skip').click({ timeout: 3000 }).catch(() => {}); await page.waitForTimeout(1500);
  await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));  // cards start folded

  const btn = page.locator('#roster button[data-invite]').first();
  console.log(tag, 'button says:', (await btn.textContent()).trim());
  await btn.click(); await page.waitForTimeout(1500);
  const cell = page.locator('#roster tr').first();
  console.log(tag, 'after click:', (await cell.innerText()).split(/\r?\n/).map((x) => x.trim()).filter(Boolean).join(' | ').slice(0, 220));
  const href = decodeURIComponent(await cell.locator('a.tiny').first().getAttribute('href'));
  const to = href.slice(7, href.indexOf('?'));
  const code = (href.match(/invite code ([A-Z0-9-]+)/) || href.match(/invite=([A-Z0-9-]+)/) || [])[1];
  console.log(tag, 'mailto to:', to, '| subject:', (href.match(/subject=([^&]*)/) || [])[1]);
  console.log(tag, 'message contains the code:', !!code, code || '', '| and the sign-up link:', /\?invite=/.test(href));
  await page.locator('#roster').scrollIntoViewIfNeeded();
  await page.screenshot({ path: process.env.LOCALAPPDATA + `/Temp/email-parent-${tag}.png` });
  await page.close();
}
await browser.close();
