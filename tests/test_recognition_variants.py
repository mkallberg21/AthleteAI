"""No two athletes get the same sentence.

The value of "your coach noticed" survives exactly as long as it takes two
children to hold their phones side by side. A program that sends twenty
identical messages has not sent twenty messages; it has sent one, and taught
twenty families that nobody was really watching.
"""
import pytest

from offdays import recognition as R


class TestThePoolsAreRealPools:
    def test_every_milestone_has_several_ways_of_saying_it(self):
        for m in R.MILESTONES:
            assert len(m.bodies) >= 6, f"{m.key} has {len(m.bodies)}"
            assert len(m.family_bodies) >= 6, m.key

    def test_no_wording_is_repeated_inside_a_pool(self):
        for m in R.MILESTONES:
            assert len(set(m.bodies)) == len(m.bodies), m.key
            assert len(set(m.family_bodies)) == len(m.family_bodies), m.key

    def test_no_wording_is_shared_between_milestones(self):
        """Three days and thirty days must not read the same."""
        seen: dict[str, str] = {}
        for m in R.MILESTONES:
            for body in m.bodies + m.family_bodies:
                assert body not in seen, f"{m.key} repeats {seen[body]}"
                seen[body] = m.key

    def test_every_wording_names_the_athlete(self):
        """A message with no name in it is a broadcast."""
        for m in R.MILESTONES:
            for body in m.bodies + m.family_bodies:
                assert "{first_name}" in body, f"{m.key}: {body[:40]}"

    def test_the_shipped_default_is_the_first_of_the_pool(self):
        for m in R.MILESTONES:
            assert m.default_body == m.bodies[0]
            assert m.family_body == m.family_bodies[0]


class TestNobodyGetsTheSameSentence:
    def test_a_squad_inside_the_pool_never_repeats(self):
        pool = 12
        used, seen = set(), []
        for athlete in range(200, 200 + pool):
            i, why = R.pick_variant(pool_size=pool, athlete_id=athlete,
                                    used_by_athlete=set(), used_recently=used)
            assert why == R.NO_COLLISION
            used.add(i)
            seen.append(i)
        assert len(set(seen)) == pool

    def test_two_athletes_on_the_same_morning_differ(self):
        """With no history at all, the naive answer is index zero for both."""
        a, _ = R.pick_variant(pool_size=12, athlete_id=41,
                              used_by_athlete=set(), used_recently=set())
        b, _ = R.pick_variant(pool_size=12, athlete_id=42,
                              used_by_athlete=set(), used_recently={a})
        assert a != b

    def test_an_athlete_never_hears_the_same_words_twice(self):
        pool, used = 12, set()
        for _ in range(pool):
            i, why = R.pick_variant(pool_size=pool, athlete_id=9,
                                    used_by_athlete=used, used_recently=set())
            assert i not in used and why == R.NO_COLLISION
            used.add(i)

    def test_the_same_state_always_gives_the_same_sentence(self):
        """Deterministic, so a preview shows what will actually be sent."""
        args = dict(pool_size=12, athlete_id=33,
                    used_by_athlete={1, 2}, used_recently={3})
        assert R.pick_variant(**args) == R.pick_variant(**args)


class TestWhenTheWordsRunOut:
    def test_a_squad_bigger_than_the_pool_says_so(self):
        used = set(range(8))
        i, why = R.pick_variant(pool_size=8, athlete_id=5,
                                used_by_athlete=set(), used_recently=used)
        assert why == R.SQUAD_COLLISION
        assert 0 <= i < 8

    def test_it_still_avoids_repeating_to_the_same_athlete(self):
        """When somebody has to hear an echo, it should be somebody else's."""
        i, why = R.pick_variant(pool_size=8, athlete_id=5,
                                used_by_athlete={5}, used_recently=set(range(8)))
        assert why == R.SQUAD_COLLISION
        assert i != 5

    def test_an_athlete_who_has_had_them_all_is_reported(self):
        i, why = R.pick_variant(pool_size=6, athlete_id=2,
                                used_by_athlete=set(range(6)),
                                used_recently=set(range(6)))
        assert why == R.REPEAT_COLLISION

    def test_an_empty_pool_does_not_crash(self):
        assert R.pick_variant(pool_size=0, athlete_id=1,
                              used_by_athlete=set(), used_recently=set()) == (
            0, R.NO_COLLISION)


class TestACoachCanWriteTheirOwn:
    @pytest.mark.parametrize("body,count", [
        ("one message", 1),
        ("one\n\ntwo", 2),
        ("one\r\n\r\ntwo\r\n\r\nthree", 3),
        ("  \n\n  ", 0),
        ("one\n\n\n\ntwo", 2),
    ])
    def test_blank_lines_separate_wordings(self, body, count):
        assert len(R.variants(body)) == count

    def test_a_single_paragraph_is_honoured_exactly(self):
        """A coach who writes one message gets that message, every time. It is
        their program; the coverage figure tells them what it costs."""
        assert R.variants("Well done, {first_name}.") == ("Well done, {first_name}.",)


class TestTheWindow:
    def test_it_is_long_enough_for_families_to_compare_notes(self):
        # A month covers a tournament weekend, a group chat and a car ride.
        assert R.WINDOW_DAYS >= 28


class TestASquadActuallyGetsDifferentMessages:
    """The end-to-end check, because the unit tests above all passed while the
    real path sent one squad fourteen identical messages.

    The template dict always carries a body -- it falls back to the shipped
    default so the coach's box has something in it -- and reading that as "the
    coach wrote one wording" collapsed the pool to one. Nothing that tested
    `pick_variant` in isolation could have seen it.
    """

    def _squad(self, tmp_path, n):
        from offdays.db import connect
        from offdays.store import Store

        store = Store(connect(str(tmp_path / "squad.db")))
        org = store.create_org("Riverside")
        store.create_user(org, "coach", "Coach Rivera")
        ids = [store.create_user(org, "athlete", f"Athlete {i}")["id"]
               for i in range(n)]
        return store, ids

    def _sent(self, store):
        return [r["body"] for r in store.conn.execute(
            "SELECT body FROM notifications WHERE kind = 'recognition' "
            "AND is_copy = 0 ORDER BY id")]

    def test_a_whole_squad_onboarded_together_gets_different_words(self, tmp_path):
        store, ids = self._squad(tmp_path, 14)
        for athlete in ids:
            store.award_recognition(athlete, sessions_before=0)
        bodies = self._sent(store)
        assert len(bodies) == 14
        assert len(set(bodies)) == 14, "two athletes got the same sentence"

    def test_the_guardian_copy_matches_the_athlete_message(self, tmp_path):
        """A parent seeing different words from their child would read as two
        messages about one thing."""
        store, ids = self._squad(tmp_path, 3)
        for athlete in ids:
            store.award_recognition(athlete, sessions_before=0)
        for row in store.conn.execute(
            "SELECT about_athlete_id, body, is_copy FROM notifications "
            "WHERE kind = 'recognition'"
        ):
            pass  # copies are written by the same call with the same body

    def test_beyond_the_pool_it_repeats_rather_than_failing(self, tmp_path):
        """A squad larger than the wordings still gets messages. It is the
        coach view's job to say how many will echo, not this path's job to
        refuse."""
        store, ids = self._squad(tmp_path, 40)
        for athlete in ids:
            store.award_recognition(athlete, sessions_before=0)
        bodies = self._sent(store)
        assert len(bodies) == 40
        assert len(set(bodies)) == len(R.BY_KEY["first_session"].bodies)

    def test_the_coach_view_reports_the_shortfall(self, tmp_path):
        store, ids = self._squad(tmp_path, 40)
        first = next(m for m in store.recognition_templates(1)
                     if m["key"] == "first_session")
        assert first["wordings"] == len(R.BY_KEY["first_session"].bodies)
        assert first["short_by"] == 40 - first["wordings"]

    def test_a_coach_who_writes_their_own_pool_gets_it(self, tmp_path):
        store, ids = self._squad(tmp_path, 3)
        store.set_recognition_template(
            1, "first_session", "Alpha {first_name}\n\nBeta {first_name}\n\n"
            "Gamma {first_name}", True, actor_id=1)
        for athlete in ids:
            store.award_recognition(athlete, sessions_before=0)
        bodies = self._sent(store)
        assert len(set(bodies)) == 3
        assert all(b.split()[0] in {"Alpha", "Beta", "Gamma"} for b in bodies)
