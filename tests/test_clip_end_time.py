"""A clip a coach adds must have an end time, or no athlete can ever finish it.

Found by running the scoring on a kid who watched 120 seconds with the sound on:
with an end time the verdict is "watched"; without one the clip has no length, so
coverage is always zero and the verdict is "partial" forever. The form called the
end time optional.
"""
from __future__ import annotations

import offdays.api as api_module
from tests.test_api import client, program  # noqa: F401  (fixtures)


def _add(client, program, **kw):
    body = {"video": "https://youtu.be/dQw4w9WgXcQ", "title": "Sliding early",
            "start_s": 0}
    body.update(kw)
    return client.post("/api/coach/clips", json=body, headers=program["director"])


class TestEveryCoachClipCanBeFinished:
    def test_a_clip_without_an_end_time_is_refused_with_a_reason(self, client, program):
        res = _add(client, program)
        assert res.status_code == 400
        assert "end" in res.json()["detail"].lower()

    def test_nothing_is_stored_when_it_is_refused(self, client, program):
        _add(client, program)
        n = api_module._store.conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        assert n == 0

    def test_a_clip_with_an_end_time_is_accepted(self, client, program):
        res = _add(client, program, start_s=10, end_s=70)
        assert res.status_code == 201

    def test_and_an_athlete_can_actually_finish_it(self, client, program):
        """The point of the rule: a clip that is accepted can be completed."""
        from offdays import film as F
        made = _add(client, program, start_s=0, end_s=60).json()
        state = F.WatchState(length_s=made["length_s"])
        pos = 0.0
        for _ in range(15):
            pos += 4.0
            F.apply_beat(state, pos, 4.0, muted=False, hidden=False, rate=1.0)
        assert F.assess(state) == F.Verdict.WATCHED

    def test_the_existing_length_cap_still_applies(self, client, program):
        res = _add(client, program, start_s=0, end_s=900)
        assert res.status_code == 400
        assert "capped" in res.json()["detail"]

    def test_the_built_in_curriculum_clips_all_have_an_end_time(self):
        from offdays import curriculum
        for sport in ("lacrosse",):
            for topic in curriculum.topics_for(sport):
                assert topic.target_s and topic.target_s > 0, topic.key
