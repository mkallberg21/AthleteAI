"""Rhythm, hand split, fade and stops, read off the sound of the ball.

The analyzer is pure, so most of this drives it directly with synthetic
impact times. The last class goes through the real endpoints to prove the
report rides on a heard wall-ball session and stays off a seen one.
"""
from __future__ import annotations

import pytest

from offdays import rhythm
from offdays.rhythm import analyze


def session(gaps, hands=None, source="sound", start=500):
    """Impacts at the given gaps. Hands alternate right/left by default."""
    t, reps = start, [{"t_ms": start, "hand": "right", "source": source}]
    for i, g in enumerate(gaps):
        t += g
        hand = hands[i] if hands else ("left" if i % 2 == 0 else "right")
        reps.append({"t_ms": t, "hand": hand, "source": source})
    return reps


def wobble(n, base=1000, amp=30):
    # Deterministic small jitter, like a real rebounder rather than a metronome.
    return [base + ((i * 37) % (2 * amp + 1)) - amp for i in range(n)]


class TestSteady:
    def test_steady_two_handed_session_reads_as_steady(self):
        rep = analyze(session(wobble(30)), "right")
        d = rep.to_dict()
        assert d["reps"] == 31
        assert d["labels"] == "strong_off"
        assert [s["side"] for s in d["sides"]] == ["strong", "off"]
        assert d["pace_ratio"] == pytest.approx(1.0, abs=0.08)
        assert d["steadiness_cv"] < rhythm.STEADY_CV
        assert d["breaks"] == 0
        assert d["fade"] == pytest.approx(1.0, abs=0.08)
        assert "steady" in d["note"].lower()


class TestOffHand:
    def test_off_hand_slower_is_named_as_the_off_hand(self):
        # Right-handed; a gap belongs to the hand that ENDS it.
        gaps = [1300 if i % 2 == 0 else 1000 for i in range(30)]  # left ends evens
        d = analyze(session(gaps), "right").to_dict()
        strong, off = d["sides"]
        assert strong["hand"] == "right" and off["hand"] == "left"
        assert strong["median_gap_ms"] == pytest.approx(1000)
        assert off["median_gap_ms"] == pytest.approx(1300)
        assert d["pace_ratio"] == pytest.approx(1.3)
        assert "off-hand" in d["note"].lower()
        assert "30%" in d["note"]

    def test_left_hander_strong_side_is_left(self):
        gaps = [1300 if i % 2 == 0 else 1000 for i in range(30)]
        d = analyze(session(gaps), "left").to_dict()
        assert (d["sides"][0]["side"], d["sides"][0]["hand"]) == ("strong", "left")
        # Their off hand (right) is the quick one here.
        assert d["pace_ratio"] == pytest.approx(1000 / 1300, abs=0.001)

    def test_no_dominant_hand_uses_neutral_labels(self):
        gaps = [1300 if i % 2 == 0 else 1000 for i in range(30)]
        d = analyze(session(gaps), None).to_dict()
        assert d["labels"] == "a_b"
        assert [s["side"] for s in d["sides"]] == ["a", "b"]
        assert d["pace_ratio"] == pytest.approx(1.3)
        assert "off-hand" not in d["note"].lower()
        assert "strong" not in d["note"].lower()


class TestFade:
    def test_slowing_late_is_reported(self):
        gaps = [1000] * 10 + [1100] * 10 + [1300] * 10
        d = analyze(session(gaps), "right").to_dict()
        assert d["fade"] == pytest.approx(1.3)
        assert "slowed" in d["note"].lower()

    def test_no_fade_claim_on_a_short_set(self):
        gaps = [1000] * 5 + [1100] * 4 + [1400] * 5  # 15 reps
        d = analyze(session(gaps), "right").to_dict()
        assert d["reps"] < rhythm.FADE_MIN_REPS
        assert d["fade"] is None


class TestBreaks:
    def test_breaks_are_counted_and_kept_out_of_pace(self):
        gaps = wobble(30)
        gaps[8] = 5000   # dropped ball
        gaps[20] = 7000  # ground-ball chase
        reps = session(gaps)
        d = analyze(reps, "right").to_dict()
        assert d["breaks"] == 2
        assert d["break_intervals"] == [
            [reps[8]["t_ms"], reps[9]["t_ms"]],
            [reps[20]["t_ms"], reps[21]["t_ms"]],
        ]
        assert d["break_ms_lost"] > 9000
        # Pace and steadiness ignore the stops entirely.
        assert d["median_gap_ms"] == pytest.approx(1000, abs=35)
        assert d["steadiness_cv"] < rhythm.STEADY_CV
        for side in d["sides"]:
            assert side["median_gap_ms"] < 1100


class TestNoClaims:
    def test_too_few_reps_makes_no_claims(self):
        d = analyze(session([1000, 1400] * 4), "right").to_dict()
        assert d["reps"] == 9
        assert d["pace_ratio"] is None
        assert d["fade"] is None
        assert d["steadiness_cv"] is None
        assert d["breaks"] == 0
        assert d["note"]  # still says something, just not a judgement

    def test_pose_timed_reps_get_no_report(self):
        rep = analyze(session(wobble(30), source=None), "right")
        assert rep.applicable is False
        assert rep.reps == 0

    def test_mostly_pose_with_a_few_heard_is_still_declined(self):
        reps = session(wobble(30), source=None)
        for r in reps[:3]:
            r["source"] = "sound"
        assert analyze(reps, "right").applicable is False

    def test_garbage_never_raises(self):
        assert analyze([{"t_ms": "x", "source": "sound"}], "right").applicable is False
        assert analyze([], None).applicable is False


class TestStrip:
    def test_strip_is_hand_coded(self):
        hands = ["left", "none"] + ["right", "left"] * 14
        d = analyze(session(wobble(30), hands=hands), "right").to_dict()
        assert d["strip"][0] == [500, "R"]
        assert d["strip"][1][1] == "L"
        assert d["strip"][2][1] == "-"

    def test_long_session_is_downsampled_to_the_cap(self):
        reps = session(wobble(999))
        d = analyze(reps, "right").to_dict()
        assert d["reps"] == 1000
        assert len(d["strip"]) == rhythm.STRIP_CAP
        assert d["strip"][0][0] == reps[0]["t_ms"]
        assert d["strip"][-1][0] == reps[-1]["t_ms"]
        times = [p[0] for p in d["strip"]]
        assert times == sorted(times)


# ---------------------------------------------------------------------------
# Through the real endpoints.
# ---------------------------------------------------------------------------

pytest.importorskip("fastapi")

class TestRelease:
    """Catch-to-next-impact, when the phone could hear the catches."""

    @staticmethod
    def with_releases(reps, strong_ms, off_ms, strong="right", every=1):
        out = []
        for i, r in enumerate(reps):
            r = dict(r)
            if i and i % every == 0:
                r["release_ms"] = strong_ms if r["hand"] == strong else off_ms
            out.append(r)
        return out

    def test_off_hand_holding_on_is_the_note(self):
        reps = self.with_releases(session(wobble(30)), strong_ms=600, off_ms=780)
        d = analyze(reps, "right").to_dict()
        assert d["release_median_ms"] is not None
        assert d["release_coverage"] > 0.9
        assert d["release_ratio"] == pytest.approx(1.3, abs=0.02)
        strong, off = d["sides"]
        assert strong["median_release_ms"] == 600 and off["median_release_ms"] == 780
        assert "off-hand" in d["note"].lower() and "longer" in d["note"].lower()

    def test_even_release_does_not_invent_a_difference(self):
        reps = self.with_releases(session(wobble(30)), strong_ms=600, off_ms=610)
        d = analyze(reps, "right").to_dict()
        assert d["release_ratio"] == pytest.approx(1.0, abs=0.03)
        assert "holding" not in d["note"].lower()

    def test_too_few_catches_heard_says_nothing_about_release(self):
        # Phone on the far side: a catch heard on one rep in four.
        reps = self.with_releases(session(wobble(30)), strong_ms=600, off_ms=900, every=4)
        d = analyze(reps, "right").to_dict()
        assert d["release_coverage"] < rhythm.MIN_RELEASE_SHARE
        assert d["release_median_ms"] is None and d["release_ratio"] is None
        assert "holding" not in d["note"].lower()

    def test_no_release_field_at_all_is_an_older_client(self):
        d = analyze(session(wobble(30)), "right").to_dict()
        assert d["release_median_ms"] is None
        assert d["release_coverage"] == 0


from fastapi.testclient import TestClient  # noqa: E402

import offdays.api as api_module  # noqa: E402
from offdays.db import connect  # noqa: E402
from offdays.store import Store  # noqa: E402


@pytest.fixture
def athlete(tmp_path):
    api_module._store = Store(connect(tmp_path / "test.db"))
    client = TestClient(api_module.app)
    org = client.post(
        "/api/orgs", json={"name": "Northshore LC", "director_name": "Dir Smith"}
    ).json()
    director = {"Authorization": f"Bearer {org['director']['token']}"}
    team = client.post(
        "/api/teams", json={"name": "U15 Boys", "season": "2026"}, headers=director
    ).json()
    a = client.post(
        "/api/athletes",
        json={
            "display_name": "Jordan P.", "birth_year": 2011, "dominant_hand": "right",
            "guardian_consent": True, "join_code": team["join_code"],
        },
        headers=director,
    ).json()
    yield client, {"Authorization": f"Bearer {a['token']}"}
    api_module._store = None


def submit(client, headers, source, drill="lax_wall_ball", release=None, base=1450):
    started = client.post(
        "/api/sessions/start", json={"drill_key": drill}, headers=headers
    ).json()
    reps = session(wobble(29, base=base, amp=60))
    for i, r in enumerate(reps):
        r["confidence"] = 0.8
        if source is None:
            r.pop("source")
        else:
            r["source"] = source
        if release and i:
            r["release_ms"] = release
    res = client.post(
        "/api/sessions/submit",
        json={
            "session_id": started["session_id"],
            "nonce": started["nonce"],
            "duration_ms": reps[-1]["t_ms"] + 700,
            "reps": reps,
            "mean_confidence": 0.8,
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()


class TestThroughTheApi:
    def test_heard_wall_ball_session_carries_rhythm(self, athlete):
        client, headers = athlete
        body = submit(client, headers, "sound")
        assert "rhythm" in body
        assert body["rhythm"]["reps"] == 30
        assert body["rhythm"]["labels"] == "strong_off"
        assert body["rhythm"]["note"]

    def test_seen_wall_ball_session_does_not(self, athlete):
        client, headers = athlete
        body = submit(client, headers, None)
        assert "rhythm" not in body

    def test_heard_wall_ball_carries_release_time(self, athlete):
        client, headers = athlete
        body = submit(client, headers, "sound", release=900)
        assert body["rhythm"]["release_median_ms"] == 900
        assert body["rhythm"]["release_coverage"] > 0.9

    def test_release_is_dropped_on_a_drill_without_a_catch(self, athlete):
        """A tennis wall rally's 'release' would be the racket hit. The phone
        may send one; the server does not coach it."""
        client, headers = athlete
        body = submit(client, headers, "sound", drill="ten_wall_rally",
                      release=500, base=900)
        assert "rhythm" in body
        assert body["rhythm"]["release_median_ms"] is None
