"""The program's drill library.

Two features on one screen, and both have a line they must not cross.

Curation is the easy one: a coach decides which of the catalog's drills their
athletes are offered. The only subtlety is that the default must stay the
default -- a club that never opens this screen has no rows in the table and
sees exactly what it saw before the feature existed.

Coach-written drills are the one with the line. The counter reads a pose
signal against thresholds somebody tuned on real video, so no name a coach
types can teach it a movement. A custom drill therefore *borrows* one, and the
coach is told which. The tempting alternative -- a free-text drill the athlete
self-certifies -- would make an uncounted drill the cheapest route to a
streak, and the integrity layer exists precisely to stop that. It stays gated
per athlete behind an accommodation, where it was.
"""
from __future__ import annotations

import pytest

from offdays import library
from offdays.db import connect
from offdays.drills import DRILLS_BY_KEY
from offdays.drills.catalog import for_sport
from offdays.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "lib.db"))


@pytest.fixture
def club(store):
    org = store.create_org("Tennessee Soccer Club", sport="soccer")
    coach = store.create_user(org, "coach", "Coach Bryan")
    team = store.create_team(org, "2031 Blue", "2026", age_group="2031")
    athlete = store.create_user(
        org, "athlete", "Kid", birth_year=2013, dominant_hand="right")
    store.join_team(team["join_code"], athlete["id"])
    return {"org": org, "coach": coach, "athlete": athlete["id"], "sport": "soccer"}


class TestTheDefaultStaysTheDefault:
    def test_a_club_that_changes_nothing_sees_the_catalog_default(self, store, club):
        offered = library.offered(store.conn, club["org"], "soccer")
        assert [d.key for d in offered] == [d.key for d in for_sport("soccer")]

    def test_touching_nothing_writes_no_rows(self, store, club):
        library.offered(store.conn, club["org"], "soccer")
        n = store.conn.execute("SELECT COUNT(*) FROM org_drill_prefs").fetchone()[0]
        assert n == 0

    def test_turning_something_off_and_on_again_leaves_no_trace(self, store, club):
        """Otherwise the table fills with rows that say "same as default", and
        a later change to the default silently fails to reach the club."""
        library.set_offered(store.conn, club["org"], "soc_juggle", False, "soccer")
        library.set_offered(store.conn, club["org"], "soc_juggle", True, "soccer")
        n = store.conn.execute("SELECT COUNT(*) FROM org_drill_prefs").fetchone()[0]
        assert n == 0


class TestCuration:
    def test_a_coach_can_turn_a_drill_off(self, store, club):
        before = len(library.offered(store.conn, club["org"], "soccer"))
        library.set_offered(store.conn, club["org"], "soc_juggle", False, "soccer")
        after = library.offered(store.conn, club["org"], "soccer")
        assert len(after) == before - 1
        assert "soc_juggle" not in {d.key for d in after}

    def test_a_coach_can_reach_across_sports(self, store, club):
        """The other half of the point. A soccer club that wants the
        basketball defensive slide should be able to have it."""
        library.set_offered(store.conn, club["org"], "bkb_slide", True, "soccer")
        assert "bkb_slide" in {
            d.key for d in library.offered(store.conn, club["org"], "soccer")}

    def test_one_club_s_choices_do_not_reach_another(self, store):
        a = store.create_org("Club A", sport="soccer")
        b = store.create_org("Club B", sport="soccer")
        library.set_offered(store.conn, a, "soc_juggle", False, "soccer")
        assert "soc_juggle" not in {d.key for d in library.offered(store.conn, a, "soccer")}
        assert "soc_juggle" in {d.key for d in library.offered(store.conn, b, "soccer")}

    def test_the_shelf_shows_the_whole_catalog_not_just_this_sport(self, store, club):
        """A coach cannot ask for a drill they have never been shown."""
        shelf = library.shelf(store.conn, club["org"], "soccer")
        assert len(shelf) == len(DRILLS_BY_KEY) - len(library.CUSTOM)
        assert any(r["sport"] == "basketball" for r in shelf)

    def test_the_shelf_says_why_a_row_looks_the_way_it_does(self, store, club):
        library.set_offered(store.conn, club["org"], "soc_juggle", False, "soccer")
        library.set_offered(store.conn, club["org"], "bkb_slide", True, "soccer")
        by_key = {r["key"]: r for r in library.shelf(store.conn, club["org"], "soccer")}
        assert by_key["soc_juggle"]["state"] == "hidden"
        assert by_key["bkb_slide"]["state"] == "added"
        assert by_key["soc_wall_pass"]["state"] == "default"
        assert by_key["bkb_crossover"]["state"] == "off"

    def test_an_unknown_drill_is_refused(self, store, club):
        with pytest.raises(library.LibraryError):
            library.set_offered(store.conn, club["org"], "nope", True, "soccer")


class TestACoachsOwnDrill:
    def test_it_borrows_a_movement_and_becomes_a_real_spec(self, store, club):
        spec = library.create(
            store.conn, club["org"], name="Keeper Reaction Squats",
            based_on="gen_squat", description="Ten squats, then set and drive.")
        base = DRILLS_BY_KEY["gen_squat"]
        assert spec.name == "Keeper Reaction Squats"
        assert spec.signal == base.signal
        assert spec.counter == base.counter
        assert spec.scoring == base.scoring

    def test_it_resolves_by_key_like_any_other_drill(self, store, club):
        """Thirty-five places look a drill up by key and expect a spec. A
        parallel type would have needed all of them to learn a second kind."""
        spec = library.create(store.conn, club["org"], name="Wall Work",
                              based_on="gen_squat")
        assert DRILLS_BY_KEY[spec.key] is not None
        assert DRILLS_BY_KEY[spec.key].name == "Wall Work"

    def test_an_athlete_can_record_a_session_against_it(self, store, club):
        spec = library.create(store.conn, club["org"], name="Reaction Squats",
                              based_on="gen_squat")
        started = store.start_session(club["athlete"], spec.key)
        assert "nonce" in started

    def test_it_appears_in_what_the_program_offers(self, store, club):
        spec = library.create(store.conn, club["org"], name="Reaction Squats",
                              based_on="gen_squat")
        assert spec.key in {d.key for d in library.offered(store.conn, club["org"], "soccer")}

    def test_it_keeps_its_own_key_so_the_coach_can_see_their_own_drill(self, store, club):
        """Counted as squats, reported as itself. Blurring it into the
        movement would leave a coach unable to see whether the thing they
        invented is being done."""
        spec = library.create(store.conn, club["org"], name="Reaction Squats",
                              based_on="gen_squat")
        assert spec.key != "gen_squat"
        assert spec.key.startswith(f"org{club['org']}_")

    def test_two_clubs_can_both_have_a_wall_work(self, store):
        a = store.create_org("Club A", sport="soccer")
        b = store.create_org("Club B", sport="lacrosse")
        ka = library.create(store.conn, a, name="Wall Work", based_on="gen_squat").key
        kb = library.create(store.conn, b, name="Wall Work", based_on="gen_squat").key
        assert ka != kb

    def test_a_name_already_used_in_this_club_is_refused(self, store, club):
        library.create(store.conn, club["org"], name="Wall Work", based_on="gen_squat")
        with pytest.raises(library.LibraryError, match="already has a drill"):
            library.create(store.conn, club["org"], name="Wall Work", based_on="gen_squat")

    def test_a_custom_drill_cannot_borrow_a_custom_drill(self, store, club):
        """Otherwise what is actually being counted sits three hops from
        anything anybody calibrated."""
        spec = library.create(store.conn, club["org"], name="Wall Work",
                              based_on="gen_squat")
        with pytest.raises(library.LibraryError, match="catalog movement"):
            library.create(store.conn, club["org"], name="Wall Work Two",
                           based_on=spec.key)

    def test_an_unknown_movement_is_refused(self, store, club):
        with pytest.raises(library.LibraryError, match="unknown movement"):
            library.create(store.conn, club["org"], name="Mystery",
                           based_on="does_not_exist")

    def test_a_nameless_drill_is_refused(self, store, club):
        for bad in ("", " ", "x", "!!!"):
            with pytest.raises(library.LibraryError):
                library.create(store.conn, club["org"], name=bad, based_on="gen_squat")

    def test_there_is_a_ceiling_on_how_many(self, store, club):
        """Not a licensing lever. A picker with two hundred entries is a
        picker nobody reads, which is the opposite of curation."""
        for i in range(library.MAX_PER_ORG):
            library.create(store.conn, club["org"], name=f"Drill {i}",
                           based_on="gen_squat")
        with pytest.raises(library.LibraryError, match="as many as a picker"):
            library.create(store.conn, club["org"], name="One More",
                           based_on="gen_squat")


class TestRetiring:
    def test_a_retired_drill_leaves_the_list(self, store, club):
        spec = library.create(store.conn, club["org"], name="Wall Work",
                              based_on="gen_squat")
        library.retire(store.conn, club["org"], spec.key)
        assert spec.key not in {
            d.key for d in library.offered(store.conn, club["org"], "soccer")}

    def test_a_retired_drill_still_resolves_for_old_sessions(self, store, club):
        """Otherwise an athlete's history develops a hole where their work
        used to be, on a day their coach tidied up."""
        spec = library.create(store.conn, club["org"], name="Wall Work",
                              based_on="gen_squat")
        library.retire(store.conn, club["org"], spec.key)
        assert DRILLS_BY_KEY[spec.key].name == "Wall Work"

    def test_another_club_cannot_retire_your_drill(self, store, club):
        other = store.create_org("Somebody Else", sport="soccer")
        spec = library.create(store.conn, club["org"], name="Wall Work",
                              based_on="gen_squat")
        with pytest.raises(library.LibraryError):
            library.retire(store.conn, other, spec.key)


class TestItSurvivesARestart:
    def test_custom_drills_resolve_after_reopening_the_database(self, tmp_path):
        path = tmp_path / "reopen.db"
        first = Store(connect(path))
        org = first.create_org("TSC", sport="soccer")
        key = library.create(first.conn, org, name="Reaction Squats",
                             based_on="gen_squat").key
        library.CUSTOM.pop(key, None)
        DRILLS_BY_KEY.pop(key, None)

        Store(connect(path))  # a fresh process would do exactly this
        assert key in DRILLS_BY_KEY
        assert DRILLS_BY_KEY[key].name == "Reaction Squats"


class TestOverTheWire:
    @pytest.fixture
    def wired(self, store, club):
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient
        import offdays.api as api_module
        api_module._store = store
        yield {
            "client": TestClient(api_module.app),
            "coach": {"Authorization": f"Bearer {club['coach']['token']}"},
            "club": club,
        }
        api_module._store = None

    def test_a_coach_sees_the_whole_library(self, wired):
        body = wired["client"].get("/api/coach/library", headers=wired["coach"]).json()
        assert body["sport"] == "soccer"
        assert len(body["drills"]) > 90
        assert body["movements"], "a coach needs something to borrow from"

    def test_a_coach_can_turn_a_drill_off_over_the_wire(self, wired):
        c, h = wired["client"], wired["coach"]
        assert c.post("/api/coach/library/soc_juggle",
                      json={"offered": False}, headers=h).status_code == 200
        shelf = {r["key"]: r for r in c.get("/api/coach/library", headers=h).json()["drills"]}
        assert shelf["soc_juggle"]["offered"] is False

    def test_creating_one_says_what_it_will_be_counted_as(self, wired):
        """A coach told afterwards feels misled. Told now, they can pick a
        closer movement."""
        r = wired["client"].post("/api/coach/drills", headers=wired["coach"], json={
            "name": "Keeper Reaction Squats", "based_on": "gen_squat"})
        assert r.status_code == 201
        assert r.json()["counted_as"]["name"] == "Bodyweight Squats"

    def test_an_athlete_is_not_allowed_to_curate_the_library(self, wired, store, club):
        athlete_token = store.conn.execute(
            "SELECT display_name FROM users WHERE id = ?", (club["athlete"],)).fetchone()
        assert athlete_token is not None
        r = wired["client"].get("/api/coach/library")
        assert r.status_code in (401, 403)
