"""A coach's own video, uploaded to play on the film shelf.

Everything else on the shelf is somebody else's video played in their player (see film.py). This is the one case where
the file is kept here: a coach filmed something, or made a clip, and wants the team to see it with no third party
involved. It is a different thing from an athlete's training video, which still never leaves the phone.

**Not public.** The files live beside the database, outside anything the web server serves by name. A player gets the
video through `/api/film/media/...` with a signed, expiring key made for that one person and that one clip, because a
`<video>` element cannot send a sign-in header. The key is re-checked against the database on every request, so a
retired clip or a removed player stops at once.

**No transcoding.** The server has no ffmpeg. The file is kept as uploaded, so what plays is what the phone can play:
MP4 (H.264) plays everywhere; a .mov straight off an iPhone may be HEVC, which some Android phones cannot play.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import struct
import time
from pathlib import Path

from .config import CONFIG

#: One clip. A couple of minutes of phone video at a sensible quality fits well inside this.
MAX_BYTES = 60 * 1024 * 1024
#: Everything one program has on the shelf at once.
ORG_QUOTA_BYTES = 500 * 1024 * 1024
#: How long a play key works. Long enough for a session on the shelf, short enough that a copied link dies the same day.
KEY_TTL_S = 3 * 60 * 60

MIME = {"mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm"}
_NAME = re.compile(r"^clip-\d+-[0-9a-f]{24}\.(mp4|mov|webm)$")


class VideoError(ValueError):
    """Not a video this shelf will take; the message is for the coach."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def folder() -> Path:
    """Beside the uploads folder, not inside it: /uploads/ is served to anyone by name, this is not."""
    return Path(CONFIG.uploads_dir).parent / "film"


def sniff(head: bytes) -> str:
    """'mp4' | 'mov' | 'webm', from the bytes alone. A file's name and declared type are not believed."""
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mov" if head[8:12] == b"qt  " else "mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    raise VideoError("That is not a video this can play. Use an MP4, MOV or WebM file.", 415)


def _boxes(data: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        header = 8
        if size == 1 and pos + 16 <= end:
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            return
        yield kind, pos + header, pos + size
        pos += size


def mp4_duration_s(path: Path) -> float | None:
    """Length of an MP4/MOV in seconds, read from its `moov/mvhd` box. None if it cannot be found.

    The top-level boxes are walked by seeking, so a 60 MB file is not read to find a header that is usually within the
    first or last few kilobytes.
    """
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            pos = 0
            while pos + 8 <= size:
                f.seek(pos)
                raw = f.read(16)
                box, kind = struct.unpack(">I4s", raw[:8])
                header = 8
                if box == 1:
                    box = struct.unpack(">Q", raw[8:16])[0]
                    header = 16
                elif box == 0:
                    box = size - pos
                if box < header:
                    return None
                if kind == b"moov":
                    if box > 8 * 1024 * 1024:
                        return None
                    f.seek(pos + header)
                    moov = f.read(box - header)
                    for k, a, b in _boxes(moov, 0, len(moov)):
                        if k != b"mvhd":
                            continue
                        body = moov[a:b]
                        if body[0] == 1:
                            timescale, duration = struct.unpack(">IQ", body[20:32])
                        else:
                            timescale, duration = struct.unpack(">II", body[12:20])
                        return duration / timescale if timescale else None
                    return None
                pos += box
    except (OSError, struct.error, IndexError):
        return None
    return None


def new_name(org_id: int, kind: str) -> str:
    return f"clip-{int(org_id)}-{secrets.token_hex(12)}.{kind}"


def path_for(name: str) -> Path | None:
    """The file for a stored name, or None. Only names this module made are ever turned into a path."""
    if not _NAME.match(name or ""):
        return None
    path = folder() / name
    return path if path.is_file() else None


def remove(name: str) -> None:
    if not _NAME.match(name or ""):
        return
    try:
        (folder() / name).unlink(missing_ok=True)
    except OSError:
        pass


def mime_for(name: str) -> str:
    return MIME.get(name.rsplit(".", 1)[-1], "application/octet-stream")


# ---------------------------------------------------------------------------
# Play keys
# ---------------------------------------------------------------------------

def _secret() -> bytes:
    return (CONFIG.secret_key or "offdays-dev-secret").encode("utf-8")


def _sign(clip_id: int, user_id: int, expires: int) -> str:
    message = f"film-media:{int(clip_id)}:{int(user_id)}:{int(expires)}".encode()
    return hmac.new(_secret(), message, hashlib.sha256).hexdigest()[:40]


def play_key(clip_id: int, user_id: int, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + KEY_TTL_S)
    return f"{int(user_id)}.{expires}.{_sign(clip_id, user_id, expires)}"


def read_key(clip_id: int, key: str, now: float | None = None) -> int | None:
    """The user a key was made for, or None if it is forged, for another clip, or expired."""
    try:
        user, expires, sig = (key or "").split(".")
        user_id, exp = int(user), int(expires)
    except ValueError:
        return None
    if exp < (now if now is not None else time.time()):
        return None
    if not hmac.compare_digest(sig, _sign(clip_id, user_id, exp)):
        return None
    return user_id


def media_url(clip_id: int, user_id: int) -> str:
    return f"/api/film/media/{int(clip_id)}?k={play_key(clip_id, user_id)}"


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """(first, last) byte for a `Range: bytes=a-b` header; None for none or one this will not honour (send it all)."""
    if not header or size <= 0:
        return None
    m = re.fullmatch(r"\s*bytes=(\d*)-(\d*)\s*", header)
    if not m or (not m.group(1) and not m.group(2)):
        return None
    if not m.group(1):                       # the last N bytes
        n = int(m.group(2))
        if n <= 0:
            return None
        return max(0, size - n), size - 1
    first = int(m.group(1))
    last = int(m.group(2)) if m.group(2) else size - 1
    if first >= size or last < first:
        return (-1, -1)                      # unsatisfiable
    return first, min(last, size - 1)
