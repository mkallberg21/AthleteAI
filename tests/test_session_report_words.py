"""What a coach, director or parent reads about one session says what happened, in words that fit the drill.

Three things a director saw on a real report: a strong-hand set stored as part left and part right; a hand split that did
not add up to the reps ("13 reps (0 L / 12 R)"); and a ground ball session shown as "0 reps, held 30s" with a note about a
plank.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from offdays import integrity, quality
from offdays.db import connect
from offdays.drills import DRILLS_BY_KEY
from offdays.integrity import RepEvent, SessionClaim
from offdays.store import Store

STATIC = Path(__file__).resolve().parent.parent / "offdays" / "web" / "static"
STRONG = DRILLS_BY_KEY["lax_wall_ball_strong"]
GROUND = DRILLS_BY_KEY["lax_ground_ball_everyday"]


def reps(hands, gap=1500):
    return [RepEvent(t_ms=1000 + i * gap, hand=h, confidence=0.9) for i, h in enumerate(hands)]


class TestOneHandSetsAreSettledOnTheServer:
    def test_the_python_list_matches_the_one_on_the_phone(self):
        js = (STATIC / "counter.js").read_text(encoding="utf-8")
        listed = re.search(r"SINGLE_HAND_DRILLS = new Set\(\[([^\]]+)\]\)", js).group(1)
        assert set(re.findall(r"'([a-z_]+)'", listed)) == set(integrity.SINGLE_HAND_DRILLS)
        assert all(k in DRILLS_BY_KEY and DRILLS_BY_KEY[k].tracks_handedness for k in integrity.SINGLE_HAND_DRILLS)

    def test_a_misread_rep_takes_the_hand_most_reps_named(self):
        out = integrity.settle_hands(reps(["none", "left", "right", "right", "right", "right"]), STRONG)
        assert [r.hand for r in out] == ["none", "right", "right", "right", "right", "right"]

    def test_a_rep_whose_hand_was_not_read_is_not_given_one(self):
        out = integrity.settle_hands(reps(["none"] * 24 + ["right"] * 4 + ["left"]), STRONG)
        assert sum(r.hand == "none" for r in out) == 24 and sum(r.hand == "right" for r in out) == 5

    def test_a_tie_and_other_drills_are_left_alone(self):
        tie = reps(["left", "right"])
        assert integrity.settle_hands(tie, STRONG) is tie
        both = DRILLS_BY_KEY["lax_wall_ball_quick_stick"] if "lax_wall_ball_quick_stick" in DRILLS_BY_KEY else None
        other = next(d for d in DRILLS_BY_KEY.values() if d.tracks_handedness and d.key not in integrity.SINGLE_HAND_DRILLS)
        mixed = reps(["left", "right", "right"])
        assert integrity.settle_hands(mixed, both or other) is mixed

    def test_the_reps_it_was_given_are_not_changed(self):
        given = reps(["left", "right", "right"])
        integrity.settle_hands(given, STRONG)
        assert [r.hand for r in given] == ["left", "right", "right"]


@pytest.fixture
def world(tmp_path):
    store = Store(connect(tmp_path / "rw.db"))
    org = store.create_org("Nashville Dogs")
    kid = store.create_user(org, "athlete", "Parker Browne", birth_year=2013)
    yield store, kid["id"]


def submit(store, kid, drill, hands=(), duration_ms=30_000, hold_ms=0):
    s = store.start_session(kid, drill)
    payload = [{"t_ms": 1000 + i * 2200, "hand": h, "confidence": 0.9} for i, h in enumerate(hands)]
    return store.submit_session(kid, s["session_id"], s["nonce"], duration_ms=duration_ms, reps=payload,
                                hold_ms=hold_ms, mean_confidence=0.9, client_version="web-0.1.0")


class TestWhatIsStored:
    def test_an_old_phone_cannot_store_a_strong_hand_set_as_two_hands(self, world):
        store, kid = world
        out = submit(store, kid, "lax_wall_ball_strong", ["none"] + ["right"] * 9 + ["left"] * 3)
        assert (out["reps_total"], out["reps_left"], out["reps_right"]) == (13, 0, 12)
        row = store.conn.execute("SELECT reps_left, reps_right FROM sessions").fetchone()
        assert tuple(row) == (0, 12)
        assert sorted({r[0] for r in store.conn.execute("SELECT hand FROM rep_events")}) == ["none", "right"]

    def test_the_log_says_what_kind_of_number_each_drill_gives(self, world):
        store, kid = world
        submit(store, kid, "lax_wall_ball_strong", ["right"] * 13)
        submit(store, kid, "lax_ground_ball_everyday", duration_ms=78_760, hold_ms=29_765)
        by = {s["drill_key"]: s for s in store.drill_log(kid, 7)["sessions"]}
        wall, ground = by["lax_wall_ball_strong"], by["lax_ground_ball_everyday"]
        assert (wall["measure"], wall["sides"], wall["one_hand"]) == ("reps", True, True)
        assert (ground["measure"], ground["hold_s"], ground["duration_s"]) == ("moving", 30, 79)
        assert ground["sides"] is False and ground["one_hand"] is False

    def test_a_plank_is_still_a_hold(self, world):
        store, kid = world
        plank = next(d for d in DRILLS_BY_KEY.values()
                     if d.metric.name == "HOLD_SECONDS" and d.signal.kind.name != "FOOTWORK_MOTION")
        submit(store, kid, plank.key, duration_ms=70_000, hold_ms=65_000)
        assert store.drill_log(kid, 7)["sessions"][0]["measure"] == "hold"


class TestMovementDrillWords:
    def test_ground_balls_are_never_called_a_plank_or_given_a_form_score(self):
        r = quality.analyze(GROUND, [], hold_ms=29_765, duration_ms=78_760)
        assert r.score is None and r.components == []
        assert "plank" not in r.coaching_note.lower() and "38%" in r.coaching_note
        assert "head to feet" in r.coaching_note

    def test_moving_nearly_the_whole_time_is_said_plainly(self):
        assert quality.analyze(GROUND, [], hold_ms=58_000, duration_ms=62_000).coaching_note == \
            "You kept moving nearly the whole time."

    def test_a_real_plank_keeps_its_own_words(self):
        plank = next(d for d in DRILLS_BY_KEY.values()
                     if d.metric.name == "HOLD_SECONDS" and d.signal.kind.name != "FOOTWORK_MOTION" and d.quality)
        assert "plank" in quality.analyze(plank, [], hold_ms=10_000, duration_ms=60_000).coaching_note

    def test_the_note_on_a_short_session_says_moving_not_hold(self):
        out = integrity.evaluate(SessionClaim(drill_key=GROUND.key, duration_ms=78_760, hold_ms=29_765,
                                              mean_confidence=0.8), GROUND)
        assert "Moving for 30s of a 79s recording, below the 60s minimum." in out.notes
        assert not any(n.startswith("Hold of") for n in out.notes)


class TestTheRowACoachReads:
    """sessionWhat() in coach.html, run in Node against the three rows from the real report."""

    @pytest.fixture(scope="class")
    def what(self, tmp_path_factory):
        import json
        import subprocess
        html = (STATIC / "coach.html").read_text(encoding="utf-8")
        a = html.index("function ddClock(sec)")
        b = html.index("function renderAthleteDetail(d, days)")
        rows = {
            "ground": {"measure": "moving", "reps": 0, "left": 0, "right": 0, "hold_s": 30, "duration_s": 79, "sides": False, "one_hand": False},
            "clean": {"measure": "reps", "reps": 13, "left": 0, "right": 12, "sides": True, "one_hand": True},
            "mostly_unread": {"measure": "reps", "reps": 29, "left": 0, "right": 5, "sides": True, "one_hand": True},
            "all_right": {"measure": "reps", "reps": 20, "left": 0, "right": 20, "sides": True, "one_hand": True},
            "none_read": {"measure": "reps", "reps": 9, "left": 0, "right": 0, "sides": True, "one_hand": True},
            "old_split": {"measure": "reps", "reps": 40, "left": 17, "right": 21, "sides": True, "one_hand": True},
            "two_hands": {"measure": "reps", "reps": 30, "left": 12, "right": 15, "sides": True, "one_hand": False},
            "no_sides": {"measure": "reps", "reps": 25, "left": 0, "right": 0, "sides": False, "one_hand": False},
            "plank": {"measure": "hold", "reps": 0, "left": 0, "right": 0, "hold_s": 95, "duration_s": 100, "sides": False, "one_hand": False},
        }
        f = tmp_path_factory.mktemp("js") / "what.mjs"
        f.write_text(html[a:b] + f"\nconst rows = {json.dumps(rows)};\nconst out = {{}};\n"
                     "for (const [k, v] of Object.entries(rows)) out[k] = sessionWhat(v).replace(/<[^>]+>/g, '');\n"
                     "console.log(JSON.stringify(out));\n", encoding="utf-8")
        return json.loads(subprocess.run(["node", str(f)], capture_output=True, text=True, check=True).stdout)

    def test_ground_balls_are_time_moving_not_reps_or_a_hold(self, what):
        assert what["ground"] == "moving 30s of a 1m 19s recording"

    def test_a_one_hand_set_names_the_hand_and_what_was_not_read(self, what):
        assert what["clean"] == "13 reps (right hand on 12, hand not read on 1)"
        assert what["mostly_unread"] == "29 reps (right hand on 5, hand not read on 24)"
        assert what["all_right"] == "20 reps (right hand)"
        assert what["none_read"] == "9 reps (hand not read)"

    def test_every_split_adds_up_to_the_reps(self, what):
        for key in ("clean", "mostly_unread", "old_split", "two_hands"):
            total = int(what[key].split(" reps")[0])
            assert sum(int(n) for n in re.findall(r"\d+", what[key].split("(", 1)[1])) == total, what[key]

    def test_older_rows_and_two_hand_drills_still_read_sensibly(self, what):
        assert what["old_split"] == "40 reps (17 L / 21 R / 2 not read)"
        assert what["two_hands"] == "30 reps (12 L / 15 R / 3 not read)"
        assert what["no_sides"] == "25 reps" and what["plank"] == "held 1m 35s"
