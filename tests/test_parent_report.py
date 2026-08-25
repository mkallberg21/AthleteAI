"""The monthly report a guardian gets about their own child.

The weekly team digest names nobody on purpose -- it gets forwarded, pasted
into team channels, and read aloud in car parks. This is the opposite object:
one household, one child, and naming them is the point. That inversion is why
it needs its own rules rather than a filter on the digest, and the rules are
what most of this file tests.

The load-bearing one is that a child is never compared to their teammates.
This product refuses volume comparison between children everywhere, and a
parent report is both the easiest place to quietly drop that refusal and the
most damaging place to drop it -- it is the document that gets held up at a
kitchen table next to a sibling's.
"""
from __future__ import annotations

import random
from datetime import date

import pytest

from athleteiq import billing, guardians as guardians_mod
from athleteiq import notifications, parent_report
from athleteiq.db import connect
from athleteiq.store import Store

TODAY = date(2026, 8, 25)          # so "last complete month" is July 2026
JULY = (date(2026, 7, 2), date(2026, 7, 5), date(2026, 7, 9), date(2026, 7, 13),
        date(2026, 7, 17), date(2026, 7, 21), date(2026, 7, 25), date(2026, 7, 29))
JUNE = (date(2026, 6, 4), date(2026, 6, 11), date(2026, 6, 18))


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "p.db"))


@pytest.fixture
def family(store):
    org = store.create_org("Northshore")
    director = store.create_user(org, "director", "Coach Ada")
    team = store.create_team(org, "U15 Boys")
    kid = store.create_user(
        org, "athlete", "Jordan Pierce", birth_year=2011, dominant_hand="right"
    )
    store.join_team(team["join_code"], kid["id"])
    invite = guardians_mod.create_invite(store.conn, kid["id"], director["id"])
    parent = guardians_mod.redeem_invite(
        store.conn, invite["code"], "Sam Pierce", "sam@example.com"
    )
    # Linking a guardian pauses training until they say yes -- correctly, and
    # a fixture that skips it is testing an account that cannot train.
    guardians_mod.set_consent(
        store.conn, kid["id"], parent["guardian_id"],
        guardians_mod.Scope.PARTICIPATION, True,
    )
    # The report is part of the parent plan under a club-free tier. These
    # tests are about what the report says, so they buy it; whether it is
    # gated correctly is tested in test_entitlements.py.
    billing.start_household(store.conn, kid["id"])
    return {"org": org, "director": director, "team": team,
            "kid": kid, "parent": parent}


def train(store, kid, day, drill="gen_squat", rom=74.0, seed=None):
    """One real session, back-dated. Timings are jittered because the
    integrity layer rejects metronomic reps as fabricated -- correctly."""
    rng = random.Random(seed if seed is not None else day.toordinal())
    started = store.start_session(kid["id"], drill)
    t, reps = 0, []
    for i in range(24):
        t += max(600, int(rng.gauss(1500, 220)))
        value = rom + rng.uniform(-3, 3)
        reps.append({
            "t_ms": t, "hand": "left" if i % 2 else "right", "confidence": 0.9,
            "rom": value, "peak": value, "cycle_ms": 1150 + rng.randint(-120, 120),
        })
    store.submit_session(
        kid["id"], started["session_id"], started["nonce"],
        duration_ms=t + 900, reps=reps, mean_confidence=0.9,
    )
    store.conn.execute(
        "UPDATE sessions SET submitted_at = ? WHERE id = ?",
        (day.isoformat() + "T18:00:00+00:00", started["session_id"]),
    )
    store.conn.commit()


class TestItCoversTheMonthThatFinished:
    def test_the_window_is_the_last_complete_month(self):
        """A report about the month you are standing in changes after you
        read it, which is not a report."""
        assert parent_report.last_complete_month(TODAY) == (
            date(2026, 7, 1), date(2026, 7, 31))

    def test_january_looks_back_into_the_previous_year(self):
        assert parent_report.last_complete_month(date(2027, 1, 9)) == (
            date(2026, 12, 1), date(2026, 12, 31))

    def test_this_months_sessions_are_not_counted_yet(self, store, family):
        train(store, family["kid"], date(2026, 8, 3))
        train(store, family["kid"], date(2026, 7, 3))
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        assert report.current.sessions == 1


class TestNoChildIsComparedToAnother:
    """The refusal this product makes everywhere, made in the one document
    where dropping it would be easiest and would do the most damage."""

    def test_nothing_in_the_report_mentions_teammates(self, store, family):
        for day in JULY:
            train(store, family["kid"], day)
        # A teammate who did far more, so a rank would be tempting to compute.
        mate = store.create_user(
            family["org"], "athlete", "Alex Okafor", birth_year=2011,
            dominant_hand="right",
        )
        store.join_team(family["team"]["join_code"], mate["id"])
        for day in JULY * 2:
            train(store, mate, day, seed=day.toordinal() + 99)

        text = str(parent_report.build(
            store.conn, family["kid"]["id"], TODAY).to_dict()).lower()
        for word in ("teammate", "squad", "rank", "percentile", "average for",
                     "compared", "than other", "alex"):
            assert word not in text, f"the report compares children: {word!r}"

    def test_the_only_comparison_is_to_their_own_previous_month(
        self, store, family
    ):
        for day in JUNE:
            train(store, family["kid"], day)
        for day in JULY:
            train(store, family["kid"], day)
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        assert report.previous.sessions == len(JUNE)
        assert f"up from {report.previous.days}" in report.headline

    def test_the_footer_says_so_out_loud(self, store, family):
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        assert "do not rank children" in parent_report.render_html(report)
        assert "do not rank children" in parent_report.render_text(report)


class TestAQuietMonthIsHonestAndKind:
    def test_a_blank_month_is_reported_not_hidden(self, store, family):
        """A parent paying for this is owed the truth."""
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        assert report.current.sessions == 0
        assert "did not log any training" in report.headline

    def test_a_few_sessions_is_described_as_a_fact_not_a_failing(
        self, store, family
    ):
        """Two sessions in a month with exams on is a fact. The child did not
        do anything wrong, and a report that scolds them is one a parent stops
        opening -- which loses the child the reader they needed."""
        train(store, family["kid"], date(2026, 7, 8))
        train(store, family["kid"], date(2026, 7, 20))
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        assert report.quiet is True
        text = f"{report.headline} {' '.join(report.highlights)}".lower()
        for scold in ("only", "failed", "should have", "behind", "disappointing",
                      "not enough", "missed"):
            assert scold not in text, f"the quiet-month copy scolds: {scold!r}"

    def test_a_quiet_month_is_not_announced_in_the_subject_line(
        self, store, family
    ):
        """A notification preview is the last place a parent should first
        read a verdict on their child's month."""
        train(store, family["kid"], date(2026, 7, 8))
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        subject = parent_report.subject_line(report)
        assert "1 session" not in subject
        assert report.first_name in subject and report.month_label in subject

    def test_a_month_that_went_down_says_so_without_a_verdict(
        self, store, family
    ):
        for day in JUNE + (date(2026, 6, 24), date(2026, 6, 27)):
            train(store, family["kid"], day)      # 5 days in June
        for day in JULY[:4]:
            train(store, family["kid"], day)      # 4 in July
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        assert "down from" in report.headline
        assert "it is the year that matters" in report.headline

    def test_a_big_drop_is_named_even_when_the_month_was_quiet(
        self, store, family
    ):
        """Tone is why the quiet branch exists, but a parent going from
        twelve sessions to two is owed the fact. Swallowing it to stay gentle
        is how a report stops being honest."""
        for day in JUNE:
            for extra in range(4):
                train(store, family["kid"], day, seed=day.toordinal() * 10 + extra)
        train(store, family["kid"], date(2026, 7, 8))
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        assert report.quiet is True
        assert "down from" in report.headline


class TestWhatItCelebrates:
    def test_improvement_in_form_outranks_doing_more(self, store, family):
        """A number that only goes up with volume is the one metric this
        product will not celebrate on its own, because celebrating it teaches
        a child that more is always better."""
        for day in JUNE:
            train(store, family["kid"], day, rom=40.0)      # shallow
        for day in JULY:
            train(store, family["kid"], day, rom=76.0)      # good
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        assert report.highlights
        assert "form score improved" in report.highlights[0]

    def test_the_weak_side_gets_named_when_they_kept_it_up(self, store, family):
        for day in JULY:
            train(store, family["kid"], day)
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        assert any("weaker side" in h for h in report.highlights)

    def test_highlights_stay_short_enough_to_read(self, store, family):
        for day in JULY:
            train(store, family["kid"], day, drill="gen_push_up")
        for day in JULY[:4]:
            train(store, family["kid"], day, seed=1)
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        assert len(report.highlights) <= parent_report.MAX_HIGHLIGHTS


class TestNothingHereIsAMedicalClaim:
    def test_soreness_is_described_as_what_the_app_did(self, store, family):
        store.report_discomfort(
            family["kid"]["id"], "knee", "niggle", day=date(2026, 7, 10))
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        assert report.care
        assert "eased their training off" in report.care[0]

    def test_the_childs_own_note_is_never_carried(self, store, family):
        """A parent report is not a route around the note staying between the
        child and whoever they chose to tell."""
        store.report_discomfort(
            family["kid"]["id"], "knee", "niggle", day=date(2026, 7, 10),
            note="it hurts when I think about the trials",
        )
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        assert "trials" not in str(report.to_dict())

    def test_it_does_not_read_as_news(self, store, family):
        """Anything needing a grown-up reached this household the day it
        happened. A monthly summary arriving as the first anyone hears of an
        injury would be a serious failure, so it must not sound like one."""
        store.report_discomfort(
            family["kid"]["id"], "knee", "hurts", day=date(2026, 7, 10))
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        text = " ".join(report.care).lower()
        for alarming in ("injury", "injured", "diagnos", "we detected",
                         "you should see"):
            assert alarming not in text, f"care copy reads as a diagnosis: {alarming!r}"


class TestSending:
    def test_one_report_per_child_per_month(self, store, family):
        for day in JULY:
            train(store, family["kid"], day)
        assert parent_report.generate(store.conn, TODAY) == 1
        # A nightly cron through the first week must not send seven.
        assert parent_report.generate(store.conn, TODAY) == 0
        assert parent_report.generate(store.conn, date(2026, 8, 29)) == 0

    def test_the_next_month_sends_again(self, store, family):
        parent_report.generate(store.conn, TODAY)
        assert parent_report.generate(store.conn, date(2026, 9, 4)) == 1

    def test_it_goes_to_the_guardian(self, store, family):
        parent_report.generate(store.conn, TODAY)
        row = store.conn.execute(
            "SELECT user_id, about_athlete_id FROM notifications "
            "WHERE dedupe_key LIKE 'parent_report:%'"
        ).fetchone()
        assert row["user_id"] == family["parent"]["guardian_id"]
        assert row["about_athlete_id"] == family["kid"]["id"]

    def test_it_is_not_copied_into_the_childs_own_alerts(self, store, family):
        """It is written for a parent. "A few sessions rather than a routine"
        reads very differently in a twelve-year-old's notifications."""
        train(store, family["kid"], date(2026, 7, 8))
        parent_report.generate(store.conn, TODAY)
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? "
            "AND dedupe_key LIKE 'parent_report:%'",
            (family["kid"]["id"],),
        ).fetchone()["n"] == 0

    def test_a_family_without_the_parent_plan_is_not_sent_one(
        self, store, family
    ):
        """The report is what the club-free tier sells. Emailing it to
        families who have not bought it gives the product away -- and sending
        a deliberately worse version instead would be a worse thing to put in
        a parent's inbox than sending nothing."""
        # On the club-free plan specifically. A new program starts on a
        # trial of a paid seat plan, and during a trial every family has the
        # parent product -- an evaluation shaped by limits the club would not
        # hit in practice is not an evaluation.
        billing.start_subscription(
            store.conn, family["org"], "club_free", trial=False)
        store.conn.execute("DELETE FROM household_subscriptions")
        store.conn.commit()
        assert parent_report.generate(store.conn, TODAY) == 0

    def test_but_a_club_on_a_paid_seat_plan_gets_them_for_everybody(
        self, store, family
    ):
        """What paying for seats means: the club covers its families."""
        billing.start_subscription(
            store.conn, family["org"], "program", trial=False)
        store.conn.execute("DELETE FROM household_subscriptions")
        store.conn.commit()
        assert parent_report.generate(store.conn, TODAY) == 1

    def test_a_child_with_no_guardian_produces_nothing(self, store, family):
        """There is no sensible fallback recipient for a report about a
        child, so an orphan notification is worse than none."""
        lonely = store.create_user(
            family["org"], "athlete", "No Guardian", birth_year=2011,
            dominant_hand="right",
        )
        store.join_team(family["team"]["join_code"], lonely["id"])
        parent_report.generate(store.conn, TODAY)
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE about_athlete_id = ? "
            "AND dedupe_key LIKE 'parent_report:%'",
            (lonely["id"],),
        ).fetchone()["n"] == 0

    def test_the_scheduled_run_includes_it(self, store, family):
        assert "parent_reports" in notifications.run_all(store.conn, TODAY)


class TestRendering:
    def test_the_html_names_the_child_and_the_month(self, store, family):
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        html = parent_report.render_html(report)
        assert "Jordan Pierce" in html and "July 2026" in html

    def test_the_html_escapes_a_name_rather_than_rendering_it(self, store, family):
        store.conn.execute(
            "UPDATE users SET display_name = ? WHERE id = ?",
            ("<script>alert(1)</script>", family["kid"]["id"]),
        )
        store.conn.commit()
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        assert "<script>" not in parent_report.render_html(report)

    def test_empty_sections_are_left_out_rather_than_shown_blank(
        self, store, family
    ):
        report = parent_report.build(store.conn, family["kid"]["id"], TODAY)
        html = parent_report.render_html(report)
        assert "Looking after themselves" not in html
        assert "What their coach said" not in html


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
        "/api/orgs", json={"name": "Northshore LC", "director_name": "Dir Smith"}
    ).json()
    director = {"Authorization": f"Bearer {org['director']['token']}"}
    team = client.post("/api/teams", json={"name": "U15"}, headers=director).json()
    kid = client.post(
        "/api/athletes",
        json={"display_name": "Jordan Pierce", "birth_year": 2011,
              "dominant_hand": "right", "guardian_consent": True,
              "join_code": team["join_code"]},
        headers=director,
    ).json()
    invite = guardians_mod.create_invite(
        store.conn, kid["id"], store.authenticate(org["director"]["token"]).id)
    parent = guardians_mod.redeem_invite(
        store.conn, invite["code"], "Sam Pierce", "sam@example.com")
    guardians_mod.set_consent(
        store.conn, kid["id"], parent["guardian_id"],
        guardians_mod.Scope.PARTICIPATION, True,
    )
    billing.start_household(store.conn, kid["id"])
    return {"store": store, "kid": kid, "team": team, "director": director,
            "parent": {"Authorization": f"Bearer {parent['token']}"}}


class TestOverTheWire:
    def test_a_guardian_can_read_their_own_childs_report(self, client, wired):
        res = client.get(
            f"/api/parent/athletes/{wired['kid']['id']}/report",
            headers=wired["parent"],
        )
        assert res.status_code == 200
        assert res.json()["display_name"] == "Jordan Pierce"

    def test_the_preview_renders_the_email_itself(self, client, wired):
        res = client.get(
            f"/api/parent/athletes/{wired['kid']['id']}/report/preview",
            headers=wired["parent"],
        )
        assert res.status_code == 200
        assert "Jordan Pierce" in res.text

    def test_someone_elses_guardian_gets_nothing(self, client, wired):
        other = client.post(
            "/api/orgs", json={"name": "Southside", "director_name": "Other"}
        ).json()
        headers = {"Authorization": f"Bearer {other['director']['token']}"}
        res = client.get(
            f"/api/parent/athletes/{wired['kid']['id']}/report", headers=headers)
        # 400 rather than 403: a guardianship failure is the same refusal on
        # every parent endpoint, and this one must not be the exception.
        assert res.status_code == 400
        assert "not listed as a guardian" in res.json()["detail"]

    def test_the_child_cannot_read_the_report_written_about_them(
        self, client, wired
    ):
        """Not a privacy matter so much as a tone one -- it is written for an
        adult, about them, and reads that way."""
        headers = {"Authorization": f"Bearer {wired['kid']['token']}"}
        assert client.get(
            f"/api/parent/athletes/{wired['kid']['id']}/report", headers=headers
        ).status_code == 400
