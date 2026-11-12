// A phone that opened the app before a release holds the old pages in the service worker's cache.
// The pages the server enforces rules on (sign-up, director dashboard, parent) must come fresh on the FIRST open after a
// release, still open with no signal, and the athlete's capture screen must stay instant and offline-capable.
// Run: node walk-stale-pages.mjs <base> <out-dir>
import { chromium, devices } from 'playwright';
import http from 'node:http';
const [target] = process.argv.slice(2);
let bad = 0;
const check = (ok, what) => { console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); if (!ok) bad++; };
const STALE = '<!doctype html><title>old</title><body><h1 id="stale-page">an older release of this page</h1></body>';

// The phone talks to this proxy, so the walk can make the "server" slow the way a bad signal does. A request the
// service worker makes itself is not visible to page.route, which is why a real proxy is used.
let delayIndexMs = 0;
const proxy = http.createServer((req, res) => {
  const go = () => {
    const up = http.request(target + req.url, { method: req.method, headers: { ...req.headers, host: new URL(target).host } }, (r) => {
      res.writeHead(r.statusCode, r.headers); r.pipe(res);
    });
    up.on('error', () => { res.statusCode = 502; res.end(); });
    req.pipe(up);
  };
  if (delayIndexMs && /\/app\/index\.html/.test(req.url)) setTimeout(go, delayIndexMs); else go();
});
await new Promise((r) => proxy.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${proxy.address().port}`;

const b = await chromium.launch();
const ctx = await b.newContext({ ...devices['iPhone 13'] });
const page = await ctx.newPage();
await page.goto(base + '/app/index.html', { waitUntil: 'networkidle' });
await page.evaluate(async () => { await navigator.serviceWorker.register('sw.js', { scope: './' }); await navigator.serviceWorker.ready; });
await page.waitForTimeout(2500);
const cacheName = await page.evaluate(async () => (await caches.keys())[0]);
check(/^offdays-shell-v\d+$/.test(cacheName || ''), `the worker made its cache (${cacheName})`);

const plant = (file) => page.evaluate(async ([f, html]) => {
  const c = await caches.open((await caches.keys())[0]);
  await c.put(new URL(f, location.href).href, new Response(html, { headers: { 'Content-Type': 'text/html' } }));
}, [file, STALE]);
const isStale = () => page.evaluate(() => !!document.getElementById('stale-page'));

// 1. sign-up, director and parent pages are fresh on the first open
for (const file of ['index.html', 'coach.html', 'parent.html']) {
  await plant(file);
  await page.goto(`${base}/app/${file}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  check(!(await isStale()), `${file}: the first open after a release is the new page, not the saved old one`);
}
await plant('index.html');
await page.goto(`${base}/app/index.html`, { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(500);
check(await page.locator('#org-terms').count() === 1, 'index.html: and it has what the release added (the terms tick box)');

// 2. with no connection those pages still open, from the saved copy
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await page.goto(`${base}/app/coach.html`, { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(800);
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);
await ctx.setOffline(true);
await page.goto(`${base}/app/index.html`, { waitUntil: 'domcontentloaded' }).catch(() => {});
await page.waitForTimeout(800);
check(await page.locator('#org-terms').count() === 1, 'offline: the sign-up page still opens from the saved copy');
await ctx.setOffline(false);

// 3. the athlete's capture screen is untouched: saved copy first, so it opens instantly and with no signal
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await plant('capture.html');
await page.goto(`${base}/app/capture.html`, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(600);
check(await isStale(), 'capture.html: still served from the saved copy first (instant, works with no signal)');

// 4. a very slow server does not leave the page blank: after about four seconds it falls back to the saved copy
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);
delayIndexMs = 12000;
const t0 = Date.now();
await page.goto(`${base}/app/index.html`, { waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => {});
const took = Date.now() - t0;
delayIndexMs = 0;
check(took >= 3500 && took < 9000 && await page.locator('#org-terms').count() === 1,
  `a server that takes 12 s falls back to the saved page after about 4 s (${took} ms)`);

await b.close();
proxy.close();
console.log(bad ? `FAILED: ${bad}` : 'all good');
process.exit(bad ? 1 : 0);
