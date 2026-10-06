/** Thin API client. Token lives in localStorage; nothing else is persisted. */

const TOKEN_KEY = 'offdays.token';
const ORG_KEY = 'offdays.org';

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(t) {
  try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
}
export function logout() {
  setToken(null);
  setOrg(null);
  location.href = '/app/index.html';
}

/** The program the caller is currently acting in. */
export function getOrg() {
  try { return localStorage.getItem(ORG_KEY); } catch { return null; }
}
export function setOrg(orgId) {
  try {
    orgId ? localStorage.setItem(ORG_KEY, String(orgId)) : localStorage.removeItem(ORG_KEY);
  } catch { /* private mode */ }
}

export async function api(path, { method = 'GET', body, raw = false } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  // Someone with roles in two clubs is one account; this says which hat.
  const org = getOrg();
  if (org) headers['X-Org-Id'] = org;

  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (res.status === 401) {
    setToken(null);
    throw new Error('Your sign-in expired. Enter your athlete code again.');
  }
  if (res.status === 403 && path === '/api/me') {
    // A real code the server will not seat: the season has ended, or the
    // wrong program. The reason is the whole message; a generic one would
    // send a kid to their coach saying the app is broken.
    let detail = 'You cannot sign in right now.';
    try { detail = (await res.json()).detail || detail; } catch { /* keep */ }
    setToken(null);
    throw new Error(detail);
  }
  if (res.status === 429) {
    // Too many wrong codes from this phone or at this code. Say how long,
    // and do not drop the stored token: the code may well be right.
    const wait = parseInt(res.headers.get('Retry-After') || '30', 10);
    const err = new Error(`Too many tries. Wait ${wait} seconds and try again.`);
    err.status = 429;
    err.permanent = false;
    throw err;
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (data.detail) {
        detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      }
    } catch { /* non-JSON error body */ }
    const err = new Error(detail);
    // A 4xx is the server rejecting this payload on its merits -- it will
    // never succeed, so a queued retry must give up rather than loop forever.
    // A 5xx or a thrown fetch (offline) is worth retrying.
    err.status = res.status;
    err.permanent = res.status >= 400 && res.status < 500;
    throw err;
  }
  if (res.status === 204) return null;
  // `raw` is for the one endpoint that returns a file rather than JSON. It
  // still goes through here so the bearer token and org header ride along --
  // a bare <a href> would 401.
  return raw ? res.text() : res.json();
}

/** Escape text before it reaches innerHTML. Display names are user-supplied. */
export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

export function fmtDate(iso) {
  if (!iso) return 'never';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'unknown';
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString();
}


/**
 * The brand accent, read from the stylesheet rather than repeated in code.
 *
 * Canvas and inline styles take a colour string, not a custom property, so
 * every overlay used to carry its own copy of the accent hex. That is how the
 * pose overlay, the review overlay and the leaderboard's "this is you" row
 * each stayed green after the app had been re-skinned -- three copies, none of
 * which the stylesheet could reach.
 */
export function accent(alpha = 1) {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue('--accent').trim() || '#008BFD';
  if (alpha >= 1) return value;
  const hex = value.replace('#', '');
  const n = parseInt(hex.length === 3
    ? hex.split('').map((c) => c + c).join('') : hex, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}


/**
 * Put the club's badge at the top of the page, with ours behind it.
 *
 * Called by every screen with a topbar. A program that has not uploaded a
 * badge still gets its name in the same place, so the header never looks
 * broken and never looks like it belongs to us.
 */
export async function renderBranding(slot, subtitle = "") {
  const el = typeof slot === "string" ? document.getElementById(slot) : slot;
  if (!el) return null;
  let brand = { name: "", logo: "" };
  try { brand = await api("/api/branding"); } catch { /* header is not worth failing over */ }
  // The club's mark sits in the centre of the bar and ours at the far left:
  // the eye lands mid-header first, so the middle is the strongest slot to
  // give a program, and our wordmark reads as the masthead of the tool it
  // arrived in. A program with no badge puts its name in the same centre.
  const centre = brand.logo
    ? `<img class="club-badge" src="${brand.logo}" alt="${brand.name}">`
    : `<div class="club-name">${esc(brand.name)}</div>`;
  // The full lockup at exactly the 120px the brand guidelines set as its
  // minimum -- below that they say to use the bare mark instead, and this is
  // the smallest the wordmark is allowed to be. The club's badge is sized
  // larger than it so the program still leads its own header.
  // The full lockup on every screen, at every width. The guidelines' 120px
  // minimum is honoured by never going below it -- a phone keeps the whole
  // wordmark and the bar wraps to two rows instead, rather than falling back
  // to the bare glyph, which read as an unfinished logo.
  // Two siblings, not one wrapper: the slot is display:contents so these
  // become columns of the top bar itself, which is what lets the badge be
  // centred on the whole header rather than on the branding block.
  el.innerHTML = `<div class="mast-left"><div class="stack">
    <img class="offdays-lockup" src="offdays-lockup.png" alt="0FFDAYS">
    ${subtitle ? `<div class="role">${esc(subtitle)}</div>` : ""}
    </div></div>${centre}`;
  return brand;
}

/**
 * Shot speed history, the same picture for the athlete, their parent and
 * their coach: recent clocked shooting sessions, newest first, with the
 * typical and best speed of each and the plain limits underneath. Built from
 * what the server worked out at the time. Never ranked against anyone.
 */
export function renderShotHistory(data, { viewer = 'athlete' } = {}) {
  const rows = (data && data.sessions) || [];
  const standing = renderShotStanding(data && data.standing, { viewer });
  if (!rows.length) {
    return '<p class="small muted">No timed shooting sessions yet. Shot speed '
      + 'comes from the Shooting drill with the microphone on.</p>';
  }
  const best = Math.max(...rows.map((r) => r.best_mph || 0));
  const body = rows.map((r) => {
    const day = (r.completed_at || '').slice(0, 10);
    const hands = r.by_hand || {};
    const split = hands.left && hands.right
      ? ` &middot; L ${Math.round(hands.left)} / R ${Math.round(hands.right)}` : '';
    return `<tr>
      <td class="small muted">${esc(day)}</td>
      <td class="num"><b>${Math.round(r.median_mph)}</b> <span class="small muted">typical</span></td>
      <td class="num">${Math.round(r.best_mph)}${r.best_mph === best ? ' &#9733;' : ''}
        <span class="small muted">best</span></td>
      <td class="small muted">${r.timed}/${r.shots} timed &middot; ${r.distance_yd} yd${split}</td>
    </tr>`;
  }).join('');
  const limits = ((data && data.limits) || []).map((l) => `<li>${esc(l)}</li>`).join('');
  return `${standing}<table style="margin-top:8px"><tbody>${body}</tbody></table>
    <p class="small muted" style="margin:8px 0 0">All speeds in mph, approximate.
    Compare a session with earlier ones from the same distance.</p>
    <ul class="small muted" style="margin:4px 0 0;padding-left:18px">${limits}</ul>`;
}

/**
 * Where an athlete's shot speed sits: a percentile among teammates, and among
 * same-age athletes nationally once there are enough of them. Only this
 * athlete's own percentile -- never anyone else's speed, name or rank.
 *
 * A percentile is drawn as a marker on a plain bar, worded as "faster than
 * about N% of ...". When a group is too small to say anything without
 * identifying the other kids in it, it says so instead.
 */
export function renderShotStanding(s, { viewer = 'athlete' } = {}) {
  if (!s || s.speed_mph === null || s.speed_mph === undefined) return '';
  // Worded for whoever is looking: "you" to the athlete, "they" to a parent
  // or coach reading about someone else's child.
  const own = viewer === 'athlete';
  const bar = (pct) => `<div class="pct-bar" role="img"
      aria-label="Faster than about ${pct}%"><i style="left:${pct}%"></i></div>`;
  const line = (label, g, groupWord) => {
    if (g.available) {
      return `<div class="pct-row"><div class="small"><b>${label}</b>
        <span class="muted">faster than about ${g.percentile}% of ${groupWord}</span></div>
        ${bar(g.percentile)}</div>`;
    }
    const more = Math.max(0, (g.needed || 0) - (g.peers || 0));
    return `<div class="pct-row"><div class="small"><b>${label}</b>
      <span class="muted">shows once ${more} more ${groupWord} ${more === 1 ? 'has' : 'have'}
      a timed session, so it never points at anyone.</span></div></div>`;
  };
  const age = s.age || {};
  const ageWord = age.birth_year ? `kids born in ${age.birth_year}` : 'kids the same age';
  return `<div class="pct-card">
    <div class="small muted">Best typical speed in the last ${s.window_days} days:
      <b>${Math.round(s.speed_mph)} mph</b></div>
    ${line(own ? 'On your team' : 'On their team', s.team || {}, 'teammates')}
    ${age.birth_year ? line('Across the country', age, ageWord) : ''}
    <div class="small muted" style="margin-top:6px">Rounded to the nearest 5%.
      No other player's name or speed is shown, here or anywhere.</div>
  </div>`;
}
