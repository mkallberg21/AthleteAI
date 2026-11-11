// Sending or resending invites to many families at once, in a real browser: pick some, pick everyone, send,
// read what happened, and prove it never touches a family that was not picked. Throwaway local server only.
//
//   node walk-bulk-invites.mjs <base> <outdir>
import { chromium, devices } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const base = process.argv[2] || 'http://127.0.0.1:8016';
const out = process.argv[3] || '.';
fs.mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) bad += 1; };
const call = async (p, opt = {}, token) => {
  const r = await fetch(base + p, { method: opt.method || 'GET', headers: { 'content-type': 'application/json', ...(token ? { authorization: `Bearer ${token}` } : {}) }, body: opt.body ? JSON.stringify(opt.body) : undefined });
  return { status: r.status, body: await r.json().catch(() => ({})) };
};

const org = (await call('/api/orgs', { method: 'POST', body: { name: 'Bulk Walk Club', accept_terms: true, director_name: 'Dir Walk' } })).body;
const director = org.director.token;
const team = (await call('/api/teams', { method: 'POST', body: { name: '2013 Red' } }, director)).body;
const players = ['Ana Alvarez', 'Ben Brooks', 'Cy Chen', 'Di Diaz', 'Ed Evans', 'Flo Fox'];
const csv = ['First Name,Last Name,Birth Year,Parent Email']
  .concat(players.map((p, i) => `${p.split(' ')[0]},${p.split(' ')[1]},2013,${i === 5 ? '' : `parent${i}@example.com`}`)).join('\n');
const imp = await call('/api/coach/roster/import', { method: 'POST', body: { content: csv, team_id: team.id, invite_guardians: false } }, director);
check(imp.status === 201, 'seeded a roster of six, one with no parent email');

const b = await chromium.launch();
async function open(device) {
  const ctx = await b.newContext({ ...devices[device] });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => { console.log('PAGE ERROR', e.message.slice(0, 200)); bad += 1; });
  page.on('dialog', (d) => d.accept());
  await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => localStorage.setItem('offdays.token', t), director);
  await page.goto(base + '/app/coach.html', { waitUntil: 'domcontentloaded' });
  await page.locator('#wizard-skip').click({ timeout: 2500 }).catch(() => {});
  await page.waitForTimeout(900);
  // Open it the way a director does: the Families tab, then the Families card.
  await page.locator('button[data-tab="families"]').click();
  await page.waitForTimeout(300);
  await page.evaluate(() => { const c = document.getElementById('families-card'); if (c && c._foldOpen && !c.classList.contains('open')) c._foldOpen(); });
  await page.waitForSelector('#families .family-row', { state: 'visible', timeout: 8000 });
  await page.waitForTimeout(400);
  return { ctx, page };
}
const rowOf = (page, name) => page.locator('#families .family-row', { hasText: name });
const pick = (page, name) => rowOf(page, name).locator('input[data-fam-pick]');
const live = async (id) => (await call('/api/coach/families', {}, director)).body.athletes.find((a) => a.athlete_id === id);

{
  const { ctx, page } = await open('iPhone 13');
  check(await page.locator('#fam-bar').isVisible(), 'phone: the "select" bar is there');
  check((await page.locator('input[data-fam-pick]').count()) === 5, 'phone: five families can be picked; the one with no parent email cannot');
  check((await rowOf(page, 'Flo Fox').locator('input[data-fam-pick]').count()) === 0, 'phone: and that one has no box');
  check(await page.locator('#fam-bulk-send').isDisabled(), 'phone: the send button is off until someone is picked');
  const box = await pick(page, 'Ana Alvarez').boundingBox();
  const lbl = await rowOf(page, 'Ana Alvarez').locator('.fam-pick').boundingBox();
  check(lbl.width >= 44 && lbl.height >= 44, `phone: the tap target is at least 44px (${Math.round(lbl.width)}x${Math.round(lbl.height)})`);

  await pick(page, 'Ana Alvarez').check();
  await pick(page, 'Cy Chen').check();
  check(/2 of 5 selected/.test(await page.locator('#fam-all-label').innerText()), 'phone: it counts the ticks');
  check((await page.locator('#fam-bulk-send').innerText()) === 'Send invites to 2 parents', `phone: the button says what it will do ("${await page.locator('#fam-bulk-send').innerText()}")`);
  check(await page.locator('#fam-all').evaluate((e) => e.indeterminate), 'phone: "select all" shows partly ticked');
  await page.locator('#fam-bar').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'bulk-phone-picked.png') });

  await page.locator('#fam-bulk-send').click();
  await page.waitForSelector('#fam-bulk-result:not(.hidden)', { timeout: 8000 });
  const msg = await page.locator('#fam-bulk-result').innerText();
  check(/2 invites are ready/.test(msg) && /Nothing was emailed/.test(msg), `phone: held program says nothing was emailed ("${msg.slice(0, 70)}...")`);
  check((await rowOf(page, 'Ana Alvarez').innerText()).includes('Send email') && (await rowOf(page, 'Cy Chen').innerText()).includes('Send email'), 'phone: each sent family now shows its own "Send email" link');
  check(!(await rowOf(page, 'Ben Brooks').innerText()).includes('New invite ready'), 'phone: a family that was not picked was not touched');
  check((await live((await call('/api/coach/families', {}, director)).body.athletes.find((a) => a.display_name === 'Ben Brooks').athlete_id)).stage === 'invite_unsent', 'phone: and its stage did not move');
  check((await call('/api/coach/families', {}, director)).body.athletes.find((a) => a.display_name === 'Ana Alvarez').stage === 'invited', 'phone: the picked ones moved to "invited"');
  check((await pick(page, 'Ana Alvarez').count()) === 0, 'phone: a family just sent to cannot be ticked again in the same sitting');
  await page.locator('#fam-bulk-result').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'bulk-phone-result.png') });

  // copy all messages
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']).catch(() => {});
  await page.locator('#fam-copy-all').click();
  await page.waitForTimeout(300);
  const copied = await page.evaluate(() => navigator.clipboard.readText()).catch(() => '');
  check(/Copied/.test(await page.locator('#fam-copy-all').innerText()) && (copied.match(/To: /g) || []).length === 2 && copied.includes('parent0@example.com') && copied.includes('parent2@example.com'), 'phone: "Copy all" puts both messages, each with its own address, on the clipboard');
  check(!copied.includes('parent1@example.com'), 'phone: and only the picked ones');
  await ctx.close();
}

{
  const { ctx, page } = await open('iPhone 13');
  // Select everyone left; resend is a "resend" for the ones already invited
  await page.locator('#fam-all').check();
  const n = await page.locator('#fam-bulk-send').innerText();
  check(/Send or resend invites to 5 parents/.test(n), `phone: select everyone picks every family that can be sent to, the two already invited included, as a resend ("${n}")`);
  await page.locator('#fam-all').uncheck();
  check((await page.locator('#fam-bulk-send').innerText()) === 'Send invites' && await page.locator('#fam-bulk-send').isDisabled(), 'phone: untick all clears it');

  // switching the filter drops picks you can no longer see
  await pick(page, 'Ben Brooks').check();
  await page.locator('#families-filter').selectOption('athlete');
  await page.waitForTimeout(300);
  await page.locator('#families-filter').selectOption('stuck');
  await page.waitForTimeout(300);
  check(await page.locator('#fam-bulk-send').isDisabled(), 'phone: changing the filter clears the picks, so nothing hidden is ever sent');
  await ctx.close();
}

{
  const { ctx, page } = await open('Desktop Chrome');
  await page.locator('#fam-all').check();
  await page.locator('#fam-bar').scrollIntoViewIfNeeded();
  await page.screenshot({ path: path.join(out, 'bulk-laptop.png') });
  const txt = await page.locator('#fam-bulk-send').innerText();
  check(/Send or resend invites to 5 parents/.test(txt), `laptop: button reads sensibly ("${txt}")`);
  await page.locator('#fam-bulk-send').click();
  await page.waitForSelector('#fam-bulk-result:not(.hidden)', { timeout: 8000 });
  check(/5 invites are ready/.test(await page.locator('#fam-bulk-result').innerText()), 'laptop: five done, the two earlier ones resent');
  const board = (await call('/api/coach/families', {}, director)).body.athletes;
  check(board.filter((a) => a.stage === 'invited').length === 5 && board.filter((a) => a.stage === 'no_parent').length === 1, 'laptop: five invited, the one with no parent email still waiting on the program');
  const live1 = [];
  for (const a of board.filter((x) => x.stage === 'invited')) live1.push(a.athlete_id);
  await ctx.close();
}

await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
