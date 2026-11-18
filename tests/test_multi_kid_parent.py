"""A parent with several children on the team: one invite, one account, one portal, a link for each child.

The roster lists the same parent address for each of a family's children. The program supplied that address, so:

* one invite email covers them all (not one email and one account per child);
* the one parent account sees every child, each with its own yes to training and its own sign-in link;
* a child added later joins the parent who is already signed up, and the parent is told;
* nothing crosses to a child the roster did not give this parent: the address typed at sign-up is never used, nor an
  address in another program.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays.db import connect
from offdays.store import Store

PARENT = "robert.langdon@example.com"
OTHER_PARENT = "christina.langdon@example.com"


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def db():
    return api_module._store.conn


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def club(client, name="Nashville Dogs"):
    made = client.post("/api/orgs", json={"name": name, "sport": "lacrosse", "accept_terms": True,
                                          "director_name": "Matt"}).json()
    d = bearer(made["director"]["token"])
    team = client.post("/api/teams", json={"name": "2031 Red"}, headers=d).json()["id"]
    return {"d": d, "team": team}


def roster(client, c, rows):
    """rows: [(first, last, parent_email)] -> the import result."""
    body = "First Name,Last Name,Birth Year,Parent Email\n" + "".join(f"{f},{l},2013,{e}\n" for f, l, e in rows)
    res = client.post("/api/coach/roster/import", headers=c["d"], json={"content": body, "team_id": c["team"]})
    assert res.status_code == 201, res.text
    return res.json()


def kid_id(client, c, name):
    rows = client.get("/api/coach/team-ranking", headers=c["d"], params={"team_id": c["team"]}).json()["rows"]
    return [r["athlete_id"] for r in rows if r["display_name"] == name][0]


def redeem(client, code, email=PARENT, name="Robert Langdon"):
    res = client.post("/api/guardians/redeem", json={"code": code, "display_name": name, "email": email,
                                                     "phone": "615-555-0101"})
    assert res.status_code == 201, res.text
    return res.json()


def me(client, token):
    return client.get("/api/guardians/me", headers=bearer(token)).json()


def say_yes(client, token, kid):
    return client.post("/api/guardians/consent", headers=bearer(token),
                       json={"athlete_id": kid, "scope": "participation", "granted": True})


def two_kid_family(client):
    c = club(client)
    out = roster(client, c, [("Dillon", "Langdon", PARENT), ("Killian", "Langdon", PARENT), ("Ben", "Amden", "j@example.com")])
    return c, out


class TestOneInviteForTheWholeFamily:
    def test_two_children_with_one_parent_address_get_one_invite(self, client):
        c, out = two_kid_family(client)
        to_parent = [i for i in out["guardian_invites"] if i["email"] == PARENT]
        assert len(to_parent) == 1
        assert to_parent[0]["also_names"] == ["Killian Langdon"]
        assert len(out["guardian_invites"]) == 2                 # the Langdons, and the Amdens

    def test_the_message_names_both_children_and_says_one_account(self, client):
        c, out = two_kid_family(client)
        inv = [i for i in out["guardian_invites"] if i["email"] == PARENT][0]
        assert "Dillon and Killian" in inv["subject"] and "Dillon and Killian" in inv["text"]
        assert "One parent account covers all of them" in inv["text"]
        assert "a separate sign-in link for each" in inv["text"]

    def test_a_single_child_family_gets_the_same_message_as_before(self, client):
        c, out = two_kid_family(client)
        ben = [i for i in out["guardian_invites"] if i["email"] == "j@example.com"][0]
        assert ben["also_names"] == [] and "set up Ben's training app" in ben["subject"]
        assert "One parent account" not in ben["text"]

    def test_three_children_are_named_in_a_list(self, client):
        c = club(client)
        out = roster(client, c, [("Ann", "Cole", PARENT), ("Bo", "Cole", PARENT), ("Cy", "Cole", PARENT)])
        inv = out["guardian_invites"][0]
        assert len(out["guardian_invites"]) == 1 and "Ann, Bo and Cy" in inv["subject"]

    def test_the_other_parent_on_the_same_children_is_not_emailed_twice(self, client):
        """A two-parent family: the invite goes to the first parent's address for the children."""
        c = club(client)
        out = roster(client, c, [("Dillon", "Langdon", PARENT), ("Killian", "Langdon", PARENT)])
        assert len(out["guardian_invites"]) == 1

    def test_different_parents_get_their_own_invites(self, client):
        c = club(client)
        out = roster(client, c, [("Dillon", "Langdon", PARENT), ("Ben", "Amden", "j@example.com")])
        assert {i["email"] for i in out["guardian_invites"]} == {PARENT, "j@example.com"}


class TestOneAccountSeesEveryChild:
    def test_redeeming_gives_one_account_with_both_children(self, client):
        c, out = two_kid_family(client)
        inv = [i for i in out["guardian_invites"] if i["email"] == PARENT][0]
        res = redeem(client, inv["code"])
        assert [a["athlete_name"] for a in res["athletes"]] == ["Dillon Langdon", "Killian Langdon"]
        home = me(client, res["token"])
        assert sorted(a["display_name"] for a in home["athletes"]) == ["Dillon Langdon", "Killian Langdon"]
        assert db().execute("SELECT COUNT(*) FROM users WHERE role = 'guardian'").fetchone()[0] == 1

    def test_the_other_family_is_not_attached(self, client):
        c, out = two_kid_family(client)
        res = redeem(client, [i for i in out["guardian_invites"] if i["email"] == PARENT][0]["code"])
        assert all("Amden" not in a["display_name"] for a in me(client, res["token"])["athletes"])

    def test_the_address_typed_at_sign_up_is_never_used_to_find_children(self, client):
        """The invite went to PARENT. The person redeeming types the Amdens' address: they must not gain Ben."""
        c, out = two_kid_family(client)
        res = redeem(client, [i for i in out["guardian_invites"] if i["email"] == PARENT][0]["code"],
                     email="j@example.com")
        assert sorted(a["display_name"] for a in me(client, res["token"])["athletes"]) == \
            ["Dillon Langdon", "Killian Langdon"]

    def test_an_address_in_another_program_attaches_nothing(self, client):
        c, out = two_kid_family(client)
        other = club(client, "Mad Dog Lacrosse")
        roster(client, other, [("Cole", "Dretler", PARENT)])
        res = redeem(client, [i for i in out["guardian_invites"] if i["email"] == PARENT][0]["code"])
        assert all("Dretler" not in a["display_name"] for a in me(client, res["token"])["athletes"])

    def test_a_manual_invite_with_no_roster_address_covers_just_that_child(self, client):
        c = club(client)
        roster(client, c, [("Dillon", "Langdon", PARENT), ("Killian", "Langdon", PARENT)])
        kid = kid_id(client, c, "Dillon Langdon")
        inv = client.post("/api/coach/guardian-invites", headers=c["d"], json={"athlete_id": kid}).json()
        res = redeem(client, inv["code"], email="grandma@example.com", name="Grandma")
        assert [a["athlete_name"] for a in res["athletes"]] == ["Dillon Langdon"]

    def test_the_second_email_for_the_same_family_is_retired(self, client):
        """If a second invite for the same address exists, redeeming the first leaves no way to make a duplicate."""
        c, out = two_kid_family(client)
        killian = kid_id(client, c, "Killian Langdon")
        spare = client.post("/api/coach/guardian-invites", headers=c["d"],
                            json={"athlete_id": killian, "email": PARENT}).json()
        redeem(client, [i for i in out["guardian_invites"] if i["email"] == PARENT][0]["code"])
        res = client.post("/api/guardians/redeem", json={"code": spare["code"], "display_name": "Robert",
                                                         "email": PARENT, "phone": "615-555-0101"})
        assert res.status_code == 400 and "Get back in" in res.text
        assert db().execute("SELECT COUNT(*) FROM users WHERE role = 'guardian'").fetchone()[0] == 1


class TestALinkForEachChild:
    def _family(self, client):
        c, out = two_kid_family(client)
        res = redeem(client, [i for i in out["guardian_invites"] if i["email"] == PARENT][0]["code"])
        d, k = kid_id(client, c, "Dillon Langdon"), kid_id(client, c, "Killian Langdon")
        return c, res["token"], d, k

    def test_a_link_needs_that_childs_own_yes(self, client):
        c, tok, d, k = self._family(client)
        assert say_yes(client, tok, d).status_code in (200, 201)
        assert client.post(f"/api/guardians/athlete-link/{d}", headers=bearer(tok)).status_code == 201
        refused = client.post(f"/api/guardians/athlete-link/{k}", headers=bearer(tok))
        assert refused.status_code in (400, 403, 409), refused.text            # Dillon's yes is not Killian's

    def test_each_link_signs_in_its_own_child(self, client):
        c, tok, d, k = self._family(client)
        links = {}
        for kid in (d, k):
            assert say_yes(client, tok, kid).status_code in (200, 201)
            links[kid] = client.post(f"/api/guardians/athlete-link/{kid}", headers=bearer(tok)).json()["link"]
        assert links[d] != links[k]
        for kid, link in links.items():
            who = client.get("/api/me", headers=bearer(link.split("code=")[1])).json()
            assert who["display_name"] == ("Dillon Langdon" if kid == d else "Killian Langdon")

    def test_a_new_link_for_one_child_does_not_end_the_other_childs(self, client):
        c, tok, d, k = self._family(client)
        for kid in (d, k):
            say_yes(client, tok, kid)
        first = {kid: client.post(f"/api/guardians/athlete-link/{kid}", headers=bearer(tok)).json()["link"].split("code=")[1]
                 for kid in (d, k)}
        client.post(f"/api/guardians/athlete-link/{d}", headers=bearer(tok))      # a new one for Dillon only
        assert client.get("/api/me", headers=bearer(first[d])).status_code in (401, 403)   # Dillon's old one is dead
        assert client.get("/api/me", headers=bearer(first[k])).status_code == 200          # Killian's still works

    def test_withdrawing_one_childs_yes_leaves_the_other_alone(self, client):
        c, tok, d, k = self._family(client)
        for kid in (d, k):
            say_yes(client, tok, kid)
        client.post("/api/guardians/consent", headers=bearer(tok),
                    json={"athlete_id": d, "scope": "participation", "granted": False})
        by = {a["athlete_id"]: a for a in me(client, tok)["athletes"]}
        yes = lambda a: any(x["scope"] == "participation" and x["granted"] for x in a["consents"])
        assert not yes(by[d]) and yes(by[k])

    def test_the_directors_family_board_shows_both_children_as_signed_up(self, client):
        c, tok, d, k = self._family(client)
        fam = client.get("/api/coach/families", headers=c["d"], params={"team_id": c["team"]}).json()
        rows = {a["athlete_id"]: a for a in fam["athletes"]}
        assert rows[d]["stage"] == rows[k]["stage"] and rows[d]["stage"] != "no_parent"


class TestAChildAddedLater:
    def _signed_up(self, client):
        c, out = two_kid_family(client)
        res = redeem(client, [i for i in out["guardian_invites"] if i["email"] == PARENT][0]["code"])
        return c, res["token"]

    def test_a_third_child_with_the_same_address_joins_the_account(self, client):
        c, tok = self._signed_up(client)
        before = db().execute("SELECT COUNT(*) FROM guardian_invites").fetchone()[0]
        out = roster(client, c, [("Sam", "Langdon", PARENT)])
        assert out["guardian_invites"] == []                                          # no second invite
        assert db().execute("SELECT COUNT(*) FROM guardian_invites").fetchone()[0] == before
        assert "Sam Langdon" in [a["display_name"] for a in me(client, tok)["athletes"]]
        assert db().execute("SELECT COUNT(*) FROM users WHERE role = 'guardian'").fetchone()[0] == 1

    def test_the_parent_is_told(self, client):
        c, tok = self._signed_up(client)
        roster(client, c, [("Sam", "Langdon", PARENT)])
        notes = client.get("/api/notifications", headers=bearer(tok)).json()
        items = notes if isinstance(notes, list) else notes.get("notifications", notes.get("items", []))
        assert any("Sam was added to your account" in n["title"] for n in items), items

    def test_the_child_still_needs_their_own_yes_before_any_link(self, client):
        c, tok = self._signed_up(client)
        roster(client, c, [("Sam", "Langdon", PARENT)])
        sam = kid_id(client, c, "Sam Langdon")
        assert client.post(f"/api/guardians/athlete-link/{sam}", headers=bearer(tok)).status_code in (400, 403, 409)

    def test_a_child_with_a_different_address_is_not_attached(self, client):
        c, tok = self._signed_up(client)
        out = roster(client, c, [("Sam", "Wright", "wright@example.com")])
        assert len(out["guardian_invites"]) == 1
        assert "Sam Wright" not in [a["display_name"] for a in me(client, tok)["athletes"]]

    def test_a_child_in_another_program_is_not_attached(self, client):
        c, tok = self._signed_up(client)
        other = club(client, "Mad Dog Lacrosse")
        roster(client, other, [("Cole", "Dretler", PARENT)])
        assert "Cole Dretler" not in [a["display_name"] for a in me(client, tok)["athletes"]]


class TestTheDirectorsResend:
    def test_resending_for_one_child_covers_the_family_and_retires_the_old_invite(self, client):
        c, out = two_kid_family(client)
        d = kid_id(client, c, "Dillon Langdon")
        res = client.post("/api/coach/families/nudge", headers=c["d"], json={"athlete_id": d})
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["covers"] == ["Dillon Langdon", "Killian Langdon"]
        assert "Dillon and Killian" in body["text"]
        live = db().execute("SELECT COUNT(*) FROM guardian_invites WHERE lower(email) = ? "
                            "AND redeemed_at IS NULL AND revoked_at IS NULL", (PARENT,)).fetchone()[0]
        assert live == 1

    def test_resending_for_the_second_child_does_the_same(self, client):
        c, out = two_kid_family(client)
        k = kid_id(client, c, "Killian Langdon")
        body = client.post("/api/coach/families/nudge", headers=c["d"], json={"athlete_id": k}).json()
        assert sorted(body["covers"]) == ["Dillon Langdon", "Killian Langdon"]
        live = db().execute("SELECT COUNT(*) FROM guardian_invites WHERE lower(email) = ? "
                            "AND redeemed_at IS NULL AND revoked_at IS NULL", (PARENT,)).fetchone()[0]
        assert live == 1

    def test_resending_to_many_sends_one_email_per_family(self, client):
        c, out = two_kid_family(client)
        ids = [kid_id(client, c, n) for n in ("Dillon Langdon", "Killian Langdon", "Ben Amden")]
        res = client.post("/api/coach/families/nudge-many", headers=c["d"], json={"athlete_ids": ids}).json()
        by = {r["athlete_id"]: r for r in res["results"]}
        assert sorted(r["status"] for r in res["results"]) == ["ready", "ready", "skipped"]
        skipped = [r for r in res["results"] if r["status"] == "skipped"][0]
        assert "one invite covers both" in skipped["reason"]
        assert db().execute("SELECT COUNT(*) FROM guardian_invites WHERE lower(email) = ? "
                            "AND redeemed_at IS NULL AND revoked_at IS NULL", (PARENT,)).fetchone()[0] == 1


class TestTheScreen:
    @staticmethod
    def page(name):
        from pathlib import Path
        return (Path(api_module.__file__).parent / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_walkthrough_opens_again_for_a_child_added_later(self):
        html = self.page("parent.html")
        assert "`done:${seen.join(',')}`" in html
        assert "me.athletes.every((a) => walked.includes(a.athlete_id))" in html
        assert "saved === 'done'" in html                       # the old switched-off value still works

    def test_the_walkthrough_has_a_yes_step_and_a_link_step_for_every_child(self):
        html = self.page("parent.html")
        assert "for (const a of me.athletes)" in html
        assert "key: `yes-${a.athlete_id}`" in html and "key: `link-${a.athlete_id}`" in html


class TestOnlyWhatTheProgramGaveCounts:
    def test_an_address_typed_at_sign_up_does_not_make_someone_elses_child_yours(self, client):
        """Ann's parent mistypes the Wrights' address at sign-up. That is not the program saying Ann is the
        Wrights' child, so when the Wrights sign up they must not gain Ann."""
        c = club(client)
        out = roster(client, c, [("Ann", "Cole", "cole@example.com"), ("Xavier", "Wright", "wright@example.com")])
        ann_inv = [i for i in out["guardian_invites"] if i["email"] == "cole@example.com"][0]
        redeem(client, ann_inv["code"], email="wright@example.com", name="Cole Parent")      # the typo
        wr_inv = [i for i in out["guardian_invites"] if i["email"] == "wright@example.com"][0]
        assert wr_inv["also_names"] == []
        res = redeem(client, wr_inv["code"], email="wright@example.com", name="Wright Parent")
        assert [a["athlete_name"] for a in res["athletes"]] == ["Xavier Wright"]
        assert [a["display_name"] for a in me(client, res["token"])["athletes"]] == ["Xavier Wright"]

    def test_a_child_who_has_left_the_program_is_not_added(self, client):
        c, out = two_kid_family(client)
        killian = kid_id(client, c, "Killian Langdon")
        db().execute("UPDATE users SET active = 0 WHERE id = ?", (killian,))
        db().commit()
        res = redeem(client, [i for i in out["guardian_invites"] if i["email"] == PARENT][0]["code"])
        assert db().execute("SELECT COUNT(*) FROM guardians WHERE athlete_id = ?", (killian,)).fetchone()[0] == 0
        assert [a["athlete_name"] for a in res["athletes"]] == ["Dillon Langdon"]

    def test_the_message_names_every_child_the_account_will_show(self, client):
        """Killian already has another adult (a grandparent) signed up. Dad's account still gets both children,
        so his email names both."""
        c = club(client)
        out = roster(client, c, [("Dillon", "Langdon", PARENT), ("Killian", "Langdon", PARENT)])
        killian = kid_id(client, c, "Killian Langdon")
        spare = client.post("/api/coach/guardian-invites", headers=c["d"], json={"athlete_id": killian}).json()
        redeem(client, spare["code"], email="grandma@example.com", name="Grandma")
        dillon = kid_id(client, c, "Dillon Langdon")
        again = client.post("/api/coach/guardian-invites", headers=c["d"],
                            json={"athlete_id": dillon, "email": PARENT}).json()
        assert again["also_names"] == ["Killian Langdon"]
        res = redeem(client, again["code"])
        assert sorted(a["athlete_name"] for a in res["athletes"]) == ["Dillon Langdon", "Killian Langdon"]
