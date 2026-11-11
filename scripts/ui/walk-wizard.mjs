// A brand-new director's first visit: the walkthrough, one step at a time.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const made = await (await fetch(`${base}/api/orgs`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: 'Mad Dog Lacrosse', sport: 'lacrosse', accept_terms: true, director_name: 'Joel White' }) })).json();
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
page.on('pageerror', (e) => console.log('PAGEERROR', e.message));
const state = async () => ({
  count: await page.locator('#wizard-count').textContent(),
  title: await page.locator('#wizard-title').textContent(),
  next: await page.locator('#wizard-next').textContent(),
  nextDisabled: await page.locator('#wizard-next').isDisabled(),
  otherCardsVisible: await page.evaluate(() => [...document.querySelectorAll('.wrap > .card:not(#wizard)')].filter((c) => getComputedStyle(c).display !== 'none').map((c) => c.id)),
});
await page.goto(`${base}/app/index.html?code=${made.director.token}`, { waitUntil: 'networkidle' });
await page.waitForSelector('#wizard:not(.hidden)', { timeout: 15000 });
await page.waitForTimeout(800);
console.log('0', await state());
await page.screenshot({ path: `${out}/0-contact.png` });
// Step 0 contact: Next locked until both saved; one field alone is refused
await page.fill('#contact-email', 'joel@example.com'); await page.click('#contact-save'); await page.waitForTimeout(400);
console.log('0b email only -> err:', (await page.locator('#contact-err').textContent()).slice(0, 40), '| next disabled:', (await state()).nextDisabled);
await page.fill('#contact-phone', '615 555 0100'); await page.click('#contact-save');
await page.waitForFunction(() => !document.getElementById('wizard-next').disabled, null, { timeout: 8000 });
console.log('0c both saved -> next:', (await state()).next);
await page.click('#wizard-next'); await page.waitForTimeout(800);
console.log('1', await state());
await page.screenshot({ path: `${out}/1-badge.png` });

// Step 1 badge: optional -> Skip for now
await page.click('#wizard-next'); await page.waitForTimeout(800);
console.log('2', await state());
await page.screenshot({ path: `${out}/2-season.png` });
// Step 2 season: Next locked until both dates
await page.fill('#season-starts', '2027-02-01'); await page.dispatchEvent('#season-starts', 'change'); await page.waitForTimeout(600);
console.log('2b after start only:', (await state()).nextDisabled);
await page.fill('#season-ends', '2027-06-30'); await page.dispatchEvent('#season-ends', 'change'); await page.waitForTimeout(900);
console.log('2c after both:', (await state()).nextDisabled, (await state()).next);
await page.click('#wizard-next'); await page.waitForTimeout(800);

// Step 3 teams
console.log('3', await state());
await page.screenshot({ path: `${out}/3-teams.png` });
await page.fill('#new-team', '2031 Red'); await page.waitForTimeout(600);
await page.fill('#new-team-coach', 'Sam Hill'); await page.fill('#new-team-coach-email', 'sam@example.com');
await page.click('#add-team');
await page.waitForFunction(() => !document.getElementById('wizard-next').disabled, null, { timeout: 10000 });
console.log('3b after team:', (await state()).next);
await page.click('#wizard-next'); await page.waitForTimeout(800);

// Step 4 roster
console.log('4', await state());
await page.screenshot({ path: `${out}/4-roster.png` });
const fc = page.waitForEvent('filechooser');
await page.click('#dropzone');
await (await fc).setFiles({ name: 'roster.csv', mimeType: 'text/csv',
  buffer: Buffer.from('First Name,Last Name,Birth Year,Parent Name,Parent Email,Parent Phone\nMason,Reed,2013,Dana Reed,dana@example.com,615 555 0100\nOwen,Hale,2013,Pat Hale,pat@example.com,615 555 0101\n') });
await page.waitForSelector('#preview:not(.hidden)', { timeout: 10000 });
await page.click('#confirm-import');
await page.waitForFunction(() => !document.getElementById('wizard-next').disabled, null, { timeout: 15000 });
console.log('4b after import:', (await state()).next);
await page.click('#wizard-next'); await page.waitForTimeout(800);

// Step 5 send
console.log('5', await state());
await page.screenshot({ path: `${out}/5-send.png` });
console.log('send-yourself rows:', await page.locator('#send-yourself-list > *').count());
await page.click('#wizard-next'); await page.waitForTimeout(1200);
console.log('after finish: wizard hidden =', await page.evaluate(() => document.getElementById('wizard').classList.contains('hidden')),
  '| cards back:', (await state()).otherCardsVisible.slice(0, 6));
await page.screenshot({ path: `${out}/6-dashboard.png` });
// Reload: the walkthrough does not come back.
await page.reload({ waitUntil: 'networkidle' }); await page.waitForTimeout(2500);
console.log('after reload: wizard hidden =', await page.evaluate(() => document.getElementById('wizard').classList.contains('hidden')));
await browser.close();
