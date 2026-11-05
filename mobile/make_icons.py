"""Build the store icons from the real 0FFDAYS mark.

The old icon-192/512 are a green target from an earlier design, not the blue
mark the app wears now. Both stores want the icon to match the app.

Outputs (all under mobile/assets/, and copied into the native projects):
  icon-1024.png            App Store icon: full square, NO transparency, no rounded corners
                           (Apple rounds it itself).
  play-icon-512.png        Google Play listing icon (512, RGB; Play rounds it).
  adaptive-foreground.png  Android adaptive icon foreground: the mark inside the
                           central 66% safe zone on a transparent 432px canvas.
  Android legacy mipmaps   ic_launcher / ic_launcher_round at each density.
  iOS AppIcon-512@2x.png   what Capacitor's iOS template expects.

Run with an environment that has Pillow:  python mobile/make_icons.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
MARK = ROOT.parent / "offdays" / "web" / "static" / "offdays-mark.png"
OUT = ROOT / "assets"
BG = (10, 10, 11)          # --bg, #0A0A0B: the app's own background
OUT.mkdir(exist_ok=True)


def mark_trimmed() -> Image.Image:
    m = Image.open(MARK).convert("RGBA")
    return m.crop(m.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox())


def on_square(size: int, mark_fraction: float) -> Image.Image:
    """The mark centred on the app's dark background, `mark_fraction` of the edge."""
    canvas = Image.new("RGB", (size, size), BG)
    m = mark_trimmed()
    side = int(size * mark_fraction)
    scale = side / max(m.size)
    m = m.resize((max(1, round(m.width * scale)), max(1, round(m.height * scale))), Image.LANCZOS)
    canvas.paste(m, ((size - m.width) // 2, (size - m.height) // 2), m)
    return canvas


def circle(img: Image.Image) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, img.size[0] - 1, img.size[1] - 1), fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img.convert("RGBA"), (0, 0), mask)
    return out


def main() -> None:
    # App Store: 1024, opaque, square.
    store = on_square(1024, 0.62)
    store.save(OUT / "icon-1024.png")
    # Google Play: 512, opaque.
    on_square(512, 0.62).save(OUT / "play-icon-512.png")

    # Android adaptive icon: 108dp canvas with a 66dp safe zone. At xxxhdpi
    # that is 432px, mark inside the middle ~61% (264px of 432).
    fg = Image.new("RGBA", (432, 432), (0, 0, 0, 0))
    m = mark_trimmed()
    scale = 264 / max(m.size)
    m = m.resize((round(m.width * scale), round(m.height * scale)), Image.LANCZOS)
    fg.paste(m, ((432 - m.width) // 2, (432 - m.height) // 2), m)
    fg.save(OUT / "adaptive-foreground.png")

    # Legacy Android launcher icons, one per density.
    res = ROOT / "android" / "app" / "src" / "main" / "res"
    for density, px in {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}.items():
        d = res / f"mipmap-{density}"
        d.mkdir(parents=True, exist_ok=True)
        sq = on_square(px, 0.66)
        sq.save(d / "ic_launcher.png")
        circle(sq).save(d / "ic_launcher_round.png")
        # adaptive foreground at this density: 108dp * density factor
        f = round(px * 108 / 48)
        fgd = fg.resize((f, f), Image.LANCZOS)
        fgd.save(d / "ic_launcher_foreground.png")

    # Adaptive icon wiring: dark background colour + the foreground per density.
    (res / "values").mkdir(parents=True, exist_ok=True)
    (res / "values" / "ic_launcher_background.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        '    <color name="ic_launcher_background">#0A0A0B</color>\n</resources>\n', encoding="utf-8")
    for name in ("ic_launcher", "ic_launcher_round"):
        (res / "mipmap-anydpi-v26").mkdir(parents=True, exist_ok=True)
        (res / "mipmap-anydpi-v26" / f"{name}.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
            '    <background android:drawable="@color/ic_launcher_background"/>\n'
            '    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>\n'
            '</adaptive-icon>\n', encoding="utf-8")
    # The template's vector foreground/background would shadow ours.
    for stale in (res / "drawable-v24" / "ic_launcher_foreground.xml",
                  res / "drawable" / "ic_launcher_background.xml"):
        if stale.exists():
            stale.unlink()

    # iOS: Capacitor's template uses one 1024 icon.
    ios = ROOT / "ios" / "App" / "App" / "Assets.xcassets" / "AppIcon.appiconset"
    if ios.exists():
        store.save(ios / "AppIcon-512@2x.png")

    for p in sorted(OUT.glob("*.png")):
        im = Image.open(p)
        print(f"{p.name:26} {im.size[0]}x{im.size[1]} {im.mode}")


if __name__ == "__main__":
    main()
