// Step 6 of the walkthrough: the roster drop box. Drag a real file onto it,
// browse for one, reject a wrong one, upload, then delete the upload.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8000';
const out = process.argv[3] || path.join(process.env.LOCALAPPDATA || os.tmpdir(), 'Temp', 'dropbox');
fs.mkdirSync(out, { recursive: true });

const csv = path.join(out, 'mad-dogs-2031.csv');
fs.writeFileSync(csv, 'First Name,Last Name,Birth Year,Parent Email,Parent Phone\nAva,Stone,2013,ava.mom@example.com,615-555-0101\nBen,Reyes,2013,ben.dad@example.com,615-555-0102\nCal,Moss,2013,cal.mom@example.com,615-555-0103\n');
const pdf = path.join(out, 'not-a-roster.pdf');
fs.writeFileSync(pdf, '%PDF-1.4 not a roster');

const browser = await chromium.launch();
for (const [tag, ctxOpts] of [['desktop', { viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const ctx = await browser.newContext(ctxOpts);
  const page = await ctx.newPage();
  page.on('dialog', (d) => { console.log(tag, 'confirm:', d.message().replace(/\n+/g, ' / ')); d.accept(); });
  await page.goto(`${base}/`);
  await page.locator('.role-btn', { hasText: /director/i }).first().click();
  await page.fill('#org-name', 'Drop Box FC'); await page.fill('#org-director', 'Joel');
  await page.click('#create-org');
  await page.waitForURL(/coach\.html/);
  await page.waitForSelector('#wizard:not(.hidden)');

  const next = page.locator('#wizard-next');
  const title = async () => (await page.locator('#wizard-title').textContent()).trim();
  // 1 code -> 2 contact -> 3 badge -> 4 season -> 5 teams -> 6 roster
  const unlocked = () => page.waitForFunction(() => !document.getElementById('wizard-next').disabled, null, { timeout: 10000 });
  await next.click();                                                    // 1 code
  await page.fill('#contact-email', 'joel@example.com'); await page.fill('#contact-phone', '615 555 0100');
  await page.click('#contact-save'); await unlocked(); await next.click(); await page.waitForTimeout(500);   // 2 contact
  await next.click(); await page.waitForTimeout(500);                    // 3 badge (optional)
  await page.fill('#season-starts', '2027-02-01'); await page.dispatchEvent('#season-starts', 'change'); await page.waitForTimeout(500);
  await page.fill('#season-ends', '2027-06-30'); await page.dispatchEvent('#season-ends', 'change');
  await unlocked(); await next.click(); await page.waitForTimeout(500);  // 4 season
  await page.fill('#new-team', '2031 Red'); await page.waitForTimeout(500);
  await page.fill('#new-team-coach', 'Sam Hill'); await page.fill('#new-team-coach-email', 'sam@example.com');
  await page.click('#add-team'); await unlocked(); await next.click(); await page.waitForTimeout(600);       // 5 teams
  console.log(tag, 'on:', await title());
  await page.locator('#dropzone').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${out}/${tag}-1-box.png` });

  // a wrong file is refused in words, before anything uploads
  await page.setInputFiles('#file-input', pdf);
  console.log(tag, 'wrong file ->', (await page.locator('#import-err').textContent()).trim());

  // drag and drop a real file onto the box
  const data = await page.evaluateHandle((text) => {
    const dt = new DataTransfer();
    dt.items.add(new File([text], 'mad-dogs-2031.csv', { type: 'text/csv' }));
    return dt;
  }, fs.readFileSync(csv, 'utf8'));
  await page.dispatchEvent('#dropzone', 'dragenter', { dataTransfer: data });
  console.log(tag, 'while dragging, box class:', await page.locator('#dropzone').getAttribute('class'));
  await page.screenshot({ path: `${out}/${tag}-2-dragging.png` });
  await page.dispatchEvent('#dropzone', 'drop', { dataTransfer: data });
  await page.waitForSelector('#confirm-import');
  console.log(tag, 'chosen:', (await page.locator('#chosen-file').textContent()).trim());
  await page.screenshot({ path: `${out}/${tag}-3-preview.png` });

  await page.click('#confirm-import');
  await page.waitForSelector('#uploads:not(.hidden)');
  console.log(tag, 'uploads:', (await page.locator('#uploads-list').innerText()).replace(/\s*\n\s*/g, ' | '));
  await page.locator('#uploads').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${out}/${tag}-4-uploaded.png` });

  await page.click('[data-del-import]');
  await page.waitForSelector('#uploads.hidden', { state: 'attached' });
  console.log(tag, 'after delete, uploads hidden:', await page.locator('#uploads').evaluate((e) => e.classList.contains('hidden')));
  await page.screenshot({ path: `${out}/${tag}-5-deleted.png` });

  // the Browse button opens the chooser
  const [chooser] = await Promise.all([page.waitForEvent('filechooser'), page.click('#browse-btn')]);
  await chooser.setFiles(csv);
  await page.waitForSelector('#confirm-import');
  console.log(tag, 'browse ->', (await page.locator('#chosen-file').textContent()).trim());
  await ctx.close();
}
await browser.close();
