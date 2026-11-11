"""The director uploads the program's badge, and every screen wears it.

White-labelling in one move: the director picks a file on the dashboard,
and the header of the coach, athlete, parent and leaderboard pages shows
their club's mark instead of their club's name. The file is stored beside
the database so it survives deploys, named by program so a second upload
replaces the first, typed from its bytes, and -- for SVG -- stripped of
anything that could run in a parent's browser.
"""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import badge, store as store_mod
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle r="4"/></svg>'
EVIL_SVG = (
    b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">'
    b'<script>alert(2)</script><a href="javascript:alert(3)"><circle r="4" onclick="x()"/></a>'
    b'<foreignObject><body xmlns="http://www.w3.org/1999/xhtml"><script>4</script></body></foreignObject></svg>'
)


@pytest.fixture
def uploads(tmp_path, monkeypatch):
    d = tmp_path / "uploads"
    patched = dataclasses.replace(CONFIG, uploads_dir=d)
    monkeypatch.setattr(api_module, "CONFIG", patched)
    monkeypatch.setattr(store_mod, "CONFIG", patched)
    return d


@pytest.fixture
def client(tmp_path, uploads):
    api_module._store = Store(connect(tmp_path / "badge.db"))
    yield TestClient(api_module.app)
    api_module._store = None


@pytest.fixture
def org(client):
    made = client.post("/api/orgs", json={"name": "Mad Dog Lacrosse", "accept_terms": True, "director_name": "Joel"}).json()
    director = {"Authorization": f"Bearer {made['director']['token']}"}
    coach = api_module._store.create_user(made["org_id"], "coach", "Sam")
    return {"org_id": made["org_id"], "director": director,
            "coach": {"Authorization": f"Bearer {coach['token']}"}}


def upload(client, headers, data, name="badge.png", mime="image/png"):
    return client.post("/api/org/logo", headers=headers, files={"file": (name, data, mime)})


class TestUpload:

    def test_a_png_becomes_the_header_badge_for_everyone_in_the_program(self, client, org, uploads):
        r = upload(client, org["director"], PNG)
        assert r.status_code == 201, r.text
        assert r.json() == {"name": "Mad Dog Lacrosse", "logo": f"/uploads/org-{org['org_id']}.png"}
        assert (uploads / f"org-{org['org_id']}.png").read_bytes() == PNG
        # A coach's header reads the same thing; it is the program's, not the uploader's.
        assert client.get("/api/branding", headers=org["coach"]).json()["logo"].endswith(".png")
        # And the file is served.
        assert client.get(f"/uploads/org-{org['org_id']}.png").status_code == 200

    def test_type_comes_from_the_bytes_not_the_name(self, client, org):
        r = upload(client, org["director"], JPG, name="pretend.png", mime="image/png")
        assert r.status_code == 201 and r.json()["logo"].endswith(".jpg")
        r = upload(client, org["director"], WEBP, name="x.bin", mime="application/octet-stream")
        assert r.status_code == 201 and r.json()["logo"].endswith(".webp")

    def test_a_second_upload_replaces_the_first_and_leaves_one_file(self, client, org, uploads):
        upload(client, org["director"], PNG)
        upload(client, org["director"], JPG, name="b.jpg", mime="image/jpeg")
        assert sorted(p.name for p in uploads.iterdir()) == [f"org-{org['org_id']}.jpg"]

    def test_not_an_image_is_refused(self, client, org):
        r = upload(client, org["director"], b"%PDF-1.4 not a badge", name="a.png")
        assert r.status_code == 415

    def test_too_big_is_refused(self, client, org):
        r = upload(client, org["director"], PNG + b"\x00" * badge.MAX_BYTES)
        assert r.status_code == 413

    def test_only_a_director_may_set_it(self, client, org):
        assert upload(client, org["coach"], PNG).status_code == 403
        assert client.delete("/api/org/logo", headers=org["coach"]).status_code == 403

    def test_remove_puts_the_name_back(self, client, org, uploads):
        upload(client, org["director"], PNG)
        r = client.delete("/api/org/logo", headers=org["director"])
        assert r.status_code == 200 and r.json()["logo"] == ""
        assert list(uploads.iterdir()) == []


class TestSvg:

    def test_a_clean_svg_is_kept_as_svg(self, client, org, uploads):
        r = upload(client, org["director"], SVG, name="crest.svg", mime="image/svg+xml")
        assert r.status_code == 201 and r.json()["logo"].endswith(".svg")
        assert b"<circle" in (uploads / f"org-{org['org_id']}.svg").read_bytes()

    def test_scripts_and_handlers_are_stripped(self, client, org, uploads):
        r = upload(client, org["director"], EVIL_SVG, name="crest.svg", mime="image/svg+xml")
        assert r.status_code == 201
        stored = (uploads / f"org-{org['org_id']}.svg").read_bytes().lower()
        assert b"<script" not in stored
        assert b"onload" not in stored and b"onclick" not in stored
        assert b"javascript:" not in stored
        assert b"foreignobject" not in stored
        assert b"<circle" in stored  # the drawing survives


class TestBranding:

    def test_a_repo_badge_still_works_alongside_uploads(self, client, org):
        # The shipped Nashville Dogs crest, set the operator's way.
        api_module._store.set_org_logo(org["org_id"], "nashville-dogs.png")
        assert client.get("/api/branding", headers=org["director"]).json()["logo"] == "teams/nashville-dogs.png"

    def test_a_badge_whose_file_went_missing_falls_back_to_the_name(self, client, org, uploads):
        upload(client, org["director"], PNG)
        (uploads / f"org-{org['org_id']}.png").unlink()
        b = client.get("/api/branding", headers=org["director"]).json()
        assert b == {"name": "Mad Dog Lacrosse", "logo": ""}
