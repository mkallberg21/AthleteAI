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
  const badge = brand.logo
    ? `<img class="club-badge" src="${brand.logo}" alt="${brand.name}">` : "";
  const name = brand.logo ? "" : `<div class="club-name">${esc(brand.name)}</div>`;
  // The full lockup at exactly the 120px the brand guidelines set as its
  // minimum -- below that they say to use the bare mark instead, and this is
  // the smallest the wordmark is allowed to be. The club's badge is sized
  // larger than it so the program still leads its own header.
  // Both marks ship and CSS chooses: the lockup where there is room for it at
  // its 120px minimum, the bare glyph where there is not. The guidelines are
  // explicit that the answer to a narrow header is the mark, never a smaller
  // lockup, so a phone gets the glyph rather than a squeezed wordmark.
  el.innerHTML = `<div class="masthead">${badge}<div class="stack">
    <img class="offdays-lockup" src="offdays-lockup.png" alt="0FFDAYS">
    <img class="offdays-mark" src="offdays-mark.png" alt="0FFDAYS">
    ${name}${subtitle ? `<div class="role">${esc(subtitle)}</div>` : ""}
    </div></div>`;
  return brand;
}
