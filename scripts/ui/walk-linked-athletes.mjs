// One athlete in two programs: a parent links them in the browser, the athlete's screen says so, and work counts in both.
// Run: node walk-linked-athletes.mjs <base> <out-dir>
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'node:fs';

const [base, out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
let bad = 0;
const check = (ok, what, extra = '') => { console.log(`${ok ? 'ok   ' : 'FAIL '}${what} ${extra}`); if (!ok) bad += 1; };
const j = async (path, token, body, method) => {
  const r = await fetch(base + path, { method: method || (body ? 'POST' : 'GET'), headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, json: await r.json().catch(() => ({})) };
};
const EMAIL = `kathy.${Date.now()}@example.com`;   // a fresh parent each run, so a reused server never has extra matches

async function club(name) {
  const made = (await j('/api/orgs', null, { name, sport: 'lacrosse', accept_terms: true, director_name: 'Dir' })).json;
  const d = made.director.token;
  const team = (await j('/api/teams', d, { name: '2031 Red' }, 'POST')).json.id;
  await j('/api/coach/roster/import', d, { content: `First Name,Last Name,Birth Year,Parent Email\nRyder,Kallberg,2013,${EMAIL}\n`, team_id: team });
  const rows = (await j(`/api/coach/team-ranking?team_id=${team}`, d)).json.rows;
  const kid = rows[0].athlete_id;
  const inv = (await j('/api/coach/guardian-invites', d, { athlete_id: kid, email: EMAIL })).json;
  const parent = (await j('/api/guardians/redeem', null, { code: inv.code, display_name: 'Kathy Kallberg', email: EMAIL, phone: '615-555-0101' })).json;
  await j('/api/guardians/consent', parent.token, { athlete_id: kid, scope: 'participation', granted: true });
  const link = (await j(`/api/guardians/athlete-link/${kid}`, parent.token, {})).json.link;
  return { d, kid, parent: parent.token, athlete: link.split('code=')[1] };
}

const A = await club('Nashville Dogs');
const B = await club('Mad Dog Lacrosse');

const b = await chromium.launch();
const ph = devices['iPhone 13'];

// --- the parent in program A sees the offer
const pctx = await b.newContext({ ...ph });
const page = await pctx.newPage();
const errs = [];
page.on('pageerror', (e) => errs.push(e.message));
await page.goto(`${base}/app/index.html`, { waitUntil: 'networkidle' });
await page.evaluate((t) => { localStorage.setItem('offdays.token', t); localStorage.setItem('offdays.pwizard', 'done'); }, A.parent);
await page.goto(`${base}/app/parent.html`, { waitUntil: 'networkidle' });
await page.waitForSelector('[data-offer]', { timeout: 15000 });
const offer = (await page.locator('[data-offer]').innerText()).replace(/\s+/g, ' ');
check(/Is Ryder in another program too\?/.test(offer), 'the parent is asked whether Ryder is in another program', `(${offer.slice(0, 60)}...)`);
check(/Ryder Kallberg at Mad Dog Lacrosse/.test(offer), 'it names the athlete and the other program');
check(/from now on/i.test(offer) && /stop any time/i.test(offer), 'it says it counts from now on and can be stopped');
check((await j(`/api/guardians/links/${A.kid}`, A.parent)).json.linked.length === 0, 'nothing is linked until the button is pressed');
await page.locator('[data-offer]').scrollIntoViewIfNeeded();
await page.screenshot({ path: `${out}/1-offer.png` });

// --- press it
await page.click('[data-link-to]');
await page.waitForSelector('[data-linked]', { timeout: 15000 });
const linkedText = (await page.locator('[data-linked]').innerText()).replace(/\s+/g, ' ');
check(/Counts in more than one program/.test(linkedText) && /Mad Dog Lacrosse/.test(linkedText), 'it now says the work counts in both', `(${linkedText.slice(0, 70)}...)`);
check(!(await page.locator('[data-offer]').count()), 'the offer is gone once linked');
check(!/Nashville/.test(linkedText), "the parent is not told their own program's name as an 'other' program");
await page.locator('[data-linked]').scrollIntoViewIfNeeded();
await page.screenshot({ path: `${out}/2-linked.png` });
const box = await page.locator('[data-linked]').boundingBox();
check(box && box.x >= 0 && box.x + box.width <= ph.viewport.width, 'the block fits the phone');

// --- the other program's parent sees it too
const me2 = (await j(`/api/guardians/links/${B.kid}`, B.parent)).json;
check(me2.linked.length === 1 && me2.linked[0].org_name === 'Nashville Dogs', "program B's parent sees it from their side");

// --- the athlete's screen says so
const actx = await b.newContext({ ...devices['Pixel 5'] });
const ap = await actx.newPage();
ap.on('pageerror', (e) => errs.push(e.message));
await ap.addInitScript(() => { try { localStorage.setItem('offdays.awizard', 'done'); } catch (e) {} });
await ap.goto(`${base}/app/index.html?code=${A.athlete}`, { waitUntil: 'networkidle' });
await ap.waitForSelector('#counts-for:not(.hidden)', { timeout: 15000 });
const line = (await ap.locator('#counts-for').innerText()).trim();
check(line === 'Your work counts for Nashville Dogs and Mad Dog Lacrosse.', 'the athlete is told which programs it counts for', `(${line})`);
await ap.screenshot({ path: `${out}/3-athlete.png` });

// --- work done in program A counts in program B
const train = async (token) => {
  const s = (await j('/api/sessions/start', token, { drill_key: 'lax_wall_ball' })).json;
  let t = 0; const reps = [];
  let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < 100; i++) { t += 700 + Math.floor(rnd() * 400); reps.push({ t_ms: t, hand: i % 2 ? 'left' : 'right', confidence: 0.88 }); }
  return (await j('/api/sessions/submit', token, { session_id: s.session_id, nonce: s.nonce, duration_ms: t + 700, reps, mean_confidence: 0.88 })).json;
};
const done = await train(A.athlete);
check(done.status === 'counted', 'the athlete finishes a drill in program A', `(${done.status}, ${done.reps_total} reps)`);
const meB = (await j('/api/me', B.athlete)).json;
const meA = (await j('/api/me', A.athlete)).json;
check(meB.total_xp > 0 && meB.total_xp === meA.total_xp, 'program B counted the same XP', `(${meB.total_xp} / ${meA.total_xp})`);
const playerB = (await j(`/api/coach/overview/player/${B.kid}?window=all`, B.d)).json;
check(playerB.sessions === 1 && (playerB.recent_sessions || []).length === 1, "program B's director sees Ryder's session on their own player page", `(${playerB.sessions} session)`);
const home = playerB;
check(!JSON.stringify(home).includes('Nashville'), "and program B's director is never shown the other program's name");
const homeA = (await j('/api/coach/overview', A.d)).json;
check(!JSON.stringify(homeA).includes('Mad Dog'), "program A's director is never shown the other program's name either");

// --- stop it
await page.reload({ waitUntil: 'networkidle' });
await page.waitForSelector('[data-unlink]');
page.once('dialog', (d) => d.accept());
await page.click('[data-unlink]');
await page.waitForSelector('[data-offer]', { timeout: 15000 });
check((await j(`/api/guardians/links/${A.kid}`, A.parent)).json.linked.length === 0, 'the parent can stop it, and the offer comes back');
const after = await train(A.athlete);
const meB2 = (await j('/api/me', B.athlete)).json;
check(meB2.total_xp === meB.total_xp, 'after stopping, new work is not counted in program B');
check(errs.length === 0, 'no page errors', errs.join(' | '));

await b.close();
console.log(bad ? `${bad} FAILED` : 'all good');
process.exit(bad ? 1 : 0);
