"""Automated coach recognition, parent copies, and the no-reply rule."""

from datetime import date, timedelta

import pytest

from athleteiq import guardians, notifications as N, recognition as R
from athleteiq.db import connect
from athleteiq.store import Store, StoreError

TODAY = date.today()


@pytest.fixture
def program(tmp_path):
    store = Store(connect(tmp_path / "t.db"))
    org = store.create_org("Northshore")
    coach = store.create_user(org, "director", "Coach Ada")
    team = store.create_team(org, "U13")
    athlete = store.create_user(
        org, "athlete", "Jordan Pierce", birth_year=TODAY.year - 13,
        dominant_hand="right",
    )
    store.join_team(team["join_code"], athlete["id"])
    invite = guardians.create_invite(store.conn, athlete["id"], created_by=coach["id"])
    guardian = guardians.redeem_invite(store.conn, invite["code"], "Dana Pierce")
    guardians.set_consent(
        store.conn, athlete["id"], guardian["guardian_id"],
        guardians.Scope.PARTICIPATION, True,
    )
    return {"store": store, "org": org, "coach": coach, "team": team,
            "athlete": athlete, "guardian": guardian}


def sent_to(store, user_id, kind=N.Kind.RECOGNITION):
    return [
        dict(r) for r in store.conn.execute(
            "SELECT title, body, from_name, is_copy FROM notifications "
            "WHERE user_id = ? AND kind = ? ORDER BY id",
            (user_id, kind),
        )
    ]


class TestWhichMilestonesFire:

    def test_the_first_session_is_recognised_on_that_session(self):
        assert [k for _, k in R.earned(sessions_before=0, streak=1, streak_start=TODAY)] \
            == ["first_session"]

    def test_only_the_largest_streak_crossed_is_sent(self):
        """Passing day ten should not replay day five and day three in the
        same breath."""
        got = [m.key for m, _ in R.earned(sessions_before=40, streak=12, streak_start=TODAY)]
        assert got == ["streak_10"]

    def test_an_ordinary_day_earns_nothing(self):
        assert R.earned(sessions_before=5, streak=2, streak_start=TODAY) == []

    def test_the_key_is_the_run_it_belongs_to(self):
        """This is what makes it fire once per streak instead of once a day."""
        start = TODAY - timedelta(days=9)
        first = R.earned(sessions_before=9, streak=10, streak_start=start)[0][1]
        later = R.earned(sessions_before=10, streak=11, streak_start=start)[0][1]
        assert first == later

    def test_a_rebuilt_streak_is_recognised_again(self):
        """Doing it a second time is harder than doing it once."""
        march = R.earned(sessions_before=9, streak=10, streak_start=date(2026, 3, 1))[0][1]
        june = R.earned(sessions_before=99, streak=10, streak_start=date(2026, 6, 1))[0][1]
        assert march != june


class TestTheWordsAreTheCoachs:

    def test_every_milestone_ships_with_something_to_send(self, program):
        for entry in program["store"].recognition_templates(program["org"]):
            assert entry["body"], entry["key"]
            assert entry["customised"] is False

    def test_a_coach_can_replace_them(self, program):
        store = program["store"]
        store.set_recognition_template(
            program["org"], "streak_5", "Five straight, {first_name}! — {coach}",
            True, program["coach"]["id"],
        )
        entry = next(
            e for e in store.recognition_templates(program["org"]) if e["key"] == "streak_5"
        )
        assert entry["customised"] and entry["body"].startswith("Five straight")

    def test_a_milestone_can_be_turned_off(self, program):
        store = program["store"]
        store.set_recognition_template(
            program["org"], "streak_3", "", False, program["coach"]["id"],
        )
        entry = next(
            e for e in store.recognition_templates(program["org"]) if e["key"] == "streak_3"
        )
        assert entry["enabled"] is False

    def test_an_enabled_milestone_needs_words(self, program):
        with pytest.raises(StoreError, match="needs some words"):
            program["store"].set_recognition_template(
                program["org"], "streak_3", "   ", True, program["coach"]["id"],
            )

    def test_an_unknown_milestone_is_refused(self, program):
        with pytest.raises(StoreError, match="unknown milestone"):
            program["store"].set_recognition_template(
                program["org"], "streak_7", "hi", True, program["coach"]["id"],
            )

    def test_tokens_are_filled_and_a_typo_is_left_alone(self):
        out = R.render(
            "{first_name} did {streak} with {team}, says {coach}. {firstname}?",
            first_name="Jordan", streak=5, coach="Ada", team="U13",
        )
        assert out == "Jordan did 5 with U13, says Ada. {firstname}?"

    def test_a_missing_name_does_not_produce_a_blank(self):
        assert "there" in R.render("Hi {first_name}", first_name="", streak=1,
                                   coach="", team="")


class TestItComesFromAPerson:

    def test_the_message_carries_a_coach_name(self, program):
        store = program["store"]
        store.award_recognition(program["athlete"]["id"], sessions_before=0)
        sent = sent_to(store, program["athlete"]["id"])
        assert sent and sent[0]["from_name"] == "Coach Ada"
        assert "Coach Ada" in sent[0]["title"]

    def test_it_still_works_with_nobody_assigned(self, tmp_path):
        """An org with no director and no staff must not crash the submit path."""
        store = Store(connect(tmp_path / "b.db"))
        org = store.create_org("Bare")
        athlete = store.create_user(org, "athlete", "Solo Kid", birth_year=2012)
        assert store.award_recognition(athlete["id"], sessions_before=0) == ["first_session"]


class TestTheParentGetsEverything:

    def test_a_copy_of_every_message(self, program):
        store = program["store"]
        store.award_recognition(program["athlete"]["id"], sessions_before=0)
        athlete_msgs = sent_to(store, program["athlete"]["id"])
        parent_msgs = sent_to(store, program["guardian"]["guardian_id"])
        assert len(parent_msgs) == len(athlete_msgs) == 1
        assert parent_msgs[0]["body"] == athlete_msgs[0]["body"]
        assert parent_msgs[0]["is_copy"] == 1

    def test_it_applies_to_every_kind_of_message_not_just_recognition(self, program):
        """Mirroring lives inside enqueue, so a kind invented next year
        inherits it without anyone remembering to."""
        store = program["store"]
        for kind in (N.Kind.BADGE, N.Kind.STREAK_AT_RISK, N.Kind.COACH_MESSAGE):
            N.enqueue(store.conn, program["athlete"]["id"], kind, f"t:{kind}", "b")
        for kind in (N.Kind.BADGE, N.Kind.STREAK_AT_RISK, N.Kind.COACH_MESSAGE):
            assert sent_to(store, program["guardian"]["guardian_id"], kind), kind

    def test_every_guardian_gets_one(self, program):
        store = program["store"]
        second = guardians.redeem_invite(
            store.conn,
            guardians.create_invite(
                store.conn, program["athlete"]["id"],
                created_by=program["coach"]["id"],
            )["code"],
            "Second Parent",
        )
        store.award_recognition(program["athlete"]["id"], sessions_before=0)
        assert sent_to(store, second["guardian_id"])

    def test_a_message_to_a_coach_is_not_mirrored_anywhere(self, program):
        store = program["store"]
        N.enqueue(store.conn, program["coach"]["id"], N.Kind.COACH_DIGEST, "Digest", "b")
        copies = store.conn.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE is_copy = 1"
        ).fetchone()["n"]
        assert copies == 0

    def test_the_copy_points_at_the_parent_portal(self, program):
        store = program["store"]
        store.award_recognition(program["athlete"]["id"], sessions_before=0)
        link = store.conn.execute(
            "SELECT link FROM notifications WHERE is_copy = 1"
        ).fetchone()["link"]
        assert link == "/parent"


class TestASeniorVoice:
    """A note from a former pro means something because it does not arrive
    every week. Putting their name on a three-day streak spends that."""

    def test_the_long_milestones_default_to_the_senior_voice(self):
        assert R.BY_KEY["streak_30"].default_voice == R.Voice.VOICE
        assert R.BY_KEY["streak_100"].default_voice == R.Voice.VOICE

    def test_the_frequent_ones_stay_with_the_coach(self):
        for key in ("first_session", "streak_3", "streak_5", "streak_10"):
            assert R.BY_KEY[key].default_voice == R.Voice.COACH

    def test_a_program_with_no_senior_figure_falls_back_to_the_coach(self, program):
        """Rather than sending a message from nobody."""
        store = program["store"]
        store.set_recognition_template(
            program["org"], "first_session", "Well done {first_name}.",
            True, program["coach"]["id"], from_voice=R.Voice.VOICE,
        )
        store.award_recognition(program["athlete"]["id"], sessions_before=0)
        assert sent_to(store, program["athlete"]["id"])[0]["from_name"] == "Coach Ada"

    def test_a_named_figure_signs_the_milestones_assigned_to_them(self, program):
        store = program["store"]
        store.set_program_voice(program["org"], "Marcus Vale", "Director of Player Development")
        store.set_recognition_template(
            program["org"], "first_session", "{first_name}, that is a start.",
            True, program["coach"]["id"], from_voice=R.Voice.VOICE,
        )
        store.award_recognition(program["athlete"]["id"], sessions_before=0)
        sent = sent_to(store, program["athlete"]["id"])[0]
        assert sent["from_name"] == "Marcus Vale"
        assert "Director of Player Development" in sent["title"]

    def test_the_coach_still_signs_everything_else(self, program):
        store = program["store"]
        store.set_program_voice(program["org"], "Marcus Vale", "Former pro")
        store.award_recognition(program["athlete"]["id"], sessions_before=0)
        assert sent_to(store, program["athlete"]["id"])[0]["from_name"] == "Coach Ada"

    def test_the_senior_voice_reaches_the_parent_too(self, program):
        store = program["store"]
        store.set_program_voice(program["org"], "Marcus Vale", "Former pro")
        store.set_recognition_template(
            program["org"], "first_session", "Good start, {first_name}.",
            True, program["coach"]["id"], from_voice=R.Voice.VOICE,
        )
        store.award_recognition(program["athlete"]["id"], sessions_before=0)
        assert sent_to(store, program["guardian"]["guardian_id"])[0]["from_name"] \
            == "Marcus Vale"

    def test_an_unknown_voice_is_refused(self, program):
        with pytest.raises(StoreError, match="unknown voice"):
            program["store"].set_recognition_template(
                program["org"], "streak_3", "hi", True,
                program["coach"]["id"], from_voice="the_mascot",
            )


class TestAFamilyRunningItThemselves:
    """No club behind them. The parent takes the coach's place, and every
    feature written for a program works on day one because a family *is* a
    program with one household in it."""

    @pytest.fixture
    def family(self, tmp_path):
        store = Store(connect(tmp_path / "f.db"))
        made = store.create_family("The Pierces", "Dana Pierce")
        child = store.add_family_athlete(
            made["org_id"], made["parent"]["id"], "Jordan Pierce",
            birth_year=TODAY.year - 12, dominant_hand="right",
            join_code=made["team"]["join_code"],
        )
        return {"store": store, **made, "child": child}

    def test_the_parent_is_both_guardian_and_in_charge(self, family):
        store = family["store"]
        assert guardians.guards(store.conn, family["parent"]["id"], family["child"]["id"])
        assert store.conn.execute(
            "SELECT role FROM users WHERE id = ?", (family["parent"]["id"],)
        ).fetchone()["role"] == "director"

    def test_the_child_can_train_immediately(self, family):
        """A parent who just created the account has already consented, so
        making them redeem a code posted to themselves would be theatre."""
        store = family["store"]
        assert guardians.current_consents(
            store.conn, family["child"]["id"]
        )[guardians.Scope.PARTICIPATION] is True
        assert store.start_session(family["child"]["id"], "gen_squat")["session_id"]

    def test_the_two_roles_stay_separate_records(self, family):
        """One sets the training, the other consents to it. Blurring them into
        a super-role is what would make the consent checks meaningless."""
        store = family["store"]
        rows = store.conn.execute(
            "SELECT COUNT(*) AS n FROM guardians WHERE guardian_id = ?",
            (family["parent"]["id"],),
        ).fetchone()["n"]
        assert rows == 1

    def test_recognition_comes_from_the_parent(self, family):
        store = family["store"]
        store.award_recognition(family["child"]["id"], sessions_before=0)
        assert sent_to(store, family["child"]["id"])[0]["from_name"] == "Dana Pierce"

    def test_the_parent_still_gets_their_copy(self, family):
        store = family["store"]
        store.award_recognition(family["child"]["id"], sessions_before=0)
        assert sent_to(store, family["parent"]["id"])

    def test_siblings_share_the_household(self, family):
        store = family["store"]
        sibling = store.add_family_athlete(
            family["org_id"], family["parent"]["id"], "Robin Pierce",
            birth_year=TODAY.year - 9,
        )
        assert guardians.guards(store.conn, family["parent"]["id"], sibling["id"])
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE org_id = ? AND role = 'athlete'",
            (family["org_id"],),
        ).fetchone()["n"] == 2

    def test_it_is_on_the_family_plan(self, family):
        from athleteiq import billing
        plan = billing.get_subscription(family["store"].conn, family["org_id"]).plan
        assert plan.code == "family"
        assert plan.max_teams == 1 and plan.included_seats >= 2

    def test_a_program_account_refuses_the_family_shortcut(self, program):
        """Otherwise a club could bypass the invite flow and link a coach to a
        child as their guardian."""
        store = program["store"]
        with pytest.raises(StoreError, match="not a family account"):
            store.add_family_athlete(
                program["org"], program["coach"]["id"], "Someone Else",
            )
