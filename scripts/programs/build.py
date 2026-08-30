"""Build one director-facing PDF per sport.

The audience is the person who runs the program -- a club director, an
athletic director, a head coach with a budget -- not an engineer. So the
order is theirs: what their athletes do, what they get to see, what it
protects them from, and what it honestly cannot do yet.

Every count, share and drill name comes from sports.json, which is read out of
the shipped catalog. Nothing here is typed by hand except the prose.
"""
import base64, html, json, pathlib, subprocess, sys

HERE = pathlib.Path(__file__).parent
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
_FONT_FILE = HERE / "fonts-inline.css"
if not _FONT_FILE.exists():
    raise SystemExit("run fetch_fonts.py first -- the faces must be inlined, "
                     "because Chromium renders these with no network")
FONTS = _FONT_FILE.read_text()

def e(s):
    """Escape, and promote the catalog's ASCII dashes to real em dashes."""
    return html.escape(str(s)).replace(" -- ", " \u2014 ")


#: Preset keys are internal names. A director reads the ball, not the table.
COLOUR_WORDS = {
    "white": "white",
    "yellow": "hi-vis yellow",
    "orange": "orange",
    "optic": "optic yellow",
    "lime": "neon lime",
    "basketball": "standard orange",
    "volleyball": "the blue-and-yellow competition pattern",
}


def logo_block():
    """The user's logo if it is here, the wordmark if it is not.

    Dropping logo.svg or logo.png into this directory is the whole install.
    """
    for name in ("logo.svg", "logo.png", "logo.jpg", "logo.webp"):
        path = HERE / name
        if not path.exists():
            continue
        if name.endswith(".svg"):
            mime = "image/svg+xml"
        elif name.endswith(".png"):
            mime = "image/png"
        elif name.endswith(".webp"):
            mime = "image/webp"
        else:
            mime = "image/jpeg"
        b64 = base64.b64encode(path.read_bytes()).decode()
        return (f'<img class="logo-img" alt="0FFDAYS" '
                f'src="data:{mime};base64,{b64}">'), True
    return '<div class="wordmark">0FFDAYS</div>', False


CSS = """
@page { size: Letter; margin: 0.62in 0.6in 0.72in; }
@page :first { margin: 0 0 0.72in; }
* { box-sizing: border-box; }
:root {
  --ground:#F9F6F2; --surface:#FFFFFF; --surface-sunk:#F1EBE3;
  --ink:#1E1712; --ink-soft:#5A4E44; --ink-faint:#8A7D71;
  --rule:#E3DAD0; --rule-strong:#C7B9AB;
  --accent:#8A4A1C; --accent-ink:#65330F; --accent-wash:#F5E4D4;
  --gold:#8A6118; --gold-wash:#F2E9D6;
  --go:#2C6449; --go-wash:#E4EFE8;
  --warn:#8E5A11; --stop:#97301F; --stop-wash:#F7E6E2;
}
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"Source Serif 4", Georgia, serif; font-size:10.1pt; line-height:1.52;
}
h1,h2,h3,h4,.num,.eyebrow,.wordmark,th,.tile-n,.pill {
  font-family:"Bricolage Grotesque","Helvetica Neue",Arial,sans-serif;
}
.mono,code,.metric { font-family:"IBM Plex Mono",monospace; }

/* ---------- cover ---------- */
.cover { background:#171310; color:#F4EDE6; padding:0.8in 0.6in 0.5in;
  position:relative; overflow:hidden;
  /* Owns page one outright. Without the break the first section flows up
     underneath the cover art, and @page:first has no side margins for it. */
  min-height:10.2in; break-after:page;
  display:flex; flex-direction:column; }
.cover::after { content:""; position:absolute; inset:0;
  background:linear-gradient(104deg,#8A4A1C 0%,#B4692C 42%,#8A6118 100%);
  opacity:.30;
  -webkit-mask-image:linear-gradient(104deg,transparent 40%,#000 100%);
          mask-image:linear-gradient(104deg,transparent 40%,#000 100%); }
.cover > * { position:relative; z-index:1; }
.wordmark { font-weight:800; font-size:23pt; letter-spacing:-.045em; color:#FFF; }
.logo-img { height:46px; width:auto; display:block; }
.cover-head { display:flex; justify-content:space-between; align-items:flex-start;
  border-bottom:1px solid rgba(255,255,255,.17); padding-bottom:14px; }
.cover-head .meta { text-align:right; font-size:8pt; color:#C9B9A9;
  font-family:"IBM Plex Mono",monospace; line-height:1.7; }
.cover h1 { font-size:41pt; line-height:.98; margin:30px 0 0;
  letter-spacing:-.032em; font-weight:800; color:#FFF; }
.cover .kicker { font-size:9pt; letter-spacing:.17em; text-transform:uppercase;
  color:#E8BE93; font-weight:600;
  font-family:"Bricolage Grotesque",sans-serif; }
.cover .thesis { font-size:14.6pt; line-height:1.4; color:#EADFD4;
  margin:16px 0 0; max-width:6.7in; text-wrap:pretty; }
.cover .thesis strong { color:#FFF; font-weight:600; }
.tiles { display:grid; grid-template-columns:repeat(4,1fr); gap:9px;
  margin-top:30px; }
.tile { background:rgba(255,255,255,.075); border:1px solid rgba(255,255,255,.14);
  border-radius:9px; padding:11px 12px 12px; }
.tile-n { font-size:21pt; font-weight:800; color:#FFF; letter-spacing:-.03em;
  line-height:1; }
.tile-l { font-size:7.6pt; color:#C7B5A4; margin-top:5px; line-height:1.35;
  text-transform:uppercase; letter-spacing:.055em;
  font-family:"Bricolage Grotesque",sans-serif; font-weight:500; }
.claim { margin:auto 0; padding:26px 0 6px; }
.claim q { quotes:none; display:block; font-family:"Bricolage Grotesque",sans-serif;
  font-size:27pt; font-weight:800; letter-spacing:-.028em; line-height:1.1;
  color:#FFF; max-width:6.6in; }
.claim q em { font-style:normal; color:#E8BE93; }
.claim .sub { margin-top:11px; font-size:9.6pt; color:#B7A697; max-width:5.4in; }
.steps { padding-top:34px; display:grid;
  grid-template-columns:repeat(3,1fr); gap:16px; }
.step { border-top:2px solid rgba(232,190,147,.5); padding-top:11px; }
.step .n { font-family:"IBM Plex Mono",monospace; font-size:8pt;
  color:#E8BE93; letter-spacing:.1em; }
.step h4 { font-family:"Bricolage Grotesque",sans-serif; font-size:11.2pt;
  margin:5px 0 4px; color:#FFF; font-weight:700; letter-spacing:-.012em; }
.step p { font-size:9.1pt; color:#BCAB9C; margin:0; line-height:1.42; }
.roster { margin-top:28px; padding-top:15px;
  border-top:1px solid rgba(255,255,255,.17); }
.roster .lbl { font-size:7.6pt; letter-spacing:.15em; text-transform:uppercase;
  color:#9C8B7C; font-family:"Bricolage Grotesque",sans-serif; font-weight:600; }
.chips { margin-top:8px; }
.chip { display:inline-block; font-size:8.6pt; color:#E4D7CA;
  border:1px solid rgba(255,255,255,.22); border-radius:20px;
  padding:2.5px 10px; margin:0 5px 5px 0;
  font-family:"Bricolage Grotesque",sans-serif; }
.cover-foot { margin-top:20px; padding-top:13px;
  border-top:1px solid rgba(255,255,255,.17); font-size:8.6pt;
  color:#B7A697; }

/* ---------- structure ---------- */
section { margin:0 0 20px; }
.eyebrow { font-size:7.8pt; letter-spacing:.16em; text-transform:uppercase;
  color:var(--accent-ink); font-weight:600; margin:0 0 5px; }
h2 { font-size:17.5pt; letter-spacing:-.022em; margin:0 0 9px; font-weight:800;
  line-height:1.14; }
h3 { font-size:11.4pt; margin:16px 0 5px; font-weight:700; letter-spacing:-.01em; }
p { margin:0 0 8px; }
.lead { font-size:11.6pt; line-height:1.5; color:var(--ink-soft); }
.lead strong { color:var(--ink); font-weight:600; }
a { color:var(--accent-ink); }

.two { display:grid; grid-template-columns:1fr 1fr; gap:17px; }
.three { display:grid; grid-template-columns:repeat(3,1fr); gap:11px; }

.card { background:var(--surface); border:1px solid var(--rule);
  border-radius:10px; padding:13px 15px; }
.card h4 { margin:0 0 5px; font-size:10pt; font-weight:700; }
.card p { margin:0; font-size:9.3pt; color:var(--ink-soft); }

.panel { border-radius:11px; padding:15px 17px; }
.panel.dark { background:#1D1815; color:#EFE8E1; }
.panel.dark h3 { color:#FFF; margin-top:0; }
.panel.dark p { color:#C4B7AB; }
.panel.dark strong { color:#F3D9BE; font-weight:600; }
.panel.go { background:var(--go-wash); border:1px solid #BFD6C9; }
.panel.gold { background:var(--gold-wash); border:1px solid #DECDA8; }
.panel.stop { background:var(--stop-wash); border:1px solid #E4C2B9; }
.panel h3 { margin-top:0; }
.panel p:last-child { margin-bottom:0; }

table { width:100%; border-collapse:collapse; font-size:8.9pt; }
th { text-align:left; font-size:7.4pt; text-transform:uppercase;
  letter-spacing:.085em; color:var(--ink-faint); font-weight:600;
  padding:0 8px 5px 0; border-bottom:1.5px solid var(--rule-strong); }
td { padding:6px 8px 6px 0; border-bottom:1px solid var(--rule);
  vertical-align:top; }
/* A drill's description must not be cut in half by a page break. */
tr { break-inside:avoid; }
thead { display:table-header-group; }
td.name { font-weight:600; font-family:"Bricolage Grotesque",sans-serif;
  white-space:nowrap; }
td.desc { color:var(--ink-soft); }
.metric { font-size:8pt; color:var(--accent-ink); white-space:nowrap; }
tr.gen td.name { font-weight:500; color:var(--ink-soft); }

.pill { display:inline-block; font-size:7pt; font-weight:600; padding:1.5px 6px;
  border-radius:20px; letter-spacing:.045em; text-transform:uppercase;
  white-space:nowrap; }
.p-power { background:var(--accent-wash); color:var(--accent-ink); }
.p-quickness { background:var(--gold-wash); color:var(--gold); }
.p-strength { background:#E7E2F0; color:#4A3E6B; }
.p-endurance { background:var(--go-wash); color:var(--go); }
.p-skill { background:var(--surface-sunk); color:var(--ink-soft); }

.pos { border-left:2.5px solid var(--accent); padding:2px 0 2px 11px;
  margin-bottom:11px; break-inside:avoid; }
.pos h4 { margin:0 0 2px; font-size:10.2pt; font-weight:700;
  font-family:"Bricolage Grotesque",sans-serif; }
.pos .focus { font-size:9.2pt; color:var(--ink-soft); margin:0 0 4px; }
.pos .top { font-size:8pt; color:var(--ink-faint);
  font-family:"IBM Plex Mono",monospace; }

ul { margin:0 0 8px; padding-left:17px; }
li { margin-bottom:4px; }
.check { list-style:none; padding-left:0; }
.check li { padding-left:19px; position:relative; }
.check li::before { content:""; position:absolute; left:2px; top:.44em;
  width:8px; height:8px; border-radius:2px; background:var(--go); }
.cross li::before { background:var(--stop); }

.rule { height:1px; background:var(--rule); margin:17px 0; border:0; }
.break { break-before:page; }
.avoid { break-inside:avoid; }
footer { margin-top:20px; padding-top:9px; border-top:1px solid var(--rule);
  font-size:7.9pt; color:var(--ink-faint); display:flex;
  justify-content:space-between; }
"""


def tile(n, label):
    return f'<div class="tile"><div class="tile-n">{e(n)}</div>' \
           f'<div class="tile-l">{e(label)}</div></div>'


def drill_rows(rows, general=False):
    out = []
    for r in rows:
        cls = ' class="gen"' if general else ""
        ball = ""
        if r["uses_ball"]:
            ball = f' <span class="metric">· ball</span>'
        out.append(
            f'<tr{cls}><td class="name">{e(r["name"])}</td>'
            f'<td><span class="pill p-{r["stimulus"].lower()}">{e(r["stimulus"])}</span></td>'
            f'<td class="metric">{e(r["metric"])}{ball}</td>'
            f'<td class="desc">{e(r["description"])}</td></tr>')
    return "\n".join(out)


def top_line(position):
    """The handful of drills that dominate a position's week."""
    return " · ".join(f'{t["name"]} {t["share"]}%' for t in position["top"])


def page(data, copy, logo, has_logo):
    d = data
    thesis, reality, worry = copy
    label = d["label"]
    n_pos = len(d["positions"])
    own, gen = d["own_drills"], d["general_drills"]

    positions = "\n".join(
        f'<div class="pos"><h4>{e(p["label"])}</h4>'
        f'<p class="focus">{e(p["focus"])}</p>'
        f'<p class="top">{e(top_line(p))}</p>'
        f'</div>' for p in d["positions"])

    mix = sorted(d["stimulus_mix"].items(), key=lambda kv: -kv[1])
    total = sum(v for _, v in mix) or 1
    mix_html = " ".join(
        f'<span class="pill p-{k.lower()}">{e(k)} {round(v/total*100)}%</span>'
        for k, v in mix)

    seasons = ", ".join(s.title() for s in d["seasons"]) or "Year round"
    ball_note = ""
    if d["ball_sport"]:
        # Preserve catalog order: the first colour is the common ball.
        seen, cols = set(), []
        for r in own:
            if not r["uses_ball"]:
                continue
            for c in r["ball_colours"]:
                if c not in seen:
                    seen.add(c)
                    cols.append(COLOUR_WORDS.get(c, c))
        listed = cols[0] if len(cols) == 1 else \
            f'{", ".join(cols[:-1])} and {cols[-1]}'
        ball_note = (
            f'<p>Ball drills find the ball by colour, size and motion at once, '
            f'and the size is checked against the athlete\'s own body — so '
            f'something orange in the background is not a ball. This sport is '
            f'set up for {e(listed)}. If an athlete owns something else, they '
            f'can show the app their ball and it learns the colour in two '
            f'seconds.</p>'
            + ('<p>In this sport the ball is optional. The repetitions are '
               'counted from the athlete\'s own movement, and the ball is used '
               'to corroborate them when the camera can see it — so a drill '
               'still counts on a dark evening.</p>'
               if d["ball_optional"] else ''))

    chips = "".join(f'<span class="chip">{e(p["label"])}</span>'
                    for p in d["positions"])
    # Five sports here have no skill drills at all, and that is the product's
    # position rather than a hole: gymnastics, cheer, dance, track and cross
    # country are supported as conditioning only. Saying "0 drills specific to
    # dance" would read as a gap, so those pages say what is actually true.
    if own:
        borrowed = d["borrowed_from"]
        share = ""
        if borrowed:
            share = (f' Some are shared with {e(", ".join(b.title() for b in borrowed))}, '
                     f'because the movement is the same one.')
        lead = (f'{len(own)} skill drills for {label.lower()}, plus {len(gen)} '
                f'from the shared athleticism library.{share} Each is counted by '
                f'a rule written for that movement — not a general-purpose model '
                f'guessing.')
        skill_table = (
            '<table style="margin-top:11px"><thead><tr>'
            '<th style="width:23%">Drill</th><th style="width:12%">Trains</th>'
            '<th style="width:16%">Counted as</th><th>What it is</th>'
            f'</tr></thead><tbody>{drill_rows(own)}</tbody></table>')
        athletic_heading = "From the shared athleticism library"
    else:
        lead = (f'{label} is supported as conditioning, and only as '
                f'conditioning. There are no {label.lower()}-specific skill '
                f'drills in this product and there will not be: the useful work '
                f'between sessions is strength, power and endurance, and the '
                f'skill itself belongs in a coached session. All {len(gen)} '
                f'drills below come from the shared athleticism library.')
        skill_table = ""
        athletic_heading = f"The {len(gen)} drills a {label.lower()} plan draws on"

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>0FFDAYS {e(label)}</title><style>{FONTS}{CSS}</style></head><body>

<div class="cover">
  <div class="cover-head">
    {logo}
    <div class="meta">FOR THE DIRECTOR OF<br><strong>{e(label.upper())}</strong><br>{e(seasons)} season</div>
  </div>
  <div style="margin-top:34px" class="kicker">Off-day training, on the record</div>
  <h1>{e(label)}</h1>
  <p class="thesis">{thesis}</p>
  <div class="tiles">
    {tile(len(own) + len(gen), "drills available")}
    {tile(n_pos, "position plans")}
    {tile(f'{d["explosive_min"]}–{d["explosive_max"]}%', "explosive share of a plan")}
    {tile(d["film_topics"], "film topics ready")}
  </div>
  <div class="claim">
    <q>Coaches see data.<br><em>Nobody sees video.</em></q>
    <p class="sub">Not as a promise. There is no endpoint in this product that
    accepts video and no column that could store an image, and the build fails
    if anyone adds one.</p>
  </div>
  <div class="steps">
    <div class="step"><div class="n">01</div><h4>They prop up a phone</h4>
      <p>Against a water bottle, a fence, anything. Any angle. No mount, no
      wearable, no second person.</p></div>
    <div class="step"><div class="n">02</div><h4>The phone does the counting</h4>
      <p>Pose analysis runs in the browser, on their device, as they move. The
      video is never uploaded and never stored.</p></div>
    <div class="step"><div class="n">03</div><h4>You get the number</h4>
      <p>Repetitions, range of motion, which hand. Enough to coach from, and
      nothing you would have to defend to a parent.</p></div>
  </div>
  <div class="roster">
    <div class="lbl">Plans written for</div>
    <div class="chips">{chips}</div>
  </div>
  <div class="cover-foot">
    Every figure on this page is read straight out of the product's own drill
    catalog. Nothing here is a projection.
  </div>
</div>

<div>

<section>
  <p class="eyebrow">The problem you already have</p>
  <h2>Your athletes train on their own. You have no idea whether it happened.</h2>
  <p class="lead">{reality}</p>
  <p>Every program runs on the same broken instrument: <strong>you ask, and they
  tell you.</strong> The honest kids under-report, the confident ones round up, and
  the ones quietly doing nothing are indistinguishable from the ones grinding in a
  garage. You cannot coach what you cannot see, and you certainly cannot protect
  an athlete whose real workload is a rumour.</p>
  <p>0FFDAYS turns a phone into the instrument. An athlete props it against a
  water bottle, does the drill, and the app counts the repetitions as they
  happen — the way a coach standing there would, except it never gets bored and
  never rounds up.</p>
</section>

<section class="avoid">
  <div class="panel dark">
    <h3>The part that matters to whoever signs your policies</h3>
    <p><strong>The video never leaves the phone.</strong> Pose analysis runs in the
    browser on the athlete's own device. What reaches our servers is a number of
    repetitions and a timestamp. There is no upload, no clip stored anywhere, no
    footage of a minor sitting in anyone's cloud, and nothing for you or us to
    lose.</p>
    <p style="margin-top:8px">This is not a policy we promise to keep. There is no
    endpoint in the product that accepts video and no column in the database that
    could store an image — and a test suite fails the build if anybody ever adds
    one. <strong>Coaches see data. Nobody sees video.</strong></p>
  </div>
</section>

<section class="two avoid">
  <div>
    <h3>What you get to see</h3>
    <ul class="check">
      <li>Who actually trained this week, and how much</li>
      <li>Which positions are keeping up and which have gone quiet</li>
      <li>An athlete whose workload jumped sharply — before it becomes an injury</li>
      <li>A pre-practice view of who arrives fresh and who arrives cooked</li>
      <li>Exports for evaluations, at season end, in a format you keep</li>
    </ul>
  </div>
  <div>
    <h3>What nobody gets to see</h3>
    <ul class="check cross">
      <li>Any video of any athlete, ever</li>
      <li>A ranking of children by who looks best doing a drill</li>
      <li>Anything about how a body looks, in any sport</li>
      <li>An athlete's data after they leave your program</li>
    </ul>
  </div>
</section>

<section class="break">
  <p class="eyebrow">The library</p>
  <h2>What a {e(label.lower())} athlete actually does</h2>
  <p class="lead">{lead}</p>
  {ball_note}
  {skill_table}
  <h3>{athletic_heading}</h3>
  <p style="font-size:9.2pt;color:var(--ink-soft);margin-bottom:8px">Speed,
  power and strength work is not sport-specific, so it is built once and
  weighted differently for every position. Every plan in this product carries a floor
  of explosive work — the thing that makes an athlete faster rather than just
  better at their sport.</p>
  <table>
    <thead><tr><th style="width:23%">Drill</th><th style="width:12%">Trains</th>
    <th style="width:16%">Counted as</th><th>What it is</th></tr></thead>
    <tbody>{drill_rows(gen, True)}</tbody>
  </table>
  <p style="margin-top:11px;font-size:9pt">Across every {e(label.lower())}
  plan: {mix_html}</p>
</section>

<section class="break">
  <p class="eyebrow">Position plans</p>
  <h2>A {e(label.lower())} plan is not one plan</h2>
  <p class="lead">Each position gets its own weighting, written separately rather
  than generated from a template. The percentages are the share of that
  position's week given to each drill.</p>
  <div style="margin-top:13px">{positions}</div>
</section>

<section class="avoid">
  <p class="eyebrow">The safeguards</p>
  <h2>Built to be put down</h2>
  <p class="lead">The thing that worries a {e(label.lower())} director most is
  {worry}. A product that rewards volume without limit makes that worse. This one
  is counter-weighted on purpose.</p>
  <div class="three" style="margin-top:12px">
    <div class="card"><h4>Caps, not multipliers</h4>
    <p>Every drill has a daily ceiling and diminishing returns before it. Doing
    four hundred reps is worth barely more than two hundred, and the app says so.</p></div>
    <div class="card"><h4>Rest is scored</h4>
    <p>Streaks survive a rest day. An athlete who trains seven days a week gets a
    warning, not a badge.</p></div>
    <div class="card"><h4>Load advisories</h4>
    <p>A sharp jump in weekly workload raises a flag to the coach — the pattern
    that precedes most overuse injuries.</p></div>
  </div>
  <div class="panel gold" style="margin-top:12px">
    <h3>The throwing ceiling</h3>
    <p>For any sport that throws, the app tracks a daily throw count against an
    age-based ceiling — 60 throws at eight years old, rising to 150 at eighteen —
    and stops paying beyond it. This is the number no league counts, because
    pitch counts only count games.</p>
  </div>
</section>

<section class="break avoid">
  <p class="eyebrow">Honest limits</p>
  <h2>What this cannot do yet</h2>
  <p class="lead">You are going to ask a version of this question, so here it is
  before you have to.</p>
  <div class="two" style="margin-top:12px">
    <div>
      <h3>Not yet calibrated on real footage</h3>
      <p>The counters are verified against synthetic movement and a large test
      suite. They have not yet been tuned against a few dozen real athletes of
      different sizes in real garages. That is the next piece of work, and it
      needs a program willing to film a calibration set.</p>
      <h3>The film library has no films</h3>
      <p>There are {e(str(d["film_topics"]))} {e(label.lower())} teaching topics
      structured and ready. The clips that hang on them have to come from you or
      from a rights holder — we are not going to scrape somebody's game footage.</p>
    </div>
    <div>
      <h3>It counts work, not quality</h3>
      <p>The app can tell you an athlete did 300 repetitions with a full range of
      motion. It cannot tell you their technique was good. A coach still coaches;
      this just means they stop having to guess about volume.</p>
      <h3>Some things are deliberately absent</h3>
      <p>There is no drill here that asks an athlete to do something unsafe alone.
      Where a movement needs a spotter, a partner or supervision, it is not in the
      product — and that is a decision, not a backlog item.</p>
    </div>
  </div>
</section>

<footer>
  <span>0FFDAYS · {e(label)} · for program directors</span>
  <span>Counts, not footage.</span>
</footer>
</div>
</body></html>"""


def main():
    sys.path.insert(0, str(HERE))
    from sportcopy import SPORT
    data = json.loads((HERE / "sports.json").read_text())
    logo, has_logo = logo_block()
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    built = []
    for key, d in sorted(data.items()):
        if key not in SPORT:
            print(f"  !! no copy for {key}")
            continue
        src = out / f"{key}-build.html"
        src.write_text(page(d, SPORT[key], logo, has_logo))
        pdf = out / f"0FFDAYS-{key.replace('_','-')}-program.pdf"
        subprocess.run([
            CHROME, "--headless", "--disable-gpu", "--no-sandbox",
            "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
            "--virtual-time-budget=12000", src.as_uri()],
            check=True, capture_output=True)
        built.append((d["label"], pdf))
    print(f"logo: {'user file' if has_logo else 'wordmark fallback'}")
    for label, pdf in built:
        from pypdf import PdfReader
        print(f"  {label:22} {len(PdfReader(pdf).pages)}pp  "
              f"{pdf.stat().st_size//1024}KB")


if __name__ == "__main__":
    main()
