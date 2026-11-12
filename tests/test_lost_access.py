"""An athlete has lost access: the parent can send a new sign-in link, and the athlete is told to ask for one.

The server side already existed (`POST /api/guardians/athlete-link/{id}`: guardian only, refused until the parent has said
yes, each call replaces the last link). These tests pin it through the API as a parent would use it, and pin the page:
the button is the first thing under the athlete's name, says what it is for, and a child who taps a dead link is told what
to do instead of being asked for a code they do not have.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays.db import connect
from offdays.store import Store

STATIC = Path(__file__).resolve().parents[1] / "offdays" / "web" / "static"
PARENT = (STATIC / "parent.html").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
API_JS = (STATIC / "api.js").read_text(encoding="utf-8")


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def family(client, name="Sam Lost", email="sam.mom@example.com", org="Lost Club", say_yes=True):
    made = client.post("/api/orgs", json={"name": org, "sport": "lacrosse", "accept_terms": True,
                                          "director_name": "Joel"}).json()
    d = bearer(made["director"]["token"])
    t = client.post("/api/teams", json={"name": "U12"}, headers=d).json()["id"]
    first, last = name.split()
    client.post("/api/coach/roster/import", headers=d, json={
        "content": f"First Name,Last Name,Birth Year,Parent Email\n{first},{last},2014,{email}\n", "team_id": t})
    kid = client.get("/api/coach/team-ranking", headers=d, params={"team_id": t}).json()["rows"][0]["athlete_id"]
    inv = client.post("/api/coach/guardian-invites", headers=d, json={"athlete_id": kid, "email": email}).json()
    parent = client.post("/api/guardians/redeem", json={"code": inv["code"], "display_name": "Pat Lost", "email": email,
                                                         "phone": "615-555-0101"}).json()
    p = bearer(parent.get("token") or parent.get("code"))
    if say_yes:
        assert client.post("/api/guardians/consent", headers=p,
                           json={"athlete_id": kid, "scope": "participation", "granted": True}).status_code in (200, 201)
    return {"d": d, "p": p, "kid": kid}


def new_link(client, f):
    r = client.post(f"/api/guardians/athlete-link/{f['kid']}", headers=f["p"])
    assert r.status_code == 201, r.text
    return r.json()


class TestAParentCanSendANewLink:

    def test_one_request_gives_a_link_the_athlete_can_sign_in_with(self, client):
        f = family(client)
        out = new_link(client, f)
        assert out["link"].endswith(f"/app/index.html?code={out['code']}")
        me = client.get("/api/me", headers=bearer(out["code"]))
        assert me.status_code == 200 and me.json()["role"] == "athlete"

    def test_asking_again_replaces_the_lost_link_everywhere(self, client):
        f = family(client)
        lost = new_link(client, f)
        fresh = new_link(client, f)
        assert fresh["code"] != lost["code"]
        assert client.get("/api/me", headers=bearer(lost["code"])).status_code == 401, "the lost link is dead"
        assert client.get("/api/me", headers=bearer(fresh["code"])).status_code == 200

    def test_it_can_be_done_as_often_as_needed(self, client):
        f = family(client)
        for _ in range(4):
            out = new_link(client, f)
            assert client.get("/api/me", headers=bearer(out["code"])).status_code == 200

    def test_the_athlete_keeps_their_training_history_when_the_link_changes(self, client):
        f = family(client)
        first = new_link(client, f)
        before = client.get("/api/me", headers=bearer(first["code"])).json()["athlete_id"]
        after = client.get("/api/me", headers=bearer(new_link(client, f)["code"])).json()["athlete_id"]
        assert before == after == f["kid"], "the same athlete, not a new account"

    def test_it_is_refused_until_the_parent_has_said_yes(self, client):
        f = family(client, say_yes=False)
        r = client.post(f"/api/guardians/athlete-link/{f['kid']}", headers=f["p"])
        assert r.status_code in (400, 403, 409) and "yes" in r.text.lower()

    def test_a_parent_cannot_send_a_link_for_someone_elses_child(self, client):
        a = family(client, name="Sam Lost", org="Club A")
        b = family(client, name="Kai Other", email="kai.dad@example.com", org="Club B")
        r = client.post(f"/api/guardians/athlete-link/{b['kid']}", headers=a["p"])
        assert r.status_code in (400, 403, 404)
        assert client.get("/api/me", headers=bearer(new_link(client, b)["code"])).status_code == 200

    def test_an_athlete_a_coach_or_nobody_cannot_do_it(self, client):
        f = family(client)
        link = new_link(client, f)
        for h in (bearer(link["code"]), f["d"], {}):
            assert client.post(f"/api/guardians/athlete-link/{f['kid']}", headers=h).status_code in (401, 403)

    def test_the_old_link_dies_even_if_the_athlete_is_signed_in_on_another_phone(self, client):
        f = family(client)
        old = new_link(client, f)
        assert client.get("/api/me", headers=bearer(old["code"])).status_code == 200
        new_link(client, f)
        assert client.get("/api/me", headers=bearer(old["code"])).status_code == 401

    def test_it_works_the_same_for_every_sport(self, client):
        for sport in ("lacrosse", "basketball", "soccer", "volleyball", "football"):
            made = client.post("/api/orgs", json={"name": f"{sport} club", "sport": sport, "accept_terms": True,
                                                   "director_name": "Joel"}).json()
            d = bearer(made["director"]["token"])
            t = client.post("/api/teams", json={"name": "U12"}, headers=d).json()["id"]
            client.post("/api/coach/roster/import", headers=d, json={
                "content": "First Name,Last Name,Birth Year,Parent Email\nAva,Moss,2014,ava.mom@example.com\n", "team_id": t})
            kid = client.get("/api/coach/team-ranking", headers=d, params={"team_id": t}).json()["rows"][0]["athlete_id"]
            inv = client.post("/api/coach/guardian-invites", headers=d, json={"athlete_id": kid, "email": "ava.mom@example.com"}).json()
            p = client.post("/api/guardians/redeem", json={"code": inv["code"], "display_name": "Pat Moss", "email": "ava.mom@example.com", "phone": "615-555-0102"}).json()
            ph = bearer(p.get("token") or p.get("code"))
            client.post("/api/guardians/consent", headers=ph, json={"athlete_id": kid, "scope": "participation", "granted": True})
            r = client.post(f"/api/guardians/athlete-link/{kid}", headers=ph)
            assert r.status_code == 201, sport
            assert client.get("/api/me", headers=bearer(r.json()["code"])).status_code == 200, sport


class TestTheParentPage:

    def test_the_button_is_the_first_thing_under_the_athletes_name(self):
        card = PARENT.split("function renderAthlete(a)", 1)[1]
        assert card.index("data-signin=") < card.index('class="stat-row"'), "above the weekly numbers, not buried below them"
        assert card.index("data-signin=") < card.index("From their coach")

    def test_it_says_what_it_is_for(self):
        assert "a new sign-in link" in PARENT
        assert "Lost the link, a new phone, or signed out?" in PARENT
        assert "The old link stops working everywhere." in PARENT

    def test_there_is_only_one_such_button_per_athlete(self):
        card = PARENT.split("function renderAthlete(a)", 1)[1].split("function ", 1)[0]
        assert card.count("data-signin=") == 1

    def test_the_button_calls_the_one_server_route(self):
        assert re.search(r"api\(`/api/guardians/athlete-link/\$\{btn\.dataset\.signin\}`, \{\s*method: 'POST'", PARENT)

    def test_the_link_can_be_copied_shared_texted_or_emailed(self):
        fn = PARENT.split("function renderSigninLink", 1)[1].split("function renderAthlete", 1)[0]
        for way in ("data-copy", "data-share", "sms:", "mailto:"):
            assert way in fn, way

    def test_a_refusal_is_shown_in_words_not_swallowed(self):
        block = PARENT.split("document.querySelectorAll('[data-signin]')", 1)[1].split("document.querySelectorAll('[data-export]')", 1)[0]
        assert "showError(e.message)" in block and "btn.disabled = false" in block, "the button comes back so they can try again"


class TestWhatTheAthleteSees:

    def test_a_dead_link_tells_the_child_to_ask_a_parent(self):
        assert "Ask your parent to send you a new one." in INDEX

    def test_that_message_is_only_for_someone_who_tapped_a_link(self):
        assert "window.__linkTapped" in INDEX
        block = INDEX.split("async function signIn", 1)[1].split("}\n}", 1)[0]
        assert "__linkTapped" in block, "typing a wrong code still gets the ordinary message"

    def test_a_coach_or_parent_is_no_longer_told_to_enter_an_athlete_code(self):
        assert "Enter your athlete code again" not in API_JS
        assert "Your sign-in ended" in API_JS

    def test_the_sign_in_page_already_says_lost_the_link_ask_them_to_send_it_again(self):
        assert "Lost the link? Ask" in INDEX or "Lost the link?" in INDEX


class TestTheLinkIsSomethingYouCanActuallySend:

    def test_the_link_is_always_a_whole_address(self):
        """A bare path texted to a child opens nothing. It does not matter what the server's own address setting is."""
        fn = PARENT.split("function renderSigninLink", 1)[1].split("function renderAthlete", 1)[0]
        assert "location.origin" in fn and "https?:" in fn

    def test_text_and_email_look_like_buttons_not_loose_words(self):
        fn = PARENT.split("function renderSigninLink", 1)[1].split("function renderAthlete", 1)[0]
        assert fn.count('class="btn-link"') == 2

    def test_the_note_names_the_box_the_sign_in_page_really_has(self):
        fn = PARENT.split("function renderSigninLink", 1)[1].split("function renderAthlete", 1)[0]
        assert "The code from your link" in fn and "The code from your link" in INDEX
        assert "Your athlete code" not in fn
