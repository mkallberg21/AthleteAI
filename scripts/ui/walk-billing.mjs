// The cost card as the director sees it: before dates, after dates with a
// roster. Prints the card text and screenshots it.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const made = await (await fetch(`${base}/api/orgs`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: 'Mad Dog Lacrosse', sport: 'lacrosse', director_name: 'Joel White' }) })).json();
const H = { Authorization: `Bearer ${made.director.token}`, 'Content-Type': 'application/json' };
const team = await (await fetch(`${base}/api/teams`, { method: 'POST', headers: H, body: JSON.stringify({ name: '2031 Blue' }) })).json();
const rows = Array.from({ length: 100 }, (_, i) => `Athlete,${i + 1},2013`).join('\n');
const imp = await fetch(`${base}/api/coach/roster/import`, { method: 'POST', headers: H,
  body: JSON.stringify({ content: `First Name,Last Name,Birth Year\n${rows}`, team_id: team.id, invite_guardians: false }) });
console.log('import', imp.status, imp.status !== 201 ? (await imp.text()).slice(0, 300) : '');
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 860 } })).newPage();
await page.goto(`${base}/app/index.html?code=${made.director.token}`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2000);
const card = page.locator('#billing-card');
console.log('BEFORE DATES:', (await card.innerText()).replace(/\s*\n\s*/g, ' | '));
await card.screenshot({ path: `${out}/1-no-dates.png` });
const r = await fetch(`${base}/api/org/season`, { method: 'PUT', headers: H,
  body: JSON.stringify({ starts_on: '2027-02-01', ends_on: '2027-06-30' }) });
console.log('season', r.status);
await page.reload({ waitUntil: 'networkidle' }); await page.waitForTimeout(2000);
console.log('AFTER DATES:', (await card.innerText()).replace(/\s*\n\s*/g, ' | '));
await card.screenshot({ path: `${out}/2-dates.png` });
await browser.close();
