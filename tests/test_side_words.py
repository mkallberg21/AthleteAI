"""What a program calls its weaker side.

Every bilateral drill measures the same two numbers, reps on the left and reps
on the right, and which of those is the hard one is a fact about the athlete
rather than about the sport. The *word* is a fact about the sport, and it is
the one a club notices immediately: no coach has ever asked a midfielder about
their off-hand, and a soccer club reading "Off-hand" on its own leaderboard has
been told, in one column heading, that this is a lacrosse product with the
names swapped.

Three badges had the same problem in a worse form. "Century", "Four Digits"
and "Ten Thousand" counted lacrosse wall ball and nothing else, so three of the
fourteen badges were permanently unreachable for the other ten sports in the
library. An athlete could see them and never earn one.
"""
from __future__ import annotations

import pytest

from offdays import sports
from offdays.db import connect
from offdays.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "s.db"))


def program(store, sport):
    org = store.create_org(f"{sport.title()} Club", sport=sport)
    team = store.create_team(org, "2031 Red", "2026", age_group="2031")
    athlete = store.create_user(
        org, "athlete", "Kid", birth_year=2013, dominant_hand="right")
    store.join_team(team["join_code"], athlete["id"])
    return org, athlete["id"]


class TestTheWordFollowsTheSport:
    def test_a_foot_sport_says_foot(self):
        w = sports.side_words("soccer")
        assert w.noun == "foot"
        assert w.label == "Weak foot"
        assert w.both == "Both Feet"

    def test_everything_else_says_hand(self):
        for sport in ("lacrosse", "basketball", "baseball", "tennis", "hockey"):
            assert sports.side_words(sport).noun == "hand", sport

    def test_it_reads_free_text_the_way_the_rest_of_the_app_does(self):
        """Callers hold whatever is on the organizations row, not a clean key."""
        assert sports.side_words("Futbol").noun == "foot"
        assert sports.side_words("football uk").noun == "foot"

    def test_an_unknown_or_missing_sport_falls_back_to_hands(self):
        """The safe direction. A wrong "off-hand" on a foot sport reads as an
        odd word; a wrong "weak foot" on a throwing sport reads as a bug."""
        for value in (None, "", "quidditch"):
            assert sports.side_words(value).noun == "hand"


class TestTheAthleteSeesTheirOwnSportsWord:
    def test_a_soccer_badge_says_feet(self, store):
        _org, athlete = program(store, "soccer")
        store.conn.execute(
            "INSERT INTO badges(athlete_id, badge_key, awarded_at) VALUES (?,?,?)",
            (athlete, "ambidextrous", "2026-01-01T00:00:00Z"))
        store.conn.commit()
        badge = store.athlete_profile(athlete)["badges"][0]
        assert badge["name"] == "Both Feet"
        assert "foot" in badge["description"]
        assert "hand" not in badge["description"]

    def test_a_lacrosse_badge_still_says_hands(self, store):
        _org, athlete = program(store, "lacrosse")
        store.conn.execute(
            "INSERT INTO badges(athlete_id, badge_key, awarded_at) VALUES (?,?,?)",
            (athlete, "ambidextrous", "2026-01-01T00:00:00Z"))
        store.conn.commit()
        badge = store.athlete_profile(athlete)["badges"][0]
        assert badge["name"] == "Both Hands"
        assert "hand" in badge["description"]

    def test_no_badge_description_is_left_holding_a_placeholder(self, store):
        """Every {weaker} and {label} has to be filled, or an athlete reads
        raw template syntax on their own profile."""
        _org, athlete = program(store, "soccer")
        from offdays.scoring import BADGES
        for spec in BADGES:
            store.conn.execute(
                "INSERT OR IGNORE INTO badges(athlete_id, badge_key, awarded_at) "
                "VALUES (?,?,?)", (athlete, spec.key, "2026-01-01T00:00:00Z"))
        store.conn.commit()
        for badge in store.athlete_profile(athlete)["badges"]:
            assert "{" not in badge["description"], badge["key"]
            assert "}" not in badge["description"], badge["key"]


class TestTheSkillBadgesAreReachableInEverySport:
    def test_a_soccer_athlete_can_earn_the_skill_badges(self, store):
        """The regression. These counted lacrosse wall ball, so this athlete
        could train every day for a season and never move them."""
        _org, athlete = program(store, "soccer")
        store.conn.execute(
            "INSERT INTO sessions(athlete_id, drill_key, nonce, started_at, "
            "status, reps_total) VALUES (?,?,?,?,'counted',?)",
            (athlete, "soc_juggle", "n1", "2026-01-01T00:00:00Z", 150))
        store.conn.commit()
        assert store.athlete_profile(athlete)["stats"]["skill_reps"] == 150

    def test_general_work_does_not_count_toward_them(self, store):
        """Push-ups are nobody's sport. A badge every athlete earns by doing
        squats says nothing about their skill work."""
        _org, athlete = program(store, "soccer")
        store.conn.execute(
            "INSERT INTO sessions(athlete_id, drill_key, nonce, started_at, "
            "status, reps_total) VALUES (?,?,?,?,'counted',?)",
            (athlete, "gen_squat", "n2", "2026-01-01T00:00:00Z", 500))
        store.conn.commit()
        assert store.athlete_profile(athlete)["stats"]["skill_reps"] == 0

    def test_another_sports_drills_do_not_count_either(self, store):
        _org, athlete = program(store, "soccer")
        store.conn.execute(
            "INSERT INTO sessions(athlete_id, drill_key, nonce, started_at, "
            "status, reps_total) VALUES (?,?,?,?,'counted',?)",
            (athlete, "lax_wall_ball", "n3", "2026-01-01T00:00:00Z", 900))
        store.conn.commit()
        assert store.athlete_profile(athlete)["stats"]["skill_reps"] == 0


class TestThePagesAreToldTheWord:
    def test_the_api_sends_it_to_an_athlete(self, tmp_path, store):
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient
        import offdays.api as api_module

        org = store.create_org("Tennessee Soccer Club", sport="soccer")
        team = store.create_team(org, "2031 Blue", "2026", age_group="2031")
        kid = store.create_user(
            org, "athlete", "Kid", birth_year=2013, dominant_hand="right")
        store.join_team(team["join_code"], kid["id"])

        api_module._store = store
        try:
            client = TestClient(api_module.app)
            body = client.get(
                "/api/me", headers={"Authorization": f"Bearer {kid['token']}"}).json()
            assert body["side"]["label"] == "Weak foot"
            assert body["side"]["both"] == "Both Feet"
        finally:
            api_module._store = None
