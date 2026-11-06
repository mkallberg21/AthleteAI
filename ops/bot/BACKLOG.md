# Backlog

Things worth doing, not yet done. The bot picks from here and adds to it.
Newest ideas at the bottom of each section. Remove an item when it ships.

## Known and open
- The three UI walks (`walk-create-team`, `walk-add-player`, `walk-resend`) all complete again on a fresh local server (checked 2026-11-06). Still to do: make them part of a check that runs. `walk-add-player` prints an empty "cost card" line because it reads `#billing`, which no longer exists (the card is `#billing-card`).
- Teams and Roster tables now stack on a phone (walk-teams-phone.mjs, walk-roster-phone.mjs). Still to check at 360px: Team standings and any other dashboard table.
- Dashboard cards fold, but a program with real players has not been looked at by eye.
- Splash screen for the phone app is still Capacitor's default.
- Push notifications are not built.
- One team link and message for the director to send to every parent (design exists, not built).

## Ideas to look at
- Empty states: every card on a brand-new program says what it is for and what to do first.
- Keyboard and screen-reader pass over the director and parent pages.
- Phone pass over every page at 360px wide.
- Speed: what does the first load cost on a slow connection?
