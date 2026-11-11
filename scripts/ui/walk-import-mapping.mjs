// Roster import preview: the line that says which column became what. A
// director must read "Parent Email -> parent's email", not the internal
// field name "guardian_email". Exits 1 if any internal name shows.
//   node scripts/ui/walk-import-mapping.mjs <base> <outdir>
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const post = async (path, body, token) => (await fetch(`${base}${path}`, { method: 'POST',
  headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
  body: JSON.stringify(body) })).json();
const made = await post('/api/orgs', { name: 'Mapping Words Check', sport: 'lacrosse', accept_terms: true, director_name: 'Pat Lee' });
const tok = made.director.token;
await post('/api/teams', { name: '2031 Red' }, tok);
const csv = 'Player ID,First Name,Last Name,Jersey,Position,Birth Year,Hand,Grade,Team,Player Email,'
  + 'Parent Name,Parent Email,Parent Phone,Parent 2 Name,Parent 2 Email,Parent 2 Phone,Shoe Size\n'
  + 'A1,Sam,Ortiz,7,Attack,2013,Right,7,2031 Red,sam@example.com,Ana Ortiz,ana@example.com,615-555-0101,'
  + 'Luis Ortiz,luis@example.com,615-555-0102,8\n';
const browser = await chromium.launch();
let bad = 0;
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
const page = await ctx.newPage();
page.on('pageerror', (e) => { console.log('PAGEERROR', e.message); bad++; });
await page.goto(`${base}/app/index.html?code=${tok}`, { waitUntil: 'networkidle' });
await page.waitForTimeout(1200);
await page.locator('#wizard-skip').click({ timeout: 1500 }).catch(() => {});
await page.evaluate(() => document.querySelectorAll('.fold').forEach((c) => c._foldOpen && c._foldOpen()));
await page.locator('.source-btn', { hasText: /file/i }).first().click().catch(() => {});
await page.setInputFiles('#file-input', { name: 'roster.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
await page.waitForSelector('#preview .mapping code', { timeout: 8000 });
const items = await page.$$eval('#preview .mapping code', (els) => els.map((e) => e.textContent.trim()));
for (const it of items) console.log('  ' + it);
const internal = items.filter((t) => /_|\b(guardian|dominant|external)\b/i.test(t.split('→').pop()));
if (!items.length) { console.log('FAIL: no column mapping shown'); bad++; }
if (internal.length) { console.log(`FAIL: internal field names shown: ${internal.join(' | ')}`); bad++; }
if (!items.some((t) => /Parent Email\s*→\s*parent's email/i.test(t))) { console.log("FAIL: Parent Email is not read as \"parent's email\""); bad++; }
// Each "column -> meaning" pair is one chip: it may wrap inside itself only
// when it is wider than the box, and two chips never share a line box.
const geo = await page.$$eval('#preview .mapping code', (els) => {
  const box = els[0].parentElement.getBoundingClientRect();
  const r = els.map((e) => e.getBoundingClientRect());
  const overlap = r.some((a, i) => r.some((b, j) => j > i && a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1));
  const outside = r.some((a) => a.right > box.right + 1 || a.left < box.left - 1);
  const split = els.filter((e, i) => r[i].height > 40 && r[i].width < box.width - 2).map((e) => e.textContent.trim());
  return { overlap, outside, split };
});
if (geo.overlap) { console.log('FAIL: two mapping chips overlap'); bad++; }
if (geo.outside) { console.log('FAIL: a mapping chip runs off the box'); bad++; }
if (geo.split.length) { console.log(`FAIL: a short pair breaks across lines: ${geo.split.join(' | ')}`); bad++; }
await page.locator('#preview .mapping').scrollIntoViewIfNeeded();
await page.locator('#preview').screenshot({ path: `${out}/mapping-390.png` });
await ctx.close();
await browser.close();
console.log(bad ? `FAILED ${bad}` : 'OK');
process.exit(bad ? 1 : 0);
