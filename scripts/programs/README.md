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

## The logo

Drop `logo.svg` (or `.png`, `.jpg`, `.webp`) into this directory and rebuild.
It replaces the wordmark on every cover, at 46px tall, with no other change.
If no file is present the build falls back to the `0FFDAYS` wordmark and says
so in its output.

## Why the fonts are inlined

Chromium renders these with no network access. A linked stylesheet falls back
to DejaVu silently, which looks almost right and is the sort of thing you
notice only after printing. `fetch_fonts.py` embeds every face as base64.
