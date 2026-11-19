"""The fields in a milestone message are fixed: a coach chooses where {first_name} goes, never what it is called."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pathlib import Path

import offdays.api as api_module
from offdays import recognition
from offdays.db import connect
from offdays.store import Store

STATIC = Path(api_module.__file__).parent / "web" / "static"


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def club(client):
    made = client.post("/api/orgs", json={"name": "Nashville Dogs", "sport": "lacrosse", "accept_terms": True,
                                          "director_name": "Matt"}).json()
    return {"Authorization": f"Bearer {made['director']['token']}"}


def save(client, h, body, milestone="first_session"):
    return client.put("/api/coach/recognition", headers=h, json={"milestone": milestone, "body": body, "enabled": True})


class TestWhatCountsAsAField:
    @pytest.mark.parametrize("text", [
        "Nice one {first_name}, {streak} days!", "{coach} says well done to {team}", "No fields at all.",
        "{first_name} {first_name}", "a\n\n{streak} in a row, {first_name}",
    ])
    def test_the_four_fields_are_fine_anywhere(self, text):
        assert recognition.bad_tokens(text) == []

    @pytest.mark.parametrize("text,frag", [
        ("Hi {firstname}", "{firstname}"), ("Hi {First_Name}", "{First_Name}"), ("Hi { first_name }", "{ first_name }"),
        ("Hi {first_na", "{first_na"), ("Hi first_name}", "}"), ("Hi {{first_name}}", "{}"), ("Hi {name}", "{name}"),
        ("Hi {Streak}", "{Streak}"), ("{coach}} oops", "}"),
    ])
    def test_anything_else_that_looks_like_one_is_caught(self, text, frag):
        assert frag in recognition.bad_tokens(text)

    def test_each_offender_is_listed_once(self):
        assert recognition.bad_tokens("{x} {x} {y}") == ["{x}", "{y}"]


class TestTheServerRefusesAChangedField:
    def test_a_good_message_saves(self, client):
        h = club(client)
        res = save(client, h, "Well done {first_name}, {streak} days. {coach}")
        assert res.status_code == 200 and res.json()["body"].startswith("Well done {first_name}")

    @pytest.mark.parametrize("body", ["Hi {firstname}", "Hi {First_Name}", "Hi {first_na", "Hi {name}", "Hi {{first_name}}"])
    def test_a_field_with_a_different_name_is_refused_with_a_plain_reason(self, client, body):
        h = club(client)
        res = save(client, h, body)
        assert res.status_code == 400
        detail = res.json()["detail"]
        assert "is not a field" in detail and "first name, streak, coach, team" in detail and "buttons" in detail

    def test_a_refused_message_does_not_replace_the_one_that_was_saved(self, client):
        h = club(client)
        save(client, h, "Good one {first_name}")
        save(client, h, "Hi {firstname}")
        rows = client.get("/api/coach/recognition", headers=h).json()["milestones"]
        mine = [m for m in rows if m["key"] == "first_session"][0]
        assert "Good one {first_name}" in (mine.get("bodies") or [mine["body"]])[0]

    def test_a_bad_field_in_the_second_wording_is_caught_too(self, client):
        h = club(client)
        assert save(client, h, "Fine {first_name}\n\nNot fine {strek}").status_code == 400

    def test_turning_a_milestone_off_does_not_need_a_valid_message_but_still_checks_one_if_sent(self, client):
        h = club(client)
        res = client.put("/api/coach/recognition", headers=h, json={"milestone": "first_session", "body": "Hi {nme}", "enabled": False})
        assert res.status_code == 400

    def test_a_message_with_every_field_in_it_reads_properly_in_the_preview(self, client):
        h = club(client)
        client.post("/api/coach/roster/import", headers=h, json={"content": "First Name,Last Name,Birth Year\nDillon,Langdon,2013\n",
                                                                  "team_id": client.post("/api/teams", json={"name": "2031 Red"}, headers=h).json()["id"],
                                                                  "invite_guardians": False})
        out = client.post("/api/coach/recognition/preview", headers=h, json={"body": "{first_name}, {streak} days, {coach}, {team}"}).json()
        assert out["preview"].startswith("Dillon, 10 days,") and "{" not in out["preview"]

    def test_the_shipped_wordings_all_use_only_real_fields(self):
        for m in recognition.MILESTONES:
            for w in recognition.variants("\n\n".join(m.bodies if hasattr(m, "bodies") else [m.body])):
                assert recognition.bad_tokens(w) == [], (m.key, w)


class TestTheScreenLocksTheFields:
    HTML = (STATIC / "coach.html").read_text(encoding="utf-8")

    def test_the_words_are_written_in_a_box_that_holds_fields_as_blocks(self):
        assert 'contenteditable="true" role="textbox"' in self.HTML and "data-recog-body" in self.HTML
        assert '<textarea rows="4" data-recog-body>' not in self.HTML
        assert 'class="recog-chip" contenteditable="false"' in self.HTML

    def test_each_field_has_a_button_to_put_it_in(self):
        assert "data-recog-insert" in self.HTML
        for token in recognition.TOKENS:
            assert f"['{token}'," in self.HTML

    def test_the_text_that_is_saved_and_previewed_is_read_back_from_the_blocks(self):
        assert "body: { body: recogText(recogBox(row)) }" in self.HTML
        assert ".value }," not in self.HTML.split("recognition-list').addEventListener('click'")[1].split("loadRecognitionSent")[0]

    def test_enter_and_paste_stay_plain_and_a_hand_typed_field_becomes_a_real_one(self):
        assert "execCommand('insertLineBreak')" in self.HTML and "getData('text/plain')" in self.HTML
        assert "recogHtml(text) !== e.target.innerHTML" in self.HTML

    def test_a_refused_save_says_why_under_the_box(self):
        assert "recogSay(row, e.message || 'Could not save.', true)" in self.HTML and 'class="small recog-err"' in self.HTML

    def test_a_field_cannot_be_selected_into_pieces(self):
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        assert ".recog-chip" in css and "user-select: none" in css.split(".recog-chip")[1]

    def test_a_field_is_saved_as_its_own_name_and_the_buttons_are_drawn_for_every_row(self):
        assert "if (c.dataset && c.dataset.token) out += c.dataset.token;" in self.HTML
        assert "data-recog-insert=\"${t}\">+ ${esc(label)}</button>" in self.HTML
