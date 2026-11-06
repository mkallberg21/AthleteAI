// Roster import preview on a 360px phone: before a director presses "Add N
// players", can they read every row's name, and see whether it is new, an
// update or skipped, without scrolling the table sideways? Exits 1 if not.
//   node scripts/ui/walk-import-preview-phone.mjs <base> <outdir>
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const post = async (path, body, token) => (await fetch(`${base}${path}`, { method: 'POST',
  headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  body: JSON.stringify(body) })).json();
const made = await post('/api/orgs', { name: 'Preview Phone Check', sport: 'lacrosse', director_name: 'Pat Lee' });
const tok = made.director.token;
await post('/api/teams', { name: '2031 Red' }, tok);
const csv = 'First Name,Last Name,Jersey,Position,Birth Year,Hand,Parent Email\n'
  + 'Alexandria,Montgomery-Whitfield,22,Midfield,2013,Left,alex.mom@example.com\n'
  + 'Sam,Ortiz,7,Attack,2013,Right,sam.dad@example.com\n'
  + 'Jo,Park,,,2013,,\n'
  + ',,,,,,\n'
  + ',Nameless,9,Defense,2013,Right,nobody@example.com\n';
const browser = await chromium.launch();
let bad = 0;
for (const width of [360, 390, 1280]) {
  const ctx = await browser.newContext({ viewport: { width, height: 800 }, deviceScaleFactor: 2, isMobile: width < 900, hasTouch: width < 900 });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => { console.log('PAGEERROR', e.message); bad++; });
  await page.goto(`${base}/app/index.html?code=${tok}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);
  await page.locator('#wizard-skip').click({ timeout: 1500 }).catch(() => {});
  await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));
  await page.locator('.source-btn', { hasText: /file/i }).first().click().catch(() => {});
  await page.setInputFiles('#file-input', { name: 'roster.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
  await page.waitForSelector('#preview .preview-row', { timeout: 8000 });
  await page.waitForTimeout(300);
  await page.locator('#preview table').scrollIntoViewIfNeeded();
  const r = await page.evaluate((vw) => {
    const table = document.querySelector('#preview table');
    const box = table.parentElement.getBoundingClientRect();
    const right = Math.min(vw, box.right);
    const vis = (el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.left >= box.left - 1 && b.right <= right + 1; };
    const rows = [...document.querySelectorAll('#preview .preview-row')];
    const oneWord = [...document.querySelectorAll('#preview .preview-row td[data-label]')]
      .filter((td) => /^\S+$/.test(td.textContent.trim()));
    const split = oneWord.filter((td) => { const rg = document.createRange(); rg.selectNodeContents(td);
      const tops = new Set([...rg.getClientRects()].filter((q) => q.width > 0).map((q) => Math.round(q.top)));
      return tops.size > 1; }).map((td) => td.textContent.trim());
    return { table: Math.round(table.getBoundingClientRect().width), box: Math.round(box.width), n: rows.length, split,
      names: rows.map((tr) => vis(tr.children[1].querySelector('b'))),
      actions: rows.map((tr) => vis(tr.lastElementChild.querySelector('.pill'))),
      labels: rows.map((tr) => tr.lastElementChild.querySelector('.pill').textContent.trim()) };
  }, width);
  console.log(`${width}px table ${r.table}px in a ${r.box}px box | ${r.n} rows (${r.labels.join(',')}) | names on screen: ${r.names.join(',')} | new/update/skip on screen: ${r.actions.join(',')}`);
  if (r.n < 3) { console.log(`FAIL ${width}px: expected the preview rows, saw ${r.n}`); bad++; }
  if (r.table > r.box + 1) { console.log(`FAIL ${width}px: the table is wider than its box and scrolls sideways`); bad++; }
  if (r.names.some((v) => !v)) { console.log(`FAIL ${width}px: a player's name is off screen`); bad++; }
  if (r.actions.some((v) => !v)) { console.log(`FAIL ${width}px: a row's new/update/skip label is off screen`); bad++; }
  if (r.split.length) { console.log(`FAIL ${width}px: a value breaks mid-word: ${r.split.join(', ')}`); bad++; }
  await page.locator('#preview').screenshot({ path: `${out}/preview-${width}.png` });
  await ctx.close();
}
await browser.close();
console.log(bad ? `FAILED ${bad}` : 'OK');
process.exit(bad ? 1 : 0);
