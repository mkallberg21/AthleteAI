"""The club buys a seat for every rostered athlete.

The club is invoiced per athlete per season and covers it by adding a line to
its own season fee. The money still comes from parents, but through the
channel they already pay through, at the moment they are already paying: no
second checkout, no chasing, and no coach explaining a subscription.

It also removes the failure mode the household model has to design around.
Every athlete is covered, so coverage is never partial and a coach's view is
never a function of who bought what.

The commercial shape is the part worth testing. A director is not being asked
to find budget -- they are shown a line that funds their own scholarship fund,
made of the margin between what they add to dues and what they owe us, plus a
rebate on what they pay. That only works if the numbers actually land that way,
and if nothing else in the price list quietly beats it.
"""
from __future__ import annotations

import pytest

from athleteiq import billing, entitlements
from athleteiq.billing import BillingError
from athleteiq.db import connect
from athleteiq.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "r.db"))


def club(store, athletes=200, plan="club_roster"):
    org = store.create_org("Northshore LC")
    director = store.create_user(org, "director", "Dir Smith")
    team = store.create_team(org, "U15 Boys")
    billing.start_subscription(store.conn, org, plan, trial=False)
    for i in range(athletes):
        person = store.create_user(
            org, "athlete", f"Kid {i}", birth_year=2011, dominant_hand="right")
        store.join_team(team["join_code"], person["id"])
    return {"org": org, "director": director, "team": team}


class TestTheClubIsOutNothing:
    def test_the_dues_add_more_than_covers_the_invoice(self, store):
        """The whole pitch. If this ever inverts, a director is being asked to
        find budget and the conversation is a different one."""
        program = club(store)
        invoice = billing.roster_invoice(store.conn, program["org"])
        assert invoice.dues_collected_cents > invoice.total_cents
        assert invoice.club_margin_cents > 0

    def test_it_holds_at_every_club_size(self, store):
        """Margin per athlete is constant by construction, but a test says so
        rather than leaving it to be re-derived."""
        for size in (12, 40, 200, 600):
            program = club(store, athletes=size)
            invoice = billing.roster_invoice(store.conn, program["org"])
            assert invoice.club_margin_cents == size * (
                billing.RECOMMENDED_DUES_ADD_CENTS
                - billing.get_plan("club_roster").per_athlete_season_cents
            )

    def test_a_roster_plan_is_never_seat_blocked(self, store):
        """You cannot exceed a seat allowance when every athlete is a seat.
        Without this the plan blocked growth at four athletes, because
        included_seats is zero for a plan that does not use it -- which would
        have broken every club on the model this product sells."""
        program = club(store, athletes=600)
        subscription = billing.get_subscription(store.conn, program["org"])
        assert subscription.unlimited_seats is True
        assert subscription.over_seats is False
        assert subscription.can_grow is True

    def test_the_payload_says_the_club_pays_nothing_directly(self, store):
        program = club(store, athletes=40)
        assert billing.roster_invoice(
            store.conn, program["org"]).to_dict()["costs_the_club_directly"] == 0

    def test_the_recommended_add_is_small_against_a_season_fee(self):
        """A club season runs into four figures. An add that a parent has to
        think about is one the club will not make."""
        assert billing.RECOMMENDED_DUES_ADD_CENTS <= 5000


class TestTheSponsorshipFund:
    def test_the_rebate_is_a_share_of_what_the_club_paid(self, store):
        program = club(store)
        invoice = billing.roster_invoice(store.conn, program["org"])
        assert invoice.rebate_cents == round(
            invoice.total_cents * billing.REBATE_RATE_DEFAULT)

    def test_the_rate_is_bounded(self, store):
        """A lever, but a bounded one. Outside the band it stops being a
        scholarship rebate and becomes a volume discount in disguise."""
        program = club(store, athletes=10)
        for bad in (0.0, 0.04, 0.25, 1.0):
            with pytest.raises(BillingError, match="between"):
                billing.roster_invoice(
                    store.conn, program["org"], rebate_rate=bad)

    def test_a_negotiated_top_of_band_rate_works(self, store):
        program = club(store, athletes=100)
        invoice = billing.roster_invoice(
            store.conn, program["org"], rebate_rate=billing.REBATE_RATE_MAX)
        assert invoice.rebate_cents > 0

    def test_the_fund_is_a_ledger_not_a_discount(self, store):
        """A discount disappears into a smaller number nobody looks at. A fund
        with a balance is something a director can point at in a board meeting
        and spend on a named family."""
        program = club(store, athletes=100)
        invoice = billing.roster_invoice(store.conn, program["org"])
        billing.accrue_rebate(store.conn, program["org"], invoice.total_cents)
        assert billing.rebate_balance(store.conn, program["org"]) == \
            invoice.rebate_cents
        assert billing.rebate_ledger(store.conn, program["org"])

    def test_spending_it_records_who_it_went_to(self, store):
        program = club(store, athletes=100)
        billing.accrue_rebate(store.conn, program["org"], 100_000)
        billing.spend_rebate(
            store.conn, program["org"], 5000, "covered the Reyes season fee")
        ledger = billing.rebate_ledger(store.conn, program["org"])
        assert any("Reyes" in row["reason"] for row in ledger)
        assert any(row["amount_cents"] < 0 for row in ledger)

    def test_it_cannot_be_overdrawn(self, store):
        program = club(store, athletes=10)
        billing.accrue_rebate(store.conn, program["org"], 10_000)
        with pytest.raises(BillingError, match="less than"):
            billing.spend_rebate(
                store.conn, program["org"], 999_999, "too much")

    def test_the_scholarship_pot_is_margin_plus_rebate(self, store):
        """The number that makes it an easy yes."""
        program = club(store)
        invoice = billing.roster_invoice(store.conn, program["org"])
        assert invoice.sponsorship_pot_cents == (
            invoice.club_margin_cents + invoice.rebate_cents)
        assert invoice.sponsorship_pot_cents > invoice.total_cents / 2


class TestNothingInThePriceListUndercutsIt:
    """The mistake this replaces, and the one before that.

    A sponsorship SKU was priced above the seat plans and always lost; the
    seat plans were then priced 3.4x to 7.5x below per-athlete and would have
    won every time. A price that always loses to another price you publish is
    a trap for whoever reads carefully.
    """

    def test_the_seat_tiers_are_retired(self):
        for code in ("team", "program", "club"):
            assert billing.PLANS_BY_CODE[code].offered is False

    def test_but_they_still_resolve_for_existing_rows(self):
        """Retiring a plan must not break a club already on one."""
        for code in ("team", "program", "club"):
            assert billing.get_plan(code) is not None

    def test_exactly_one_plan_is_offered_to_a_paying_club(self):
        offered = [p for p in billing.PLANS
                   if p.offered and p.payer == billing.PAYER_PROGRAM
                   and (p.price_cents > 0 or p.per_athlete_season_cents > 0)]
        assert [p.code for p in offered] == ["club_roster"]

    def test_a_club_buying_beats_its_families_buying_individually(self, store):
        """The direction has to be this way round. A club committing its whole
        roster, guaranteed and with no acquisition cost, should not pay more
        per head than one family buying alone."""
        assert billing.get_plan("club_roster").per_athlete_season_cents < \
            billing.HOUSEHOLD_SEASON_CENTS


class TestLateJoinersAreProrated:
    def test_a_full_season_is_the_full_price(self):
        plan = billing.get_plan("club_roster")
        assert billing.prorated_cents(plan, billing.SEASON_MONTHS) == \
            plan.per_athlete_season_cents

    def test_half_a_season_is_about_half(self):
        plan = billing.get_plan("club_roster")
        half = billing.prorated_cents(plan, billing.SEASON_MONTHS // 2)
        assert 0 < half < plan.per_athlete_season_cents

    def test_a_player_who_joins_at_the_end_costs_almost_nothing(self):
        """A club billed a full season for a week-ten joiner will stop adding
        late joiners, which turns a billing rule into a reason to leave a
        child off a roster."""
        plan = billing.get_plan("club_roster")
        assert billing.prorated_cents(plan, 1) < plan.per_athlete_season_cents / 4

    def test_no_months_left_costs_nothing(self):
        assert billing.prorated_cents(billing.get_plan("club_roster"), 0) == 0


class TestEveryRosteredAthleteIsCovered:
    def test_coverage_is_never_partial(self, store):
        """The failure mode the household model has to design around simply
        does not exist here."""
        program = club(store, athletes=30)
        for row in store.conn.execute(
            "SELECT id FROM users WHERE role = 'athlete'"
        ):
            granted = entitlements.for_athlete(store.conn, int(row["id"]))
            assert granted.active is True
            assert granted.has("parent_report")

    def test_a_club_on_the_free_plan_still_does_not_cover_anybody(self, store):
        program = club(store, athletes=5, plan="club_free")
        row = store.conn.execute(
            "SELECT id FROM users WHERE role = 'athlete' LIMIT 1").fetchone()
        assert entitlements.for_athlete(
            store.conn, int(row["id"])).active is False

    def test_the_coach_still_cannot_tell_who_paid(self, store):
        """It stops mattering under this plan, and the guarantee stays anyway
        -- a club may move to the free plan mid-season."""
        program = club(store, athletes=5)
        from athleteiq.leaderboard import coach_roster

        payload = str(coach_roster(
            store.conn, program["org"], program["team"]["id"], "week")).lower()
        for leak in ("paid", "invoice", "rebate", "sponsor", "billing"):
            assert leak not in payload


# ---------------------------------------------------------------------------
# Over the wire
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ATHLETEIQ_DB", str(tmp_path / "api.db"))
    from athleteiq import api

    api.app.dependency_overrides.clear()
    return TestClient(api.app)


@pytest.fixture
def wired(client):
    from athleteiq import api as api_mod

    store = api_mod.get_store()
    org = client.post(
        "/api/orgs", json={"name": "Northshore LC", "director_name": "Dir"}
    ).json()
    director = {"Authorization": f"Bearer {org['director']['token']}"}
    team = client.post("/api/teams", json={"name": "U15"}, headers=director).json()
    for i in range(20):
        client.post(
            "/api/athletes",
            json={"display_name": f"Kid {i}", "birth_year": 2011,
                  "dominant_hand": "right", "guardian_consent": True,
                  "join_code": team["join_code"]},
            headers=director)
    org_id = store.authenticate(org["director"]["token"]).org_id
    billing.start_subscription(store.conn, org_id, "club_roster", trial=False)
    return {"store": store, "org_id": org_id, "director": director}


class TestOverTheWire:
    def test_a_director_sees_the_whole_arrangement(self, client, wired):
        body = client.get("/api/org/invoice", headers=wired["director"]).json()
        assert body["athletes"] == 20
        assert body["costs_the_club_directly"] == 0
        assert body["sponsorship_pot_cents"] > 0

    def test_the_dues_add_is_theirs_to_change(self, client, wired):
        """Our recommendation, their number."""
        body = client.get(
            "/api/org/invoice?dues_add_cents=6000",
            headers=wired["director"]).json()
        assert body["recommended_dues_add_cents"] == 6000
        assert body["club_margin_cents"] > 0

    def test_an_out_of_band_rebate_is_refused(self, client, wired):
        """422 rather than a payment error: an out-of-range parameter is a
        bad request, not a billing problem."""
        assert client.get(
            "/api/org/invoice?rebate_rate=0.5",
            headers=wired["director"]).status_code == 422

    def test_an_assistant_coach_cannot_see_the_invoice(self, client, wired):
        coach = wired["store"].create_user(wired["org_id"], "coach", "Asst")
        headers = {"Authorization": f"Bearer {coach['token']}"}
        assert client.get("/api/org/invoice", headers=headers).status_code == 403
        assert client.get(
            "/api/org/sponsorship-fund", headers=headers).status_code == 403

    def test_the_fund_can_be_spent_and_shows_where_it_went(self, client, wired):
        billing.accrue_rebate(wired["store"].conn, wired["org_id"], 100_000)
        res = client.post(
            "/api/org/sponsorship-fund/spend",
            json={"amount_cents": 4000, "reason": "covered a season fee"},
            headers=wired["director"])
        assert res.status_code == 201
        ledger = client.get(
            "/api/org/sponsorship-fund", headers=wired["director"]).json()
        assert ledger["balance_cents"] == 7500 - 4000 + (100_000 * 0.075 - 7500)
        assert any("covered a season fee" in row["reason"]
                   for row in ledger["ledger"])

    def test_the_pricing_page_offers_only_the_roster_plan(self, client):
        body = client.get("/api/pricing").json()
        assert body["club_roster"]["per_athlete_season_cents"] > 0
        assert body["club_pays_instead"]["plans"] == []
