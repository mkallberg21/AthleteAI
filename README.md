# AthleteIQ

**On-device training analysis for youth athletes.**

Athletes record their own training with a phone camera. Pose analysis runs **in
the browser on the athlete's device** — the video never leaves the phone. Only
derived counts (reps, which hand, timing, confidence) are uploaded, scored into
XP, and rolled up for coaches and leaderboards.

Built for youth lacrosse first — the flagship drill counts wall-ball
throw/catch cycles and attributes each one to the hand on top of the stick —
but the drill system is sport-agnostic and ships with general strength, speed,
agility, and conditioning exercises.

Coaches assign work and see who did it. Athletes get nudged when a streak is on
the line. Every session is scored for **form quality**, not just rep count, and
**training load is monitored** so the gamification cannot quietly push an
athlete into an overuse injury. Parents get their own portal, where consent is
granular and revocable and their child's data can be exported or erased. The
whole capture flow works with no signal, because youth athletes train in
driveways.

---

## Why on-device

The product requirement was "coaches shouldn't watch the videos, just get the
data." Running the analysis on the phone is the only version of that which is
structurally true rather than a policy promise:

- **There is no endpoint that accepts video.** A test asserts this against the
  generated OpenAPI schema, and a second asserts no database column stores
  imagery. If someone later adds an upload path, the suite fails.
- **No storage or GPU bill** that scales with usage. Inference is the athlete's
  device.
- **No footage of minors** in anyone's S3 bucket, which is the liability that
  ends youth-sports products.

The tradeoff is real and worth stating: with no footage retained, a disputed
count cannot be settled by watching the clip. That is why the integrity layer
and the coach review queue exist — see below.

---

## Running it

```bash
pip install -r requirements.txt

# Seed a demo program (2 teams, 8 athletes, 6 weeks of history)
python scripts/seed_demo.py --db data/demo.db

# Serve
ATHLETEIQ_DB_PATH=data/demo.db uvicorn athleteiq.api:app --reload
```

Open <http://127.0.0.1:8000/> and sign in with a token the seeder printed.
Coaches land on the dashboard, athletes on the capture screen.

> **Camera access requires HTTPS** on anything other than `localhost`. Browsers
> refuse `getUserMedia` on plain HTTP, so a phone on your LAN needs a TLS
> terminator in front (Caddy, ngrok, or `mkcert` + any TLS proxy all work).

### Tests

```bash
python -m pytest tests/ -q          # 836 tests

DRILL_SPECS="$(python -c 'import json;from athleteiq.drills import ALL_DRILLS;print(json.dumps([d.to_dict() for d in ALL_DRILLS]))')" \
  node --test tests/js/counter.test.mjs tests/js/calibration.test.mjs   # 21 tests
```

The JS tests drive the counter with synthetic pose streams built from known rep
counts — that is how the detector is verified without a camera and a stick.

---

## Architecture

```
athleteiq/
  config.py         Scoring curves, integrity limits, retention, VAPID keys
  db.py             SQLite schema; tokens stored hashed, never in the clear
  drills/
    base.py         DrillSpec: the declarative counting contract
    catalog.py      The 12 shipped drills
  integrity.py      Server-side plausibility scoring of submitted sessions
  scoring.py        XP, levels, streaks, badges
  quality.py        Form scoring: consistency, range, tempo, fatigue, off-hand
  load.py           Workload ratio, throwing volume, rest days, advisories
  guardians.py      Parent accounts, invites, consent, export and erasure
  roster.py         Bulk import: header detection, parsing, claim codes
  digest.py         Weekly team KPIs and the coach email
  billing.py        Plans, seats, entitlements, invoicing seam
  mailer.py         Outbound queue: retries, suppression, unsubscribe
  webhooks.py       Inbound delivery events: verification, bounce handling
  sns.py            SNS certificate verification for SES notifications
  chain.py          X.509 path validation against pinned Amazon roots
  revocation.py     OCSP and CRL checking for signing certificates
  staple.py         Pre-fetched OCSP responses, refreshed off the request path
  assignments.py    Coach prescriptions and derived compliance
  notifications.py  Nudge generation, dedupe, and delivery channels
  leaderboard.py    Windowed boards, team standings, coach roster rollups
  store.py          The only module that speaks SQL
  api.py            FastAPI surface
  web/static/
    counter.js      On-device pose -> reps engine (shared spec with server)
    offline.js      IndexedDB slot pool + submission queue
    sw.js           Service worker: app-shell cache and push delivery
    capture.html    Athlete capture app
    coach.html      Coach dashboard
    parent.html     Guardian portal
    leaderboard.html
scripts/
  seed_demo.py            Demo program with six weeks of history
  run_notifications.py    Scheduled nudge generation and delivery
```

### The drill spec is the load-bearing idea

A drill declares *how to collapse 33 pose landmarks into one number*, and the
thresholds that turn that number into reps. The **same JSON** is consumed twice:
the browser counts with it, and the server re-validates against it. They cannot
drift apart.

Adding an exercise is a data change in `drills/catalog.py` — no counter code, no
client change, no migration:

```python
LUNGE = DrillSpec(
    key="gen_lunge", name="Walking Lunges", sport="general",
    category=Category.STRENGTH, metric=Metric.REPS,
    description="Knee angle cycles from standing through a deep lunge.",
    signal=SignalSpec(kind=SignalKind.JOINT_ANGLE,
                      joints=("left_hip", "left_knee", "left_ankle")),
    counter=CounterSpec(down_threshold=95.0, up_threshold=165.0, min_rep_ms=700),
    setup_hint="Side-on to the phone, full body in frame.",
)
```

Append it to `ALL_DRILLS` and it appears in the athlete's drill picker, counts
on-device, scores, and ranks. `tests/test_drills.py` runs eleven
invariants against every drill in the catalog, so a malformed spec fails the
suite rather than silently miscounting in someone's driveway.

Four signal kinds cover most exercises: `joint_angle` (push-ups, squats),
`relative_height` (jumping jacks, pull-ups, high knees), `body_height` (burpees,
squat jumps), and the bespoke `wall_ball_cycle`.

### How wall ball counting works

A single threshold cannot distinguish a throw from a catch — both move the
stick. So the detector tracks the **top hand on the stick** (the wrist nearer
the head) and measures its height above the shoulder line, normalized by torso
length so it is invariant to how far the athlete stands from the phone.

Through one throw–catch cycle that value dips (receiving) then peaks (cocked to
throw). Whichever wrist is on top *at the peak* is the hand the rep is credited
to — which is exactly the distinction lacrosse coaches care about.

Two safeguards make it usable in a driveway:
- **Hysteresis.** The signal must cross fully down *and* fully back up. Without
  it, a signal hovering at the boundary sprays dozens of phantom reps.
- **A refractory period.** Reps closer together than the drill's physical floor
  are discarded.

Both are covered by tests (`counter.test.mjs`), including a case that parks the
signal on the threshold with noise and asserts zero reps.

---

## Programs, roles, and billing

### Access follows responsibility

Until now any coach in a program could read every athlete in it. At a club with
four hundred children that is not a product gap, it is a safeguarding one.

A coach now sees only the teams they are assigned to — enforced on the roster
*and* on every route that reaches an individual athlete, because scoping a list
while leaving the detail route open is not scoping at all. A JV coach asking for
a varsity athlete by id, assigning them work, broadcasting to their team, or
inviting their parent all return 403. Directors see their whole program, and
only a director can change team assignments, since assigning a team grants
access to those children's data.

One deliberate accommodation: **a coach with no assignments falls back to seeing
the whole program.** Accounts created before team assignment existed have no
assignment rows, and defaulting them to "sees nothing" would lock out every
existing coach on deploy. New deployments should set
`ATHLETEIQ_STRICT_TEAM_SCOPE=1`, which makes an unassigned coach see nothing
instead; until then the dashboard flags any coach in that state. The empty-scope
case is tested explicitly, because "no teams" silently meaning "all teams" is
exactly the bug this feature would otherwise ship with.

### One person, several programs

A school coach who also runs a club side is one human with two jobs, and making
them keep two logins is how a roster ends up half-maintained. Roles live in a
`memberships` table, so the same account can be a coach at one club and a
director at another. The active program comes from an `X-Org-Id` header and
defaults to their home org; asking for a program they do not belong to is a 403,
not a 401 — re-authenticating would not help.

### Billing that never locks a child out

One rule overrides the rest: **an adult's payment problem must never stop a kid
from training.** A lapsed card is a conversation with the club treasurer, not a
reason to end a fourteen-year-old's streak or hide a load warning from the coach
responsible for them.

So enforcement is asymmetric. *Growth* is gated — adding athletes, teams, and
staff stops when a program is past due or over its seats, returning **402** with
the exact number of seats needed. *Everything already running keeps running*:
athletes train, coaches see rosters, parents keep their portal, safety
advisories keep flowing. A program that stops paying stops growing, and someone
calls them. There is a test class holding this.

| Plan | Athletes | Teams | Price |
|---|---|---|---|
| Single Team | 25 | 1 | Free |
| Team | 60 | 3 | $49/mo |
| Program | 200 | 12 | $149/mo |
| Club | 600 | unlimited | $399/mo |

Extra seats are billed per athlete at a rate that falls with plan size, so
upgrading is genuinely cheaper at scale — 250 athletes costs $189 on Program
against $239 on Team, and `recommend()` picks the cheapest plan that actually
fits.

Two onboarding decisions worth naming. **New programs start on a Program
trial**, not the free tier: hitting a paywall on your second team before the
product has shown anyone anything is how an evaluation ends. And **existing
programs are backfilled onto a plan that fits what they already run** — telling
a club with six teams that they are now on a one-team plan is the wrong way to
introduce billing to someone already using the thing.

No payment processor is wired in. `Gateway` is the seam one drops into, and the
default `ManualGateway` records the invoice without charging — which is also
what most youth clubs, paying by invoice or purchase order, actually need.

---

## The weekly coach digest

Coaches will not log into a dashboard, so the dashboard goes to them. But a
digest is a different object from a dashboard: it gets forwarded to assistant
coaches, pasted into team channels, and read aloud in the parking lot. That
changes what belongs in it.

### No athlete is named in it

Not the ones who did nothing, and not the ones who did the most. Naming the
bottom is obviously corrosive; naming the same top three every week is the same
mechanism inverted — it tells everyone else, weekly, that they are not one of
them. Individual detail stays in the dashboard behind a login, where it is a
working tool rather than a broadcast.

The email reports that *three athletes* didn't log a session and links to the
dashboard for the names. A test suite class exists solely to enforce this, because
it is exactly the constraint a later change breaks without anyone noticing until
a coach forwards an email with a twelve-year-old's name next to "didn't train".

### Numbers a team can move together

| KPI | Why it's on the list |
|---|---|
| **Athletes who trained** | The headline. Goes up when the *quiet* kids show up, not when the committed ones do more — the only volume metric here whose marginal contributor is the athlete you actually want to reach |
| Trained 3+ days | Turning up once is a good week; three times is a habit |
| Reps outside practice | Every one happened in a driveway or against a wall |
| Training days logged | Athlete-days across the squad — raw showing up |
| Work on the weak hand | Share of reps on the hand nobody wants to use |
| Average form score | How well, not how much |
| Assigned work completed | Only appears when assignments exist |

Every KPI carries last week's value, the change, and whether it beat the best of
the trailing twelve weeks. "We beat last week" is what makes a team read the
same email eight weeks running, so the digest closes with one concrete target —
*"2 more athletes logging a session takes participation to 100%"* — and the
program-wide edition ranks teams by XP per athlete so squad size doesn't decide
it.

Two details that matter more than they look. A change too small to display is
reported as **"holding steady"**, never "up 0%", which reads as a bug. And a
**record** requires genuinely beating the previous best, not matching it to four
decimal places — a record badge on a flat number devalues every other one on the
page.

### Delivery

Composing a digest and getting it into an inbox are different problems, and the
second is where weekly email quietly stops working. Delivery is a queue, not a
send loop.

**Queue, then send.** A Monday job that mails a hundred coaches inside one SMTP
session loses the whole week when the ninetieth times out. Composition writes
rows; a separate worker drains them and can be re-run. `run_notifications.py`
composes on Mondays and flushes on *every* tick, so a message that hit a
transient failure is retried within the hour rather than at next week's
composition.

**Idempotent queueing.** Every message carries a dedupe key, so a cron that
fires twice on a Monday queues once. This was a real bug in the first version:
the in-app copy deduped by week while the email did not, and a double cron run
sent two.

**Scoped per coach.** A director gets the program-wide numbers; a coach
assigned to JV gets JV's. Folding varsity's participation into a JV coach's
email makes the number they are meant to move meaningless — and hands them data
about children they are not responsible for. This was also wrong initially:
every coach got the program-wide digest regardless of scope.

**Retry the transient, give up on the permanent.** A connection reset gets
another attempt on a 5/20/60/240-minute backoff. A 5xx or a refused recipient
never will succeed, so it fails immediately and the address is added to a
suppression list — retrying a dead mailbox forever damages the sending domain
for every other recipient on it.

**One-click unsubscribe that needs no login.** Someone who wants out is holding
an email, not a login; requiring them to sign in is how a message gets marked as
spam instead. Links are HMAC-signed rather than random, so they need no storage
and another coach's cannot be forged by swapping the user id. `List-Unsubscribe`
and `List-Unsubscribe-Post` headers let a mail client do it in place. Opting out
of the weekly digest does not touch in-app alerts, and transactional mail ignores
the preference entirely.

### Bounce webhooks

Most bounces are asynchronous. The receiving server accepts the message and only
sends a bounce back minutes or hours later, long after the SMTP conversation has
closed — so without a webhook a dead address is retried every Monday forever.

`POST /api/webhooks/email/{provider}` accepts events from SendGrid, Postmark,
Mailgun, and SES.

**Verification comes before parsing.** This endpoint's entire job is taking
instructions from the public internet about which addresses to stop mailing.
Unverified, it is a one-request tool for cutting any coach off from their
digest. Each provider is checked with its own real scheme — SendGrid's ECDSA
P-256 over timestamp + raw body, Mailgun's HMAC over timestamp + token, a
constant-time shared secret for Postmark, and full SNS certificate verification
for SES. The signature is checked before the payload reaches a parser, and a
stale timestamp is refused so a captured request cannot be replayed tomorrow.
**An unset secret disables the provider rather than trusting everything**, and
the rejection says only "unauthorized", because explaining the failure helps the
next attempt succeed.

#### SES and SNS

SES bounces arrive through SNS, which signs each message with a certificate it
tells you where to fetch. That last part is the whole problem, and two mistakes
make the verification worthless:

**Fetching the certificate the message points at.** An attacker hosts their own
certificate, signs their own payload with the matching key, and the signature
verifies perfectly. The URL is therefore matched against the real SNS hostname
pattern (`sns.<region>.amazonaws.com`, plus the China partition) *before*
anything is fetched — a check on the exact host, not a suffix, since
`sns.us-east-1.amazonaws.com.attacker.net` ends with nothing useful. Redirects
are refused outright: a 302 from a genuine AWS host would otherwise walk
straight through the check.

**Trusting any valid AWS signature.** Anyone can create an SNS topic in their
own account and have Amazon sign messages for it entirely legitimately, so a
signature alone establishes only that the sender has an AWS account. The topic
ARN is checked against `ATHLETEIQ_SNS_TOPIC_ARNS`, and an empty allowlist
disables the endpoint rather than accepting everything.

**Trusting the certificate because of how it arrived.** Checking the URL and
fetching over TLS is a real argument, but it is a single point of failure: it
assumes every fetcher in every deployment validates TLS properly, and that no
certificate is ever misissued for an AWS hostname. So the signing certificate is
also verified to **chain to a trusted root**, independently of transport.

Anchors are pinned to Amazon rather than the system store. A host trusts around
150 root CAs; trusting all of them to vouch for an AWS signing certificate would
mean a misissuance by any one is enough. Filtering to Amazon's four roots and the
Starfield roots that cross-sign them takes that from 137 anchors to 6. They are
read from the system trust store at runtime rather than embedded, so nothing goes
stale — `scripts/fetch_amazon_roots.py` builds a pinned bundle for images whose
CA store is minimal.

Path validation is explicit rather than delegated, because the library's built-in
validator is built for *server* certificates and applies policy this use does not
want — hostname matching and a TLS-server-auth EKU requirement would reject a
perfectly good signing certificate for the wrong reason. It verifies every
signature link, every certificate's validity window, path-length constraints, and
that each issuer actually carries `CA=TRUE`. That last check is the classic hole:
without it, any certificate an attacker legitimately owns can sign a forged
intermediate that walks all the way up to a genuine root.

**Accepting a certificate that has been revoked.** The chain is checked against
OCSP, falling back to a CRL, across the *whole path* rather than just the leaf —
a revoked intermediate compromises everything beneath it at once.

Two things make this real rather than decorative. **Every OCSP response is
signature-verified** against the issuer's key, or against a delegated responder
certificate the issuer signed *and* marked with the OCSP-signing EKU. An
unverified response is worse than no check at all, because anyone able to answer
the request can reply "good" for a certificate revoked years ago — and it reads
as protection. The same applies to CRLs: an unsigned list could simply omit the
serial an attacker cares about.

And **soft-fail is named as a limitation, not hidden as a default.** When no
responder can be reached, the check proceeds with a warning logged. That is
defeated by anyone who can block the request, which is exactly why browsers
stopped relying on OCSP. It is the default here because a failed webhook is
retried by the provider and the primary controls — allowlisted topic, pinned
chain — do not depend on this one. Set `ATHLETEIQ_SNS_REVOCATION_STRICT=1` to
refuse anything that cannot be cleared. **A `revoked` answer is always fatal**,
in either mode; that part is never a judgement call.

Answers are cached for an hour, so this is roughly one network round trip per
hour rather than one per webhook — and a revocation is never cached, since
re-deciding it costs nothing that matters.

#### Stapling

In TLS, stapling means the server fetches an OCSP response for its own
certificate and hands it over during the handshake, so the client never asks the
responder itself. An SNS signing certificate arrives as a *file*, not in a
handshake, so there is nothing to staple it into — and Python's `ssl` module
cannot read a stapled response anyway, which is worth knowing before designing
around one.

What *is* available is the same division of labour. `scripts/refresh_staples.py`
fetches responder answers on a schedule, verifies each one, and stores it;
verification then reads the stored answer and makes no network call at all:

```
result: good via staple  (no network call made)
```

That changes what soft-fail costs. Revocation soft-fails because refusing on an
unreachable responder would let a CA outage take down bounce processing. Once
staples are refreshed out of band — with their own retries, on their own
schedule — **`ATHLETEIQ_SNS_REVOCATION_STRICT=1` stops being an availability
risk**, because a missing staple is a condition the refresh job reports and
`/api/coach/staples` shows, rather than a race decided while a webhook waits.

Two properties make it trustworthy. Responses are verified **on the way in**, so
nothing unverifiable can be stored and read back later as an answer — a forged
response is rejected at ingest, never at use. And a staple past its own
`nextUpdate` is **not believed**: it falls through to a live query rather than
pinning a verdict from before whatever went wrong. Staples are also capped by
age, so a responder promising a month of validity cannot hold one answer that
long, and they are refreshed six hours before expiry so a scheduled job gets
several attempts before anything goes stale.

A response can also be handed in directly — `staple.staple_response()` — for a
sidecar that fetches them, or for a provider that starts offering one.

Both signature versions are supported — v1 is SHA1, v2 is SHA256, and AWS still
emits v1 for older topics. Certificates are cached for an hour so a bounce storm
is not one HTTPS round trip per bounce, and `SubscriptionConfirmation` is handled
by visiting the confirm URL — which is host-checked again, being a second
attacker-supplied URL this server would otherwise fetch on command.

Network access is injected rather than imported, so all of this is tested
against a generated keypair without touching the internet.

**A soft bounce is not a dead address.** A full mailbox, a greylisting server,
an over-quota school account: all bounce, all recover. Hard bounces and spam
complaints suppress immediately; soft bounces only suppress after three in a
fortnight. Suppressing on the first one loses real recipients silently, which is
the exact failure the webhook exists to prevent. SendGrid's `blocked` bounce is
mapped to *soft* for the same reason.

**A spam complaint outranks an administrator.** It suppresses the address *and*
turns the preference off, and a director cannot undo it from the dashboard —
someone who reported the mail did not ask to be put back on the list. A plain
bounce, which is usually a typo in a roster import, can be cleared in one click.

Events are deduplicated on the provider's own id, because providers retry and a
soft bounce counted twice pushes a live address off the list. Raw payloads are
retained alongside the normalized event: when a coach says they never got the
digest, the provider's own words are what settles it.

**Every send is recorded.** `/api/coach/outbox` shows what was delivered, what is
waiting, what failed and why, so "did the coach actually get it?" has an answer.
Delivered mail is pruned after 90 days; failures are kept, because a failure is
evidence and a delivered message is just storage.

Without SMTP configured the queue drains through a console transport, the digest
still posts to the in-app feed, and it is still viewable and printable at
`/api/coach/digest/preview` — and the send endpoint says nothing left the
machine rather than claiming a delivery.

---

## Roster import

Nobody hand-creates two hundred athletes, and a coach who has to will not
finish. In practice this kills more pilots than any missing feature, so the
parser is forgiving of the files people actually have rather than demanding one
they would have to build.

**Headers are matched, not dictated.** A TeamSnap export, a school SIS dump, and
a spreadsheet an assistant coach typed will not agree on what the jersey column
is called. `Jersey #`, `No.`, `Number`, `Uniform Number`, and bare `#` all
resolve — that last one matters because it is the most common of the lot and
normalizes to an empty string, so it needs handling that generic fuzzy matching
misses entirely. Same for names: `First`/`Last` columns, a single `Name` column,
and `Pierce, Jordan` in either arrangement all come out as `Jordan Pierce`.

**Nothing happens without a preview.** Every import is planned first and shows
per row what it will create, update, and skip. Applying is a separate call, and
it re-parses the file rather than trusting a plan echoed back by the client — a
plan is a preview, not an instruction.

**Blocking problems are separated from warnings.** A row with no name cannot be
imported. A malformed parent email is no reason to leave a kid off the roster,
so that athlete imports and the warning says the invite was skipped.

**Re-importing an edited file updates rather than duplicates.** Matched on an
external ID when the file carries one, otherwise on a normalized name within the
program. Coaches always upload again after fixing a spelling, and an import that
doubles the roster on the second pass is worse than one that never ran. A file
with fewer columns will not blank out data it does not mention, and a name that
already belongs to two athletes is skipped rather than guessed — guessing could
overwrite the wrong child's record.

**Ages default to minor.** A grade or graduation year gives an estimate, not a
birth year, and both an estimate and a missing age are treated as a minor.
Erring the other way puts a child's full name on a shared leaderboard.

### Claim codes

A bulk import mints hundreds of logins at once, and the existing "token shown
once on screen" flow cannot be handed to two hundred kids. Each imported athlete
instead gets a short claim code — printable, single-use, expiring in 30 days,
stored only as a hash. The coach prints a sheet of slips and hands them out; the
athlete types theirs once and gets a real token. Until it is claimed the account
holds a placeholder token nobody has, so an imported account is not a login
waiting to be guessed.

A parent email column issues guardian invites in the same pass, so importing a
roster also onboards the parents.

---

## Parent accounts

Parents consent, parents pay, and parents decide whether a product that films
their child is allowed in the house.

**A coach issues an invite code** for a specific athlete. The parent redeems it
to create their account — redemption *is* the identity proof, so the code is
treated as a credential: single-use, expiring after 14 days, revocable, and
stored only as a hash. Failure messages are deliberately identical for expired,
revoked, and unknown codes, because distinguishing them would let someone probe
for valid ones.

### Consent that actually means something

`guardian_consent` used to be a boolean a coach ticked. That records that an
adult clicked something — not who agreed, to what, when, or whether they later
changed their mind. It is now an append-only, revocable record, granted by the
guardian themselves, across three separate scopes:

| Scope | Effect when withdrawn |
|---|---|
| Training in the app | The athlete cannot start or reserve sessions |
| Full name on leaderboards | They still compete, under an initial and jersey number |
| Keep detailed rep timings | Rep-by-rep detail is purged immediately; totals remain |

Two things make this real rather than decorative. **Withdrawal takes effect
now** — revoking retention purges the rep detail on the spot, not at the next
scheduled prune, because a consent decision that applies tomorrow is not a
decision. And **participation consent is enforced at the point of capture**, on
both the online and offline paths, so banked offline slots aren't a way around
it.

Enforcement only begins once a guardian is actually linked. Athletes onboarded
before parent accounts existed have no consent rows, and defaulting those to
"denied" would lock out every existing user on deploy.

### Data rights

A guardian can export everything held about their child — profile, sessions, rep
timings, XP, badges, consent history — and can erase it, choosing between
removing the training history and removing the account entirely. Deletion is
real: rows are gone, not flagged. Only the *fact* of the erasure is kept, keyed
by a hash, so a program can show an auditor that a request was honoured without
retaining what it deleted.

### What the parent portal deliberately does not have

**No leaderboard.** Not in the UI and not reachable with a parent's token — the
API returns 403 and says why. A ranked list of other people's children for
adults to scroll is the mechanism behind the worst behaviour in youth sports,
and building one would be a choice, not an accident.

**No integrity or review status.** "Your child's session was held for review"
reads as an accusation, and it is a coach's conversation to have, not a push
notification's.

What a parent *does* see, above the numbers, is wellbeing: if their child has
trained seventeen days without a rest day, that is the first thing on the page.

Parents also get a **weekly digest**, because parents will not log into a
dashboard — so the dashboard goes to them, framed around what their child did
rather than where they rank.

---

## Form quality

Counting reps is the easy half of the pose stream. The counter already computed
each rep's peak, range of motion, and cycle duration and then threw them away;
keeping them is what turns a rep counter into something a coach can't get from a
stopwatch.

Four components, combined into a 0-100 score:

| Component | What it reads | Why it matters |
|---|---|---|
| **Consistency** | Rep-to-rep variability of range | A repeatable movement is the precondition for a coachable one |
| **Range of motion** | How much of the drill's full range each rep covers | Half reps count toward volume; they shouldn't count toward quality |
| **Tempo** | Whether reps land in a controlled band, and how evenly | Rushing builds nothing |
| **Held up** | Whether the last third looks like the first | Form collapsing under fatigue is exactly when to stop |

Three decisions that shape how this behaves:

**Components combine geometrically, not as a weighted average.** A movement with
textbook consistency and half the range is not a good movement, and an
arithmetic mean lets three strong components hide one bad one — a session of 99%
half reps scored 79/100 under that model, and 65 under this one.

**Statistics are robust throughout.** Medians and trimmed spreads, because one
glitched rep from the detector should not tank an honest session.

**Quality never subtracts.** It earns an XP bonus (8% at 70+, 15% at 85+) and
ranks on its own leaderboard, but it never reduces XP. Docking points for poor
form punishes hardest exactly the athlete who most needs to improve, and a
13-year-old who loses XP for a bad rep stops filming.

### The off-hand gap

For lacrosse this is the whole point, so it gets its own treatment: each hand is
scored separately, and the deficit is measured on the **range-of-motion ratio**
between them rather than the composite score gap — the scoring ramps compress a
genuine 20% deficit into about 11 composite points, which is under any threshold
loose enough to also reject noise.

The claim threshold scales with the noise *within* each hand, not the pooled
spread: a real gap pushes the two hands apart, which inflates the pooled figure
and would hide exactly the deficit this exists to find. Measured across repeated
runs, that gives zero false positives below an 8% deficit on a clean session,
reliable detection from 15%, and appropriate silence on a session too jittery to
tell.

In the demo data it reads an athlete's weak hand at 32% less range and says so
in one sentence, rather than reporting four numbers and leaving the coaching to
someone else.

### Calibration

`target_rom` on each drill is **measured, not guessed**. `tests/js/calibration.test.mjs`
drives every drill with a synthetic textbook rep and asserts both that the drill
counts it and that the reported range lands within 15% of the target its spec
claims.

That test exists because it caught a real bug: squat jumps were smoothed so
heavily (α=0.20) that a one-second cycle lost 27% of its amplitude, the signal
never fell back to the arming threshold, and the drill counted **one rep in
twenty-four** — in real use, not just in the harness. Nothing else in the suite
noticed, because every other test drives a drill whose thresholds already worked.

Hold drills score differently: a plank's quality is the share of the session
actually spent inside the body-line tolerance, so sagging costs you.

---

## Load management and overuse protection

Stated plainly, because it is the reason this exists: **everything else in this
codebase rewards volume.** XP scales with reps, leaderboards rank on totals, and
streaks reward training every single day. Those mechanics work — which is the
problem, because what they are good at driving is exactly what causes overuse
injury in young athletes. A product that gamifies youth training volume without
a counterweight is not neutral; it is a risk factor.

Four things are watched:

- **Acute:chronic workload ratio** — this week's load against the trailing
  four-week average. Load is per-drill, not per-rep, so 200 wall balls and 200
  burpees don't read as the same week's work.
- **Throwing volume**, tracked separately. Youth baseball has decades of
  evidence behind pitch counts; lacrosse involves the same repetitive overhead
  motion and essentially nobody counts it.
- **Consecutive days without rest**, against standard youth guidance of at least
  one full day off per week.
- **Monotony** — training the same amount every day with no hard/easy variation.

In the demo data this immediately surfaces the athlete who tops every
leaderboard: Jordan Pierce, first on XP and form, 17 days straight without a
rest day. That is the whole point — the leaderboard was never going to tell you
that.

### The recovery day

The important design piece. A streak that breaks when you rest makes the athlete
with the most to protect the one most pressured to train through fatigue, so a
**recovery day counts toward the streak**:

```
5-day streak → take a recovery day → 6-day streak
```

It has to be earned (three consecutive training days, and the run must still be
live), so it isn't just a button that keeps a streak alive without training. A
notification offers it when load is high. This turns the gamification from a
risk factor into a protective one, without taking XP away from anyone.

### Honesty about the evidence

The acute:chronic ratio is a **useful heuristic, not settled science.** The
rolling-average form used here has been criticised in the literature on
methodological grounds — spurious correlation, arbitrary thresholds, sensitivity
to the chosen windows. It is deliberately used to raise a question with a coach,
never to diagnose anything or to lock an athlete out of training. A test asserts
that no advisory is phrased as a medical claim.

Two things the model deliberately refuses to do:

**It stays quiet when it doesn't know.** No ratio at all until there is enough
history, because comparing a first week against nothing produces alarming
numbers for an athlete who simply just started. The chronic baseline is averaged
over days actually trained rather than the full 28-day window — padding with
pre-history zeros deflated the baseline and made three weeks of perfectly
consistent training score 1.33 and trip an "elevated" warning, a false alarm
that would have fired for every new athlete in weeks three and four.

**It doesn't nag someone already resting.** A rest suggestion only fires while
the training run is still live.

**It only sees what is logged here.** Team practices, games, and other sports
are invisible to it, so a quiet reading is not evidence that an athlete is
fresh. The age-based volume advisory says so explicitly rather than implying the
app knows the athlete's whole week.

---

## Assignments

A coach assigns a drill with any combination of targets — total reps, number of
sessions, and a minimum share of reps on the athlete's weaker hand — over a
date window, to a whole team or to named athletes. The athlete's home screen
leads with the assignment instead of a drill picker, and the coach gets a
compliance table sorted worst-first, because that list exists to say who needs a
text tonight.

**Compliance is derived, never stored.** A session counts toward an assignment
if it matches the drill and falls inside the window, so a session rejected by
the integrity checks stops counting and one later approved in review starts
counting, with nothing to recompute. Storing progress would mean two sources of
truth that drift.

The off-hand target is the interesting one in practice: in the demo data, an
athlete with 1,449 reps still fails the assignment at 15% off-hand while a
teammate with fewer reps passes at 42%. That is the entire point — it makes the
hard work the binding constraint instead of volume.

---

## Notifications

Every streak mechanic is really a notification mechanic. The app knew when a
streak was about to lapse and never told anyone, which made the streak
decorative.

Generation is separate from delivery. Rules produce notification rows; channels
ship them. **The in-app feed therefore works with no third-party service
configured at all** — Web Push is additive, not required.

Every rule carries a dedupe key, so the scheduler can run as often as you like:

```bash
0 * * * *  cd /srv/athleteiq && python scripts/run_notifications.py
```

Rules that fire today: streak at risk (only for streaks of 3+, since warning
someone about a one-day streak is noise and noise costs you push permission),
assignment due in two days and again on the due date, badge unlocked, week-long
inactivity, and coach broadcasts to a team.

To enable phone-level push, set `ATHLETEIQ_VAPID_PUBLIC_KEY`,
`ATHLETEIQ_VAPID_PRIVATE_KEY`, and `ATHLETEIQ_VAPID_EMAIL`, and install
`pywebpush`. Without them the generator still runs and the feed still fills.

---

## Offline capture

Athletes train in driveways and on fields with one bar. Previously, starting a
session needed a server round-trip, so a dead zone cost the whole session — and
a lost session breaks a streak, and a broken streak loses the athlete. This is a
correctness requirement, not a convenience.

Three pieces make it work:

**Pre-reserved session slots.** `POST /api/sessions/reserve` hands out session
IDs and nonces ahead of time, banked in IndexedDB. The client tops up whenever
it has signal — on app load for assigned drills, and whenever a drill screen is
opened — and spends one when it doesn't. A drill you have opened once online
works offline from then on.

**A durable submission queue.** A finished session is written to IndexedDB
*before* any network call, so it survives a dropped connection, a closed tab, or
a dead battery. It flushes on reconnect.

**Idempotent submit.** Resubmitting with the correct nonce replays the original
result instead of erroring or scoring twice, which is what makes retrying safe.
A wrong nonce is still refused, so idempotency never becomes a way to read back
someone else's session. A 4xx marks the payload permanently rejected and drops
it from the queue rather than retrying forever.

**Day attribution.** The device reports its own completion time, and that
decides which day the session is credited to — a session trained Sunday in a
dead zone and synced Monday earns Sunday's credit. The value is clamped: more
than five minutes in the future or more than 14 days in the past falls back to
today, so a device clock cannot be used to dodge the daily XP cap.

The app is a PWA — installable, with the shell cached by a service worker. API
responses are deliberately never cached: a stale leaderboard or stale assignment
progress read as current is worse than an absent one.

---

## Integrity: the client is untrusted

Counting happens on a device the athlete controls. Anyone willing to open
developer tools can post any number they like, and on a leaderboard that matters.
Every submission is therefore treated as a *claim* and re-scored server-side:

| Check | Catches |
|---|---|
| Rep rate vs the drill's physical ceiling | "500 wall balls in 30 seconds" |
| Cadence variance (too even) | Generated payloads — humans are never metronomic |
| Cadence variance (too erratic) | Detector firing on background motion |
| Timestamps past session end / negative | Hand-edited payloads |
| Single-use nonce per session | Replaying a captured submission |
| Mean pose confidence | Athlete half out of frame; counts unreliable |
| Session duration envelope | Forgotten timers, accidental taps |

Scores land in one of three buckets: **counted**, **held for review**, or
**rejected**. Held sessions go to a coach queue *with the reason attached* —
approving credits the withheld XP.

This is deliberately not a fraud oracle. Falsely accusing a 14-year-old who
actually did the work is far more damaging than a few inflated reps reaching a
leaderboard, so borderline sessions go to a human rather than being thrown away.
The confidence curve is tuned the same way: a marginally-framed session (0.45)
still counts, and only a genuinely unusable one (0.40 and below) is held.

---

## Gamification, and what it is tuned against

Points aimed at 12–18 year olds reward whatever you actually measure, so each
choice here is deliberate:

- **Off-hand reps pay 1.5×.** In lacrosse the weak hand is what every player
  avoids and every coach wants. The premium points the incentive at the hard
  thing. Off-hand is computed against the athlete's *stated* dominant hand, so
  lefties are credited correctly.
- **Balanced-session bonus** when the weaker side carries 40%+ of the work.
- **Diminishing returns within a session.** One three-hour Sunday must not beat
  six honest twenty-minute days.
- **A hard daily XP cap.** Without it the leaderboard measures free time and
  quietly encourages overuse injury.
- **Streaks forgive one missed day.** Games, travel, and exams shouldn't erase
  six weeks; an unforgiving streak makes athletes quit after the first break.

**Five leaderboards, not one** — XP, off-hand, streak, reps, and most-improved.
Ranking only by total XP crowns whoever has the most free time. Most-improved
resets the field every window, and off-hand ranks the hardest work on its own,
so a different athlete can be first at something that matters.

**Team standings rank by XP *per athlete*,** not total — otherwise the board
just ranks teams by roster size and a small squad can never win.

---

## Handling minors

- **Coach-mediated signup.** An adult in the program creates athlete accounts;
  tokens are handed over in person. No athlete email required.
- **Name masking on shared leaderboards.** An athlete 17 or under without
  recorded guardian consent appears as `A. (#14)` or `Athlete A.` — still
  ranked, still accountable, but not full-named on a screen other families see.
  Assigning jersey numbers keeps those handles distinct.
- **Coaches always see real names** on the roster. They are the responsible
  adult; the masking is about broadcast, not supervision.
- **Per-rep timings are pruned** after 45 days (`prune_rep_events`), and
  immediately if a guardian withdraws retention consent. Aggregate session
  records persist; the granular stream exists only for integrity review.

`guardian_consent` is currently a boolean an adult sets. A production deployment
needs a real consent record — who consented, when, and to what — plus the
deletion and access rights COPPA and state student-privacy laws require. That is
the main compliance gap between this and a shippable product.

---

## Known limitations

Stated plainly, because these are the things that decide whether this survives
contact with a real driveway:

1. **Thresholds are calibrated against synthetic motion, not real athletes.**
   The calibration harness makes every drill self-consistent — a textbook rep
   counts and measures what its spec claims — but "textbook" is still a
   sine wave, not a 13-year-old. Filming 20-30 real athletes and re-running
   the calibration against hand-counted ground truth remains the
   highest-value next task, and the reason the specs are data rather than code.
2. **Wall-ball counting is pose-only.** It infers a throw–catch cycle from arm
   motion without tracking the ball, so a convincing shadow-throw with no ball
   counts. Ball detection would close that, at real cost in model size and
   battery.
3. **Handedness is inferred from wrist height**, which is reliable for standard
   lacrosse form and less so for unusual grips.
4. **"Before 8am" badges use UTC.** Athlete-local timezones are not stored yet,
   so that badge is wrong outside UTC. Noted in `store.py`.
5. **Single-process SQLite.** Fine for a program or two; a district-wide rollout
   wants Postgres. `store.py` is the only module to change. Schema upgrades run
   automatically on connect (`db.migrate`), probing the actual database rather
   than trusting a version counter.
6. **Auth is bearer tokens with no rotation or expiry.** Adequate for a pilot,
   not for a public launch.
7. **Revocation soft-fails by default**, though pre-fetched staples make strict
   mode practical — see **Stapling** above. Left soft by default because a
   deployment that has not set up the refresh job would otherwise start
   refusing webhooks; turn on `ATHLETEIQ_SNS_REVOCATION_STRICT=1` once
   `/api/coach/staples` shows them fresh.
8. **No TLS-level stapling on outbound fetches.** Python's `ssl` cannot read a
   stapled response, and doing it needs pyOpenSSL. It would only cover AWS's
   *TLS* certificate rather than the SNS signing certificate, so it was left
   out rather than added untested.
9. **No payment processor.** The billing model, entitlements, and invoicing are
   real; taking money is a `Gateway` implementation away, and nothing here has
   been through a PCI review.
9. **Offline slots are per-drill.** A drill you have never opened online has no
   banked slot, so its first-ever session needs a connection. The app says so
   plainly rather than failing silently.
10. **Web Push needs credentials.** Notifications generate and display in-app
   with nothing configured, but reaching a locked phone needs VAPID keys.
11. **Form quality is pose-only.** It reads how the body moved, not where the
   ball went. A wall-ball rep with perfect mechanics and a bad release still
   scores well, and stick position is invisible to it.
12. **Guardian identity is proven by the invite code alone.** There is no email
    verification, so a code handed to the wrong adult creates a valid account.
    Short expiry, single use, and revocation limit the window; real
    verification is a launch requirement.
13. **Roster import reads delimited text only.** CSV, TSV, and
    semicolon-separated files work; a native `.xlsx` has to be exported to CSV
    first. Direct TeamSnap/SportsEngine API sync is a separate integration.
14. **Load coefficients are reasoned estimates, not measured values.** The
    per-drill numbers in `catalog.py` are a defensible ordering rather than
    validated physiology, and the app sees only self-directed work — so the
    workload picture is directionally useful and absolutely not a clinical
    assessment.
