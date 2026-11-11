"""Resend or send the parent invite to many families at once.

One tap for "everyone stuck waiting on an invite" instead of forty. It must be exactly the single "Resend invite to parent"
done N times: the same refusals (a parent already signed up, no address on file, someone else's athlete or team), the
same one-live-invite-per-athlete rule, and the same email hold. A bad id in the list must skip that family, never fail
the others and never reach someone else's program.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import contacts as C
from offdays import guardians as G
from offdays import invites, mailer
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store

URL = "/api/coach/families/nudge-many"


@pytest.fixture
def smtp_on(monkeypatch):
    from dataclasses import replace
    patched = replace(CONFIG, smtp_host="smtp.test", app_base_url="https://app.0ffdays.com")
    monkeypatch.setattr(invites, "CONFIG", patched)
    monkeypatch.setattr(mailer, "CONFIG", patched)
    monkeypatch.setattr(mailer, "mail_held", lambda conn, org_id: False)


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


@pytest.fixture
def program(client):
    store = api_module._store
    made = client.post("/api/orgs", json={"name": "Mad Dog", "accept_terms": True, "director_name": "Dir K"}).json()
    org = made["org_id"]
    director = {"Authorization": f"Bearer {made['director']['token']}"}
    red = store.create_team(org, "2031 Red", "2026")
    blue = store.create_team(org, "2031 Blue", "2026")
    kids = []
    for i, (name, team) in enumerate([("Ana A", red), ("Ben B", red), ("Cy C", red), ("Di D", blue), ("Ed E", blue)]):
        kid = store.create_user(org, "athlete", name, birth_year=2013, dominant_hand="right")
        store.join_team(team["join_code"], kid["id"])
        C.upsert(store.conn, org_id=org, athlete_id=kid["id"], name=f"Parent of {name}", email=f"p{i}@example.com")
        kids.append(kid)
    coach = store.create_user(org, "coach", "Coach R")
    store.assign_staff_to_team(coach["id"], red["id"])
    return {"org": org, "h": director, "coach": {"Authorization": f"Bearer {coach['token']}"},
            "kids": kids, "red": red, "blue": blue, "store": store}


def ids(program, *idx):
    return [program["kids"][i]["id"] for i in idx]


def live_invites(store, athlete_id):
    return store.conn.execute(
        "SELECT COUNT(*) FROM guardian_invites WHERE athlete_id = ? AND redeemed_at IS NULL AND revoked_at IS NULL",
        (athlete_id,)).fetchone()[0]


def outbox(store):
    return store.conn.execute("SELECT to_email FROM email_outbox ORDER BY id").fetchall()


class TestOneTapForMany:

    def test_everyone_in_the_list_gets_a_fresh_invite(self, client, program, smtp_on):
        r = client.post(URL, headers=program["h"], json={"athlete_ids": ids(program, 0, 1, 2, 3, 4)})
        assert r.status_code == 201, r.text
        body = r.json()
        assert [x["status"] for x in body["results"]] == ["ready"] * 5 or all(x["status"] in ("sent", "ready") for x in body["results"])
        assert body["counts"]["invited"] == 5 and body["counts"]["skipped"] == 0
        for k in program["kids"]:
            assert live_invites(program["store"], k["id"]) == 1

    def test_with_email_on_every_parent_is_emailed_once(self, client, program, smtp_on):
        r = client.post(URL, headers=program["h"], json={"athlete_ids": ids(program, 0, 1, 2)}).json()
        assert r["counts"]["emailed"] == 3 and r["emailed"] == 3
        assert sorted(x["to_email"] for x in outbox(program["store"])) == ["p0@example.com", "p1@example.com", "p2@example.com"]
        assert all(x["status"] == "sent" for x in r["results"])

    def test_doing_it_twice_leaves_one_live_invite_each(self, client, program, smtp_on):
        for _ in range(2):
            assert client.post(URL, headers=program["h"], json={"athlete_ids": ids(program, 0, 1)}).status_code == 201
        assert live_invites(program["store"], program["kids"][0]["id"]) == 1
        assert live_invites(program["store"], program["kids"][1]["id"]) == 1

    def test_each_result_names_the_athlete_and_carries_what_a_director_needs_to_send_it_himself(self, client, program):
        r = client.post(URL, headers=program["h"], json={"athlete_ids": ids(program, 0)}).json()["results"][0]
        for key in ("athlete_id", "display_name", "email", "subject", "text", "link", "code", "status"):
            assert key in r, key
        assert r["display_name"] == "Ana A" and r["email"] == "p0@example.com"
        assert r["link"].endswith(f"?invite={r['code']}")


class TestTheEmailHoldStillHolds:

    def test_held_means_nobody_is_emailed_and_each_family_is_ready_to_send_by_hand(self, client, program):
        # no smtp_on: the program is held, the default
        r = client.post(URL, headers=program["h"], json={"athlete_ids": ids(program, 0, 1, 2)}).json()
        assert outbox(program["store"]) == []
        assert r["emailed"] == 0 and r["counts"]["invited"] == 3 and r["counts"]["emailed"] == 0
        assert [x["status"] for x in r["results"]] == ["ready"] * 3
        assert r["smtp_configured"] is False

    def test_released_then_held_again(self, client, program, smtp_on, monkeypatch):
        monkeypatch.setattr(mailer, "mail_held", lambda conn, org_id: True)
        r = client.post(URL, headers=program["h"], json={"athlete_ids": ids(program, 0)}).json()
        assert r["emailed"] == 0 and outbox(program["store"]) == []


class TestEachFamilyIsJudgedOnItsOwn:

    def test_a_parent_who_already_signed_up_is_skipped_and_the_rest_go(self, client, program, smtp_on):
        store = program["store"]
        inv = G.create_invite(store.conn, program["kids"][1]["id"], 1, "p1@example.com")
        G.redeem_invite(store.conn, inv["code"], "Pat B", email="p1@example.com")
        r = client.post(URL, headers=program["h"], json={"athlete_ids": ids(program, 0, 1, 2)}).json()
        by = {x["athlete_id"]: x for x in r["results"]}
        assert by[program["kids"][1]["id"]]["status"] == "skipped"
        assert "already signed up" in by[program["kids"][1]["id"]]["reason"]
        assert by[program["kids"][0]["id"]]["status"] == "sent" and by[program["kids"][2]["id"]]["status"] == "sent"
        assert r["counts"] == {**r["counts"], "invited": 2, "skipped": 1}

    def test_no_address_on_file_is_skipped_with_the_reason(self, client, program, smtp_on):
        store = program["store"]
        store.conn.execute("DELETE FROM guardian_contacts WHERE athlete_id = ?", (program["kids"][0]["id"],))
        store.conn.commit()
        r = client.post(URL, headers=program["h"], json={"athlete_ids": ids(program, 0, 1)}).json()
        first = r["results"][0]
        assert first["status"] == "skipped" and "no parent email" in first["reason"]
        assert live_invites(store, program["kids"][0]["id"]) == 0
        assert live_invites(store, program["kids"][1]["id"]) == 1

    def test_an_unknown_id_skips_that_one_only(self, client, program, smtp_on):
        r = client.post(URL, headers=program["h"], json={"athlete_ids": [987654] + ids(program, 0)}).json()
        assert [x["status"] for x in r["results"]] == ["skipped", "sent"]
        assert "unknown" in r["results"][0]["reason"]

    def test_the_same_id_twice_is_one_invite(self, client, program, smtp_on):
        r = client.post(URL, headers=program["h"], json={"athlete_ids": ids(program, 0, 0, 0)}).json()
        assert len(r["results"]) == 1 and r["emailed"] == 1
        assert len(outbox(program["store"])) == 1


class TestOnlyYourOwn:

    def test_a_coach_can_do_their_own_team_and_is_refused_the_other(self, client, program, smtp_on):
        r = client.post(URL, headers=program["coach"], json={"athlete_ids": ids(program, 0, 3)}).json()
        by = {x["athlete_id"]: x for x in r["results"]}
        assert by[program["kids"][0]["id"]]["status"] == "sent"
        assert by[program["kids"][3]["id"]]["status"] == "skipped"
        assert "not assigned" in by[program["kids"][3]["id"]]["reason"]
        assert live_invites(program["store"], program["kids"][3]["id"]) == 0
        assert [x["to_email"] for x in outbox(program["store"])] == ["p0@example.com"]

    def test_another_programs_athlete_is_never_touched(self, client, program, smtp_on):
        other = client.post("/api/orgs", json={"name": "Rivals", "accept_terms": True, "director_name": "Rival Dir"}).json()
        theirs = api_module._store.create_user(other["org_id"], "athlete", "Zed Z", birth_year=2013)
        C.upsert(api_module._store.conn, org_id=other["org_id"], athlete_id=theirs["id"], email="zed@example.com")
        r = client.post(URL, headers=program["h"], json={"athlete_ids": [theirs["id"]] + ids(program, 0)}).json()
        assert r["results"][0]["status"] == "skipped" and "another program" in r["results"][0]["reason"]
        assert live_invites(program["store"], theirs["id"]) == 0
        assert "zed@example.com" not in [x["to_email"] for x in outbox(program["store"])]

    def test_a_parent_or_athlete_cannot_use_it(self, client, program):
        kid_headers = {"Authorization": f"Bearer {program['kids'][0]['token']}"}
        assert client.post(URL, headers=kid_headers, json={"athlete_ids": ids(program, 0)}).status_code in (401, 403)
        assert client.post(URL, json={"athlete_ids": ids(program, 0)}).status_code in (401, 403)


class TestThePageIsWiredToIt:

    def test_the_families_card_offers_it_and_sends_through_the_one_route(self):
        from pathlib import Path
        html = (Path(__file__).resolve().parents[1] / "offdays" / "web" / "static" / "coach.html").read_text(encoding="utf-8")
        for needle in ("id=\"fam-all\"", "id=\"fam-bulk-send\"", "/api/coach/families/nudge-many", "data-fam-pick",
                       "famPicked.clear()", "Copy all"):
            assert needle in html, needle

    def test_a_pick_you_can_no_longer_see_is_dropped_before_sending(self):
        from pathlib import Path
        html = (Path(__file__).resolve().parents[1] / "offdays" / "web" / "static" / "coach.html").read_text(encoding="utf-8")
        assert "if (!shownIds.has(id)) famPicked.delete(id)" in html


class TestTheListItself:

    def test_an_empty_list_is_refused(self, client, program):
        assert client.post(URL, headers=program["h"], json={"athlete_ids": []}).status_code == 422

    def test_a_huge_list_is_refused_rather_than_run(self, client, program):
        assert client.post(URL, headers=program["h"], json={"athlete_ids": list(range(1, 402))}).status_code == 422

    def test_non_numbers_are_refused(self, client, program):
        assert client.post(URL, headers=program["h"], json={"athlete_ids": ["a", None]}).status_code == 422

    def test_the_funnel_says_who_can_be_sent_to(self, client, program):
        board = client.get("/api/coach/families", headers=program["h"]).json()
        assert sum(1 for a in board["athletes"] if a["can_nudge"]) == 5


class TestItIsTheSingleResendRepeated:

    def test_same_invite_text_as_the_single_button(self, client, program):
        one = client.post("/api/coach/families/nudge", headers=program["h"], json={"athlete_id": program["kids"][0]["id"]}).json()
        many = client.post(URL, headers=program["h"], json={"athlete_ids": ids(program, 0)}).json()["results"][0]
        assert one["subject"] == many["subject"]
        assert one["text"].replace(one["code"], "X") == many["text"].replace(many["code"], "X")
        assert one["email"] == many["email"]
