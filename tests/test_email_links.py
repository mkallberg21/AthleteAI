"""Every link an email tells someone to open is a real, clickable hyperlink.

The plain-text part carries the address on a line of its own. The HTML part has the button AND the same address written
out under it as a hyperlink, so it works in every mail program, including ones that strip button styling. The dashboard
preview shows the real HTML email, and "copy message" keeps the link a link when it is pasted into Gmail or Outlook.
"""
from __future__ import annotations

import re
from dataclasses import replace
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

import offdays.api as api_module
from offdays import guardians, invites, mailer, parent_signin, sender_email, staff_mail
from offdays.config import CONFIG
from offdays.db import connect
from offdays.store import Store

BASE = "https://app.0ffdays.com"
URL = re.compile(r"https?://[^\s<>\"']+")


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []          # (href, visible text)
        self._href = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._buf = []

    def handle_data(self, data):
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._buf).strip()))
            self._href = None


def anchors(html):
    p = Anchors()
    p.feed(html)
    return p.links


@pytest.fixture(autouse=True)
def with_a_host(monkeypatch):
    patched = replace(CONFIG, app_base_url=BASE, smtp_host="smtp.test")
    for mod in (invites, mailer, guardians, staff_mail, sender_email):
        if hasattr(mod, "CONFIG"):
            monkeypatch.setattr(mod, "CONFIG", patched)
    monkeypatch.setattr(api_module, "CONFIG", patched)
    import offdays.config as config_module
    monkeypatch.setattr(config_module, "CONFIG", patched)       # guardians.signin_link reads it at call time


def emails():
    """Every kind of email that tells a person to open a link: (name, text, html)."""
    out = []
    s, h, t = invites.compose(athlete_name="Ben Amden", org_name="Nashville Dogs", coach_name="Matt", code="ABCD-EFGH-JKLM")
    out.append(("parent invite", t, h))
    s, h, t = invites.compose(athlete_name="Ben Amden", org_name="Nashville Dogs", coach_name="Matt", code="ABCD-EFGH-JKLM",
                              intro="Hi all.\n\nMatt here.", reply_to="matt@x.example")
    out.append(("parent invite with a note", t, h))
    s, h, t = invites.compose(athlete_name="Dillon Langdon", org_name="Nashville Dogs", coach_name="Matt",
                              code="ABCD-EFGH-JKLM", also=["Killian Langdon"])
    out.append(("parent invite for a family", t, h))
    s, h, t = invites.compose_staff(coach_name="Sam", org_name="Nashville Dogs", director_name="Matt", code="ABCDEF")
    out.append(("coach sign-in", t, h))
    for kind in ("confirm", "reset"):
        link = f"{BASE}/app/index.html?{kind}=TOKEN_a-b"
        s, t, h = staff_mail._compose(kind, "Nashville Dogs", link)
        out.append((f"staff {kind}", t, h))
    s, t, h = parent_signin._compose("Nashville Dogs", "Ben and Cole", f"{BASE}/app/index.html?parent=TOKEN_a-b")
    out.append(("parent back in", t, h))
    s, h, t = sender_email._compose("Nashville Dogs", f"{BASE}/app/index.html?sender=TOKEN_a-b")
    out.append(("sender confirm", t, h))
    return out


NAMES = ["parent invite", "parent invite with a note", "parent invite for a family", "coach sign-in", "staff confirm",
         "staff reset", "parent back in", "sender confirm"]


@pytest.fixture
def email(request):
    """(text, html) of one kind of email, built AFTER the test host is set."""
    return {n: (t, h) for n, t, h in emails()}[request.param]


@pytest.mark.parametrize("email", NAMES, indirect=True)
class TestEveryEmailLinkIsClickable:
    def test_the_text_has_the_link_on_a_line_of_its_own(self, email):
        name = 'email'
        text, html = email
        urls = URL.findall(text)
        assert urls, name
        lines = [ln.strip() for ln in text.splitlines()]
        for u in urls:
            assert u in lines, f"{name}: {u} is not on its own line"

    def test_every_address_in_the_text_is_a_hyperlink_in_the_html(self, email):
        name = 'email'
        text, html = email
        hrefs = [h for h, _ in anchors(html)]
        for u in URL.findall(text):
            assert u in hrefs, f"{name}: {u} is not a hyperlink"

    def test_the_address_is_also_written_out_as_clickable_text(self, email):
        name = 'email'
        text, html = email
        shown = [(h, t) for h, t in anchors(html) if t.startswith("http")]
        for u in URL.findall(text):
            assert (u, u) in shown, f"{name}: {u} is not shown as a link"

    def test_the_button_is_still_there(self, email):
        text, html = email
        assert 'style="display:inline-block;padding:12px 20px' in html

    def test_no_bare_address_sits_in_the_html_outside_a_hyperlink(self, email):
        name = 'email'
        text, html = email
        stripped = re.sub(r"<a [^>]*>.*?</a>", "", html, flags=re.S)
        assert not URL.search(re.sub(r"<[^>]+>", " ", stripped)), name


class TestTheAddressIsEscapedInHtml:
    def test_an_ampersand_in_a_link_is_valid_html_and_still_the_same_link(self):
        s, t, h = staff_mail._compose("reset", "Club", f"{BASE}/app/index.html?a=1&b=2")
        assert "a=1&amp;b=2" in h and "a=1&b=2" not in re.sub(r"&amp;", "", h).replace("a=1b=2", "")
        assert (f"{BASE}/app/index.html?a=1&b=2", f"{BASE}/app/index.html?a=1&b=2") in anchors(h)


class Recorder:
    def __init__(self):
        self.sent = []

    def send(self, to_email, subject, html, text, headers):
        self.sent.append({"to": to_email, "html": html, "text": text})
        return mailer.SendResult(ok=True)


@pytest.fixture
def client(tmp_path, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(mailer, "default_transport", lambda: rec)
    api_module._store = Store(connect(tmp_path / "t.db"))
    c = TestClient(api_module.app)
    c.rec = rec
    yield c
    api_module._store = None


CSV = "First Name,Last Name,Birth Year,Parent Email\nBen,Amden,2013,jess@example.com\n"


def program(client, release):
    made = client.post("/api/orgs", json={"name": "Nashville Dogs", "sport": "lacrosse", "accept_terms": True,
                                          "director_name": "Matt"}).json()
    h = {"Authorization": f"Bearer {made['director']['token']}"}
    if release:
        client.put("/api/org/mail-hold", headers=h, json={"held": False})
    team = client.post("/api/teams", json={"name": "2031 Red"}, headers=h).json()["id"]
    return h, team


def has_link(html, code_re=r"invite=[A-Z0-9-]{14}"):
    return any(re.search(code_re, h) and t == h for h, t in anchors(html))


class TestWhatActuallyGoesOut:
    def test_the_email_a_parent_receives_has_the_link_hyperlinked_twice(self, client):
        h, team = program(client, release=True)
        client.post("/api/coach/roster/import", headers=h, json={"content": CSV, "team_id": team})
        assert len(client.rec.sent) == 1
        html = client.rec.sent[0]["html"]
        links = [(a, b) for a, b in anchors(html) if "invite=" in a]
        assert len(links) == 2                                   # the button and the written-out link
        assert has_link(html)

    def test_what_the_director_copies_to_send_themselves_carries_the_hyperlinked_email(self, client):
        h, team = program(client, release=False)                   # on hold: nothing is emailed, they send it themselves
        res = client.post("/api/coach/roster/import", headers=h, json={"content": CSV, "team_id": team}).json()
        inv = res["guardian_invites"][0]
        assert inv["emailed"] is False and has_link(inv["html"])
        ben = [r["athlete_id"] for r in client.get("/api/coach/team-ranking", headers=h, params={"team_id": team}).json()["rows"]][0]
        again = client.post("/api/coach/families/nudge", headers=h, json={"athlete_id": ben}).json()
        assert has_link(again["html"])
        one = client.post("/api/coach/guardian-invites", headers=h, json={"athlete_id": ben, "email": "j@example.com"}).json()
        assert has_link(one["html"])

    def test_the_preview_is_the_real_html_email(self, client):
        h, team = program(client, release=False)
        res = client.post("/api/coach/families/invite-preview", headers=h, json={"intro": "Hi"}).json()
        assert has_link(res["html"], r"invite=ABCD-EFGH-JKLM")


class TestTheScreens:
    @staticmethod
    def page(name):
        from pathlib import Path
        return (Path(api_module.__file__).parent / "web" / "static" / name).read_text(encoding="utf-8")

    def test_the_preview_shows_the_email_as_a_parent_sees_it(self):
        html = self.page("coach.html")
        assert '<iframe title="What a parent will receive"' in html and 'sandbox="allow-popups' in html
        assert "m.html" in html and 'target="_blank"' in html
        assert "the button and the link under it are both clickable" in html

    def test_copying_a_message_keeps_the_link_a_link(self):
        html = self.page("coach.html")
        assert "new ClipboardItem" in html and "'text/html': new Blob([html]" in html and "r.html" in html

    def test_a_parents_email_to_their_athlete_puts_the_link_on_its_own_line(self):
        html = self.page("parent.html")
        assert "const emailBody = `${first}, tap this link to sign in to your training app:\\n\\n${link}\\n\\n" in html
        assert "body=${encodeURIComponent(emailBody)}\">Email</a>" in html
        assert "sms:?&body=${encodeURIComponent(message)}" in html    # a text message keeps one line
