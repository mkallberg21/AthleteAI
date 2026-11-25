"""Two more ways to put a clip on the film shelf: an Instagram link, and a video a coach made and uploaded."""
from __future__ import annotations

import dataclasses
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import film, staff_film
from offdays import store as store_mod
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store, StoreError

STATIC = Path(api_module.__file__).parent / "web" / "static"
YEAR = datetime.now(timezone.utc).year
REEL = "https://www.instagram.com/reel/Cabc123_-x/?igsh=MWtrackme"


def box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), kind) + body


def mp4(seconds: float = 30.0, brand: bytes = b"isom", junk: int = 2000, moov_first: bool = True) -> bytes:
    mvhd = box(b"mvhd", struct.pack(">IIIII", 0, 0, 0, 1000, int(seconds * 1000)) + b"\x00" * 80)
    parts = [box(b"moov", mvhd), box(b"mdat", b"\x07" * junk)]
    if not moov_first:
        parts.reverse()
    return box(b"ftyp", brand + b"\x00\x00\x02\x00isomiso2") + b"".join(parts)


WEBM = b"\x1a\x45\xdf\xa3" + b"\x01" * 400


@pytest.fixture
def world(tmp_path, monkeypatch):
    patched = dataclasses.replace(CONFIG, uploads_dir=tmp_path / "uploads", secret_key="test-secret")
    for mod in (api_module, store_mod, staff_film):
        monkeypatch.setattr(mod, "CONFIG", patched)
    store = Store(connect(tmp_path / "cs.db"))
    api_module._store = store
    org = store.create_org("Nashville Dogs", sport="lacrosse")
    other_org = store.create_org("Other Club", sport="lacrosse")
    people = {
        "director": store.create_user(org, "director", "Matt"),
        "coach": store.create_user(org, "coach", "Coach Tommy"),
        "teen": store.create_user(org, "athlete", "Teen", birth_year=YEAR - 15),
        "thirteen": store.create_user(org, "athlete", "Thirteen", birth_year=YEAR - 13),
        "kid": store.create_user(org, "athlete", "Kid", birth_year=YEAR - 11),
        "unknown": store.create_user(org, "athlete", "Unknown"),
        "outsider": store.create_user(other_org, "athlete", "Outsider", birth_year=YEAR - 15),
        "other_coach": store.create_user(other_org, "coach", "Other Coach"),
    }
    guess = store.create_user(org, "athlete", "Guess", birth_year=YEAR - 15)
    store.conn.execute("UPDATE users SET birth_year_estimated = 1 WHERE id = ?", (guess["id"],))
    store.conn.execute("UPDATE organizations SET default_shelf = 0")
    store.conn.commit()
    people["guess"] = guess
    client = TestClient(api_module.app)
    yield {"client": client, "store": store, "org": org, "other_org": other_org, "p": people, "tmp": tmp_path}
    api_module._store = None


def h(w, who):
    return {"Authorization": f"Bearer {w['p'][who]['token']}"}


def add_ig(w, link=REEL, who="coach", **extra):
    return w["client"].post("/api/coach/clips", headers=h(w, who),
                            json={"video": link, "title": "Reading the slide", "focus": "Watch the crease", **extra})


def upload(w, data=None, who="coach", name="clip.mp4", **fields):
    form = {"title": "Our ride against a zone", "focus": "Watch the middie", "length_s": "30", "rights": "yes", **fields}
    return w["client"].post("/api/coach/clips/file", headers=h(w, who), data=form,
                            files={"file": (name, mp4() if data is None else data, "video/mp4")})


def shelf(w, who):
    return w["client"].get("/api/film", headers=h(w, who)).json()


def titles(w, who):
    return [c["title"] for c in shelf(w, who)["clips"]]


class TestReadingAnInstagramLink:
    @pytest.mark.parametrize("link,want", [
        (REEL, "reel/Cabc123_-x"),
        ("https://instagram.com/p/Cxyz12345/", "p/Cxyz12345"),
        ("https://www.instagram.com/some.user/reel/Cabc12345/", "reel/Cabc12345"),
        ("https://www.instagram.com/reels/Cabc12345", "reel/Cabc12345"),
        ("instagram.com/tv/Babc12345/", "tv/Babc12345"),
    ])
    def test_posts_and_reels_in_the_shapes_people_paste(self, link, want):
        assert film.parse_instagram(link) == want

    @pytest.mark.parametrize("link", [
        "https://www.instagram.com/some.user/", "https://www.instagram.com/", "https://youtu.be/dQw4w9WgXcQ",
        "https://notinstagram.com/reel/abcdef12/", "https://evil.example/?next=instagram.com/reel/abcdef12", "", "reel",
    ])
    def test_anything_else_is_not_one(self, link):
        assert film.parse_instagram(link) is None

    def test_only_the_kind_and_code_are_kept_never_the_share_tracking(self, world):
        made = add_ig(world).json()
        assert made["provider"] == "instagram" and made["video_id"] == "reel/Cabc123_-x"
        assert made["embed_url"] == "https://www.instagram.com/reel/Cabc123_-x/embed/"
        assert "igsh" not in str(made)

    def test_a_stored_id_that_is_not_the_right_shape_makes_no_embed_address(self):
        assert film.embed_url("instagram", "reel/x\"><script>", 0, None) == ""


class TestAnInstagramClip:
    def test_a_coach_adds_one_with_no_end_time_and_it_is_for_13_and_over(self, world):
        r = add_ig(world)
        assert r.status_code == 201, r.text
        made = r.json()
        assert made["min_age"] == film.INSTAGRAM_MIN_AGE and made["end_s"] is None and made["tracked"] is False

    def test_a_link_pasted_as_youtube_is_still_an_instagram_clip(self, world):
        assert add_ig(world, provider="youtube").json()["provider"] == "instagram"

    def test_a_youtube_clip_still_needs_its_end_time(self, world):
        r = world["client"].post("/api/coach/clips", headers=h(world, "coach"),
                                 json={"video": "https://youtu.be/dQw4w9WgXcQ", "title": "Sliding early"})
        assert r.status_code == 400 and "end time" in r.json()["detail"]

    def test_a_coach_cannot_lower_the_age(self, world):
        assert add_ig(world, min_age=8).json()["min_age"] == 13

    def test_a_profile_link_is_refused_in_plain_words(self, world):
        r = add_ig(world, link="https://www.instagram.com/some.user/", provider="instagram")
        assert r.status_code == 400 and "Instagram post or reel" in r.json()["detail"]

    def test_only_athletes_13_and_over_with_a_known_age_are_offered_it(self, world):
        add_ig(world)
        assert titles(world, "teen") == ["Reading the slide"]
        assert titles(world, "thirteen") == ["Reading the slide"]
        for who in ("kid", "unknown", "guess"):
            assert titles(world, who) == [], who

    def test_a_younger_athlete_cannot_open_it_by_asking_for_it_directly(self, world):
        cid = add_ig(world).json()["id"]
        for who in ("kid", "unknown", "guess"):
            r = world["client"].post(f"/api/film/{cid}/start", headers=h(world, who))
            assert r.status_code == 409, who
        assert world["store"].conn.execute("SELECT COUNT(*) FROM clip_watches").fetchone()[0] == 0

    def test_opening_it_is_recorded_as_opened_never_as_watched_and_earns_nothing(self, world):
        cid = add_ig(world).json()["id"]
        r = world["client"].post(f"/api/film/{cid}/start", headers=h(world, "teen"))
        assert r.status_code == 201
        row = world["store"].conn.execute("SELECT verdict, xp_awarded, watched_s FROM clip_watches").fetchone()
        assert (row["verdict"], row["xp_awarded"], row["watched_s"]) == ("opened", 0, 0)
        assert world["store"].conn.execute("SELECT COUNT(*) FROM xp_ledger").fetchone()[0] == 0

    def test_a_client_cannot_claim_to_have_watched_one(self, world):
        cid = add_ig(world).json()["id"]
        wid = world["client"].post(f"/api/film/{cid}/start", headers=h(world, "teen")).json()["watch_id"]
        r = world["client"].post(f"/api/film/watches/{wid}/beat", headers=h(world, "teen"), json={"position_s": 30})
        assert r.status_code == 404
        row = world["store"].conn.execute("SELECT verdict, xp_awarded FROM clip_watches").fetchone()
        assert (row["verdict"], row["xp_awarded"]) == ("opened", 0)

    def test_it_uses_one_of_the_days_clips_and_opening_again_is_counted(self, world):
        cid = add_ig(world).json()["id"]
        before = shelf(world, "teen")["day"]["clips_left"]
        world["client"].post(f"/api/film/{cid}/start", headers=h(world, "teen"))
        again = world["client"].post(f"/api/film/{cid}/start", headers=h(world, "teen")).json()
        after = shelf(world, "teen")
        assert after["day"]["clips_left"] == before - 1 and again["looks"] == 2
        assert [c["title"] for c in after["again"]] == ["Reading the slide"]

    def test_the_coach_sees_opened_not_watched(self, world):
        cid = add_ig(world).json()["id"]
        world["client"].post(f"/api/film/{cid}/start", headers=h(world, "teen"))
        s = world["store"]
        log = s.film_watch_log(world["p"]["teen"]["id"])
        assert log["clips"][0]["last_verdict"] == "opened"
        cov = s.clip_coverage(world["org"], [world["p"]["teen"]["id"], world["p"]["kid"]["id"]])["clips"][0]
        assert cov["tracked"] is False and cov["watched_count"] == 0
        assert [a["display_name"] for a in cov["started"]] == ["Teen"]

    def test_an_athlete_can_say_it_did_not_show_and_gets_the_slot_back(self, world):
        cid = add_ig(world).json()["id"]
        before = shelf(world, "teen")["day"]["clips_left"]
        wid = world["client"].post(f"/api/film/{cid}/start", headers=h(world, "teen")).json()["watch_id"]
        r = world["client"].post(f"/api/film/watches/{wid}/unavailable", headers=h(world, "teen"))
        assert r.status_code == 200 and r.json()["counted"] is True
        after = shelf(world, "teen")
        assert after["day"]["clips_left"] == before and after["clips"] == []


class TestTheFileItself:
    def test_the_kind_comes_from_the_bytes(self):
        assert staff_film.sniff(mp4()[:64]) == "mp4"
        assert staff_film.sniff(mp4(brand=b"qt  ")[:64]) == "mov"
        assert staff_film.sniff(WEBM[:64]) == "webm"
        for junk in (b"%PDF-1.4 hello there and more", b"<html><script>alert(1)</script>", b"", b"MZ\x90\x00" + b"\x00" * 60):
            with pytest.raises(staff_film.VideoError):
                staff_film.sniff(junk)

    @pytest.mark.parametrize("moov_first", [True, False])
    def test_an_mp4_says_how_long_it_is_wherever_its_header_sits(self, tmp_path, moov_first):
        path = tmp_path / "a.mp4"
        path.write_bytes(mp4(42.5, moov_first=moov_first))
        assert staff_film.mp4_duration_s(path) == pytest.approx(42.5)

    def test_a_damaged_file_has_no_length_rather_than_an_error(self, tmp_path):
        path = tmp_path / "b.mp4"
        for data in (mp4()[:30], b"\x00\x00\x00\x08ftyp" + b"\xff" * 50, b""):
            path.write_bytes(data)
            assert staff_film.mp4_duration_s(path) is None

    def test_only_names_this_made_become_a_path(self, world):
        staff_film.folder().mkdir(parents=True)
        (staff_film.folder().parent / "secret.mp4").write_bytes(b"x")
        for name in ("../secret.mp4", "..\\secret.mp4", "clip-1-zz.mp4", "org-1.png", "", "clip-1-" + "a" * 24 + ".exe"):
            assert staff_film.path_for(name) is None, name

    def test_range_requests(self):
        assert staff_film.parse_range(None, 100) is None
        assert staff_film.parse_range("bytes=0-", 100) == (0, 99)
        assert staff_film.parse_range("bytes=10-19", 100) == (10, 19)
        assert staff_film.parse_range("bytes=90-500", 100) == (90, 99)
        assert staff_film.parse_range("bytes=-10", 100) == (90, 99)
        assert staff_film.parse_range("bytes=100-", 100) == (-1, -1)
        assert staff_film.parse_range("bytes=5-2", 100) == (-1, -1)
        assert staff_film.parse_range("items=0-5", 100) is None


class TestACoachUploadsTheirOwnVideo:
    def test_it_goes_on_the_shelf_with_its_real_length(self, world):
        r = upload(world, mp4(42.4), length_s="999")
        assert r.status_code == 201, r.text
        made = r.json()
        assert made["provider"] == "upload" and made["length_s"] == 42 and made["tracked"] is True
        assert made["embed_url"] == "" and "media_url" not in made
        files = list(staff_film.folder().iterdir())
        assert len(files) == 1 and files[0].read_bytes() == mp4(42.4)
        row = world["store"].conn.execute("SELECT media_bytes, rights_ok_at, video_id FROM clips").fetchone()
        assert row["media_bytes"] == len(mp4(42.4)) and row["rights_ok_at"] and row["video_id"] == files[0].name

    def test_it_is_not_in_the_public_uploads_folder(self, world):
        upload(world)
        name = next(staff_film.folder().iterdir()).name
        assert staff_film.folder() != world["tmp"] / "uploads"
        assert world["client"].get(f"/uploads/{name}").status_code == 404
        assert world["client"].get(f"/app/{name}").status_code == 404

    def test_the_box_must_be_ticked(self, world):
        r = upload(world, rights="")
        assert r.status_code == 400 and "your video to share" in r.json()["detail"]
        assert not staff_film.folder().exists() or not list(staff_film.folder().iterdir())

    def test_not_a_video_is_refused_whatever_it_is_called(self, world):
        r = upload(world, b"%PDF-1.4 " + b"x" * 200, name="clip.mp4")
        assert r.status_code == 415
        assert not list(staff_film.folder().iterdir()) if staff_film.folder().exists() else True

    def test_too_long_is_refused_and_the_file_is_not_kept(self, world):
        r = upload(world, mp4(600))
        assert r.status_code == 400 and "600 seconds" in r.json()["detail"] and "240" in r.json()["detail"]
        assert list(staff_film.folder().iterdir()) == []

    def test_too_big_is_refused_and_the_file_is_not_kept(self, world, monkeypatch):
        monkeypatch.setattr(staff_film, "MAX_BYTES", 1500)
        r = upload(world, mp4(junk=5000))
        assert r.status_code == 413 and "MB" in r.json()["detail"]
        assert list(staff_film.folder().iterdir()) == []

    def test_a_program_has_an_allowance(self, world, monkeypatch):
        monkeypatch.setattr(staff_film, "ORG_QUOTA_BYTES", len(mp4()) + 500)
        assert upload(world).status_code == 201
        r = upload(world)
        assert r.status_code == 413 and "Remove one first" in r.json()["detail"]
        assert len(list(staff_film.folder().iterdir())) == 1

    def test_a_webm_uses_the_length_the_browser_measured(self, world):
        r = upload(world, WEBM, name="c.webm", length_s="12.4")
        assert r.status_code == 201 and r.json()["length_s"] == 12
        assert upload(world, WEBM, name="c.webm", length_s="0").status_code == 400

    def test_a_highlight_reel_title_is_refused_like_any_other_clip(self, world):
        marker = next(t for t in ("Best goals of 2026", "Top 10 plays", "Season highlights", "Highlight reel")
                      if film.looks_like_highlights(t))
        assert upload(world, title=marker).status_code == 400

    def test_a_question_can_ride_along(self, world):
        q = '{"prompt":"Who slides?","options":["Crease","Adjacent"],"answer":0,"because":"Crease is closest"}'
        made = upload(world, question=q).json()
        assert made["question"]["prompt"] == "Who slides?" and "answer" not in made["question"]
        assert upload(world, question="{not json").status_code == 400

    def test_athletes_and_parents_cannot_upload(self, world):
        assert upload(world, who="teen").status_code == 403

    def test_removing_the_clip_deletes_the_file_and_frees_the_space(self, world):
        cid = upload(world).json()["id"]
        assert world["store"].uploaded_video_bytes(world["org"]) > 0
        assert world["client"].delete(f"/api/coach/clips/{cid}", headers=h(world, "coach")).json()["retired"] is True
        assert list(staff_film.folder().iterdir()) == []
        assert world["store"].uploaded_video_bytes(world["org"]) == 0

    def test_another_program_cannot_remove_it(self, world):
        cid = upload(world).json()["id"]
        r = world["client"].delete(f"/api/coach/clips/{cid}", headers=h(world, "other_coach"))
        assert r.json()["retired"] is False and len(list(staff_film.folder().iterdir())) == 1


class TestPlayingIt:
    def start(self, w, who="teen"):
        cid = upload(w, mp4(30)).json()["id"]
        r = w["client"].post(f"/api/film/{cid}/start", headers=h(w, who))
        return cid, r

    def test_the_athlete_is_given_an_address_that_plays_with_no_sign_in_header(self, world):
        cid, r = self.start(world)
        assert r.status_code == 201
        url = r.json()["media_url"]
        assert url.startswith(f"/api/film/media/{cid}?k=") and r.json()["media_type"] == "video/mp4"
        got = world["client"].get(url)
        assert got.status_code == 200 and got.content == mp4(30) and got.headers["content-type"] == "video/mp4"
        assert got.headers["accept-ranges"] == "bytes" and "private" in got.headers["cache-control"]

    def test_a_phone_can_ask_for_part_of_it(self, world):
        cid, r = self.start(world)
        url, data = r.json()["media_url"], mp4(30)
        part = world["client"].get(url, headers={"Range": "bytes=100-299"})
        assert part.status_code == 206 and part.content == data[100:300]
        assert part.headers["content-range"] == f"bytes 100-299/{len(data)}" and part.headers["content-length"] == "200"
        tail = world["client"].get(url, headers={"Range": "bytes=-50"})
        assert tail.status_code == 206 and tail.content == data[-50:]
        assert world["client"].get(url, headers={"Range": f"bytes={len(data)}-"}).status_code == 416

    def test_no_key_a_wrong_key_or_another_clips_key_gets_nothing(self, world):
        cid, r = self.start(world)
        other = upload(world, mp4(20)).json()["id"]
        key = r.json()["media_url"].split("k=")[1]
        assert world["client"].get(f"/api/film/media/{cid}").status_code == 404
        assert world["client"].get(f"/api/film/media/{cid}?k={key[:-2]}zz").status_code == 404
        assert world["client"].get(f"/api/film/media/{other}?k={key}").status_code == 404
        assert world["client"].get(f"/api/film/media/{cid}", headers=h(world, "teen")).status_code == 404

    def test_a_key_stops_working_after_a_few_hours(self, world):
        cid, _ = self.start(world)
        uid = world["p"]["teen"]["id"]
        old = staff_film.play_key(cid, uid, now=time.time() - staff_film.KEY_TTL_S - 5)
        assert world["client"].get(f"/api/film/media/{cid}?k={old}").status_code == 404
        assert staff_film.read_key(cid, staff_film.play_key(cid, uid)) == uid

    def test_a_key_cannot_be_made_for_someone_else_by_editing_it(self, world):
        cid, r = self.start(world)
        user, exp, sig = r.json()["media_url"].split("k=")[1].split(".")
        forged = f"{world['p']['outsider']['id']}.{exp}.{sig}"
        assert world["client"].get(f"/api/film/media/{cid}?k={forged}").status_code == 404
        later = f"{user}.{int(exp) + 99999}.{sig}"
        assert world["client"].get(f"/api/film/media/{cid}?k={later}").status_code == 404

    def test_someone_from_another_program_cannot_start_or_play_it(self, world):
        cid, _ = self.start(world)
        assert world["client"].post(f"/api/film/{cid}/start", headers=h(world, "outsider")).status_code == 409
        key = staff_film.play_key(cid, world["p"]["outsider"]["id"])
        assert world["client"].get(f"/api/film/media/{cid}?k={key}").status_code == 404

    def test_it_stops_playing_when_the_clip_is_removed_or_the_player_leaves(self, world):
        cid, r = self.start(world)
        url = r.json()["media_url"]
        world["store"].conn.execute("UPDATE users SET active = 0 WHERE id = ?", (world["p"]["teen"]["id"],))
        world["store"].conn.commit()
        assert world["client"].get(url).status_code == 404
        world["store"].conn.execute("UPDATE users SET active = 1 WHERE id = ?", (world["p"]["teen"]["id"],))
        world["store"].conn.commit()
        assert world["client"].get(url).status_code == 200
        world["client"].delete(f"/api/coach/clips/{cid}", headers=h(world, "coach"))
        assert world["client"].get(url).status_code == 404

    def test_watching_it_is_scored_like_any_tracked_clip(self, world):
        cid, r = self.start(world)
        wid = r.json()["watch_id"]
        s = world["store"]
        t0 = datetime.now(timezone.utc)
        from datetime import timedelta
        out = None
        for i in range(1, 11):
            out = s.record_beat(world["p"]["teen"]["id"], wid, i * 3.0, now=t0 + timedelta(seconds=i * 3))
        assert out["verdict"] == "watched" and out["xp_awarded"] == film.XP_PER_WATCH

    def test_the_coach_can_play_back_what_they_uploaded(self, world):
        upload(world, mp4(30))
        listed = world["client"].get("/api/coach/clips", headers=h(world, "coach")).json()
        clip = listed["clips"][0]
        assert world["client"].get(clip["media_url"]).status_code == 200
        assert listed["own_video"]["used_mb"] >= 0 and listed["own_video"]["max_s"] == 240
        assert listed["instagram_min_age"] == 13

    def test_every_age_is_offered_a_coachs_own_clip_that_fits_their_band(self, world):
        upload(world, mp4(30))
        for who in ("teen", "kid", "unknown", "guess"):
            assert titles(world, who) == ["Our ride against a zone"], who
        assert titles(world, "outsider") == []


class TestWhatDidNotChange:
    def test_a_youtube_clip_is_made_and_scored_as_before(self, world):
        r = world["client"].post("/api/coach/clips", headers=h(world, "coach"), json={
            "video": "https://youtu.be/dQw4w9WgXcQ", "title": "Sliding early", "end_s": 60})
        assert r.status_code == 201
        made = r.json()
        assert made["provider"] == "youtube" and made["tracked"] is True and "youtube-nocookie.com" in made["embed_url"]
        assert titles(world, "kid") == ["Sliding early"]

    def test_the_store_refuses_an_upload_clip_whose_file_is_not_there(self, world):
        with pytest.raises(StoreError):
            world["store"].create_clip(world["org"], "clip-1-" + "a" * 24 + ".mp4", "T", provider="upload", end_s=30)


class TestTheScreens:
    def test_the_athlete_page_plays_all_three_kinds(self):
        page = (STATIC / "capture.html").read_text(encoding="utf-8")
        assert "EMBEDDED_FROM[clip.provider]" in page and "clip.provider === 'upload'" in page
        assert "filmWatch.media_url" in page and "frame.src = clip.embed_url" in page
        assert "Your coach can see that you opened it, not how much you watched." in page
        assert 'id="film-wont-show"' in page

    def test_instagram_is_only_contacted_when_a_clip_is_opened(self):
        for name in ("capture.html", "coach.html", "index.html", "parent.html"):
            page = (STATIC / name).read_text(encoding="utf-8")
            assert "<iframe src=\"https://www.instagram.com" not in page and "instagram.com/embed.js" not in page, name

    def test_the_coach_page_says_what_an_instagram_clip_cannot_do(self):
        page = (STATIC / "coach.html").read_text(encoding="utf-8")
        for phrase in ("It must be <b>public</b>", "not how much they watched", "'s own minimum age is 13",
                       "This is my video to share, and the people in it are fine with the team seeing it.",
                       "'/api/coach/clips/file'", "opened (that player does not say more)"):
            assert phrase in page, phrase
        assert "Nothing is uploaded or re-hosted" not in page

    def test_the_privacy_page_names_instagram_and_the_coachs_video(self):
        page = (STATIC / "privacy.html").read_text(encoding="utf-8")
        assert "Instagram (Meta)" in page and "not shown to athletes under 13" in page
        assert "A video a coach chooses to upload for film study" in page
