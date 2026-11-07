"""No animated stick figures on the drill screen.

The technique reference used to ship an inline animated SVG of a stick figure
doing the drill, shown under the camera. It has been taken off every drill. The
drawing code in offdays/demo.py is left in place, unused, so it can be deleted
in its own change if that is wanted.
"""
from __future__ import annotations

import pytest

from offdays.drills.catalog import ALL_DRILLS
from tests.test_api import client  # noqa: F401  (fixture)


class TestNoFigureIsSent:
    def test_no_drill_carries_a_demo(self, client):
        sent = []
        for d in ALL_DRILLS:
            res = client.get(f"/api/technique/{d.key}")
            if res.status_code == 200 and "demo" in res.json():
                sent.append(d.key)
        assert sent == [], f"these drills still send a figure: {sent}"

    @pytest.mark.parametrize("key", ["lax_shooting", "lax_wall_ball_strong", "lax_wall_ball_off"])
    def test_the_drills_named_by_the_coach_send_none(self, client, key):
        res = client.get(f"/api/technique/{key}")
        if res.status_code == 200:
            body = res.json()
            assert "demo" not in body
            assert "<svg" not in str(body)

    def test_the_rest_of_the_reference_still_arrives(self, client):
        """Cues and the movement trace are real coaching and stay."""
        res = client.get("/api/technique/lax_wall_ball_strong")
        assert res.status_code == 200
        body = res.json()
        assert body.get("cues"), "the written cues must still be there"


class TestThePageDoesNotDrawOne:
    def test_the_drill_screen_has_no_figure_slot(self):
        from pathlib import Path
        html = (Path(__file__).resolve().parent.parent / "offdays" / "web" / "static"
                / "capture.html").read_text(encoding="utf-8")
        assert 'id="demo-fig"' not in html
        assert "ref.demo.svg" not in html
