"""Suggested videos: a weekly YouTube scan whose finds a coach can add with one tap.

Nothing here reaches an athlete. The scan fills `video_suggestions`; a coach reads each one on the
dashboard (with a link to watch it) and taps Add or Dismiss. Add goes through `Store.create_clip`,
the same door as a pasted link, so the age caps and the highlight-reel refusal still bind.

Why YouTube only: it is the one place a find can become a clip a kid can watch with attention
tracking (IFrame API) and a coach can verify. TikTok, Instagram and Facebook offer no search without
a reviewed developer account, no embed with playback telemetry, and no captions to check.

What a machine can check, and does: public, embeddable, not age-restricted, English, a length that
fits an age band, lacrosse in the title or tags, no highlight-reel or other-game wording, no swearing
in the words a coach will read. What it cannot: whether the coaching is right. That is why the coach
watches it first and why nothing is added automatically.

The API key (OFFDAYS_YOUTUBE_API_KEY) is read from the server's environment, sent only to Google,
and never appears in an error, a log line or a response.
"""

from __future__ import annotations

import json
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from . import film, iq_shelf
from .config import CONFIG
from .db import transaction

#: How many pending suggestions a program is ever shown. A list a coach has to wade through is a list
#: nobody reads, and each search costs quota.
MAX_PENDING = 40
#: A search costs 100 of YouTube's 10,000 free daily units. Weekly, this is a small share.
MAX_SEARCHES_PER_RUN = 12
#: videos.list takes 50 ids a call and costs one unit.
DETAILS_BATCH = 50
#: The longest clip a young person can be shown. The top band (19+, 240 s) is adults only, and a shelf
#: that drifts that way quietly stops being for children, so anything past 17-18's ceiling is refused.
LONGEST_S = max(b.clip_max_s for b in film.BANDS if b.min_age <= 17)
SHORTEST_S = 15

#: Each is about reading the game, not drilling a skill. A few ask for Shorts. Rotated through a
#: week at a time so a full cycle covers all of them.
QUERIES: tuple[str, ...] = (
    "lacrosse film study off ball movement", "lacrosse film breakdown slide defense", "lacrosse film study clearing",
    "lacrosse film breakdown riding", "lacrosse film breakdown transition decision", "lacrosse film study ground ball",
    "lacrosse film breakdown two man game", "lacrosse film study 1-4-1 offense", "lacrosse film breakdown crease play",
    "lacrosse goalie film study angles", "lacrosse faceoff wing film breakdown", "lacrosse man down defense film",
    "lacrosse defense communication help film", "lacrosse offense spacing film study", "lacrosse teach tape defender",
    "lacrosse how to read a slide", "lacrosse what to look for watching film", "lacrosse shot clock decision making",
    "lacrosse fast break 3 on 2 decision", "lacrosse approach angle defense film", "lacrosse picks off ball film study",
    "lacrosse iq #shorts", "lacrosse film study #shorts", "lacrosse defense tip #shorts", "lacrosse off ball #shorts",
    "lacrosse clear #shorts", "lacrosse ride #shorts", "lacrosse slide #shorts",
)

#: Wording that means a video teaches nothing or is for another game.
_REEL = re.compile(
    r"\b(highlights?|mix(?:tape)?|recruit\w*|top\s*\d+|best plays|goals of|beat drop|official video|"
    r"vlog|podcast|interview|reaction|unboxing|giveaway|merch|commit(?:ment)?|signing|rankings?)\b", re.I)
_OTHER_GAME = re.compile(
    r"\b(box lacrosse|indoor lacrosse|nll|women'?s|womens|girls?|female|wlax|draw control|8.?meter|12.?meter|"
    r"hockey|soccer|football|basketball|baseball|softball|field hockey)\b", re.I)
_LANGUAGE = re.compile(
    r"(\bf+u+c+k\w*|\bf+\*+|\bs+h+i+t\w*|\bs+\*+t\b|\bb+i+t+c+h\w*|\bdamn\w*|\bass(?:hole)?\b|\bcrap\b|\bwtf\b|"
    r"\bpiss\w*|\bdick\b|\bbastard\b)", re.I)
_LACROSSE = re.compile(r"\b(lacrosse|lax)\b", re.I)
_IQ = re.compile(
    r"\b(film|breakdown|study|read\w*|iq|spac\w+|slide\w*|cut\w*|decision\w*|communicat\w+|rotat\w+|recover\w*|"
    r"transition|clear\w*|ride|riding|angle\w*|mismatch|off.?ball|teach tape|principles?|why|how)\b", re.I)
_GOALIE = re.compile(r"\bgoalie|goalkeeper|keeper\b", re.I)

#: Concept -> a "what to watch for" a coach can accept or rewrite. True of any good clip on the idea.
_FOCUS = {
    "goalie": "Watch where the goalie stands and what they are reading before the shot.",
    "slide": "Watch the defenders who do not have the ball. Who moves, and who covers for them?",
    "cut": "Watch the player without the ball. When do they move, and what is their defender looking at?",
    "spacing": "Look at the gaps between teammates. Who is bunched up, and who is spread out?",
    "clear": "Listen for where players go, and why, the moment the ball changes hands.",
    "transition": "Watch the first few seconds after the ball changes hands.",
    "default": "Before the pass or the dodge, ask what the player saw that made them choose it.",
}


class ScoutError(Exception):
    """A YouTube call failed. Never carries the key, the URL or the underlying exception."""

    def __init__(self, reason: str, *, quota: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.quota = quota


@dataclass(frozen=True)
class Candidate:
    video_id: str
    title: str
    channel: str
    duration_s: int
    min_age: int
    concept: str
    reason: str
    score: float
    views: int = 0
    published: str = ""


def parse_duration(iso: str | None) -> int | None:
    """ISO-8601 duration (PT1M30S) to seconds, or None if it is not one."""
    if not iso:
        return None
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m or not any(m.groups()):
        return None
    h, mi, s = (int(g or 0) for g in m.groups())
    return h * 3600 + mi * 60 + s


def _placement(seconds: int) -> int | None:
    """Youngest age that may be shown a clip this long, by the film caps. None if over every cap."""
    for band in film.BANDS:
        if seconds <= band.clip_max_s:
            return band.min_age if band.min_age > 0 else 0
    return None


def _concept(text: str) -> str:
    low = text.lower()
    if _GOALIE.search(low):
        return "goalie"
    for key, pat in (("slide", r"slide|slides|hot|recover"), ("cut", r"cut|cuts|cutting|off.?ball|backdoor"),
                     ("spacing", r"spac\w+"), ("clear", r"clear|ride|riding"), ("transition", r"transition|fast break")):
        if re.search(pat, low):
            return key
    return "default"


def assess(video: dict[str, Any], known: set[str]) -> Candidate | str:
    """A Candidate if this video qualifies, otherwise the reason it does not (a short code)."""
    vid = video.get("id") or ""
    if vid in known:
        return "known"
    snippet = video.get("snippet") or {}
    status = video.get("status") or {}
    details = video.get("contentDetails") or {}
    if status.get("privacyStatus") != "public":
        return "not_public"
    if not status.get("embeddable", False):
        return "not_embeddable"
    if (details.get("contentRating") or {}).get("ytRating") == "ytAgeRestricted":
        return "age_restricted"
    lang = (snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage") or "en").lower()
    if not lang.startswith("en"):
        return "not_english"
    seconds = parse_duration(details.get("duration"))
    if seconds is None or seconds < SHORTEST_S:
        return "too_short"
    if seconds > LONGEST_S:
        return "too_long"

    title = snippet.get("title") or ""
    tags = " ".join(snippet.get("tags") or [])
    desc = (snippet.get("description") or "")[:600]
    about = f"{title} {tags}"
    if not _LACROSSE.search(about):
        return "not_lacrosse"
    if _OTHER_GAME.search(about) or _OTHER_GAME.search(desc[:200]):
        return "other_game"
    if _REEL.search(title):
        return "highlight_reel"
    if _LANGUAGE.search(f"{title} {tags} {desc}"):
        return "language"

    concept = _concept(about)
    score = 1.0 + 0.6 * min(len(_IQ.findall(about)), 5)
    if (details.get("caption") or "").lower() == "true":
        score += 0.8
    views = int(((video.get("statistics") or {}).get("viewCount")) or 0)
    score += min(views, 100_000) / 100_000
    age = _placement(seconds)
    placed = {0: "for all ages, including the youngest", 11: "for ages 11 and up", 13: "for ages 13 and up",
              15: "for ages 15 and up", 17: "for ages 17 and up"}.get(age or 0, "")
    reason = (
        f"{'Short clip' if seconds <= 75 else 'Film breakdown'} about "
        f"{ {'goalie': 'goalie play', 'slide': 'slides and recovery', 'cut': 'off-ball movement', 'spacing': 'spacing', 'clear': 'clearing and riding', 'transition': 'transition', 'default': 'decision-making'}[concept] }"
        f", {seconds} seconds, short enough {placed}."
    )
    return Candidate(
        video_id=vid, title=title.strip(), channel=snippet.get("channelTitle") or "", duration_s=seconds,
        min_age=age or 0, concept=concept, reason=reason, score=round(score, 3), views=views,
        published=(snippet.get("publishedAt") or "")[:10],
    )


def queries_for(week: int, n: int = MAX_SEARCHES_PER_RUN) -> list[str]:
    """The queries for one run, advancing through the whole list so every one gets a turn."""
    total = len(QUERIES)
    n = min(n, total)
    start = (week * n) % total
    return [QUERIES[(start + i) % total] for i in range(n)]


class YouTubeApi:
    """The two YouTube Data API calls the scanner needs. The key is only ever put in the request."""

    BASE = "https://www.googleapis.com/youtube/v3"

    def __init__(self, key: str, opener: Callable[..., Any] | None = None) -> None:
        self._key = key
        self._open = opener or urllib.request.urlopen

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        url = f"{self.BASE}/{path}?{urllib.parse.urlencode({**params, 'key': self._key})}"
        try:
            with self._open(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            reason, quota = f"http_{exc.code}", False
            try:
                errors = json.loads(exc.read().decode("utf-8")).get("error", {}).get("errors", [])
                if errors:
                    reason = str(errors[0].get("reason") or reason)
                    quota = reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded")
            except Exception:  # noqa: BLE001 - the body is only for the reason code
                pass
            err = ScoutError(reason, quota=quota)
        except (urllib.error.URLError, TimeoutError, OSError):
            err = ScoutError("network")
        except (ValueError, json.JSONDecodeError):
            err = ScoutError("bad_response")
        # Raised outside the except block so the original exception, whose text can contain the
        # request URL and so the key, is not chained to this one.
        raise err

    def search(self, query: str, *, short: bool = False) -> list[str]:
        params = {
            "part": "snippet", "q": query, "type": "video", "maxResults": "25", "order": "relevance",
            "safeSearch": "strict", "videoEmbeddable": "true", "relevanceLanguage": "en",
            "videoDuration": "short" if short else "any",
        }
        data = self._get("search", params)
        return [i["id"]["videoId"] for i in data.get("items", []) if (i.get("id") or {}).get("videoId")]

    def details(self, ids: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i in range(0, len(ids), DETAILS_BATCH):
            chunk = ids[i:i + DETAILS_BATCH]
            data = self._get("videos", {"part": "snippet,contentDetails,status,statistics", "id": ",".join(chunk)})
            out.extend(data.get("items", []))
        return out


def api_from_config() -> YouTubeApi | None:
    key = getattr(CONFIG, "youtube_api_key", "") or ""
    return YouTubeApi(key) if key else None


def enabled() -> bool:
    return bool(getattr(CONFIG, "youtube_api_key", ""))


# ---------------------------------------------------------------------------
# The scan
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _known(conn: sqlite3.Connection) -> set[str]:
    """Videos not worth suggesting to anyone: the built-in shelf's, and anything already decided."""
    known = {c.video_id for shelf in iq_shelf.SHELVES.values() for c in shelf}
    known |= {r["video_id"] for r in conn.execute("SELECT video_id FROM video_suggestions")}
    return known


def scan(conn: sqlite3.Connection, api: Any | None, *, week: int | None = None) -> dict[str, Any]:
    """One weekly run. Adds suggestions, withdraws ones that no longer qualify, records the result."""
    if api is None:
        return {"ran": False, "reason": "no key", "added": 0}
    if week is None:
        week = datetime.now(timezone.utc).isocalendar().week
    known = _known(conn)
    found: dict[str, Candidate] = {}
    rejected: dict[str, int] = {}
    stopped = ""
    searched = 0

    ids_seen: list[str] = []
    # Suggestions already on offer are looked up again (50 ids cost one unit) so a video that was
    # taken down, made private or had embedding switched off since stops being offered.
    recheck = [r["video_id"] for r in conn.execute(
        "SELECT video_id FROM video_suggestions WHERE withdrawn = 0")]
    for query in queries_for(week):
        try:
            ids = api.search(query, short="#shorts" in query)
        except ScoutError as exc:
            stopped = exc.reason
            break
        searched += 1
        for vid in ids:
            if vid not in known and vid not in ids_seen:
                ids_seen.append(vid)

    details: list[dict[str, Any]] = []
    looked_up = False
    to_look_up = list(dict.fromkeys(ids_seen + recheck))
    if to_look_up:
        try:
            details = api.details(to_look_up)
            looked_up = True
        except ScoutError as exc:
            stopped = stopped or exc.reason
    for video in details:
        if video.get("id") in recheck:
            continue            # already a suggestion; judged for withdrawal below, not as a new find
        verdict = assess(video, known)
        if isinstance(verdict, Candidate):
            found[verdict.video_id] = verdict
        else:
            rejected[verdict] = rejected.get(verdict, 0) + 1

    pending = int(conn.execute("SELECT COUNT(*) FROM video_suggestions WHERE withdrawn = 0").fetchone()[0])
    room = max(0, MAX_PENDING - pending)
    added = 0
    with transaction(conn) as c:
        # A suggestion YouTube no longer returns as playable is withdrawn. A video that has been
        # deleted or made private is simply absent from the answer, so absence counts. Only when the
        # lookup itself succeeded: a network error must not empty a coach's list.
        if looked_up:
            still_ok = {v["id"] for v in details if isinstance(assess(v, set()), Candidate)}
            for r in c.execute("SELECT id, video_id FROM video_suggestions WHERE withdrawn = 0").fetchall():
                if r["video_id"] in recheck and r["video_id"] not in still_ok:
                    c.execute("UPDATE video_suggestions SET withdrawn = 1 WHERE id = ?", (r["id"],))
        for cand in sorted(found.values(), key=lambda x: -x.score)[:room]:
            c.execute(
                "INSERT OR IGNORE INTO video_suggestions(video_id, title, channel, seconds, min_age, concept, reason, "
                "score, views, published, found_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (cand.video_id, cand.title, cand.channel, cand.duration_s, cand.min_age, cand.concept, cand.reason,
                 cand.score, cand.views, cand.published, _now()),
            )
            added += 1
        c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('video_scout_last', ?)",
                  (json.dumps({"at": _now(), "added": added, "searched": searched, "stopped": stopped}),))
    return {"ran": True, "added": added, "searched": searched, "stopped": stopped, "rejected": rejected}


def last_scan(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute("SELECT value FROM meta WHERE key = 'video_scout_last'").fetchone()
    return json.loads(row["value"]) if row else None


def status(conn: sqlite3.Connection) -> dict[str, Any]:
    return {"enabled": enabled(), "last_scan": last_scan(conn)}


# ---------------------------------------------------------------------------
# What a program sees, and what it can do
# ---------------------------------------------------------------------------

def _decided(conn: sqlite3.Connection, org_id: int, suggestion_id: int) -> str | None:
    r = conn.execute(
        "SELECT decision FROM video_suggestion_decisions WHERE org_id = ? AND suggestion_id = ?",
        (org_id, suggestion_id),
    ).fetchone()
    return r["decision"] if r else None


def pending_for(conn: sqlite3.Connection, org_id: int, sport: str = "lacrosse", limit: int = 30) -> list[dict[str, Any]]:
    """What this program has not yet decided on, best first."""
    own = {r["video_id"] for r in conn.execute("SELECT video_id FROM clips WHERE org_id = ? AND shelf = ''", (org_id,))}
    rows = conn.execute(
        "SELECT s.* FROM video_suggestions s WHERE s.withdrawn = 0 AND NOT EXISTS ("
        "  SELECT 1 FROM video_suggestion_decisions d WHERE d.org_id = ? AND d.suggestion_id = s.id) "
        "ORDER BY s.score DESC, s.id", (org_id,),
    ).fetchall()
    out = []
    for r in rows:
        if r["video_id"] in own:
            continue
        out.append({
            "id": int(r["id"]), "video_id": r["video_id"], "title": r["title"], "channel": r["channel"],
            "seconds": int(r["seconds"]), "min_age": int(r["min_age"]), "reason": r["reason"],
            "concept": r["concept"], "published": r["published"],
            "watch_url": f"https://www.youtube.com/watch?v={r['video_id']}",
            "focus_default": _FOCUS.get(r["concept"], _FOCUS["default"]),
        })
        if len(out) >= limit:
            break
    return out


def _row(conn: sqlite3.Connection, suggestion_id: int):
    from .store import StoreError

    row = conn.execute("SELECT * FROM video_suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    if row is None:
        raise StoreError("no such suggestion")
    return row


def dismiss(conn: sqlite3.Connection, org_id: int, user_id: int, suggestion_id: int) -> None:
    from .store import StoreError

    _row(conn, suggestion_id)
    if _decided(conn, org_id, suggestion_id):
        raise StoreError("this program has already decided on that one")
    with transaction(conn) as c:
        c.execute(
            "INSERT INTO video_suggestion_decisions(org_id, suggestion_id, decision, decided_by, decided_at) "
            "VALUES (?,?,?,?,?)", (org_id, suggestion_id, "dismissed", user_id or None, _now()),
        )


def add(
    store: Any, org_id: int, user_id: int, suggestion_id: int, *,
    title: str | None = None, focus: str | None = None, min_age: int | None = None,
) -> dict[str, Any]:
    """Turn a suggestion into one of the program's own clips. Same rules as pasting a link."""
    from .store import StoreError

    conn = store.conn
    row = _row(conn, suggestion_id)
    if row["withdrawn"]:
        raise StoreError("that video is no longer available to suggest")
    if _decided(conn, org_id, suggestion_id):
        raise StoreError("this program has already decided on that one")
    if conn.execute("SELECT 1 FROM clips WHERE org_id = ? AND video_id = ? AND active = 1 AND shelf = ''",
                    (org_id, row["video_id"])).fetchone():
        raise StoreError("that video is already one of this program's clips")

    floor = int(row["min_age"])                       # what the clip's own length allows
    age = max(floor, int(min_age)) if min_age is not None else floor
    positions = ["goalie"] if row["concept"] == "goalie" else []
    clip = store.create_clip(
        org_id, row["video_id"], (title or row["title"]).strip()[:160],
        focus=(focus or _FOCUS.get(row["concept"], _FOCUS["default"])).strip()[:400],
        start_s=0, end_s=int(row["seconds"]), positions=positions, min_age=age, created_by=user_id or None,
    )
    credit = row["channel"] or ""
    with transaction(conn) as c:
        c.execute("UPDATE clips SET credit = ? WHERE id = ?", (credit, clip["id"]))
        c.execute(
            "INSERT INTO video_suggestion_decisions(org_id, suggestion_id, decision, decided_by, decided_at) "
            "VALUES (?,?,?,?,?)", (org_id, suggestion_id, "added", user_id or None, _now()),
        )
    return {**clip, "credit": credit}
