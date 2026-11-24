"""Form cues are built but not switched on: an athlete only gets them on a phone opened with ?formcues=1.

The logic is tested in tests/js/formcue.test.mjs against a model skeleton. These tests guard the wiring: that it stays off
by default until it has been checked against real video, and that it cannot take the capture screen down.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "offdays" / "web" / "static"
CAPTURE = (STATIC / "capture.html").read_text(encoding="utf-8").replace("\r\n", "\n")
FORMCUE = (STATIC / "formcue.js").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")


def test_it_is_off_unless_asked_for_on_that_phone():
    gate = CAPTURE.split("const FORM_CUES_ON = (() => {", 1)[1].split("})();", 1)[0]
    assert "get('formcues')" in gate
    assert "return localStorage.getItem('offdays.formcues') === 'on';" in gate
    assert "catch { return false; }" in gate, "a phone that blocks storage simply has no cues"
    assert "asked === '0'" in gate and "removeItem('offdays.formcues')" in gate, "and it can be turned off again"


def test_a_coach_is_only_made_when_the_gate_is_on_and_the_drill_has_cues():
    made = re.search(r"formCoach = (.+?);", CAPTURE.split("holdWatch = new HoldWatch();\n  formCoach", 1)[0][-1:]
                     + "formCoach" + CAPTURE.split("holdWatch = new HoldWatch();\n  formCoach", 1)[1]).group(1)
    assert made.startswith("FORM_CUES_ON && !soundCounter && FormCoach.supports(activeDrill)")
    assert made.endswith(": null")


def test_with_no_coach_the_screen_behaves_exactly_as_before():
    assert "const formCue = formCoach ? formCoach.update({" in CAPTURE
    step = CAPTURE.split("const formCue = formCoach", 1)[1].split("step();", 1)[0]
    order = [step.index("conf > 0 && conf < 0.6"), step.index("} else if (formCue) {"),
             step.index("holdWatch.update(counter.holdMs")]
    assert order == sorted(order), "framing first, then a form cue, then the paused clock"


def test_it_uses_the_clocks_own_number():
    assert "value: counter.smoothed" in CAPTURE, "so a cue can never contradict a running clock"
    assert "aspect: video.videoWidth / (video.videoHeight || 1)" in CAPTURE


def test_cues_are_spoken_through_the_existing_voice():
    assert "if (formCue.say) callOut(formCue.text);" in CAPTURE


def test_the_module_is_in_the_offline_shell():
    shell = re.search(r"const SHELL = \[(.*?)\];", SW, re.S).group(1)
    assert "'formcue.js'" in shell, "the capture screen imports it, so without it the screen will not load offline"
    assert "import { FormCoach } from './formcue.js';" in CAPTURE


def test_the_module_says_plainly_that_it_is_not_validated():
    assert "NOT SWITCHED ON FOR ATHLETES" in FORMCUE and "not yet checked against real video" in FORMCUE
