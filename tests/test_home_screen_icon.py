"""The icon a phone shows when 0FFDAYS is added to the home screen is the 0FFDAYS lockup."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "offdays" / "web" / "static"
BLUE = (0, 139, 253)
DARK = (11, 15, 20)

spec = importlib.util.spec_from_file_location("build_icons", ROOT / "scripts" / "build_icons.py")
build_icons = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_icons)


def near(pixel, colour, slack=40):
    return all(abs(a - b) <= slack for a, b in zip(pixel[:3], colour))


def ink_box(im):
    """The box around everything that is not background."""
    px = im.convert("RGB").load()
    xs, ys = [], []
    for y in range(im.height):
        for x in range(im.width):
            if not near(px[x, y], DARK, 12):
                xs.append(x); ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


@pytest.mark.parametrize("name,size,fill", build_icons.ICONS)
def test_each_icon_is_the_lockup_on_the_dark_background(name, size, fill):
    im = Image.open(STATIC / name)
    assert im.size == (size, size) and im.mode == "RGB", "square and opaque: iPhones turn transparency black"
    px = im.load()
    assert all(near(px[x, y], DARK, 4) for x, y in ((0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)))
    colours = [px[x, y] for y in range(size) for x in range(size)]
    assert sum(near(c, BLUE) for c in colours) > size * size * 0.02, "the blue 0FF and lines"
    assert sum(near(c, (255, 255, 255), 25) for c in colours) > size * size * 0.015, "the white DAYS"
    left, top, right, bottom = ink_box(im)
    assert abs((left + right) / 2 - size / 2) <= size * 0.02 and abs((top + bottom) / 2 - size / 2) <= size * 0.02


@pytest.mark.parametrize("name", ["icon-maskable-192.png", "icon-maskable-512.png"])
def test_a_phone_that_crops_to_a_circle_cuts_nothing_off(name):
    im = Image.open(STATIC / name)
    size = im.width
    left, top, right, bottom = ink_box(im)
    safe = size * 0.4                                    # the middle 80% is a circle of radius 40%
    for x, y in ((left, top), (right, top), (left, bottom), (right, bottom)):
        assert ((x - size / 2) ** 2 + (y - size / 2) ** 2) ** 0.5 <= safe, (name, x, y)


def test_the_checked_in_icons_are_what_the_script_builds():
    lockup = Image.open(STATIC / "offdays-lockup.png").convert("RGBA")
    for name, size, fill in build_icons.ICONS:
        assert list(build_icons.build(size, fill, lockup).getdata()) == list(Image.open(STATIC / name).getdata()), \
            f"{name} is stale: run python scripts/build_icons.py"


def test_the_manifest_points_at_icons_that_exist():
    icons = json.loads((STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))["icons"]
    assert {i["purpose"] for i in icons} == {"any", "maskable"}
    for i in icons:
        path = STATIC / i["src"].split("?")[0]
        assert path.exists() and "x".join(map(str, Image.open(path).size)) == i["sizes"]
        assert ("maskable" in path.name) == (i["purpose"] == "maskable")


@pytest.mark.parametrize("page", ["index.html", "coach.html", "capture.html", "terms.html", "privacy.html"])
def test_every_page_names_the_home_screen_icon(page):
    html = (STATIC / page).read_text(encoding="utf-8")
    found = re.search(r'<link rel="apple-touch-icon" sizes="180x180" href="([^"?]+)\?v=(\d+)">', html)
    assert found and (STATIC / found.group(1)).exists(), page
    assert Image.open(STATIC / found.group(1)).size == (180, 180)
