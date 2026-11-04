// The family path through the landing page, end to end, on a phone:
//   director imports a roster with a parent email -> parent opens the
//   invite link (Parent panel opens, code filled) -> registers -> says yes
//   -> gets the kid's link -> kid taps it (Athlete panel, auto sign-in)
//   -> lands on drills. Prints each hop; screenshots to --out.
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const J = { 'Content-Type': 'application/json' };
const made = await (await fetch(`${base}/api/orgs`, { method: 'POST', headers: J,
  body: JSON.stringify({ name: 'Mad Dog Lacrosse', sport: 'lacrosse', director_name: 'Joel White' }) })).json();
const H = { Authorization: `Bearer ${made.director.token}`, ...J };
const team = await (await fetch(`${base}/api/teams`, { method: 'POST', headers: H, body: JSON.stringify({ name: '2031 Blue' }) })).json();
const imp = await (await fetch(`${base}/api/coach/roster/import`, { method: 'POST', headers: H,
  body: JSON.stringify({ content: 'First Name,Last Name,Birth Year,Parent Name,Parent Email\nMason,Reed,2013,Dana Reed,dana@example.com', team_id: team.id }) })).json();
const invite = imp.guardian_invites[0];
// Links are minted for the public host; point them at the server under test.
const local = (u) => u.replace(/^https?:\/\/[^/]+/, base);
console.log('invite link:', invite.link);

const browser = await chromium.launch();
const ctx = await browser.newContext(devices['iPhone 13']);
const page = await ctx.newPage();
page.on('pageerror', (e) => console.log('PAGEERROR', e.message));

// Parent taps the invite link
await page.goto(local(invite.link), { waitUntil: 'networkidle' });
await page.waitForTimeout(600);
console.log('parent panel open:', !(await page.locator('#panel-parent').evaluate((el) => el.classList.contains('hidden'))),
  '| invite prefilled:', await page.inputValue('#invite'));
await page.screenshot({ path: `${out}/1-parent-lands.png`, fullPage: true });
await page.fill('#pname', 'Dana Reed');
// Name only: the page refuses before the server does.
await page.click('#redeem');
await page.waitForTimeout(300);
console.log('without contact details:', (await page.locator('#perr').textContent()).trim());
await page.fill('#pemail', 'dana@example.com');
await page.fill('#pphone', '615 555 0100');
await page.click('#redeem');
await page.waitForURL(/parent\.html/);
await page.waitForTimeout(2500);
await page.screenshot({ path: `${out}/2-parent-portal.png`, fullPage: false });

// Say yes + get the kid's link, through the API with the parent's token
// (the portal's switches are covered by walk-director / tests).
const ptoken = await page.evaluate(() => localStorage.getItem('offdays.token'));
const PH = { Authorization: `Bearer ${ptoken}`, ...J };
const me = await (await fetch(`${base}/api/guardians/me`, { headers: PH })).json();
const kid = (me.athletes || me.children || me.links || [])[0];
console.log('parent sees athlete:', kid && (kid.display_name || kid.name));
const aid = kid.athlete_id || kid.id;
const c = await fetch(`${base}/api/guardians/consent`, { method: 'POST', headers: PH,
  body: JSON.stringify({ athlete_id: aid, scope: 'participation', granted: true }) });
console.log('consent', c.status);
const l = await (await fetch(`${base}/api/guardians/athlete-link/${aid}`, { method: 'POST', headers: PH })).json();
console.log('kid link:', l.link || JSON.stringify(l).slice(0, 120));

// Kid taps it on their own phone
const kidCtx = await browser.newContext(devices['iPhone 13']);
const kp = await kidCtx.newPage();
kp.on('pageerror', (e) => console.log('KID PAGEERROR', e.message));
await kp.goto(local(l.link), { waitUntil: 'networkidle' });
await kp.waitForURL(/capture\.html/, { timeout: 15000 });
await kp.waitForTimeout(2500);
console.log('kid landed on:', kp.url().split('/').pop());
await kp.screenshot({ path: `${out}/3-kid-home.png`, fullPage: false });
await browser.close();
