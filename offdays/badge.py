"""A program's own badge, uploaded by its director.

A club opens this app to train for *their* club. The first thing a director
does after signing up is make it look like theirs, so the badge goes in
through the dashboard rather than through us. The file lives beside the
database -- not under static/, which every deploy rebuilds -- named by
program so a second upload replaces the first, and every screen that program
sees picks it up on the next load (`Store.org_branding`).

The type is read from the bytes, never from the filename or the header; a
browser will send image/png for anything. SVG is allowed because clubs have
vector crests, but only after its script and event surface is removed: an
SVG is a document, and one that runs code in a parent's browser is not a
badge.
"""

from __future__ import annotations

import re
from pathlib import Path

#: 2 MB is generous for a logo and small enough that nobody can fill the
#: data volume with one request.
MAX_BYTES = 2 * 1024 * 1024

_MAGIC = (
    ("png", b"\x89PNG\r\n\x1a\n"),
    ("jpg", b"\xff\xd8\xff"),
)

_SCRIPT = re.compile(r"<script\b.*?</script\s*>", re.S | re.I)
_SCRIPT_EMPTY = re.compile(r"<script\b[^>]*/>", re.I)
_ON_ATTR = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
_JS_HREF = re.compile(r"\b(?:xlink:)?href\s*=\s*(\"\s*javascript:[^\"]*\"|'\s*javascript:[^']*')", re.I)
_FOREIGN = re.compile(r"<foreignObject\b.*?</foreignObject\s*>", re.S | re.I)


class BadgeError(ValueError):
    """Not an image we will put in a header."""


def sniff(data: bytes) -> str:
    """'png' | 'jpg' | 'webp' | 'svg', from the bytes alone."""
    for ext, magic in _MAGIC:
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    head = data[:512].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:4096].lower()):
        return "svg"
    raise BadgeError("a badge must be a PNG, JPEG, WebP or SVG file")


def clean_svg(data: bytes) -> bytes:
    text = data.decode("utf-8", errors="replace")
    text = _SCRIPT.sub("", text)
    text = _SCRIPT_EMPTY.sub("", text)
    text = _FOREIGN.sub("", text)
    text = _ON_ATTR.sub("", text)
    text = _JS_HREF.sub("", text)
    return text.encode("utf-8")


def filename(org_id: int, ext: str) -> str:
    return f"org-{org_id}.{ext}"


def save(uploads_dir: Path, org_id: int, data: bytes) -> str:
    """Validate, scrub, write. Returns the stored filename.

    Raises BadgeError for a wrong type and ValueError for a bad size, so the
    route can map each to the right status.
    """
    if not data:
        raise ValueError("empty file")
    if len(data) > MAX_BYTES:
        raise ValueError("that image is over 2 MB; a badge should be much smaller")
    ext = sniff(data)
    if ext == "svg":
        data = clean_svg(data)
    name = filename(org_id, ext)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    # One badge on disk per program: drop an earlier one in another format.
    for old in uploads_dir.glob(f"org-{org_id}.*"):
        if old.name != name:
            old.unlink(missing_ok=True)
    (uploads_dir / name).write_bytes(data)
    return name


def remove(uploads_dir: Path, org_id: int) -> None:
    for old in uploads_dir.glob(f"org-{org_id}.*"):
        old.unlink(missing_ok=True)
