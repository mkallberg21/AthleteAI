"""Home-screen and browser icons from the 0FFDAYS lockup. Run again whenever the lockup changes.

    python scripts/build_icons.py

The lockup is wide and a home-screen icon is square, so the whole lockup sits centered on the app's dark background.
Android may crop an icon to a circle, so the "maskable" pair keeps the lockup inside the middle 80%.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

STATIC = Path(__file__).resolve().parent.parent / "offdays" / "web" / "static"
BACKGROUND = (11, 15, 20)            # manifest background_color, #0b0f14
# name, size, how much of the width the lockup fills
ICONS = (
    ("icon-192.png", 192, 0.90),
    ("icon-512.png", 512, 0.90),
    ("icon-180.png", 180, 0.90),             # iPhone and iPad home screen
    ("icon-maskable-192.png", 192, 0.70),
    ("icon-maskable-512.png", 512, 0.70),
)


def build(size: int, fill: float, lockup: Image.Image) -> Image.Image:
    art = lockup.crop(lockup.getbbox())
    width = round(size * fill)
    art = art.resize((width, round(art.height * width / art.width)), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), BACKGROUND + (255,))
    out.alpha_composite(art, ((size - art.width) // 2, (size - art.height) // 2))
    return out.convert("RGB")


def main() -> None:
    lockup = Image.open(STATIC / "offdays-lockup.png").convert("RGBA")
    for name, size, fill in ICONS:
        build(size, fill, lockup).save(STATIC / name, optimize=True)
        print(name)


if __name__ == "__main__":
    main()
