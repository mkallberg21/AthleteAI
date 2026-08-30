"""Screenshot the running coach dashboard for the program summaries.

Real captures rather than a drawn mock. A picture of a product a director has
not seen yet is a promise, and the honest version of that promise is the
software itself -- so these come from the app running against the demo seed.

    python3 scripts/seed_demo.py --db /tmp/demo.db
    OFFDAYS_DB_PATH=/tmp/demo.db python3 -m uvicorn offdays.api:app --port 8811
    python3 scripts/programs/capture_dashboard.py --token <coach token>

The seeder prints the tokens. Use the director's.

Two things are removed before capturing, and both are honest edits rather than
flattery. The sticky header is dropped because it renders over the panel being
photographed. The first-week onboarding checklist is dropped because it is
scaffolding for a coach setting up, not part of what a director is being shown
-- leaving it in would show a half-configured program.
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import textwrap

HERE = pathlib.Path(__file__).parent
SHOTS = HERE / "shots"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

SCRIPT = """
const {{ chromium }} = require('playwright');
(async () => {{
  const b = await chromium.launch({{ executablePath: {chrome!r} }});
  const p = await b.newPage({{ viewport: {{ width: 1120, height: 1400 }},
                               deviceScaleFactor: 2 }});
  const url = {url!r} + '/app/coach.html';
  await p.goto(url);
  await p.evaluate(t => localStorage.setItem('offdays.token', t), {token!r});
  await p.goto(url);
  await p.waitForTimeout(5000);
  await p.addStyleTag({{ content:
    'header,.topbar,[class*=sticky]{{position:static!important;display:none!important}}'
    + 'textarea{{height:auto!important;min-height:58px!important;font-size:13px!important}}' }});
  await p.evaluate(() => {{
    for (const h of document.querySelectorAll('h2,h3')) {{
      if (/Set up/i.test(h.textContent)) {{
        const c = h.closest('section,div,article'); if (c) c.remove();
      }}
    }}
  }});
  await p.waitForTimeout(500);

  // The dashboard down to the headline numbers.
  const bottom = await p.evaluate(() => {{
    const el = [...document.querySelectorAll('*')]
      .find(n => /TOTAL XP/i.test(n.textContent || '') && n.children.length === 0);
    const card = el && el.closest('div');
    return card ? card.getBoundingClientRect().bottom : 900;
  }});
  await p.evaluate(() => window.scrollTo(0, 0));
  await p.waitForTimeout(300);
  await p.screenshot({{ path: {dash!r},
    clip: {{ x: 0, y: 0, width: 1120, height: Math.ceil(bottom) + 14 }} }});

  // The nudge list, whole.
  const nudge = p.locator('div.card')
    .filter({{ has: p.locator('h2,h3', {{ hasText: 'Needs a nudge' }}) }}).last();
  await nudge.scrollIntoViewIfNeeded();
  await p.waitForTimeout(300);
  await nudge.screenshot({{ path: {nudge!r} }});

  // Recognition, trimmed to three milestones: the panel repeats the same
  // control six times and three carries the idea inside a page.
  await p.evaluate(() => {{
    const h = [...document.querySelectorAll('h2,h3')]
      .find(n => /Automatic recognition/.test(n.textContent));
    const card = h.closest('div.card');
    [...card.querySelectorAll('div.recog')].slice(3).forEach(r => r.remove());
    card.querySelectorAll('details').forEach(d => d.remove());
  }});
  await p.waitForTimeout(400);
  const recog = p.locator('div.card')
    .filter({{ has: p.locator('h2,h3', {{ hasText: 'Automatic recognition' }}) }}).last();
  await recog.scrollIntoViewIfNeeded();
  await p.waitForTimeout(300);
  await recog.screenshot({{ path: {recog!r} }});

  console.log('captured 3');
  await b.close();
}})();
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--token", required=True, help="a coach or director token")
    ap.add_argument("--url", default="http://127.0.0.1:8811")
    args = ap.parse_args()

    SHOTS.mkdir(exist_ok=True)
    js = SCRIPT.format(
        chrome=CHROME, url=args.url, token=args.token,
        dash=str(SHOTS / "dashboard.png"),
        nudge=str(SHOTS / "nudge.png"),
        recog=str(SHOTS / "recognition.png"),
    )
    # Run from the repo root so the local playwright install resolves.
    result = subprocess.run(
        ["node", "-e", js], cwd=HERE.parents[1], capture_output=True, text=True)
    if result.returncode:
        print(textwrap.indent(result.stderr[-800:], "  "), file=sys.stderr)
        return 1
    print(result.stdout.strip())
    for shot in sorted(SHOTS.glob("*.png")):
        print(f"  {shot.name:18} {shot.stat().st_size // 1024}KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
