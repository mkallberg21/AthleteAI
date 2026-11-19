"""Small things a first-time director or coach would notice, pinned so they stay fixed."""
from __future__ import annotations

from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "offdays" / "web" / "static" / "coach.html").read_text(encoding="utf-8")


def _between(start: str, end: str) -> str:
    a = HTML.index(start)
    return HTML[a:HTML.index(end, a)]


class TestSettingsHasNoUseForTheTeamFilter:
    def test_the_filter_is_hidden_on_settings_home_and_teams_but_not_on_the_tabs_it_filters(self):
        # The Teams tab is the teams and one open team; it has nothing for a team or window filter to narrow.
        paint = _between("function paint()", "function dots()")
        assert "c.id === 'filter-card' && (tab === 'home' || tab === 'settings' || tab === 'teams')" in paint
        for tab in ("today", "families"):
            assert f"tab === '{tab}'" not in paint.split("filter-card")[1].split("away = true")[0]


class TestACoachIsNeverRefusedForAskingForTheDirectorsOutbox:
    def test_the_outbox_and_bounce_list_are_only_asked_for_by_a_director(self):
        fn = _between("async function loadDelivery()", "$('digest-optin').addEventListener")
        gate = fn.index("if (!IS_DIRECTOR) return;")
        assert gate < fn.index("/api/coach/outbox") < fn.index("/api/coach/bounces")

    def test_a_coach_still_gets_their_own_email_preference(self):
        fn = _between("async function loadDelivery()", "$('digest-optin').addEventListener")
        assert fn.index("/api/email/preferences") < fn.index("if (!IS_DIRECTOR) return;")


class TestTheSigninLinkIsOneSelectableLine:
    def test_it_is_a_read_only_box_not_text_that_breaks_mid_word(self):
        assert 'id="code-link" readonly' in HTML
        assert 'onfocus="this.select()"' in _between('id="code-link"', ">")
        assert "$('code-link').value = link;" in HTML
        assert "$('code-link').textContent" not in HTML

    def test_the_link_is_still_the_full_address_with_the_code(self):
        block = _between("if (newDirectorCode) {", "$('code-copy')")
        assert "location.origin}/app/index.html?code=${encodeURIComponent(newDirectorCode)}" in block


class TestAParentWithNoNameIsNotCalledParentTwice:
    def test_the_name_line_is_left_out_when_there_is_no_name(self):
        block = _between("async function homePlayer()", "Where this family is")
        assert "${p.name ? `<b>${esc(p.name)}</b>` : ''}" in block
        assert "esc(p.name || 'Parent')" not in block

    def test_the_heading_still_says_parent_or_parents(self):
        assert "d.parents.length === 1 ? 'Parent' : 'Parents'" in HTML
