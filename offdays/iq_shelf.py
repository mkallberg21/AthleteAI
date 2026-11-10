"""The default Lacrosse IQ shelf: what players watch until a program adds its own.

A program that never adds a clip still gets a working film shelf. These are YouTube videos
chosen because someone talks over game footage (or on camera) about *reading* the game -- spacing,
cuts, slides, clears, decisions -- with a few fundamentals mixed in for the youngest players. They
play in YouTube's own embedded player; nothing is downloaded or re-hosted, so each video's owner
keeps control of it.

What was checked by machine, for every id below: it was public and embeddable when listed, its
length fits the age band it is placed in, captions show someone speaking for most of it, and the
captions carry no profanity. What was NOT and cannot be checked by a machine: that the lesson is
correct and the footage matches the voice. A person who knows lacrosse should watch each one -- the
coach's "Default shelf" card lists them all with a preview link and a Hide button, and a hidden clip
is never offered to that program again.

Three product rules live here:

* **Program clips come first.** The shelf only fills the room a program's own clips leave.
* **It comes round again.** A clip a player has watched is due again after `REVISIT_AFTER_DAYS`
  (sooner after a missed question), so it is seen a couple of times a month rather than once and
  forgotten. A second look earns no XP and costs none -- that rule is in `rewatch.py`.
* **Age caps still bind.** Each clip is placed by its own length against `film.BANDS`, and the daily
  allowance is unchanged, so a default shelf can never make film into homework.

Only lacrosse has a shelf today. Another sport is a new tuple in `SHELVES` and nothing else.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import curriculum, film
from .db import transaction

#: A watched clip is offered again after this many days...
REVISIT_AFTER_DAYS = 14
#: ...or this many when the player's answer to its question was wrong.
MISSED_REVISIT_AFTER_DAYS = 7
#: Phones that could not play a clip before it stops being offered to a program.
UNAVAILABLE_LIMIT = 3
#: Fundamentals are marked by a ceiling on age rather than another column.
FUNDAMENTAL_MAX_AGE = 12


@dataclass(frozen=True)
class ShelfClip:
    video_id: str
    title: str
    credit: str
    end_s: int
    min_age: int
    #: FILM = game footage with a voice explaining it. TEACH = a person on camera explaining it.
    kind: str
    concept: str
    max_age: int = 200
    positions: tuple[str, ...] = ()
    fundamental: bool = False
    #: A curriculum topic whose comprehension question this clip answers (see curriculum.py).
    topic: str = ""

    @property
    def focus(self) -> str:
        return WATCH_FOR.get(self.concept, "Listen to what is said, then watch it again and see if you can spot it.")

    @property
    def question(self) -> dict[str, Any] | None:
        topic = curriculum.BY_KEY.get(self.topic)
        if topic is None:
            return None
        return {
            "prompt": topic.ask.prompt,
            "options": list(topic.ask.options),
            "answer": topic.ask.answer,
            "because": topic.ask.because,
        }


def _c(video_id, title, credit, end_s, min_age, kind, concept, **kw) -> ShelfClip:
    return ShelfClip(video_id, title, credit, end_s, min_age, kind, concept, **kw)


#: What to watch for, by idea. Written to be true of any good clip on the idea, because it is
#: shown above clips this module cannot watch.
WATCH_FOR = {
    "ground_ball": "Listen for what to do first when the ball is loose.",
    "fund_stance": "Watch the feet, the knees and the eyes. Then stand like that yourself.",
    "fund_catch": "Watch what the stick does at the moment the ball arrives.",
    "fund_protect": "Watch where the stick is held, and what that lets the player do next.",
    "cut": "Watch the player without the ball. When do they move, and what is their defender looking at?",
    "slide_def": "Watch the defenders who do not have the ball. Who moves, and who covers for them?",
    "slide_off": "Watch the dodger's eyes. Who are they looking at, and what does that freeze?",
    "decision": "Before the pass or the dodge, ask what the player saw that made them choose it.",
    "defense": "Watch the defender's feet and body. What are they taking away from the attacker?",
    "goalie": "Watch where the goalie stands and what they are reading before the shot.",
    "clear": "Listen for where players go, and why, the moment the ball changes hands.",
    "spacing": "Look at the gaps between teammates. Who is bunched up, and who is spread out?",
    "man_up": "Count the passes. Where does the ball go, and what does that do to the defense?",
    "transition": "Watch the first few seconds after the ball changes hands.",
    "crease": "Watch where the player on the crease stands as the ball moves.",
}

#: Placed youngest-first, and mixed within an age so a run of clips varies.
LACROSSE: tuple[ShelfClip, ...] = (
    _c("AFiymZBnscM", 'How to pick up "Ground Balls"', 'Bixby Ballers Lacrosse', 63, 7, "TEACH", "ground_ball", max_age=12, fundamental=True),
    _c("jXD8fNcyXv0", 'The Ultimate Guide to Youth Lacrosse - Defense Stance', 'ModusMindBody', 70, 7, "TEACH", "fund_stance", max_age=12, fundamental=True, topic="lax_fund_stance"),
    _c("4g4BflmOqMg", 'Lacrosse: Catching The Ball ("Soft Hands")', 'Laxlife Lacrosse', 58, 7, "TEACH", "fund_catch", max_age=12, fundamental=True, topic="lax_fund_soft_hands"),
    _c("y_iNHAPXbpg", 'Triple Threat Position - Boys Lacrosse', 'TeamSnap', 56, 7, "TEACH", "fund_protect", max_age=12, fundamental=True, topic="lax_fund_triple_threat"),
    _c("ETsu_iD3Fjs", 'Skills & Drills - Loose Balls', 'Panther City Lacrosse Club', 46, 7, "TEACH", "ground_ball", max_age=12, fundamental=True),
    _c("QKzdhwpyCI4", 'Laxlife Lacrosse: Dynamic Cradling', 'Laxlife Lacrosse', 22, 7, "TEACH", "fund_protect", max_age=12, fundamental=True),
    _c("EhHob2bjZyM", '1 Minute Film Study: Off-ball cutting', 'LacrosseStuff', 57, 9, "FILM", "cut", topic="lax_iq_cut_on_head_turn"),
    _c("7C7dVdOki7Y", '1 Minute Film Study: Using a defender as a screen', 'LacrosseStuff', 61, 9, "FILM", "decision"),
    _c("URWc2fNWwIs", '5 Ways to Make More 1-on-1 Saves - Goaliesmith Lacrosse', 'Goaliesmith', 51, 9, "TEACH", "goalie", positions=("goalie",)),
    _c("cyzQgmz3dDU", 'Outlet Passing Tips for Lacrosse Goalies', "DICK'S", 74, 9, "TEACH", "clear", positions=("goalie",)),
    _c("5WpdE6i-az8", 'Spacing on Offense', 'POWLAX l Patrick Chapla', 24, 9, "TEACH", "spacing", topic="lax_iq_space_without_ball"),
    _c("rVtoHCHvluU", 'Understanding the Substitution Box in Lacrosse', "DICK'S", 45, 9, "TEACH", "transition"),
    _c("7Pyiyzce8hM", 'Boys Lacrosse 2 Minute Drill Cutting In Motion Offense', 'KuddaSports', 71, 9, "TEACH", "cut"),
    _c("x2J1AhzmFeA", 'Harvard throws the skip pass and feeds the sneaking attackman', 'Scott “Urhotwithscott” Kellner', 62, 9, "FILM", "decision"),
    _c("3fyhjkIhZBc", 'Bonus: Pre-Dodge Spacing', 'Players Academy', 61, 9, "TEACH", "spacing"),
    _c("mwGYRjZXLNw", 'Cole Williams Dodging a Short Stick: Film Breakdown', 'Lacrosse All Stars', 36, 9, "FILM", "decision"),
    _c("ZLq9KkVyPis", 'Film Break Down: Hopkins slides against a Maryland 1-4-1 wing dodge', 'Lacrosse Film Room', 51, 11, "FILM", "slide_def"),
    _c("HVTU-A7D8_o", 'How to punch and push (defenders)', 'Premier Lacrosse League', 58, 11, "TEACH", "defense"),
    _c("eCBfptEeWPY", 'Learning Lacrosse: How to Pick up Ground Balls', "DICK'S", 93, 11, "TEACH", "ground_ball"),
    _c("XWLKRt0CC7w", 'How to catch a lacrosse ball', 'Premier Lacrosse League', 88, 11, "TEACH", "fund_catch", max_age=12, fundamental=True, topic="lax_fund_soft_hands"),
    _c("ScbT8leKB0k", 'Bullis HS, national champions: film breakdown', 'Lacrosse All Stars', 93, 11, "FILM", "cut"),
    _c("opJ20CN-Q60", 'What is a men’s principles based offense in Lacrosse', 'JM3 Sports | Lacrosse', 60, 11, "TEACH", "spacing"),
    _c("iXDQ1RG1qzA", 'Dave Cottle: The Attacking 1-4-1 Motion Offense', 'Championship Productions', 30, 11, "TEACH", "decision"),
    _c("Y0MD0fXxm_E", "How to Freeze the Slide Guy with Harvard's Jackson Greene", 'First Class Lacrosse', 56, 11, "FILM", "slide_off", topic="lax_iq_read_the_slide"),
    _c("aA_Wrek02Ig", 'Substitutions During A Clear', 'POWLAX l Patrick Chapla', 63, 11, "TEACH", "clear"),
    _c("rbL9yXyCXtQ", 'Defense Slide and Recovery', 'USA Lacrosse', 100, 11, "TEACH", "slide_def", topic="lax_iq_recover_after_slide"),
    _c("7rTfRzpdd6Y", 'Pick and roll defense: communication, switch, stay, turn', 'Laxlife Lacrosse', 28, 11, "TEACH", "defense"),
    _c("mryVnFhRj1w", "How to Dominate Off the Ball: Virginia Lacrosse' Xander Dickson", 'First Class Lacrosse', 76, 11, "FILM", "cut"),
    _c("pYRht8UEJlc", 'The Ultimate Guide to Youth Lacrosse - Off Ball Play', 'ModusMindBody', 99, 11, "TEACH", "spacing"),
    _c("TJiHmdfL2KU", 'Pairs Action from Ohio State', '36 Lacrosse', 29, 11, "FILM", "decision"),
    _c("5RNqhFzNmxA", 'Reading the Defense, Slide & Recovery', 'Josh McClendon', 67, 11, "FILM", "slide_off", topic="lax_iq_read_the_slide"),
    _c("klrA6xpoTG4", 'On Sides Responsibility', 'POWLAX l Patrick Chapla', 40, 11, "TEACH", "clear"),
    _c("plq8n99vouo", 'How To Play Defense', 'CoachUp', 81, 11, "TEACH", "defense"),
    _c("X2b8MR_gt7c", '1v1 Dodge by Charlie Kitchen: Delaware Film Breakdown', 'Lacrosse All Stars', 84, 11, "FILM", "decision"),
    _c("XEGBUh350DE", 'Film Break Down: Georgetown scores on 1-4-1 Mumbo-Pop', 'Lacrosse Film Room', 132, 13, "FILM", "slide_def"),
    _c("7TjFS3G_Wsk", 'Lacrosse IQ: Skip Vision', 'LaxFilmStudy HQ', 133, 13, "FILM", "decision"),
    _c("ZNJ4gjx1gsc", 'Hopkins Man Up play out of a 2-2-2', 'LaxPlayBook', 108, 13, "FILM", "man_up"),
    _c("eGL4ioDOY20", 'Cutting off the ball (IMG Academy, 1 of 10)', 'IMG Academy', 125, 13, "TEACH", "cut"),
    _c("VR-ghl1Ovzg", 'Flow Tips with Connor Martin - Ground Balls', 'Flow Society', 104, 13, "TEACH", "ground_ball"),
    _c("J_7i_tG8SmU", 'How To Execute A Proper Defensive Double Team', 'Lacrosse All Stars', 39, 13, "FILM", "defense"),
    _c("zzJxejKeTD0", '10 Principles of Transition Lacrosse Offense and Defense', 'SportsNationVideo.com', 32, 13, "TEACH", "transition"),
    _c("eNgVV6GuSDo", 'Boys Lacrosse Circle Offense Principles', 'KuddaSports', 132, 13, "TEACH", "spacing"),
    _c("vTShn0pbdJo", 'Inside Lacrosse Instruction: Crease Play with Ryan Boyle', 'Trilogy Lacrosse', 117, 13, "TEACH", "crease"),
    _c("OGNO355WXKY", 'Goalie: defending low-angle shots', 'Crease Coach', 136, 13, "TEACH", "goalie", positions=("goalie",)),
    _c("PhtnOZvN1I8", 'Lars Tiffany: How To Create a Strong Team Defense', 'Championship Productions', 37, 13, "TEACH", "slide_def"),
    _c("8ePGMen3Gw0", 'Matchup film room: Shellenberger vs. Zappitello', 'First Class Lacrosse', 119, 13, "FILM", "decision"),
    _c("_U8CqxWqz8o", 'How One Off-Ball Cut Creates a Goal', 'Next Read Lacrosse', 128, 13, "FILM", "cut"),
    _c("K4YvEXYgMac", 'Hang-up defense: Maryland v. Ohio State', 'Lacrosse All Stars', 60, 13, "FILM", "defense"),
    _c("l7uPBEo6lDQ", 'Installing the Sliding Defensive Lacrosse System', 'SportsNationVideo.com', 37, 13, "TEACH", "slide_def"),
    _c("LI2HKIXavrE", 'Bullis Double Pick', 'Lacrosse All Stars', 65, 13, "FILM", "decision"),
    _c("Bk0ce7Qu2Z8", 'Teach Defensemen How to Guard the Wing! - Lacrosse 2016', 'Championship Productions', 130, 13, "TEACH", "defense"),
    _c("w3uYm6ljHYg", '1 4 1 Wing Pick with a Seal & Pop on Crease', 'UKLaxfan', 19, 13, "FILM", "decision"),
    _c("zM_HP6zrIsI", 'The Complete Guide to Team Defense for Lacrosse', 'Championship Productions', 115, 13, "TEACH", "defense"),
    _c("POm_co-TLrY", 'How to Lacrosse Dodge Kyle Harrison: Midfield Dodging', 'The Lacrosse Network | TLN', 101, 13, "TEACH", "decision"),
    _c("rGLlLyXMJXU", 'Breaking Down the Johns Hopkins Extra Man Offense vs Navy', 'Lacrosse Film Room', 166, 15, "FILM", "man_up"),
    _c("yzXRZA28BBk", 'Elite Off-Ball Defense in Lacrosse', 'Next Read Lacrosse', 165, 15, "FILM", "slide_def"),
    _c("zcLXyak2_Sk", 'What you can learn from the #1 defender in the country', 'The Ride: Lacrosse Podcast', 164, 15, "FILM", "defense"),
    _c("tsyiDZ-LmYY", 'Film Break Down: Syracuse scores in the national championship game', 'Lacrosse Film Room', 168, 15, "FILM", "decision"),
    _c("3HJGSzyROXM", 'Man-up play: draw-up and film breakdown', 'The Lacrosse Lounge', 164, 15, "FILM", "man_up"),
    _c("AruW2jZIFXQ", 'Bill Tierney Whiteboard - The Crease Slide', 'Inside Lacrosse', 132, 15, "TEACH", "slide_def"),
    _c("UkXwonSo3vA", 'Defense Against the Big-Little With Dom Starsia', 'Championship Productions', 34, 15, "TEACH", "defense"),
    _c("8liz3Fu7DGU", 'Strategy Explained: Wheel Plays, Man-Up Rotation and Zone Offense', 'Lacrosse Film Room', 165, 15, "FILM", "man_up"),
    _c("Oso_nD6m5Es", 'Inside Lacrosse Instruction: Slides with Ronnie Staines', 'Trilogy Lacrosse', 149, 15, "TEACH", "slide_def"),
    _c("yvrhXVISjpQ", 'How Notre Dame Flows Between Offensive Sets', 'Next Read Lacrosse', 194, 17, "FILM", "decision"),
    _c("X-3EJT-d-00", "Paul Rabil's Tips for Offball Scoring", 'Paul Rabil', 195, 17, "TEACH", "cut"),
    _c("Uv5KtnSMwvk", 'Defend using a basic sliding package', 'Championship Productions', 194, 17, "TEACH", "slide_def"),
    _c("D7x5sRjN4to", 'Film Break Down: Syracuse fast break created by a Duke substitution mistake', 'Lacrosse Film Room', 195, 17, "FILM", "transition"),
    _c("yWLlZKJAUaI", 'Film Break Down: Duke scores against Syracuse zone defense', 'Lacrosse Film Room', 195, 17, "FILM", "decision"),
    _c("pZidjWvu_G0", 'Inside Lacrosse: the two-man game', 'Trilogy Lacrosse', 172, 17, "TEACH", "decision"),
)

#: A sport with no entry has no default shelf, and its programs see only their own clips.
SHELVES: dict[str, tuple[ShelfClip, ...]] = {"lacrosse": LACROSSE}

#: Changes whenever the shelf's content does, so a program's copy is refreshed on its next film view.
VERSION = hashlib.sha1(repr(LACROSSE).encode("utf-8")).hexdigest()[:10]


# ---------------------------------------------------------------------------
# Copying the shelf into a program
# ---------------------------------------------------------------------------

def _org(conn: sqlite3.Connection, org_id: int):
    return conn.execute(
        "SELECT sport, default_shelf FROM organizations WHERE id = ?", (org_id,)
    ).fetchone()


def available(conn: sqlite3.Connection, org_id: int) -> bool:
    """Does this program's sport have a shelf at all (whether or not it is switched on)?"""
    row = _org(conn, org_id)
    return bool(row) and (row["sport"] or "lacrosse") in SHELVES


def is_on(conn: sqlite3.Connection, org_id: int) -> bool:
    """A shelf exists for the sport AND the director has not turned it off."""
    row = _org(conn, org_id)
    return bool(row) and (row["sport"] or "lacrosse") in SHELVES and bool(row["default_shelf"])


def ensure(conn: sqlite3.Connection, org_id: int) -> int:
    """Copy the shelf into this program as real `clips` rows. Safe to call on every film view.

    Rows are keyed by video id within the program, so a hidden clip stays hidden and a restored one
    keeps its watch history. A refresh updates titles, lengths and questions but never touches
    `active` or `unavailable_n`, which belong to the program. Returns how many rows were added.
    """
    row = _org(conn, org_id)
    shelf = SHELVES.get((row["sport"] or "lacrosse") if row else "")
    if not shelf:
        return 0
    key = f"iq_shelf:{org_id}"
    done = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if done is not None and done["value"] == VERSION:
        return 0

    have = {
        r["video_id"]: int(r["id"])
        for r in conn.execute(
            "SELECT id, video_id FROM clips WHERE org_id = ? AND shelf = 'default'", (org_id,)
        )
    }
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    import json as _json

    added = 0
    with transaction(conn) as c:
        for clip in shelf:
            question = _json.dumps(clip.question) if clip.question else None
            positions = ",".join(clip.positions)
            if clip.video_id in have:
                c.execute(
                    "UPDATE clips SET title = ?, focus = ?, end_s = ?, positions = ?, min_age = ?, "
                    "max_age = ?, question = ?, credit = ? WHERE id = ?",
                    (clip.title, clip.focus, clip.end_s, positions, clip.min_age, clip.max_age,
                     question, clip.credit, have[clip.video_id]),
                )
            else:
                c.execute(
                    "INSERT INTO clips(org_id, provider, video_id, title, focus, start_s, end_s, "
                    "positions, min_age, max_age, question, active, created_by, created_at, "
                    "shelf, credit) VALUES (?,?,?,?,?,?,?,?,?,?,?,1,NULL,?,?,?)",
                    (org_id, "youtube", clip.video_id, clip.title, clip.focus, 0, clip.end_s,
                     positions, clip.min_age, clip.max_age, question, now, "default", clip.credit),
                )
                added += 1
        c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, VERSION))
    return added


# ---------------------------------------------------------------------------
# What to offer today
# ---------------------------------------------------------------------------

def is_fundamental(clip: film.Clip) -> bool:
    return clip.max_age <= FUNDAMENTAL_MAX_AGE


def pick(
    candidates: list[film.Clip],
    history: dict[int, tuple[str, bool]],
    *,
    today: date,
    room: int,
    young: bool = False,
    age: int | None = None,
) -> list[tuple[film.Clip, int | None]]:
    """Choose up to `room` shelf clips for one player today. Pure: no database, no clock.

    `history` maps clip id -> (last day watched, whether the answer was missed). A clip never
    watched is *new*; one watched is *due* once it has been `REVISIT_AFTER_DAYS` (a missed one,
    `MISSED_REVISIT_AFTER_DAYS`). New clips come first, in shelf order; due ones follow, the one
    seen longest ago first. New clips for the player's position first, then nearest the player's own age come first -- a seventeen-
    year-old is shown what was written for seventeen before anything meant for nine -- and the
    shelf's own order breaks ties. For `young` players new clips then alternate fundamental / IQ,
    so a nine-year-old gets a mix and not seven fundamentals in a row. Returns (clip, days_since)
    where days_since is None for a new clip.
    """
    if room <= 0:
        return []
    fresh: list[film.Clip] = []
    due: list[tuple[int, int, film.Clip]] = []
    for clip in candidates:
        seen = history.get(clip.id)
        if seen is None:
            fresh.append(clip)
            continue
        last, missed = seen
        gap = (today - date.fromisoformat(last)).days
        if gap >= (MISSED_REVISIT_AFTER_DAYS if missed else REVISIT_AFTER_DAYS):
            due.append((-gap, clip.id, clip))

    # A clip written for the player's own position leads (candidates only hold position-specific
    # clips for a player who matches them), then the nearest to their age; the shelf's own order
    # breaks ties. Without the first rule a goalie's four slots all go to age-matched field clips
    # and the goalie clips, written for younger players, would never come up.
    fresh.sort(key=lambda c: (0 if c.positions else 1, max(0, age - c.min_age) if age is not None else 0))
    if young:
        basics = [c for c in fresh if is_fundamental(c)]
        iq = [c for c in fresh if not is_fundamental(c)]
        mixed: list[film.Clip] = []
        while basics or iq:
            if basics:
                mixed.append(basics.pop(0))
            if iq:
                mixed.append(iq.pop(0))
        fresh = mixed

    out: list[tuple[film.Clip, int | None]] = [(c, None) for c in fresh]
    out += [(clip, -neg) for neg, _id, clip in sorted(due)]
    return out[:room]


# ---------------------------------------------------------------------------
# What a coach sees
# ---------------------------------------------------------------------------

def summary(conn: sqlite3.Connection, org_id: int, athlete_ids: list[int]) -> dict[str, Any]:
    row = _org(conn, org_id)
    sport = (row["sport"] if row else None) or "lacrosse"
    shelf = SHELVES.get(sport)
    if not shelf:
        return {"available": False, "sport": sport, "on": False, "total": 0, "clips": [],
                "athletes_watching": 0, "note": f"There is no default shelf for {sport} yet."}
    on = bool(row["default_shelf"])
    ensure(conn, org_id)
    kinds = {c.video_id: c for c in shelf}
    clips = []
    for r in conn.execute(
        "SELECT id, video_id, title, credit, start_s, end_s, min_age, max_age, active, unavailable_n "
        "FROM clips WHERE org_id = ? AND shelf = 'default' ORDER BY id", (org_id,),
    ):
        meta = kinds.get(r["video_id"])
        clips.append({
            "id": int(r["id"]), "video_id": r["video_id"], "title": r["title"], "credit": r["credit"],
            "seconds": int((r["end_s"] or 0) - (r["start_s"] or 0)),
            "min_age": int(r["min_age"]), "max_age": int(r["max_age"]),
            "kind": meta.kind if meta else "", "concept": meta.concept if meta else "",
            "hidden": not r["active"], "unavailable": int(r["unavailable_n"]),
            "watch_url": f"https://www.youtube.com/watch?v={r['video_id']}",
        })
    watching = 0
    if athlete_ids:
        since = (datetime.now(timezone.utc).date() - timedelta(days=27)).isoformat()
        marks = ",".join("?" * len(athlete_ids))
        watching = int(conn.execute(
            f"SELECT COUNT(DISTINCT w.athlete_id) FROM clip_watches w JOIN clips c ON c.id = w.clip_id "
            f"WHERE c.org_id = ? AND c.shelf = 'default' AND w.verdict = 'watched' AND w.day >= ? "
            f"AND w.athlete_id IN ({marks})", (org_id, since, *athlete_ids),
        ).fetchone()[0])
    return {
        "available": True, "sport": sport, "on": on, "total": len(clips),
        "visible": sum(1 for c in clips if not c["hidden"]),
        "clips": clips, "athletes_watching": watching,
        "revisit_after_days": REVISIT_AFTER_DAYS,
    }
