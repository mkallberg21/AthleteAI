// The director's kickoff, driven through the real pages at tablet size:
// sign up -> teams -> add a coach -> import roster with parent emails ->
// Families card. Screenshots each step.
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ ...devices['iPad (gen 7)'] });
const page = await ctx.newPage();
page.on('pageerror', (e) => console.log('PAGEERROR', e.message));
page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE', m.text().slice(0, 160)); });

// 1. Sign up a program from the public page.
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await page.click('.role-btn[data-role="director"]');
await page.fill('#org-name', 'Mad Dog Lacrosse');
await page.selectOption('#org-sport', 'lacrosse');
await page.fill('#org-director', 'Joel White');
await page.click('#create-org');
await page.waitForSelector('#org-token:not(.hidden)');
const code = (await page.locator('#org-token code').textContent()).trim();
console.log('1 program created, director code shown once:', code.length, 'chars');
await page.screenshot({ path: `${out}/1-signup.png`, fullPage: false });

// 2. Sign in as the director.
await page.goto(`${base}/app/index.html?code=${code}`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);
await page.locator('#wizard-skip').click({ timeout: 1500 }).catch(() => {}); await page.waitForTimeout(400);
console.log('2 landed on:', page.url().split('/').pop());
const next = await page.locator('#setup-card').first().innerText().catch(() => '');
console.log('   checklist head:', next.split('\n').slice(0, 4).join(' | '));

// 3. Create two teams.
for (const name of ['2031 Red', '2031 Blue']) {
  await page.fill('#new-team', name);
  await page.click('#add-team');
  await page.waitForTimeout(800);
}
await page.reload({ waitUntil: 'networkidle' }); await page.waitForTimeout(2000);
console.log('3 teams:', await page.locator('#import-team option').allTextContents());

// 4. Add a coach with email on Red.
await page.fill('#new-coach-name', 'Sam Hill');
await page.fill('#new-coach-email', 'sam@example.com');
await page.selectOption('#new-coach-teams', { label: '2031 Red' });
await page.click('#new-coach-add');
await page.waitForSelector('#new-coach-out:not(.hidden)');
console.log('4 coach:', (await page.locator('#new-coach-out').innerText()).trim());
await page.locator('#staff-card').screenshot({ path: `${out}/4-coach-added.png` });

// 5. Import a roster with parent emails into Red.
const csv = 'Name,Birth Year,Jersey,Parent Email\nMason Reed,2013,7,mason.parent@example.com\nEli Tanner,2013,12,eli.parent@example.com\nOwen Price,2013,3,\n';
await page.selectOption('#import-team', { label: '2031 Red' });
await page.setInputFiles('#file-input', { name: 'roster.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
await page.waitForSelector('#preview:not(.hidden)');
await page.click('#confirm-import');
await page.waitForTimeout(3000);
console.log('5 import done; slips card visible:', await page.locator('#slips-card').isVisible());
const sy = page.locator('#send-yourself');
console.log('   send-yourself visible:', await sy.isVisible(), '| rows:', await page.locator('#send-yourself-list > div').count());
const href = await page.locator('#send-yourself-list a').first().getAttribute('href');
const u = new URL(href);
console.log('   mailto to:', decodeURIComponent(u.pathname), '| subject:', decodeURIComponent(u.searchParams.get('subject')));
console.log('   body head:', decodeURIComponent(u.searchParams.get('body')).split('\n')[0].slice(0, 90));
console.log('   body has link:', /app[.]0ffdays[.]com[/]app[/]index[.]html[?]invite=[A-Z0-9-]+/.test(decodeURIComponent(u.searchParams.get('body'))));
await page.locator('#slips-card').screenshot({ path: `${out}/5-send-yourself.png` });

// 6. Families card.
await page.reload({ waitUntil: 'networkidle' }); await page.waitForTimeout(2500);
console.log('6 families:', (await page.locator('#families-through').innerText()).trim(), '|',
  (await page.locator('#families-counts').innerText()).replace(/\s*\n\s*/g, ' | '));
await page.locator('#families-card').screenshot({ path: `${out}/6-families.png` });
const steps = await page.locator('#setup-card').first().innerText().catch(() => '');
console.log('   checklist now:', steps.split('\n').filter((l) => l.trim()).slice(0, 8).join(' | '));
await browser.close();
