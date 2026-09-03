#!/usr/bin/env python3
"""The pilot brochure: a club's-eye case for running 0FFDAYS for a season.

Built as HTML and printed by headless Chromium, so the type is vector and the
screenshots are the real application rather than mockups. The alternative in
this repo, make_brochure.py, composites pages as 150dpi bitmaps with PIL --
which is why its text softens when a director zooms in, and why it cannot run
in an environment without PIL installed.

Everything factual in here is either computed from the code at build time or
is a screenshot of the running app. Nothing is a projected outcome: a pilot
proposal that opens with an invented "37% improvement" is one search away from
being embarrassing, and clubs that fund youth programs have seen it before.

    python scripts/pilot_brochure.py --shots <dir> --out <file.pdf>
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
STATIC = REPO / "offdays" / "web" / "static"
FONTS = REPO / "scripts" / "programs" / "fonts-inline.css"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def uri(path: pathlib.Path, webp: dict[str, str] | None = None) -> str:
    if webp and path.name in webp:
        return webp[path.name]
    return f"data:image/png;base64,{base64.b64encode(path.read_bytes()).decode()}"


def facts() -> dict[str, int]:
    """Numbers the brochure states, read from the code that defines them."""
    from offdays.drills import ALL_DRILLS, for_sport
    from offdays.positions import for_sport as positions_for

    return {
        "drills": len(ALL_DRILLS),
        "offered": len(for_sport("lacrosse")),
        "sports": len({d.sport for d in ALL_DRILLS} - {"general"}),
        "positions": len(positions_for("lacrosse")),
    }


STYLE = """
/* The club's colours lead, since the document is addressed to them; 0FFDAYS
   blue is the accent and carries the data. Sampled from the crest itself. */
:root {
  --navy: #22395F; --navy-deep: #16273F; --crest-navy: #2E4B7F;
  --red: #A5292B; --stone: #D2D4D6;
  --ink: #101B2B; --body: #46566A; --faint: #8494A6;
  --accent: #008BFD; --paper: #FFFFFF; --rule: #E1E6EC;
  --head: "Barlow Condensed", "Arial Narrow", sans-serif;
  --text: "Inter", system-ui, sans-serif;
}
* { box-sizing: border-box; }
body {
  margin: 0; font-family: var(--text); color: var(--ink); background: var(--paper);
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
@page { size: Letter portrait; margin: 0; }

.page {
  width: 8.5in; height: 11in; position: relative; overflow: hidden;
  break-after: page; padding: 0.72in 0.78in; display: flex; flex-direction: column;
}
.page:last-child { break-after: auto; }
.dark { background: var(--navy-deep); color: #EAF1F8; }
.dark .lede, .dark p { color: #B9CADB; }

h1 { font-family: var(--head); font-weight: 700; font-size: 54pt; line-height: .96;
     margin: 0; letter-spacing: -.005em; text-wrap: balance; }
h2 { font-family: var(--head); font-weight: 700; font-size: 30pt; line-height: 1.02;
     margin: 0 0 10px; text-wrap: balance; }
h3 { font-family: var(--head); font-weight: 600; font-size: 15pt; margin: 0 0 5px; }
p  { font-size: 11pt; line-height: 1.6; color: var(--body); margin: 0 0 11px;
     max-width: 34em; }
.lede { font-size: 13.5pt; line-height: 1.5; color: var(--ink); max-width: 30em; }

.eyebrow {
  font-family: var(--head); font-size: 11pt; font-weight: 600; letter-spacing: .18em;
  text-transform: uppercase; color: var(--accent); margin: 0 0 12px;
}
.dark .eyebrow { color: #6FC0FF; }
.rule { height: 3px; width: 54px; background: var(--red); margin: 0 0 18px; }

/* Cover */
.cover { justify-content: space-between; padding: 0.9in 0.85in; }
.cover-marks { display: flex; align-items: center; gap: 26px; }
.cover-marks .crest { height: 1.35in; }
.cover-marks .bar { width: 1px; height: 1in; background: rgba(255,255,255,.22); }
.cover-marks .lockup { width: 1.5in; }
.cover h1 { font-size: 66pt; color: #fff; }
.cover .sub { font-size: 13.5pt; color: #A9C0D6; max-width: 26em; margin-top: 16px;
              line-height: 1.5; }
.cover .foot { font-size: 9.5pt; color: #7B90A6; letter-spacing: .04em; }

/* A screenshot, framed so it reads as a photograph of a screen. */
figure { margin: 0; }
figure img {
  width: 100%; display: block; border-radius: 7px; border: 1px solid var(--rule);
}
.dark figure img { border-color: rgba(255,255,255,.14); }
figcaption { font-size: 8.8pt; color: var(--faint); margin-top: 7px; letter-spacing: .02em; }
.shots-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.tall img { width: auto; max-width: 100%; max-height: 5.9in; margin: 0 auto; }

/* Three-up points */
.points { display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; margin-top: 6px; }
.points p { font-size: 9.8pt; margin: 0; }
.points .n {
  font-family: var(--head); font-size: 12pt; font-weight: 700; color: var(--red);
  letter-spacing: .12em; margin-bottom: 6px;
}
.dark .points .n { color: #FF8A8C; }

/* A figure worth reading as a figure */
.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 4px 0 0; }
.stat { border-top: 2px solid var(--accent); padding-top: 10px; }
.stat b { font-family: var(--head); font-size: 27pt; font-weight: 700; display: block;
          line-height: 1; color: var(--ink); font-variant-numeric: tabular-nums; }
.dark .stat b { color: #fff; }
.stat span { font-size: 8.4pt; letter-spacing: .1em; text-transform: uppercase;
             color: var(--faint); }

/* The pilot timeline: real structure, so it is numbered. */
.weeks { border-top: 1px solid var(--rule); margin-top: 4px; }
.week { display: grid; grid-template-columns: 1.35in 1fr; gap: 18px;
        padding: 13px 0; border-bottom: 1px solid var(--rule); }
.week .when { font-family: var(--head); font-weight: 600; font-size: 13pt;
              color: var(--crest-navy); }
.week p { margin: 0; font-size: 9.8pt; }

.two { display: grid; grid-template-columns: 1fr 1fr; gap: 30px; }
.ask { border-left: 3px solid var(--stone); padding-left: 16px; }
.ask h3 { color: var(--crest-navy); }
.ask li { font-size: 9.8pt; color: var(--body); line-height: 1.5; margin-bottom: 6px; }
.ask ul { margin: 0; padding-left: 17px; }

.pull {
  font-family: var(--head); font-size: 21pt; line-height: 1.2; color: var(--ink);
  border-left: 3px solid var(--red); padding-left: 18px; margin: 6px 0 18px;
  max-width: 22em; font-weight: 600;
}
.dark .pull { color: #fff; }

.grow { flex: 1; min-height: 0; }
.pagenum { position: absolute; bottom: .42in; right: .78in; font-size: 8pt;
           color: var(--faint); letter-spacing: .1em; }
.dark .pagenum, .dark .footline { color: #5C7188; }
.footline { position: absolute; bottom: .42in; left: .78in; font-size: 8pt;
            color: var(--faint); letter-spacing: .06em; }
"""


def build(shots: pathlib.Path, webp: dict[str, str] | None) -> str:
    f = facts()
    crest = uri(STATIC / "teams" / "nashville-dogs.png")
    lockup = uri(STATIC / "offdays-lockup.png")
    shot = lambda name: uri(shots / name, webp)  # noqa: E731

    pages: list[str] = []
    add = pages.append

    # ---------------------------------------------------------------- cover
    add(f"""<section class="page dark cover">
      <div class="cover-marks">
        <img class="crest" src="{crest}" alt="Nashville Dogs">
        <div class="bar"></div>
        <img class="lockup" src="{lockup}" alt="0FFDAYS">
      </div>
      <div>
        <h1>The off days<br>are the season.</h1>
        <p class="sub">A pilot proposal for the Nashville Dogs — one squad,
        one season, and a way to see the work that happens between practices
        without asking a single child to upload a video of themselves.</p>
      </div>
      <div class="foot">PREPARED FOR JOEL WHITE · NASHVILLE DOGS · 2031 RED</div>
    </section>""")

    # ------------------------------------------------------------- the gap
    add(f"""<section class="page">
      <p class="eyebrow">The problem</p>
      <div class="rule"></div>
      <h2>You coach them for four hours a week.<br>Something happens in the other hundred.</h2>
      <p class="lede">Every coach knows which players put the work in on their
      own. Almost none of them can prove it, and none of them find out in time
      to do anything about it.</p>
      <p>The athlete who has quietly not touched a stick in twelve days looks
      identical to the one who has been out there every evening — until a game,
      by which point the gap has been growing for a fortnight. The athlete
      grinding out six hundred reps a week with their dominant hand only looks
      like the hardest worker on the roster, because in volume terms they are.
      And the one training seventeen days without a rest day looks like the most
      committed kid in the program right up to the week their elbow stops them.</p>
      <p>None of that is a coaching failure. It is missing information, and it
      is missing for a simple reason: nobody has been able to collect it without
      asking children to film themselves and send it somewhere.</p>
      <div class="grow"></div>
      <p class="pull" style="margin-bottom:34px">So we built the version that
      collects none of it.</p>
      <div class="stats">
        <div class="stat"><b>{f['drills']}</b><span>Drills in the library</span></div>
        <div class="stat"><b>{f['offered']}</b><span>Offered to a lacrosse squad</span></div>
        <div class="stat"><b>{f['positions']}</b><span>Lacrosse positions planned for</span></div>
        <div class="stat"><b>0</b><span>Videos uploaded, ever</span></div>
      </div>
      <div class="footline">0FFDAYS · PILOT PROPOSAL</div><div class="pagenum">2</div>
    </section>""")

    # ------------------------------------------------------------- privacy
    add(f"""<section class="page dark">
      <p class="eyebrow">Why this one is different</p>
      <div class="rule"></div>
      <h2 style="color:#fff">The video never leaves the phone.</h2>
      <p class="pull">Not "encrypted in transit". Not "deleted after 30 days".
      It is never sent.</p>
      <p>An athlete props their phone against a bag and records a wall-ball set.
      The pose analysis runs in the browser, on the device, while they train.
      What reaches the club is a row of numbers — how many reps, which hand,
      how consistent the tempo, how the range of motion held up as they tired.
      The footage stays in the camera buffer and is gone when the screen closes.</p>
      <p>This is enforced by the shape of the system rather than by a policy
      page: no endpoint in the product accepts a video file, and no column in
      the database stores one. A coach cannot request footage, because there is
      no mechanism by which they could receive it.</p>
      <p><b style="color:#fff">The one exception, stated plainly.</b> An athlete
      can choose to send a coach one specific clip for feedback — and only when
      a guardian has switched that permission on for that child. It is never
      automatic, it is one clip at a time, it expires, and withdrawing consent
      deletes it immediately. That is the whole of it.</p>
      <div class="grow"></div>
      <p style="font-size:9.6pt;color:#8FA8C0;max-width:38em">Every screenshot in
      this document is the running application with demonstration data — not a
      mockup, and not a rendering.</p>
      <div class="footline">0FFDAYS · PILOT PROPOSAL</div><div class="pagenum">3</div>
    </section>""")

    # ------------------------------------------------- Monday morning (c01)
    add(f"""<section class="page">
      <p class="eyebrow">What a director sees</p>
      <div class="rule"></div>
      <h2>Monday morning, before you have had coffee.</h2>
      <p>The first thing on the screen is not a chart to interpret. It is a
      short list of who to talk to today, and why. Joel signs in and sees the
      whole program; a coach signs in and sees only the squad they are assigned
      to — enforced on every request, not hidden in the page.</p>
      <figure>
        <img src="{shot('c01-program.png')}" alt="The director's dashboard">
        <figcaption>The director's view · 2031 Red · last 7 days</figcaption>
      </figure>
      <div class="grow"></div>
      <div class="points" style="margin-top:26px">
        <div><div class="n">01</div><p>Two or three names, with the reason
        beside each. Not a leaderboard of who trained most.</p></div>
        <div><div class="n">02</div><p>The line under the filters is on the
        product itself: no video reaches this screen, ever.</p></div>
        <div><div class="n">03</div><p>Assignment progress at a glance — who
        still has not started the week's work.</p></div>
      </div>
      <div class="footline">0FFDAYS · PILOT PROPOSAL</div><div class="pagenum">4</div>
    </section>""")

    # --------------------------------------------- who needs a text tonight
    add(f"""<section class="page">
      <p class="eyebrow">The two lists that matter</p>
      <div class="rule"></div>
      <h2>Training too little and training too much are both worth a call.</h2>
      <p>Most tools in this space only find the first. The pattern that precedes
      most overuse injuries in youth sport is a sharp jump in weekly load, and
      it is invisible without a baseline — which is exactly what six weeks of
      counted reps gives you.</p>
      <figure style="margin-bottom:16px">
        <img src="{shot('c04-needs-a-nudge.png')}" alt="Needs a nudge">
        <figcaption>Who has gone quiet, and for how long</figcaption>
      </figure>
      <figure>
        <img src="{shot('c05-workload-watch.png')}" alt="Workload watch">
        <figcaption>A sharp jump in weekly load, flagged before it becomes an injury</figcaption>
      </figure>
      <div class="footline">0FFDAYS · PILOT PROPOSAL</div><div class="pagenum">5</div>
    </section>""")

    # --------------------------------------------------------- the athlete
    add(f"""<section class="page">
      <p class="eyebrow">What the athlete sees</p>
      <div class="rule"></div>
      <h2>A ten-year-old opens it and knows what to do.</h2>
      <p>Their position's plan, the drill drawn before they attempt it, and a
      target they can actually hit. A child who has never heard of a given
      exercise is not left guessing at it — every drill in the library is
      demonstrated, and the goalies get goalie work rather than a midfielder's.</p>
      <div class="shots-2">
        <figure><img src="{shot('athlete-1-home.png')}" alt="Home screen">
          <figcaption>Their week, and a wellbeing check that never costs a streak</figcaption></figure>
        <figure><img src="{shot('athlete-2-pick-a-drill.png')}" alt="Pick a drill">
          <figcaption>What the position plan actually asks for</figcaption></figure>
      </div>
      <div class="footline">0FFDAYS · PILOT PROPOSAL</div><div class="pagenum">6</div>
    </section>""")

    add(f"""<section class="page">
      <p class="eyebrow">What the athlete sees</p>
      <div class="rule"></div>
      <h2>The rep is counted where it happens.</h2>
      <div class="shots-2">
        <figure><img src="{shot('athlete-3-wall-ball.png')}" alt="A drill">
          <figcaption>The movement, drawn, before they start</figcaption></figure>
        <figure><img src="{shot('athlete-4-good-rep.png')}" alt="What a good rep looks like">
          <figcaption>Target range and tempo, from the same numbers the counter scores against</figcaption></figure>
      </div>
      <p style="margin-top:20px">The counter runs against a declarative spec —
      the same definition the server re-checks the submission against, so a
      session that could not physically have happened does not become a number
      on a coach's screen. Reps the counter was unsure about are held back for
      a human rather than quietly scored.</p>
      <div class="footline">0FFDAYS · PILOT PROPOSAL</div><div class="pagenum">7</div>
    </section>""")

    # ---------------------------------------------------------- lacrosse IQ
    add(f"""<section class="page">
      <p class="eyebrow">The other half of the game</p>
      <div class="rule"></div>
      <h2>Lacrosse IQ, and who has actually watched it.</h2>
      <p>Reps build hands. Watching builds the rest — reading a slide, seeing a
      cut two passes early. Short clips, curated by your staff, capped by age
      so it cannot become forty minutes of screen time dressed up as training.</p>
      <figure>
        <img src="{shot('c18-sport-iq.png')}" alt="Lacrosse IQ coverage">
        <figcaption>Grouped by clip, never by athlete — coverage, not compliance</figcaption>
      </figure>
      <div class="footline">0FFDAYS · PILOT PROPOSAL</div><div class="pagenum">8</div>
    </section>""")

    # ------------------------------------------------------- anti-burnout
    add(f"""<section class="page dark">
      <p class="eyebrow">Deliberately counter-weighted</p>
      <div class="rule"></div>
      <h2 style="color:#fff">The gamification is built to argue with itself.</h2>
      <p class="pull">A streak that punishes a rest day is a machine for
      producing hurt children.</p>
      <p>Points, levels and streaks are in here because they work on
      twelve-year-olds. Every one of them is bounded by something that pushes
      the other way. A wellbeing check never costs a streak. A planned absence
      pauses it rather than breaking it. "Needs a rest day" sits in the same
      list as "quiet for ten days", because both are a conversation. Standings
      are per athlete rather than per team total, so a bigger squad cannot win
      by being bigger — and the squad has one collective number to chase
      instead of a table that ranks eleven-year-olds against their friends.</p>
      <p>Recognition messages are drawn from a pool wide enough that no two
      athletes get the same sentence inside a month. The first thing two
      teammates do is compare phones, and a coach whose praise turns out to be
      a template loses something they do not get back.</p>
      <div class="grow"></div>
      <figure><img src="{shot('c11-team-goal.png')}" alt="Team goal">
        <figcaption>One number the squad chases together</figcaption></figure>
      <div class="footline">0FFDAYS · PILOT PROPOSAL</div><div class="pagenum">9</div>
    </section>""")

    # ------------------------------------------------------------- parents
    add(f"""<section class="page">
      <p class="eyebrow">Parents</p>
      <div class="rule"></div>
      <h2>What a parent is shown, and what they are not.</h2>
      <p>Participation and wellbeing. No footage, and no ranking of their child
      against other people's children. Consent is a switch a guardian holds,
      it is off until they turn it on, and an athlete whose guardian has not
      consented appears on the leaderboard without their name.</p>
      <figure class="tall">
        <img src="{shot('c17-parent.png')}" alt="The parent view">
        <figcaption>The guardian's view of one athlete</figcaption>
      </figure>
      <div class="footline">0FFDAYS · PILOT PROPOSAL</div><div class="pagenum">10</div>
    </section>""")

    # ---------------------------------------------------------- the pilot
    add("""<section class="page">
      <p class="eyebrow">The pilot</p>
      <div class="rule"></div>
      <h2>One squad. One season. No club-wide commitment.</h2>
      <p class="lede">2031 Red is the right size to learn something from and
      small enough that nothing breaks if it does not suit you.</p>
      <div class="weeks">
        <div class="week"><div class="when">Before week 1</div>
          <p>We load your roster, set the season phase, and put your crest on
          it. Nothing to install — it runs in a phone's browser and can be
          added to a home screen.</p></div>
        <div class="week"><div class="when">Week 1</div>
          <p>Fifteen minutes with the coaching staff, and a note home to
          guardians explaining what is and is not collected. Consent is
          gathered before any athlete is on the board.</p></div>
        <div class="week"><div class="when">Weeks 2&ndash;3</div>
          <p>Athletes record their own off-day work. We watch for the boring
          failure modes — a phone propped where it cannot see, a drill that
          needs its target adjusted for this age group.</p></div>
        <div class="week"><div class="when">Weeks 4&ndash;8</div>
          <p>Assignments, film, and the pre-practice list in ordinary use. By
          now the workload baseline is real enough that the load flags mean
          something.</p></div>
        <div class="week"><div class="when">End of the pilot</div>
          <p>You get a written read on what the squad actually did, and the
          full data export. If you walk away, you take it with you.</p></div>
      </div>
      <div class="grow"></div>
      <p class="pull">Nothing to install. Nothing to buy. One squad.</p>
      <div class="footline">0FFDAYS · PILOT PROPOSAL</div><div class="pagenum">11</div>
    </section>""")

    add("""<section class="page">
      <p class="eyebrow">Terms</p>
      <div class="rule"></div>
      <h2>What we need, and what you get.</h2>
      <div class="two">
        <div class="ask">
          <h3>From the Dogs</h3>
          <ul>
            <li>One squad — 2031 Red.</li>
            <li>A roster with birth years and positions, in any format you already keep it.</li>
            <li>Fifteen minutes of a coaches' meeting to introduce it.</li>
            <li>One member of staff as the point of contact.</li>
            <li>Honest feedback, including the parts you dislike.</li>
          </ul>
        </div>
        <div class="ask">
          <h3>From us</h3>
          <ul>
            <li>The platform for the full pilot season, at no cost.</li>
            <li>Your crest on every screen a Dogs family sees.</li>
            <li>Setup, roster import and guardian consent handled.</li>
            <li>A film shelf built for your age group with your staff.</li>
            <li>Your data, exportable in full, at any point, including if you leave.</li>
          </ul>
        </div>
      </div>
      <div class="grow"></div>
      <figure><img src="%s" alt="Assignments">
        <figcaption>An assignment set for the squad, and who has finished it</figcaption></figure>
      <div class="footline">0FFDAYS · PILOT PROPOSAL</div><div class="pagenum">12</div>
    </section>""" % shot("c07-assignments.png"))

    # ------------------------------------------------------- honest limits
    add("""<section class="page">
      <p class="eyebrow">Before you say yes</p>
      <div class="rule"></div>
      <h2>What this does not do.</h2>
      <p class="lede">Every product in youth sport is sold on what it promises.
      This is the list we would want if we were the ones signing.</p>
      <div class="points" style="margin-top:22px">
        <div><div class="n">NOT</div><p><b>It does not coach.</b> It counts
        reps and shows patterns. Deciding what to do about a pattern is the job
        you already have and it is not being automated.</p></div>
        <div><div class="n">NOT</div><p><b>It does not watch a game.</b> Nothing
        here scores a save, a dodge or a decision under pressure. It measures
        solo, repeatable work.</p></div>
        <div><div class="n">NOT</div><p><b>It is not medical.</b> The load flags
        are a prompt for a conversation, not a diagnosis, and the app says so
        wherever it raises one.</p></div>
      </div>
      <div class="grow"></div>
      <div class="ask" style="margin-top:24px">
        <h3 style="color:var(--crest-navy)">And two things that are simply true today</h3>
        <p>A handful of drills still need a filmed demonstration rather than the
        drawn one, and we would film those with your athletes during the pilot.
        The calibration set behind the counters was built on adult and
        late-teen movement; a season with a 2031 age group is exactly what
        makes it right for thirteen-year-olds, and that is part of why we are
        asking you.</p>
      </div>
      <div class="footline">0FFDAYS · PILOT PROPOSAL</div><div class="pagenum">13</div>
    </section>""")

    # ------------------------------------------------------------- closing
    add(f"""<section class="page dark cover">
      <div class="cover-marks">
        <img class="crest" src="{crest}" alt="Nashville Dogs">
        <div class="bar"></div>
        <img class="lockup" src="{lockup}" alt="0FFDAYS">
      </div>
      <div>
        <h1 style="font-size:46pt">Let's run it for<br>one squad and see.</h1>
        <p class="sub">If it earns its place with 2031 Red over a season, the
        rest of the program is a conversation worth having. If it does not, you
        have lost a roster import and a coaches' meeting.</p>
      </div>
      <div class="foot">NASHVILLE DOGS &middot; 2031 RED &middot; PILOT PROPOSAL</div>
    </section>""")

    fonts = FONTS.read_text()
    return (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>Nashville Dogs — 0FFDAYS pilot</title>"
        f"<style>{fonts}{STYLE}</style></head><body>{''.join(pages)}</body></html>"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--webp", type=pathlib.Path,
                    help="optional {filename: data-uri} map, for smaller files")
    args = ap.parse_args()

    webp = json.loads(args.webp.read_text()) if args.webp and args.webp.exists() else None
    html = build(args.shots, webp)
    src = args.out.with_suffix(".html")
    src.write_text(html)
    subprocess.run(
        # The fonts and images are inlined, so the render needs no network at
        # all -- and a headless browser left to itself will still reach for
        # component updates and telemetry on the way past.
        [CHROME, "--headless", "--no-sandbox", "--disable-gpu",
         "--disable-background-networking", "--disable-sync", "--no-first-run",
         "--no-default-browser-check", "--disable-component-update",
         "--no-pdf-header-footer", f"--print-to-pdf={args.out}", src.as_uri()],
        check=True, capture_output=True,
    )
    print(f"{args.out}  {args.out.stat().st_size // 1024}KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
