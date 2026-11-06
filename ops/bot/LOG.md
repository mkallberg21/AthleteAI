# Bot log

One entry per run, newest first. Written by the bot; read by a person.
Nothing here has reached `main` until someone merges `bot/improve`.

## 2026-11-06 — Roster fits a phone: Last active and Status on screen
- CHANGED: On a phone, each player in the Roster card now shows as its own small block (name, team, Email parent, then Sessions, Strong / Off-hand, Last active and Status, each with its label) instead of a five-column table where "Last active" was cut off and "Status" (e.g. "never trained") was hidden off the right edge.
- WHY: Coaches and directors checking their roster on a phone; the column that says who has not trained yet was the one they could not see.
- PROOF: new scripts/ui/walk-roster-phone.mjs (fresh program, three players) failed before the change at 360px and 390px (table 435px wide in a 302px box, every Status off screen) and passes after; laptop table unchanged at 1280px. Screenshots at 360px and 1280px looked at. Full test suite green apart from the known date-dependent tests.
- NOTE: Stylesheet pin bumped to v=23 on all pages, hash updated in tests/test_branding.py. Same pattern as the Teams table change.
- NEXT: Team standings and the other dashboard tables at 360px (backlog).

## 2026-11-06 — Teams list fits a phone: join code and Remove on screen
- CHANGED: On a phone, each team in the Teams list now shows as its own small block (name, coach, roster, wall ball, shots, join code with its Remove button) instead of a six-column table where the join code and Remove button were hidden off the right edge.
- WHY: Directors setting up on a phone; they could not see the code to give a coach or the button to remove a team made by mistake without discovering a sideways scroll.
- PROOF: new scripts/ui/walk-teams-phone.mjs (fresh program, two teams) failed before the change at 360px and 390px (table 506px wide in a 302px box, join codes and Remove off screen) and passes after; it also checks the stacked numbers sit under their labels and the laptop table is unchanged at 1280px. Screenshots at 360px and 1280px looked at. walk-create-team.mjs still creates and removes teams. Full test suite green apart from the known date-dependent tests.
- NOTE: Stylesheet pin bumped to v=22 on all pages, hash updated in tests/test_branding.py. On a phone the labels read "Wall ball" and "Shots" (the laptop headers still say "/day").
- NEXT: Give the roster table the same phone layout (backlog).

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
