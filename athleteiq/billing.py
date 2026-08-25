"""Plans, seats, and entitlements.

Billing for youth sports has one rule that overrides the rest: **an adult's
payment problem must never stop a child from training.** A lapsed card is a
conversation with the club treasurer, not a reason to lock a fourteen-year-old
out of their wall-ball streak or to hide a load warning from the coach
responsible for them.

So enforcement is deliberately asymmetric. Growth is gated -- adding athletes,
teams, and staff stops when a program is over its plan or past due. Everything
already in flight keeps working: athletes train, coaches see their rosters,
parents keep their portal, and safety advisories keep flowing. A program that
stops paying stops *growing*, and someone calls them.

There is no payment processor wired in here. `Gateway` is the seam one drops
into, and `ManualGateway` -- record what happened, charge nothing -- is what
runs until then, which is also what a club paying by invoice actually needs.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

TRIAL_DAYS = 30

# What a new program is given for its trial: full capability, so an evaluation
# is not shaped by limits the club would not hit in practice anyway.
TRIAL_PLAN = "program"

# How far a program may exceed its seat count before adding more is blocked.
# A few over at the start of a season is a roster still being built, not abuse.
SEAT_GRACE = 3


class BillingError(Exception):
    """An action that the program's current plan does not permit."""


#: Who the invoice goes to.
PAYER_PROGRAM = "program"     # the club is billed for seats
PAYER_HOUSEHOLD = "household"  # the club is billed nothing; families opt in


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    price_cents: int                 # per month
    included_seats: int              # billable athletes included
    extra_seat_cents: int            # per athlete per month beyond that
    max_teams: int                   # 0 means unlimited
    max_staff: int                   # 0 means unlimited
    blurb: str = ""
    payer: str = PAYER_PROGRAM

    @property
    def is_free(self) -> bool:
        return self.price_cents == 0

    def seat_cost_cents(self, athletes: int) -> int:
        extra = max(0, athletes - self.included_seats)
        return self.price_cents + extra * self.extra_seat_cents

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "price_cents": self.price_cents,
            "price_display": f"${self.price_cents / 100:,.0f}/mo" if self.price_cents else "Free",
            "included_seats": self.included_seats,
            "extra_seat_cents": self.extra_seat_cents,
            "max_teams": self.max_teams,
            "max_staff": self.max_staff,
            "blurb": self.blurb,
        }


# Priced per program per month. Seats are *athletes*, because that is the unit
# a club budgets in and the number a director already knows.
PLANS: tuple[Plan, ...] = (
    Plan(
        code="family",
        name="Family",
        # Priced at zero for now. The whole product works for a family the day
        # they sign up, and what they eventually pay is a business decision
        # that has not been made -- so it is set here rather than assumed
        # anywhere else in the code.
        price_cents=0,
        # A household, with room for siblings and a generous margin.
        included_seats=6,
        extra_seat_cents=0,
        max_teams=1,
        max_staff=1,
        blurb=(
            "One family, running it themselves. A parent takes the coach's "
            "place: they set the training, write the recognition, and see "
            "everything."
        ),
    ),
    Plan(
        code="free",
        name="Single Team",
        price_cents=0,
        included_seats=25,
        extra_seat_cents=0,
        max_teams=1,
        max_staff=2,
        blurb="One team, up to 25 athletes. Everything works; nothing expires.",
    ),
    Plan(
        code="team",
        name="Team",
        price_cents=4900,
        included_seats=60,
        extra_seat_cents=100,
        max_teams=3,
        max_staff=6,
        blurb="A school programme or a single travel club.",
    ),
    Plan(
        code="program",
        name="Program",
        price_cents=14900,
        included_seats=200,
        extra_seat_cents=80,
        max_teams=12,
        max_staff=25,
        blurb="Multiple age groups under one athletic department.",
    ),
    Plan(
        code="club_free",
        name="Club",
        # Nothing, and unlimited, on purpose. A director should be able to say
        # yes without a budget line, a procurement cycle, or a board meeting --
        # those are what actually kill a youth-sports pilot, not price.
        #
        # The coaching product is complete at zero paying parents, so a club
        # here is never running a degraded version of anything while it waits
        # for families to opt in. See entitlements.py for why that is
        # structural rather than generous.
        price_cents=0,
        included_seats=0,       # unlimited; see `seat_limit`
        extra_seat_cents=0,
        max_teams=0,
        max_staff=0,
        payer=PAYER_HOUSEHOLD,
        blurb=(
            "Free for the club, for ever. Unlimited teams, staff and athletes. "
            "Parents who want the parent product buy it for their own child; "
            "everything a coach or an athlete needs is included."
        ),
    ),
    Plan(
        code="club",
        name="Club",
        price_cents=39900,
        included_seats=600,
        extra_seat_cents=55,
        max_teams=0,
        max_staff=0,
        blurb="Large clubs and districts. Unlimited teams and staff.",
    ),
)

PLANS_BY_CODE = {p.code: p for p in PLANS}
FREE_PLAN = PLANS_BY_CODE["free"]


def get_plan(code: str) -> Plan:
    plan = PLANS_BY_CODE.get(code)
    if plan is None:
        raise BillingError(f"unknown plan: {code!r}")
    return plan


# ---------------------------------------------------------------------------
# Subscription state
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Usage:
    athletes: int = 0
    teams: int = 0
    staff: int = 0


@dataclass
class Subscription:
    org_id: int
    plan: Plan
    status: str = "trialing"
    seats_purchased: int = 0
    trial_ends_at: str | None = None
    period_start: str = ""
    period_end: str = ""
    usage: Usage = field(default_factory=Usage)

    @property
    def trial_days_left(self) -> int | None:
        if self.status != "trialing" or not self.trial_ends_at:
            return None
        try:
            ends = datetime.fromisoformat(self.trial_ends_at)
        except ValueError:
            return None
        return max(0, (ends.date() - _now().date()).days)

    @property
    def unlimited_seats(self) -> bool:
        """A household-paid plan does not meter the club at all.

        Metering a club that is not being charged would be pure friction: it
        would stop a director importing their roster to protect revenue that
        does not exist.
        """
        return self.plan.payer == PAYER_HOUSEHOLD

    @property
    def seat_limit(self) -> int:
        """Seats the program may fill: whatever the plan includes, or more if
        they have deliberately bought extra."""
        if self.unlimited_seats:
            return 10 ** 9
        return max(self.plan.included_seats, self.seats_purchased)

    @property
    def seats_remaining(self) -> int:
        return max(0, self.seat_limit - self.usage.athletes)

    @property
    def over_seats(self) -> bool:
        if self.unlimited_seats:
            return False
        return self.usage.athletes > self.seat_limit + SEAT_GRACE

    @property
    def can_grow(self) -> bool:
        """Whether the program may add anything new.

        Note what this does *not* gate: training, viewing, coaching, or safety
        advisories. Only growth.
        """
        if self.status == "canceled":
            return False
        if self.status == "past_due":
            return False
        return not self.over_seats

    @property
    def monthly_cents(self) -> int:
        if self.unlimited_seats:
            return 0
        return self.plan.seat_cost_cents(max(self.usage.athletes, self.plan.included_seats))

    def to_dict(self) -> dict[str, Any]:
        return {
            "org_id": self.org_id,
            "plan": self.plan.to_dict(),
            "status": self.status,
            "trial_days_left": self.trial_days_left,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "usage": {
                "athletes": self.usage.athletes,
                "teams": self.usage.teams,
                "staff": self.usage.staff,
            },
            "seat_limit": self.seat_limit,
            "seats_remaining": None if self.unlimited_seats else self.seats_remaining,
            "payer": self.plan.payer,
            "over_seats": self.over_seats,
            "can_grow": self.can_grow,
            "monthly_cents": self.monthly_cents,
            "monthly_display": f"${self.monthly_cents / 100:,.2f}",
        }


def measure_usage(conn: sqlite3.Connection, org_id: int) -> Usage:
    """What the program is actually using right now.

    Athletes are counted from memberships rather than sessions: a club is
    billed for the roster it maintains, not for how much any individual
    trained, and billing that punishes a quiet week would be a strange
    incentive to build into a training product.
    """
    def count(sql: str) -> int:
        return int(conn.execute(sql, (org_id,)).fetchone()[0])

    return Usage(
        athletes=count(
            "SELECT COUNT(*) FROM memberships m JOIN users u ON u.id = m.user_id "
            "WHERE m.org_id = ? AND m.role = 'athlete' AND m.active = 1 AND u.active = 1"
        ),
        teams=count("SELECT COUNT(*) FROM teams WHERE org_id = ?"),
        staff=count(
            "SELECT COUNT(*) FROM memberships m JOIN users u ON u.id = m.user_id "
            "WHERE m.org_id = ? AND m.role IN ('coach','director') "
            "AND m.active = 1 AND u.active = 1"
        ),
    )


def get_subscription(conn: sqlite3.Connection, org_id: int) -> Subscription:
    """The program's subscription, defaulting to the free plan.

    A program with no row is not broken and is not blocked; it is on the free
    plan. Requiring a billing record before anyone can train would make the
    first five minutes of the product about payment.
    """
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE org_id = ?", (org_id,)
    ).fetchone()
    usage = measure_usage(conn, org_id)

    if row is None:
        start = _now()
        return Subscription(
            org_id=org_id,
            plan=FREE_PLAN,
            status="active",
            period_start=_iso(start),
            period_end=_iso(start + timedelta(days=30)),
            usage=usage,
        )

    plan = PLANS_BY_CODE.get(row["plan_code"], FREE_PLAN)
    subscription = Subscription(
        org_id=org_id,
        plan=plan,
        status=row["status"],
        seats_purchased=int(row["seats_purchased"]),
        trial_ends_at=row["trial_ends_at"],
        period_start=row["period_start"],
        period_end=row["period_end"],
        usage=usage,
    )

    # A trial that has run out is past due, not indefinitely free.
    if subscription.status == "trialing" and subscription.trial_days_left == 0:
        subscription.status = "past_due"
    return subscription


def start_subscription(
    conn: sqlite3.Connection,
    org_id: int,
    plan_code: str,
    *,
    trial: bool = True,
    seats: int = 0,
    actor: str = "system",
) -> Subscription:
    plan = get_plan(plan_code)
    now = _now()
    trial_ends = _iso(now + timedelta(days=TRIAL_DAYS)) if trial and not plan.is_free else None

    conn.execute(
        "INSERT INTO subscriptions(org_id, plan_code, status, seats_purchased, "
        "trial_ends_at, period_start, period_end, updated_at) VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(org_id) DO UPDATE SET plan_code=excluded.plan_code, "
        "  status=excluded.status, seats_purchased=excluded.seats_purchased, "
        "  trial_ends_at=excluded.trial_ends_at, period_end=excluded.period_end, "
        "  updated_at=excluded.updated_at",
        (
            org_id, plan.code,
            "trialing" if trial_ends else "active",
            seats, trial_ends, _iso(now), _iso(now + timedelta(days=30)), _iso(now),
        ),
    )
    record_event(
        conn, org_id, "plan_change",
        f"Moved to {plan.name} by {actor}", seats=seats,
    )
    conn.commit()
    return get_subscription(conn, org_id)


def set_status(
    conn: sqlite3.Connection, org_id: int, status: str, actor: str = "system"
) -> Subscription:
    if status not in ("trialing", "active", "past_due", "canceled"):
        raise BillingError(f"unknown status: {status!r}")
    conn.execute(
        "UPDATE subscriptions SET status = ?, updated_at = ? WHERE org_id = ?",
        (status, _iso(_now()), org_id),
    )
    record_event(conn, org_id, "status_change", f"{status} ({actor})")
    conn.commit()
    return get_subscription(conn, org_id)


def record_event(
    conn: sqlite3.Connection,
    org_id: int,
    kind: str,
    detail: str = "",
    amount_cents: int = 0,
    seats: int = 0,
) -> None:
    conn.execute(
        "INSERT INTO billing_events(org_id, kind, detail, amount_cents, seats, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (org_id, kind, detail, amount_cents, seats, _iso(_now())),
    )


def history(conn: sqlite3.Connection, org_id: int, limit: int = 50) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT kind, detail, amount_cents, seats, created_at FROM billing_events "
            "WHERE org_id = ? ORDER BY created_at DESC LIMIT ?",
            (org_id, limit),
        )
    ]


# ---------------------------------------------------------------------------
# Entitlements
# ---------------------------------------------------------------------------

def check_can_add_athletes(
    conn: sqlite3.Connection, org_id: int, count: int = 1
) -> None:
    """Raise if adding `count` athletes would exceed what the plan allows."""
    subscription = get_subscription(conn, org_id)

    if subscription.status == "canceled":
        raise BillingError(
            "This program's subscription is canceled. Existing athletes keep "
            "training; reactivate the plan to add new ones."
        )
    if subscription.status == "past_due":
        raise BillingError(
            "This program's payment is overdue. Nobody has been locked out and "
            "training continues as normal, but new athletes cannot be added "
            "until it is settled."
        )

    projected = subscription.usage.athletes + count
    if projected > subscription.seat_limit + SEAT_GRACE:
        need = projected - subscription.seat_limit
        raise BillingError(
            f"{subscription.plan.name} includes {subscription.seat_limit} athletes "
            f"and this program has {subscription.usage.athletes}. Adding {count} "
            f"needs {need} more seat{'s' if need != 1 else ''} — upgrade the plan "
            "or remove inactive athletes."
        )


def check_can_add_team(conn: sqlite3.Connection, org_id: int) -> None:
    subscription = get_subscription(conn, org_id)
    plan = subscription.plan
    if not subscription.can_grow:
        raise BillingError(
            "This program cannot add teams until its billing is up to date. "
            "Existing teams are unaffected."
        )
    if plan.max_teams and subscription.usage.teams >= plan.max_teams:
        raise BillingError(
            f"{plan.name} includes {plan.max_teams} "
            f"team{'s' if plan.max_teams != 1 else ''}. Upgrade to add more."
        )


def check_can_add_staff(conn: sqlite3.Connection, org_id: int) -> None:
    subscription = get_subscription(conn, org_id)
    plan = subscription.plan
    if not subscription.can_grow:
        raise BillingError(
            "This program cannot add staff until its billing is up to date."
        )
    if plan.max_staff and subscription.usage.staff >= plan.max_staff:
        raise BillingError(
            f"{plan.name} includes {plan.max_staff} staff accounts. Upgrade to add more."
        )


def quote(conn: sqlite3.Connection, org_id: int, plan_code: str) -> dict[str, Any]:
    """What a given plan would cost this program at its current size."""
    plan = get_plan(plan_code)
    usage = measure_usage(conn, org_id)
    billable = max(usage.athletes, 0)
    extra = max(0, billable - plan.included_seats)
    total = plan.seat_cost_cents(billable)

    fits = (
        (not plan.max_teams or usage.teams <= plan.max_teams)
        and (not plan.max_staff or usage.staff <= plan.max_staff)
    )
    return {
        "plan": plan.to_dict(),
        "athletes": billable,
        "included_seats": plan.included_seats,
        "extra_seats": extra,
        "base_cents": plan.price_cents,
        "extra_cents": extra * plan.extra_seat_cents,
        "total_cents": total,
        "total_display": f"${total / 100:,.2f}",
        "per_athlete_display": (
            f"${total / billable / 100:,.2f}" if billable else "—"
        ),
        "fits_current_usage": fits,
    }


def recommend(conn: sqlite3.Connection, org_id: int) -> str:
    """The cheapest plan that actually fits this program."""
    usage = measure_usage(conn, org_id)
    for plan in PLANS:
        seats_ok = usage.athletes <= plan.included_seats
        teams_ok = not plan.max_teams or usage.teams <= plan.max_teams
        staff_ok = not plan.max_staff or usage.staff <= plan.max_staff
        if seats_ok and teams_ok and staff_ok:
            return plan.code
    return PLANS[-1].code


# ---------------------------------------------------------------------------
# Payment gateway seam
# ---------------------------------------------------------------------------

class Gateway(Protocol):
    """Where a payment processor plugs in.

    Kept as a protocol so the billing model above stays testable without
    network access or a vendor account, and so the choice of processor is a
    late decision rather than one baked through the codebase.
    """

    def charge(self, org_id: int, amount_cents: int, description: str) -> dict[str, Any]:
        ...


class ManualGateway:
    """Records the charge without taking payment.

    The default, and not a placeholder: youth clubs overwhelmingly pay by
    invoice or purchase order, so "raise it, mark it paid when the cheque
    clears" is the real workflow for most of them.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def charge(self, org_id: int, amount_cents: int, description: str) -> dict[str, Any]:
        record_event(self.conn, org_id, "invoice", description, amount_cents=amount_cents)
        self.conn.commit()
        return {
            "captured": False,
            "amount_cents": amount_cents,
            "note": "Recorded as an invoice. No card was charged.",
        }


def backfill_subscriptions(conn: sqlite3.Connection) -> int:
    """Give programs that predate billing a plan that fits what they already run.

    Retroactively paywalling an existing customer -- telling a club with six
    teams that they are now on a one-team plan -- is the wrong way to introduce
    billing to people already using the thing.
    """
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='subscriptions'"
    ).fetchone():
        return 0

    made = 0
    for row in conn.execute(
        "SELECT id FROM organizations WHERE id NOT IN (SELECT org_id FROM subscriptions)"
    ).fetchall():
        start_subscription(
            conn, row["id"], recommend(conn, row["id"]),
            trial=False, actor="migration",
        )
        made += 1
    return made


def run_billing_cycle(
    conn: sqlite3.Connection, gateway: Gateway | None = None, today: date | None = None
) -> list[dict[str, Any]]:
    """Raise this period's charge for every paid program whose period has ended."""
    today = today or _now().date()
    gateway = gateway or ManualGateway(conn)
    raised = []

    for row in conn.execute(
        "SELECT org_id FROM subscriptions WHERE status IN ('active','trialing')"
    ).fetchall():
        subscription = get_subscription(conn, row["org_id"])
        if subscription.plan.is_free:
            continue
        try:
            period_end = datetime.fromisoformat(subscription.period_end).date()
        except ValueError:
            continue
        if period_end > today:
            continue

        amount = subscription.monthly_cents
        result = gateway.charge(
            subscription.org_id, amount,
            f"{subscription.plan.name} — {subscription.usage.athletes} athletes",
        )
        conn.execute(
            "UPDATE subscriptions SET period_start = ?, period_end = ?, "
            "status = CASE WHEN status = 'trialing' THEN 'active' ELSE status END, "
            "updated_at = ? WHERE org_id = ?",
            (
                _iso(_now()), _iso(_now() + timedelta(days=30)),
                _iso(_now()), subscription.org_id,
            ),
        )
        raised.append({"org_id": subscription.org_id, "amount_cents": amount, **result})

    conn.commit()
    return raised

# ---------------------------------------------------------------------------
# What a parent pays, under a club-free plan
#
# Priced against what a youth-sports family is already spending rather than
# against what the software costs to run. A club season runs into four figures;
# an add-on that a parent has to think about is an add-on they decline, so this
# sits at the level of a couple of coffees and is charged once a season rather
# than monthly.
#
# Seasonal, not monthly, for three reasons. Youth sports is seasonal and
# parents already budget that way. Monthly billing invites a cancellation
# decision twelve times a year instead of two. And a monthly card failure in
# February would put a support burden on a club that is paying nothing.
# ---------------------------------------------------------------------------

#: One season, in months. Five covers a typical club season with the shoulder
#: weeks either side.
SEASON_MONTHS = 5

#: Per athlete, per season. The second child in a household is discounted and
#: the third onward is free: a family with three children in a club is already
#: the one paying the most, and charging them three times over is how a
#: product acquires a reputation among exactly the parents who talk to other
#: parents.
HOUSEHOLD_SEASON_CENTS = 2900
HOUSEHOLD_SIBLING_CENTS = 1900
HOUSEHOLD_FREE_FROM_CHILD = 3

#: For a family that would rather pay monthly. Deliberately worse value than a
#: season, and deliberately not much worse -- a punitive gap would just read as
#: a trap.
HOUSEHOLD_MONTHLY_CENTS = 800

# There is deliberately no separate sponsorship price. Pricing one was a
# mistake worth recording: at $19 an athlete it came out between 2.5x and 5.7x
# more expensive than simply buying the seat-metered plan that fits the same
# roster, so no club would ever rationally have chosen it. A club that wants to
# cover its families buys Team, Program or Club -- those plans include the
# parent product for every athlete in them, which is what paying for seats
# should mean. Sponsorship survives as a mechanism for a club-free program
# quietly covering particular families, and costs that program nothing.

#: How a family got their entitlement.
SOURCE_PAID = "paid"
SOURCE_SPONSORED = "sponsored"
SOURCE_HARDSHIP = "hardship"
SOURCE_TRIAL = "trial"

#: A new family gets the parent product for a season's first weeks without
#: paying, so the monthly report they are being asked to buy is one they have
#: actually read.
HOUSEHOLD_TRIAL_DAYS = 21


def household_price_cents(child_index: int) -> int:
    """Season price for the nth child in one household, 1-based."""
    if child_index >= HOUSEHOLD_FREE_FROM_CHILD:
        return 0
    return HOUSEHOLD_SEASON_CENTS if child_index <= 1 else HOUSEHOLD_SIBLING_CENTS


def household_quote(children: int) -> dict[str, Any]:
    """What a household with this many athletes would pay for a season."""
    lines = [
        {"child": i + 1, "cents": household_price_cents(i + 1)}
        for i in range(max(0, children))
    ]
    total = sum(line["cents"] for line in lines)
    return {
        "children": children,
        "lines": lines,
        "season_total_cents": total,
        "season_total_display": f"${total / 100:,.2f}",
        "monthly_alternative_cents": HOUSEHOLD_MONTHLY_CENTS * max(0, children),
        "per_month_equivalent_cents": round(total / SEASON_MONTHS) if children else 0,
    }


def household_subscription(
    conn: sqlite3.Connection, athlete_id: int
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM household_subscriptions WHERE athlete_id = ?",
        (athlete_id,),
    ).fetchone()
    return dict(row) if row else None


def start_household(
    conn: sqlite3.Connection,
    athlete_id: int,
    *,
    source: str = SOURCE_PAID,
    days: int | None = None,
    actor: str = "system",
    today: date | None = None,
) -> dict[str, Any]:
    """Give this child's family the parent product.

    Per athlete rather than per guardian: a household with two children in
    different clubs is one family and two entitlements, and a guardian-level
    subscription would have to invent an answer for which club it applied to.
    """
    if source not in (SOURCE_PAID, SOURCE_SPONSORED, SOURCE_HARDSHIP,
                      SOURCE_TRIAL):
        raise BillingError(f"unknown entitlement source: {source!r}")

    today = today or _now().date()
    span = days if days is not None else (
        HOUSEHOLD_TRIAL_DAYS if source == SOURCE_TRIAL else SEASON_MONTHS * 30
    )
    end = today + timedelta(days=span)
    conn.execute(
        "INSERT INTO household_subscriptions(athlete_id, source, status, "
        "  period_start, period_end, updated_at) VALUES (?,?,'active',?,?,?) "
        "ON CONFLICT(athlete_id) DO UPDATE SET source = excluded.source, "
        "  status = 'active', period_start = excluded.period_start, "
        "  period_end = excluded.period_end, updated_at = excluded.updated_at",
        (athlete_id, source, today.isoformat(), end.isoformat(), _iso(_now())),
    )
    conn.commit()
    return household_subscription(conn, athlete_id) or {}


def grant_hardship(
    conn: sqlite3.Connection, athlete_id: int, actor: str = "self"
) -> dict[str, Any]:
    """The parent product, free, no questions, no coach involved.

    Self-service and silent by design. A family that has to ask their child's
    coach for a discount is a family that will not ask, and this product
    already promises it does not score what a household can afford -- a
    hardship path that ran through the club would make that promise hollow.

    Indistinguishable from a paid entitlement everywhere a coach can see, which
    is the point rather than a side effect.
    """
    return start_household(
        conn, athlete_id, source=SOURCE_HARDSHIP,
        days=SEASON_MONTHS * 30, actor=actor,
    )


def sponsor_athletes(
    conn: sqlite3.Connection, org_id: int, athlete_ids: list[int] | None = None
) -> int:
    """Cover the parent product for particular athletes, free.

    For a club-free program that wants to quietly cover some families -- the
    scaled-up version of the hardship path, decided by a director who knows
    their community rather than by a family having to ask.

    A club that wants to cover *everybody* should buy a seat plan instead;
    those include the parent product by definition. This is not a cheaper
    route to the same thing, and pricing it as one was wrong.
    """
    if athlete_ids is None:
        athlete_ids = [
            int(r["user_id"])
            for r in conn.execute(
                "SELECT m.user_id FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.org_id = ? AND m.role = 'athlete' AND m.active = 1 "
                "AND u.active = 1",
                (org_id,),
            )
        ]
    for athlete_id in athlete_ids:
        start_household(conn, athlete_id, source=SOURCE_SPONSORED)
    return len(athlete_ids)


def expire_households(conn: sqlite3.Connection, today: date | None = None) -> int:
    """Lapse households whose season has ended.

    Lapsing is quiet and costs a child nothing: training, safety, consent and
    everything a coach sees carry on untouched. What stops is the parent
    product. Nobody is told, least of all a coach.
    """
    today = (today or _now().date()).isoformat()
    with conn:
        return conn.execute(
            "UPDATE household_subscriptions SET status = 'lapsed' "
            "WHERE status = 'active' AND period_end < ?",
            (today,),
        ).rowcount

