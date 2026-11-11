"""Terms at sign-up, and the wall of programs on the 0FFDAYS website.

Rules held in place here:
* a program cannot be created unless the director accepts the terms, and the
  acceptance (when, which version) is recorded;
* accepting also gives permission to show the program's name and badge on the
  0FFDAYS website, and the director can take that permission back;
* nothing reaches the public list until 0FFDAYS has looked at that image and
  approved it, so a stranger cannot put any picture they like on the site;
* a new upload goes back to "waiting", and removing the badge takes the
  program off the list at once;
* the public list carries a name, a sport and an image address, nothing else:
  no ids, no counts, no people;
* only the operator can approve or hide.
"""
from __future__ import annotations

import dataclasses
import hashlib

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import store as store_mod
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
KEY = "k" * 32
OP = {"Authorization": f"Bearer {KEY}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    d = tmp_path / "uploads"
    patched = dataclasses.replace(CONFIG, uploads_dir=d)
    monkeypatch.setattr(api_module, "CONFIG", patched)
    monkeypatch.setattr(store_mod, "CONFIG", patched)
    monkeypatch.setenv("OFFDAYS_ADMIN_KEY_SHA256", hashlib.sha256(KEY.encode()).hexdigest())
    api_module._store = Store(connect(tmp_path / "terms.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def make(client, name="Mad Dog Lacrosse", **extra):
    body = {"name": name, "director_name": "Joel", "accept_terms": True, **extra}
    r = client.post("/api/orgs", json=body)
    assert r.status_code == 201, r.text
    return {"org_id": r.json()["org_id"], "h": {"Authorization": f"Bearer {r.json()['director']['token']}"}}


def upload(client, org, data=PNG):
    return client.post("/api/org/logo", headers=org["h"], files={"file": ("b.png", data, "image/png")})


def public(client):
    r = client.get("/api/programs/showcase")
    assert r.status_code == 200, r.text
    return r.json()["programs"]


class TestTermsAtSignup:

    @pytest.mark.parametrize("body", [
        {"name": "A", "director_name": "J"},
        {"name": "A", "director_name": "J", "accept_terms": False},
    ])
    def test_no_acceptance_no_program(self, client, body):
        r = client.post("/api/orgs", json=body)
        assert r.status_code == 400
        assert "terms" in r.json()["detail"].lower()
        assert client.app and api_module._store.conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0] == 0

    def test_acceptance_is_recorded_with_the_version(self, client):
        org = make(client)
        row = api_module._store.conn.execute(
            "SELECT terms_accepted_at, terms_version, showcase_ok FROM organizations WHERE id = ?",
            (org["org_id"],)).fetchone()
        assert row["terms_accepted_at"] and row["terms_version"]
        assert row["showcase_ok"] == 1

    def test_the_terms_page_is_served_and_says_what_is_being_agreed(self, client):
        r = client.get("/app/terms.html")
        assert r.status_code == 200
        text = r.text.lower()
        assert "logo" in text and "website" in text and "withdraw" in text or "remove" in text


class TestWhatTheDirectorSees:

    def test_the_status_starts_as_nothing_uploaded(self, client):
        org = make(client)
        s = client.get("/api/org/showcase", headers=org["h"]).json()
        assert s == {"allowed": True, "status": "no_logo"}

    def test_an_upload_is_waiting_not_public(self, client):
        org = make(client)
        assert upload(client, org).status_code == 201
        assert client.get("/api/org/showcase", headers=org["h"]).json()["status"] == "waiting"
        assert public(client) == []

    def test_a_coach_cannot_read_or_change_it(self, client):
        org = make(client)
        coach = api_module._store.create_user(org["org_id"], "coach", "Sam")
        h = {"Authorization": f"Bearer {coach['token']}"}
        assert client.get("/api/org/showcase", headers=h).status_code == 403
        assert client.post("/api/org/showcase", headers=h, json={"allowed": False}).status_code == 403

    def test_the_director_can_withdraw_and_allow_again(self, client):
        org = make(client)
        upload(client, org)
        client.post("/api/admin/showcase/%d/approve" % org["org_id"], headers=OP)
        assert [p["name"] for p in public(client)] == ["Mad Dog Lacrosse"]
        r = client.post("/api/org/showcase", headers=org["h"], json={"allowed": False})
        assert r.status_code == 200 and r.json()["status"] == "withdrawn"
        assert public(client) == []
        # Allowing again does not skip the review of a logo that was already approved:
        # the approval still stands, because the image has not changed.
        client.post("/api/org/showcase", headers=org["h"], json={"allowed": True})
        assert [p["name"] for p in public(client)] == ["Mad Dog Lacrosse"]


class TestThePublicWall:

    def test_approved_programs_appear_with_name_sport_and_image_only(self, client):
        org = make(client, sport="lacrosse")
        upload(client, org)
        assert client.post("/api/admin/showcase/%d/approve" % org["org_id"], headers=OP).status_code == 200
        items = public(client)
        assert len(items) == 1
        assert set(items[0]) == {"name", "sport", "logo"}
        assert items[0]["name"] == "Mad Dog Lacrosse"
        assert items[0]["sport"] == "Lacrosse"
        assert items[0]["logo"].startswith("/uploads/org-")

    def test_it_needs_no_sign_in_and_may_be_read_by_the_website(self, client):
        r = client.get("/api/programs/showcase", headers={"Origin": "https://www.0ffdays.com"})
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "*"

    def test_a_program_without_an_approval_never_appears(self, client):
        a = make(client, "Approved FC")
        b = make(client, "Pending FC")
        upload(client, a)
        upload(client, b)
        client.post("/api/admin/showcase/%d/approve" % a["org_id"], headers=OP)
        assert [p["name"] for p in public(client)] == ["Approved FC"]

    def test_a_new_upload_goes_back_to_waiting(self, client):
        org = make(client)
        upload(client, org)
        client.post("/api/admin/showcase/%d/approve" % org["org_id"], headers=OP)
        assert len(public(client)) == 1
        upload(client, org, b"\xff\xd8\xff\xe0" + b"\x00" * 64)
        assert public(client) == []
        assert client.get("/api/org/showcase", headers=org["h"]).json()["status"] == "waiting"

    def test_removing_the_badge_takes_the_program_off(self, client):
        org = make(client)
        upload(client, org)
        client.post("/api/admin/showcase/%d/approve" % org["org_id"], headers=OP)
        client.delete("/api/org/logo", headers=org["h"])
        assert public(client) == []

    def test_a_program_that_withdrew_before_approval_cannot_be_approved_onto_the_wall(self, client):
        org = make(client)
        upload(client, org)
        client.post("/api/org/showcase", headers=org["h"], json={"allowed": False})
        client.post("/api/admin/showcase/%d/approve" % org["org_id"], headers=OP)
        assert public(client) == []

    def test_a_missing_file_is_never_listed(self, client, tmp_path):
        org = make(client)
        upload(client, org)
        client.post("/api/admin/showcase/%d/approve" % org["org_id"], headers=OP)
        for f in (tmp_path / "uploads").iterdir():
            f.unlink()
        assert public(client) == []

    def test_the_test_programs_are_never_listed(self, client):
        org = make(client, "UI health check")
        upload(client, org)
        client.post("/api/admin/showcase/%d/approve" % org["org_id"], headers=OP)
        assert public(client) == []


class TestTheOperator:

    def test_only_the_operator_may_review(self, client):
        org = make(client)
        upload(client, org)
        for path in ("/api/admin/showcase", f"/api/admin/showcase/{org['org_id']}/approve",
                     f"/api/admin/showcase/{org['org_id']}/hide"):
            call = client.get if path.endswith("showcase") else client.post
            assert call(path).status_code == 401
            assert call(path, headers=org["h"]).status_code == 401

    def test_the_review_list_shows_waiting_and_live_with_their_images(self, client):
        a = make(client, "Waiting FC")
        b = make(client, "Live FC")
        upload(client, a)
        upload(client, b)
        client.post("/api/admin/showcase/%d/approve" % b["org_id"], headers=OP)
        data = client.get("/api/admin/showcase", headers=OP).json()
        assert [p["name"] for p in data["waiting"]] == ["Waiting FC"]
        assert [p["name"] for p in data["live"]] == ["Live FC"]
        assert data["waiting"][0]["logo"].startswith("/uploads/org-")
        assert data["waiting"][0]["org_id"] == a["org_id"]

    def test_hide_takes_it_down_and_it_stays_down_until_a_new_image(self, client):
        org = make(client)
        upload(client, org)
        client.post("/api/admin/showcase/%d/approve" % org["org_id"], headers=OP)
        assert client.post("/api/admin/showcase/%d/hide" % org["org_id"], headers=OP).status_code == 200
        assert public(client) == []
        assert client.get("/api/admin/showcase", headers=OP).json()["waiting"] == []

    def test_an_unknown_program_is_a_404(self, client):
        assert client.post("/api/admin/showcase/999/approve", headers=OP).status_code == 404


class TestApprovalBelongsToTheImage:
    """The approval is for one image, not for a file name. org-<id>.png is the same name every time."""

    def test_the_same_file_name_uploaded_again_is_looked_at_again(self, client):
        org = make(client)
        upload(client, org)
        client.post("/api/admin/showcase/%d/approve" % org["org_id"], headers=OP)
        assert len(public(client)) == 1
        upload(client, org, PNG + b"\x01")  # a different picture, saved under the very same name
        assert public(client) == []
        assert client.get("/api/org/showcase", headers=org["h"]).json()["status"] == "waiting"

    def test_removing_and_re_adding_the_badge_is_looked_at_again(self, client):
        org = make(client)
        upload(client, org)
        client.post("/api/admin/showcase/%d/approve" % org["org_id"], headers=OP)
        client.delete("/api/org/logo", headers=org["h"])
        upload(client, org)
        assert public(client) == []
        assert client.get("/api/org/showcase", headers=org["h"]).json()["status"] == "waiting"

    def test_an_approval_pressed_while_withdrawn_is_not_stored_for_later(self, client):
        org = make(client)
        upload(client, org)
        client.post("/api/org/showcase", headers=org["h"], json={"allowed": False})
        client.post("/api/admin/showcase/%d/approve" % org["org_id"], headers=OP)
        client.post("/api/org/showcase", headers=org["h"], json={"allowed": True})
        assert public(client) == []
        assert client.get("/api/org/showcase", headers=org["h"]).json()["status"] == "waiting"
