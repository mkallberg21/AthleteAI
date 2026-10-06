"""A new program's families get in without the coach doing anything by hand.

Upload the roster, the parent gets an email with a link, they tap it, say yes
to training, and the app gives them a sign-in link to text to the child.
Every step
was already half-built; these tests pin the joins between them, because the
joins are where it was broken -- an invite that was stored but never sent,
a sign-up button with no handler, a claim code only the coach could see.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import guardians as G
from offdays import invites, mailer, roster
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store, StoreError

STATIC = Path(__file__).resolve().parents[1] / "offdays" / "web" / "static"

CSV = (
    "Last Name,First Name,#,Birth Year,Parent Email\n"
    "Pierce,Jordan,14,2012,dana@example.com\n"
    "Rivera,Sam,7,2012,\n"
    "Okafor,Lee,3,2012,not-an-address\n"
)


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "f.db"))


@pytest.fixture
def program(store):
    org = store.create_org("Nashville Dogs")
    coach = store.create_user(org, "coach", "Coach Mike")
    team = store.create_team(org, "2031 Red")
    return {"org": org, "coach": coach, "team": team}


def import_roster(store, program, **kw):
    plan = store.resolve_import(program["org"], roster.parse(CSV))
    return store.apply_import(
        program["org"], program["team"]["id"], plan, program["coach"]["id"], **kw
    )


def outbox(store):
    return store.conn.execute(
        "SELECT to_email, subject, text_body, kind, status, dedupe_key "
        "FROM email_outbox ORDER BY id"
    ).fetchall()


class TestImportEmailsTheParent:
    def test_one_email_per_parent_with_an_address(self, store, program):
        result = import_roster(store, program)
        # The parser already drops "not-an-address", so one invite, one email.
        assert len(result["guardian_invites"]) == 1
        assert result["emailed"] == 1
        rows = outbox(store)
        assert [r["to_email"] for r in rows] == ["dana@example.com"]

    def test_the_email_carries_the_link_the_code_and_the_promise(
        self, store, program, monkeypatch
    ):
        # CONFIG is frozen; swap the whole object the way the mailer reads it.
        from dataclasses import replace
        patched = replace(CONFIG, app_base_url="https://app.0ffdays.com")
        monkeypatch.setattr(invites, "CONFIG", patched)
        result = import_roster(store, program)
        invite = next(i for i in result["guardian_invites"] if i["emailed"])
        body = outbox(store)[0]["text_body"]
        assert f"https://app.0ffdays.com/app/index.html?invite={invite['code']}" in body
        assert invite["code"] in body
        assert "video never leaves the phone" in body
        assert "Coach Mike" in body and "Nashville Dogs" in body
        assert outbox(store)[0]["subject"] == "Nashville Dogs: set up Jordan's training app"

    def test_it_is_transactional_so_a_digest_opt_out_does_not_block_it(
        self, store, program
    ):
        import_roster(store, program)
        assert outbox(store)[0]["kind"] == mailer.Kind.TRANSACTIONAL

    def test_a_second_import_does_not_send_the_same_invite_twice(self, store, program):
        import_roster(store, program)
        # Re-importing updates rather than creates, and mints a new invite
        # (a new code) -- that is one new email, not a duplicate of the first.
        import_roster(store, program)
        keys = {r["dedupe_key"] for r in outbox(store)}
        assert len(keys) == len(outbox(store))

    def test_declining_invites_sends_nothing(self, store, program):
        import_roster(store, program, issue_guardian_invites=False)
        assert outbox(store) == []

    def test_an_invite_without_an_address_is_not_queued_and_says_so(self, store, program):
        result = import_roster(store, program, issue_guardian_invites=False)
        sam = next(a for a in result["created"] if a["display_name"] == "Sam Rivera")
        invite = G.create_invite(store.conn, sam["athlete_id"], program["coach"]["id"])
        assert invites.deliver(
            store.conn, invite, org_name="Nashville Dogs", coach_name="Coach Mike"
        ) is False
        assert outbox(store) == []

    def test_delivery_status_names_what_went_where(self, store, program):
        result = import_roster(store, program)
        sam = next(a for a in result["created"] if a["display_name"] == "Sam Rivera")
        unsent = G.create_invite(store.conn, sam["athlete_id"], program["coach"]["id"])
        ids = [i["invite_id"] for i in result["guardian_invites"]] + [unsent["invite_id"]]
        status = invites.delivery_status(store.conn, ids)
        assert sorted(status.values()) == ["none", "queued"]
        mailer.flush(store.conn, transport=mailer.ConsoleTransport())
        assert sorted(invites.delivery_status(store.conn, ids).values()) == ["none", "sent"]


class TestTheLinkedCodeWorks:
    def test_the_emailed_code_redeems_to_a_guardian_of_that_child(self, store, program):
        result = import_roster(store, program)
        invite = next(i for i in result["guardian_invites"] if i["emailed"])
        guardian = G.redeem_invite(store.conn, invite["code"], "Dana Pierce")
        assert guardian["athlete_name"] == "Jordan Pierce"
        assert G.guards(store.conn, guardian["guardian_id"], invite["athlete_id"])


class TestParentForwardsTheSignInLink:
    """The parent is on a tablet; the kid has a phone. What the parent needs
    is a link to text or email, and they only get it after saying yes. It
    then works all season, on any phone, until a parent issues a new one."""

    def _family(self, store, program):
        result = import_roster(store, program)
        invite = next(i for i in result["guardian_invites"] if i["emailed"])
        guardian = G.redeem_invite(store.conn, invite["code"], "Dana Pierce")
        return guardian["guardian_id"], invite["athlete_id"]

    def test_refused_until_training_is_switched_on(self, store, program):
        gid, aid = self._family(store, program)
        with pytest.raises(G.GuardianError, match="Say yes to training first"):
            G.athlete_signin_link(store.conn, gid, aid)

    def test_the_link_carries_the_standing_sign_in_code(self, store, program):
        gid, aid = self._family(store, program)
        G.set_consent(store.conn, aid, gid, G.Scope.PARTICIPATION, True)
        out = G.athlete_signin_link(store.conn, gid, aid)
        assert out["athlete_name"] == "Jordan Pierce"
        assert out["link"].endswith(f"/app/index.html?code={out['code']}")
        assert "expires_at" not in out
        assert store.authenticate(out["code"]).id == aid

    def test_the_same_link_works_again_and_again_on_any_phone(self, store, program):
        """Parent says yes once; the kid is in for the season."""
        gid, aid = self._family(store, program)
        G.set_consent(store.conn, aid, gid, G.Scope.PARTICIPATION, True)
        code = G.athlete_signin_link(store.conn, gid, aid)["code"]
        for _ in range(3):
            assert store.authenticate(code).id == aid

    def test_it_retires_the_printed_claim_code(self, store, program):
        """A slip that went astray stops working the moment the parent does this."""
        result = import_roster(store, program)
        slip = next(a for a in result["created"] if a["display_name"] == "Jordan Pierce")
        invite = next(i for i in result["guardian_invites"] if i["emailed"])
        guardian = G.redeem_invite(store.conn, invite["code"], "Dana Pierce")
        G.set_consent(store.conn, invite["athlete_id"], guardian["guardian_id"],
                      G.Scope.PARTICIPATION, True)
        G.athlete_signin_link(store.conn, guardian["guardian_id"], invite["athlete_id"])
        with pytest.raises(StoreError, match="not valid"):
            store.claim_account(slip["claim_code"])

    def test_a_new_link_turns_the_old_one_off_everywhere(self, store, program):
        """Asking for a new one is how a parent revokes a link that went astray."""
        gid, aid = self._family(store, program)
        G.set_consent(store.conn, aid, gid, G.Scope.PARTICIPATION, True)
        first = G.athlete_signin_link(store.conn, gid, aid)["code"]
        second = G.athlete_signin_link(store.conn, gid, aid)["code"]
        assert first != second
        assert store.authenticate(second).id == aid
        with pytest.raises(StoreError):
            store.authenticate(first)

    def test_withdrawing_consent_pauses_recording_but_keeps_the_kid_signed_in(
        self, store, program
    ):
        """The app says 'waiting on a parent'; it does not throw them out."""
        from offdays import onboarding
        gid, aid = self._family(store, program)
        G.set_consent(store.conn, aid, gid, G.Scope.PARTICIPATION, True)
        code = G.athlete_signin_link(store.conn, gid, aid)["code"]
        G.set_consent(store.conn, aid, gid, G.Scope.PARTICIPATION, False)
        assert store.authenticate(code).id == aid
        assert onboarding.athlete_blockers(store.conn, aid)[0]["key"] == "awaiting_consent"
        with pytest.raises(StoreError):
            store.start_session(aid, "lax_wall_ball")

    def test_a_parent_cannot_mint_a_link_for_another_family(self, store, program):
        gid, aid = self._family(store, program)
        other = store.conn.execute(
            "SELECT id FROM users WHERE display_name = 'Sam Rivera'"
        ).fetchone()["id"]
        G.set_consent(store.conn, other, None, G.Scope.PARTICIPATION, True)
        with pytest.raises(G.GuardianError, match="not listed as a guardian"):
            G.athlete_signin_link(store.conn, gid, other)


class TestThroughTheApi:
    @pytest.fixture
    def client(self, tmp_path):
        api_module._store = Store(connect(tmp_path / "api.db"))
        yield TestClient(api_module.app)
        api_module._store = None

    @pytest.fixture
    def director(self, client):
        org = client.post(
            "/api/orgs", json={"name": "Nashville Dogs", "director_name": "Dir K"}
        ).json()
        headers = {"Authorization": f"Bearer {org['director']['token']}"}
        team = client.post(
            "/api/teams", json={"name": "2031 Red", "season": "2026"}, headers=headers
        ).json()
        return {"headers": headers, "team": team}

    def test_the_whole_chain_end_to_end(self, client, director):
        imported = client.post(
            "/api/coach/roster/import",
            json={"content": CSV, "team_id": director["team"]["id"]},
            headers=director["headers"],
        ).json()
        assert imported["emailed"] == 1
        invite = next(i for i in imported["guardian_invites"] if i["emailed"])

        # The list the coach sees says the email was queued.
        listed = client.get("/api/coach/guardian-invites", headers=director["headers"]).json()
        by_id = {i["id"]: i for i in listed["invites"]}
        assert by_id[invite["invite_id"]]["email_status"] == "queued"
        assert "smtp_configured" in listed

        # Parent taps the link, signs up.
        parent = client.post(
            "/api/guardians/redeem",
            json={"code": invite["code"], "display_name": "Dana Pierce"},
        ).json()
        ph = {"Authorization": f"Bearer {parent['token']}"}

        # Not yet: the gate is in the parent's words.
        refused = client.post(
            f"/api/guardians/athlete-link/{invite['athlete_id']}", headers=ph
        )
        assert refused.status_code == 400
        assert "Say yes to training first" in refused.json()["detail"]

        client.post(
            "/api/guardians/consent",
            json={"athlete_id": invite["athlete_id"], "scope": "participation", "granted": True},
            headers=ph,
        )
        sent = client.post(
            f"/api/guardians/athlete-link/{invite['athlete_id']}", headers=ph
        ).json()
        assert sent["link"].endswith(f"?code={sent['code']}")

        # The child taps the link: the page signs in with the code in the URL
        # and lands on home -- drills, film, leaderboard -- not the camera.
        code = sent["code"]
        me = client.get("/api/me", headers={"Authorization": f"Bearer {code}"}).json()
        assert me["role"] == "athlete" and me["display_name"] == "Jordan Pierce"
        started = client.post(
            "/api/sessions/start", json={"drill_key": "lax_wall_ball"},
            headers={"Authorization": f"Bearer {code}"},
        )
        assert started.status_code == 201, started.text

    def test_a_coach_issued_invite_with_an_email_is_sent_too(self, client, director):
        imported = client.post(
            "/api/coach/roster/import",
            json={"content": CSV, "team_id": director["team"]["id"],
                  "invite_guardians": False},
            headers=director["headers"],
        ).json()
        sam = next(a for a in imported["created"] if a["display_name"] == "Sam Rivera")
        res = client.post(
            "/api/coach/guardian-invites",
            json={"athlete_id": sam["athlete_id"], "email": "rivera@example.com"},
            headers=director["headers"],
        ).json()
        assert res["emailed"] is True
        assert res["link"].endswith(f"?invite={res['code']}")

    def test_staff_cannot_use_the_parent_code_route(self, client, director):
        imported = client.post(
            "/api/coach/roster/import",
            json={"content": CSV, "team_id": director["team"]["id"]},
            headers=director["headers"],
        ).json()
        aid = imported["created"][0]["athlete_id"]
        res = client.post(f"/api/guardians/athlete-link/{aid}", headers=director["headers"])
        assert res.status_code == 403


class TestTheSignUpPageIsWired:
    """The Sept re-skin dropped the handlers behind two buttons. Keep them."""

    def test_the_parent_and_claim_buttons_have_handlers(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        assert "/api/guardians/redeem" in html
        assert "/api/claim" in html
        assert "get('invite')" in html  # the ?invite= prefill
        assert "get('code')" in html    # the kid's ?code= link signs them in
        assert "requestSubmit()" in html  # ...through the ordinary sign-in form

    def test_the_parent_portal_offers_every_way_to_forward_the_link(self):
        html = (STATIC / "parent.html").read_text(encoding="utf-8")
        assert "/api/guardians/athlete-link/" in html
        for way in ("navigator.clipboard", "navigator.share", "sms:", "mailto:"):
            assert way in html, way
