// Walk the athlete link at phone size: link -> home -> drill -> Start -> Finish. Screenshots each step.
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';
const link = process.argv[2];
const out = process.argv[3] || 'C:/Users/mtkal/AppData/Local/Temp/walk';
mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
const ctx = await browser.newContext({ ...devices['iPhone 13'], permissions: ['camera', 'microphone'] });
const page = await ctx.newPage();
page.on('pageerror', (e) => console.log('PAGEERROR', e.message));
page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE', m.text().slice(0, 160)); });
await page.goto(link, { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);
console.log('1 after link:', page.url());
await page.screenshot({ path: `${out}/1-home.png` });
const vh = page.viewportSize().height;
const firstDrill = await page.locator('#drill-list button').first().boundingBox();
console.log('   first drill button y=', firstDrill && Math.round(firstDrill.y), '(viewport', vh + ')');
await page.locator('#drill-list button', { hasText: /wall ball/i }).first().click();
await page.waitForTimeout(3000);
await page.screenshot({ path: `${out}/2-drill.png` });
const ss = page.locator('#startstop');
let box = await ss.boundingBox();
console.log('2 Start:', JSON.stringify(await ss.textContent()), 'disabled=', await ss.isDisabled(), 'box=', box && { y: Math.round(box.y), h: Math.round(box.height), w: Math.round(box.width) }, 'on-screen=', box && box.y + box.height <= vh);
if (!(await ss.isDisabled())) {
  await ss.click();
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${out}/3-recording.png` });
  box = await ss.boundingBox();
  console.log('3 after Start:', JSON.stringify(await ss.textContent()), 'box=', box && { y: Math.round(box.y), h: Math.round(box.height) }, 'on-screen=', box && box.y + box.height <= vh);
  await page.mouse.wheel(0, 2000); await page.waitForTimeout(500);
  box = await ss.boundingBox();
  console.log('   after scrolling down: on-screen=', box && box.y + box.height <= vh);
  await ss.click();
  await page.waitForTimeout(4000);
  await page.screenshot({ path: `${out}/4-finished.png` });
  console.log('4 after Finish: url=', page.url(), 'visible sections=', await page.locator('section:not(.hidden)').evaluateAll((els) => els.map((e) => e.id)));
}
await browser.close();
