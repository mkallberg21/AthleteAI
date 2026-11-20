"""The guide for parents, as a PDF with the program's own logo at the top, for the invite email to carry.

The guide itself is `assets/parent_guide/guide.html`, printed to two PDFs by `scripts/ui/build-parent-guide.mjs`
(the server has no browser): `guide_logo.pdf`, whose header band leaves room on the left, and `guide_plain.pdf`,
which does not. This module lays the program's uploaded logo onto the first one. Whatever goes wrong (a logo
Pillow cannot read, an SVG, a missing library) the parent still gets the guide, just without the logo, and the
invite is never held back by it.
"""

from __future__ import annotations

import io
import logging
import sqlite3
from pathlib import Path

from .config import CONFIG

log = logging.getLogger(__name__)

ASSETS = Path(__file__).parent / "assets" / "parent_guide"
FILENAME = "0FFDAYS-guide-for-parents.pdf"
MIME = "application/pdf"
#: What an outbox row's `attachment` column holds: this, then the program's id.
PREFIX = "parent_guide:"

# The header band is 88 CSS px high on a 720 px wide page (1 px = 0.75 pt). The logo sits on a white tile so a
# dark or transparent logo reads on the dark band.
_PX = 0.75
_TILE_X, _TILE_Y, _TILE_H = 24, 16, 56
_PAD = 8
_LOGO_BOX = (240, _TILE_H - 2 * _PAD)
_SCALE = 4                      # draw at 4x so the logo is sharp in print
_MAX_PIXELS = 25_000_000        # refuse a decompression bomb

_cache: dict[tuple, bytes] = {}


def attachment_name(org_id: int | None) -> str:
    return f"{PREFIX}{int(org_id or 0)}"


def org_of(attachment: str) -> int | None:
    if not attachment.startswith(PREFIX):
        return None
    try:
        return int(attachment[len(PREFIX):])
    except ValueError:
        return None


def logo_path(conn: sqlite3.Connection, org_id: int | None) -> Path | None:
    """The program's uploaded logo on disk, or None."""
    if not org_id:
        return None
    row = conn.execute("SELECT logo_file FROM organizations WHERE id = ?", (org_id,)).fetchone()
    name = ((row["logo_file"] if row else "") or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    from .store import TEAM_LOGOS
    for folder in (CONFIG.uploads_dir, TEAM_LOGOS):
        path = Path(folder) / name
        if path.is_file():
            return path
    return None


def _tile(path: Path):
    """The logo on a white rounded tile, as a Pillow RGB image (None if it cannot be read)."""
    from PIL import Image, ImageDraw, ImageOps

    data = path.read_bytes()
    if data[:5].lstrip().startswith(b"<") or b"<svg" in data[:2048].lower():
        return None                      # SVG: no way to draw it without a browser
    with Image.open(io.BytesIO(data)) as im:
        if im.width * im.height > _MAX_PIXELS:
            return None
        im = ImageOps.exif_transpose(im).convert("RGBA")
    box_w, box_h = _LOGO_BOX
    ratio = min(box_w / im.width, box_h / im.height)
    w, h = max(1, round(im.width * ratio * _SCALE)), max(1, round(im.height * ratio * _SCALE))
    im = im.resize((w, h), Image.LANCZOS)
    tile_w, tile_h = w + 2 * _PAD * _SCALE, _TILE_H * _SCALE
    out = Image.new("RGB", (tile_w, tile_h), (10, 10, 11))
    ImageDraw.Draw(out).rounded_rectangle((0, 0, tile_w - 1, tile_h - 1), radius=12 * _SCALE, fill=(244, 247, 250))
    out.paste(im, (_PAD * _SCALE, (tile_h - h) // 2), im)
    return out


def _with_logo(base: bytes, tile) -> bytes:
    from pypdf import PdfReader, PdfWriter, Transformation

    buf = io.BytesIO()
    # 4x pixels at this resolution come out 0.75 pt per CSS px, the scale the page was printed at.
    tile.save(buf, "PDF", resolution=72 * _SCALE / _PX)
    overlay = PdfReader(io.BytesIO(buf.getvalue())).pages[0]
    writer = PdfWriter(clone_from=io.BytesIO(base))
    page = writer.pages[0]
    top = float(page.mediabox.height)
    page.merge_transformed_page(
        overlay, Transformation().translate(tx=_TILE_X * _PX, ty=top - _TILE_Y * _PX - float(overlay.mediabox.height)))
    writer.add_metadata({"/Title": "0FFDAYS: a guide for parents"})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def guide_pdf(conn: sqlite3.Connection, org_id: int | None) -> bytes | None:
    """The guide for one program: its logo on top if it has one we can draw, otherwise the plain guide.

    None only if the guide files are not there at all.
    """
    logo, plain = ASSETS / "guide_logo.pdf", ASSETS / "guide_plain.pdf"
    if not plain.is_file():
        return None
    path = logo_path(conn, org_id)
    if path is not None and logo.is_file():
        stat = path.stat()
        key = (org_id, path.name, stat.st_mtime_ns, stat.st_size)
        if key in _cache:
            return _cache[key]
        try:
            tile = _tile(path)
            if tile is not None:
                data = _with_logo(logo.read_bytes(), tile)
                if len(_cache) >= 16:
                    _cache.pop(next(iter(_cache)))
                _cache[key] = data
                return data
        except Exception:  # noqa: BLE001 -- a bad logo must not stop a parent getting the guide
            log.warning("parent guide: could not place the logo for program %s", org_id, exc_info=True)
    return plain.read_bytes()


def available() -> bool:
    return (ASSETS / "guide_plain.pdf").is_file()


def attachments_for(conn: sqlite3.Connection, attachment: str) -> list[tuple[str, str, bytes]]:
    """(filename, mime, bytes) for an outbox row's `attachment` value; empty if it cannot be made."""
    if not attachment:
        return []
    org_id = org_of(attachment)
    if org_id is None:
        return []
    data = guide_pdf(conn, org_id)
    return [(FILENAME, MIME, data)] if data else []
