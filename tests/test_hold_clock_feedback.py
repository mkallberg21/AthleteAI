"""A two minute wall sit was credited one second, and the athlete was told "Only 1% of that was a real plank".

The clock on a hold only runs while the camera can see the position. Nothing here changes how the position is
measured; it makes sure the athlete is told while it can still be fixed, and that nobody is told something untrue after.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from offdays import integrity, quality
from offdays.drills import DRILLS_BY_KEY
from offdays.integrity import SessionClaim

STATIC = Path(__file__).resolve().parent.parent / "offdays" / "web" / "static"
WALL_SIT = DRILLS_BY_KEY["gen_wall_sit"]
PLANK = next(d for d in DRILLS_BY_KEY.values() if "plank" in d.name.lower() and d.metric.name == "HOLD_SECONDS")


class TestWhatTheAthleteIsToldAfter:
    def test_the_real_session_is_not_called_a_bad_plank(self):
        r = quality.analyze(WALL_SIT, [], hold_ms=826, duration_ms=129_270)
        note = r.coaching_note
        assert "plank" not in note.lower() and "Only" not in note
        assert "The clock ran for 1s of a 129s recording" in note and "wall sit" in note
        assert "usually the camera angle, not your effort" in note
        assert WALL_SIT.setup_hint in note, "it says how to set the phone up"

    def test_no_form_score_is_given_for_a_position_the_camera_never_saw(self):
        r = quality.analyze(WALL_SIT, [], hold_ms=826, duration_ms=129_270)
        assert r.score is None and r.components == []

    def test_a_short_recording_is_not_explained_away(self):
        r = quality.analyze(WALL_SIT, [], hold_ms=1_000, duration_ms=12_000)
        assert r.score is not None and "camera angle" not in r.coaching_note

    def test_a_wall_sit_held_half_the_time_is_scored_in_its_own_words(self):
        r = quality.analyze(WALL_SIT, [], hold_ms=30_000, duration_ms=60_000)
        assert r.score is not None and "plank" not in r.coaching_note.lower()
        assert "in position for 50%" in r.coaching_note

    def test_a_wall_sit_held_most_of_the_time_does_not_mention_hips_dropping(self):
        r = quality.analyze(WALL_SIT, [], hold_ms=48_000, duration_ms=60_000)
        assert "hips" not in r.coaching_note and "80%" in r.coaching_note

    def test_a_plank_keeps_its_plank_words(self):
        assert "real plank" in quality.analyze(PLANK, [], hold_ms=20_000, duration_ms=60_000).coaching_note
        assert "hips are dropping" in quality.analyze(PLANK, [], hold_ms=48_000, duration_ms=60_000).coaching_note

    def test_a_hold_held_the_whole_way_is_unchanged(self):
        r = quality.analyze(WALL_SIT, [], hold_ms=118_000, duration_ms=120_000)
        assert r.score == 100

    def test_the_staff_note_gives_both_numbers(self):
        out = integrity.evaluate(SessionClaim(drill_key=WALL_SIT.key, duration_ms=129_270, hold_ms=826,
                                              mean_confidence=0.98), WALL_SIT)
        assert any(n.startswith("Hold of 1s in a 129s recording is below the") for n in out.notes), out.notes


def node(script: str, tmp_path) -> dict:
    f = tmp_path / "t.mjs"
    f.write_text(script, encoding="utf-8")
    done = subprocess.run(["node", str(f)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


class TestWhatTheAthleteIsToldDuring:
    COUNTER = (STATIC / "counter.js").as_uri()

    def test_the_clock_standing_still_is_noticed_and_forgiven_when_it_moves(self, tmp_path):
        out = node(f"""
import {{ HoldWatch }} from '{self.COUNTER}';
const w = new HoldWatch();
const seen = [];
let hold = 0;
for (let t = 0; t <= 12000; t += 100) {{
  if (t >= 6000 && t < 9000) hold += 100;          // in position from 6s to 9s only
  const s = w.update(hold, t);
  if (!seen.length || seen[seen.length - 1][1] !== s) seen.push([t, s]);
}}
console.log(JSON.stringify({{ seen, after: HoldWatch.PAUSE_AFTER_MS }}));
""", tmp_path)
        assert out["seen"] == [[0, "running"], [2500, "paused"], [6000, "running"], [11400, "paused"]]

    def test_the_message_says_what_the_clock_needs_in_the_drills_own_words(self, tmp_path):
        out = node(f"""
import {{ holdPausedMessage }} from '{self.COUNTER}';
console.log(JSON.stringify({{
  sit: holdPausedMessage({{ signal: {{ kind: 'joint_angle' }}, setup_hint: {json.dumps(WALL_SIT.setup_hint)} }}),
  ground: holdPausedMessage({{ signal: {{ kind: 'footwork_motion' }}, setup_hint: 'Prop the phone far back.' }}),
  bare: holdPausedMessage({{ signal: {{ kind: 'joint_angle' }} }}),
}}));
""", tmp_path)
        assert out["sit"] == f"The clock is paused because the phone cannot see you in position. {WALL_SIT.setup_hint}"
        assert out["ground"].startswith("The clock is paused. It runs while you are moving")
        assert out["bare"] == "The clock is paused because the phone cannot see you in position."

    def test_the_capture_screen_uses_it_for_timed_drills(self):
        html = (STATIC / "capture.html").read_text(encoding="utf-8")
        assert "import { RepCounter, HoldWatch, holdPausedMessage } from './counter.js';" in html
        assert "holdWatch.update(counter.holdMs, performance.now()) === 'paused'" in html
        assert "setBanner(holdPausedMessage(activeDrill), true);" in html
        start = html.index("  setupGate = null;\n" if "  setupGate = null;\n" in html else "  setupGate = null;\r\n")
        assert "holdWatch = new HoldWatch();" in html[start:start + 120], "the watch starts fresh with each recording"


class TestTheRowACoachReads:
    def test_a_hold_far_shorter_than_the_recording_shows_both_numbers(self, tmp_path):
        html = (STATIC / "coach.html").read_text(encoding="utf-8")
        a, b = html.index("function ddClock(sec)"), html.index("function renderAthleteDetail(d, days)")
        out = node(html[a:b] + """
const strip = (s) => sessionWhat(s).replace(/<[^>]+>/g, '');
console.log(JSON.stringify({
  ryder: strip({ measure: 'hold', hold_s: 1, duration_s: 129 }),
  good: strip({ measure: 'hold', hold_s: 95, duration_s: 100 }),
  shaky: strip({ measure: 'hold', hold_s: 40, duration_s: 70 }),
}));
""", tmp_path)
        assert out["ryder"] == "held 1s of a 2m 09s recording (the phone mostly could not see the position)"
        assert out["good"] == "held 1m 35s" and out["shaky"] == "held 40s"
