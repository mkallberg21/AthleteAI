// "Sign in with an email and a password" for whoever is signed in by their link, and a parent's control over a child's.
//
// The proof of an address is the link we send to it, so this only asks for the address. Nothing here creates a login by
// itself. Used by capture.html (an athlete) and parent.html (a parent, and their children's logins).
import { api, esc } from './api.js';

const say = (el, text, bad = false) => { el.style.color = bad ? 'var(--danger)' : ''; el.textContent = text; };

// A signed-in person makes their own login.
export async function mountMyLogin(el, { who = 'you' } = {}) {
  let me;
  try { me = await api('/api/me/login'); } catch { return; }
  if (me.has_login) {
    el.innerHTML = `<p class="small">${who === 'you' ? 'You' : esc(who)} can sign in with <b>${esc(me.email)}</b> and a password.</p>`;
    return;
  }
  if (!me.mail) { el.innerHTML = ''; return; }
  el.innerHTML = `<p class="small muted">Sign in next time with an email and a password, with no link from anyone.
    Type an email address; we send it a link. Open it and choose a password.</p>
    <input type="email" data-ml-email autocomplete="email" placeholder="you@example.com">
    <button type="button" class="secondary inline" data-ml-go>Make my login</button>
    <div class="small" data-ml-msg role="status" style="margin-top:6px"></div>`;
  const msg = el.querySelector('[data-ml-msg]');
  el.querySelector('[data-ml-go]').addEventListener('click', async (ev) => {
    const email = el.querySelector('[data-ml-email]').value.trim();
    if (!email) return say(msg, 'Type an email address.', true);
    ev.target.disabled = true;
    try {
      const res = await api('/api/me/make-login', { method: 'POST', body: { email } });
      say(msg, res.sent ? `We sent a link to ${res.email}. Open it and choose a password.`
        : 'We could not send that email. Check the address and try again.', !res.sent);
    } catch (e) { say(msg, e.message || 'Could not make a login.', true); }
    finally { ev.target.disabled = false; }
  });
}

// A parent sees which of their children sign in by email, and can switch it off.
export async function mountChildLogins(el, athletes) {
  const rows = [];
  for (const a of athletes) {
    try {
      const s = await api(`/api/guardians/athlete-login/${a.athlete_id}`);
      if (s.has_login) rows.push({ id: a.athlete_id, name: (a.display_name || '').split(' ')[0] || 'Your athlete', email: s.email });
    } catch { /* not theirs to see */ }
  }
  if (!rows.length) { el.innerHTML = ''; return; }
  el.innerHTML = rows.map((r) => `<div class="small" style="margin-top:8px" data-kid-login="${r.id}">
      ${esc(r.name)} signs in with <b>${esc(r.email)}</b> and a password.
      <button type="button" class="tiny" data-kid-off="${r.id}">Turn off</button>
      <span data-kid-msg></span></div>`).join('');
  el.querySelectorAll('[data-kid-off]').forEach((b) => b.addEventListener('click', async () => {
    const row = el.querySelector(`[data-kid-login="${b.dataset.kidOff}"]`);
    if (!window.confirm('Turn off this email login? The sign-in link you sent still works.')) return;
    try {
      await api(`/api/guardians/athlete-login/${b.dataset.kidOff}`, { method: 'DELETE' });
      row.innerHTML = 'Turned off. The sign-in link you sent still works.';
    } catch (e) { row.querySelector('[data-kid-msg]').textContent = e.message || 'Could not turn it off.'; }
  }));
}
