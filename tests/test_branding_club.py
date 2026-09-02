"""A program's own badge at the top of every screen.

An athlete opens this app to train for their club, not for us. Their badge
leads and ours sits behind it as a credit -- a child should see their own crest
first, and a director handing this to parents should see their program rather
than a vendor.
"""
import pathlib
import struct

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

    def test_the_whole_wordmark_shows_at_every_width(self):
        """Never the bare glyph in the header, and never a shrunken lockup.

        The guidelines allow swapping to the mark where the lockup will not
        fit, but a half-logo reads as a broken one, so the bar wraps to two
        rows instead. The 120px floor is still honoured -- by never going
        under it, rather than by substituting something else.
        """
        import re
        css = (self.STATIC / "styles.css").read_text()
        js = (self.STATIC / "api.js").read_text()
        assert "offdays-lockup.png" in js, "the header stopped rendering it"
        assert 'class="offdays-mark"' not in js, (
            "the header is emitting the bare glyph again")
        # No breakpoint may hide the lockup or put it under the minimum.
        for query in re.findall(r"@media[^{]*\{(.*?)\n\}", css, re.S):
            assert ".offdays-lockup { display: none" not in query, query[:120]
        for width in re.findall(r"\.offdays-lockup \{[^}]*width:\s*([\d.]+)px", css):
            assert float(width) >= self.LOCKUP_MIN_PX, width

    def test_the_bar_wraps_rather_than_squeezing_three_things_onto_one_row(self):
        """Below ~430px a 120px lockup, a legible badge and a control do not
        fit side by side. The badge keeps its own row instead of either logo
        being shrunk to fit."""
        import re
        css = (self.STATIC / "styles.css").read_text()
        wrap = re.search(r"@media \(max-width: 430px\) \{(.*?)\n\}", css, re.S)
        assert wrap, "no wrapped-bar breakpoint"
        assert 'grid-template-areas: "left right" "centre centre"' in wrap.group(1)
        assert "justify-self: center" in wrap.group(1), (
            "the badge must stay centred on its own row")

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
        # Measured from the badge actually shipped, not from a remembered
        # aspect. Hard-coding one is how the header first came to be sized
        # for a crest 11% wider than the club's real one.
        badge = TEAM_LOGOS / "nashville-dogs.png"
        head = badge.read_bytes()[16:24]
        px_w, px_h = struct.unpack(">II", head)
        badge_w = badge_h * (px_w / px_h)
        assert badge_w >= ours * 1.5, (
            f"club badge renders {badge_w:.0f}px wide against our {ours:.0f}px; "
            f"raise .club-badge height for a {px_w / px_h:.2f}:1 crest")
        # ... and it must still fit the slot it is given.
        cap = float(
            re.search(r"\.club-badge \{[^}]*max-width:\s*([\d.]+)px", css).group(1))
        assert badge_w <= cap, (
            f"badge wants {badge_w:.0f}px but max-width caps it at {cap:.0f}px, "
            "which silently shrinks it below the height set here")

    def test_the_club_badge_sits_in_the_centre_of_the_bar(self):
        """Ours at the far left, theirs in the middle -- and centred on the
        whole bar, not on the branding block, which is the difference a
        three-column grid makes and a flex row cannot.
        """
        import re
        css = (self.STATIC / "styles.css").read_text()
        bar = re.search(r"\.topbar \{(.*?)\n\}", css, re.S).group(1)
        cols = re.search(r"grid-template-columns:\s*([^;]+);", bar).group(1)
        assert cols.count("1fr") == 2 and "auto" in cols, cols
        # Outer columns must be able to shrink under their content, or a wide
        # sign-out block shoves the centre column off the middle.
        assert "minmax(0, 1fr)" in cols, (
            f"outer columns are {cols!r}; plain 1fr will not stay centred")
        # The slot lays out nothing itself, so its children are bar columns.
        assert re.search(r"#masthead \{[^}]*display:\s*contents", css)

        js = (self.STATIC / "api.js").read_text()
        body = js[js.index("export async function renderBranding"):]
        body = body[:body.index("\n}")]
        assert body.index("mast-left") < body.index("${centre}"), (
            "our wordmark must be emitted before the club's mark, so it takes "
            "the left column and the club's takes the centre")

    def test_a_phone_drops_the_viewer_name_rather_than_the_badge(self):
        """Something has to give at 414px. It is not the club's crest."""
        import re
        css = (self.STATIC / "styles.css").read_text()
        narrow = re.search(r"@media \(max-width: \d+px\) \{(.*?)\n\}", css, re.S).group(1)
        assert re.search(r"#whoami \{[^}]*display:\s*none", narrow), narrow
        assert "club-badge { display: none" not in narrow

    def test_the_signed_out_page_carries_only_our_mark(self):
        """There is no club yet at sign-in, so there is nothing to lead with."""
        assert 'id="masthead"' not in (self.STATIC / "index.html").read_text()


class TestTheAssignmentTargetsAreReadable:
    """A coach should not need a decoder ring for their own dashboard.

    The compliance table showed three unlabelled letters -- S, R, O -- whose
    only state cue was a colour difference. It did not survive a screenshot,
    a printout, or a coach who cannot separate the two hues, and the person
    who commissioned the product could not read it.
    """

    STATIC = pathlib.Path(__file__).resolve().parents[1] / "offdays" / "web" / "static"

    def test_each_target_is_named_rather_than_lettered(self):
        html = (self.STATIC / "coach.html").read_text()
        assert "function targetMarks" in html
        for label in ("'Sessions'", "'Reps'", "'Off-hand'"):
            assert label in html, label
        # The old single-character code, which is what made it unreadable.
        assert "mark(p.sessions_met, 'S')" not in html
        assert 'class="dots"' not in html

    def test_the_column_says_what_was_met(self):
        html = (self.STATIC / "coach.html").read_text()
        assert "<th>Targets met</th>" in html

    def test_met_and_unmet_differ_by_more_than_colour(self):
        """Greyscale and colour-blindness both have to survive this."""
        import re
        css = (self.STATIC / "styles.css").read_text()
        met = re.search(r"\.mark\.met \{([^}]*)\}", css).group(1)
        unmet = re.search(r"\.mark\.unmet \{([^}]*)\}", css).group(1)
        assert "solid" in met and "dashed" in unmet, (met, unmet)
        html = (self.STATIC / "coach.html").read_text()
        # A tick against a middot, so the glyph carries the state too.
        assert "\\u2713" in html and "\\u00b7" in html

    def test_the_percentage_shown_never_contradicts_the_tick(self):
        """0.346 rounds up to "35%" against a 35% minimum, then shows as not
        met -- the number and the state disagreeing in adjacent columns. The
        displayed share is floored so that cannot happen."""
        html = (self.STATIC / "coach.html").read_text()
        assert "Math.floor(p.offhand_share * 100)" in html
        assert "Math.round(p.offhand_share * 100)" not in html

    def test_every_mark_carries_its_target_in_a_tooltip(self):
        html = (self.STATIC / "coach.html").read_text()
        assert 'title="${esc(label)}${esc(goal)}' in html
        assert "'met' : 'not met yet'" in html
