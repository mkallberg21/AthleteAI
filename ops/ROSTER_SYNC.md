# Roster sync

How a team's roster gets into 0FFDAYS and stays current, what each source is
proven to do, and what to do on day one of a pilot.

Code: `offdays/roster.py` (the parser), `offdays/roster_sync.py` (providers,
departures, scheduled sweep), `Store.link_roster / sync_roster / apply_import`
in `offdays/store.py`, routes under `/api/coach/roster/*` in `offdays/api.py`,
cron entry `scripts/run_roster_sync.py`. Tests: `tests/test_roster.py`,
`tests/test_roster_sync.py`.

---

## TL;DR for the Nashville Dogs pilot

**Use the CSV upload.** Export the roster from wherever it lives (TeamSnap,
SportsEngine, a spreadsheet), upload it on the coach dashboard, read the
preview, import. It is the one path that is proven end to end. Do not connect
TeamSnap or SportsEngine for the first time on the day families are signing
up. Nobody has run those adapters against a real account yet (see
[Provider status](#provider-status)).

---

## The three ways in

| Path | What the coach does | When to use it |
|---|---|---|
| **Upload** | Dashboard → Roster → upload a CSV/TSV. Preview, then import. | Day one. Any time. |
| **Export link** (`csv_url`) | Paste a URL that returns a CSV (plus a token if it needs one). | The roster changes during the season and the platform can publish a CSV link. |
| **TeamSnap / SportsEngine** | Paste an API token and the team id. | After it has been [verified](#verifying-a-hosted-adapter) against the club's real account. |

All three end in the same place. A provider's only job is to return rows. Those
rows are turned back into CSV (`roster_sync.rows_to_csv`) and parsed by
exactly the same `roster.parse` the upload button uses. Header detection,
name handling, birth-year inference, duplicate matching and claim codes are
the same code whichever way the roster arrived.

---

## What the parser accepts

Only a **name** is required. Headers are matched loosely: case,
spaces and punctuation are ignored, and a header containing a known alias still
matches (`Player Jersey #` → jersey).

| Field | Headers it recognises (after normalising) |
|---|---|
| first name | `First Name`, `First`, `Given Name`, `FName` |
| last name | `Last Name`, `Last`, `Surname`, `Family Name`, `LName` |
| full name | `Name`, `Full Name`, `Athlete`, `Player`. `Last, First` is swapped automatically |
| jersey | `#`, `No.`, `No`, `Num`, `Jersey`, `Jersey Number`, `Number`, `Uniform` |
| position | `Position`, `Pos`, `Role` |
| birth year | `Birth Year`, `YOB`, `Class Of`, `Grad Year` (grad/class years are estimates → athlete treated as a minor) |
| birth date | `DOB`, `Birth Date`, `Date of Birth`, `Birthday` |
| grade | `Grade`, `Grade Level`, `School Year` |
| hand | `Dominant Hand`, `Hand`, `Shoots`, `Shot` |
| athlete email | `Email`, `Athlete Email`, `Player Email` |
| **guardian email** | `Parent Email`, `Guardian Email`, `Parent`, `Guardian`, `Contact Email`, `Parent1 Email`, `Mother Email`, `Father Email` |
| guardian name | `Parent Name`, `Guardian Name`, `Contact Name` |
| other sports | `Sports`, `Other Sports`, `Multi Sport` |
| external id | `ID`, `Member ID`, `Player ID`, `Athlete ID` |

The source of truth is `FIELD_ALIASES` in `offdays/roster.py`. Update this
table when that changes.

Limits: 2,000 rows per file, delimited text only (CSV, TSV, semicolon). A
native `.xlsx` must be saved as CSV first. A template is at
`GET /api/coach/roster/template`.

**A guardian email column matters.** When it is present, import issues a
single-use, 14-day guardian invite for each athlete automatically
(`invite_guardians` defaults to true). Without it, a coach has to send invites
by hand.

---

## Upload flow

1. `POST /api/coach/roster/preview` with the file content. **Nothing is
   written.** The response lists every create, every update, every row it
   could not read and why.
2. The coach reads it. This is where a bad export shows up: wrong team, a
   header that did not match, 40 rows with no names.
3. `POST /api/coach/roster/import` with the same content and a `team_id`. The
   server **re-parses the file** and does not trust the preview the client
   sends back, so an edited payload cannot create athletes the file did not
   contain.

Re-importing is safe. Athletes are matched by normalised name (and external id
when present), so the second upload updates rather than duplicates.

---

## Linked sources (export link, TeamSnap, SportsEngine)

### Lifecycle

```
link  ──► dry run (automatic) ──► coach reads it ──► manual sync (apply)
                                                        │
                                  auto-sync ON ◄────────┘  (only if the last run succeeded)
                                        │
                                  cron every 6h  (scripts/run_roster_sync.py)
```

1. **Link.** `POST /api/coach/roster/link` stores the provider, token and
   team id / URL, then **immediately dry-runs** and returns the preview. The
   dry run cannot be skipped, because a wrong team id is the most common first
   mistake and it looks like a real roster until someone reads the names.
2. **Sync by hand.** `POST /api/coach/roster/sync` with `apply: false` runs
   another dry run. With `apply: true` it writes.
3. **Auto-sync.** `POST /api/coach/roster/auto-sync {on: true}` is **refused
   unless the last run succeeded**, so a broken link never goes onto a schedule.
4. **Scheduled sweep.** `scripts/run_roster_sync.py` (cron, every 6 h) calls
   `roster_sync.run_due`, which syncs every auto-sync link not run in the last
   12 h. One failing link never stops the others. Each failure is written to
   that link's `last_result`, where its coach sees it.
5. **Unlink.** `DELETE /api/coach/roster/link`. Athletes already imported stay.

### Safety rails (and why)

| Rail | Behaviour | Why |
|---|---|---|
| **Departures are never applied** | Someone missing from the remote roster is *reported* by name and never deactivated or deleted. | A coach tidying TeamSnap, or an API hiccup returning a short page, must not destroy a child's training history. |
| **Departure alarm** | If more than 50% of the current roster would be departures, the whole sync is refused and nothing is applied. | A wrong team id and a mass exodus look identical. Only one is plausible. |
| **Empty roster refused** | Zero rows back → error, nothing changed. | Almost always a wrong team id, not an empty team. |
| **Tokens are write-only** | Stored, used by the sync, never returned by any endpoint or written to a log. | The token reaches into a system holding children's contact details. |
| **HTTPS only, bounded fetch** | Non-https URLs refused, 20 s timeout, 8 MB / 5,000-row cap. | A hung or runaway third-party response must not take the cron job down with it. |

Consequence: **roster sync never removes anyone.** A program with mid-season
turnover has to deactivate departed athletes by hand. The dashboard lists who
has gone missing on every sync.

---

## Provider status

| Provider | `verified` | Endpoint used | Credential |
|---|---|---|---|
| Export link (`csv_url`) | **yes** | the URL you paste | optional bearer token |
| TeamSnap | **no** | `GET https://api.teamsnap.com/v3/members/search?team_id=…` (Collection+JSON) | personal access token |
| SportsEngine | **no** | `GET https://api.sportngin.com/v3/teams/{id}/members` | API token |

"Not verified" means the adapter was written against the platform's published
API and has never been run against a live account. The flag is shown in the
API response and in the coach UI, and tests check that it stays that way until
someone changes it on purpose.

What is most likely to break on first contact:

- **Field names.** The mappings (`_teamsnap`, `_sportsengine` in
  `roster_sync.py`) are the guess. TeamSnap may return `birthday` in a
  different format or keep guardian contacts on separate
  `contact_email_addresses` records instead of on the member.
- **Non-players.** TeamSnap's member search includes coaches and managers. The
  adapter does not filter on `is_non_player` yet, so staff may show up in the
  preview as athletes.
- **Pagination.** Neither adapter follows a next-page link. That is fine for a
  35-player team and wrong for a whole club in one call.
- **Token expiry.** Neither adapter refreshes OAuth tokens. An expired token
  shows as "That token was refused" on the link, and the coach pastes a new one.

### Verifying a hosted adapter

Do this once per provider, against a real account, **before** a coach relies
on it:

1. Link the team in a **staging org**, never the live program.
2. Read the dry-run preview against the real roster. Check the name count,
   that no coaches or parents appear as athletes, that jerseys and positions
   are in the right columns, and that birth years look right.
3. Save the raw API response (redact names and emails) as a fixture under
   `tests/fixtures/roster_sync/` and add a test that parses it.
4. Fix any field mapping, re-run, apply, then run a second sync. It should
   report 0 created and 0 updated.
5. Only then set `verified=True` on the provider in `roster_sync.PROVIDERS`,
   in the same commit as the fixture test.

### Export-link recipes (the proven path)

Most platforms can publish a CSV even when their API is closed or paywalled:

- **Google Sheets:** File → Share → Publish to web → the sheet → CSV. Paste
  that URL. No token.
- **TeamSnap:** Roster → Export gives a download, not a stable URL. Upload the
  file instead, or keep a published Google Sheet as the club's master roster.
- **LeagueApps / Stack Sports / Sports Connect:** use the scheduled report or
  export URL if the club's plan has one. Otherwise upload.

---

## Operations

- **Schedule:** `30 */6 * * *` in `infra/crontab.offdays`. Log:
  `~/offdays-logs/roster_sync.log`. Exit code 1 only when every due link
  failed (a network or DNS problem rather than one expired token).
- **Run one by hand:**
  `podman exec offdays_app_1 python scripts/run_roster_sync.py --older-than-hours 0`
- **See a link's last result:** `GET /api/coach/roster/links` (coach token).
  `last_result` carries the counts, departures, warnings and any error.

## Known gaps (tracked)

1. TeamSnap and SportsEngine are unverified (above).
2. No pagination and no OAuth refresh in the hosted adapters.
3. Departures are reported, not applied. Deactivating an athlete is manual.
4. `.xlsx` is not read directly.
