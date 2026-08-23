/** Thin API client. Token lives in localStorage; nothing else is persisted. */

const TOKEN_KEY = 'athleteiq.token';

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(t) {
  try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
}
export function logout() { setToken(null); location.href = '/app/index.html'; }

export async function api(path, { method = 'GET', body } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

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
  return res.status === 204 ? null : res.json();
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
