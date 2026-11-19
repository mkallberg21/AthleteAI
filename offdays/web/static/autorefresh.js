// Keeps a page current without anyone pressing refresh.
//
// Every couple of minutes, while the page is open and in front of the person, it re-reads what the page shows. It never
// gets in the way: nothing happens while the tab is hidden or offline, while someone is typing or has just clicked, or
// while a dialog is open, so a half-written message or a form is never wiped. When the app itself has been updated
// (the server reports a different build) the page reloads once the person is idle, or offers a button if they are not.
//
// `decide` is the whole policy as a pure function, so it can be tested without a browser.

export const EVERY_MS = 120_000;      // "every couple of minutes"
export const QUIET_MS = 8_000;        // how long after the last click or keypress before the page may redraw

/** What to do on a tick: 'skip', 'refresh', 'reload' or 'banner'. */
export function decide({ hidden, online, running, editing, typed, recentlyActive, versionChanged }) {
  if (hidden || !online || running) return 'skip';
  if (versionChanged) return (editing || typed || recentlyActive) ? 'banner' : 'reload';
  if (editing || recentlyActive) return 'skip';
  return 'refresh';
}

const TEXTY = 'input:not([type=checkbox]):not([type=radio]):not([type=button]):not([type=submit]):not([type=date]):not([type=range]), textarea';

function isEditing(doc) {
  const el = doc.activeElement;
  if (el && el !== doc.body && el.matches && el.matches('input, textarea, select, [contenteditable=""], [contenteditable="true"]')) return true;
  return !!doc.querySelector('[role=dialog][aria-modal=true]:not([style*="display: none"]), #athlete-dd:not([style*="display: none"])');
}
// Words typed into a visible box and not yet sent: a reload would lose them.
function hasTyped(doc) {
  return [...doc.querySelectorAll(TEXTY)].some((e) => e.value && e.offsetParent !== null && !e.readOnly && e.type !== 'hidden');
}

async function buildOf() {
  try {
    const r = await fetch('/api/live', { cache: 'no-store' });
    if (!r.ok) return '';
    const j = await r.json();
    return j.git_sha || j.version || '';
  } catch { return ''; }
}

/**
 * Start keeping the page fresh. `refresh` re-reads and redraws; it should throw on failure (the next tick tries again) and
 * is never shown as an error. `dataToo: false` checks only for a new version (for pages where a redraw would be unwelcome).
 */
export function keepFresh(refresh, { everyMs = EVERY_MS, dataToo = true } = {}) {
  let lastAct = 0, running = false, lastRun = Date.now(), first = '', bannerUp = false, note = null;
  const act = () => { lastAct = Date.now(); };
  ['pointerdown', 'keydown', 'touchstart', 'wheel'].forEach((ev) => document.addEventListener(ev, act, { passive: true, capture: true }));

  function stamp() {
    if (!dataToo) return;
    if (!note) {
      note = document.createElement('div');
      note.id = 'fresh-note';
      note.className = 'small muted';
      note.style.cssText = 'position:fixed;right:10px;bottom:6px;opacity:.7;pointer-events:none;z-index:50';
      document.body.appendChild(note);
    }
    note.textContent = `Updated ${new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
  }
  function banner() {
    if (bannerUp) return;
    bannerUp = true;
    const b = document.createElement('div');
    b.id = 'fresh-banner';
    b.setAttribute('role', 'status');
    b.style.cssText = 'position:fixed;left:0;right:0;bottom:0;padding:10px 14px;background:var(--accent,#008BFD);color:#fff;text-align:center;z-index:9000';
    b.innerHTML = 'A new version of 0FFDAYS is ready. <button type="button" style="margin-left:8px;min-height:auto;padding:4px 10px">Update now</button>';
    b.querySelector('button').addEventListener('click', () => location.reload());
    document.body.appendChild(b);
  }

  async function tick() {
    const sha = await buildOf();
    if (!first && sha) first = sha;
    const action = decide({
      hidden: document.hidden, online: navigator.onLine !== false, running,
      editing: isEditing(document), typed: hasTyped(document),
      recentlyActive: Date.now() - lastAct < QUIET_MS,
      versionChanged: !!(first && sha && sha !== first),
    });
    if (action === 'reload') { location.reload(); return; }
    if (action === 'banner') { banner(); return; }
    if (action !== 'refresh' || !dataToo) return;
    running = true;
    try { await refresh(); lastRun = Date.now(); stamp(); } catch { /* try again next time; never an error on screen */ }
    finally { running = false; }
  }

  buildOf().then((s) => { if (s && !first) first = s; });
  const timer = setInterval(tick, everyMs);
  // Back to the tab after a while away: catch up now rather than waiting out the clock.
  document.addEventListener('visibilitychange', () => { if (!document.hidden && Date.now() - lastRun > 60_000) tick(); });
  window.addEventListener('online', () => tick());
  return { now: tick, stop: () => clearInterval(timer) };
}
