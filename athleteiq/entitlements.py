"""What a family's payment buys, and — far more importantly — what it cannot.

The club tier is free to the club. A director signs up, imports a roster, and
is never invoiced. Parents who want the parent-facing product pay for their own
child.

That model has one well-known way of failing, and the failure is structural
rather than commercial. If what a *coach* sees depends on which parents paid,
then a club at 40% adoption has a 40%-populated dashboard — which is useless,
so the coach stops opening it, so the club drops the product, so nobody pays at
all. Parent-paid club software dies of partial adoption, not of price.

So the line is drawn by **who consumes a feature**, not by how valuable it is:

* Everything a coach touches is free forever. Roster, assignments, compliance,
  the pre-practice card, the digest, the evaluation export. A club at zero
  paying parents has the complete coaching product, and one at ninety per cent
  has exactly the same one.
* Everything that keeps a child safe is free forever. Soreness reporting, the
  return-to-play ramp, load advisories, the adaptive accommodations. Charging
  a family for injury prevention for a child is indefensible, and charging for
  accessibility doubly so.
* Everything that is a right rather than a feature is free forever. Consent,
  data export, erasure, and the guardian's copy of every message their child
  receives. A parent behind on a payment does not lose the ability to see what
  is being said to their kid.
* **A child can always train.** That rule predates this file and outranks it.

What is left — the monthly report, the history beyond a month, peer context,
film study, shared clips, other-sport tracking — is the parent product. A
family that does not buy it loses nothing their child needs and nothing their
coach relies on.

One consequence is deliberate and worth stating: **no coach-facing surface ever
reveals which families pay.** Not a badge, not a count, not a sorted list. This
product already promises it does not score family resources; a dashboard that
quietly showed a coach which children came from paying households would make
that promise false in the one place it matters most.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any


class Tier:
    #: Free for everyone, for ever, and not switchable. See `FREE_REASONS`.
    FREE = "free"
    #: What a parent buys for their own child.
    HOUSEHOLD = "household"


class Audience:
    ATHLETE = "athlete"
    COACH = "coach"
    PARENT = "parent"


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    tier: str
    audience: str
    blurb: str = ""

    @property
    def paid(self) -> bool:
        return self.tier == Tier.HOUSEHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "tier": self.tier,
            "audience": self.audience,
            "blurb": self.blurb,
        }


#: Why each free feature is free. Kept as prose rather than a comment because
#: these are the commitments, and a test asserts every free feature has one --
#: which makes moving a feature behind the paywall a change somebody has to
#: argue for in a diff rather than a one-word edit.
FREE_REASONS: dict[str, str] = {
    "train": "A child can always train. An adult's payment problem is not a "
             "reason to lock a fourteen-year-old out of their streak.",
    "coach_roster": "If what a coach sees depended on which parents paid, a "
                    "club at partial adoption would have a partial dashboard "
                    "— and would drop the product.",
    "coach_assignments": "A coach prescribing work cannot have it land for "
                         "some of the squad and not others depending on whose "
                         "parents paid. Half a compliance table is worse than "
                         "none.",
    "coach_practice": "This is read on a field ninety seconds before a "
                      "session, and it decides who trains and how. A card "
                      "missing the children whose families did not pay would "
                      "be actively dangerous.",
    "coach_digest": "The digest measures a squad, and its headline metric is "
                    "participation. Counting only paying families would make "
                    "the one number this product asks a team to move a "
                    "measurement of household income instead.",
    "coach_evaluation": "A selection document covering only the families who "
                        "could pay is far worse than no selection document. "
                        "This is the surface where charging would do the most "
                        "damage of anywhere in the product.",
    "wellness": "Charging a family for a child to report that they are hurt "
                "is indefensible, and it would make the whole subsystem "
                "useless: an unpaid child who stays quiet is the outcome.",
    "return_to_play": "A ramp back from injury needs a named adult, not a "
                      "receipt.",
    "load": "Overuse protection is the safety floor. It is not an upsell.",
    "adaptive": "Charging for accessibility is indefensible. An athlete the "
                "camera was not built for already gets less from this product, "
                "not more.",
    "technique": "Form scoring without the fix is a mark out of ten. Telling a "
                 "child they are wrong and charging to say how to be right is "
                 "the worst possible thing to put behind a paywall.",
    "consent": "Consent and data rights are rights, not features.",
    "data_export": "A family's own data is theirs whether or not they are "
                   "current.",
    "guardian_alerts": "Every message a child receives is copied to their "
                       "guardian. A lapsed payment does not stop a parent "
                       "seeing what is said to their kid.",
    "recognition": "A coach's recognition is the coach's to give.",
    "team_goals": "A squad number that only counted paying families would be "
                  "a strange thing to ask a team to chase.",
    "absence": "A holiday is not a premium event.",
}


FEATURES: tuple[Feature, ...] = (
    # -- Free for everyone, for ever ---------------------------------------
    Feature("train", "Training and streaks", Tier.FREE, Audience.ATHLETE,
            "Record drills, counts, streaks, XP and badges."),
    Feature("technique", "Technique cues and reference", Tier.FREE,
            Audience.ATHLETE, "What a good rep looks like, per drill."),
    Feature("wellness", "Soreness and injury reporting", Tier.FREE,
            Audience.ATHLETE, "Telling the truth is always free."),
    Feature("return_to_play", "Return-to-play ramp", Tier.FREE,
            Audience.ATHLETE, "Coming back after an injury."),
    Feature("load", "Load and overuse advisories", Tier.FREE,
            Audience.ATHLETE, "The safety floor."),
    Feature("adaptive", "Adaptive accommodations", Tier.FREE, Audience.ATHLETE,
            "For athletes the camera was not built for."),
    Feature("absence", "Planned absence", Tier.FREE, Audience.PARENT,
            "Pause a streak for a holiday."),
    Feature("team_goals", "Squad goals", Tier.FREE, Audience.ATHLETE,
            "One number a team chases together."),
    Feature("recognition", "Coach recognition messages", Tier.FREE,
            Audience.ATHLETE, "Milestones, in a coach's own words."),
    Feature("coach_roster", "Coach dashboard and roster", Tier.FREE,
            Audience.COACH, "Everything a coach sees about their squad."),
    Feature("coach_assignments", "Assignments and compliance", Tier.FREE,
            Audience.COACH, "Prescribe work, see who did it."),
    Feature("coach_practice", "The pre-practice card", Tier.FREE,
            Audience.COACH, "The ninety seconds before a session."),
    Feature("coach_digest", "Weekly team digest", Tier.FREE, Audience.COACH,
            "The dashboard that goes to them."),
    Feature("coach_evaluation", "Evaluation export", Tier.FREE, Audience.COACH,
            "The tryout artifact."),
    Feature("consent", "Consent and permissions", Tier.FREE, Audience.PARENT,
            "What a guardian agrees to, and can withdraw."),
    Feature("data_export", "Data export and erasure", Tier.FREE,
            Audience.PARENT, "Your child's record is yours."),
    Feature("guardian_alerts", "Copies of every message", Tier.FREE,
            Audience.PARENT, "Everything your child is sent, you are sent."),

    # -- What a parent buys, for their own child ---------------------------
    Feature("parent_report", "The monthly report", Tier.HOUSEHOLD,
            Audience.PARENT,
            "What your child actually did last month, and what improved."),
    Feature("history", "Full history and trends", Tier.HOUSEHOLD,
            Audience.PARENT,
            "Beyond the last 30 days: the whole season, and the shape of it."),
    Feature("peer_context", "How they compare for their age", Tier.HOUSEHOLD,
            Audience.PARENT,
            "Percentile context against their age band — never against "
            "named teammates."),
    Feature("film", "Film study", Tier.HOUSEHOLD, Audience.ATHLETE,
            "Short clips with audio feedback, capped by age."),
    Feature("shared_clips", "Coach video review", Tier.HOUSEHOLD,
            Audience.ATHLETE,
            "Send a coach one clip for feedback. Requires consent too."),
    Feature("multi_sport", "Other sports and transfer", Tier.HOUSEHOLD,
            Audience.ATHLETE,
            "What every drill is worth in their other sports."),
)

BY_KEY = {f.key: f for f in FEATURES}
FREE_KEYS = frozenset(f.key for f in FEATURES if f.tier == Tier.FREE)
HOUSEHOLD_KEYS = frozenset(f.key for f in FEATURES if f.tier == Tier.HOUSEHOLD)

#: How much history a family sees without the household plan. Generous on
#: purpose: a month is long enough that a child's own progress is visible and
#: the limit is felt by a parent looking back over a season, which is exactly
#: who the paid product is for.
FREE_HISTORY_DAYS = 30


@dataclass
class Entitlement:
    athlete_id: int
    #: paid | sponsored | hardship | trial | none
    source: str = "none"
    active: bool = False

    def has(self, key: str) -> bool:
        """Whether this child's family has a feature.

        Anything free is free regardless of the entitlement, and that is
        enforced here rather than at each call site -- one function every gate
        passes through is the difference between a rule and an intention.
        """
        if key in FREE_KEYS:
            return True
        if key not in BY_KEY:
            raise KeyError(f"unknown feature: {key!r}")
        return self.active

    @property
    def history_days(self) -> int | None:
        """None means unlimited."""
        return None if self.has("history") else FREE_HISTORY_DAYS

    def to_dict(self) -> dict[str, Any]:
        return {
            "athlete_id": self.athlete_id,
            "active": self.active,
            # Shown to the family, never to a coach. See the module docstring.
            "source": self.source,
            "features": {f.key: self.has(f.key) for f in FEATURES},
            "history_days": self.history_days,
        }


def _org_covers(conn: sqlite3.Connection, athlete_id: int) -> bool:
    """Whether this athlete's club is on a plan that already includes it.

    A club paying for seats is paying for the whole product, families
    included. This is why there is no separate sponsorship price: a club that
    wants to cover its parents buys the seat plan it was already going to
    buy, rather than choosing between two numbers where one is always worse.
    """
    from . import billing

    row = conn.execute(
        "SELECT s.plan_code FROM users u "
        "JOIN subscriptions s ON s.org_id = u.org_id "
        "WHERE u.id = ? AND s.status IN ('active','trialing')",
        (athlete_id,),
    ).fetchone()
    if row is None:
        return False
    plan = billing.PLANS_BY_CODE.get(row["plan_code"])
    return bool(plan and plan.payer == billing.PAYER_PROGRAM
                and plan.price_cents > 0)


def for_athlete(
    conn: sqlite3.Connection, athlete_id: int, today: str | None = None
) -> Entitlement:
    """What this child's family currently has.

    Three routes in, and they are indistinguishable to a coach: the family
    bought it, the club is on a paid plan that includes it, or it was granted
    -- as hardship, or because the club chose to cover that athlete.
    """
    from datetime import date

    today = today or date.today().isoformat()
    if _org_covers(conn, athlete_id):
        return Entitlement(
            athlete_id=athlete_id, source="included", active=True)

    row = conn.execute(
        "SELECT source, status, period_end FROM household_subscriptions "
        "WHERE athlete_id = ?",
        (athlete_id,),
    ).fetchone()
    if row is None:
        return Entitlement(athlete_id=athlete_id)

    active = row["status"] == "active" and (
        not row["period_end"] or row["period_end"] >= today
    )
    return Entitlement(
        athlete_id=athlete_id,
        source=row["source"] if active else "none",
        active=active,
    )


def catalog() -> dict[str, Any]:
    """The whole feature line, for a pricing page that has to be honest.

    Published rather than described in marketing copy: a family deciding
    whether to pay should be able to read exactly what they are and are not
    buying, and every free feature carries the reason it is free.
    """
    return {
        "free_history_days": FREE_HISTORY_DAYS,
        "free": [
            {**f.to_dict(), "why_free": FREE_REASONS.get(f.key, "")}
            for f in FEATURES if f.tier == Tier.FREE
        ],
        "household": [f.to_dict() for f in FEATURES if f.paid],
    }
