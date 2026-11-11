# Family onboarding: roster to first session

## The director's kickoff (the order it happens)

1. **Sign up** on the public page: program name, sport, their own name. The
   director code is shown once and is their standing sign-in.
2. **Teams** -- one per squad, from the dashboard.
3. **Coaches** -- `POST /api/coach/staff` (Coaches card, "Add a coach"): name,
   email, teams. Each coach is emailed a standing sign-in link
   (`invites.compose_staff`). No email = the code is shown once to read out.
4. **Roster with a Parent Email column** -- import into a team. Every parent
   is emailed an invite on import (`invite_guardians` defaults on).

**No SMTP on the server (the pilot's starting state):** nothing is queued and
nothing claims to be sent (`invites.deliver` returns False). Every invite --
roster import, single invite, Nudge, new coach -- comes back with `link`,
`subject` and `text`, and the dashboard shows a "Send these from your own
email" block: one `mailto:` per parent with to/subject/body filled in, a Copy
per message, and Copy all. The director sends from his own account. Turning
on Resend (`scripts/setup_resend.py`) makes the same invites go out on their
own with no other change.

From here the system runs it: parents sign up and say yes, send the kid the
link, the kid trains. The Families card shows every family's stage and a
Nudge for parents who have not opened the invite. `onboarding.PROGRAM_STEPS`
is this list, in this order.

How a new program gets from "here is our roster" to a child recording a
drill, with the parent in the loop, and with the coach doing nothing after
the upload.

Code: `offdays/invites.py` (the email), `guardians.create_invite` /
`guardians.athlete_signin_link`, `Store.apply_import` in `offdays/store.py`,
routes `/api/coach/roster/import`, `/api/coach/guardian-invites`,
`/api/guardians/redeem`, `/api/guardians/consent`,
`/api/guardians/athlete-link/{athlete_id}`. Pages: `index.html` (sign-up),
`parent.html` (consent + sign-in link), `coach.html` (import + slips).
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
"Send Jordan their sign-in link"  →  Copy / Share / Text / Email
        │  /app/index.html?code=CODE -- the athlete's standing sign-in code,
        │  reusable on any phone all season, until a parent issues a new one
        ▼
child taps it on their own phone  →  signed in  →  home screen (drills, film, badges)
```

Each arrow is a real join and each was previously broken: the invite was
stored but never sent; the sign-up buttons had no handlers after the
re-skin; the athlete's claim code was only on the coach's printed slip, and a parent on a tablet had nothing to forward to a phone.

## What the coach does

1. **Roster card → upload CSV.** Include a `Parent Email` column (see
   `ops/ROSTER_SYNC.md` for every header the parser accepts). Preview, then
   import. **No file?** Choose **Type it in** instead: one block per player
   (a line per player on a laptop), or paste rows copied from a spreadsheet,
   an email or notes. It builds the same CSV in the browser
   (`offdays/web/static/roster_entry.js`) and sends it to the same preview and
   the same import, so everything below is identical: the parent is invited
   first, no code is made for the child, the program's email hold still
   applies, and a name typed twice is skipped with the reason. Works the same
   in every sport.
2. Read the slips card note: "*N of M parent invites were emailed*". Print
   the slips **only** for families without an address on the roster, and the
   athlete claim codes as the fallback for a parent who never opens the email.
3. Nothing else. The dashboard's "N athletes waiting on a parent" blocker
   names who has not yet said yes.

**Many at once.** On the Families card, tick the families (or **Select everyone**) and press the button above the list.
`POST /api/coach/families/nudge-many` runs the same `_nudge_one` as the single **Resend invite to parent** for each
athlete, so every rule is identical: a parent already signed up, no address on file, another program's athlete, or a
team a coach does not have are each skipped *with the reason* and never stop the others; one live invite per athlete; one
invite per athlete however often the id repeats; at most 200 per tap. While the email hold is on nothing is emailed:
each family is "ready" and the page offers its own **Send email** link plus **Copy all N messages**. Changing the filter
clears the ticks, so nothing out of sight is ever sent. With email on, the director confirms first.

A single parent can also be invited from the roster row (**Invite**). With
an email it is sent; without one the code is shown to read out.

## What the parent does

1. Opens the email, taps the button (or enters the code on the sign-up page).
2. Types their name, taps **Create parent account**. They land in the parent
   portal.
3. Ticks **Training in the app**. Until this is on, the child's app says
   "Waiting on a parent" and the sign-in button below refuses with
   "Say yes to training first".
4. Taps **Send Jordan their sign-in link** and texts, emails, shares or
   copies it to the child's phone. Most kids have their own device and most
   parents do this from a tablet, so the deliverable is a link, not a code
   to read across the room. The code is shown too for a phone with no link
   handling. One yes, one link, the whole season; the parent only comes
   back here to turn a stray link off by issuing a new one.

## What the child does

Taps the link. The sign-in page sees `?code=` and signs in with no typing,
landing on their home screen: the drill list to choose from, film the coach
has curated, their badges and the next ones to earn, the wellness check-in. Picks a drill,
records it. That is the step that proves the whole chain.

The link is not single-use and does not expire. The parent says yes once;
the kid is in for the season on whatever phone opens the link -- a new
phone, a cleared browser, a tablet at a grandparent's. Access ends when a
parent issues a new link (old one off everywhere), withdraws training
(signed in, but the app says "waiting on a parent" and will not record),
the coach deactivates the athlete, or **the season end date passes**
(director sets it on the Season card; the morning after, athlete sign-in
says "the season has ended" until the next date is set -- parents and staff
are never cut off, and nobody re-registers: the same link works again the
day the next season opens).

## Rules the code enforces

| Rule | Where |
|---|---|
| Invite email is transactional: a parent who unsubscribed from digests still gets it | `invites.deliver`, `mailer.Kind.TRANSACTIONAL` |
| One email per invite, never twice: dedupe key `guardian_invite:{id}` | `invites.deliver` |
| No address on the roster → nothing queued, `emailed: false`, printed slip | `invites.deliver` |
| Invite codes are single-use, 14 days, stored hashed, throttled on redeem | `guardians.redeem_invite`, `throttle` |
| Sign-in link refused until participation consent is granted: the parent registers the child first | `guardians.athlete_signin_link` |
| The link carries the athlete's standing sign-in code: reusable, no expiry | `guardians.athlete_signin_link` |
| Every request issues a new code: the old link, and any printed claim slip, stop working everywhere | `guardians.athlete_signin_link` |
| Withdrawing training pauses recording but does not sign the kid out; the home screen says why | `Store._require_participation_consent`, `onboarding.athlete_blockers` |
| A guardian can only mint a link for a child they are linked to | `require_guardianship` |
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

## What the club is billed

$0.50 per rostered athlete per day of the season, both ends inclusive. The
director sets **start** and **end** on the Season card when setting up the
program, before families sign up; a roster import never touches them. The
end date is the same one that pauses athlete sign-in. A late joiner is billed from the day they were added.

500 athletes, 1 February to 30 June = 150 days = $75 a head = **$37,500**.
The director sees this live under the Season card dates; `GET
/api/org/invoice` is the number. No dates set = no number, just a note.

## The program's parent list

Every parent named on a roster is kept from the import -- name, email,
phone, relationship, which athlete, which team -- whether or not they ever
make an account (`guardian_contacts`; `offdays/contacts.py`). Phone-only
parents and a second parent's columns (`Parent 2 Name/Email/Phone`) count.
When a parent redeems an invite the account joins its roster row by email;
a parent the roster never named is added then, and the sign-up form takes a
mobile number.

Director sees a **Parents** card with counts and a **Download CSV**
(`GET /api/org/parents?format=csv`). Coaches do not get it.

**Sponsor use is the parent's call.** The portal has a fifth switch, "Let
the program's sponsors and partners contact you", off by default. The CSV
carries it as `marketing` = yes / no / not asked. Running the program and
reaching a family about their own athlete never needs it; a sponsor message
does, and a text to a parent who did not switch it on is a TCPA problem
with statutory damages per message, so the director filters on it first.
Erasing an athlete ("delete the whole account") removes their contact rows.

## Known gaps

1. **Verification.** Whoever opens the email is the parent. That is Option B
   in `ops/GUARDIAN_VERIFICATION.md` by construction (possession of the roster
   inbox), but a bare code typed on the sign-up page is still accepted with
   no email check. The verified/unverified split in that doc is not built.
2. **Re-send.** Built: the **Families** card on the dashboard shows every
   athlete's stage (`GET /api/coach/families`, `offdays/funnel.py`: no parent
   on file -> not invited -> invited -> signed up, consent pending -> link
   not sent -> link sent -> signed in -> training) and whose move it is.
   **Nudge** (`POST /api/coach/families/nudge`) revokes any open invite and
   emails a fresh one to the roster's parent address; refused once a parent
   is linked, because from there the move is theirs. `users.link_sent_at`
   and `users.last_seen_at` (athletes only) are the two stamps that were
   missing for the last three stages.
3. **Two parents.** One invite per roster row. A second parent joins via the
   first parent's code (`/api/guardians/link`) or a second coach invite.
4. **Mail flush cadence.** Hourly. A parent who signs up in the car park
   waits up to an hour for the email. Flush more often if that bites.

## Coach and director sign-in with an email and password

A coach or director can choose an email and password (Settings, "Sign in with a
password") and sign in with those. The six-character code keeps working as a
backup, and parents and athletes are untouched.

### Forgot your password: it runs by itself

With outbound email connected (`scripts/setup_resend.py`), nobody at 0FFDAYS reads a
mailbox or sends anything:

1. When someone sets a password, we email **that address** a confirm link. Opening it
   confirms the address. (No recovery code is handed out when the mail went.)
2. **Forgot your password?** on the sign-in page asks for their email and sends a
   one-time link. It works once, for about an hour. They choose a new password and are
   signed in. Every other open session ends, and a "your password was changed" notice
   goes to the same address.
3. The reply to "email me a link" is identical for every address, so it cannot be used
   to find out who has an account.

The message comes from `no-reply@mail.0ffdays.com`, which nobody logs into; staff keep
using their own Gmail or club address as the recipient. There is no Reply-To, and every
message says the mailbox is not monitored.

**A reset link is only ever sent to a confirmed address.** Otherwise a typo when setting
a password would hand the account to whoever owns the typo. This mail is sent at once and
only to the person asking, and it does **not** depend on the parents' email hold: the hold
exists so a mail provider cannot start emailing families, and this mail goes to one staff
member who asked for it.

Limits: three links of one kind an hour per person; guessing is throttled per source
address; a changed address kills every link sent to the old one; asking again kills the
earlier link; a weak password does not spend the link.

### When email cannot help (still built, in this order)

1. **A reset code from the director**: Teams, Coaches, "Forgot password? Give a reset
   code". One time, 24 hours, read out to the coach. This is also the answer for a coach
   who typed their address wrong or never confirmed it.
2. **The recovery code**, shown once only when email is NOT connected (or the mail did
   not go). "I have a recovery code" on the forgot card takes it.
3. **The operator**, on the server:
   `podman exec -it offdays_app_1 python scripts/reset_password.py someone@example.com`
   prints a one-time reset code. Read it to the person once you are sure it is them.
   This is the one case left for a human: a director who has lost every door.

### Deliverability

The sender domain is new. If a message lands in spam, mark it "Not spam" and the next ones
follow. The page tells people to check spam. Watch `GET /api/coach/outbox` for `failed` or
`suppressed` rows: a hard bounce retires the address.

Passwords are scrypt hashes; recovery codes, reset codes, emailed links and sessions are
stored as SHA-256 digests; none of it is in a program export. Wrong guesses are slowed per
address and per email. A reset or a password change ends every open session.
