"""Gymnastics, cheer and dance -- the physical half, and only the physical half.

These three sports were held back on the grounds that they are judged on
*form*, and a number on a child's line about how their body looked is the most
dangerous thing this product could produce. That objection was to scoring
technique. It says nothing about whether the app can help a gymnast get
stronger, and the answer to that is obviously yes.

So this build is a conditioning programme, and the line it draws is load
bearing: **0FFDAYS scores work, never appearance.** Nothing here counts a
tumbling pass, a stunt or a combination, and the tests below are what stops one
turning up later.

Building it turned up something bigger than the three sports. Their plans were
made entirely of general bodyweight movements -- which was not wrong, but the
shelf those were picked from had eighteen exercises that between them never
measured an ankle, never went overhead, and never asked anybody to hang. Those
were real holes in the general catalogue, and every sport in the product now
has them filled.
"""

from __future__ import annotations

import re

import pytest

from offdays import curriculum, film, technique, transfer
from offdays.drills import ALL_DRILLS, get_drill
from offdays.drills.base import Category, Metric, SignalKind, Tissue
from offdays.positions import BY_SPORT

JUDGED = ("gymnastics", "cheer", "dance")
NEW = ("gen_calf_raise", "gen_handstand_hold", "gen_dead_hang")


class TestTheQualitiesTheCatalogueCouldNotTrain:
    @pytest.mark.parametrize("key", NEW)
    def test_it_exists_and_is_general(self, key):
        # General rather than sport-prefixed on purpose: a calf raise does not
        # belong to gymnastics, and hiding it under one sport would have meant
        # fifteen others still had no way to train an ankle.
        assert get_drill(key).sport == "general"

    @pytest.mark.parametrize("key", NEW)
    def test_it_has_cues_and_transfers(self, key):
        assert technique.cues_for(key)
        assert transfer.for_drill(key)

    def test_nothing_else_in_the_catalogue_measures_the_ankle(self):
        """The hole this was filling.

        Eighteen general movements and sixty sport drills, and the joint every
        landing arrives on and every jump leaves from was measured by none of
        them.
        """
        drill = get_drill("gen_calf_raise")
        assert drill.signal.landmark == "left_heel"
        assert drill.signal.reference == "left_foot_index"
        others = [
            d.key for d in ALL_DRILLS
            if d.key != drill.key
            and "heel" in (d.signal.landmark or "", d.signal.reference or "")
        ]
        assert others == [], others

    def test_the_inverted_hold_needed_no_new_signal(self):
        """Hip height is measured against the feet, so putting the feet above
        the hips simply makes it negative. Nothing else here ever goes below
        zero, which makes an inverted hold unmistakable rather than merely
        different."""
        drill = get_drill("gen_handstand_hold")
        assert drill.signal.kind is SignalKind.BODY_HEIGHT
        assert drill.counter.up_threshold < 0
        negatives = [
            d.key for d in ALL_DRILLS
            if d.signal.kind is SignalKind.BODY_HEIGHT and d.counter.up_threshold < 0
        ]
        assert negatives == ["gen_handstand_hold"], negatives

    def test_a_hang_stops_where_a_pull_up_starts(self):
        """Same measurement, and that is the point: this drill is about the
        grip, so pulling yourself up is not a better version of it. The bands
        do not overlap, so the clock stops the moment it becomes a pull-up."""
        hang = get_drill("gen_dead_hang")
        pull = get_drill("gen_pull_up")
        assert (hang.signal.landmark, hang.signal.reference) \
            == (pull.signal.landmark, pull.signal.reference)
        assert hang.counter.up_threshold <= pull.counter.down_threshold

    def test_the_two_holds_are_upper_body_load(self):
        for key in ("gen_handstand_hold", "gen_dead_hang"):
            drill = get_drill(key)
            assert drill.metric is Metric.HOLD_SECONDS
            assert drill.load.tissue is Tissue.UPPER_BODY
            assert drill.load.load_per_minute > 0

    def test_none_of_them_touch_the_throwing_ledger(self):
        for key in NEW:
            assert get_drill(key).load.throws_per_rep == 0.0


class TestTheAppScoresWorkAndNeverAppearance:
    """The line this whole build is drawn along."""

    def test_no_drill_belongs_to_a_judged_sport(self):
        """These three get conditioning, and it is general conditioning.

        A `gym_` or `dnc_` drill would be a drill about executing the sport,
        and executing the sport is exactly what nothing here scores.
        """
        offenders = [d.key for d in ALL_DRILLS if d.sport in JUDGED]
        assert offenders == [], offenders

    @pytest.mark.parametrize("sport", JUDGED)
    def test_every_plan_is_built_from_general_conditioning(self, sport):
        keys = {d.key: d for d in ALL_DRILLS}
        for plan in BY_SPORT[sport]:
            for key in plan.emphasis:
                assert keys[key].sport == "general", f"{plan.key}: {key}"

    @pytest.mark.parametrize("sport", JUDGED)
    def test_no_plan_promises_anything_about_how_it_looks(self, sport):
        # The focus line is the one sentence an athlete reads about what their
        # hour is for, and in these three sports it is the easiest place in the
        # product for appearance language to creep in.
        # Phrases rather than bare words. "Weight through your hands" is the
        # right description of what a hip hop dancer's hour is for, and a test
        # that banned the word "weight" would be a test that fails on good
        # copy while still passing "long and lean".
        banned = (
            r"looks?\b", r"\blean\b", r"\bslim\b", r"slender", r"toned",
            r"aesthetics?", r"physique", r"\bfigure\b", r"body type",
            r"(your|body|lose|losing) weight", r"weigh(s|ing|ed)?\b",
        )
        for plan in BY_SPORT[sport]:
            low = plan.focus.lower()
            for pattern in banned:
                assert re.search(pattern, low) is None, \
                    f"{plan.key}: {plan.focus!r} matched {pattern}"


class TestThePositionPlans:
    @pytest.mark.parametrize("sport", JUDGED)
    def test_there_are_four_and_they_sum_to_one(self, sport):
        plans = BY_SPORT[sport]
        assert len(plans) == 4
        for plan in plans:
            assert sum(plan.emphasis.values()) == pytest.approx(1.0)

    def test_a_ballet_dancer_leads_with_the_ankle(self):
        plan = {p.key: p for p in BY_SPORT["dance"]}["ballet"].emphasis
        assert max(plan, key=plan.get) == "gen_calf_raise"

    def test_a_bars_gymnast_leads_with_the_hands(self):
        plan = {p.key: p for p in BY_SPORT["gymnastics"]}["bars"].emphasis
        hands = plan["gen_pull_up"] + plan["gen_dead_hang"] + plan["gen_handstand_hold"]
        assert hands > 0.5, plan

    def test_a_cheer_base_gets_the_overhead_work(self):
        # Somebody is standing on these hands. The overhead position is the
        # job, not a nice extra, and until now there was no way to train it.
        plan = {p.key: p for p in BY_SPORT["cheer"]}["base"].emphasis
        assert plan.get("gen_handstand_hold", 0) > 0.1

    @pytest.mark.parametrize("sport", JUDGED)
    def test_every_plan_uses_at_least_one_of_the_new_qualities(self, sport):
        for plan in BY_SPORT[sport]:
            assert set(plan.emphasis) & set(NEW), plan.key


class TestTheFilmCurriculum:
    TOPICS = curriculum.topics_for("gymnastics")

    def test_all_three_sports_share_one_syllabus(self):
        for sport in JUDGED:
            assert curriculum.topics_for(sport) is self.TOPICS

    def test_there_is_one(self):
        assert len(self.TOPICS) >= 12

    def test_every_topic_fits_its_age_ceiling(self):
        for topic in self.TOPICS:
            cap = film.band_for(topic.min_age).clip_max_s
            assert topic.target_s <= cap, f"{topic.key}: {topic.target_s} > {cap}"

    def test_every_topic_carries_a_question_with_its_reasoning(self):
        for topic in self.TOPICS:
            assert topic.ask.because, topic.key
            assert 0 <= topic.ask.answer < len(topic.ask.options), topic.key

    def test_no_topic_ships_a_video_id(self):
        blob = " ".join(t.find + t.title for t in self.TOPICS).lower()
        for banned in ("youtu.be", "youtube.com", "watch?v="):
            assert banned not in blob

    def test_no_topic_reads_like_a_highlight_reel(self):
        for topic in self.TOPICS:
            assert film.looks_like_highlights(topic.title) is None, topic.key

    def test_it_teaches_training_sense_rather_than_technique(self):
        assert {t.focus for t in self.TOPICS} == {"Training sense", "Staying safe"}

    def test_safety_is_most_of_it(self):
        safe = [t for t in self.TOPICS if t.focus == "Staying safe"]
        assert len(safe) >= len(self.TOPICS) / 2

    def test_the_youngest_band_is_taught_to_tell_somebody(self):
        # The single most useful thing a ten-year-old can learn here, and it
        # does not wait for the oldest band.
        young = [t for t in self.TOPICS if t.min_age == 0]
        assert any("tell an adult" in t.ask.options[t.ask.answer].lower()
                   or "tell an adult" in t.ask.because.lower() for t in young)

    def test_nothing_names_a_condition_or_reads_as_a_diagnosis(self):
        """The same rule the wellness module is held to.

        The pressure to write something that sounds clinical is real and one
        commit away, and these are exactly the topics where it would happen.
        Every answer here is a thing to do or a thing to notice.
        """
        # Matched on word boundaries rather than as substrings: "conditioning"
        # contains "condition", and banning the training word to catch the
        # clinical one would be a test that fails on the right answer.
        banned = (
            r"tendin\w*itis", r"tendon\w*itis", r"fractures?", r"spondylo\w*",
            r"sprains?", r"strains?", r"syndromes?", r"disorders?", r"anorexi\w*",
            r"diagnos\w*", r"conditions?",
        )
        for topic in self.TOPICS:
            blob = " ".join(
                (topic.title, topic.focus, topic.find, topic.ask.prompt,
                 topic.ask.because, *topic.ask.options)
            ).lower()
            for word in banned:
                assert re.search(rf"\b{word}\b", blob) is None, \
                    f"{topic.key}: {word}"

    def test_the_fuelling_topic_talks_about_training_never_about_weight(self):
        topic = curriculum.BY_KEY["jdg_iq_fuel"]
        blob = " ".join(
            (topic.title, topic.ask.prompt, topic.ask.because, *topic.ask.options)
        ).lower()
        assert "eating enough" in blob or "not eating enough" in blob
        # No numbers, no targets, and nothing an athlete could read as a goal.
        for word in ("calorie", "kg", "lbs", "pounds", "diet", "bmi"):
            assert word not in blob, word

    def test_a_comment_about_a_body_resolves_to_telling_somebody(self):
        topic = curriculum.BY_KEY["jdg_iq_comments"]
        assert "tell another adult" in topic.ask.options[topic.ask.answer].lower()
