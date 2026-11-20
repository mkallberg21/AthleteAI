// Builds the two PDFs the server attaches to a parent's invite (offdays/parent_guide.py lays a program's
// own logo on the first one). Run after the wording in guide.html changes, then commit the PDFs:
//   node scripts/ui/build-parent-guide.mjs        (needs playwright, as the other scripts/ui walks do)
import { chromium } from 'playwright';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

const root = process.env.OFFDAYS_ROOT || path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const dir = path.join(root, 'offdays', 'assets', 'parent_guide');
const url = pathToFileURL(path.join(dir, 'guide.html')).href;
const b = await chromium.launch();
const out = {};
for (const [file, hasLogo] of [['guide_logo.pdf', true], ['guide_plain.pdf', false]]) {
  const p = await b.newPage({ viewport: { width: 720, height: 900 } });
  await p.goto(url, { waitUntil: 'networkidle' });
  await p.evaluate(([logo]) => { document.body.classList.add('pdf'); if (logo) document.body.classList.add('has-logo'); }, [hasLogo]);
  await p.evaluate(() => document.fonts.ready);
  await p.emulateMedia({ media: 'print' });
  const h = await p.evaluate(() => Math.ceil(document.documentElement.scrollHeight));
  await p.pdf({ path: path.join(dir, file), width: '720px', height: `${h + 4}px`, printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 }, pageRanges: '1' });
  out[file] = h;
  await p.close();
}
console.log(JSON.stringify(out));
await b.close();
