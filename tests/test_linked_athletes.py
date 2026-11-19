"""One athlete in two programs: a parent links the records and the work counts in each.

Each program keeps its own athlete record; a parent links them; a counted session is then counted in every
linked program, under that program's own rules. These tests hold the rules in place:

* only a parent who is a parent in BOTH programs by an address the programs supplied can link, and must choose;
* at most one athlete per program in a group;
* a copy is made once, only for counted work, never copied again, and only where that program's season is
  running, the athlete is active and that program's parent has said yes;
* a held session is copied only once a coach approves it;
* nothing else crosses (each program sees only its own athlete), and a failure in a linked program never breaks
  the athlete's own session;
* either parent can stop it; copies already made stay.
"""
from __future__ import annotations

import random

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import linked
from offdays.db import connect
from offdays.store import Store

EMAIL = "kathy.k@example.com"


@pytest.fixture
def client(tmp_path):
    api_module._store = Store(connect(tmp_path / "t.db"))
    yield TestClient(api_module.app)
    api_module._store = None


def db():
    return api_module._store.conn


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def club(client, name):
    made = client.post("/api/orgs", json={"name": name, "sport": "lacrosse", "accept_terms": True,
                                          "director_name": "Dir"}).json()
    d = bearer(made["director"]["token"])
    team = client.post("/api/teams", json={"name": "U12"}, headers=d).json()["id"]
    org_id = client.get("/api/orgs/mine", headers=d).json()["active_org_id"]
    return {"d": d, "team": team, "org_id": org_id, "name": name}


def family(client, c, name="Ryder Kallberg", roster_email=EMAIL, typed_email=None, invite_email=None,
           parent_name="Kathy", say_yes=True, birth_year=2013):
    """The kid on this club's roster, a parent who redeems the invite and says yes, and the kid's own link."""
    first, last = name.split()
    client.post("/api/coach/roster/import", headers=c["d"], json={
        "content": f"First Name,Last Name,Birth Year,Parent Email\n{first},{last},{birth_year},{roster_email}\n",
        "team_id": c["team"]})
    rows = client.get("/api/coach/team-ranking", headers=c["d"], params={"team_id": c["team"]}).json()["rows"]
    kid = [r for r in rows if r.get("display_name", r.get("name", r.get("athlete_name"))) == name][0]["athlete_id"]
    inv = client.post("/api/coach/guardian-invites", headers=c["d"],
                      json={"athlete_id": kid, "email": invite_email or roster_email}).json()
    parent = client.post("/api/guardians/redeem", json={
        "code": inv["code"], "display_name": f"{parent_name} {last}", "email": typed_email or roster_email,
        "phone": "615-555-0101"}).json()
    p = bearer(parent["token"])
    if say_yes:
        assert client.post("/api/guardians/consent", headers=p,
                           json={"athlete_id": kid, "scope": "participation", "granted": True}).status_code in (200, 201)
        link = client.post(f"/api/guardians/athlete-link/{kid}", headers=p).json()["link"]
        a = bearer(link.split("code=")[1])
    else:
        a = None
    return {"kid": kid, "p": p, "a": a, "club": c, "parent_id": parent["guardian_id"]}


def two_clubs(client, **kw):
    a = family(client, club(client, "Club A"), **kw)
    b = family(client, club(client, "Club B"), **kw)
    return a, b


def link_them(client, mine, other):
    return client.post(f"/api/guardians/links/{mine['kid']}", headers=mine["p"], json={"other_id": other["kid"]})


def train(client, fam, drill="lax_wall_ball", count=120, seed=5, gap=880, hold=False):
    h = fam["a"]
    started = client.post("/api/sessions/start", json={"drill_key": drill}, headers=h).json()
    rng = random.Random(seed)
    t, reps = 0, []
    for i in range(count):
        if hold:
            t += gap                                   # perfectly metronomic: held for review
        else:
            t += max(150, int(rng.gauss(gap, 200)))
        reps.append({"t_ms": t, "hand": "left" if i % 2 else "right", "confidence": 0.88 if not hold else 0.9})
    return client.post("/api/sessions/submit", headers=h, json={
        "session_id": started["session_id"], "nonce": started["nonce"], "duration_ms": t + 700,
        "reps": reps, "mean_confidence": 0.88}), started["session_id"]


def sessions_of(kid):
    return [dict(r) for r in db().execute(
        "SELECT * FROM sessions WHERE athlete_id = ? ORDER BY id", (kid,)).fetchall()]


def xp_of(kid):
    return int(db().execute("SELECT COALESCE(SUM(amount),0) FROM xp_ledger WHERE athlete_id = ?", (kid,)).fetchone()[0])


# ----------------------------------------------------------------------------------- finding the other record
class TestAParentIsOfferedTheOtherProgram:
    def test_nothing_is_offered_before_the_second_program_has_this_parent(self, client):
        a = family(client, club(client, "Club A"))
        res = client.get(f"/api/guardians/links/{a['kid']}", headers=a["p"]).json()
        assert res == {"linked": [], "candidates": []}

    def test_it_is_offered_once_the_same_parent_is_in_the_second_program(self, client):
        a, b = two_clubs(client)
        cand = client.get(f"/api/guardians/links/{a['kid']}", headers=a["p"]).json()["candidates"]
        assert [c["athlete_id"] for c in cand] == [b["kid"]]
        assert cand[0]["org_name"] == "Club B" and cand[0]["same_name"] is True

    def test_it_is_offered_from_either_side(self, client):
        a, b = two_clubs(client)
        cand = client.get(f"/api/guardians/links/{b['kid']}", headers=b["p"]).json()["candidates"]
        assert [c["athlete_id"] for c in cand] == [a["kid"]]

    def test_the_address_typed_at_signup_is_not_trusted(self, client):
        """Both parents typed the same address at sign-up, but neither program has it: a stranger could
        have typed it. No suggestion."""
        a = family(client, club(client, "Club A"), roster_email="roster.a@example.com", typed_email="same@example.com")
        family(client, club(client, "Club B"), roster_email="roster.b@example.com", typed_email="same@example.com")
        assert client.get(f"/api/guardians/links/{a['kid']}", headers=a["p"]).json()["candidates"] == []

    def test_the_address_an_invite_was_emailed_to_counts(self, client):
        a = family(client, club(client, "Club A"), roster_email="a@example.com", invite_email=EMAIL, typed_email="x@example.com")
        b = family(client, club(client, "Club B"), roster_email="b@example.com", invite_email=EMAIL, typed_email="y@example.com")
        assert [c["athlete_id"] for c in client.get(f"/api/guardians/links/{a['kid']}", headers=a["p"]).json()["candidates"]] == [b["kid"]]

    def test_capitals_in_the_address_do_not_matter(self, client):
        a = family(client, club(client, "Club A"), roster_email="Kathy.K@Example.com")
        b = family(client, club(client, "Club B"), roster_email="kathy.k@example.COM")
        assert client.get(f"/api/guardians/links/{a['kid']}", headers=a["p"]).json()["candidates"]

    def test_a_different_parent_in_the_other_program_is_not_offered(self, client):
        a = family(client, club(client, "Club A"), roster_email="one@example.com")
        family(client, club(client, "Club B"), roster_email="two@example.com")
        assert client.get(f"/api/guardians/links/{a['kid']}", headers=a["p"]).json()["candidates"] == []

    def test_the_same_name_is_not_enough(self, client):
        """Two Sam Hills in two clubs with two different families must never be offered to each other."""
        a = family(client, club(client, "Club A"), name="Sam Hill", roster_email="hill.a@example.com")
        family(client, club(client, "Club B"), name="Sam Hill", roster_email="hill.b@example.com")
        assert client.get(f"/api/guardians/links/{a['kid']}", headers=a["p"]).json()["candidates"] == []

    def test_a_second_child_of_the_same_parent_is_offered_but_ranked_after_the_same_name(self, client):
        a = family(client, club(client, "Club A"), name="Ryder Kallberg")
        cb = club(client, "Club B")
        b1 = family(client, cb, name="Wren Kallberg")
        # same parent, same email, second child on club B's roster
        client.post("/api/coach/roster/import", headers=cb["d"], json={
            "content": f"First Name,Last Name,Birth Year,Parent Email\nRyder,Kallberg,2013,{EMAIL}\n", "team_id": cb["team"]})
        rows = client.get("/api/coach/team-ranking", headers=cb["d"], params={"team_id": cb["team"]}).json()["rows"]
        ryder_b = [r for r in rows if r.get("display_name", r.get("name")) == "Ryder Kallberg"][0]["athlete_id"]
        inv = client.post("/api/coach/guardian-invites", headers=cb["d"], json={"athlete_id": ryder_b, "email": EMAIL}).json()
        assert inv.get("code")
        # the second invite is refused or accepted; either way the parent in club B now holds both children
        db().execute("INSERT OR IGNORE INTO guardians(guardian_id, athlete_id, relationship, linked_at) VALUES (?,?,?,?)",
                     (b1["parent_id"], ryder_b, "parent", "2026-01-01T00:00:00+00:00"))
        db().commit()
        cand = client.get(f"/api/guardians/links/{a['kid']}", headers=a["p"]).json()["candidates"]
        assert [c["athlete_id"] for c in cand][0] == ryder_b and cand[0]["same_name"] is True
        assert {c["athlete_id"] for c in cand} == {ryder_b, b1["kid"]}

    def test_only_the_athletes_own_parent_can_ask(self, client):
        a, b = two_clubs(client)
        assert client.get(f"/api/guardians/links/{a['kid']}", headers=b["p"]).status_code in (400, 403)

    def test_an_athlete_a_coach_and_the_anonymous_cannot_ask(self, client):
        a, b = two_clubs(client)
        assert client.get(f"/api/guardians/links/{a['kid']}", headers=a["a"]).status_code == 403
        assert client.get(f"/api/guardians/links/{a['kid']}", headers=a["club"]["d"]).status_code == 403
        assert client.get(f"/api/guardians/links/{a['kid']}").status_code == 401


# ----------------------------------------------------------------------------------- making and ending the link
class TestLinkingAndUnlinking:
    def test_the_parent_chooses_and_it_links(self, client):
        a, b = two_clubs(client)
        res = link_them(client, a, b)
        assert res.status_code == 201, res.text
        assert [p["org_name"] for p in res.json()["linked"]] == ["Club B"]
        assert res.json()["candidates"] == []

    def test_it_is_linked_for_the_other_parent_too(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        seen = client.get(f"/api/guardians/links/{b['kid']}", headers=b["p"]).json()
        assert [p["org_name"] for p in seen["linked"]] == ["Club A"]

    def test_an_athlete_that_is_not_offered_is_refused(self, client):
        a = family(client, club(client, "Club A"), roster_email="one@example.com")
        stranger = family(client, club(client, "Club B"), roster_email="two@example.com")
        res = link_them(client, a, stranger)
        assert res.status_code == 400 and linked.group_of(db(), a["kid"]) is None

    def test_a_guessed_id_is_refused(self, client):
        a, b = two_clubs(client)
        assert client.post(f"/api/guardians/links/{a['kid']}", headers=a["p"], json={"other_id": 99999}).status_code == 400
        assert client.post(f"/api/guardians/links/{a['kid']}", headers=a["p"], json={"other_id": a["kid"]}).status_code == 400

    def test_another_parent_cannot_link_this_athlete(self, client):
        a, b = two_clubs(client)
        assert client.post(f"/api/guardians/links/{a['kid']}", headers=b["p"], json={"other_id": b["kid"]}).status_code in (400, 403)
        assert linked.group_of(db(), a["kid"]) is None

    def test_two_athletes_in_one_program_never_join(self, client):
        """A brother on the same club is a candidate for nobody: one athlete per program in a group."""
        a, b = two_clubs(client)
        link_them(client, a, b)
        cb = b["club"]
        client.post("/api/coach/roster/import", headers=cb["d"], json={
            "content": f"First Name,Last Name,Birth Year,Parent Email\nWren,Kallberg,2015,{EMAIL}\n", "team_id": cb["team"]})
        rows = client.get("/api/coach/team-ranking", headers=cb["d"], params={"team_id": cb["team"]}).json()["rows"]
        wren = [r for r in rows if r.get("display_name", r.get("name")) == "Wren Kallberg"][0]["athlete_id"]
        db().execute("INSERT OR IGNORE INTO guardians(guardian_id, athlete_id, relationship, linked_at) VALUES (?,?,?,?)",
                     (b["parent_id"], wren, "parent", "2026-01-01T00:00:00+00:00"))
        db().commit()
        cand = client.get(f"/api/guardians/links/{a['kid']}", headers=a["p"]).json()["candidates"]
        assert wren not in [c["athlete_id"] for c in cand]
        assert client.post(f"/api/guardians/links/{a['kid']}", headers=a["p"], json={"other_id": wren}).status_code == 400

    def test_linking_twice_changes_nothing(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        again = link_them(client, a, b)
        assert again.status_code == 400                    # already linked: no longer a candidate
        assert db().execute("SELECT COUNT(*) FROM athlete_links").fetchone()[0] == 2

    def test_three_programs_form_one_group(self, client):
        a, b = two_clubs(client)
        c = family(client, club(client, "Club C"))
        link_them(client, a, b)
        assert link_them(client, c, a).status_code == 201
        assert sorted(linked.members(db(), b["kid"])) == sorted([a["kid"], c["kid"]])
        assert len({linked.group_of(db(), k) for k in (a["kid"], b["kid"], c["kid"])}) == 1

    def test_either_parent_can_stop_it(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        res = client.delete(f"/api/guardians/links/{b['kid']}", headers=b["p"])
        assert res.status_code == 200 and res.json()["linked"] == []
        assert linked.group_of(db(), a["kid"]) is None, "a group of one is not a group"

    def test_stopping_does_not_take_back_work_already_counted(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        train(client, a)
        before = len(sessions_of(b["kid"]))
        client.delete(f"/api/guardians/links/{a['kid']}", headers=a["p"])
        assert len(sessions_of(b["kid"])) == before == 1

    def test_after_stopping_new_work_is_not_copied(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        client.delete(f"/api/guardians/links/{a['kid']}", headers=a["p"])
        train(client, a)
        assert sessions_of(b["kid"]) == []

    def test_only_the_athletes_own_parent_can_stop_it(self, client):
        a, b = two_clubs(client)
        c = family(client, club(client, "Club C"), roster_email="other@example.com")
        link_them(client, a, b)
        client.delete(f"/api/guardians/links/{a['kid']}", headers=c["p"])
        assert linked.group_of(db(), a["kid"]) is not None

    def test_the_athlete_is_told_every_program_their_work_counts_for(self, client):
        a, b = two_clubs(client)
        assert client.get("/api/me", headers=a["a"]).json()["counts_for"] == []
        link_them(client, a, b)
        assert client.get("/api/me", headers=a["a"]).json()["counts_for"] == ["Club A", "Club B"]
        assert client.get("/api/me", headers=b["a"]).json()["counts_for"] == ["Club B", "Club A"]

    def test_deleting_an_athlete_removes_their_links(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        db().execute("PRAGMA foreign_keys = ON")
        db().execute("DELETE FROM users WHERE id = ?", (b["kid"],))
        db().commit()
        assert db().execute("SELECT COUNT(*) FROM athlete_links WHERE athlete_id = ?", (b["kid"],)).fetchone()[0] == 0


# ----------------------------------------------------------------------------------- the work counts in each
class TestTheWorkCountsInEachProgram:
    def test_a_counted_session_is_counted_in_the_other_program(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        res, sid = train(client, a)
        assert res.status_code == 200 and res.json()["status"] == "counted"
        mine, theirs = sessions_of(a["kid"]), sessions_of(b["kid"])
        assert len(mine) == 1 and len(theirs) == 1
        assert theirs[0]["status"] == "counted" and theirs[0]["mirrored_from"] == sid
        for col in ("drill_key", "reps_total", "reps_left", "reps_right", "duration_ms", "xp_awarded", "completed_at"):
            assert theirs[0][col] == mine[0][col], col

    def test_the_xp_is_counted_in_each_program(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        train(client, a)
        assert xp_of(a["kid"]) > 0 and xp_of(b["kid"]) == xp_of(a["kid"])
        assert client.get("/api/me", headers=b["a"]).json()["total_xp"] == client.get("/api/me", headers=a["a"]).json()["total_xp"]

    def test_the_rep_detail_comes_too(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        train(client, a, count=60)
        src, dst = sessions_of(a["kid"])[0]["id"], sessions_of(b["kid"])[0]["id"]
        n = lambda s: db().execute("SELECT COUNT(*) FROM rep_events WHERE session_id = ?", (s,)).fetchone()[0]
        assert n(src) == n(dst) > 0

    def test_it_works_the_other_way_round_too(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        train(client, b)
        assert len(sessions_of(a["kid"])) == 1 and len(sessions_of(b["kid"])) == 1

    def test_the_other_program_gets_the_athletes_badges(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        train(client, a)
        mine = client.get("/api/me", headers=a["a"]).json()
        theirs = client.get("/api/me", headers=b["a"]).json()
        assert mine.get("badges") == theirs.get("badges") and mine.get("badges")

    def test_a_copy_is_made_once_and_never_copied_again(self, client):
        a, b = two_clubs(client)
        c = family(client, club(client, "Club C"))
        link_them(client, a, b)
        link_them(client, c, a)
        res, sid = train(client, a)
        total = db().execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        assert total == 3, "one session from A, one copy each in B and C, nothing more"
        assert db().execute("SELECT COUNT(*) FROM sessions WHERE mirrored_from IS NOT NULL AND mirrored_from <> ?", (sid,)).fetchone()[0] == 0
        assert linked.mirror_session(db(), sid) == []       # asking again copies nothing
        assert db().execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 3

    def test_a_copy_is_never_copied_by_asking_for_it(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        train(client, a)
        copy_id = sessions_of(b["kid"])[0]["id"]
        assert linked.mirror_session(db(), copy_id) == []
        assert len(sessions_of(a["kid"])) == 1

    def test_the_same_session_resent_by_a_phone_is_counted_once(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        h = a["a"]
        started = client.post("/api/sessions/start", json={"drill_key": "lax_wall_ball"}, headers=h).json()
        rng, t, reps = random.Random(5), 0, []
        for i in range(100):
            t += max(150, int(rng.gauss(880, 200)))
            reps.append({"t_ms": t, "hand": "left" if i % 2 else "right", "confidence": 0.88})
        body = {"session_id": started["session_id"], "nonce": started["nonce"], "duration_ms": t + 700, "reps": reps, "mean_confidence": 0.88}
        r1 = client.post("/api/sessions/submit", json=body, headers=h)
        r2 = client.post("/api/sessions/submit", json=body, headers=h)
        assert r1.status_code == 200 and r2.status_code in (200, 409)
        assert len(sessions_of(a["kid"])) == 1 and len(sessions_of(b["kid"])) == 1

    def test_work_done_before_the_link_is_not_copied(self, client):
        a, b = two_clubs(client)
        train(client, a)
        link_them(client, a, b)
        assert sessions_of(b["kid"]) == []
        train(client, a, seed=9)
        assert len(sessions_of(b["kid"])) == 1

    def test_each_program_ranks_its_own_athlete_on_the_work(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        train(client, a)
        rows = client.get("/api/coach/team-ranking", headers=b["club"]["d"], params={"team_id": b["club"]["team"]}).json()["rows"]
        mine = [r for r in rows if r["athlete_id"] == b["kid"]][0]
        assert mine["xp"] == xp_of(b["kid"]) > 0


# ----------------------------------------------------------------------------------- each program's own rules
class TestEachProgramKeepsItsOwnRules:
    def test_a_held_session_is_not_copied_until_a_coach_approves_it(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        res, sid = train(client, a, count=99, gap=800, hold=True)
        assert sessions_of(a["kid"])[0]["status"] == "review"
        assert sessions_of(b["kid"]) == []
        client.post(f"/api/coach/review/{sid}", json={"approve": True}, headers=a["club"]["d"])
        assert [s["status"] for s in sessions_of(b["kid"])] == ["counted"]
        assert sessions_of(b["kid"])[0]["mirrored_from"] == sid

    def test_a_rejected_session_is_never_copied(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        res, sid = train(client, a, count=99, gap=800, hold=True)
        client.post(f"/api/coach/review/{sid}", json={"approve": False}, headers=a["club"]["d"])
        assert sessions_of(b["kid"]) == []

    def test_a_program_whose_season_has_ended_takes_no_copy_and_the_other_is_unaffected(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        db().execute("UPDATE organizations SET season_ends_on = '2000-01-01' WHERE id = ?", (b["club"]["org_id"],))
        db().commit()
        res, _ = train(client, a)
        assert res.status_code == 200 and len(sessions_of(a["kid"])) == 1
        assert sessions_of(b["kid"]) == []

    def test_the_last_day_of_a_season_still_counts(self, client):
        from datetime import datetime, timezone
        a, b = two_clubs(client)
        link_them(client, a, b)
        db().execute("UPDATE organizations SET season_ends_on = ? WHERE id = ?", (datetime.now(timezone.utc).date().isoformat(), b["club"]["org_id"]))
        db().commit()
        train(client, a)
        assert len(sessions_of(b["kid"])) == 1

    def test_a_program_whose_parent_has_withdrawn_takes_no_copy(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        client.post("/api/guardians/consent", headers=b["p"], json={"athlete_id": b["kid"], "scope": "participation", "granted": False})
        res, _ = train(client, a)
        assert res.status_code == 200 and len(sessions_of(a["kid"])) == 1
        assert sessions_of(b["kid"]) == []

    def test_a_program_that_has_removed_the_athlete_takes_no_copy(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        db().execute("UPDATE users SET active = 0 WHERE id = ?", (b["kid"],))
        db().commit()
        train(client, a)
        assert sessions_of(b["kid"]) == []

    def test_a_failure_in_the_other_program_never_breaks_the_athletes_own_session(self, client, monkeypatch):
        a, b = two_clubs(client)
        link_them(client, a, b)

        def boom(*_a, **_k):
            raise RuntimeError("the other program is broken")

        monkeypatch.setattr(linked, "mirror_session", boom)
        res, _ = train(client, a)
        assert res.status_code == 200 and res.json()["status"] == "counted"
        assert len(sessions_of(a["kid"])) == 1 and xp_of(a["kid"]) > 0


# ----------------------------------------------------------------------------------- what does not cross
class TestNothingElseCrosses:
    def test_a_director_cannot_reach_the_other_programs_athlete(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        train(client, a)
        res = client.get(f"/api/coach/overview/player/{b['kid']}", headers=a["club"]["d"])
        assert res.status_code in (403, 404)

    def test_a_directors_views_never_name_the_other_program(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        train(client, a)
        for path in (f"/api/coach/overview/player/{a['kid']}", "/api/coach/overview", "/api/coach/families"):
            body = client.get(path, headers=a["club"]["d"]).text
            assert "Club B" not in body, path

    def test_a_coach_sees_the_copied_work_as_that_athletes_own(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        train(client, a)
        body = client.get(f"/api/coach/overview/player/{b['kid']}", headers=b["club"]["d"]).json()
        assert body["athlete"]["id"] == b["kid"]
        assert body["sessions"] == 1 and len(body["recent_sessions"]) == 1
        assert "Club A" not in str(body)

    def test_checkins_do_not_cross(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        db().execute("INSERT INTO wellness_checkins(athlete_id, day, energy, soreness, mood, created_at) VALUES (?,?,?,?,?,?)",
                     (a["kid"], "2026-11-17", 3, 1, 3, "2026-11-17T00:00:00+00:00")) if _has(db(), "wellness_checkins", "energy") else None
        db().commit()
        assert db().execute("SELECT COUNT(*) FROM wellness_checkins WHERE athlete_id = ?", (b["kid"],)).fetchone()[0] == 0

    def test_a_parent_sees_only_their_own_programs_children_in_the_portal(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        me = client.get("/api/guardians/me", headers=a["p"]).json()
        assert [x.get("athlete_id", x.get("id")) for x in me["athletes"]] == [a["kid"]]


def _has(conn, table, col):
    return col in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


# ----------------------------------------------------------------------------------- an older database opens
class TestAnOlderDatabaseOpens:
    def test_the_new_column_and_index_arrive_on_a_database_made_before_them(self, tmp_path):
        """Prod has a database that predates this feature. Opening it must add the column BEFORE anything
        indexes it, or the app would not start."""
        import re
        from offdays import db as dbm

        old_schema = re.sub(r",\n    -- Set on a copy made.*?mirrored_from[^\n]*\n\);", "\n);", dbm.SCHEMA, flags=re.S)
        old_schema = re.sub(r"-- One athlete in several programs.*?idx_athlete_links_group[^\n]*\n", "", old_schema, flags=re.S)
        assert "mirrored_from" not in old_schema and "athlete_links" not in old_schema
        conn = connect(tmp_path / "old.db")
        conn.executescript(old_schema)
        conn.commit()
        assert "mirrored_from" not in {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
        conn.close()

        reopened = connect(tmp_path / "old.db")
        dbm.init_db(reopened)                      # what opening the app does
        assert "mirrored_from" in {r[1] for r in reopened.execute("PRAGMA table_info(sessions)")}
        assert reopened.execute("SELECT 1 FROM sqlite_master WHERE name = 'idx_sessions_mirror'").fetchone()
        assert reopened.execute("SELECT 1 FROM sqlite_master WHERE name = 'athlete_links'").fetchone()
        dbm.init_db(reopened)                      # and opening it again is harmless


# ----------------------------------------------------------------------------------- the two screens
from pathlib import Path as _P

_STATIC = _P(__file__).resolve().parents[1] / "offdays" / "web" / "static"
PARENT_HTML = (_STATIC / "parent.html").read_text(encoding="utf-8")
CAPTURE_HTML = (_STATIC / "capture.html").read_text(encoding="utf-8")


class TestTheParentPage:
    def test_each_athlete_card_has_a_place_for_it_and_it_is_loaded(self):
        assert 'data-links="${a.athlete_id}"' in PARENT_HTML
        assert "document.querySelectorAll('[data-links]').forEach((box) => loadLinks(box));" in PARENT_HTML

    def test_it_asks_for_a_link_only_when_the_parent_presses_the_button(self):
        fn = PARENT_HTML[PARENT_HTML.index("async function loadLinks(box)"):PARENT_HTML.index("function renderAthlete(a)")]
        assert fn.count("method: 'POST'") == 1
        assert fn.index("data-link-to") < fn.index("method: 'POST'")
        assert "other_id: Number(btn.dataset.linkTo)" in fn

    def test_it_says_what_will_happen_and_that_it_can_be_stopped(self):
        fn = PARENT_HTML[PARENT_HTML.index("async function loadLinks(box)"):PARENT_HTML.index("function renderAthlete(a)")]
        assert "from now on" in fn and "stop any time" in fn
        assert "Each program sees only its own athlete" in fn

    def test_stopping_asks_first_and_says_what_stays(self):
        fn = PARENT_HTML[PARENT_HTML.index("async function loadLinks(box)"):PARENT_HTML.index("function renderAthlete(a)")]
        assert "window.confirm" in fn and "Work already counted stays" in fn
        assert fn.index("window.confirm") < fn.index("method: 'DELETE'")

    def test_the_block_is_left_empty_when_there_is_nothing_to_say(self):
        fn = PARENT_HTML[PARENT_HTML.index("async function loadLinks(box)"):PARENT_HTML.index("function renderAthlete(a)")]
        assert "catch { box.innerHTML = ''; return; }" in fn

    def test_it_is_the_athlete_in_the_other_program_that_is_named_not_an_id(self):
        fn = PARENT_HTML[PARENT_HTML.index("async function loadLinks(box)"):PARENT_HTML.index("function renderAthlete(a)")]
        assert "esc(c.display_name)" in fn and "esc(c.org_name)" in fn


class TestTheAthletePage:
    def test_it_says_which_programs_the_work_counts_for_only_when_there_is_more_than_one(self):
        assert 'id="counts-for"' in CAPTURE_HTML
        block = CAPTURE_HTML[CAPTURE_HTML.index("const cf = profile.counts_for"):CAPTURE_HTML.index("$('level-pill')")]
        assert "Your work counts for ${cf.join(' and ')}." in block
        assert "classList.toggle('hidden', cf.length < 2)" in block

    def test_the_line_is_hidden_until_there_is_something_to_say(self):
        assert 'class="small muted hidden" id="counts-for"' in CAPTURE_HTML

    def test_the_saved_pages_on_phones_are_replaced(self):
        sw = (_STATIC / "sw.js").read_text(encoding="utf-8")
        assert "offdays-shell-v30" in sw


class TestSelfReportedWorkCountsToo:
    def test_a_session_an_athlete_logged_because_the_camera_could_not_count_it_is_copied_as_such(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        store = api_module._store
        director = db().execute("SELECT id FROM users WHERE role = 'director' AND org_id = ?", (a["club"]["org_id"],)).fetchone()[0]
        store.set_adaptive_profile(a["kid"], ["self_report"], set_by=director, set_by_name="Coach")
        out = store.log_self_reported(a["kid"], "gen_squat", minutes=20)
        assert out["self_reported"] is True
        copy = sessions_of(b["kid"])
        assert len(copy) == 1 and copy[0]["self_reported"] == 1 and copy[0]["mirrored_from"] == out["session_id"]
        assert xp_of(b["kid"]) == xp_of(a["kid"]) > 0


class TestGuardsThatNothingElseCovers:
    def test_a_parent_cannot_link_a_child_that_is_not_theirs_to_their_own(self, client):
        """P is a parent in clubs B and C (same address). They name a stranger's child in club A, not theirs.
        P's own child in C would otherwise be offered as the 'other' record. Only the guardianship check stops it."""
        stranger = family(client, club(client, "Club A"), name="Sam Hill", roster_email="hill@example.com")
        p_b = family(client, club(client, "Club B"), name="Ryder Kallberg")
        p_c = family(client, club(client, "Club C"), name="Ryder Kallberg")
        res = client.post(f"/api/guardians/links/{stranger['kid']}", headers=p_b["p"], json={"other_id": p_c["kid"]})
        assert res.status_code in (400, 403)
        assert linked.group_of(db(), stranger["kid"]) is None and linked.group_of(db(), p_c["kid"]) is None
        with pytest.raises(Exception):
            linked.candidates(db(), p_b["parent_id"], stranger["kid"])

    def test_two_existing_groups_become_one_when_a_parent_joins_them(self, client):
        a, b = two_clubs(client)
        c = family(client, club(client, "Club C"), roster_email="other.parent@example.com")
        d = family(client, club(client, "Club D"), roster_email="other.parent@example.com")
        link_them(client, a, b)
        link_them(client, c, d)
        assert linked.group_of(db(), a["kid"]) != linked.group_of(db(), c["kid"])
        # one parent in A and C (two addresses on the roster) joins the groups
        db().execute("INSERT INTO guardian_contacts(org_id, athlete_id, guardian_id, name, email, phone, relationship, source, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (c["club"]["org_id"], c["kid"], c["parent_id"], "K", EMAIL, "", "parent", "roster", "2026-01-01", "2026-01-01"))
        db().commit()
        assert {x["athlete_id"] for x in client.get(f"/api/guardians/links/{c['kid']}", headers=c["p"]).json()["candidates"]} == {a["kid"], b["kid"]}
        assert link_them(client, c, a).status_code == 201
        groups = {linked.group_of(db(), k["kid"]) for k in (a, b, c, d)}
        assert len(groups) == 1
        assert sorted(linked.members(db(), a["kid"])) == sorted([b["kid"], c["kid"], d["kid"]])

    def test_asking_to_copy_a_session_that_is_not_counted_copies_nothing(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        res, sid = train(client, a, count=99, gap=800, hold=True)
        assert sessions_of(a["kid"])[0]["status"] == "review"
        assert linked.mirror_session(db(), sid) == []
        assert sessions_of(b["kid"]) == []

    def test_an_athlete_who_has_left_the_other_program_is_not_one_of_the_members(self, client):
        a, b = two_clubs(client)
        link_them(client, a, b)
        assert linked.members(db(), a["kid"]) == [b["kid"]]
        db().execute("UPDATE users SET active = 0 WHERE id = ?", (b["kid"],))
        db().commit()
        assert linked.members(db(), a["kid"]) == []
        assert linked.programs(db(), a["kid"]) == []


class TestARemovedParentIsNotTheSamePerson:
    def test_a_parent_account_that_has_been_removed_is_not_offered_as_a_match(self, client):
        a, b = two_clubs(client)
        assert client.get(f"/api/guardians/links/{a['kid']}", headers=a["p"]).json()["candidates"]
        db().execute("UPDATE users SET active = 0 WHERE id = ?", (b["parent_id"],))
        db().commit()
        assert client.get(f"/api/guardians/links/{a['kid']}", headers=a["p"]).json()["candidates"] == []
