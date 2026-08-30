# Program-director summaries

One PDF per sport, written for the person who runs the program rather than for
an engineer. Sixteen sports, six or seven pages each.

```bash
python3 fetch_fonts.py      # once: inlines the typefaces (needs network)
python3 extract.py          # reads the shipped catalog -> sports.json
python3 build.py            # sports.json + prose -> out/*.pdf
```

Every count, percentage, drill name, position and colour in these documents is
read out of `offdays/` by `extract.py`. Nothing is typed twice, so a document
cannot claim a drill the product does not have. The only hand-written content
is the per-sport prose in `sportcopy.py` and the template in `build.py`.

## Brand

`brandkit/` is the supplied OffDays kit and is the source of truth. The build
reads three things out of it and nothing is duplicated by hand:

* the primary lockup, transparent-on-dark, for the cover
* the colour tokens from `tokens.css`
* the typefaces named in the guidelines — Barlow Condensed, Inter, JetBrains
  Mono — fetched by `fetch_fonts.py`

If `brandkit/` is missing the build falls back to a text wordmark and says so
in its output, so a fallback can never ship unnoticed.

### Rules being honoured, and where

| Rule | How |
|---|---|
| Print minimum 1.25in wide | Cover runs the lockup at 1.9in (688dpi, inside the 1307px native raster) |
| Clear space ≥ the mark's height | 0.44in required; cover padding is 0.6–0.8in with a 0.5in gutter to the meta block |
| No recolour, stretch, skew or rotation | `width` set, `height:auto`, no transforms or filters |
| Full-colour lockup off mid-tone/busy grounds | Cover is flat Court with a masked gradient; the on-dark transparent asset is used |
| Electric Blue fails at body size on light | Small blue text on light uses Blue Deep. Electric Blue appears on light only as rules, fills and pills; on Ink it is used for text, where it reaches 5.1:1 |
| Tabular figures on counts | Scoped to the stat tiles, plan percentages and table figures |
| JetBrains Mono for codes and IDs only | Declared as `.code`, used nowhere in these documents |

**Do not set `font-variant-numeric: tabular-nums` on `body`.** Inter's `tnum`
feature also swaps the hyphen for a tabular-width minus, which puts a visible
gap inside every hyphenated word — "off-hand" and "hi-vis" came out spaced
across all sixteen documents before this was caught.

### Known limitation, from the kit's own guidelines

The lockup is a raster derived from an AI-generated image and does not scale
past 1307px. At the cover's 1.9in that is 688dpi and fine. Anything larger —
a banner, signage, a cover at full-bleed — needs the vector redraw the
guidelines call for.

## Why the fonts are inlined

Chromium renders these with no network access. A linked stylesheet falls back
to DejaVu silently, which looks almost right and is the sort of thing you
notice only after printing. `fetch_fonts.py` embeds every face as base64.

## The dashboard screenshots

`shots/` holds real captures of the running coach dashboard, not a mock.

```bash
python3 ../seed_demo.py --db /tmp/demo.db
OFFDAYS_DB_PATH=/tmp/demo.db python3 -m uvicorn offdays.api:app --port 8811 &
python3 capture_dashboard.py --token <the director token the seeder printed>
```

Two things are removed before capturing, both honest edits rather than
flattery: the sticky header, which renders over the panel being photographed,
and the first-week onboarding checklist, which is scaffolding for a coach
setting up rather than part of what a director is being shown.

**Known mismatch.** The app still renders in its original green accent, while
these documents follow the brand kit's Electric Blue. The screenshots are
therefore accurate and off-palette at the same time. Fixing it belongs in the
app rather than here — re-skinning `offdays/web/static/styles.css` onto
`tokens.css` would settle it for the product and these captures together.
