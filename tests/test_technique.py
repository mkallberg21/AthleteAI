"""Technique references.

Form scoring could already tell a child their range was short. It could not
tell them what "not short" looks like, and a score without a fix is a mark out
of ten -- which is the thing this product is otherwise careful not to hand a
twelve-year-old.

The property worth protecting is that the fix and the score are always about
the same thing. A tip list a child has to search is not a fix; the sentence
that appears has to be the sentence for the component that actually scored
lowest. `quality.weakest` exists so those two can never disagree.

The reference itself is generated from each drill's own thresholds rather than
filmed. That is not only about avoiding a third-party embed in front of a
child -- it means the reference cannot drift out of agreement with the score,
which a clip shot once and a threshold tuned later silently do.
"""
from __future__ import annotations

import pytest

from offdays import quality as quality_mod
from offdays import technique
from offdays.drills import ALL_DRILLS, DRILLS_BY_KEY
from offdays.drills.base import Metric


class TestEveryDrillHasSomething:
    def test_every_shipped_drill_has_cues_written_for_it(self):
        """Not a template -- "go deeper" is not advice. Each one has to name
        the body part and the feeling."""
        assert technique.coverage()["without_cues"] == []

    @pytest.mark.parametrize("drill", ALL_DRILLS, ids=lambda d: d.key)
    def test_the_cues_are_for_components_that_drill_can_actually_score(self, drill):
        """A cue for a component this drill never scores would be advice that
        never surfaces, which is worse than no cue -- it reads as coverage."""
        scoreable = {"consistency", "depth", "tempo", "endurance"}
        if drill.metric is Metric.HOLD_SECONDS:
            scoreable = {"position", "endurance"}
        if drill.tracks_handedness:
            scoreable |= {"offhand"}
        for cue in technique.cues_for(drill.key):
            assert cue.component in scoreable, \
                f"{drill.key} has a {cue.component} cue it can never show"

    def test_a_handed_drill_says_something_about_the_weak_side(self):
        """The gap is the thing this whole product exists to surface."""
        for drill in ALL_DRILLS:
            if not drill.tracks_handedness:
                continue
            assert any(c.component == "offhand" for c in technique.cues_for(drill.key)), \
                f"{drill.key} is handed but has no off-hand cue"

    def test_cues_are_written_to_a_child_not_a_coach(self):
        for drill in ALL_DRILLS:
            for cue in technique.cues_for(drill.key):
                assert cue.fix[0].isupper(), f"{drill.key}: {cue.fix!r}"
                assert cue.fix.endswith("."), f"{drill.key}: {cue.fix!r}"
                # A cue longer than this is a paragraph, and a paragraph
                # mid-session is a paragraph nobody reads.
                assert len(cue.fix) < 200, f"{drill.key} cue is too long"


class TestTheFixMatchesTheScore:
    def test_a_bespoke_cue_is_marked_as_one(self):
        assert technique.fix_for("gen_squat", "depth")["bespoke"] is True

    def test_a_generic_fallback_says_it_is_generic(self):
        """Worth showing, not worth pretending it was written for this drill."""
        fix = technique.fix_for("vb_set", "endurance")
        assert fix["bespoke"] is False

    def test_an_unknown_component_gets_nothing_rather_than_something_wrong(self):
        assert technique.fix_for("gen_squat", "vibes") is None

    def test_every_component_the_scorer_emits_has_a_generic_fallback(self):
        """Otherwise a component with no bespoke cue shows nothing at all,
        and the child gets a score with no fix -- the exact failure this
        feature exists to remove."""
        for key in ("consistency", "depth", "tempo", "endurance", "position",
                    "offhand"):
            assert key in technique.GENERIC


class TestTheScorerNamesWhatItIsTalkingAbout:
    """`weakest` is what lets the fix and the note agree. Without it a caller
    has to re-derive the weakest component and can get a different answer."""

    def _report(self, drill_key, roms, cycles=None):
        drill = DRILLS_BY_KEY[drill_key]
        reps = [
            quality_mod.RepFeature(
                t_ms=i * 1500, rom=rom, confidence=0.9,
                cycle_ms=(cycles[i] if cycles else 1200), peak=rom,
            )
            for i, rom in enumerate(roms)
        ]
        return quality_mod.analyze(drill, reps, duration_ms=len(reps) * 1500)

    def test_the_note_and_the_weakest_key_are_about_the_same_thing(self):
        # Consistently shallow reps: depth should be the weak one.
        report = self._report("gen_squat", [30.0] * 12)
        assert report.weakest == "depth"
        assert report.coaching_note == next(
            c.detail for c in report.components if c.key == "depth"
        )

    def test_a_clean_session_still_names_a_next_thing(self):
        """A child who did well should get "here is the next thing", not a
        blank -- otherwise the only feedback in the app is negative."""
        report = self._report("gen_squat", [78.0, 79.0, 77.0, 78.0, 78.5] * 3)
        assert report.weakest
        assert technique.fix_for("gen_squat", report.weakest) is not None

    def test_a_hold_names_position(self):
        drill = DRILLS_BY_KEY["gen_plank"]
        report = quality_mod.analyze(drill, [], duration_ms=60_000, hold_ms=40_000)
        assert report.weakest == "position"
        assert technique.fix_for("gen_plank", "position")["bespoke"] is True


class TestTheReferenceIsGeneratedNotFilmed:
    def test_a_drill_that_scores_form_gets_a_trace(self):
        assert technique.reference("gen_squat")["trace"] is not None

    def test_the_trace_uses_the_same_target_the_scorer_marks_against(self):
        """The point of generating it. A clip shot once and a threshold tuned
        later disagree silently, and the child pays for that."""
        trace = technique.reference("gen_squat")["trace"]
        assert trace["target_rom"] == DRILLS_BY_KEY["gen_squat"].quality.target_rom

    def test_the_traces_tempo_sits_inside_the_scorers_own_band(self):
        for drill in ALL_DRILLS:
            reference = technique.reference(drill.key)
            trace, spec = reference.get("trace"), drill.quality
            if not trace or spec is None:
                continue
            assert spec.tempo_min_ms <= trace["tempo_ms"] <= spec.tempo_max_ms, \
                f"{drill.key} demonstrates a tempo its own scorer would mark down"

    def test_a_hold_is_drawn_as_a_flat_line(self):
        """Which is exactly what a hold is."""
        trace = technique.reference("gen_plank")["trace"]
        assert trace["hold"] is True
        assert {v for _, v in (tuple(p) for p in trace["points"])} == {1.0}

    def test_a_rep_starts_and_ends_where_it_started(self):
        for drill in ALL_DRILLS:
            trace = technique.reference(drill.key).get("trace")
            if not trace or trace["hold"]:
                continue
            first, last = trace["points"][0], trace["points"][-1]
            assert first == [0.0, 0.0] and last == [1.0, 0.0], drill.key

    def test_it_reaches_the_target_rather_than_stopping_short(self):
        for drill in ALL_DRILLS:
            trace = technique.reference(drill.key).get("trace")
            if not trace:
                continue
            assert max(v for _, v in trace["points"]) == 1.0, \
                f"{drill.key} demonstrates a rep that misses its own target"


class TestNoThirdPartyEmbed:
    def test_a_clip_is_only_claimed_when_the_file_is_really_there(self):
        """Read from disk rather than declared in a table, so this cannot
        promise a clip that is not on the server."""
        assert technique.reference("gen_squat")["has_clip"] is False
        assert technique.reference("gen_squat")["clip_url"] == ""

    def test_clip_urls_are_local_paths_never_someone_elses_domain(self):
        """The problem film study carries: an ad before a drill, a sidebar of
        recommendations, and a way out of the app, in front of a child
        mid-session."""
        for drill in ALL_DRILLS:
            url = technique.reference(drill.key)["clip_url"]
            assert not url.startswith("http"), f"{drill.key} points off-site"
            assert "//" not in url, f"{drill.key} points off-site"

    def test_nothing_in_a_reference_is_about_any_athlete(self):
        """It describes a movement. That is why it can be public."""
        reference = technique.reference("gen_squat")
        assert set(reference) == {
            "drill_key", "drill_name", "setup_hint", "cues", "trace",
            "clip_url", "has_clip",
        }


# ---------------------------------------------------------------------------
# Over the wire
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFDAYS_DB", str(tmp_path / "api.db"))
    from offdays import api

    api.app.dependency_overrides.clear()
    return TestClient(api.app)


class TestOverTheWire:
    def test_a_reference_needs_no_login(self, client):
        """Public reference data, like the drill catalog. It describes a
        movement and contains nothing about anybody."""
        assert client.get("/api/technique/gen_squat").status_code == 200

    def test_an_unknown_drill_is_a_404_not_an_empty_reference(self, client):
        assert client.get("/api/technique/gen_moonwalk").status_code == 404

    def test_coverage_is_reported_rather_than_hidden(self, client):
        body = client.get("/api/technique").json()
        assert body["drills"] == len(ALL_DRILLS)
        assert body["with_cues"] == len(ALL_DRILLS)
        assert body["with_clip"] == []
