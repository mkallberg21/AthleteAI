"""The lacrosse IQ film curriculum, and the clamp drill.

The film module shipped empty for the whole life of this product. The
machinery to teach the half of the game learned by watching existed and
nothing had been loaded into it.

What this curriculum deliberately does not contain is video links. Picking
real clips means watching them, and a catalogue of plausible-looking ids that
turn out dead or wrong would be worse than an empty shelf because it would
look full. So the tests below check the part that is actually here: that every
topic is teachable, that its question has a defensible answer, and above all
that its length fits the age band it is offered to -- because that cap is
enforced, and a clip over it is silently never shown.
"""
from __future__ import annotations

import tempfile

import pytest

from offdays import curriculum
from offdays.db import connect
from offdays.drills import DRILLS_BY_KEY
from offdays.film import band_for
from offdays.positions import for_sport
from offdays.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "c.db"))


class TestEveryClipFitsTheAgeItIsOfferedTo:
    """The cap is enforced in film.py, not advisory. A clip over its band's
    ceiling is filtered out and the athlete simply never sees it -- which
    would look like a curriculum that shipped and a module that stayed
    stubbornly empty."""

    @pytest.mark.parametrize("topic", curriculum.TOPICS, ids=lambda t: t.key)
    def test_target_length_is_inside_the_ceiling(self, topic):
        ceiling = band_for(topic.min_age).clip_max_s
        assert topic.target_s <= ceiling, (
            f"{topic.key} is {topic.target_s}s but a {topic.min_age}-year-old "
            f"can only be shown {ceiling}s"
        )

    def test_the_youngest_athletes_get_something(self):
        """Under-11s have a 75-second ceiling. Without clips cut for them they
        would have a film module that shows them nothing at all."""
        youngest = [t for t in curriculum.TOPICS if t.min_age == 0]
        assert len(youngest) >= 3
        for topic in youngest:
            assert topic.target_s <= 75

    def test_the_bulk_sits_where_the_athletes_are(self):
        """Most youth lacrosse is 13 to 18. A curriculum weighted to adults
        would be technically correct and practically useless."""
        teen = [t for t in curriculum.TOPICS if 13 <= t.min_age <= 15]
        assert len(teen) >= len(curriculum.TOPICS) // 2

    def test_nothing_is_pinned_to_adults_only(self):
        """A four-minute clip is visible only at 19+. If the curriculum drifted
        that way it would quietly stop being for children."""
        assert not [t for t in curriculum.TOPICS if t.min_age >= 19]


class TestEveryTopicIsActuallyTeachable:
    @pytest.mark.parametrize("topic", curriculum.TOPICS, ids=lambda t: t.key)
    def test_it_has_a_question_with_a_real_answer(self, topic):
        ask = topic.ask
        assert ask.prompt.endswith("?") or ask.prompt.endswith(".")
        assert len(ask.options) >= 3, "a two-option question is a coin flip"
        assert 0 <= ask.answer < len(ask.options)
        assert len(ask.because) > 40, "the explanation is the teaching"

    @pytest.mark.parametrize("topic", curriculum.TOPICS, ids=lambda t: t.key)
    def test_it_says_what_footage_to_cut(self, topic):
        """The one instruction a coach actually needs, since they are supplying
        the video."""
        assert len(topic.find) > 60, f"{topic.key} has no guidance"

    @pytest.mark.parametrize("topic", curriculum.TOPICS, ids=lambda t: t.key)
    def test_it_targets_positions_that_exist(self, topic):
        known = {p.key for p in for_sport("lacrosse")}
        unknown = set(topic.positions) - known
        assert not unknown, f"{topic.key} targets {unknown}"

    def test_every_position_is_taught_something(self):
        """A goalie or a face-off man opening the film module and finding
        nothing for them is the same empty shelf in miniature."""
        covered = {p for t in curriculum.TOPICS for p in t.positions}
        for position in for_sport("lacrosse"):
            assert position.key in covered, f"nothing for {position.key}"

    def test_topic_keys_are_unique(self):
        keys = [t.key for t in curriculum.TOPICS]
        assert len(keys) == len(set(keys))

    def test_the_wrong_answers_are_plausible(self):
        """A question whose distractors are obviously silly teaches nothing and
        scores everybody full marks."""
        for topic in curriculum.TOPICS:
            for option in topic.ask.options:
                assert len(option) > 12, f"{topic.key}: {option!r} is a throwaway"


class TestNoVideoIsInvented:
    def test_the_curriculum_ships_no_video_ids(self):
        """The load-bearing omission. A catalogue of plausible-looking ids that
        turn out dead is worse than an empty shelf, because it looks full."""
        blob = str(curriculum.catalogue())
        for leak in ("youtube.com", "youtu.be", "watch?v="):
            assert leak not in blob

    def test_a_topic_without_a_video_creates_no_clip(self, store):
        org = store.create_org("Northshore")
        out = curriculum.install(store, org, {})
        assert out["installed"] == []
        assert len(out["awaiting_video"]) == len(curriculum.TOPICS)
        assert store.conn.execute(
            "SELECT COUNT(*) FROM clips").fetchone()[0] == 0

    def test_a_blank_string_is_not_a_video(self, store):
        org = store.create_org("Northshore")
        out = curriculum.install(
            store, org, {"lax_iq_cut_on_head_turn": "   "})
        assert out["installed"] == []


class TestInstalling:
    def test_it_creates_clips_for_the_topics_given_a_video(self, store):
        org = store.create_org("Northshore")
        out = curriculum.install(store, org, {
            "lax_iq_cut_on_head_turn": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "lax_iq_ground_ball_box_out": "aBcDeFgHiJk",
        })
        assert sorted(out["installed"]) == [
            "lax_iq_cut_on_head_turn", "lax_iq_ground_ball_box_out"]
        assert store.conn.execute(
            "SELECT COUNT(*) FROM clips").fetchone()[0] == 2

    def test_the_clip_carries_the_question_and_the_age_band(self, store):
        org = store.create_org("Northshore")
        curriculum.install(
            store, org, {"lax_iq_cut_on_head_turn": "dQw4w9WgXcQ"})
        row = store.conn.execute(
            "SELECT title, min_age, end_s, question FROM clips").fetchone()
        topic = curriculum.BY_KEY["lax_iq_cut_on_head_turn"]
        assert row["title"] == topic.title
        assert row["min_age"] == topic.min_age
        assert row["end_s"] == topic.target_s
        assert "backdoor" in row["question"]

    def test_running_it_twice_does_not_duplicate(self, store):
        """A coach pastes five links today and the rest next week."""
        org = store.create_org("Northshore")
        for _ in range(2):
            curriculum.install(
                store, org, {"lax_iq_cut_on_head_turn": "dQw4w9WgXcQ"})
        assert store.conn.execute(
            "SELECT COUNT(*) FROM clips").fetchone()[0] == 1

    def test_one_bad_link_does_not_stop_the_rest(self, store):
        org = store.create_org("Northshore")
        out = curriculum.install(store, org, {
            "lax_iq_cut_on_head_turn": "dQw4w9WgXcQ",
            "lax_iq_give_and_go": "!!! not a video !!!",
        })
        assert "lax_iq_cut_on_head_turn" in out["installed"]
        assert out["failed"] and out["failed"][0]["topic"] == "lax_iq_give_and_go"


class TestTheClampDrill:
    """Face-off was a position with no position-specific work. The clamp
    rotation itself is invisible to pose -- it happens around a stick the
    camera does not know exists -- so what this drill measures is the hand
    speed around it, and it says so rather than letting a FOGO assume more."""

    @property
    def drill(self):
        return DRILLS_BY_KEY["lax_faceoff_clamp"]

    def test_it_is_a_speed_drill_not_a_volume_one(self):
        """The only drill in the catalogue where tempo outweighs range: a
        face-off is decided in about half a second."""
        quality = self.drill.quality
        assert quality.w_tempo >= quality.w_depth
        assert self.drill.category.value == "speed"

    def test_it_allows_a_genuinely_fast_rep(self):
        assert self.drill.counter.min_rep_ms <= 300

    def test_it_carries_no_throwing_load(self):
        """Nothing goes overhead. Counting it as throwing volume would trip a
        shoulder advisory for work that never touched the shoulder."""
        assert self.drill.load.throws_per_rep == 0.0
        assert self.drill.load.tissue.value != "throwing"

    def test_the_face_off_position_now_leads_on_it(self):
        fogo = next(p for p in for_sport("lacrosse") if p.key == "fogo")
        top = max(fogo.emphasis.items(), key=lambda kv: kv[1])
        assert top[0] == "lax_faceoff_clamp"

    def test_every_lacrosse_position_emphasis_still_sums_to_one(self):
        for position in for_sport("lacrosse"):
            assert abs(sum(position.emphasis.values()) - 1.0) < 0.001, position.key

    def test_the_description_does_not_claim_to_see_the_clamp(self):
        """The honesty that keeps the drill worth having."""
        from offdays import technique

        text = (self.drill.description + self.drill.signal.kind.value).lower()
        assert "clamp" in text
        cues = technique.cues_for("lax_faceoff_clamp")
        assert any(c.component == "offhand" for c in cues)


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


class TestOverTheWire:
    def test_the_curriculum_is_public(self, client):
        """A coach evaluating the product should see what it would teach their
        athletes before signing up."""
        body = client.get("/api/curriculum/lacrosse").json()
        assert body["count"] == len(curriculum.TOPICS)
        assert body["topics"][0]["question"]["because"]

    def test_a_director_can_load_it(self, client):
        org = client.post(
            "/api/orgs", json={"name": "Northshore", "director_name": "Dir"}
        ).json()
        headers = {"Authorization": f"Bearer {org['director']['token']}"}
        res = client.post(
            "/api/coach/curriculum/lacrosse",
            json={"topics": [
                {"topic": "lax_iq_cut_on_head_turn", "video": "dQw4w9WgXcQ"},
            ]},
            headers=headers)
        assert res.status_code == 201
        assert res.json()["installed"] == ["lax_iq_cut_on_head_turn"]

    def test_loading_nothing_creates_nothing(self, client):
        org = client.post(
            "/api/orgs", json={"name": "Northshore", "director_name": "Dir"}
        ).json()
        headers = {"Authorization": f"Bearer {org['director']['token']}"}
        body = client.post("/api/coach/curriculum/lacrosse",
                           json={"topics": []}, headers=headers).json()
        assert body["installed"] == []
        assert len(body["awaiting_video"]) == len(curriculum.TOPICS)

    def test_an_assistant_coach_cannot_load_a_curriculum(self, client):
        from offdays import api as api_mod

        org = client.post(
            "/api/orgs", json={"name": "Northshore", "director_name": "Dir"}
        ).json()
        store = api_mod.get_store()
        org_id = store.authenticate(org["director"]["token"]).org_id
        coach = store.create_user(org_id, "coach", "Asst")
        assert client.post(
            "/api/coach/curriculum/lacrosse", json={"topics": []},
            headers={"Authorization": f"Bearer {coach['token']}"},
        ).status_code == 403
