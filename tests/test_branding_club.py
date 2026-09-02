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
    def test_the_fixture_badge_exists(self):
        """The tests need one file present; the demo ships with none."""
        assert (TEAM_LOGOS / "sample-badge.svg").exists()

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
        assert store.set_org_logo(org, "sample-badge.svg")["logo"] == \
            "teams/sample-badge.svg"

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
        store.set_org_logo(org, "sample-badge.svg")
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

    #: From the brand guidelines: "Minimum width: 120 px on screen. Below that,
    #: use the Ø mark alone instead of shrinking the lockup."
    LOCKUP_MIN_PX = 120

    def test_the_lockup_is_never_shrunk_below_its_documented_minimum(self):
        import re
        assert (self.STATIC / "offdays-lockup.png").exists()
        css = (self.STATIC / "styles.css").read_text()
        width = float(
            re.search(r"\.offdays-lockup \{[^}]*width:\s*([\d.]+)px", css).group(1))
        assert width >= self.LOCKUP_MIN_PX, (
            f"the lockup is set to {width}px, below the {self.LOCKUP_MIN_PX}px "
            "minimum -- use the bare mark instead of shrinking it")

    def test_a_narrow_screen_swaps_to_the_mark_rather_than_shrinking(self):
        """The guidelines' own instruction for a header with no room.

        A media query that simply made the lockup smaller would put it below
        the documented minimum, which is the one thing the rule forbids.
        """
        import re
        css = (self.STATIC / "styles.css").read_text()
        assert (self.STATIC / "offdays-mark.png").exists()
        narrow = re.search(r"@media \(max-width: \d+px\) \{(.*?)\n\}", css, re.S).group(1)
        assert ".offdays-lockup { display: none" in narrow
        assert ".offdays-mark { display: block" in narrow
        # And nowhere is the lockup given a width under the minimum.
        for width in re.findall(r"\.offdays-lockup \{[^}]*width:\s*([\d.]+)px", css):
            assert float(width) >= self.LOCKUP_MIN_PX, width

    def test_the_club_badge_still_leads(self):
        """"More prevalent" is a measurable claim, so it is measured.

        Compared on rendered width rather than height: the lockup is a wide,
        short wordmark and the badge is a broad crest, and width is what the
        eye actually weighs between two marks sitting side by side.
        """
        import re
        css = (self.STATIC / "styles.css").read_text()
        badge_h = float(
            re.search(r"\.club-badge \{[^}]*height:\s*([\d.]+)px", css).group(1))
        ours = float(
            re.search(r"\.offdays-lockup \{[^}]*width:\s*([\d.]+)px", css).group(1))
        # The club mark in the demo is 768x246; a badge is wider than it is
        # tall, and this is the aspect the header is designed around.
        badge_w = badge_h * (768 / 246)
        assert badge_w >= ours * 1.5, (
            f"club badge renders {badge_w:.0f}px wide against our {ours:.0f}px")

    def test_the_signed_out_page_carries_only_our_mark(self):
        """There is no club yet at sign-in, so there is nothing to lead with."""
        assert 'id="masthead"' not in (self.STATIC / "index.html").read_text()
