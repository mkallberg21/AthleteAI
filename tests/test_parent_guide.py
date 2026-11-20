"""The guide for parents rides on the invite email, with the program's own logo at the top."""
from __future__ import annotations

import dataclasses
import io
import smtplib
from dataclasses import replace
from email import message_from_bytes

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import invites, mailer, parent_guide
from offdays import store as store_mod
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store


def make_png(size=(600, 200), color=(200, 30, 30, 255)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return buf.getvalue()


def pdf_images(data: bytes) -> int:
    from pypdf import PdfReader
    page = PdfReader(io.BytesIO(data)).pages[0]
    return len(page.images)


class Modern:
    def __init__(self):
        self.sent = []

    def send(self, to_email, subject, html, text, headers, attachments=None):
        self.sent.append({"to": to_email, "subject": subject, "text": text, "html": html, "attachments": attachments or []})
        return mailer.SendResult(ok=True)


class Old:
    """A transport written before attachments existed."""
    def __init__(self):
        self.sent = []

    def send(self, to_email, subject, html, text, headers):
        self.sent.append({"to": to_email, "text": text})
        return mailer.SendResult(ok=True)


@pytest.fixture
def world(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    patched = replace(CONFIG, smtp_host="smtp.test", app_base_url="https://app.0ffdays.com", uploads_dir=uploads,
                      smtp_from="0FFDAYS <no-reply@mail.0ffdays.com>")
    for mod in (mailer, invites, parent_guide, api_module, store_mod):
        monkeypatch.setattr(mod, "CONFIG", patched)
    parent_guide._cache.clear()
    rec = Modern()
    monkeypatch.setattr(mailer, "default_transport", lambda: rec)
    store = Store(connect(tmp_path / "pg.db"))
    api_module._store = store
    client = TestClient(api_module.app)
    made = client.post("/api/orgs", json={"name": "Nashville Dogs", "sport": "lacrosse", "accept_terms": True,
                                          "director_name": "Matt Kallberg"}).json()
    h = {"Authorization": f"Bearer {made['director']['token']}"}
    yield {"client": client, "h": h, "org": made["org_id"], "store": store, "rec": rec, "uploads": uploads}
    api_module._store = None


def upload_logo(w, data, name="logo.png"):
    return w["client"].post("/api/org/logo", headers=w["h"], files={"file": (name, data, "image/png")})


def release_and_import(w, email="jess@example.com"):
    w["client"].put("/api/org/mail-hold", headers=w["h"], json={"held": False})
    team = w["client"].post("/api/teams", json={"name": "2031 Red"}, headers=w["h"]).json()["id"]
    r = w["client"].post("/api/coach/roster/import", headers=w["h"], json={
        "content": f"First Name,Last Name,Birth Year,Parent Email\nBen,Amden,2013,{email}\n", "team_id": team})
    assert r.status_code in (200, 201), r.text


class TestTheGuideFile:
    def test_the_two_pdfs_are_shipped(self):
        assert (parent_guide.ASSETS / "guide_plain.pdf").is_file() and (parent_guide.ASSETS / "guide_logo.pdf").is_file()
        assert parent_guide.available()

    def test_a_program_with_a_logo_gets_it_on_the_first_page(self, world):
        upload_logo(world, make_png())
        with_logo = parent_guide.guide_pdf(world["store"].conn, world["org"])
        plain = (parent_guide.ASSETS / "guide_logo.pdf").read_bytes()
        assert with_logo.startswith(b"%PDF") and with_logo != plain
        assert pdf_images(with_logo) == pdf_images(plain) + 1

    def test_the_logo_lands_inside_the_header_band_at_the_top_left(self, world):
        pytest.importorskip("pypdfium2")
        import pypdfium2 as pdfium
        upload_logo(world, make_png(color=(200, 30, 30, 255)))
        data = parent_guide.guide_pdf(world["store"].conn, world["org"])
        img = pdfium.PdfDocument(data)[0].render(scale=1).to_pil().convert("RGB")
        # 0.75 pt per css px at scale 1 => 1 px of image per pt. The tile is white, the logo red, inside 88 css px.
        reds = [(x, y) for x in range(0, 300, 3) for y in range(0, 70, 3) if img.getpixel((x, y))[0] > 150 and img.getpixel((x, y))[1] < 80]
        assert reds, "no logo pixels in the header band"
        assert max(y for _, y in reds) < 66 and min(x for x, _ in reds) >= 18

    def test_no_logo_means_the_plain_guide(self, world):
        assert parent_guide.guide_pdf(world["store"].conn, world["org"]) == (parent_guide.ASSETS / "guide_plain.pdf").read_bytes()

    @pytest.mark.parametrize("junk", [b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, b"\xff\xd8\xff\xe0" + b"\x00" * 64, b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64])
    def test_a_logo_that_cannot_be_read_still_gets_a_guide(self, world, junk):
        (world["uploads"] / f"org-{world['org']}.png").write_bytes(junk)
        world["store"].conn.execute("UPDATE organizations SET logo_file = ? WHERE id = ?", (f"org-{world['org']}.png", world["org"]))
        world["store"].conn.commit()
        assert parent_guide.guide_pdf(world["store"].conn, world["org"]) == (parent_guide.ASSETS / "guide_plain.pdf").read_bytes()

    def test_an_svg_logo_falls_back_to_the_plain_guide(self, world):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle r="4"/></svg>'
        r = world["client"].post("/api/org/logo", headers=world["h"], files={"file": ("a.svg", svg, "image/svg+xml")})
        assert r.status_code == 201
        assert parent_guide.guide_pdf(world["store"].conn, world["org"]) == (parent_guide.ASSETS / "guide_plain.pdf").read_bytes()

    def test_the_preset_club_logos_work_too(self, world):
        world["store"].set_org_logo(world["org"], "nashville-dogs.png")
        assert pdf_images(parent_guide.guide_pdf(world["store"].conn, world["org"])) == pdf_images(
            (parent_guide.ASSETS / "guide_logo.pdf").read_bytes()) + 1

    def test_a_huge_picture_is_refused_not_decoded(self, world, monkeypatch):
        monkeypatch.setattr(parent_guide, "_MAX_PIXELS", 100)
        upload_logo(world, make_png())
        assert parent_guide.guide_pdf(world["store"].conn, world["org"]) == (parent_guide.ASSETS / "guide_plain.pdf").read_bytes()

    def test_another_programs_logo_is_never_used(self, world):
        upload_logo(world, make_png())
        other = world["store"].create_org("Other Club")
        assert parent_guide.guide_pdf(world["store"].conn, other) == (parent_guide.ASSETS / "guide_plain.pdf").read_bytes()

    def test_a_logo_name_cannot_point_outside_the_folders(self, world):
        (world["uploads"].parent / "secret.png").write_bytes(make_png())
        for name in ("../secret.png", "..\\secret.png", ".hidden.png"):
            world["store"].conn.execute("UPDATE organizations SET logo_file = ? WHERE id = ?", (name, world["org"]))
            assert parent_guide.logo_path(world["store"].conn, world["org"]) is None, name

    def test_a_new_logo_replaces_the_cached_guide(self, world):
        upload_logo(world, make_png(color=(200, 30, 30, 255)))
        a = parent_guide.guide_pdf(world["store"].conn, world["org"])
        upload_logo(world, make_png(color=(30, 30, 200, 255)))
        b = parent_guide.guide_pdf(world["store"].conn, world["org"])
        assert a != b

    def test_the_guide_has_no_real_family_in_it(self):
        html = (parent_guide.ASSETS / "guide.html").read_text(encoding="utf-8")
        assert "Tommy" not in html and "Ryder" not in html
        assert "\u2014" not in html and "\u2013" not in html


class TestTheEmail:
    def test_the_invite_carries_the_guide_with_the_programs_logo(self, world):
        upload_logo(world, make_png())
        release_and_import(world)
        sent = world["rec"].sent
        assert len(sent) == 1
        mail = sent[0]
        assert [a[0] for a in mail["attachments"]] == [parent_guide.FILENAME]
        name, mime, data = mail["attachments"][0]
        assert mime == "application/pdf" and data.startswith(b"%PDF")
        assert pdf_images(data) == pdf_images((parent_guide.ASSETS / "guide_logo.pdf").read_bytes()) + 1
        assert invites.GUIDE_LINE in mail["text"] and "attached" in mail["html"]

    def test_a_program_with_no_logo_still_sends_the_guide(self, world):
        release_and_import(world)
        mail = world["rec"].sent[0]
        assert mail["attachments"][0][2] == (parent_guide.ASSETS / "guide_plain.pdf").read_bytes()

    def test_each_program_gets_its_own_logo(self, world):
        upload_logo(world, make_png(color=(200, 30, 30, 255)))
        release_and_import(world, "a@example.com")
        mine = world["rec"].sent[0]["attachments"][0][2]
        assert mine != (parent_guide.ASSETS / "guide_plain.pdf").read_bytes()

    def test_nothing_goes_while_the_email_hold_is_on(self, world):
        team = world["client"].post("/api/teams", json={"name": "2031 Red"}, headers=world["h"]).json()["id"]
        world["client"].post("/api/coach/roster/import", headers=world["h"], json={
            "content": "First Name,Last Name,Birth Year,Parent Email\nBen,Amden,2013,jess@example.com\n", "team_id": team})
        assert world["rec"].sent == []
        assert world["store"].conn.execute("SELECT COUNT(*) FROM email_outbox WHERE attachment <> ''").fetchone()[0] == 0

    def test_the_queue_holds_a_name_not_a_megabyte(self, world):
        release_and_import(world)
        row = world["store"].conn.execute("SELECT attachment, length(html_body) + length(text_body) AS n FROM email_outbox").fetchone()
        assert row["attachment"] == f"parent_guide:{world['org']}" and row["n"] < 20000

    def test_other_emails_carry_nothing(self, world):
        release_and_import(world)
        before = len(world["rec"].sent)
        mailer.enqueue(world["store"].conn, to_email="x@example.com", subject="s", html="h", text="t",
                       kind=mailer.Kind.TRANSACTIONAL, dedupe_key="plain:1")
        mailer.flush(world["store"].conn)
        assert world["rec"].sent[before]["attachments"] == []

    def test_an_old_style_transport_still_delivers_the_invite_without_it(self, world, monkeypatch):
        old = Old()
        monkeypatch.setattr(mailer, "default_transport", lambda: old)
        release_and_import(world)
        assert len(old.sent) == 1 and "Ben" in old.sent[0]["text"]

    def test_if_the_guide_cannot_be_made_the_invite_still_goes(self, world, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no pillow")
        monkeypatch.setattr(parent_guide, "attachments_for", boom)
        release_and_import(world)
        assert len(world["rec"].sent) == 1 and world["rec"].sent[0]["attachments"] == []

    def test_the_director_preview_says_the_guide_is_attached_only_when_it_will_be(self, world):
        pre = world["client"].post("/api/coach/families/invite-preview", headers=world["h"], json={"intro": ""}).json()
        assert pre["sending"] is False and invites.GUIDE_LINE not in pre["text"]
        world["client"].put("/api/org/mail-hold", headers=world["h"], json={"held": False})
        pre = world["client"].post("/api/coach/families/invite-preview", headers=world["h"], json={"intro": ""}).json()
        assert pre["sending"] is True and invites.GUIDE_LINE in pre["text"]


class TestSmtp:
    def test_the_message_on_the_wire_has_the_pdf_attached(self, monkeypatch):
        captured = {}

        class FakeSMTP:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def starttls(self): pass
            def login(self, *a): pass
            def send_message(self, message): captured["m"] = message

        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        monkeypatch.setattr(mailer, "CONFIG", replace(CONFIG, smtp_host="smtp.test", smtp_user=""))
        res = mailer.SmtpTransport().send("a@example.com", "Hi", "<p>x</p>", "x", {"From": "0FFDAYS <a@b.co>"},
                                          attachments=[("guide.pdf", "application/pdf", b"%PDF-1.4 test")])
        assert res.ok
        parsed = message_from_bytes(captured["m"].as_bytes())
        parts = [p for p in parsed.walk() if p.get_content_type() == "application/pdf"]
        assert len(parts) == 1 and parts[0].get_filename() == "guide.pdf" and parts[0].get_payload(decode=True) == b"%PDF-1.4 test"
        assert any(p.get_content_type() == "text/html" for p in parsed.walk())

    def test_no_attachment_is_still_a_plain_two_part_message(self, monkeypatch):
        captured = {}

        class FakeSMTP:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def starttls(self): pass
            def login(self, *a): pass
            def send_message(self, message): captured["m"] = message

        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        monkeypatch.setattr(mailer, "CONFIG", replace(CONFIG, smtp_host="smtp.test", smtp_user=""))
        mailer.SmtpTransport().send("a@example.com", "Hi", "<p>x</p>", "x", {})
        parsed = message_from_bytes(captured["m"].as_bytes())
        assert not [p for p in parsed.walk() if p.get_content_type() == "application/pdf"]


class TestTheResearchSection:
    @staticmethod
    def html():
        return (parent_guide.ASSETS / "guide.html").read_text(encoding="utf-8")

    def test_every_citation_has_a_source_and_every_source_is_cited(self):
        import re
        html = self.html()
        cited = {int(n) for grp in re.findall(r'<span class="cite">\[(.*?)\]</span>', html) for n in re.findall(r'href="#src-(\d+)"', grp)}
        listed = {int(n) for n in re.findall(r'<li id="src-(\d+)">', html)}
        assert cited and cited == listed, (cited ^ listed)

    def test_every_source_has_a_doi_link(self):
        import re
        html = self.html()
        items = re.findall(r'<li id="src-\d+">.*?</li>', html, re.S)
        assert len(items) >= 10
        for item in items:
            assert re.search(r'href="https://doi\.org/10\.\d{4,9}/\S+"', item), item[:80]

    def test_it_says_the_studies_are_not_about_this_app_and_what_they_cannot_show(self):
        html = self.html()
        assert "not about this app" in html and "no study says an app guarantees results" in html
        assert html.count("The honest part") >= 2

    def test_no_dashes_and_no_money_in_the_guide(self):
        import re
        html = self.html()
        text = re.sub(r"<style>.*?</style>", "", html, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        assert "\u2014" not in text and "\u2013" not in text and " - " not in text
        assert not re.search(r"\$\d|\bdues\b|\bprice\b", text, re.I)

    def test_the_shipped_pdfs_were_built_from_this_wording(self):
        from pypdf import PdfReader
        for name in ("guide_plain.pdf", "guide_logo.pdf"):
            text = PdfReader(str(parent_guide.ASSETS / name)).pages[0].extract_text()
            low = " ".join(text.lower().split()); assert "what the research" in low and "sports specialization and intensive training" in low, name
