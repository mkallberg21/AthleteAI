"""A program's own badge at the top of every screen.

An athlete opens this app to train for their club, not for us. Their badge
leads and ours sits behind it as a credit -- a child should see their own crest
first, and a director handing this to parents should see their program rather
than a vendor.
"""
import pathlib

import pytest

from offdays.db import connect
from offdays.store import Store, StoreError, TEAM_LOGOS


@pytest.fixture
def store(tmp_path):
    return Store(connect(str(tmp_path / "b.db")))


@pytest.fixture
def org(store):
    return store.create_org("Nashville Dogs")


class TestABadgeIsOptional:
    def test_a_program_with_no_badge_still_has_a_header(self, store, org):
        """The name stands in, so the bar is never empty and never ours."""
        assert store.org_branding(org) == {"name": "Nashville Dogs", "logo": ""}

    def test_a_missing_file_is_treated_as_no_badge(self, store, org):
        """A broken image in the header is worse than no image."""
        store.conn.execute(
            "UPDATE organizations SET logo_file = 'gone.png' WHERE id = ?", (org,))
        store.conn.commit()
        assert store.org_branding(org)["logo"] == ""
        assert store.org_branding(org)["name"] == "Nashville Dogs"


class TestSettingABadge:
    def test_a_real_file_is_accepted_and_served_from_teams(self, store, org):
        name = next(f.name for f in TEAM_LOGOS.iterdir() if f.suffix in {".svg", ".png"})
        assert store.set_org_logo(org, name)["logo"] == f"teams/{name}"

    def test_a_file_that_is_not_there_is_refused(self, store, org):
        with pytest.raises(StoreError):
            store.set_org_logo(org, "not-a-real-badge.png")

    @pytest.mark.parametrize("bad", [
        "../../etc/passwd", "sub/dir.png", ".hidden.png", "..\\\\windows.png",
    ])
    def test_a_path_is_refused(self, store, org, bad):
        """A logo is a file name in one directory, not somewhere to point."""
        with pytest.raises(StoreError):
            store.set_org_logo(org, bad)

    def test_clearing_it_is_allowed(self, store, org):
        name = next(f.name for f in TEAM_LOGOS.iterdir() if f.suffix in {".svg", ".png"})
        store.set_org_logo(org, name)
        assert store.set_org_logo(org, "")["logo"] == ""


class TestTheHeaderIsOnEveryScreen:
    STATIC = pathlib.Path(__file__).resolve().parents[1] / "offdays" / "web" / "static"
    PAGES = ("coach.html", "capture.html", "parent.html", "leaderboard.html")

    @pytest.mark.parametrize("page", PAGES)
    def test_the_page_renders_the_club_first(self, page):
        text = (self.STATIC / page).read_text()
        assert 'id="masthead"' in text, f"{page} has no branding slot"
        assert "renderBranding" in text, f"{page} never fills it"

    @pytest.mark.parametrize("page", PAGES)
    def test_no_page_still_hardcodes_our_wordmark(self, page):
        """The old header put us first on a screen belonging to a club."""
        assert '<span>0FF</span>DAYS' not in (self.STATIC / page).read_text()

    def test_the_mark_is_the_bare_glyph_not_the_lockup(self):
        """The brand guidelines set a 120px minimum on the full lockup and say
        to use the mark alone below it. A credit beside somebody else's badge
        is well below it."""
        assert (self.STATIC / "offdays-mark.png").exists()
        css = (self.STATIC / "styles.css").read_text()
        assert ".offdays-mark" in css

    def test_the_badge_outsizes_our_mark(self):
        """"More prevalent" is a measurable claim, so it is measured."""
        css = (self.STATIC / "styles.css").read_text()
        import re
        club = float(re.search(r"\.club-badge \{[^}]*height:\s*([\d.]+)px", css).group(1))
        ours = float(re.search(r"\.offdays-mark \{[^}]*height:\s*([\d.]+)px", css).group(1))
        assert club >= ours * 2, f"club badge {club}px vs our mark {ours}px"

    def test_the_signed_out_page_carries_only_our_mark(self):
        """There is no club yet at sign-in, so there is nothing to lead with."""
        assert 'id="masthead"' not in (self.STATIC / "index.html").read_text()
