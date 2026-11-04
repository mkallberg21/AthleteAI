import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';
const out = 'C:/Users/mtkal/AppData/Local/Temp/look';
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
for (const [name, opts] of [['phone', devices['iPhone 13']], ['desktop', { viewport: { width: 1280, height: 900 } }]]) {
  const ctx = await browser.newContext(opts);
  const page = await ctx.newPage();
  const res = await page.goto('https://app.0ffdays.com/app/index.html', { waitUntil: 'networkidle' });
  const css = await page.evaluate(async () => {
    const links = [...document.querySelectorAll('link[rel=stylesheet]')].map((l) => l.href);
    const out = [];
    for (const h of links) { const r = await fetch(h); out.push([h, r.status, (await r.text()).length]); }
    return out;
  });
  console.log(name, res.status(), 'stylesheets:', JSON.stringify(css));
  await page.screenshot({ path: `${out}/${name}-index.png`, fullPage: true });
  await ctx.close();
}
await browser.close();
