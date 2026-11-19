"""The first email to a parent says why, what the athlete gets, and what it runs on.

A parent deciding whether to let an app point a camera at their child wants three answers before the link: why is the
program doing this, what does my child get out of it (body and mind), and what do we need to use it. The email gives all
three, above the link, in plain words. Every claim in it is something the app really does, and none promises a health
outcome.
"""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import offdays
import offdays.api as api_module
from offdays import invites, mailer
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store

STATIC = Path(offdays.__file__).parent / "web" / "static"


def kinds():
    one = invites.compose(athlete_name="Ben Amden", org_name="Nashville Dogs", coach_name="Matt Kallberg", code="ABCD-EFGH-JKLM")
    note = invites.compose(athlete_name="Ben Amden", org_name="Nashville Dogs", coach_name="Matt Kallberg", code="ABCD-EFGH-JKLM",
                           intro="Hi all.", reply_to="matt@x.example")
    fam = invites.compose(athlete_name="Dillon Langdon", org_name="Nashville Dogs", coach_name="Matt Kallberg",
                          code="ABCD-EFGH-JKLM", also=["Killian Langdon"])
    return {"one child": one, "with a note": note, "a family": fam}


@pytest.fixture(params=["one child", "with a note", "a family"])
def mail(request):
    subject, html, text = kinds()[request.param]
    return subject, html, text


def plain(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


class TestItAnswersTheThreeQuestions:
    def test_it_says_why_the_program_is_doing_this(self, mail):
        _, html, text = mail
        assert "Why we are doing this:" in text and "<b>Why we are doing this.</b>" in html
        assert "Practice is only a few hours a week" in text and "Most of the improvement happens on the days in between" in text
        assert "shows Matt Kallberg who is putting in the effort" in text

    def test_it_says_what_the_athlete_gets_physically_and_mentally(self, mail):
        _, html, text = mail
        assert "* Physically:" in text and "* Mentally:" in text
        assert "<b>Physically:</b>" in html and "<b>Mentally:</b>" in html
        for word in ("push-ups", "planks", "jump rope", "strength", "conditioning", "coordination", "short"):
            assert word in text, word
        for word in ("habit of showing up", "confidence", "streaks and badges", "something is sore"):
            assert word in text, word

    def test_it_says_it_works_on_a_phone_or_a_tablet(self, mail):
        _, html, text = mail
        assert "Works on a phone or a tablet." in text and "<b>Works on a phone or a tablet.</b>" in html
        assert "Any phone or tablet with a camera and a web browser will do" in text
        assert "There is nothing to download" in text
        assert "own phone or tablet" in text and "never leaves the phone or tablet" in text
        assert "sign-in link" in text and re.search(r"text or email to (\w+'s|that athlete's) phone or\s+tablet", text)

    def test_the_html_says_the_same_things_as_the_text(self, mail):
        _, html, text = mail
        words = plain(html)
        for phrase in ("Why we are doing this", "Physically", "Mentally", "Works on a phone or a tablet",
                       "Practice is only a few hours a week", "with a camera and a web browser"):
            assert phrase in words, phrase

    def test_the_reasons_come_before_the_link(self, mail):
        _, html, text = mail
        assert text.index("Why we are doing this") < text.index("Physically") < text.index("Works on a phone") \
            < text.index("Open this link")
        assert html.index("Why we are doing this") < html.index("Physically") < html.index("Works on a phone") \
            < html.index("Set up ")

    def test_it_stays_short_enough_to_read(self, mail):
        _, _, text = mail
        assert len(text) < 3800 and text.count("\n\n") < 22


class TestItIsWrittenTheWayWeWrite:
    def test_no_dashes_as_punctuation(self, mail):
        _, html, text = mail
        assert "\u2014" not in text + html and "\u2013" not in text + html and " -- " not in text + html

    def test_american_spelling(self, mail):
        _, html, text = mail
        for british in ("colour", "favour", "organis", "programme", "behaviour", "centre", "practise", "catalogue",
                        "defence", "training programme", "whilst", "tyre"):
            assert british not in (text + html).lower(), british

    def test_no_assumption_about_a_childs_gender(self, mail):
        _, html, text = mail
        assert not re.search(r"\b(he|she|his|her|hers|him|boy|girl|son|daughter)\b", text, re.I)

    def test_no_health_promise(self, mail):
        _, html, text = mail
        for word in ("guarantee", "prevent", "cure", "treat ", "therapy", "anxiety", "depress", "injury-free", "lose weight",
                     "medical", "doctor"):
            assert word not in text.lower(), word

    def test_it_does_not_send_a_parent_to_an_app_store(self, mail):
        _, html, text = mail
        assert "app store" not in text.lower() and "google play" not in text.lower() and "testflight" not in text.lower()


class TestEveryClaimIsSomethingTheAppDoes:
    def test_the_drill_catalog_has_the_strength_and_conditioning_work_it_names(self):
        from offdays.drills.catalog import ALL_DRILLS
        names = {d.name for d in ALL_DRILLS}
        assert {"Push-Ups", "Plank Hold", "Jump Rope"} <= names

    def test_streaks_and_badges_exist(self):
        from offdays import badge, scoring
        assert callable(scoring.compute_streak) and badge is not None

    def test_the_soreness_check_in_exists_and_an_athlete_can_reach_it(self):
        paths = {r.path for r in api_module.app.routes}
        assert "/api/wellness/checkin" in paths
        assert "/api/wellness/checkin" in (STATIC / "capture.html").read_text(encoding="utf-8")

    def test_the_weekly_plan_is_sized_by_age_and_rest_is_suggested(self):
        from offdays import week_plan
        assert callable(week_plan._compose_line)
        assert "rest_recommended" in (Path(offdays.__file__).parent / "store.py").read_text(encoding="utf-8")

    def test_it_runs_in_a_browser_on_the_devices_camera_with_nothing_to_install(self):
        capture = (STATIC / "capture.html").read_text(encoding="utf-8")
        assert "navigator.mediaDevices.getUserMedia" in capture
        assert (STATIC / "manifest.webmanifest").exists() or (STATIC / "manifest.json").exists()

    def test_coaches_see_numbers_never_footage(self):
        # the sentence the email leans on: no video upload route exists
        paths = [r.path for r in api_module.app.routes]
        assert not [p for p in paths if "upload" in p and "video" in p]


class TestOtherEmailsAreNotChanged:
    def test_the_coach_sign_in_email_is_not_a_pitch(self):
        _, _, text = invites.compose_staff(coach_name="Sam", org_name="Nashville Dogs", director_name="Matt", code="ABCDEF")
        assert "Why we are doing this" not in text and "Physically" not in text

    def test_a_note_from_the_sender_still_comes_first(self):
        _, _, text = kinds()["with a note"]
        assert text.startswith("Hi all.\n\nMatt Kallberg at Nashville Dogs uses 0FFDAYS")


class TestWhatTheDirectorSeesAndSends:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        patched = replace(CONFIG, smtp_host="smtp.test", app_base_url="https://app.0ffdays.com")
        for mod in (invites, mailer):
            monkeypatch.setattr(mod, "CONFIG", patched)
        monkeypatch.setattr(api_module, "CONFIG", patched)
        sent = []

        class Rec:
            def send(self, to_email, subject, html, text, headers):
                sent.append({"to": to_email, "text": text, "html": html})
                return mailer.SendResult(ok=True)

        monkeypatch.setattr(mailer, "default_transport", lambda: Rec())
        api_module._store = Store(connect(tmp_path / "t.db"))
        c = TestClient(api_module.app)
        c.sent = sent
        yield c
        api_module._store = None

    def test_the_preview_and_the_real_email_carry_the_new_sections(self, client):
        made = client.post("/api/orgs", json={"name": "Nashville Dogs", "sport": "lacrosse", "accept_terms": True,
                                              "director_name": "Matt"}).json()
        h = {"Authorization": f"Bearer {made['director']['token']}"}
        pre = client.post("/api/coach/families/invite-preview", headers=h, json={"intro": ""}).json()
        assert "Why we are doing this" in pre["text"] and "phone or a tablet" in pre["text"]
        client.put("/api/org/mail-hold", headers=h, json={"held": False})
        team = client.post("/api/teams", json={"name": "2031 Red"}, headers=h).json()["id"]
        client.post("/api/coach/roster/import", headers=h, json={
            "content": "First Name,Last Name,Birth Year,Parent Email\nBen,Amden,2013,jess@example.com\n", "team_id": team})
        assert len(client.sent) == 1
        mail = client.sent[0]
        for part in (mail["text"], plain(mail["html"])):
            for phrase in ("Why we are doing this", "Physically", "Mentally", "phone or a tablet"):
                assert phrase in part, phrase
