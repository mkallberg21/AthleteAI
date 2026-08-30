"""The app's paint, checked rather than eyeballed.

The brand kit's tokens and its contrast notes are written for a light
interface. This app is dark, so three values had to be derived, and a derived
value with no test is a value that drifts back. These assert the reasoning,
not the hexes for their own sake.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "offdays" / "web" / "static"
CSS = (STATIC / "styles.css").read_text()

#: Brand values used unchanged, from the kit's tokens.css.
BRAND = {
    "--bg": "#0A0A0B",       # Court
    "--surface": "#0B1B2B",  # Ink
    "--accent": "#008BFD",   # Electric Blue
    "--go": "#12A150",
    "--warn": "#C77700",
}


def token(name: str) -> str:
    m = re.search(rf"{name}:\s*(#[0-9A-Fa-f]{{6}})", CSS)
    assert m, f"{name} is not defined in styles.css"
    return m.group(1).upper()


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    out = []
    for i in (0, 2, 4):
        v = int(h[i:i + 2], 16) / 255
        out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("name,expected", sorted(BRAND.items()))
def test_the_brand_values_are_used_unchanged(name, expected):
    assert token(name) == expected.upper()


@pytest.mark.parametrize("name", ["--text", "--muted", "--accent", "--go",
                                  "--warn", "--danger"])
def test_every_foreground_is_readable_on_every_background(name):
    """4.5:1 against all three surfaces, which is why three values are derived.

    Blue Deep is absent from this list on purpose: it fails on dark at 3.38:1,
    the exact opposite of its role on white, so it is used for fills and
    pressed states and never for text.
    """
    fg = token(name)
    for surface in ("--bg", "--surface", "--surface-2"):
        ratio = contrast(fg, token(surface))
        assert ratio >= 4.5, (
            f"{name} on {surface} is {ratio:.2f}:1, below 4.5")


def test_blue_deep_is_never_used_as_text():
    """It is 3.38:1 on Court. Fills only."""
    assert token("--accent-dim") == "#0063C4"
    body = CSS[CSS.index("* { box-sizing"):]
    for line in body.splitlines():
        if "--accent-dim" in line:
            assert "color:" not in line.split("--accent-dim")[0][-24:], line


def test_the_two_handedness_colours_stay_apart():
    """Left and right are read at a glance, often by children.

    Red against green would be the obvious pair and the wrong one. These are
    separated in luminance as well as hue, so they survive being seen by
    someone who cannot tell those two apart.
    """
    left, right = token("--left"), token("--right")
    assert contrast(left, right) >= 1.35, "left and right are too close"


def test_no_legacy_palette_survives_anywhere():
    """The pre-brand green, in hex and in the rgba form that hid from grep."""
    legacy = ("#39d98a", "#1f8f5b", "57,217,138", "#0b0f14", "#141b24",
              "#8ba0b5", "#ffb020", "#ff5c5c")
    for path in list(STATIC.glob("*.css")) + list(STATIC.glob("*.html")) \
            + list(STATIC.glob("*.js")):
        text = path.read_text().lower()
        for needle in legacy:
            assert needle.lower() not in text, f"{path.name} still has {needle}"


def test_the_typefaces_are_served_from_our_own_origin():
    """A <link> to a font CDN would leave the app shell incomplete offline and
    send a child's IP to a third party on every cold load."""
    assert "fonts.googleapis.com" not in CSS
    assert "fonts.gstatic.com" not in CSS
    face_css = (STATIC / "fonts" / "fonts.css").read_text()
    assert "https://" not in face_css
    for name in re.findall(r"url\(([^)]+)\)", face_css):
        assert (STATIC / "fonts" / name.strip("\"'")).exists(), name


def test_every_font_in_the_service_worker_shell_exists():
    """A 404 in the precache list is silent -- cache.add failures are caught
    individually so one bad entry does not abort the install."""
    sw = (STATIC / "sw.js").read_text()
    shell = re.search(r"const SHELL = \[(.*?)\];", sw, re.S).group(1)
    for entry in re.findall(r"'([^']+)'", shell):
        if entry in ("./",):
            continue
        assert (STATIC / entry).exists(), f"{entry} is precached but missing"


def test_the_wordmark_colours_the_half_the_logo_colours():
    """Blue carries "0FF", the neutral carries "DAYS" -- the app had it the
    other way round, so its header disagreed with the lockup on every
    document a program sees."""
    assert ".brand > span:first-child { color: var(--accent); }" in CSS
    for page in STATIC.glob("*.html"):
        text = page.read_text()
        if 'class="brand"' in text:
            assert '<span>0FF</span>DAYS' in text, page.name
