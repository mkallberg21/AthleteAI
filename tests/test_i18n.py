"""Spanish on the surfaces where not having it does the most damage.

Not the leaderboard or the drill picker -- a child navigates those from icons
and numbers regardless. The parent portal, the consent flow, and the messages
a coach sends home: the places a guardian is asked to understand something and
then agree to it.

A consent screen somebody cannot read is not consent. That is the whole
argument, and it is what most of these tests protect.

Two honest limits are also pinned here, because a translation feature that
overstates itself is worse than one that does not exist. We translate what we
ship and not what a coach types -- there is no translation service in this
application. And a half-translated language is a promise the product does not
keep, so `missing()` exists to make the gap visible rather than let it turn up
on a consent form.
"""
from __future__ import annotations

import pytest

from athleteiq import i18n
from athleteiq.db import connect
from athleteiq.guardians import scopes_for
from athleteiq.recognition import MILESTONES
from athleteiq.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "i.db"))


class TestResolvingWhatABrowserSends:
    @pytest.mark.parametrize("tag", ["es", "ES", "es-MX", "es_419", "es-ES",
                                     "es-MX,en;q=0.8"])
    def test_every_spanish_tag_lands_on_spanish(self, tag):
        """A browser sends whatever it likes. Falling back to English on a tag
        we could have matched hands a Spanish-speaking parent an English
        consent form."""
        assert i18n.normalize(tag) == i18n.ES

    @pytest.mark.parametrize("tag", ["fr", "de-CH", "", None, "  ", "xx-YY"])
    def test_anything_else_falls_back_to_english(self, tag):
        assert i18n.normalize(tag) == i18n.EN

    def test_the_picker_only_offers_what_is_actually_translated(self):
        """A half-translated language in a picker is a promise the product
        does not keep."""
        assert {code for code, _ in i18n.LOCALES} == i18n.SUPPORTED


class TestNothingIsHalfTranslated:
    def test_no_key_is_missing_a_translation(self):
        assert i18n.missing() == {}

    def test_a_missing_key_returns_empty_rather_than_the_key_itself(self):
        """Showing `consent.coach_video.why` to a parent would be worse than
        showing English."""
        assert i18n.t("nope.not.a.key", i18n.ES) == ""

    def test_a_key_with_no_spanish_falls_back_to_english(self):
        i18n.STRINGS["test.only_english"] = {i18n.EN: "Hello"}
        try:
            assert i18n.t("test.only_english", i18n.ES) == "Hello"
        finally:
            i18n.STRINGS.pop("test.only_english", None)


class TestConsentIsTranslatedWhereItIsBuilt:
    """Every consent surface goes through `scopes_for`, so translating there
    rather than at each call site is the difference between a rule and an
    intention."""

    def test_every_scope_comes_back_in_spanish(self):
        for key, label, why in scopes_for("program", "es"):
            assert label and why
            assert label != dict(
                (k, lbl) for k, lbl, _ in scopes_for("program", "en"))[key], \
                f"{key} was not translated"

    def test_the_household_wording_is_translated_too(self):
        """A consent screen describing somebody else's situation is not
        informed consent, and that stays true in Spanish."""
        family = dict((k, lbl) for k, lbl, _ in scopes_for("family", "es"))
        program = dict((k, lbl) for k, lbl, _ in scopes_for("program", "es"))
        assert family["coach_video"] != program["coach_video"]
        assert "panel" in family["coach_video"]

    def test_english_is_unchanged(self):
        assert scopes_for()[0][1] == "Training in the app"
        assert scopes_for("program", "en") == scopes_for("program")

    def test_the_video_permission_still_says_what_actually_happens(self):
        """The English copy is careful that a clip really is uploaded. A
        translation that softened that would be the one place this matters
        most."""
        why = dict((k, w) for k, _, w in scopes_for("program", "es"))["coach_video"]
        assert "30 días" in why
        assert "se borran" in why

    def test_a_guardian_reads_consent_in_their_own_language(self, store):
        from athleteiq import guardians as guardians_mod

        org = store.create_org("Northshore")
        director = store.create_user(org, "director", "Coach Ada")
        team = store.create_team(org, "U15")
        kid = store.create_user(
            org, "athlete", "Jordan P.", birth_year=2011, dominant_hand="right")
        store.join_team(team["join_code"], kid["id"])
        invite = guardians_mod.create_invite(store.conn, kid["id"], director["id"])
        parent = guardians_mod.redeem_invite(
            store.conn, invite["code"], "Sam Pierce", "sam@example.com")

        store.set_locale(parent["guardian_id"], "es")
        summary = store.guardian_summary(parent["guardian_id"])
        labels = [c["label"] for c in summary["athletes"][0]["consents"]]
        assert "Entrenar en la aplicación" in labels


class TestLanguageBelongsToThePerson:
    @staticmethod
    def _household(store):
        """A real guardian, made the way guardians are actually made."""
        from athleteiq import guardians as guardians_mod

        org = store.create_org("Northshore")
        director = store.create_user(org, "director", "Coach Ada")
        team = store.create_team(org, "U15")
        teen = store.create_user(
            org, "athlete", "Jordan P.", birth_year=2009, dominant_hand="right")
        store.join_team(team["join_code"], teen["id"])
        invite = guardians_mod.create_invite(store.conn, teen["id"], director["id"])
        parent = guardians_mod.redeem_invite(
            store.conn, invite["code"], "Sam Pierce", "sam@example.com")
        return {"parent_id": parent["guardian_id"], "teen": teen}

    def test_it_defaults_to_english(self, store):
        assert store.locale_for(self._household(store)["parent_id"]) == "en"

    def test_a_guardian_sets_their_own(self, store):
        parent_id = self._household(store)["parent_id"]
        assert store.set_locale(parent_id, "es-MX") == "es"
        assert store.locale_for(parent_id) == "es"

    def test_one_persons_choice_does_not_move_anybody_else(self, store):
        """A Spanish-speaking parent of an English-preferring teenager is an
        entirely ordinary household."""
        home = self._household(store)
        store.set_locale(home["parent_id"], "es")
        assert store.locale_for(home["teen"]["id"]) == "en"

    def test_a_nonsense_locale_is_stored_as_english_not_as_itself(self, store):
        parent_id = self._household(store)["parent_id"]
        store.set_locale(parent_id, "klingon")
        assert store.locale_for(parent_id) == "en"


class TestRecognitionTranslatesWhatWeShipAndSaysSo:
    def test_every_shipped_milestone_has_spanish(self):
        for milestone in MILESTONES:
            assert milestone.has_translation("program", "es"), milestone.key
            assert milestone.has_translation("family", "es"), milestone.key

    def test_the_body_comes_back_in_spanish(self):
        body = MILESTONES[0].body_for("program", "es")
        assert "{first_name}" in body
        assert "entrenamiento" in body

    def test_the_parent_voice_stays_distinct_in_spanish(self):
        """A separate default rather than the coach one with nouns swapped --
        a parent talking like a coach is something a child can hear."""
        for milestone in MILESTONES:
            assert milestone.body_for("program", "es") != \
                milestone.body_for("family", "es"), milestone.key

    def test_a_coach_who_writes_their_own_is_flagged_untranslated(self):
        """There is no translation service here, and pretending otherwise
        would be worse than the gap."""
        shipped = MILESTONES[1].to_dict(kind="program", locale="es")
        custom = MILESTONES[1].to_dict(
            body="Great work this week!", customised=True, locale="es")
        assert shipped["translated"] is True
        assert custom["translated"] is False

    def test_a_custom_body_is_returned_exactly_as_typed(self):
        written = "¡Muy bien esta semana!"
        assert MILESTONES[1].to_dict(
            body=written, customised=True, locale="es")["body"] == written


class TestTheMessageMatchesWhatTheChildRead:
    def test_recognition_renders_in_the_athletes_language(self, store):
        org = store.create_org("Northshore")
        store.create_user(org, "director", "Coach Ada")
        team = store.create_team(org, "U15")
        kid = store.create_user(
            org, "athlete", "Jordan P.", birth_year=2011, dominant_hand="right")
        store.join_team(team["join_code"], kid["id"])
        store.set_locale(kid["id"], "es")

        body = MILESTONES[0].body_for("program", store.locale_for(kid["id"]))
        assert "Nos vemos" in body


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


class TestOverTheWire:
    def test_the_bundle_needs_no_login(self, client):
        """Interface copy, like the drill catalog. It contains nothing about
        anybody, and a sign-in page nobody can read is a poor first screen."""
        res = client.get("/api/i18n/es")
        assert res.status_code == 200
        assert res.json()["strings"]["parent.title"] == "Portal para padres"

    def test_a_prefix_narrows_it(self, client):
        body = client.get("/api/i18n/es?prefix=consent.").json()["strings"]
        assert body
        assert all(k.startswith("consent.") for k in body)

    def test_an_unknown_locale_serves_english_rather_than_failing(self, client):
        body = client.get("/api/i18n/klingon").json()
        assert body["locale"] == "en"
        assert body["strings"]["parent.title"] == "Parent portal"

    def test_a_user_can_set_and_read_their_own(self, client):
        org = client.post(
            "/api/orgs", json={"name": "N", "director_name": "Dir"}).json()
        headers = {"Authorization": f"Bearer {org['director']['token']}"}
        assert client.put("/api/me/locale", json={"locale": "es"},
                          headers=headers).json()["locale"] == "es"
        assert client.get("/api/me/locale",
                          headers=headers).json()["locale"] == "es"

    def test_setting_a_locale_needs_a_login(self, client):
        assert client.put("/api/me/locale",
                          json={"locale": "es"}).status_code == 401
