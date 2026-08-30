"""Fetch the document typefaces and inline them as base64.

The PDFs are rendered by headless Chromium with no network, so every face has
to be embedded in the HTML before rendering. A linked stylesheet silently
falls back to DejaVu, which looks almost right and is the kind of thing you
only notice once the document is printed.

Run once; the output is cached and reused by build.py.
"""
import base64, pathlib, re, subprocess, sys

HERE = pathlib.Path(__file__).parent
OUT = HERE / "fonts-inline.css"
CA = "/root/.ccr/ca-bundle.crt"

# The three families named in the brand guidelines. Barlow Condensed carries
# headings and KPI numbers, Inter carries body and UI, JetBrains Mono is
# restricted to claim codes and athlete identifiers.
FAMILIES = [
    "Barlow+Condensed:wght@500;600;700",
    "Inter:ital,wght@0,400;0,500;0,600;0,700;1,400",
    "JetBrains+Mono:wght@400;500",
]
# A browser UA, because the Google Fonts CSS API serves woff2 only to browsers
# it recognises and a legacy TTF payload to everything else.
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")


def get(url: str) -> bytes:
    r = subprocess.run(["curl", "-sS", "--fail", "--cacert", CA,
                        "-A", UA, url], capture_output=True)
    if r.returncode:
        raise SystemExit(f"fetch failed: {url}\n{r.stderr.decode()[:400]}")
    return r.stdout


def main() -> None:
    css = "\n".join(
        get(f"https://fonts.googleapis.com/css2?family={fam}&display=swap").decode()
        for fam in FAMILIES)

    urls = sorted(set(re.findall(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", css)))
    print(f"{len(urls)} font files")
    for url in urls:
        data = get(url)
        mime = "font/woff2" if url.endswith(".woff2") else "font/ttf"
        css = css.replace(url, f"data:{mime};base64,{base64.b64encode(data).decode()}")

    if "https://fonts.gstatic.com" in css:
        raise SystemExit("a font URL was left un-inlined")
    OUT.write_text(css)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024}KB)")


if __name__ == "__main__":
    main()
