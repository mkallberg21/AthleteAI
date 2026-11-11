// Every role's first visit, end to end, on a phone: director creates the
// program (walkthrough skipped, it has its own walk), adds a team + coach,
// imports a roster with a parent; then the coach's, the parent's and the
// kid's first screens, one at a time.
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const J = { 'Content-Type': 'application/json' };
const local = (u) => /^https?:/.test(u) ? u.replace(/^https?:\/\/[^/]+/, base) : base + u;

const made = await (await fetch(`${base}/api/orgs`, { method: 'POST', headers: J,
  body: JSON.stringify({ name: 'Mad Dog Lacrosse', sport: 'lacrosse', accept_terms: true, director_name: 'Joel White' }) })).json();
const H = { Authorization: `Bearer ${made.director.token}`, ...J };
const team = await (await fetch(`${base}/api/teams`, { method: 'POST', headers: H,
  body: JSON.stringify({ name: '2031 Red', coach_name: 'Sam Hill', coach_email: 'sam@example.com' }) })).json();
const imp = await (await fetch(`${base}/api/coach/roster/import`, { method: 'POST', headers: H,
  body: JSON.stringify({ content: 'First Name,Last Name,Birth Year,Parent Name,Parent Email\nMason,Reed,2013,Dana Reed,dana@example.com', team_id: team.id }) })).json();
const invite = imp.guardian_invites[0];
const browser = await chromium.launch();
const ctx = async () => { const c = await browser.newContext(devices['iPhone 13']); const p = await c.newPage(); p.on('pageerror', (e) => console.log('PAGEERROR', e.message)); return [c, p]; };
const wiz = async (p, id) => ({
  on: await p.locator(`#${id}`).isVisible(),
  title: await p.locator(`#${id}-title`).textContent().catch(() => ''),
  others: await p.evaluate(() => [...document.querySelectorAll('.wrap > *')].filter((e) => getComputedStyle(e).display !== 'none' && !/wizard/.test(e.id)).map((e) => e.id || e.tagName)),
});

// ---- COACH
console.log('\n== coach');
{
  const [c, p] = await ctx();
  await p.goto(`${base}/app/index.html?code=${team.coach.code}`, { waitUntil: 'networkidle' });
  await p.waitForSelector('#wizard:not(.hidden)', { timeout: 15000 });
  await p.waitForTimeout(600);
  console.log('1', await wiz(p, 'wizard'));
  await p.screenshot({ path: `${out}/coach-1.png` });
  await p.fill('#contact-email', 'sam@example.com'); await p.fill('#contact-phone', '615 555 0101'); await p.click('#contact-save');
  await p.waitForFunction(() => !document.getElementById('wizard-next').disabled, null, { timeout: 8000 });
  for (const n of [2, 3, 4]) {
    await p.click('#wizard-next'); await p.waitForTimeout(700);
    console.log(n, (await wiz(p, 'wizard')).title, '| next:', await p.locator('#wizard-next').textContent());
    await p.screenshot({ path: `${out}/coach-${n}.png` });
  }
  await p.click('#wizard-next'); await p.waitForTimeout(1000);
  console.log('finished: wizard hidden =', !(await p.locator('#wizard').isVisible()), '| sees roster card:', await p.locator('#roster-card').isVisible());
  await c.close();
}

// ---- PARENT
console.log('\n== parent');
let kidLink = '';
{
  const [c, p] = await ctx();
  await p.goto(local(invite.link), { waitUntil: 'networkidle' });
  await p.fill('#pname', 'Dana Reed'); await p.fill('#pemail', 'dana@example.com'); await p.fill('#pphone', '615 555 0100');
  await p.click('#redeem'); await p.waitForURL(/parent\.html/); await p.waitForTimeout(2000);
  console.log('1', await wiz(p, 'pwizard'));
  await p.screenshot({ path: `${out}/parent-1-yes.png` });
  console.log('   next disabled before answering:', await p.locator('#pwizard-next').isDisabled());
  await p.click('[data-pw-yes]'); await p.waitForTimeout(900);
  console.log('   after yes -> next disabled:', await p.locator('#pwizard-next').isDisabled());
  await p.click('#pwizard-next'); await p.waitForTimeout(700);
  console.log('2', (await wiz(p, 'pwizard')).title, '| next disabled:', await p.locator('#pwizard-next').isDisabled());
  await p.click('[data-pw-link]'); await p.waitForSelector('[data-link-field]'); await p.waitForTimeout(400);
  kidLink = await p.inputValue('[data-link-field]');
  console.log('   link ready, buttons:', await p.locator('#pwizard-body button, #pwizard-body a').allTextContents());
  await p.screenshot({ path: `${out}/parent-2-link.png` });
  await p.click('#pwizard-next'); await p.waitForTimeout(600);
  console.log('3', (await wiz(p, 'pwizard')).title, '| next:', await p.locator('#pwizard-next').textContent());
  await p.click('#pwizard-next'); await p.waitForTimeout(1500);
  console.log('finished: wizard hidden =', !(await p.locator('#pwizard').isVisible()), '| athlete card shown:', await p.locator('#athletes .card').count());
  await p.reload({ waitUntil: 'networkidle' }); await p.waitForTimeout(1500);
  console.log('reload: wizard hidden =', !(await p.locator('#pwizard').isVisible()));
  await c.close();
}

// ---- ATHLETE
console.log('\n== athlete');
{
  const [c, p] = await ctx();
  await p.goto(local(kidLink), { waitUntil: 'networkidle' });
  await p.waitForURL(/capture\.html/, { timeout: 15000 }); await p.waitForTimeout(2500);
  console.log('1', await wiz(p, 'awizard'));
  await p.screenshot({ path: `${out}/athlete-1.png` });
  await p.click('#awizard-next'); await p.waitForTimeout(400);
  console.log('2', (await wiz(p, 'awizard')).title);
  await p.screenshot({ path: `${out}/athlete-2.png` });
  await p.click('#awizard-next'); await p.waitForTimeout(400);
  console.log('3', (await wiz(p, 'awizard')).title, '| button:', await p.locator('#awizard-next').textContent());
  await p.click('#awizard-next'); await p.waitForTimeout(600);
  const firstDrill = await p.locator('#drill-list button, #drill-list .drill').first().boundingBox();
  console.log('finished: wizard hidden =', !(await p.locator('#awizard').isVisible()), '| first drill on screen:', !!firstDrill && firstDrill.y < 664);
  await p.screenshot({ path: `${out}/athlete-home.png` });
  await c.close();
}
await browser.close();
