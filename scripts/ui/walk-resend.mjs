// Families: "Resend invite to parent" on a family that has not moved. With no
// outbound email, nothing is sent: the director gets Open in my email + Copy link.
import { chromium } from 'playwright';
const base = process.argv[2] || 'http://127.0.0.1:8000';
const b = await chromium.launch();
const p = await (await b.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
await p.goto(`${base}/`);
await p.locator('.role-btn', { hasText: /director/i }).first().click();
await p.fill('#org-name', 'Resend FC'); await p.fill('#org-director', 'Joel'); await p.click('#create-org');
await p.waitForURL(/coach\.html/); await p.waitForSelector('#wizard-skip'); await p.click('#wizard-skip');
await p.fill('#new-team', '2031 Red'); await p.waitForTimeout(400);
await p.fill('#new-team-coach', 'Sam Hill'); await p.fill('#new-team-coach-email', 'sam@example.com');
await p.click('#add-team'); await p.waitForTimeout(1000);
await p.fill('#ap-first', 'Mason'); await p.fill('#ap-last', 'Reed'); await p.fill('#ap-year', '2013');
await p.fill('#ap-email', 'reed.mom@example.com'); await p.fill('#ap-phone', '615-555-0140');
await p.click('#ap-add'); await p.waitForSelector('#ap-ok:not(:empty)'); await p.waitForTimeout(1200);
const btn = p.locator('button[data-nudge]').first();
console.log('button says:', (await btn.textContent()).trim());
await btn.click(); await p.waitForTimeout(1500);
const row = p.locator('#families');
console.log('after click, links:', (await row.locator('a.btn-link').allTextContents()).join(' | '), '| buttons:', (await row.locator('button').allTextContents()).map((x) => x.trim()).join(' | '));
console.log('mailto goes to:', decodeURIComponent((await row.locator('a.btn-link').first().getAttribute('href')).slice(7, 40)));
await row.scrollIntoViewIfNeeded();
await p.screenshot({ path: process.env.LOCALAPPDATA + '/Temp/resend.png' });
await b.close();
