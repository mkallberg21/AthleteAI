// Terms at sign-up, the director's website switch, the operator's review, and the public list. As a person would.
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8017';
const out = process.argv[3] || '.';
const OPKEY = 'k'.repeat(32);
fs.mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); if (!ok) bad++; };

// A real small PNG with a recognisable colour, so the operator's thumbnail is visible in the screenshot.
import zlib from 'node:zlib';
function makePng(w, h) {
  // A real, valid PNG: a blue badge with a white stripe, built from raw pixels.
  const rows = [];
  for (let y = 0; y < h; y++) {
    const row = Buffer.alloc(1 + w * 3);
    for (let x = 0; x < w; x++) {
      const stripe = y > h * 0.4 && y < h * 0.6;
      row[1 + x * 3] = stripe ? 255 : 0; row[2 + x * 3] = stripe ? 255 : 139; row[3 + x * 3] = stripe ? 255 : 253;
    }
    rows.push(row);
  }
  const crcT = new Uint32Array(256).map((_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
  const crc = (b) => { let c = 0xffffffff; for (const x of b) c = crcT[(c ^ x) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const chunk = (t, d) => { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const td = Buffer.concat([Buffer.from(t), d]); const c = Buffer.alloc(4); c.writeUInt32BE(crc(td)); return Buffer.concat([l, td, c]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(Buffer.concat(rows))), chunk('IEND', Buffer.alloc(0))]);
}
const PNG = makePng(160, 80);
const png = path.join(out, 'badge.png');
fs.writeFileSync(png, PNG);

const browser = await chromium.launch();
const pub = async () => (await (await fetch(base + '/api/programs/showcase')).json()).programs;

for (const [tag, ctx] of [['laptop', { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } }], ['phone', { ...devices['iPhone 13'] }]]) {
  const stamp = `${tag} ${Date.now()}`;
  const name = `Wall ${stamp}`;
  const page = await (await browser.newContext(ctx)).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));

  // 1. Sign-up: the box is there, unticked, and the program is not made without it.
  await page.goto(`${base}/app/index.html`);
  await page.locator('.role-btn[data-role="director"]').click();
  await page.locator('#panel-director').waitFor({ state: 'visible' });
  await page.fill('#org-name', name);
  await page.fill('#org-director', 'Dana Pierce');
  check(await page.locator('#org-terms').isVisible(), `${tag}: the terms box is on the sign-up form`);
  check(!(await page.locator('#org-terms').isChecked()), `${tag}: it starts unticked`);
  check(await page.locator('.terms-check a[href="terms.html"]').count() === 1, `${tag}: it links to the terms`);
  await page.locator('#create-org').click();
  check(/terms/i.test(await page.locator('#oerr').innerText()), `${tag}: leaving it empty is refused with a plain message`);
  await page.screenshot({ path: path.join(out, `${tag}-signup.png`), fullPage: false });

  // 2. Tick it and go.
  await page.locator('#org-terms').check();
  await page.locator('#create-org').click();
  await page.waitForURL(/coach\.html/, { timeout: 15000 }).catch(() => {});
  check(/coach\.html/.test(page.url()), `${tag}: with the box ticked the program is created and the director is in`);

  // 3. Upload a badge through the dashboard, then the switch says "waiting".
  const dashboardHasBadgeCard = await page.locator('#badge-card').count();
  check(dashboardHasBadgeCard === 1, `${tag}: the badge card exists`);
  await page.locator('button[data-tab="settings"]').click();
  await page.locator('#badge-card').waitFor({ state: 'visible' });
  await page.setInputFiles('#badge-file', png);
  await page.waitForFunction(() => /waiting|looking/i.test(document.getElementById('show-note')?.textContent || ''), null, { timeout: 15000 }).catch(() => {});
  check(await page.locator('#show-site').isChecked(), `${tag}: "Show my program on the website" is on, from the terms`);
  check(/looking at your badge/i.test(await page.locator('#show-note').innerText()), `${tag}: it says we are looking at it, not that it is live`);
  check(!(await pub()).some((p) => p.name === name), `${tag}: it is not public yet`);
  await page.locator('#badge-card').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, `${tag}-director-waiting.png`) });

  // 4. The operator opens the page, sees the image and approves it.
  const op = await (await browser.newContext(ctx)).newPage();
  await op.goto(`${base}/admin`);
  await op.fill('#key', OPKEY);
  await op.locator('#enter').click();
  await op.locator('#wall-card').waitFor({ state: 'visible' });
  await op.waitForFunction((n) => document.getElementById('wall').innerText.includes(n), name, { timeout: 15000 });
  const row = op.locator('#wall .prog', { hasText: name });
  check(await row.locator('img').count() === 1, `${tag}: the operator sees the image to judge`);
  check(/Waiting for you/.test(await row.innerText()), `${tag}: it is listed as waiting`);
  await op.screenshot({ path: path.join(out, `${tag}-operator.png`) });
  await row.getByRole('button', { name: 'Approve' }).click();
  await op.waitForFunction((n) => /Live on the website/.test(document.querySelector('#wall').innerText) && document.getElementById('wall').innerText.includes(n), name, { timeout: 15000 });
  check((await pub()).some((p) => p.name === name), `${tag}: after approval it is on the public list`);
  const mine = (await pub()).find((p) => p.name === name);
  check(mine && Object.keys(mine).sort().join() === 'logo,name,sport', `${tag}: the public list shows only name, sport and logo`);

  // 5. The director turns it off; it is gone at once. Turning it on again brings the approved image back.
  await page.reload();
  await page.locator('button[data-tab="settings"]').click();
  await page.locator('#badge-card').waitFor({ state: 'visible' });
  await page.waitForFunction(() => /on the list/i.test(document.getElementById('show-note')?.textContent || ''), null, { timeout: 15000 }).catch(() => {});
  check(/on the list/i.test(await page.locator('#show-note').innerText()), `${tag}: the director is told it is live`);
  await page.locator('#show-site').uncheck();
  await page.waitForFunction(() => /not shown/i.test(document.getElementById('show-note').textContent), null, { timeout: 10000 }).catch(() => {});
  check(!(await pub()).some((p) => p.name === name), `${tag}: turning it off removes it from the public list at once`);
  check(/not shown/i.test(await page.locator('#show-note').innerText()), `${tag}: and says so`);
  await page.locator('#show-site').check();
  await page.waitForFunction(() => /on the list/i.test(document.getElementById('show-note').textContent), null, { timeout: 10000 }).catch(() => {});
  check((await pub()).some((p) => p.name === name), `${tag}: turning it back on restores the approved image`);

  // 6. The operator can take it down, and it stays down.
  await op.reload();
  await op.fill('#key', OPKEY); await op.locator('#enter').click();
  await op.waitForFunction((n) => document.getElementById('wall').innerText.includes(n), name, { timeout: 15000 });
  await op.locator('#wall .prog', { hasText: name }).getByRole('button', { name: 'Take down' }).click();
  await op.waitForTimeout(800);
  check(!(await pub()).some((p) => p.name === name), `${tag}: the operator taking it down removes it`);

  check(errors.length === 0, `${tag}: no script errors${errors.length ? ' ' + errors[0] : ''}`);
}
await browser.close();
console.log(bad ? `\n${bad} FAILED` : '\nall good');
process.exit(bad ? 1 : 0);
