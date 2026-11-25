"""A Facebook reel or video on the film shelf: played in Facebook's own player, never copied.

It does what an Instagram clip does: opened is all that is known, it is for athletes 13 and over with a known age, and
nothing of the video is ever fetched or stored here. The one thing our server asks Facebook is where a share link points.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from offdays import film
from tests.test_clip_sources import STATIC, h, shelf, titles, world  # noqa: F401  (world is a fixture)

ID = "1805786367298615"
REEL = f"https://www.facebook.com/reel/{ID}/?hpir=1#"
SHARE = "https://www.facebook.com/share/r/1A2kybptam/?mibextid=wwXIfr"


def add_fb(w, link=REEL, who="coach", **extra):
    return w["client"].post("/api/coach/clips", headers=h(w, who),
                            json={"video": link, "title": "Seven defense tips", "focus": "Where his eyes are", **extra})


class TestReadingAFacebookLink:
    @pytest.mark.parametrize("link,want", [
        (REEL, f"reel/{ID}"),
        (f"https://m.facebook.com/reel/{ID}", f"reel/{ID}"),
        (f"facebook.com/reel/{ID}/", f"reel/{ID}"),
        ("https://www.facebook.com/watch/?v=1234567890", "video/1234567890"),
        ("https://www.facebook.com/watch?v=1234567890&ref=sharing", "video/1234567890"),
        ("https://www.facebook.com/video.php?v=1234567890", "video/1234567890"),
        ("https://www.facebook.com/1stclasslacrosse/videos/1234567890/", "video/1234567890"),
        ("https://web.facebook.com/1stclasslacrosse/videos/seven-tips/1234567890", "video/1234567890"),
        (f"reel/{ID}", f"reel/{ID}"),
    ])
    def test_reels_and_videos_in_the_shapes_people_paste(self, link, want):
        assert film.parse_facebook(link) == want

    @pytest.mark.parametrize("link", [
        "https://www.facebook.com/1stclasslacrosse", "https://www.facebook.com/", "https://www.facebook.com/reel/abc",
        f"https://evil.com/?u=https://www.facebook.com/reel/{ID}", f"https://www.facebook.com.evil.com/reel/{ID}",
        f"https://notfacebook.com/reel/{ID}", f"https://user@www.facebook.com/reel/{ID}",
        f"https://www.facebook.com:8443/reel/{ID}", f"https://www.facebook.com:99999/reel/{ID}",
        f"javascript:alert(1)//facebook.com/reel/{ID}", f"ftp://www.facebook.com/reel/{ID}",
        f"https://www.facebook.com/reel/{ID} and more", "https://www.instagram.com/reel/Cabc123_-x/",
        "https://youtu.be/dQw4w9WgXcQ", SHARE, "https://fb.watch/abcDEF123/", "", None, "x" * 700,
    ])
    def test_anything_else_is_not_one(self, link):
        assert film.parse_facebook(link) is None

    def test_a_share_link_is_recognised_and_stripped_of_who_shared_it(self):
        assert film.facebook_share(SHARE) == "https://www.facebook.com/share/r/1A2kybptam/"
        assert film.facebook_share("https://www.facebook.com/share/v/Ab12Cd34/") == "https://www.facebook.com/share/v/Ab12Cd34/"
        assert film.facebook_share("fb.watch/abcDEF123/?mibextid=x") == "https://fb.watch/abcDEF123/"
        for not_share in (REEL, "https://www.facebook.com/share/p/1A2kybptam/", "https://evil.com/share/r/1A2kybptam/",
                          "https://fb.watch/", "https://fb.watch/a/b/c"):
            assert film.facebook_share(not_share) is None, not_share

    def test_the_player_address_is_built_from_the_number_alone(self):
        assert film.embed_url("facebook", f"reel/{ID}", 0, None) == (
            "https://www.facebook.com/plugins/video.php?href=https%3A%2F%2Fwww.facebook.com%2Freel%2F"
            f"{ID}%2F&show_text=false&width=360")
        assert "video.php%3Fv%3D1234567890" in film.embed_url("facebook", "video/1234567890", 0, None)
        for bad in ("reel/abc", "reel/1\"><script>", "https://evil.com", ""):
            assert film.embed_url("facebook", bad, 0, None) == "", bad
        assert "autoplay" not in film.embed_url("facebook", f"reel/{ID}", 0, None), "autoplay starts the player muted"


class TestAskingFacebookWhereAShareLinkPoints:
    def test_one_hop_to_the_reel(self):
        asked = []
        got = film.resolve_facebook(SHARE, locate=lambda u: asked.append(u) or f"https://www.facebook.com/reel/{ID}/?fs=e")
        assert got == f"reel/{ID}"
        assert asked == ["https://www.facebook.com/share/r/1A2kybptam/"], "the cleaned address, asked once"

    def test_a_short_link_that_goes_through_a_share_link(self):
        hops = {"https://fb.watch/abcDEF123/": "https://www.facebook.com/share/v/Ab12Cd34/",
                "https://www.facebook.com/share/v/Ab12Cd34/": "https://www.facebook.com/watch/?v=1234567890"}
        assert film.resolve_facebook("https://fb.watch/abcDEF123/", locate=hops.get) == "video/1234567890"

    def test_a_sign_in_wall_that_still_names_the_video(self):
        wall = f"https://www.facebook.com/login/?next=https%3A%2F%2Fwww.facebook.com%2Freel%2F{ID}%2F"
        assert film.resolve_facebook(SHARE, locate=lambda u: wall) == f"reel/{ID}"

    @pytest.mark.parametrize("where", [
        None, "", "https://evil.com/reel/1805786367298615", "http://169.254.169.254/latest/meta-data/",
        "https://www.facebook.com/1stclasslacrosse", "file:///etc/passwd",
    ])
    def test_it_will_not_be_led_anywhere_but_facebook(self, where):
        asked = []
        assert film.resolve_facebook(SHARE, locate=lambda u: asked.append(u) or where) is None
        assert len(asked) == 1, "and it stops there"

    def test_it_gives_up_after_three_hops(self):
        asked = []
        loop = "https://www.facebook.com/share/r/1A2kybptam/"
        assert film.resolve_facebook(SHARE, locate=lambda u: asked.append(u) or loop) is None
        assert len(asked) == 3

    def test_a_link_that_is_not_a_share_link_is_never_asked_about(self):
        asked = []
        for link in (REEL, "https://evil.com/share/r/abcd", "https://www.instagram.com/reel/Cabc123_-x/"):
            assert film.resolve_facebook(link, locate=lambda u: asked.append(u)) is None
        assert asked == []

    def test_asking_reads_one_header_and_never_follows_or_downloads(self):
        src = inspect.getsource(film._facebook_location)
        assert "_NoRedirect" in src and 'headers.get("Location")' in src and "timeout=6" in src
        assert ".read(" not in src, "the page is not read, so no video can be"
        assert film._NoRedirect().redirect_request(None, None, 302, "", {}, "https://x") is None


class TestAFacebookClip:
    def test_a_coach_adds_a_reel_with_no_end_time_and_it_is_for_13_and_over(self, world):  # noqa: F811
        r = add_fb(world)
        assert r.status_code == 201, r.text
        made = r.json()
        assert (made["provider"], made["video_id"], made["min_age"], made["end_s"], made["tracked"]) == \
            ("facebook", f"reel/{ID}", 13, None, False)
        assert made["page_url"] == f"https://www.facebook.com/reel/{ID}/"
        assert made["embed_url"].startswith("https://www.facebook.com/plugins/video.php?href=")

    def test_only_the_kind_and_number_are_stored(self, world):  # noqa: F811
        add_fb(world, link=f"https://www.facebook.com/reel/{ID}/?mibextid=wwXIfr&rdid=abc")
        stored = [tuple(r) for r in world["store"].conn.execute("SELECT provider, video_id FROM clips")]
        assert stored == [("facebook", f"reel/{ID}")]
        dump = " ".join(str(tuple(r)) for r in world["store"].conn.execute("SELECT * FROM clips"))
        assert "mibextid" not in dump and "rdid" not in dump

    def test_a_link_pasted_as_youtube_is_still_a_facebook_clip(self, world):  # noqa: F811
        assert add_fb(world, provider="youtube").json()["provider"] == "facebook"

    def test_a_share_link_is_resolved_and_then_stored_the_same_way(self, world, monkeypatch):  # noqa: F811
        monkeypatch.setattr(film, "_facebook_location", lambda url: f"https://www.facebook.com/reel/{ID}/?fs=e")
        r = add_fb(world, link=SHARE)
        assert r.status_code == 201, r.text
        assert r.json()["video_id"] == f"reel/{ID}"

    def test_a_share_link_facebook_will_not_explain_is_refused_with_what_to_do(self, world, monkeypatch):  # noqa: F811
        monkeypatch.setattr(film, "_facebook_location", lambda url: None)
        r = add_fb(world, link=SHARE)
        assert r.status_code == 400
        assert "copy the address from the top of the browser" in r.json()["detail"]
        assert world["store"].conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0] == 0

    def test_a_page_link_is_refused_in_plain_words(self, world):  # noqa: F811
        r = add_fb(world, link="https://www.facebook.com/1stclasslacrosse", provider="facebook")
        assert r.status_code == 400 and "Facebook video or reel" in r.json()["detail"]

    def test_a_coach_cannot_lower_the_age(self, world):  # noqa: F811
        assert add_fb(world, min_age=8).json()["min_age"] == 13

    def test_only_athletes_13_and_over_with_a_known_age_are_offered_it(self, world):  # noqa: F811
        add_fb(world)
        assert titles(world, "teen") == ["Seven defense tips"] and titles(world, "thirteen") == ["Seven defense tips"]
        for who in ("kid", "unknown", "guess"):
            assert titles(world, who) == [], who

    def test_a_younger_athlete_cannot_open_it_by_asking_for_it_directly(self, world):  # noqa: F811
        cid = add_fb(world).json()["id"]
        for who in ("kid", "unknown", "guess"):
            assert world["client"].post(f"/api/film/{cid}/start", headers=h(world, who)).status_code == 409, who
        assert world["store"].conn.execute("SELECT COUNT(*) FROM clip_watches").fetchone()[0] == 0

    def test_opening_it_is_opened_never_watched_and_earns_nothing(self, world):  # noqa: F811
        cid = add_fb(world).json()["id"]
        wid = world["client"].post(f"/api/film/{cid}/start", headers=h(world, "teen")).json()["watch_id"]
        beat = world["client"].post(f"/api/film/watches/{wid}/beat", headers=h(world, "teen"), json={"position_s": 30})
        assert beat.status_code == 404, "a phone cannot claim to have watched it"
        row = world["store"].conn.execute("SELECT verdict, xp_awarded, watched_s FROM clip_watches").fetchone()
        assert (row["verdict"], row["xp_awarded"], row["watched_s"]) == ("opened", 0, 0)
        assert world["store"].conn.execute("SELECT COUNT(*) FROM xp_ledger").fetchone()[0] == 0

    def test_the_coach_sees_opened_not_watched(self, world):  # noqa: F811
        cid = add_fb(world).json()["id"]
        world["client"].post(f"/api/film/{cid}/start", headers=h(world, "teen"))
        cov = world["store"].clip_coverage(world["org"], [world["p"]["teen"]["id"]])["clips"][0]
        assert (cov["provider"], cov["tracked"], cov["watched_count"]) == ("facebook", False, 0)
        assert [a["display_name"] for a in cov["started"]] == ["Teen"]

    def test_an_athlete_can_say_it_did_not_show_and_gets_the_slot_back(self, world):  # noqa: F811
        cid = add_fb(world).json()["id"]
        before = shelf(world, "teen")["day"]["clips_left"]
        wid = world["client"].post(f"/api/film/{cid}/start", headers=h(world, "teen")).json()["watch_id"]
        assert world["client"].post(f"/api/film/watches/{wid}/unavailable", headers=h(world, "teen")).status_code == 200
        assert shelf(world, "teen")["day"]["clips_left"] == before

    def test_the_athlete_is_handed_the_player_and_the_page_and_nothing_else(self, world):  # noqa: F811
        add_fb(world)
        clip = shelf(world, "teen")["clips"][0]
        assert clip["embed_url"].startswith("https://www.facebook.com/plugins/video.php?")
        assert clip["page_url"] == f"https://www.facebook.com/reel/{ID}/"
        assert clip.get("media_url") in (None, ""), "there is no file of ours to play"

    def test_an_athlete_or_parent_cannot_add_one(self, world):  # noqa: F811
        assert add_fb(world, who="teen").status_code == 403


class TestNothingIsReHosted:
    """The promise: someone else's video is only ever shown in their own player."""

    def test_no_code_path_fetches_a_facebook_or_instagram_video(self):
        root = Path(film.__file__).parent
        for path in root.glob("*.py"):
            src = path.read_text(encoding="utf-8")
            for bad in ("yt_dlp", "youtube_dl", "fbcdn", "cdninstagram", "video_redirect", "playable_url"):
                assert bad not in src, f"{path.name} mentions {bad}"
        # The only outbound call in the film module is the one that reads a Location header.
        src = (root / "film.py").read_text(encoding="utf-8")
        assert src.count("opener.open(") == 1 and src.count("urlopen(") == 0

    def test_an_embedded_clip_never_has_a_file(self, world):  # noqa: F811
        add_fb(world)
        row = world["store"].conn.execute("SELECT media_bytes FROM clips").fetchone()
        assert int(row["media_bytes"] or 0) == 0
        film_dir = world["tmp"] / "film"
        assert not film_dir.exists() or not any(film_dir.iterdir())

    def test_the_upload_route_still_asks_whose_video_it_is(self):
        page = (STATIC / "coach.html").read_text(encoding="utf-8")
        assert "This is my video to share, and the people in it are fine with the team seeing it." in page


class TestTheScreens:
    def test_the_coach_form_knows_a_facebook_link_and_says_what_it_cannot_do(self):
        page = (STATIC / "coach.html").read_text(encoding="utf-8")
        assert "const isFacebookLink" in page and "YouTube, Instagram or Facebook link" in page
        for phrase in ("0FFDAYS does not copy or keep the video", "It must be <b>public</b>", "not how much they watched",
                       'On an iPhone, Facebook may show a "View Video" button'):
            assert phrase in page, phrase

    def test_the_athlete_page_plays_it_in_facebooks_player_and_offers_the_page(self):
        page = (STATIC / "capture.html").read_text(encoding="utf-8")
        assert "const EMBEDDED_FROM = { instagram: 'Instagram', facebook: 'Facebook' };" in page
        assert 'id="film-page" target="_blank" rel="noopener noreferrer"' in page
        assert "frame.src = clip.embed_url" in page

    def test_facebook_is_only_contacted_when_a_clip_is_opened(self):
        for name in ("capture.html", "coach.html", "index.html", "parent.html"):
            page = (STATIC / name).read_text(encoding="utf-8")
            assert not re.search(r'<(iframe|script)[^>]+src="https://(www\.|connect\.)?facebook\.(com|net)', page), name
            assert "connect.facebook.net" not in page, name

    def test_the_privacy_page_names_facebook(self):
        page = (STATIC / "privacy.html").read_text(encoding="utf-8")
        assert "Facebook (Meta)" in page and "do not download, copy or store the video" in page
        assert "asks Facebook\n    once which video it points to" in page.replace("\r\n", "\n")

    def test_the_words_follow_the_house_rules(self):
        note = (STATIC / "coach.html").read_text(encoding="utf-8").split('id="clip-ig-note"', 1)[1].split("</div>", 1)[0]
        assert "\u2014" not in note and "\u2013" not in note
        assert not re.search(r"\b(he|she|his|her|him)\b", re.sub(r"<[^>]+>", " ", note), re.I)
