"""Plans, seats, and entitlements.

The rule this whole module is shaped around: an adult's payment problem must
never stop a child from training. TestBillingNeverLocksOutAthletes is the class
that enforces it, and it is the one to look at first if any of this is ever
refactored.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from athleteiq import billing as B
from athleteiq.db import connect
from athleteiq.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "b.db"))


@pytest.fixture
def org(store):
    return store.create_org("Northshore LC")


def add_athletes(store, org_id, count, start=0):
    made = []
    for i in range(count):
        made.append(store.create_user(org_id, "athlete", f"Athlete {start + i}"))
    return made


def _seat_metered(plan) -> bool:
    """Billed to the club by seat allowance rather than per head."""
    return (plan.payer == B.PAYER_PROGRAM
            and plan.price_cents > 0
            and plan.per_athlete_season_cents == 0)


class TestPlans:
    def test_every_plan_is_internally_consistent(self):
        for plan in B.PLANS:
            assert plan.price_cents >= 0
            assert plan.extra_seat_cents >= 0
            # Only a *seat-metered* plan has an allowance to be consistent
            # about. Neither of the plans this product now sells is one: the
            # roster plan bills per athlete, so every athlete is a seat and
            # there is no ceiling, and the club-free plan bills the club
            # nothing at all.
            if _seat_metered(plan):
                assert plan.included_seats > 0

    def test_plans_ascend_in_capacity(self):
        seats = [p.included_seats for p in B.PLANS if _seat_metered(p)]
        assert seats == sorted(seats)

    def test_a_per_athlete_plan_has_no_seat_ceiling(self):
        """You cannot exceed a seat allowance when every athlete is a seat.
        Getting this wrong blocked roster growth at four athletes."""
        for plan in B.PLANS:
            if plan.per_athlete_season_cents > 0:
                assert plan.included_seats == 0
                assert plan.max_teams == 0 and plan.max_staff == 0

    def test_a_household_paid_plan_charges_and_meters_nothing(self):
        """Stated as its own invariant rather than as an exception to the
        others, so "free to the club" cannot drift into "cheap"."""
        for plan in B.PLANS:
            if plan.payer != B.PAYER_HOUSEHOLD:
                continue
            assert plan.price_cents == 0
            assert plan.extra_seat_cents == 0
            assert plan.max_teams == 0        # 0 means unlimited here
            assert plan.max_staff == 0

    def test_exactly_one_plan_is_household_paid(self):
        """More than one would mean two answers to "what does a club pay",
        which is the question this tier exists to make trivial."""
        household = [p for p in B.PLANS if p.payer == B.PAYER_HOUSEHOLD]
        assert len(household) == 1
        assert household[0].code == "club_free"

    def test_per_seat_price_falls_as_plans_grow(self):
        """Otherwise there is no reason to move up."""
        paid = [p for p in B.PLANS if not p.is_free]
        rates = [p.extra_seat_cents for p in paid]
        assert rates == sorted(rates, reverse=True)

    def test_extra_seats_are_charged(self):
        plan = B.get_plan("team")
        assert plan.seat_cost_cents(plan.included_seats + 10) > plan.price_cents

    def test_an_unknown_plan_raises(self):
        with pytest.raises(B.BillingError, match="unknown plan"):
            B.get_plan("enterprise-platinum")


class TestSubscription:
    def test_a_new_program_starts_on_a_trial(self, store, org):
        """Hitting a paywall before the product has shown anything ends an evaluation."""
        subscription = B.get_subscription(store.conn, org)
        assert subscription.status == "trialing"
        assert subscription.plan.code == B.TRIAL_PLAN
        assert subscription.trial_days_left == B.TRIAL_DAYS

    def test_a_program_with_no_row_falls_back_to_free_not_broken(self, store):
        org_id = store.create_org("Legacy")
        store.conn.execute("DELETE FROM subscriptions WHERE org_id = ?", (org_id,))
        store.conn.commit()
        subscription = B.get_subscription(store.conn, org_id)
        assert subscription.plan.code == "free"
        assert subscription.can_grow

    def test_an_expired_trial_becomes_past_due(self, store, org):
        store.conn.execute(
            "UPDATE subscriptions SET trial_ends_at = ? WHERE org_id = ?",
            ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), org),
        )
        store.conn.commit()
        assert B.get_subscription(store.conn, org).status == "past_due"

    def test_usage_counts_the_roster_not_the_training(self, store, org):
        """Billing on sessions would punish a quiet week, which is a strange
        incentive for a training product."""
        add_athletes(store, org, 4)
        usage = B.measure_usage(store.conn, org)
        assert usage.athletes == 4
        assert usage.staff == 0

    def test_deactivated_athletes_stop_being_billable(self, store, org):
        athletes = add_athletes(store, org, 3)
        store.conn.execute("UPDATE users SET active = 0 WHERE id = ?", (athletes[0]["id"],))
        store.conn.commit()
        assert B.measure_usage(store.conn, org).athletes == 2

    def test_plan_changes_are_recorded(self, store, org):
        B.start_subscription(store.conn, org, "club", trial=False, actor="tester")
        events = B.history(store.conn, org)
        assert any(e["kind"] == "plan_change" for e in events)


class TestEntitlements:
    def test_athletes_can_be_added_inside_the_plan(self, store, org):
        B.check_can_add_athletes(store.conn, org, 10)

    def test_exceeding_seats_is_refused_with_a_number(self, store, org):
        B.start_subscription(store.conn, org, "free", trial=False)
        add_athletes(store, org, 25)
        with pytest.raises(B.BillingError, match="more seat"):
            B.check_can_add_athletes(store.conn, org, 10)

    def test_a_few_over_is_tolerated(self, store, org):
        """A roster still being built at the start of a season is not abuse."""
        B.start_subscription(store.conn, org, "free", trial=False)
        add_athletes(store, org, 25)
        B.check_can_add_athletes(store.conn, org, B.SEAT_GRACE)

    def test_team_limits_are_enforced(self, store, org):
        B.start_subscription(store.conn, org, "free", trial=False)
        store.create_team(org, "Only Team")
        with pytest.raises(B.BillingError, match="team"):
            store.create_team(org, "Second Team")

    def test_unlimited_plans_have_no_team_limit(self, store, org):
        B.start_subscription(store.conn, org, "club", trial=False)
        for i in range(15):
            store.create_team(org, f"Team {i}")

    def test_past_due_blocks_growth(self, store, org):
        B.set_status(store.conn, org, "past_due")
        with pytest.raises(B.BillingError, match="overdue"):
            B.check_can_add_athletes(store.conn, org, 1)

    def test_the_past_due_message_says_nobody_is_locked_out(self, store, org):
        """The error a director reads should not imply their athletes are cut off."""
        B.set_status(store.conn, org, "past_due")
        with pytest.raises(B.BillingError) as exc:
            B.check_can_add_athletes(store.conn, org, 1)
        assert "training continues" in str(exc.value)

    def test_canceled_blocks_growth_but_says_so_kindly(self, store, org):
        B.set_status(store.conn, org, "canceled")
        with pytest.raises(B.BillingError) as exc:
            B.check_can_add_athletes(store.conn, org, 1)
        assert "keep training" in str(exc.value)


class TestBillingNeverLocksOutAthletes:
    """The rule everything else here is shaped around."""

    def _train(self, store, athlete_id, seed=1):
        slot = store.start_session(athlete_id, "lax_wall_ball")
        rng = random.Random(seed)
        t, reps = 0, []
        for i in range(120):
            rom = 0.47 * (1 + rng.gauss(0, 0.08))
            t += max(150, int(rng.gauss(880, 180)))
            reps.append({
                "t_ms": t, "hand": "left" if i % 2 else "right", "confidence": 0.9,
                "rom": round(max(0.01, rom), 3), "peak": round(rom * 0.7, 3),
                "cycle_ms": max(120, int(rng.gauss(880, 150))),
            })
        return store.submit_session(
            athlete_id, slot["session_id"], slot["nonce"],
            duration_ms=t + 700, reps=reps, mean_confidence=0.9,
        )

    @pytest.mark.parametrize("status", ["past_due", "canceled"])
    def test_athletes_keep_training_whatever_the_billing_says(self, store, org, status):
        athlete = store.create_user(org, "athlete", "Jordan", dominant_hand="right")
        team = store.create_team(org, "Varsity")
        store.join_team(team["join_code"], athlete["id"])

        B.set_status(store.conn, org, status)
        result = self._train(store, athlete["id"])
        assert result["status"] == "counted"
        assert result["xp_awarded"] > 0

    def test_a_coach_still_sees_safety_advisories_when_past_due(self, store, org):
        """Hiding a load warning over an unpaid invoice would be indefensible."""
        athlete = store.create_user(org, "athlete", "Jordan", dominant_hand="right")
        team = store.create_team(org, "Varsity")
        store.join_team(team["join_code"], athlete["id"])
        self._train(store, athlete["id"])

        B.set_status(store.conn, org, "past_due")
        assert store.load_state(athlete["id"]) is not None
        assert store.athlete_profile(athlete["id"])["total_xp"] > 0

    def test_over_seats_does_not_stop_existing_athletes(self, store, org):
        """A club that downgrades is suddenly over its limit. The kids on the
        roster did not do anything, and must not lose their training."""
        athletes = add_athletes(store, org, 40)
        team = store.create_team(org, "Varsity")
        store.join_team(team["join_code"], athletes[0]["id"])

        B.start_subscription(store.conn, org, "free", trial=False)
        subscription = B.get_subscription(store.conn, org)
        assert subscription.over_seats
        assert not subscription.can_grow

        assert self._train(store, athletes[0]["id"])["status"] == "counted"


class TestQuoting:
    def test_a_quote_prices_the_current_roster(self, store, org):
        add_athletes(store, org, 80)
        quote = B.quote(store.conn, org, "team")
        assert quote["athletes"] == 80
        assert quote["extra_seats"] == 20
        assert quote["total_cents"] > B.get_plan("team").price_cents

    def test_a_larger_plan_can_be_cheaper_at_scale(self, store, org):
        """Which is the point of having tiers at all."""
        B.start_subscription(store.conn, org, "club", trial=False)
        add_athletes(store, org, 250)
        assert B.quote(store.conn, org, "program")["total_cents"] < \
            B.quote(store.conn, org, "team")["total_cents"]

    def test_recommendation_picks_the_cheapest_plan_that_fits(self, store, org):
        add_athletes(store, org, 10)
        assert B.recommend(store.conn, org) == "free"
        add_athletes(store, org, 40, start=100)
        assert B.recommend(store.conn, org) == "team"

    def test_a_quote_flags_a_plan_that_does_not_fit(self, store, org):
        B.start_subscription(store.conn, org, "club", trial=False)
        for i in range(5):
            store.create_team(org, f"Team {i}")
        assert B.quote(store.conn, org, "free")["fits_current_usage"] is False


class TestBillingCycle:
    def test_the_manual_gateway_records_without_charging(self, store, org):
        gateway = B.ManualGateway(store.conn)
        result = gateway.charge(org, 14900, "Program")
        assert result["captured"] is False
        assert any(e["kind"] == "invoice" for e in B.history(store.conn, org))

    def test_free_programs_are_not_invoiced(self, store, org):
        B.start_subscription(store.conn, org, "free", trial=False)
        store.conn.execute(
            "UPDATE subscriptions SET period_end = ? WHERE org_id = ?",
            ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), org),
        )
        store.conn.commit()
        assert B.run_billing_cycle(store.conn) == []

    def test_a_due_period_raises_a_charge_and_rolls_forward(self, store, org):
        B.start_subscription(store.conn, org, "team", trial=False)
        add_athletes(store, org, 10)
        store.conn.execute(
            "UPDATE subscriptions SET period_end = ? WHERE org_id = ?",
            ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), org),
        )
        store.conn.commit()

        raised = B.run_billing_cycle(store.conn)
        assert len(raised) == 1
        assert raised[0]["amount_cents"] == B.get_plan("team").price_cents
        # Running again immediately must not double-charge.
        assert B.run_billing_cycle(store.conn) == []

    def test_a_migrated_program_is_not_retroactively_paywalled(self, store):
        """Telling a club with six teams they are now on a one-team plan is the
        wrong way to introduce billing to an existing customer."""
        org_id = store.create_org("Big Club")
        B.start_subscription(store.conn, org_id, "club", trial=False)
        for i in range(8):
            store.create_team(org_id, f"Team {i}")
        store.conn.execute("DELETE FROM subscriptions WHERE org_id = ?", (org_id,))
        store.conn.commit()

        B.backfill_subscriptions(store.conn)
        subscription = B.get_subscription(store.conn, org_id)
        assert subscription.plan.max_teams == 0 or subscription.plan.max_teams >= 8
