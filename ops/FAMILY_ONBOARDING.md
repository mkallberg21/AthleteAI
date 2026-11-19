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

**How the director meets these steps (the setup flow).** A new director is walked through them one
question per screen, with a step bar and one big Next, and nothing else on the page. In order: how the
program reaches them, badge (optional), season dates, **teams**, **coaches**, **rosters**, **email to
parents** (optional), send the invites. A club with a dozen squads does not make a dozen forms:

- **Teams** takes one name per line (or commas, or a paste from a sheet). Repeats and teams that already
  exist are left out and listed with the reason; at most 60 per paste.
- **Coaches** shows one row per team that has no coach: a name and an email. The same email on two
  teams is one person with one sign-in and no second code; two people who share only a name stay two
  people. A team left blank can wait, so this step can be skipped.
- **Rosters** is the same roster card as always (TeamSnap, SportsEngine, a file, or typing), one team at
  a time, with "n of m teams have players" under it.
- **Email to parents** only shows the hold (see the next section). The flow never releases it for the
  director.

The flow adds no server route. Each team goes through `POST /api/teams` and each coach through
`POST /api/coach/staff`, the routes the one-team form already used, so a team or coach made either way
is identical. The decisions (which names, which coaches, who is the same person) are in
`offdays/web/static/setup_flow.js`, tested by `tests/js/setup_flow.test.mjs` and `tests/test_setup_flow.py`.

**After setup: the Home tab.** The dashboard opens on Home, not on a stack of cards. It is a view over data the program
already holds, and adds nothing that is stored.

- **All teams:** one row per team: its coach, "n of m training", a status (all training, n not training yet, no coach,
  no players yet) and when it last trained. Above the rows, a short list of what needs a person: families not training
  yet, teams with no coach or no players, coaches who have never signed in or have been quiet for two weeks, scanned
  videos waiting for a decision (director only), sessions held for a look. Each line has a button to the place that fixes it.
- **One team:** its players ranked by full name, everyone included. Players with nothing done share one rank at the
  bottom, with the stage their family is at and whose move it is. Its coaches, when each last opened the app, and how
  many videos each added in 30 days.
- **One player:** where the family is, the parent's contact, rank and XP for the window, recent sessions, and
  "Send the invite again" (the same path as the Families card; while the hold is on it hands over a Send email link and
  never says "sent").
- **Coaches** (director): who is coaching what, who has signed in, who is adding videos.

Everything else is still on its tab (Today, Families, Teams, Settings). Rankings and names are staff only; a coach
sees only their own teams and players. Routes: `GET /api/coach/overview`, `/overview/team/{id}`,
`/overview/player/{id}`, `/overview/coaches` (`offdays/overview.py`). Staff sign-ins are now stamped once a day, like
athletes', so "has not signed in" is real. Tests: `tests/test_director_home.py`; walk: `walk-director-home.mjs`.

**An athlete lost access.** The parent can send a new link any time, from their own portal, with no one at the club
involved. It is the first thing under the athlete's name: "Send <first> a new sign-in link" (`POST
/api/guardians/athlete-link/{id}`). It gives a link to text, email, share or copy. Each new link replaces the last
everywhere, so a link that went astray or a lost phone is dealt with in one tap, and it is the same athlete with the
same history. It needs the parent's yes to training first, and only that child's parent can do it (not the athlete, not
a coach). What the athlete sees on a dead link: "This link does not work any more. Ask your parent to send you a new
one." A director can see who has not signed in from the Home tab (Player page) and nudge the parent, but cannot mint an
athlete's link: a child's sign-in is the parent's to hand out.

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

## One athlete in two programs

A club roster creates its own athlete record, so a kid on two clubs' rosters starts as two records, each with
its own history. A parent can **link** them, and from then on a counted session is counted in each program.
Each program keeps its own record, so every dashboard, ranking, streak, badge, season rule and bill works as
before (`offdays/linked.py`, schema 31: `athlete_links`, `sessions.mirrored_from`).

How it goes: the parent is a parent in both programs (same roster email), opens their portal, and under the
athlete sees "Is Ryder in another program too?" with the other athlete named. One tap: "Count it there too".
The athlete's home screen then says "Your work counts for A and B." Either parent can stop it from their portal.

Rules:

- **Only a parent who can prove it.** The same address, supplied by the programs (roster email, or the address
  an invite was emailed to), is on a parent account in both. An address typed at sign-up is never trusted, and a
  matching name alone never links (two Sam Hills exist). The rule is written once (`linked._TRUSTED`).
- **The parent confirms.** The app suggests; nothing links by itself.
- **One athlete per program in a group.** Two brothers on one club never merge.
- **Only counted work, once, from now on.** Same reps and XP. A session held for review is copied only when a
  coach approves it. A copy is never copied again. Work done before the link is not copied.
- **Each program's own rules decide.** No copy where that program's season has ended (its last day still
  counts), the athlete has left it, or its parent has not said yes or has withdrawn. The source session is never
  affected, and a failure in a linked program never breaks the athlete's own submit.
- **Nothing else crosses.** Not check-ins, film watched or messages. A director never sees the other program's
  name or athlete; they see a normal session on their own athlete.
- **Stopping keeps what was counted** (that work was done) and ends future copies.
- **Billing is unchanged**: each program pays for its own roster.

Limits: the two parents must share an address the programs hold. A family where mom is on one roster and dad on
the other has no shared address, so no offer appears; fix the roster email and it will. Deleting an account in one
program does not delete the athlete's data in the other; the parent deletes each. The privacy policy should say
that linked programs each hold their own copy of the athlete's counted sessions (for the lawyer).

## The parent email is a message from 0FFDAYS on behalf of the coach or director

Every invite (roster import, the Families screen's send and resend, one at a time or many) goes out from the program's
own mail address as a message for a person, not an anonymous notice:

- **From line:** `"Matt Kallberg (Nashville Dogs) via 0FFDAYS" <no-reply@mail.0ffdays.com>`. The name is the person who
  pressed send (director or coach); the address stays on the verified mail domain. Stored per message in
  `email_outbox.from_name` / `reply_to` (schema 32) and applied in `mailer._headers`.
- **Replies** go to that person's own address, so a parent can just reply, in whatever email platform they use. The
  address is used only once its owner has CONFIRMED it (`offdays/sender_email.py`, table `sender_emails`, schema 33): in
  the message box they enter it, 0FFDAYS emails that address a link (`?sender=`, one use, 24 hours, stored as a hash, at
  most 5 an hour), and clicking it confirms it. An address confirmed for email sign-in counts too. An unconfirmed
  address is never a reply address, so a typo cannot send a parent's reply to a stranger; a changed address starts
  unconfirmed. Until then the email's footer says replies are not read. 0FFDAYS never reads their inbox or sends from
  their account (a message "from" a Gmail or Outlook address would be rejected by the receiving server, which is why
  it is sent from our own domain with their name).
- **While email is on hold, sending from your own email** no longer assumes the computer's default mail app. A click on
  any "Send email" link asks once which service the person uses (Gmail, Outlook.com or Hotmail, Outlook for work or
  school, Yahoo Mail, or the mail app on the computer), opens a ready-written message there, and remembers the choice
  (`MAIL_PREF` in the browser, changeable under the message box). A true send-from-their-own-account integration (Gmail
  or Microsoft OAuth) is not built: it needs a registered app with each provider, and Google reviews apps that send mail.
- **A note of their own** (up to 1500 characters, plain text, escaped) goes at the top of every parent's email, above the
  personal link. The Families screen's "Message to parents" box holds it; it is remembered in the browser.
- **Preview and test:** `POST /api/coach/families/invite-preview` shows exactly what a parent gets and who it is from;
  `POST /api/coach/families/invite-test` sends the same message to the sender's own address only (allowed while the hold
  is on, because it reaches nobody else; the link in it is a placeholder).
- **Sent right away:** the request queues the mail and hands it to the provider straight after responding
  (`_send_now`, a background task). The hourly job stays as the retry net.
- **Unchanged:** the program's email hold. While it is on, nothing is sent to anyone and the director still gets each
  message to send from their own mail, now including their note. Sender names and reply addresses are cleaned so they
  cannot break a header.

## Links in emails are hyperlinks

Every email that tells someone to open a link (parent invite, coach sign-in, confirm and reset, parent back in, sender
confirm) carries it three ways: the plain-text part has the address on a line of its own (never mid-sentence, where mail
programs most often leave it as text); the HTML part has the button; and under the button the address is written out as
a hyperlink (`mailer.link_fallback_html`), for mail programs that strip button styling. `tests/test_email_links.py`
parses every kind and fails if any address in the text is not a hyperlink in the HTML.

Where the message is not sent by 0FFDAYS, a link cannot be formatted: a `mailto:` body is plain text by definition. So:
- the director's dashboard preview shows the real HTML email (a sandboxed frame), and "Copy message" puts BOTH html and
  text on the clipboard, so pasting into Gmail or Outlook keeps the link a link (the invite responses carry `html`);
- a parent's email to their athlete (the Email button in the portal) puts the sign-in link on a line of its own;
  a text message keeps one line.

## What the first email to a parent says

Above the link, in this order: why the program uses the app (practice is a few hours a week, most improvement happens
between practices, and the coach can see who is putting in the effort); what the athlete gets out of it, physically
(skill reps plus strength, conditioning and coordination work, short sessions sized for age, rest suggested after a heavy
stretch) and mentally (a habit of showing up, confidence from visible progress through streaks and badges, a soreness
check-in the plan responds to); and that it works on a phone or a tablet (any with a camera and a web browser, nothing
to download). Single child and family versions share `invites._reasons`.

Every claim is something the app does, and `tests/test_invite_content.py` checks that the things it names exist (the
Push-Ups, Plank Hold and Jump Rope drills, streaks and badges, the check-in route, the age-sized weekly plan, a browser
app on the device camera). No health outcome is promised, no child's gender is assumed, no dashes, American spelling.
Edit the wording there, not in a template elsewhere; the preview and the email that goes out are the same text.

## A parent with several children on the team

One parent, one email, one account, however many children. The roster gives the same parent address for each of a
family's children, and the program supplying it is what ties them together.

- **One invite per family.** The import issues one invite per parent address once the whole file is in, not one per
  child. The email names every child ("set up Dillon and Killian on 0FFDAYS") and says one account covers them all.
  Redeeming it creates a single parent account linked to every child on the roster under that address
  (`guardians.family_athletes`, `redeem_invite`).
- **A link for each child.** The first-visit walkthrough has a yes step and a link step per child, and the portal keeps
  a "Send <name> a new sign-in link" button on each. Each child needs their own yes before a link is issued, and a new
  link for one child never ends another's.
- **A child added later joins the parent already signed up** (`guardians.attach_known_parents`), with no second invite.
  The parent gets a "<name> was added to your account" notice, and the walkthrough opens again for that child only.
- **The director's resend** (one or many at once) covers the family with one email; the siblings in a batch are
  reported as "the same parent: one invite covers both".
- **Only what the program gave counts.** Children are found by the ROSTER address, in this program only. The address
  typed at sign-up is never used, so a typo cannot hand a parent someone else's child.

Limits: two parents with different addresses on the same children (mom and dad each listed under their own email) are
two accounts, each invited by the address the import chose, and the other parent can be added from the director's
Families screen or with the "Add another athlete" code box. Children of one parent who are on different programs are
separate accounts; use the linked-programs feature for one athlete in two programs.

## When the camera cannot count a drill ("Tell us what you did")

Any athlete can log work the camera missed: a standing button above the drill list, and a prompt on the "That one
didn't count" screen with that drill preselected. They pick what they did, how many minutes (1 to 240) and an optional
note. No coach switch is needed (`POST /api/sessions/self-reported`, `store.log_self_reported`).

What keeps it honest is what it may do:

- Marked `self_reported` for ever, and shown as "logged by athlete" to the parent (drill list) and the director
  (player page).
- Counts for turning up: the streak, participation and the squad goal. Never for a rank: the staff ranking, XP boards,
  team totals, the roster's window XP and level read only measured XP (`leaderboard._NOT_LOGGED`), and the reps board
  already excluded it.
- Only the first one of a day earns XP, a flat amount that ignores the minutes and reps typed. At most
  `MAX_LOGGED_PER_DAY` (4) are accepted a day, so typing more earns nothing more.
- In a linked program it counts there too, still marked as logged.

The old "self_report" accommodation no longer gates this; it is harmless and can be left alone.

## A parent on a new phone (getting back in)

A parent signs up once with an invite code and is then signed in by a code their phone keeps. They have no
password, so a new phone or a cleared browser used to be a dead end: the invite code is spent and the coach's
resend refuses once a parent has signed up.

Now: on the sign-in page, **Parent > Already set up? Get back in**. The parent types their email and is sent a
one-time link (`parent_signin.py`, schema 30 `parent_links`). Opening it signs them in on that phone and signs
out the old one. From there they send their athlete a new link (see above).

Rules:

- **Only an address the program gave us**: the roster email, or the address the invite was emailed to. The address
  a parent typed while signing up does not count, so a typo cannot hand a stranger a child's details.
- **The email hold stays in charge.** Nothing is sent while the program's hold is on. The director releases it
  with "Start sending email", as for every other message to families.
- **The reply never says who is a parent**: same words for a known, unknown, held, suppressed or malformed address.
- One link at a time, works once, lasts an hour; three an hour per parent; guessing is throttled; only a hash is kept.
- It opens a parent account and nothing else (never a coach, director or athlete).
- If nothing arrives, the reply tells the parent to ask their director to check the address on the roster.

