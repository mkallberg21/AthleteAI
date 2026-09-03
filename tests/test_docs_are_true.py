"""The demo guide's facts, checked against the code that produces them.

Written because the README claimed "2 teams, 8 athletes" and "33 shipped
drills" long after both had changed, and because a document nobody can
verify is worse than no document: it is read with the same confidence and
is wrong.

Only claims that can drift are pinned. Prose is left alone.
"""
import pathlib
import re

import pytest

from offdays.drills import ALL_DRILLS, for_sport

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "demo-program.md"
README = ROOT / "README.md"
SEED = ROOT / "scripts" / "seed_demo.py"


def _seed_source() -> str:
    return SEED.read_text()


def _roster_names() -> list[str]:
    src = _seed_source()
    block = src[src.index("ROSTER = ["):src.index("\n]\n", src.index("ROSTER = ["))]
    return re.findall(r'^\s+\("([^"]+)",', block, re.M)


class TestTheDemoGuideMatchesTheSeed:
    def test_every_athlete_on_the_roster_is_in_the_table(self):
        doc = DOC.read_text()
        for name in _roster_names():
            assert name in doc, f"{name} is seeded but undocumented"

    def test_the_table_invents_nobody(self):
        """A name in the guide that the seeder never creates is worse than an
        omission -- somebody will go looking for them."""
        doc = DOC.read_text()
        rows = re.findall(r"^\| ([A-Z][a-z]+ [A-Z][a-z]+) \| ", doc, re.M)
        seeded = set(_roster_names()) | {
            "Joel White", "Travis Anderson", "Coach Tommy", "Coach Matt", "Coach Mike",
        }
        for name in rows:
            assert name in seeded, f"{name} is documented but never seeded"

    def test_the_athlete_count_is_right(self):
        doc = DOC.read_text()
        count = len(_roster_names())
        assert f"{count} athletes" in doc or "Thirteen athletes" in doc
        assert count == 13, "the guide says thirteen; update both together"

    def test_the_squad_name_is_the_one_seeded(self):
        assert '"2031 Red"' in _seed_source()
        assert "2031 Red" in DOC.read_text()
        assert "2031 Blue" not in DOC.read_text(), "that squad was removed"

    def test_the_film_shelf_size_matches(self):
        src = _seed_source()
        block = src[src.index("FILM_SHELF = ["):src.index("\n]\n", src.index("FILM_SHELF = ["))]
        clips = re.findall(r'^\s+\("([^"]+)",', block, re.M)
        doc = DOC.read_text()
        assert len(clips) == 5, "the guide says five clips"
        for title in clips:
            assert title in doc, f"{title} is seeded but undocumented"


class TestTheCountsInProseAreReal:
    def test_the_guide_s_drill_numbers_are_computed_ones(self):
        doc = DOC.read_text()
        assert f"**{len(for_sport('lacrosse'))}** of the {len(ALL_DRILLS)} shipped" in doc

    def test_the_readme_drill_count_is_current(self):
        """It said 33 for a long time after there were 89."""
        assert f"The {len(ALL_DRILLS)} shipped drills" in README.read_text()

    @pytest.mark.parametrize("claim", ["2 teams", "8 athletes", "33 shipped drills"])
    def test_the_readme_no_longer_repeats_its_old_numbers(self, claim):
        assert claim not in README.read_text(), claim
