# Bot log

One entry per run, newest first. Written by the bot; read by a person.
Nothing here has reached `main` until someone merges `bot/improve`.

## 2026-11-06 — Dashboard numbers sit two by two on a phone
- CHANGED: On a phone, the four numbers at the top of the director and coach dashboard (Athletes, Participation, Sessions, Total XP) now show as a neat two-by-two block with space under it, instead of three in a row and "Total XP" alone on a second line pressed against the card below.
- WHY: Directors and coaches checking the dashboard on their phone; the strip looked broken and the last number ran into the setup card.
- PROOF: new scripts/ui/walk-stat-strip.mjs (fresh program, 360px, 390px and 1280px) failed before the change ("a tile sits alone on the last line", "the strip touches the card below it", gap 0px) and passes after (2 + 2, 16px gap; laptop still 4 across). 360px screenshot looked at. Full test suite green apart from the known date-dependent tests.
- NOTE: Stylesheet pin bumped to v=21 on all pages, hash updated in tests/test_branding.py. The same rule also tidies any other four-number strip (e.g. the cost card) on a phone. Also checked the backlog's "three walks broke" item: all three complete now; backlog updated.
- NEXT: The Teams table is wider than a 360px phone; check the Remove button and join code are reachable (backlog).

## 2026-11-05 — Season step: no repeated heading, no "go to the Season card" line
- CHANGED: On the walkthrough's "When the season runs" step, the card's own heading ("Where the season is") and the line telling the director to "set the dates on the Season card" no longer show; the dashboard card keeps both.
- WHY: Directors setting up a program. The step showed two titles, and it told them to go to a card they were already on.
- PROOF: scripts/ui/walk-season-step.mjs (iPhone 13, fresh program) now also checks both; it failed before the change ("card heading repeats the step title", "step tells the director to go to the Season card") and passes after. walk-wizard.mjs still walks every step. Screenshots of the step and the dashboard card looked at. Full test suite green apart from the known date-dependent tests.
- NOTE: The fold styling had been bringing every embedded card's heading back inside the walkthrough; the CSS fix hides it for all of them, not just Season. Stylesheet pin bumped to v=20 on all pages, hash updated in tests/test_branding.py.
- NEXT: Find out why the three UI walks broke after the cards began folding (backlog).

## 2026-11-05 — Director walkthrough's season step asks for the dates only
- CHANGED: A new director setting up their program is now asked only for the season's start and end dates on the "When the season runs" step; the "This program is currently Pre-season / In-season" choice no longer appears there and stays on the dashboard's "Where the season is" card.
- WHY: Directors. The step said "set the start and end dates" but opened with an unexplained phase drop-down, a question a brand-new director cannot answer yet and does not need to.
- PROOF: scripts/ui/walk-season-step.mjs (iPhone 13, fresh program) failed before the change ("phase selector shows in the walkthrough") and passes after; it also checks the selector is still on the dashboard card. Screenshots of both looked at. Full test suite green apart from the known date-dependent tests.
- NOTE: Page-only change (coach.html); no CSS, so no stylesheet pin bump.
- NEXT: Hide the card's own heading and the stray "on the Season card" line inside that same step (backlog).

## 2026-11-05 — Families list no longer says "Invite sent" while email is on hold
- CHANGED: While a program's email is on hold (the default) or there is no mail service, the Families list now says "Invite ready (email is on hold), parent has not signed up" instead of "Invite sent". Once the director releases email it says "Invite sent" as before.
- WHY: Directors were told parents had been emailed when nobody had been, so they waited for sign-ups that could never come.
- PROOF: tests/test_funnel.py::TestInviteWordingFollowsTheEmailHold — 3 tests, red without the change, green with it; full suite green apart from the known date-dependent tests.
- NOTE: An earlier run had left this change half-done and uncommitted. This run checked it, tested it and committed it, and did nothing else. The funnel response also gains a `mail_sending` flag. The page shows whatever label the server sends, so no HTML or CSS changed.
- NEXT: Find out why the three UI walks broke after the cards began folding (backlog).
