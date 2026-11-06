# Bot log

One entry per run, newest first. Written by the bot; read by a person.
Nothing here has reached `main` until someone merges `bot/improve`.

## 2026-11-06 — Before-practice card reads properly on a phone
- CHANGED: On a phone, each player on the coach's "Before practice" card now shows their name with the Not training / Modified / Keep an eye label on one line, and what to do ("Keep them off hard conditioning, throwing, upper-body work.") across the full width underneath. Before, that instruction was squeezed into a third of the card, two or three words a line, and at 360px it ran past the right edge.
- WHY: Coaches checking on their phone, minutes before practice, who is not training and what to hold an injured player back from.
- PROOF: new scripts/ui/walk-practice-phone.mjs (fresh program, three players reporting a head knock, a sore shoulder and a sore wrist) failed before the change (360px: table 310px in a 302px box, 3 of 9 values off screen, instruction in 31% of the card; 390px: 33%) and passes after (9/9 on screen, instruction full width, laptop three columns unchanged at 1280px). Screenshots at 360px and 1280px looked at. Full test suite green: 4813 passed, no failures (the known date-dependent tests passed too).
- NOTE: Stylesheet pin bumped to v=27 on all pages, hash updated in tests/test_branding.py. Layout only; what the card says, and who sees it, is unchanged.
- NEXT: The remaining coach-side tables at 360px: ball framing and sync links (backlog).

## 2026-11-06 — Evaluation export fits a phone: Form and Trend on screen
- CHANGED: On a phone, the Evaluation export list (after pressing "Show") now shows each player's name on its own line with Weeks trained, Participation, Form and Trend labelled two by two underneath, instead of a five-column table where Form and Trend were cut off the right edge.
- WHY: Directors and coaches preparing tryouts or season reviews on a phone; Form and Trend are the improvement half of the report and they could not see them.
- PROOF: new scripts/ui/walk-evaluation-phone.mjs (fresh program, two players) failed before the change at 360px and 390px (table 410px wide in a 302px box, 4 of 10 values off screen, no labels) and passes after (10/10 on screen, every value labelled); laptop table unchanged at 1280px. walk-evaluation.mjs and walk-standings-phone.mjs still pass. Screenshots at 360px and 1280px looked at. Full test suite green: 4813 passed, no failures (the known date-dependent tests passed too).
- NOTE: Stylesheet pin bumped to v=26 on all pages, hash updated in tests/test_branding.py. The CSV download is unchanged.
- NEXT: The remaining coach-side tables at 360px: practice card, ball framing, sync links (backlog).

## 2026-11-06 — Evaluation export works again with "All teams"
- CHANGED: Pressing "Show" or "Download CSV" on the dashboard's Evaluation export card now lists the players. Before, with "All teams" picked (what the card opens on), it showed "Request failed (500)" and the download failed, for every director and coach. A coach assigned to one team who picks "All teams" sees only their own team's players.
- WHY: Directors and coaches preparing tryouts and end-of-season reviews; the card did nothing unless they first picked a single team.
- PROOF: two new tests in tests/test_evaluation.py (All teams answers for the page and the CSV; a one-team coach sees only their team) failed before the fix with the server error and pass after. New scripts/ui/walk-evaluation.mjs (fresh program, 390px and 1280px) failed on the old code (HTTP 500, error on the card) and passes on the new; phone screenshot looked at. Full test suite green: 4813 passed, no failures (the known date-dependent tests passed too).
- NOTE: The report was handed the coach's team filter in one shape and expected another. Only the server changed; no page or CSS change. Found while checking the evaluation table at phone width, which is still cut off on the right (added to backlog).
- NEXT: Stack the Evaluation table on a phone so Form and Trend are on screen.

## 2026-11-06 — Roster upload preview says what each column became, in plain words
- CHANGED: After a director picks a roster file, the list at the top of the preview now reads "Parent Email → parent's email", "Hand → strong hand", "Parent 2 Phone → second parent's phone" and so on, instead of the computer's names ("guardian_email", "dominant_hand", "guardian2_phone"). Each pair is its own small tag, so on a phone a pair no longer breaks in half across two lines or runs into the next one.
- WHY: Directors uploading their roster. That line is how they check the parent columns were read as parents before they press Import; "guardian2_phone" did not tell them that.
- PROOF: new scripts/ui/walk-import-mapping.mjs (fresh program, 17-column file, 390px phone) failed before the change (11 internal names shown, "Parent Email" not read as "parent's email") and passes after; it also fails if two tags overlap, run off the box, or a short pair breaks across lines. Phone screenshot looked at. Full test suite green: 4811 passed, no failures (the known date-dependent tests passed this time too).
- NOTE: Page-only change (coach.html, inline styles); styles.css untouched, so no stylesheet pin bump. The server's field names are unchanged; only the words shown changed.
- NEXT: The coach-side tables at 360px (evaluation, practice card, ball framing, sync links), per backlog.

## 2026-11-06 — Roster upload preview fits a phone: new / update / skip on screen
- CHANGED: On a phone, the preview shown after a roster file is picked (before "Import N new") now lists each player as a small block: name and its new / update / skip label on the first line, then row, number, position, birth year and hand, each labelled. Before, it was a seven-column table where the new / update / skip label was off the right edge. The "players with no parent email" warning now reads as one paragraph with its warning dot, instead of being chopped into narrow columns (it was broken that way on a laptop too).
- WHY: Directors uploading their roster from a phone, in the walkthrough or on the dashboard. Whether a row will be added, updated or skipped is what they check before they press Import.
- PROOF: new scripts/ui/walk-import-preview-phone.mjs (fresh program, five-row file) failed before the change at 360px and 390px (table 434px wide in a 302px box, every new / update / skip off screen) and passes after; it also fails if a value such as "Midfield" breaks mid-word, which the first version of the fix did. Screenshots at 360px and 1280px looked at. walk-dropbox (the walkthrough's roster step), walk-roster-phone, walk-teams-phone, walk-standings-phone and walk-stat-strip still pass. Full test suite green apart from the known date-dependent tests.
- NOTE: Stylesheet pin bumped to v=25 on all pages, hash updated in tests/test_branding.py. The laptop table is unchanged.
- NEXT: The other coach-side tables at 360px: evaluation, practice card, ball framing, sync links (backlog).

## 2026-11-06 — Team standings fit a phone: Total XP on screen
- CHANGED: On a phone, each team in the Team standings card now shows its rank and name on one line, with "XP each", "Participation" and "Total XP" labelled underneath, instead of a five-column table where "Total XP" was cut off the right edge. A team with one player now says "1 athlete", not "1 athletes".
- WHY: Directors and coaches checking how their teams compare on a phone; the total was the column they could not see.
- PROOF: new scripts/ui/walk-standings-phone.mjs (fresh program, two teams) failed before the change at 360px and 390px (table 346px wide in a 302px box, Total XP off screen) and passes after; it also checks no label runs into the next one and the laptop table keeps its headers at 1280px. Screenshots at 360px and 1280px looked at. Full test suite green apart from the known date-dependent tests.
- NOTE: Stylesheet pin bumped to v=24 on all pages, hash updated in tests/test_branding.py. On a phone the first label reads "XP each" because "XP / athlete" wrapped onto two lines and pushed its number below the others; the laptop header is unchanged.
- NEXT: The coach-side tables (evaluation, practice card, ball framing) at 360px (backlog).

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
