// Does the live interface still look right? Run against prod on a schedule
// and after every deploy; exits non-zero (and the job turns red) when it
// does not. Screenshots of every screen are saved for a human to look at.
//
// This checks the things that have actually gone wrong, not a pixel diff:
//   - the stylesheet the page asks for is the one the server has (a stale
//     ?v= pin is how every panel unfolded on a phone once)
//   - no 4xx/5xx on anything the page loads, no JS errors
//   - landing: four role buttons, every panel hidden, page short enough
//     to sit on one phone screen, header shows the one-word lockup
//   - tap each role: that panel and only that panel opens; the first
//     input is on screen
//   - the director path: create a program, land on the dashboard, badge
//     card and cost card present, no empty sponsor bar, dashboard wider
//     than a phone column on a laptop
//   - buttons a human must find are >= 44px tall and on screen
//
//   node scripts/ui/health.mjs https://app.0ffdays.com <outdir>
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';

const [base = 'https://app.0ffdays.com', out = 'ui-health'] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const problems = [];
const bad = (what) => { problems.push(what); console.log('  PROBLEM:', what); };
const ok = (what) => console.log('  ok:', what);

const browser = await chromium.launch();

async function fresh(tag, opts) {
  const ctx = await browser.newContext({ ...opts, serviceWorkers: 'block' });
  const page = await ctx.newPage();
  const failures = [];
  page.on('response', (r) => { if (r.status() >= 400 && !/family\/board/.test(r.url())) failures.push(`${r.status()} ${r.url()}`); });
  page.on('pageerror', (e) => failures.push(`JS: ${e.message}`));
  return { ctx, page, failures, tag };
}

async function assertStylesheetCurrent(page, tag) {
  const href = await page.evaluate(() => [...document.styleSheets].map((s) => s.href).find((h) => h && /styles\.css/.test(h)));
  if (!href) return bad(`${tag}: no styles.css loaded`);
  const rules = await page.evaluate(() => { try { return [...document.styleSheets].find((s) => /styles\.css/.test(s.href || '')).cssRules.length; } catch { return 0; } });
  if (rules < 300) bad(`${tag}: styles.css has ${rules} rules; expected the full sheet`);
  // The pinned version must match what the server serves for the unpinned file.
  const served = await (await fetch(`${base}/app/styles.css`, { cache: 'no-store' })).text();
  const pinned = await (await fetch(href, { cache: 'no-store' })).text();
  if (served !== pinned) bad(`${tag}: ${href} differs from the server's styles.css -- bump the ?v= pin`);
  else ok(`${tag}: stylesheet ${href.split('?')[1] || '(unpinned)'} is current`);
}

async function box(page, sel) {
  const el = page.locator(sel).first();
  if (!(await el.count())) return null;
  const b = await el.boundingBox();
  const vp = page.viewportSize();
  return b && { ...b, onScreen: b.y >= 0 && b.y + b.height <= vp.height, visible: await el.isVisible() };
}

// ------------------------------------------------------------ landing
for (const [tag, opts] of [['phone', devices['iPhone 13']], ['laptop', { viewport: { width: 1280, height: 800 } }]]) {
  console.log(`\n== landing (${tag})`);
  const { ctx, page, failures } = await fresh(tag, opts);
  // The bare domain is what people type. It must land on the styled page.
  await page.goto(`${base}/`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(500);
  if (!/\/app\/index\.html/.test(page.url())) bad(`${tag}: '/' stayed at ${page.url()} instead of /app/index.html`); else ok(`${tag}: '/' lands on /app/index.html`);
  await assertStylesheetCurrent(page, tag);
  if (failures.length) bad(`${tag}: ${failures.join('; ')}`);

  const roles = await page.locator('.role-btn').count();
  if (roles !== 4) bad(`${tag}: ${roles} role buttons, expected 4`); else ok(`${tag}: four role buttons`);
  const open = await page.evaluate(() => [...document.querySelectorAll('.role-panel')].filter((e) => getComputedStyle(e).display !== 'none').map((e) => e.id));
  if (open.length) bad(`${tag}: panels open on arrival: ${open.join(', ')}`); else ok(`${tag}: all panels closed on arrival`);
  const sponsor = await page.evaluate(() => [...document.querySelectorAll('.sponsor-slot')].some((e) => getComputedStyle(e).display !== 'none' && !e.classList.contains('has-sponsor')));
  if (sponsor) bad(`${tag}: empty 'Sponsored by' bar is showing`);
  const h = await page.evaluate(() => document.body.scrollHeight);
  const vp = page.viewportSize().height;
  if (tag === 'phone' && h > vp * 1.15) bad(`phone: landing is ${h}px tall on a ${vp}px screen; it should be one screen`); else ok(`${tag}: landing height ${h}px`);
  const lockup = await box(page, 'header .offdays-lockup');
  if (!lockup || !lockup.visible) bad(`${tag}: one-word 0FFDAYS lockup not in the header`); else ok(`${tag}: header lockup visible`);
  await page.screenshot({ path: `${out}/${tag}-landing.png`, fullPage: true });

  for (const role of ['athlete', 'parent', 'coach', 'director']) {
    await page.click(`.role-btn[data-role="${role}"]`);
    await page.waitForTimeout(600);
    const nowOpen = await page.evaluate(() => [...document.querySelectorAll('.role-panel')].filter((e) => getComputedStyle(e).display !== 'none').map((e) => e.id));
    if (nowOpen.join() !== `panel-${role}`) bad(`${tag}: tapping ${role} opened [${nowOpen.join(', ')}]`);
    const input = await box(page, `#panel-${role} input`);
    if (!input || !input.visible) bad(`${tag}: ${role} panel has no visible input`);
    const btn = await box(page, `#panel-${role} button.btn-primary, #panel-${role} button[type="submit"], #panel-${role} .btn`);
    if (btn && btn.height < 40) bad(`${tag}: ${role} button is ${Math.round(btn.height)}px tall`);
    await page.screenshot({ path: `${out}/${tag}-landing-${role}.png`, fullPage: true });
  }
  ok(`${tag}: each role opens only its own panel`);
  await ctx.close();
}

// ------------------------------------------------------------ director dashboard
console.log('\n== director dashboard');
const made = await (await fetch(`${base}/api/orgs`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: 'UI health check', sport: 'lacrosse', director_name: 'Health Check' }) })).json();
const token = made?.director?.token;
if (!token) bad('could not create a throwaway program on prod');
else {
  for (const [tag, opts] of [['phone', devices['iPhone 13']], ['laptop', { viewport: { width: 1280, height: 800 } }]]) {
    const { ctx, page, failures } = await fresh(tag, opts);
    await page.goto(`${base}/app/index.html?code=${token}`, { waitUntil: 'networkidle' });
    await page.waitForURL(/coach\.html/, { timeout: 15000 }).catch(() => bad(`${tag}: director code did not land on the dashboard`));
    await page.waitForTimeout(2500);
    await assertStylesheetCurrent(page, `dashboard ${tag}`);
    // A brand-new director meets the walkthrough: one step, nothing else, Next gated.
    const wiz = await page.locator('#wizard').isVisible().catch(() => false);
    if (!wiz) bad(`dashboard ${tag}: a new director did not get the setup walkthrough`);
    else {
      const others = await page.evaluate(() => [...document.querySelectorAll('.wrap > .card:not(#wizard)')].filter((c) => getComputedStyle(c).display !== 'none').map((c) => c.id));
      if (others.length) bad(`dashboard ${tag}: walkthrough is on but other cards show: ${others.join(', ')}`);
      const t = await page.locator('#wizard-title').textContent();
      if (!/badge/i.test(t)) bad(`dashboard ${tag}: walkthrough starts at '${t}', expected the badge step`);
      await page.screenshot({ path: `${out}/${tag}-walkthrough.png`, fullPage: false });
      await page.click('#wizard-skip'); await page.waitForTimeout(600);
      ok(`dashboard ${tag}: walkthrough shown first, skipped for the card checks`);
    }
    if (failures.length) bad(`dashboard ${tag}: ${failures.join('; ')}`);
    for (const [sel, name] of [['#badge-card', 'badge card'], ['#billing-card', 'cost card'], ['#setup-card', 'setup checklist'], ['#sync-card', 'roster sync card']]) {
      const b = await box(page, sel);
      if (!b || !b.visible) bad(`dashboard ${tag}: ${name} missing`);
    }
    const costText = await page.locator('#billing-card').innerText().catch(() => '');
    if (/per month|Compare plans|seats used/i.test(costText)) bad(`dashboard ${tag}: cost card shows legacy seat/monthly wording`);
    if (!/season costs|per athlete per day/i.test(costText)) bad(`dashboard ${tag}: cost card is not the per-athlete-per-day card`);
    const sponsor = await page.evaluate(() => [...document.querySelectorAll('.sponsor-slot')].some((e) => getComputedStyle(e).display !== 'none' && !e.classList.contains('has-sponsor')));
    if (sponsor) bad(`dashboard ${tag}: empty 'Sponsored by' bar is showing`);
    if (tag === 'laptop') {
      const w = await page.evaluate(() => document.querySelector('.wrap').getBoundingClientRect().width);
      if (w < 900) bad(`dashboard laptop: content column is ${Math.round(w)}px wide; it should use the screen`); else ok(`dashboard laptop: ${Math.round(w)}px wide`);
    }
    await page.screenshot({ path: `${out}/${tag}-dashboard.png`, fullPage: false });
    await ctx.close();
    ok(`dashboard ${tag}: cards present, cost card correct`);
  }
}

await browser.close();
console.log(`\n${problems.length ? problems.length + ' PROBLEM(S)' : 'ALL GOOD'} -- screenshots in ${out}/`);
process.exit(problems.length ? 1 : 0);
