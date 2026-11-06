# Bot log

One entry per run, newest first. Written by the bot; read by a person.
Nothing here has reached `main` until someone merges `bot/improve`.

## 2026-11-05 — Families list no longer says "Invite sent" while email is on hold
- CHANGED: While a program's email is on hold (the default) or there is no mail service, the Families list now says "Invite ready (email is on hold), parent has not signed up" instead of "Invite sent". Once the director releases email it says "Invite sent" as before.
- WHY: Directors were told parents had been emailed when nobody had been, so they waited for sign-ups that could never come.
- PROOF: tests/test_funnel.py::TestInviteWordingFollowsTheEmailHold — 3 tests, red without the change, green with it; full suite green apart from the known date-dependent tests.
- NOTE: An earlier run had left this change half-done and uncommitted. This run checked it, tested it and committed it, and did nothing else. The funnel response also gains a `mail_sending` flag. The page shows whatever label the server sends, so no HTML or CSS changed.
- NEXT: Find out why the three UI walks broke after the cards began folding (backlog).
