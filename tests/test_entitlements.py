"""The club-free tier: what a family's payment buys, and what it cannot.

The club pays nothing. Parents who want the parent-facing product buy it for
their own child. That model has one well-known way of failing and it is
structural rather than commercial: if what a *coach* sees depended on which
parents paid, a club at forty per cent adoption would have a forty per cent
dashboard, would stop opening it, and would drop the product — at which point
nobody pays at all.

So most of this file is about the free side of the line. Everything a coach
touches, everything that keeps a child safe, and everything that is a right
rather than a feature is free for ever, and these tests are what make that
structural instead of a paragraph in a pricing page.

The last class is the one worth reading twice. A coach must not be able to
tell which families pay — not from a badge, not a count, not an ordering. This
product already promises it does not score what a household can afford, and a
dashboard that quietly revealed paying families would make that false exactly
where it matters most.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from offdays import billing, entitlements
from offdays.db import connect
from offdays.entitlements import Audience, Tier
from offdays.store import Store

# Anchored to the real date. A pinned anchor drifts out of the store's
# backdate window -- it refuses a completion older than
# OFFLINE_BACKDATE_LIMIT_DAYS and credits the session to today instead -- so
# fixtures that log backdated sessions quietly stop testing what they claim.
TODAY = date.today()


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "e.db"))


@pytest.fixture
def club(store):
    org = store.create_org("Northshore LC")
    director = store.create_user(org, "director", "Dir Smith")
    team = store.create_team(org, "U15 Boys")
    billing.start_subscription(store.conn, org, "club_free", trial=False)
    athletes = []
    for name in ("Ada Lin", "Ben Osei", "Cara Vale"):
        person = store.create_user(
            org, "athlete", name, birth_year=2011, dominant_hand="right")
        store.join_team(team["join_code"], person["id"])
        athletes.append(person)
    billing.start_household(store.conn, athletes[0]["id"])
    billing.grant_hardship(store.conn, athletes[2]["id"])
    return {"org": org, "director": director, "team": team,
            "paying": athletes[0], "unpaid": athletes[1],
            "hardship": athletes[2]}


class TestTheClubIsBilledNothing:
    def test_the_plan_costs_zero(self, store, club):
        subscription = billing.get_subscription(store.conn, club["org"])
        assert subscription.monthly_cents == 0
        assert subscription.plan.payer == billing.PAYER_HOUSEHOLD

    def test_seats_are_not_metered(self, store, club):
        """Metering a club that is not being charged would be pure friction --
        it would stop a director importing their roster to protect revenue
        that does not exist."""
        subscription = billing.get_subscription(store.conn, club["org"])
        assert subscription.unlimited_seats is True
        assert subscription.over_seats is False
        assert subscription.can_grow is True

    def test_a_huge_roster_never_blocks_growth(self, store, club):
        for i in range(80):
            person = store.create_user(
                club["org"], "athlete", f"Kid {i}", birth_year=2011,
                dominant_hand="right")
            store.join_team(club["team"]["join_code"], person["id"])
        assert billing.get_subscription(store.conn, club["org"]).can_grow

    def test_teams_and_staff_are_unlimited(self, store, club):
        plan = billing.PLANS_BY_CODE["club_free"]
        assert plan.max_teams == 0 and plan.max_staff == 0


class TestTheCoachingProductIsCompleteAtZeroPayingParents:
    """The failure mode this pricing is shaped around."""

    @pytest.mark.parametrize("key", sorted(
        f.key for f in entitlements.FEATURES if f.audience == Audience.COACH))
    def test_every_coach_feature_is_free(self, key):
        assert entitlements.BY_KEY[key].tier == Tier.FREE

    def test_an_unpaid_athlete_has_every_coach_feature(self, store, club):
        unpaid = entitlements.for_athlete(store.conn, club["unpaid"]["id"])
        assert unpaid.active is False
        for feature in entitlements.FEATURES:
            if feature.audience == Audience.COACH:
                assert unpaid.has(feature.key), feature.key

    def test_the_roster_shows_paying_and_unpaid_children_alike(
        self, store, club
    ):
        from offdays.leaderboard import coach_roster

        names = {
            row["display_name"]
            for row in coach_roster(
                store.conn, club["org"], club["team"]["id"], "week")
        }
        assert {"Ada Lin", "Ben Osei", "Cara Vale"} <= names


class TestWhatCanNeverBeChargedFor:
    def test_a_child_can_always_train(self, store, club):
        """Predates this file and outranks it."""
        assert entitlements.for_athlete(
            store.conn, club["unpaid"]["id"]).has("train")

    @pytest.mark.parametrize("key", ["wellness", "return_to_play", "load",
                                     "adaptive"])
    def test_safety_is_free(self, store, club, key):
        """Charging a family for injury prevention for a child is
        indefensible, and it would make the subsystem useless -- an unpaid
        child who stays quiet is the outcome."""
        assert entitlements.for_athlete(store.conn, club["unpaid"]["id"]).has(key)

    @pytest.mark.parametrize("key", ["consent", "data_export",
                                     "guardian_alerts"])
    def test_rights_are_free(self, store, club, key):
        assert entitlements.for_athlete(store.conn, club["unpaid"]["id"]).has(key)

    def test_technique_is_free(self, store, club):
        """Form scoring without the fix is a mark out of ten. Telling a child
        they are wrong and charging to say how to be right is the worst thing
        that could go behind this paywall."""
        assert entitlements.for_athlete(
            store.conn, club["unpaid"]["id"]).has("technique")

    def test_every_free_feature_states_why_it_is_free(self):
        """Prose rather than a comment, so moving one behind the paywall is a
        change somebody has to argue for in a diff."""
        for key in entitlements.FREE_KEYS:
            reason = entitlements.FREE_REASONS.get(key, "")
            assert len(reason) > 30, f"{key} is free with no stated reason"

    def test_the_free_list_is_not_quietly_shrinkable(self):
        """A guard on the count itself. Moving something out of the free tier
        should fail here and make somebody justify it."""
        assert len(entitlements.FREE_KEYS) >= 17
        for key in ("train", "wellness", "return_to_play", "load", "adaptive",
                    "technique", "consent", "data_export", "guardian_alerts",
                    "coach_roster", "coach_practice", "coach_evaluation"):
            assert key in entitlements.FREE_KEYS, f"{key} left the free tier"


class TestWhatAParentActuallyBuys:
    def test_an_unpaid_family_does_not_get_the_monthly_report(
        self, store, club
    ):
        assert not entitlements.for_athlete(
            store.conn, club["unpaid"]["id"]).has("parent_report")

    def test_a_paying_family_does(self, store, club):
        assert entitlements.for_athlete(
            store.conn, club["paying"]["id"]).has("parent_report")

    def test_history_is_clamped_rather_than_refused(self, store, club):
        """A family without the plan still sees the last month, which is
        enough for their child's own progress to be visible."""
        unpaid = entitlements.for_athlete(store.conn, club["unpaid"]["id"])
        assert unpaid.history_days == entitlements.FREE_HISTORY_DAYS
        assert entitlements.for_athlete(
            store.conn, club["paying"]["id"]).history_days is None

    def test_an_unknown_feature_raises_rather_than_silently_denying(self):
        """A typo in a gate must not read as "not paid for"."""
        with pytest.raises(KeyError):
            entitlements.Entitlement(athlete_id=1).has("nonsense")


class TestLapsingCostsAChildNothing:
    def test_an_expired_season_lapses(self, store, club):
        billing.start_household(
            store.conn, club["paying"]["id"], days=1,
            today=TODAY - timedelta(days=10))
        assert billing.expire_households(store.conn, TODAY) == 1
        assert not entitlements.for_athlete(
            store.conn, club["paying"]["id"], TODAY.isoformat()).active

    def test_but_training_and_safety_carry_on(self, store, club):
        billing.start_household(
            store.conn, club["paying"]["id"], days=1,
            today=TODAY - timedelta(days=10))
        billing.expire_households(store.conn, TODAY)
        lapsed = entitlements.for_athlete(
            store.conn, club["paying"]["id"], TODAY.isoformat())
        for key in ("train", "wellness", "load", "return_to_play", "consent",
                    "guardian_alerts", "coach_roster"):
            assert lapsed.has(key), key


class TestTheHardshipPathIsQuietAndSelfService:
    def test_it_gives_the_full_parent_product(self, store, club):
        granted = entitlements.for_athlete(store.conn, club["hardship"]["id"])
        assert granted.active is True
        for feature in entitlements.FEATURES:
            assert granted.has(feature.key), feature.key

    def test_it_is_indistinguishable_from_paying_in_every_feature(
        self, store, club
    ):
        paid = entitlements.for_athlete(store.conn, club["paying"]["id"])
        free = entitlements.for_athlete(store.conn, club["hardship"]["id"])
        assert paid.to_dict()["features"] == free.to_dict()["features"]

    def test_no_coach_is_involved_in_granting_it(self, store, club):
        """A family that has to ask their child's coach for a discount is a
        family that will not ask."""
        # Structural: granting notifies nobody at all.
        before = store.conn.execute(
            "SELECT COUNT(*) AS n FROM notifications").fetchone()["n"]
        billing.grant_hardship(store.conn, club["unpaid"]["id"])
        after = store.conn.execute(
            "SELECT COUNT(*) AS n FROM notifications").fetchone()["n"]
        assert after == before, "granting hardship notified somebody"


class TestNoCoachSurfaceRevealsWhoPays:
    """The rule this whole pricing model rests on.

    This product promises it does not score what a family can afford. A
    dashboard that quietly showed which children came from paying households
    would make that promise false in the one place it matters most — and it
    would do it at tryouts.
    """

    def _train(self, store, athlete, day=TODAY):
        rng = random.Random(athlete["id"])
        started = store.start_session(athlete["id"], "gen_squat")
        t, reps = 0, []
        for _ in range(20):
            t += max(600, int(rng.gauss(1500, 220)))
            value = 74.0 + rng.uniform(-3, 3)
            reps.append({"t_ms": t, "hand": "none", "confidence": 0.9,
                         "rom": value, "peak": value,
                         "cycle_ms": 1150 + rng.randint(-120, 120)})
        store.submit_session(
            athlete["id"], started["session_id"], started["nonce"],
            duration_ms=t + 900, reps=reps, mean_confidence=0.9)
        store.conn.execute(
            "UPDATE sessions SET submitted_at = ?, completed_at = ? WHERE id = ?",
            (day.isoformat() + "T18:00:00+00:00",
             day.isoformat() + "T18:00:00+00:00",
             started["session_id"]))
        store.conn.commit()

    def test_the_coach_roster_carries_no_billing_signal(self, store, club):
        from offdays.leaderboard import coach_roster

        payload = str(coach_roster(
            store.conn, club["org"], club["team"]["id"], "week")).lower()
        for leak in ("paid", "unpaid", "hardship", "sponsor", "subscription",
                     "entitle", "plan", "billing"):
            assert leak not in payload, f"the roster leaks: {leak!r}"

    def test_the_evaluation_export_carries_none_either(self, store, club):
        """The tryout document. The worst possible place to learn which
        children come from families who could pay."""
        from offdays import evaluation

        for athlete in (club["paying"], club["unpaid"], club["hardship"]):
            self._train(store, athlete)
        export = evaluation.build(
            store.conn, club["org"], club["team"]["id"], today=TODAY)
        rows = str([r.to_dict() for r in export.rows]).lower()
        for leak in ("paid", "hardship", "sponsor", "entitle", "billing"):
            assert leak not in rows, f"the evaluation export leaks: {leak!r}"

    def test_paying_and_unpaid_rows_are_shaped_identically(self, store, club):
        from offdays import evaluation

        for athlete in (club["paying"], club["unpaid"]):
            self._train(store, athlete)
        export = evaluation.build(
            store.conn, club["org"], club["team"]["id"], today=TODAY)
        paying = next(r for r in export.rows if r.display_name == "Ada Lin")
        unpaid = next(r for r in export.rows if r.display_name == "Ben Osei")
        assert set(paying.to_dict()) == set(unpaid.to_dict())
        assert paying.weeks_available == unpaid.weeks_available

    def test_the_pre_practice_card_carries_none(self, store, club):
        from offdays import practice

        card = str(practice.brief(
            store, club["org"], club["team"]["id"], today=TODAY).to_dict()).lower()
        for leak in ("paid", "hardship", "sponsor", "entitle", "billing"):
            assert leak not in card, f"the practice card leaks: {leak!r}"

    def test_no_coach_facing_module_reads_the_household_table(self):
        """Structural rather than by inspection of output."""
        import inspect

        from offdays import digest, evaluation, leaderboard, practice

        for module in (leaderboard, practice, evaluation, digest):
            source = inspect.getsource(module)
            assert "household_subscriptions" not in source, module.__name__
            assert "entitlements" not in source, module.__name__


class TestThePriceItself:
    def test_a_single_child_is_one_season_price(self):
        quote = billing.household_quote(1)
        assert quote["season_total_cents"] == billing.HOUSEHOLD_SEASON_CENTS

    def test_a_sibling_is_discounted(self):
        quote = billing.household_quote(2)
        assert quote["season_total_cents"] == (
            billing.HOUSEHOLD_SEASON_CENTS + billing.HOUSEHOLD_SIBLING_CENTS)

    def test_a_third_child_is_free(self):
        """A family with three children in a club is already the one paying
        the most."""
        assert billing.household_quote(3)["season_total_cents"] == \
            billing.household_quote(2)["season_total_cents"]

    def test_and_so_is_a_fourth(self):
        assert billing.household_quote(4)["season_total_cents"] == \
            billing.household_quote(2)["season_total_cents"]

    def test_a_season_beats_paying_monthly(self):
        """Monthly is worse value on purpose, and deliberately not much worse
        -- a punitive gap would read as a trap."""
        season = billing.household_quote(1)
        monthly = billing.HOUSEHOLD_MONTHLY_CENTS * billing.SEASON_MONTHS
        assert season["season_total_cents"] < monthly
        assert monthly < season["season_total_cents"] * 2

    def test_there_is_no_separate_sponsorship_price(self):
        """Pricing one was a mistake worth keeping a test about. At $19 an
        athlete it came out between 2.5x and 5.7x more expensive than simply
        buying the seat plan that fits the same roster, so no club would ever
        rationally have chosen it. A third price that always loses to one you
        already publish is not a pricing option, it is a trap for whoever
        reads the pricing page carefully."""
        assert not hasattr(billing, "SPONSOR_SEASON_CENTS")

    def test_covering_everybody_means_buying_a_seat_plan(self, store, club):
        """And that plan is cheaper than covering families one at a time."""
        season = billing.SEASON_MONTHS
        for size in (40, 100, 200, 400):
            households = size * billing.HOUSEHOLD_SEASON_CENTS
            fits = [p for p in billing.PLANS
                    if p.payer == billing.PAYER_PROGRAM
                    and p.price_cents > 0 and p.included_seats >= size]
            assert fits, size
            cheapest = min(p.seat_cost_cents(size) for p in fits) * season
            assert cheapest < households, (
                f"at {size} athletes a seat plan should beat paying for every "
                f"household: {cheapest} vs {households}"
            )

    def test_a_paid_seat_plan_includes_the_parent_product(self, store, club):
        """What paying for seats should mean."""
        billing.start_subscription(store.conn, club["org"], "program",
                                   trial=False)
        for key in ("paying", "unpaid", "hardship"):
            granted = entitlements.for_athlete(store.conn, club[key]["id"])
            assert granted.active is True
            assert granted.has("parent_report")

    def test_the_free_club_plan_does_not(self, store, club):
        assert not entitlements.for_athlete(
            store.conn, club["unpaid"]["id"]).active

    def test_a_club_free_program_can_still_cover_named_athletes(
        self, store, club
    ):
        """The scaled-up hardship path: a director covering families who will
        not ask. Free to the club."""
        covered = billing.sponsor_athletes(
            store.conn, club["org"], [club["unpaid"]["id"]])
        assert covered == 1
        assert entitlements.for_athlete(store.conn, club["unpaid"]["id"]).active


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
def wired(client):
    from offdays import api as api_mod
    from offdays import guardians as guardians_mod

    store = api_mod.get_store()
    org = client.post(
        "/api/orgs", json={"name": "Northshore LC", "director_name": "Dir"}
    ).json()
    director = {"Authorization": f"Bearer {org['director']['token']}"}
    team = client.post("/api/teams", json={"name": "U15"}, headers=director).json()
    kid = client.post(
        "/api/athletes",
        json={"display_name": "Jordan P.", "birth_year": 2011,
              "dominant_hand": "right", "guardian_consent": True,
              "join_code": team["join_code"]},
        headers=director).json()
    org_id = store.authenticate(org["director"]["token"]).org_id
    billing.start_subscription(store.conn, org_id, "club_free", trial=False)
    invite = guardians_mod.create_invite(
        store.conn, kid["id"], store.authenticate(org["director"]["token"]).id)
    parent = guardians_mod.redeem_invite(
        store.conn, invite["code"], "Sam Pierce", "sam@example.com")
    guardians_mod.set_consent(
        store.conn, kid["id"], parent["guardian_id"],
        guardians_mod.Scope.PARTICIPATION, True)
    return {"store": store, "org_id": org_id, "director": director, "kid": kid,
            "parent": {"Authorization": f"Bearer {parent['token']}"}}


class TestOverTheWire:
    def test_pricing_is_public(self, client):
        """A family should be able to read what they are buying before they
        have an account."""
        body = client.get("/api/pricing").json()
        assert body["club"]["costs_the_club"] == 0
        assert body["household"]["first_child_cents"] > 0
        assert body["features"]["free"]

    def test_every_free_feature_publishes_why(self, client):
        for feature in client.get("/api/pricing").json()["features"]["free"]:
            assert feature["why_free"], feature["key"]

    def test_the_report_is_refused_with_402_not_403(self, client, wired):
        """Not a permission problem, and the copy should not read like one. A
        family that has not bought has done nothing wrong."""
        res = client.get(
            f"/api/parent/athletes/{wired['kid']['id']}/report",
            headers=wired["parent"])
        assert res.status_code == 402
        assert "keeps training" in res.json()["detail"]

    def test_and_allowed_once_they_have_the_plan(self, client, wired):
        billing.start_household(wired["store"].conn, wired["kid"]["id"])
        assert client.get(
            f"/api/parent/athletes/{wired['kid']['id']}/report",
            headers=wired["parent"]).status_code == 200

    def test_hardship_is_self_service(self, client, wired):
        assert client.post(
            f"/api/parent/athletes/{wired['kid']['id']}/plan/hardship",
            headers=wired["parent"]).status_code == 201
        assert client.get(
            f"/api/parent/athletes/{wired['kid']['id']}/report",
            headers=wired["parent"]).status_code == 200

    def test_the_history_window_is_clamped_not_refused(self, client, wired):
        res = client.get(
            f"/api/parent/athletes/{wired['kid']['id']}/drills?days=180",
            headers=wired["parent"])
        assert res.status_code == 200

    def test_a_family_sees_their_own_quote(self, client, wired):
        body = client.get(
            f"/api/parent/athletes/{wired['kid']['id']}/plan",
            headers=wired["parent"]).json()
        assert body["quote"]["children"] == 1
        assert body["active"] is False

    def test_only_a_director_can_sponsor(self, client, wired):
        coach = wired["store"].create_user(wired["org_id"], "coach", "Asst")
        headers = {"Authorization": f"Bearer {coach['token']}"}
        assert client.post(
            "/api/org/sponsor", json={"athlete_ids": []},
            headers=headers).status_code == 403
        assert client.post(
            "/api/org/sponsor", json={"athlete_ids": []},
            headers=wired["director"]).status_code == 201

    def test_sponsoring_costs_the_club_nothing(self, client, wired):
        body = client.post(
            "/api/org/sponsor", json={"athlete_ids": []},
            headers=wired["director"]).json()
        assert body["cost_to_the_club_cents"] == 0

    def test_the_pricing_page_offers_one_paid_club_plan(self, client):
        """The seat tiers are retired, so the page that once pointed a paying
        club at them now points at the roster plan and nothing else. One
        price for a paying club is the whole point."""
        body = client.get("/api/pricing").json()
        assert "sponsorship" not in body
        assert body["club_pays_instead"]["plans"] == []
        assert body["club_roster"]["per_athlete_season_cents"] > 0
