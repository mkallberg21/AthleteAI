#!/usr/bin/env python3
"""Add a Phone / Web view switch and a full-screen button to the published decks.

    python scripts/programs/viewmode.py docs/index.html docs/tennessee/index.html

The decks in docs/ are single self-contained HTML files. Their generator does
not live in this repo, so this is applied to the built files and is safe to run
again after a rebuild: it replaces its own marked block rather than adding a
second one.

What it adds, for walking a club through the deck on a shared screen:

* **Phone view** -- the deck as a family sees it, in a phone-sized frame with
  its own scroll, so a laptop on a Teams call shows what a phone shows.
* **Web view** -- the same deck laid out for a wide screen: the four roles in a
  row, and each screen beside its caption at the full height of the window
  instead of a long scroll.
* **Full screen** -- hides the browser's own chrome. F toggles it; the arrow
  keys step through a role's screens, so the presenter never has to find the
  Next button.

The choice is remembered per browser, and ?view=phone or ?view=web in the
link forces one. On a real phone neither control is shown: the page is already
a phone page there, and phones mostly cannot full-screen a page anyway.
"""
from __future__ import annotations

import pathlib
import re
import sys

BEGIN, END = "<!-- viewmode:begin -->", "<!-- viewmode:end -->"

STYLE = """
<style id="viewmode-style">
.vm-bar { position:fixed; top:12px; right:12px; z-index:50; display:flex; gap:6px;
          align-items:center; padding:5px; border-radius:12px;
          background:rgba(12,24,38,.88); border:1px solid var(--edge);
          backdrop-filter:blur(6px); opacity:.6; transition:opacity .15s; }
.vm-bar:hover, .vm-bar:focus-within { opacity:1; }
.vm-bar button { font:inherit; font-size:.8rem; font-weight:600; cursor:pointer;
                 color:var(--muted); background:transparent; border:0;
                 border-radius:8px; padding:7px 11px; }
.vm-bar button[aria-pressed="true"] { background:var(--accent); color:#04121F; }
.vm-bar .vm-sep { width:1px; align-self:stretch; background:var(--edge); margin:2px 2px; }
.vm-hint { font-size:.7rem; color:var(--faint); padding:0 6px; }
@media (max-width:699px) { .vm-bar { display:none; } }

/* ---- phone view on a wide screen: a phone in the middle of the window ---- */
@media (min-width:700px) {
  body.vm-phone { background:#070F19; }
  body.vm-phone .wrap {
    max-width:420px; height:min(880px, calc(100vh - 40px)); margin:20px auto;
    overflow-y:auto; overscroll-behavior:contain; background:var(--night);
    border:11px solid #020509; border-radius:46px;
    box-shadow:0 0 0 1px #2A3B50, 0 30px 80px rgba(0,0,0,.55);
    scrollbar-width:none;
  }
  body.vm-phone .wrap::-webkit-scrollbar { display:none; }
  /* The deck's own breakpoints read the window, not the phone. */
  body.vm-phone .roles { grid-template-columns:1fr !important; }
}

/* ---- web view: the same deck laid out for a wide shared screen ----
   The screenshots run from a single wide card to a whole scrolling page, so the
   screen sits in its own scroll box at a readable width and the caption stays
   beside it rather than being pushed off the bottom. */
@media (min-width:700px) {
  body.vm-web .wrap { max-width:1280px; padding:0 40px 64px; }
  body.vm-web p { max-width:46em; }
  body.vm-web .roles { grid-template-columns:repeat(4, 1fr); }
  body.vm-web .roleview .frame {
    display:grid; grid-template-columns:minmax(0, 1.7fr) minmax(260px, 1fr);
    grid-template-rows:auto auto auto 1fr; column-gap:32px; align-items:start;
    padding:20px;
  }
  body.vm-web .roleview .vm-shot {
    grid-row:1 / -1; max-height:calc(100vh - 130px); min-height:360px;
    overflow-y:auto; border-radius:10px; border:1px solid var(--edge);
    background:var(--night); scrollbar-width:thin;
  }
  body.vm-web .roleview .vm-shot img { border:0; border-radius:0; }
  body.vm-web .roleview .cap b { font-size:1.9rem; margin-top:2px; line-height:1.1; }
  body.vm-web .roleview .cap span { font-size:1.08rem; margin-top:10px; }
  body.vm-web .roleview .dots { margin-top:22px; }
  body.vm-web .roleview .nav { margin-top:16px; }
  body.vm-web .roleview .nav button { font-size:1.02rem; padding:12px 18px; }
}
:fullscreen body.vm-web .roleview .vm-shot { max-height:calc(100vh - 90px); }
</style>
"""

BAR_AND_SCRIPT = """
<div class="vm-bar" role="toolbar" aria-label="View">
  <button type="button" data-vm="phone" aria-pressed="false" title="Show it on a phone">Phone</button>
  <button type="button" data-vm="web" aria-pressed="false" title="Lay it out for a wide screen">Web</button>
  <span class="vm-sep"></span>
  <button type="button" data-vm-fs title="Full screen (F)">Full screen</button>
</div>
<script>
(() => {
  const KEY = 'offdays.deck.view';
  const body = document.body;
  const wrap = document.querySelector('.wrap');
  const forced = new URLSearchParams(location.search).get('view');
  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) { /* private mode */ }

  function setView(v) {
    body.classList.toggle('vm-phone', v === 'phone');
    body.classList.toggle('vm-web', v === 'web');
    document.querySelectorAll('[data-vm]').forEach((b) =>
      b.setAttribute('aria-pressed', String(b.dataset.vm === v)));
    try { localStorage.setItem(KEY, v); } catch (e) { /* private mode */ }
  }
  setView(forced === 'phone' || forced === 'web' ? forced
    : saved === 'phone' || saved === 'web' ? saved : 'web');

  document.querySelectorAll('[data-vm]').forEach((b) =>
    b.addEventListener('click', () => setView(b.dataset.vm)));

  // Each screenshot gets its own scroll box (used by web view), and a new
  // screen starts at its top rather than wherever the last one was left.
  document.querySelectorAll('.roleview [data-screen]').forEach((img) => {
    const box = document.createElement('div');
    box.className = 'vm-shot';
    img.parentNode.insertBefore(box, img);
    box.appendChild(img);
    new MutationObserver(() => { box.scrollTop = 0; })
      .observe(img, { attributes: true, attributeFilter: ['src'] });
  });

  // In phone view the phone scrolls, not the window, so a change of role has
  // to bring the phone back to the top the way the deck does for the window.
  window.addEventListener('hashchange', () => { if (wrap) wrap.scrollTop = 0; });

  const fsBtn = document.querySelector('[data-vm-fs]');
  const root = document.documentElement;
  const canFull = !!(root.requestFullscreen || root.webkitRequestFullscreen);
  const isFull = () => !!(document.fullscreenElement || document.webkitFullscreenElement);
  function toggleFull() {
    if (isFull()) (document.exitFullscreen || document.webkitExitFullscreen).call(document);
    else (root.requestFullscreen || root.webkitRequestFullscreen).call(root);
  }
  function label() { fsBtn.textContent = isFull() ? 'Exit full screen' : 'Full screen'; }
  if (!canFull) fsBtn.hidden = true;
  fsBtn.addEventListener('click', toggleFull);
  document.addEventListener('fullscreenchange', label);
  document.addEventListener('webkitfullscreenchange', label);

  // Presenter keys: F for full screen, arrows to step through a role.
  document.addEventListener('keydown', (e) => {
    if (e.target.closest && e.target.closest('input, textarea, select')) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if ((e.key === 'f' || e.key === 'F') && canFull) { e.preventDefault(); toggleFull(); return; }
    const view = document.querySelector('.roleview.on');
    if (!view) return;
    const dir = e.key === 'ArrowRight' ? '1' : e.key === 'ArrowLeft' ? '-1' : null;
    if (!dir) return;
    const btn = view.querySelector('[data-step="' + dir + '"]');
    if (btn && !btn.disabled) { e.preventDefault(); btn.click(); }
  });
})();
</script>
"""


def apply(path: pathlib.Path) -> None:
    html = path.read_text(encoding="utf-8")
    # Strip a previous run, so this can be applied again after a rebuild.
    html = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\s*", "", html, flags=re.S)
    if "</head>" not in html or "</body>" not in html:
        raise SystemExit(f"{path}: no </head> or </body> to attach to")
    html = html.replace("</head>", f"{BEGIN}{STYLE}{END}\n</head>", 1)
    i = html.rindex("</body>")
    html = html[:i] + f"{BEGIN}{BAR_AND_SCRIPT}{END}\n" + html[i:]
    path.write_text(html, encoding="utf-8", newline="")
    print(f"view switch added: {path}")


if __name__ == "__main__":
    for arg in sys.argv[1:] or ["docs/index.html", "docs/tennessee/index.html"]:
        apply(pathlib.Path(arg))
