// The dashboard's number strip (Athletes / Participation / Sessions / Total XP)
// must read as one block on a phone: no lone tile on a second line, and a
// gap before the card under it. Exits 1 if not.
//   node scripts/ui/walk-stat-strip.mjs <base> <outdir>
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const made = await (await fetch(`${base}/api/orgs`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: 'Stat Strip Check', sport: 'lacrosse', director_name: 'Pat Lee' }) })).json();
const browser = await chromium.launch();
let bad = 0;
for (const width of [360, 390, 1280]) {
  const ctx = await browser.newContext({ viewport: { width, height: 800 }, deviceScaleFactor: 2, isMobile: width < 900, hasTouch: width < 900 });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => { console.log('PAGEERROR', e.message); bad++; });
  await page.goto(`${base}/app/index.html?code=${made.director.token}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);
  await page.locator('#wizard-skip').click({ timeout: 1500 }).catch(() => {});
  await page.waitForSelector('#summary .stat', { timeout: 8000 });
  const r = await page.evaluate(() => {
    const s = document.getElementById('summary');
    const tiles = [...s.querySelectorAll('.stat')].map((t) => t.getBoundingClientRect());
    const rows = [...new Set(tiles.map((b) => Math.round(b.top)))].map((top) => tiles.filter((b) => Math.round(b.top) === top).length);
    let next = s.nextElementSibling;
    while (next && !next.getClientRects().length) next = next.nextElementSibling;
    const gap = next ? Math.round(next.getBoundingClientRect().top - s.getBoundingClientRect().bottom) : null;
    return { rows, gap };
  });
  console.log(`${width}px tiles per row: ${r.rows.join(' + ')} | gap to next card: ${r.gap}px`);
  if (r.rows.length > 1 && r.rows[r.rows.length - 1] < r.rows[0]) { console.log(`FAIL ${width}px: a tile sits alone on the last line`); bad++; }
  if (r.gap !== null && r.gap < 12) { console.log(`FAIL ${width}px: the strip touches the card below it`); bad++; }
  await page.locator('#summary').screenshot({ path: `${out}/strip-${width}.png` });
  await page.screenshot({ path: `${out}/top-${width}.png` });
  await ctx.close();
}
await browser.close();
console.log(bad ? `FAILED ${bad}` : 'OK');
process.exit(bad ? 1 : 0);
