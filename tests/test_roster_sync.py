"""Keeping a roster in step with wherever it actually lives.

A CSV upload is a snapshot, and the friction that kills a pilot is not the
first import -- it is week three, when two players join and nobody remembers
to re-export. So a team can be wired to the system its roster already lives
in.

Two things are load-bearing here and get most of the tests.

The credential reaches back into a system holding children's contact details,
so it is write-only above the store: it goes in, the sync uses it, and no
dashboard, API response, or log can read it back.

And departures are reported, never applied. A child missing from a remote
roster is the one event continuous sync introduces that a one-off import never
had, and the tempting thing to do with it is delete. A wrong team id and a
real mass exodus are indistinguishable from here, so a big enough drop refuses
outright rather than reporting something a coach might act on.

The TeamSnap and SportsEngine adapters are written against published API
shapes and have never been run against a live account -- there are no
credentials in this environment. They say so in `verified`, and the tests
below assert they keep saying so rather than quietly claiming otherwise.
"""
from __future__ import annotations

import json

import pytest

from offdays import roster_sync
from offdays.db import connect
from offdays.store import Store, StoreError

SECRET = "tok-do-not-leak-9f3c"


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "s.db"))


@pytest.fixture
def program(store):
    org = store.create_org("Northshore")
    director = store.create_user(org, "director", "Coach Ada")
    team = store.create_team(org, "U15 Boys")
    return {"org": org, "director": director, "team": team}


@pytest.fixture
def remote():
    """A stand-in for a provider, so the plumbing is exercised offline.

    The list is mutable so a test can add or drop a player between syncs,
    which is the whole point of the feature.
    """
    rows = [
        {"first_name": "Jordan", "last_name": "Pierce", "jersey": "7",
         "birth_date": "2011-04-02"},
        {"first_name": "Sam", "last_name": "Reyes", "jersey": "12",
         "birth_date": "2011-09-14"},
        {"first_name": "Alex", "last_name": "Okafor", "jersey": "3",
         "birth_date": "2010-12-01"},
    ]
    seen = {}

    def fetch(token, ref):
        seen["token"], seen["ref"] = token, ref
        return list(rows)

    roster_sync.BY_KEY["stub"] = roster_sync.Provider(
        key="stub", label="Stub League", credential_label="Token",
        team_field="Team ID", help_url="", fetch=fetch, verified=True,
    )
    yield {"rows": rows, "seen": seen}
    roster_sync.BY_KEY.pop("stub", None)


def link(store, program, ref="team-99"):
    return store.link_roster(
        program["org"], program["team"]["id"], "stub", SECRET, ref,
        program["director"]["id"],
    )


class TestTheCredentialNeverComesBack:
    def test_the_token_is_absent_from_everything_the_store_returns(
        self, store, program, remote
    ):
        link(store, program)
        surface = json.dumps([
            store.roster_link(program["team"]["id"], "stub"),
            store.roster_links(program["org"]),
            store.sync_roster(program["org"], program["team"]["id"], "stub"),
        ])
        assert SECRET not in surface

    def test_a_coach_can_still_tell_whether_one_is_set(self, store, program, remote):
        link(store, program)
        assert store.roster_link(program["team"]["id"], "stub")["has_token"] is True

    def test_it_does_reach_the_provider(self, store, program, remote):
        link(store, program, ref="team-42")
        store.sync_roster(program["org"], program["team"]["id"], "stub")
        assert remote["seen"]["token"] == SECRET
        assert remote["seen"]["ref"] == "team-42"

    def test_the_stored_run_record_carries_no_credential(self, store, program, remote):
        link(store, program)
        store.sync_roster(program["org"], program["team"]["id"], "stub")
        row = store.conn.execute(
            "SELECT last_result FROM roster_links WHERE team_id = ?",
            (program["team"]["id"],),
        ).fetchone()
        assert SECRET not in row["last_result"]


class TestNothingWritesUntilSomebodyHasLooked:
    def test_a_new_link_does_not_sync_on_its_own(self, store, program, remote):
        assert link(store, program)["auto_sync"] is False

    def test_a_dry_run_changes_no_roster(self, store, program, remote):
        link(store, program)
        result = store.sync_roster(program["org"], program["team"]["id"], "stub")
        assert result["created"] == 3 and result["dry_run"] is True
        assert self.roster_size(store, program) == 0

    def test_applying_creates_the_athletes(self, store, program, remote):
        link(store, program)
        result = store.sync_roster(
            program["org"], program["team"]["id"], "stub",
            dry_run=False, actor_id=program["director"]["id"],
        )
        assert result["created"] == 3
        assert self.roster_size(store, program) == 3

    def test_running_twice_does_not_duplicate_anybody(self, store, program, remote):
        link(store, program)
        for _ in range(2):
            store.sync_roster(
                program["org"], program["team"]["id"], "stub",
                dry_run=False, actor_id=program["director"]["id"],
            )
        assert self.roster_size(store, program) == 3

    def test_a_player_who_joins_midseason_is_picked_up(self, store, program, remote):
        link(store, program)
        store.sync_roster(program["org"], program["team"]["id"], "stub",
                          dry_run=False, actor_id=program["director"]["id"])
        remote["rows"].append(
            {"first_name": "Robin", "last_name": "Hale", "jersey": "21",
             "birth_date": "2011-02-20"}
        )
        result = store.sync_roster(
            program["org"], program["team"]["id"], "stub",
            dry_run=False, actor_id=program["director"]["id"],
        )
        assert result["created"] == 1
        assert self.roster_size(store, program) == 4

    @staticmethod
    def roster_size(store, program):
        return store.conn.execute(
            "SELECT COUNT(*) AS n FROM team_members WHERE team_id = ?",
            (program["team"]["id"],),
        ).fetchone()["n"]


class TestDeparturesAreReportedNotApplied:
    def test_somebody_dropping_off_their_roster_is_named(self, store, program, remote):
        link(store, program)
        store.sync_roster(program["org"], program["team"]["id"], "stub",
                          dry_run=False, actor_id=program["director"]["id"])
        remote["rows"].pop()
        result = store.sync_roster(
            program["org"], program["team"]["id"], "stub",
            dry_run=False, actor_id=program["director"]["id"],
        )
        assert [d["display_name"] for d in result["departures"]] == ["Alex Okafor"]

    def test_but_they_stay_on_ours(self, store, program, remote):
        """Leaving a team-management app is not leaving a program, and it is
        certainly not a coach's decision made by a nightly job."""
        link(store, program)
        store.sync_roster(program["org"], program["team"]["id"], "stub",
                          dry_run=False, actor_id=program["director"]["id"])
        remote["rows"].pop()
        store.sync_roster(program["org"], program["team"]["id"], "stub",
                          dry_run=False, actor_id=program["director"]["id"])
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM team_members WHERE team_id = ?",
            (program["team"]["id"],),
        ).fetchone()["n"] == 3

    def test_an_implausible_exodus_refuses_rather_than_reports(
        self, store, program, remote
    ):
        """A wrong team id looks exactly like everyone quitting. Refusing is
        recoverable; a coach acting on a false report is not."""
        link(store, program)
        store.sync_roster(program["org"], program["team"]["id"], "stub",
                          dry_run=False, actor_id=program["director"]["id"])
        del remote["rows"][1:]
        result = store.sync_roster(program["org"], program["team"]["id"], "stub")
        assert "wrong team id" in result["error"]
        assert result["ok"] is False

    def test_an_empty_roster_is_treated_as_a_mistake(self, store, program, remote):
        link(store, program)
        remote["rows"].clear()
        result = store.sync_roster(program["org"], program["team"]["id"], "stub")
        assert result["ok"] is False
        assert "empty" in result["error"]


class TestFailuresAreLegible:
    def test_a_provider_error_is_recorded_not_raised(self, store, program, remote):
        def angry(token, ref):
            raise roster_sync.SyncError("They rejected the token.")

        roster_sync.BY_KEY["stub"] = roster_sync.Provider(
            key="stub", label="Stub League", credential_label="Token",
            team_field="Team ID", help_url="", fetch=angry, verified=True,
        )
        link(store, program)
        result = store.sync_roster(program["org"], program["team"]["id"], "stub")
        assert result["error"] == "They rejected the token."
        assert store.roster_link(program["team"]["id"], "stub")["last_run_at"]

    def test_an_unknown_provider_is_refused_at_link_time(self, store, program):
        with pytest.raises(StoreError, match="unknown roster provider"):
            store.link_roster(program["org"], program["team"]["id"], "nope",
                              SECRET, "x", program["director"]["id"])

    def test_a_team_from_another_program_is_refused(self, store, program, remote):
        other = store.create_org("Southside")
        theirs = store.create_team(other, "Their Team")
        with pytest.raises(StoreError, match="no such team"):
            store.link_roster(program["org"], theirs["id"], "stub", SECRET, "x")


class TestScheduling:
    def test_only_links_with_auto_sync_on_come_due(self, store, program, remote):
        link(store, program)
        assert store.due_roster_syncs() == []
        store.set_roster_auto_sync(program["org"], program["team"]["id"], "stub", True)
        assert store.due_roster_syncs() == [
            (program["org"], program["team"]["id"], "stub")
        ]

    def test_a_link_that_just_ran_is_not_due_again(self, store, program, remote):
        link(store, program)
        store.set_roster_auto_sync(program["org"], program["team"]["id"], "stub", True)
        store.sync_roster(program["org"], program["team"]["id"], "stub")
        assert store.due_roster_syncs() == []


class TestTheShippedAdapters:
    def test_teamsnap_and_sportsengine_are_present(self):
        assert {"teamsnap", "sportsengine"} <= set(roster_sync.BY_KEY)

    def test_any_platform_with_an_export_link_is_covered(self):
        """The named two are the common cases, not the only ones. A league
        product nobody here has heard of still works if it can produce a CSV
        at a URL, and that path is the one we can actually vouch for."""
        assert roster_sync.BY_KEY["csv_url"].verified is True

    @pytest.mark.parametrize("key", ["teamsnap", "sportsengine"])
    def test_untested_adapters_say_so(self, key):
        """Written from published docs, never run against a real account.
        Claiming otherwise would be the one failure a coach cannot check."""
        provider = roster_sync.BY_KEY[key]
        assert provider.verified is False
        assert "dry run" in provider.note

    def test_rows_round_trip_through_the_same_parser_as_an_upload(self):
        """Synced and uploaded rosters must not be two code paths -- the
        import parser is the forgiving, well-tested one, so the sync feeds it
        rather than reimplementing it."""
        from offdays import roster as roster_mod

        csv = roster_sync.rows_to_csv([
            {"first_name": "Jordan", "last_name": "Pierce", "jersey": "7"},
            {"first_name": "Sam", "last_name": "Reyes", "position": "Midfield"},
        ])
        plan = roster_mod.parse(csv)
        assert [a.display_name for a in plan.athletes] == ["Jordan Pierce", "Sam Reyes"]

    def test_fetching_refuses_a_plaintext_url(self):
        """The credential and a roster of children's names travel over this."""
        with pytest.raises(roster_sync.SyncError, match="https"):
            roster_sync._get("http://example.com/roster.csv")


# ---------------------------------------------------------------------------
# Over the wire
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFDAYS_DB", str(tmp_path / "api.db"))
    from offdays import api

    api.app.dependency_overrides.clear()
    return TestClient(api.app)


@pytest.fixture
def wired(client, remote):
    org = client.post(
        "/api/orgs", json={"name": "Northshore LC", "director_name": "Dir Smith"}
    ).json()
    director = {"Authorization": f"Bearer {org['director']['token']}"}
    team = client.post(
        "/api/teams", json={"name": "U15 Boys", "season": "2026"}, headers=director
    ).json()
    return {"director": director, "team": team, "remote": remote}


class TestOverTheWire:
    def test_connecting_previews_before_it_writes(self, client, wired):
        res = client.post(
            "/api/coach/roster/link",
            json={"team_id": wired["team"]["id"], "provider": "stub",
                  "token": SECRET, "remote_ref": "team-99"},
            headers=wired["director"],
        )
        assert res.status_code == 201
        body = res.json()
        assert body["preview"]["dry_run"] is True
        assert body["preview"]["created"] == 3
        assert client.get(
            "/api/coach/roster", headers=wired["director"]
        ).json()["athletes"] == []

    def test_no_response_ever_contains_the_credential(self, client, wired):
        client.post(
            "/api/coach/roster/link",
            json={"team_id": wired["team"]["id"], "provider": "stub",
                  "token": SECRET, "remote_ref": "team-99"},
            headers=wired["director"],
        )
        for path in ("/api/coach/roster/links", "/api/coach/roster/providers"):
            assert SECRET not in client.get(path, headers=wired["director"]).text
        assert SECRET not in client.post(
            "/api/coach/roster/sync",
            json={"team_id": wired["team"]["id"], "provider": "stub", "apply": True},
            headers=wired["director"],
        ).text

    def test_auto_sync_is_allowed_once_a_run_has_worked(self, client, wired):
        client.post(
            "/api/coach/roster/link",
            json={"team_id": wired["team"]["id"], "provider": "stub",
                  "token": SECRET, "remote_ref": "team-99"},
            headers=wired["director"],
        )
        assert client.post(
            "/api/coach/roster/auto-sync",
            json={"team_id": wired["team"]["id"], "provider": "stub", "on": True},
            headers=wired["director"],
        ).status_code == 200

    def test_a_connection_that_failed_cannot_be_put_on_a_schedule(
        self, client, wired
    ):
        """A wrong team id is the common first mistake, and putting one on a
        nightly schedule is how it stops being noticed."""
        wired["remote"]["rows"].clear()          # as a wrong team id looks
        client.post(
            "/api/coach/roster/link",
            json={"team_id": wired["team"]["id"], "provider": "stub",
                  "token": SECRET, "remote_ref": "wrong-team"},
            headers=wired["director"],
        )
        res = client.post(
            "/api/coach/roster/auto-sync",
            json={"team_id": wired["team"]["id"], "provider": "stub", "on": True},
            headers=wired["director"],
        )
        assert res.status_code == 400
        assert "did not succeed" in res.json()["detail"]

    def test_an_athlete_cannot_reach_any_of_it(self, client, wired):
        team = wired["team"]
        athlete = client.post(
            "/api/athletes",
            json={"display_name": "Jordan P.", "birth_year": 2011,
                  "dominant_hand": "right", "guardian_consent": True,
                  "join_code": team["join_code"]},
            headers=wired["director"],
        ).json()
        headers = {"Authorization": f"Bearer {athlete['token']}"}
        assert client.get("/api/coach/roster/links", headers=headers).status_code == 403
        assert client.post(
            "/api/coach/roster/link",
            json={"team_id": team["id"], "provider": "stub",
                  "token": SECRET, "remote_ref": "x"},
            headers=headers,
        ).status_code == 403

    def test_another_program_cannot_sync_your_team(self, client, wired):
        other = client.post(
            "/api/orgs", json={"name": "Southside", "director_name": "Other Dir"}
        ).json()
        headers = {"Authorization": f"Bearer {other['director']['token']}"}
        res = client.post(
            "/api/coach/roster/link",
            json={"team_id": wired["team"]["id"], "provider": "stub",
                  "token": SECRET, "remote_ref": "x"},
            headers=headers,
        )
        assert res.status_code == 400
        assert res.json()["detail"] == "no such team in this program"
        # And the sync endpoint is not a way around the link endpoint.
        assert client.post(
            "/api/coach/roster/sync",
            json={"team_id": wired["team"]["id"], "provider": "stub",
                  "apply": True},
            headers=headers,
        ).status_code == 400

    def test_disconnecting_keeps_the_athletes(self, client, wired):
        team = wired["team"]
        client.post(
            "/api/coach/roster/link",
            json={"team_id": team["id"], "provider": "stub",
                  "token": SECRET, "remote_ref": "team-99"},
            headers=wired["director"],
        )
        client.post(
            "/api/coach/roster/sync",
            json={"team_id": team["id"], "provider": "stub", "apply": True},
            headers=wired["director"],
        )
        assert client.delete(
            f"/api/coach/roster/link?team_id={team['id']}&provider=stub",
            headers=wired["director"],
        ).json()["removed"] is True
        # They are ours now. Dropping the connection is not dropping the kids.
        assert len(client.get(
            "/api/coach/roster", headers=wired["director"]
        ).json()["athletes"]) == 3

    def test_the_provider_list_is_honest_about_what_is_untested(self, client, wired):
        providers = client.get(
            "/api/coach/roster/providers", headers=wired["director"]
        ).json()["providers"]
        by_key = {p["key"]: p for p in providers}
        assert by_key["teamsnap"]["verified"] is False
        assert by_key["sportsengine"]["verified"] is False
        assert by_key["csv_url"]["verified"] is True


class TestTheScheduledSweep:
    def test_it_syncs_every_link_that_is_due(self, store, program, remote):
        link(store, program)
        store.set_roster_auto_sync(program["org"], program["team"]["id"], "stub", True)
        assert roster_sync.run_due(store) == {"ran": 1, "failed": 0}
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM team_members WHERE team_id = ?",
            (program["team"]["id"],),
        ).fetchone()["n"] == 3

    def test_one_broken_link_does_not_stop_the_others(self, store, program, remote):
        """A token that expired on one team is a normal Tuesday. It is not a
        reason for every other team in the program to go stale."""
        def angry(token, ref):
            raise roster_sync.SyncError("expired")

        roster_sync.BY_KEY["angry"] = roster_sync.Provider(
            key="angry", label="Angry", credential_label="T", team_field="ID",
            help_url="", fetch=angry, verified=True,
        )
        try:
            other = store.create_team(program["org"], "U13 Boys")
            store.link_roster(program["org"], other["id"], "angry", SECRET, "x")
            store.set_roster_auto_sync(program["org"], other["id"], "angry", True)
            link(store, program)
            store.set_roster_auto_sync(
                program["org"], program["team"]["id"], "stub", True)

            assert roster_sync.run_due(store) == {"ran": 2, "failed": 1}
            # The healthy team still got its roster.
            assert store.conn.execute(
                "SELECT COUNT(*) AS n FROM team_members WHERE team_id = ?",
                (program["team"]["id"],),
            ).fetchone()["n"] == 3
        finally:
            roster_sync.BY_KEY.pop("angry", None)

    def test_the_failure_is_left_where_that_teams_coach_will_see_it(
        self, store, program, remote
    ):
        def angry(token, ref):
            raise roster_sync.SyncError("They rejected the token.")

        roster_sync.BY_KEY["stub"] = roster_sync.Provider(
            key="stub", label="Stub League", credential_label="Token",
            team_field="Team ID", help_url="", fetch=angry, verified=True,
        )
        link(store, program)
        store.set_roster_auto_sync(program["org"], program["team"]["id"], "stub", True)
        roster_sync.run_due(store)
        last = store.roster_link(program["team"]["id"], "stub")["last_result"]
        assert last["error"] == "They rejected the token."
