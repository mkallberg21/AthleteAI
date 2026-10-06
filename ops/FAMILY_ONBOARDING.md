# Family onboarding: roster to first session

How a new program gets from "here is our roster" to a child recording a
drill, with the parent in the loop, and with the coach doing nothing after
the upload.

Code: `offdays/invites.py` (the email), `guardians.create_invite` /
`guardians.athlete_signin_code`, `Store.apply_import` in `offdays/store.py`,
routes `/api/coach/roster/import`, `/api/coach/guardian-invites`,
`/api/guardians/redeem`, `/api/guardians/consent`,
`/api/guardians/athlete-code/{athlete_id}`. Pages: `index.html` (sign-up),
`parent.html` (consent + sign-in code), `coach.html` (import + slips).
Tests: `tests/test_family_onboarding.py`.

---

## The chain

```
coach uploads roster CSV (with a Parent Email column)
        │
        ▼
import creates athletes + one guardian invite per parent email
        │  invite email queued (transactional, deduped per invite)
        │  hourly job sends it; coach's "Invites" list shows queued / sent / failed
        ▼
parent taps the link  →  /app/index.html?invite=CODE
        │  code pre-filled; parent types their name; "Create parent account"
        ▼
parent portal: "Decide whether Jordan can train"  →  tick participation
        │  (the consent gate switches on the moment a parent is linked)
        ▼
"Get Jordan's sign-in code"  →  shown once; parent hands the phone over
        │
        ▼
child enters it under "Your athlete code"  →  capture.html  →  first session
```

Each arrow is a real join and each was previously broken: the invite was
stored but never sent; the sign-up buttons had no handlers after the
re-skin; the athlete's claim code was only on the coach's printed slip.

## What the coach does

1. **Roster card → upload CSV.** Include a `Parent Email` column (see
   `ops/ROSTER_SYNC.md` for every header the parser accepts). Preview, then
   import.
2. Read the slips card note: "*N of M parent invites were emailed*". Print
   the slips **only** for families without an address on the roster, and the
   athlete claim codes as the fallback for a parent who never opens the email.
3. Nothing else. The dashboard's "N athletes waiting on a parent" blocker
   names who has not yet said yes.

A single parent can also be invited from the roster row (**Invite**). With
an email it is sent; without one the code is shown to read out.

## What the parent does

1. Opens the email, taps the button (or enters the code on the sign-up page).
2. Types their name, taps **Create parent account**. They land in the parent
   portal.
3. Ticks **Training in the app**. Until this is on, the child's app says
   "Waiting on a parent" and the sign-in button below refuses with
   "Say yes to training first".
4. Taps **Get Jordan's sign-in code**, hands the phone to the child.

## What the child does

Opens `app.0ffdays.com`, enters the code under "Your athlete code", records
one drill. That is the step that proves the whole chain.

## Rules the code enforces

| Rule | Where |
|---|---|
| Invite email is transactional: a parent who unsubscribed from digests still gets it | `invites.deliver`, `mailer.Kind.TRANSACTIONAL` |
| One email per invite, never twice: dedupe key `guardian_invite:{id}` | `invites.deliver` |
| No address on the roster → nothing queued, `emailed: false`, printed slip | `invites.deliver` |
| Invite codes are single-use, 14 days, stored hashed, throttled on redeem | `guardians.redeem_invite`, `throttle` |
| Sign-in code refused until participation consent is granted | `guardians.athlete_signin_code` |
| Every sign-in code request rotates: the old code and the printed claim code die | `guardians.athlete_signin_code` |
| A guardian can only mint a code for a child they are linked to | `require_guardianship` |
| Staff and athletes cannot call the parent code route (403) | `_guardian` dependency |

## Email delivery

The email is composed and queued by the import. It is **sent** by the hourly
`scripts/run_notifications.py` job (`mailer.flush`), through SMTP when
`OFFDAYS_SMTP_*` is set (Resend, per `ops/DECISIONS.md`) and otherwise logged
by the console transport. `GET /api/coach/guardian-invites` returns
`smtp_configured` and an `email_status` per invite (`none` / `queued` /
`sent` / `failed` / `suppressed`), so "did the parent get it?" has an answer.

**Until SMTP is configured in production (checklist §7), nothing reaches a
parent's inbox.** The import still says `emailed: 1`, meaning queued. The
printed slips remain the real path for the pilot until that box is ticked.

The email copy (`invites.compose`) leads with the privacy promise -- video
never leaves the phone -- names the coach and the program, carries the link,
the code as a fallback, and the parent's rights (withdraw, export, delete).

## Known gaps

1. **Verification.** Whoever opens the email is the parent. That is Option B
   in `ops/GUARDIAN_VERIFICATION.md` by construction (possession of the roster
   inbox), but a bare code typed on the sign-up page is still accepted with
   no email check. The verified/unverified split in that doc is not built.
2. **Re-send.** A coach cannot re-send an invite from the dashboard; the
   workaround is **Invite** on the roster row, which mints a new code and
   emails it. The old one stays valid until it expires or is revoked.
3. **Two parents.** One invite per roster row. A second parent joins via the
   first parent's code (`/api/guardians/link`) or a second coach invite.
4. **Mail flush cadence.** Hourly. A parent who signs up in the car park
   waits up to an hour for the email. Flush more often if that bites.
