"""A phone that opened the app before a release must not be stuck on the old sign-up page.

The service worker used to serve every page from its saved copy first. After the terms release, a phone that had
opened the app before it kept the old sign-up page (no tick box) while the server required one, so the director saw
"please agree to the terms" with nothing to tick. The pages the server enforces rules on now load fresh when there is a
connection and fall back to the saved copy only when there is none; the athlete's capture screen is untouched.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "offdays" / "web" / "static"
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def network_first() -> list[str]:
    m = re.search(r"const NETWORK_FIRST = \[(.*?)\];", SW, re.S)
    assert m, "the worker must name which pages it fetches fresh"
    return re.findall(r"'([^']+)'", m.group(1))


class TestWhichPagesAreFetchedFresh:

    def test_the_pages_the_server_enforces_rules_on_come_fresh(self):
        assert set(network_first()) == {"index.html", "coach.html", "parent.html"}

    def test_the_athletes_capture_screen_is_still_saved_copy_first(self):
        """It has to open instantly with no signal; going to the network first would put a spinner in a driveway."""
        assert "capture.html" not in network_first()

    def test_every_fresh_page_is_still_in_the_offline_shell(self):
        shell = re.search(r"const SHELL = \[(.*?)\];", SW, re.S).group(1)
        for page in network_first():
            assert f"'{page}'" in shell, f"{page} must still be saved for offline use"

    def test_the_fresh_route_is_used_before_the_saved_copy_route(self):
        fetch = SW.split("self.addEventListener('fetch'", 1)[1]
        assert fetch.index("NETWORK_FIRST.includes") < fetch.index("caches.match(request).then((cached) =>")

    def test_a_slow_or_missing_connection_falls_back_to_the_saved_page(self):
        fn = SW.split("function networkFirst(request)", 1)[1].split("self.addEventListener('fetch'", 1)[0]
        assert "AbortController" in fn and "NETWORK_FIRST_MS" in fn, "a stalled server must not hold the page forever"
        assert ".catch(" in fn and "caches.match(request)" in fn, "offline, the saved copy is the answer"
        assert "cache: 'no-store'" in fn, "the browser's own HTTP cache must not hand back an old page either"

    def test_the_wait_is_a_few_seconds_not_a_minute(self):
        ms = int(re.search(r"const NETWORK_FIRST_MS = (\d+);", SW).group(1))
        assert 2000 <= ms <= 6000

    def test_the_fresh_copy_is_saved_for_next_time_offline(self):
        fn = SW.split("function networkFirst(request)", 1)[1].split("self.addEventListener('fetch'", 1)[0]
        assert "c.put(request, copy)" in fn

    def test_the_cache_name_moved_so_old_phones_drop_their_old_pages(self):
        n = int(re.search(r"offdays-shell-v(\d+)", SW).group(1))
        assert n >= 12, "a new rule needs a new cache name, or phones keep the old saved pages"


class TestAnOutOfDatePageRecovers:

    def test_a_terms_refusal_reloads_the_page_once(self):
        assert "agree to the terms" in INDEX and "location.reload()" in INDEX

    def test_it_never_reloads_in_a_loop(self):
        block = INDEX.split("agree to the terms", 1)[1].split("const errEl", 1)[0]
        assert "offdays.reloadedForTerms" in block
        assert block.index("getItem('offdays.reloadedForTerms')") < block.index("location.reload()")

    def test_the_normal_error_still_shows_when_it_is_not_that_case(self):
        block = INDEX.split("agree to the terms", 1)[1].split("const errEl", 1)[0]
        assert "$('oerr').textContent = e.message;" in block
