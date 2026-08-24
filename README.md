# AthleteIQ

**On-device training analysis for youth athletes.**

Athletes record their own training with a phone camera. Pose analysis runs **in
the browser on the athlete's device** — the video never leaves the phone. Only
derived counts (reps, which hand, timing, confidence) are uploaded, scored into
XP, and rolled up for coaches and leaderboards.

There is exactly one exception, and it is opt-in twice over: an athlete can send
**one clip they choose** to their coach, and only where a guardian has turned
that on. Off by default, deleted on withdrawal, gone after 30 days. See
**Coach video** below.

**Sixteen sports.** A program picks its sport at signup and the app fits itself
around it: Lacrosse, Basketball, Soccer, Volleyball, Baseball, Softball, Cheer,
Dance, Swimming, Track & Field, Football, Gymnastics, Tennis, Cross Country,
Ice Hockey and Rugby. Each ships with its own positions — 61 in total — and each
position with its own suggested mix of work and a line saying what that mix is
for. A volleyball middle blocker and a rugby prop get genuinely different plans.

Five sports have skill drills that watch the **ball** rather than the body —
soccer juggling, basketball dribbling, volleyball setting, baseball wall throws,
tennis wall rallies — counted on the phone by the same on-device pipeline, with
nothing but timestamps leaving it. Lacrosse came first and still has the
stick-skill drills, which count wall-ball throw/catch cycles and attribute each
to the hand on top of the stick. Everything else is built on eighteen bodyweight movements
that work for any sport, and the app tells athletes which *other* sports each
one carries over into — because a twelve-year-old doing lateral bounds should
know that is a basketball slide and a tennis recovery step too.

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
python -m pytest tests/ -q          # 1490 tests

DRILL_SPECS="$(python -c 'import json;from athleteiq.drills import ALL_DRILLS;print(json.dumps([d.to_dict() for d in ALL_DRILLS]))')" \
  node --test tests/js/*.test.mjs   # 40 tests
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
  wellness.py       Soreness and injury reporting, and what it holds back
  rtp.py            The ramp back after an injury, and who has to authorise it
  film.py           Short film study: attention scoring and daily caps
  benchmarks.py     Age-banded weekly time budgets and peer context
  positions.py      Canonical positions, aliases, and per-position drill mix
  sports.py         Other sports played, and how single-sport a year is
  transfer.py       What each drill is worth in an athlete's other sports
  ball.py           Server-side checks on ball-tracked sessions
  guardians.py      Parent accounts, invites, consent, export and erasure
  roster.py         Bulk import: header detection, parsing, claim codes
  digest.py         Weekly team KPIs and the coach email
  billing.py        Plans, seats, entitlements, invoicing seam
  recognition.py    Milestones, coach templates, and who signs them
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
    ball.js         Ball tracking: detect-then-track, contacts, ball reps
    ballvision.js   Purpose-built ball detector: colour, regulated size, motion
    review.js       Self-review recording, markers, pose track (never uploaded)
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

## Recognition, and who it comes from

A kid who does wall ball in the driveway on a Tuesday gets a number on a
dashboard their coach might look at on Friday. What they wanted was for someone
to notice. This makes someone notice, on the day, by name.

Milestones fire the moment a session is counted — not from a nightly job,
because "well done" an hour later lands and the same words next morning are a
report. First session, then three, five, ten, thirty and a hundred days in a
row.

**Once per run, not once per day.** A ten-day streak is worth saying something
about; saying it again on day eleven is how a child learns to ignore the app.
Milestones dedupe on the streak they belong to, so an athlete who breaks a
streak and rebuilds it is congratulated again — which is right, because doing it
twice is harder than doing it once. The first version derived the run's start by
counting back from *today*, so the key moved every day the streak continued and
the same message went out three days running. Caught end-to-end, and now the run
start comes from the training days themselves.

**The words are the coach's.** Every milestone ships with a default that reads
like the placeholder it is, editable per milestone with `{first_name}`,
`{streak}`, `{coach}` and `{team}`. Any milestone can be switched off.

### A senior voice, used sparingly

Programs often have someone above the coach — a director of player development,
a former professional. A director can name one, and assign specific milestones
to them: by default only the thirty- and hundred-day streaks.

The restraint is the design. A note from someone like that means something
*because it does not arrive every week*, and putting their name on a three-day
streak spends exactly what made it worth having. A program that never names one
has every message signed by the athlete's own coach, rather than by nobody.

## Families running it themselves

A household can sign up with no club behind it. The parent takes the coach's
place: they set the training, write the recognition, and see everything.

**A family is a program with one household in it.** Building it that way rather
than as a parallel account type means every feature written for a club —
assignments, budgets, recognition, wellness, return-to-play, the lot — works for
a family on the day it ships, with no second code path to keep in step. There is
a test asserting a family can reach the same endpoints a club can.

The parent ends up wearing both hats: director of their own small program, and
guardian of their own children. Those stay **two records rather than one blurred
super-role**, because one sets the training and the other consents to it, and
merging them is what would quietly make the consent checks meaningless. The
guardian link is made directly rather than through an invite code — a code
posted to yourself is theatre — and participation consent is recorded as given
by the parent who just created the account, so the child can train immediately.

Recognition in a family comes from the parent by name. The senior-voice control
is hidden there, because there is no chain of command in a household to be
higher up. The `family` plan is priced at zero for now: the whole product works
for a family the day they sign up, and what they eventually pay is a business
decision that has not been made, so it is set in one place rather than assumed
across the code.

## Messages go one way

Every message an athlete receives is copied to their guardians, and that happens
inside `enqueue` rather than at each call site — the difference between a rule
and an intention. A kind of message invented next year inherits it without
anyone remembering to, and there is a test that fires several unrelated kinds
and checks the parent got all of them.

The copy is marked as one and points at the parent portal, so a parent reads it
as *"here is what your child was sent"* rather than as something addressed to
them. Messages to coaches are not mirrored anywhere.

**Nobody can reply — including the parent.** Not a policy note: there is no
write path into the message stream from an athlete or a guardian, and a test
walks the OpenAPI schema asserting no such route exists. Nothing to moderate,
because there is nothing to send.

## Coach video: the one exception, and what it costs

Everywhere else in this product, video never leaves the phone. This is the
exception, and it is worth being blunt about the trade rather than burying it.

An athlete can send **one clip they choose** to their coaching staff, and only
when a guardian has turned on the `coach_video` consent — which is **off unless
a parent turns it on**. There is no path that uploads a recording because a
session happened, and a test asserts a completed session leaves nothing behind.

| | |
|---|---|
| Consent | Off by default, guardian-granted, revocable |
| Selection | One clip, chosen by the athlete, never automatic |
| Retention | 30 days, purged by the notifications cron |
| Revocation | **Deletes the clips**, in the same transaction as the decision |
| Audit | Every view logged, visible to the athlete and their parent |
| Scope | Staff in that athlete's own program only |

Withdrawing permission deletes the video rather than hiding it. Anything less
makes the consent a preference rather than a permission: a parent who turns it
off has to be able to believe the clips are gone. Consent is also re-checked
when a clip is played, so a permission withdrawn this morning cannot serve last
night's clip this afternoon.

On the athlete's screen the send button is **absent** rather than
present-and-failing when permission is off, because a child tapping something
that tells them their parent said no is a conversation the app should not start.

**This changed the product's headline claim, and four separate structural tests
caught it** — which is what they were for. The database now has its first
athlete-facing binary column, named explicitly in the allowlist rather than
pattern-matched away. One of those tests also exposed a loophole it could not
have caught before: a 20MB string field named `data` sailed through every
name-based check, so oversized request fields now have to be named with a
reason, and that immediately turned up the roster CSV as well.

## What a parent sees

Everything. The same drill log a coach gets, for their own child: every session
across every drill, what was trained, how it scored, and what was held for
review — **held sessions shown rather than hidden**, because a parent finding out
from their child that something was queried is worse than reading it here.

Plus every message their athlete has been sent, and the permissions screen where
any of it can be withdrawn.

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

## Self review

Video is the one thing a rep count cannot give an athlete: seeing what their own
release actually looked like on the rep where the range collapsed. The whole
product rests on that footage never leaving the phone, so this feature exists
entirely on the device — **no endpoint, no upload, no field on any request.**

After a session the athlete can watch it back with the skeleton drawn over it,
and jump straight to the moments worth watching:

- **Your best rep** — fullest range of the session
- **Shortest rep** — only shown when it is meaningfully worse than the best, so
  a consistent set is not handed something to feel bad about
- **Form started slipping** — the first rep in the back half that fell well
  below the early median and did not recover
- **Best left / best right hand** on drills that track handedness

Every marker comes from rep data the client already has, so the whole feature
costs no request and no server round trip. Scrubbing a ten-minute clip to find
the rep that went wrong is work nobody does twice.

Three constraints hold it to the privacy promise:

**It cannot upload.** The recording is a Blob in memory. `review.js` contains no
`fetch`, no `XMLHttpRequest`, no `sendBeacon`, and no URL — asserted by a test
that strips comments first, so the guarantee is checked structurally rather than
promised in prose. A second test inspects every `api()`, `enqueue()`, and
`flush()` call in the capture app and fails if a recorder, Blob, or pose track
ever reaches one.

**It does not outlive the moment.** The Blob and its object URL are released
when the athlete leaves the review screen, taps Done, starts another session, or
backgrounds the app. A clip sitting in memory while the phone is in a pocket is
exactly what the promise says does not happen.

**It does not grow without bound.** A long session is capped at 60MB, oldest
footage dropped first — an athlete who trains twenty minutes can still review
the last ten, and the end of a set is the part worth watching anyway. The app
says when that happened rather than silently showing a shorter clip.

Alongside the video it keeps a compact pose track — twelve body landmarks at
15fps, about 120KB a minute — so the skeleton can be scrubbed instantly instead
of re-running detection on every drag. **Face landmarks are not stored**, and a
landmark that was not visible is recorded as absent rather than guessed, so the
overlay never claims the athlete was somewhere they were not.

Saving the clip puts it on the athlete's own phone. It is their video of
themselves and nothing about it reaches a server either way.

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

## Age benchmarks and the weekly time budget

Most benchmark features answer "how do I compare?" and quietly imply "do more".
For a twelve-year-old who already trains four evenings a week, that is the wrong
answer, so this module is built the other way round: the primary number is a
**time budget**, and the app is willing to tell an athlete to stop.

### The bands

`weekly_target` is a good week, not a floor. `weekly_max` is the point past which
the app says *that is more than enough*. All figures are minutes of logged
training **outside team practice** — team sessions, games, and PE are not in this
budget and are assumed to sit on top of it.

| Band | Target/wk | Min-max | Max session | Days/wk | Framing |
|---|---|---|---|---|---|
| Under 11 | 30 | 15-60 | 15 | 2 (max 3) | Short and fun beats long and serious |
| 11-12 | 45 | 20-90 | 20 | 3 (max 4) | Keep other sports in the mix |
| 13-14 | 75 | 30-135 | 30 | 3 (max 5) | A real habit without taking over the week |
| 15-16 | 110 | 45-180 | 40 | 4 (max 5) | Rest days matter as much as reps |
| 17-18 | 140 | 60-225 | 45 | 4 (max 6) | School is still the bigger commitment |
| 19+ | 150 | 60-300 | 60 | 4 (max 6) | Judge it against your own schedule |

Where the numbers come from: they are anchored on the widely used paediatric
sports-medicine heuristics — cap organised training hours per week at roughly the
athlete's age, keep single-sport specialisation late, take at least one or two
full rest days a week, and take extended off-season breaks. This module spends a
*fraction* of that age-hours allowance on solo work, because the rest belongs to
team practice and games. They are deliberately conservative defaults, not a
clinical instrument, and a program can scale them with `ATHLETEIQ_BUDGET_SCALE`.

An unknown or estimated birth year falls back to the **11-12** band rather than
an average one: guessing low is the safe direction to be wrong in.

### What the athlete sees

Five states, each with copy written to close the loop rather than open it:

- **unknown** — nothing logged; describes what a good week looks like for the band.
- **building** — under the minimum; suggests a number of short sessions capped at
  the band's own `days_target`.
- **good** — "Right where you should be."
- **full** — target reached: *"You have done enough this week... go and do
  something else."*
- **over** — past `weekly_max`: *"Take a couple of days off... there is more to
  being your age than this."*

Advisories fire independently for a single session longer than `session_max`,
for training more than `days_max` days in the week, and for an under-13 over
target — that one points at other sports and unstructured play by name.

The progress bar is capped at `weekly_max`, not at the target, so a full bar
never reads as a score to beat. Tests assert that no message in any state
contains "must", "behind", or "only".

### Peer comparison, deliberately narrowed

Comparison never crosses age bands: telling a twelve-year-old they rank below
the seventeen-year-olds is information about their birthday, not their training.
Within the band it narrows to position where the numbers allow (see **Position
benchmarks** below) and is suppressed entirely below `MIN_PEER_GROUP` (8) even
at full band width, so a small squad cannot turn into a two-person race.

**Volume is never compared.** Ranking kids by minutes trained is precisely the
mechanic that produces the twelve-year-old training four evenings a week. What
is compared is **form quality** and **off-hand balance** — things that improve by
training better rather than more. **Consistency** is offered only to an athlete
whose status is `unknown` or `building`, where a nudge is still useful; once
they are at `good` or above it disappears rather than becoming a reason to add
sessions.

### The drill catalog, and what is deliberately missing

Twenty drills: two lacrosse stick drills and eighteen bodyweight movements that
work for any sport — squats, lunges, glute bridges, push-ups, pull-ups, planks,
side planks, hollow holds, wall sits, dead bugs, mountain climbers, burpees,
squat jumps, tuck jumps, lateral bounds, high knees, jumping jacks, sit-ups.

**There are no dribbling, juggling, serving or shooting drills, on purpose.**
Those need the *ball* tracked, not the body, and a drill that miscounts is worse
than one that does not exist. Everything shipped has an unambiguous pose signal
and is driven by the calibration harness — which caught a real error while this
was being written: mountain climbers were declared with a `target_rom` of 0.33
when a textbook rep measures 0.42, which would have handed out full depth for a
half rep.

Sport-specific *skill* work is coached through film clips and assignments
instead, which is where a coach's eye belongs anyway.

The harness also used to skip any drill with no calibration sweep, silently — so
a newly added drill was unguarded and looked green. It now fails instead.

### Position benchmarks

Three problems sit between a `position` column and a useful benchmark, and the
first two are the ones usually skipped.

**Sixteen sports ship with positions.** Lacrosse, Basketball, Soccer,
Volleyball, Baseball, Softball, Cheer, Dance, Swimming, Track & Field, Football,
Gymnastics, Tennis, Cross Country, Ice Hockey and Rugby — 61 positions, each
with its own drill mix and its own one-line focus. A program picks its sport at
signup and the app fits itself around it.

Positions resolve **per sport**, which matters more than it sounds: "C" is a
centre in basketball and a catcher in baseball, "D" is a defender in lacrosse
and a defenceman in hockey. Sports without a meaningful position (cross country)
still get one entry describing the sport's own demands, rather than falling back
to a generic mix that knows nothing about distance running.

Emphasis weights are written as relative numbers and normalised by a `mix()`
helper, because the alternative is a hundred hand-balanced dicts of decimals
where one typo silently leaves a position adding up to 0.97 and nobody notices.

Weak-hand parity stays a **lacrosse-only** comparison. It is computed from the
left/right split a drill reports, and the only drills that report one are the
two stick drills — so `offhand_matters` is False everywhere else. That is not a
claim that bilateral skill is unimportant in basketball; it is a refusal to rank
children on a number that would be zero for all of them.

**The column is free text.** A single roster import contains "Middie",
"midfield", "MF", "M" and "Mid" for the same position. `WHERE position =
'midfield'` matches none of them, which is how a position filter ends up
looking implemented and grouping nobody. `positions.py` normalises on read —
case, punctuation, parenthetical qualifiers ("Goalie (JV)"), dual entries
("attackman/midfield" takes the first, by convention the primary), and
placeholders. Placeholders are checked *first*, because some are actively
dangerous: "N/A" splits on the slash into `["N", "A"]`, and "A" is a perfectly
good alias for Attack. Unrecognised is a real answer — it widens the peer pool
rather than inventing a position, and it is reported to the coach, because an
unresolved position silently drops that athlete out of every position feature.

All of this applies **only to athletes old enough for it** — see
**Specialisation is a setting** below, which gates both the drill mix and the
peer pool.

**A team does not have eight goalies.** So the peer pool widens in steps —
position, then position family, then simply the age band — and the answer says
which step it settled on. The athlete reads "compared with 11 midfielders your
age", not an unqualified percentile. On one realistic U13 squad all three tiers
fire: midfielders compare within position, attackers within *attackers and
midfielders*, and the lone face-off specialist against the age band.

Families pool attack with midfield, and defense with LSM — a long-stick
midfielder is a defender who runs, and the stick work they practise is a
defender's.

**Comparison is the less useful half.** What a defender should do with a
driveway hour does not depend on how many other defenders logged sessions this
week. So each position carries an `emphasis` — a drill mix expressed as
*shares of solo time*, never as an amount — and the athlete sees their actual
mix against it. This needs no peer group at all: a goalie spending every
session on wall ball gets told so on a team of one, on day one.

Every suggestion is a **swap**: *"Swap some of your wall ball time for quick
stick. Same minutes, and it is what goalies lean on."* "Also do lateral bounds"
would quietly raise the weekly total the budget just finished capping, so the
tests assert no suggestion contains "add", "more", "extra" or "also", and that
every one contains "same minutes". Suggestions are suppressed entirely when an
athlete is over their ceiling — there, the only message that should land is
"stop", and a second task alongside it blunts the first.

Position also decides *what is worth comparing*. Weak-hand parity is a goal for
field players and not for a goalie, whose stick work is two-handed save
mechanics and an outlet pass; ranking a goalie on left/right balance would score
them on something they are not building, and worse, make them chase it. So the
off-hand board is withheld from goalies specifically.

`/api/positions` exists so the join form can offer a list instead of a text box.
Normalising free text is repair work; a dropdown means there is nothing to
repair. A sport with no position model returns an empty list and the form falls
back to free text — honest silence rather than another sport's positions with
the labels changed.

### Multi-sport tracking, and why the gate reads it

An age threshold alone could not tell a fourteen-year-old who plays basketball
in winter and runs track in spring from one who plays lacrosse eleven months a
year and nothing else. Those are different children, and the second is the one
the research is actually about. So athletes record what else they play, and two
things key off it.

**Seasons, not hours.** A twelve-year-old can answer "which seasons do you play
basketball" and cannot answer "how many hours a year". Four checkboxes per sport
is the smallest thing they will actually fill in.

The score is shaped after the screening questions used in youth sports
medicine — has this athlete dropped other sports, is one ranked above the rest,
do they train it more than eight months a year — with the last two answered by
proxy from the season picker. It is a routing heuristic for how cautious to be,
not a diagnosis.

| Year | Level | Gate (program set to 15) | Weekly budget |
|---|---|---|---|
| Three sports across three seasons | low | **13** | ×0.7 |
| One sport, one or two seasons | moderate | 15 | ×0.85 |
| One sport, year-round | high | **17** | ×1.0 |
| Nothing recorded | unknown | 15 | ×1.0 |

**The specialisation gate moves.** Real variety already supplies the broad
athletic base the delay was protecting, so position guidance starts earlier.
Single-sport and year-round gets it later. Three guards on that, all tested:
the adjustment is bounded to ±2 years, it can never go below `ABSOLUTE_MIN_AGE`
(12) whatever the sport mix says, and a director who set the program to *never*
is not overridden by a child filling in a season picker.

**The weekly solo budget shrinks.** A kid playing three sports is already moving
plenty, and none of that week shows up here. Only the volume figures scale —
`session_max` and the days-per-week targets are left alone, since trimming the
week should not start flagging ordinary sessions as too long or push the same
work into fewer days. `BUDGET_SCALE` is capped at 1.0 in both the table and a
test: **recording sports can never unlock more training.**

The athlete is told when their line moved, and why:

> Your training plan is the all-round one until you are 17. […] You have
> Lacrosse down for most of the year and nothing else, so we are giving the
> all-round work a bit longer than usual — that is the part that protects you.

An unexplained difference between two kids on the same team gets compared in a
group chat and read as the app being broken.

Transfer notes also lead with the sports the athlete actually plays — *"This one
pays off in Basketball, which you play — and in Soccer and Tennis."* Sorted
rather than filtered, because part of the point is making a single-sport kid
curious about a sport they have not tried.

Coaches see the squad's spread across the four levels, and the year-round
athletes **by name** — unlike the budget lists, which never name anyone. That is
deliberate: this is not a this-week nudge, it is a conversation with a family
about a pattern that took a season to form, and the dashboard says so.

Roster import reads a `sports` column ("basketball; soccer", "Bball / XC") but
deliberately **imports no seasons** — a roster column will not carry them, and
inventing a plausible span would relax the gate on data nobody gave us. An empty
season list scores as a short year, which never makes an athlete look more
multi-sport than they are.

### Specialisation is a setting, and it defaults late

Position guidance is **off below an age the program sets**, default 15. Under it
every athlete gets the all-round mix regardless of the position on their jersey.

This is the one place the tool could do real harm by being good at its job. A
twelve-year-old labelled a goalie, handed a goalie drill mix and a goalie
leaderboard, is being specialised by software — and early single-sport,
single-role specialisation is the pattern youth sports medicine warns about most
consistently. So the gate applies to *both* halves of the position feature: below
the threshold the athlete gets the general mix **and** is pooled against their
whole age band rather than their position.

A useful consequence falls out of that: the off-hand board is withheld from
goalies who specialise, but a *young* goalie still gets it. They may not be a
goalie at sixteen, and both hands are worth building either way.

`PUT /api/org/specialisation` moves the line — directors only, since it is a
judgement about how children in this program are developed. Options are all
ages, 13+, 15+ (recommended), 17+, or never. Setting it to never keeps an entire
program on the all-round plan permanently, which is a legitimate thing for a rec
league to want. Existing databases migrate to 15.

Position is still **recorded** below the threshold — on the roster, in the coach
view, and named back to the athlete:

> **You are down as goalie, and your coach knows it.** Your training plan is the
> all-round one until you are 15. The best players your age are the ones who can
> run, jump, land and change direction — that is what turns into being good at
> goalie later, and it is worth more right now than practising one job.

Saying nothing here would read as the app not knowing what position they play,
and a kid who believes that will go and do position work anyway.

### What a drill is worth in the sports they also play

Every drill carries what it transfers to, with the athlete's own sport filtered
out — on the drill picker, and again on the summary screen right after they
finish, which is when they are most likely to read it.

| Drill | Reads as |
|---|---|
| Lateral Bounds | *Basketball* — staying in front of the player you are guarding is this exact move |
| Squat Jumps | *Basketball* — the second jump on a rebound, which wins most of them |
| Burpees | *Soccer* — the 80th minute |
| Plank Hold | *Baseball* — a bat swing comes from your middle, not your arms |

This is not decoration. It is the argument for the gating above, written where an
athlete will actually read it — and it is the argument they will repeat to a
parent who asks why the lacrosse app has them doing squats. So for an athlete
below the threshold, the mix suggestion itself is argued by other sports rather
than by position:

> Swap some of your wall ball time for push-ups. Same minutes, and it pays off in
> Swimming, Wrestling and Football too.

Two rules keep it honest, both tested. The athlete's own sport is never listed
back to them. And a drill that genuinely does not transfer says so: the stick
drills get two entries, not a padded four, because a claim a kid can check and
find false costs every other claim on the screen. Every `why` names a moment in a
sport rather than a quality — the test bans "helps with", "good for", "improves
your" and friends, since length is a poor proxy ("the 80th minute" is fifteen
characters and one of the most concrete lines in the table).

### What the coach sees

`program_summary()` returns counts across all five states, an explicit
`over_budget` list, the squad's position breakdown, and any position strings
that did not resolve. Over-training surfaces as prominently as under-training, on
the same screen — a coach should find out that a kid is grinding every night in
the same glance that tells them who has not started.

## Ball tracking

The catalog used to stop at the body. A wall-ball rep was a throwing motion, so
a convincing shadow-throw with no ball counted, and there were no dribbling or
juggling drills at all because counting them means watching the *ball*. Five
drills now do: soccer juggling, basketball dribbling, volleyball setting,
baseball wall throws and tennis wall rallies.

It runs on the phone, like everything else. Nothing about the privacy posture
changes: what reaches the server is still timestamps and speeds.

### Detect, then track

A detector heavy enough to find a tennis ball cannot run every frame while
MediaPipe is already using the GPU. So detection runs at roughly 15fps and a
constant-velocity tracker fills the gaps — and frames the tracker *invented* are
labelled as such and never counted as evidence.

The detector is COCO's `sports ball` class, which covers every ball in the
catalog, loaded on demand: an athlete who only does squats never downloads it.

### A contact is physics, not a heuristic

A ball in free flight accelerates downward at a constant rate. Anything else is
something hitting it. So a contact is a velocity change far larger than gravity
explains — and **gravity is learned from the athlete's own footage**, which means
the detector never needs to know the camera distance, what the frame height
represents in metres, or which way up the phone is. Against synthetic
trajectories it recovers a true gravity of 2.4 as 2.40, and 4.0 as 3.77.

What *kind* of contact is the difference between two drills. The classifier
checks body landmarks before the floor, so a ball bouncing at ankle height is a
juggle if a foot is next to it and a dribble if nothing is. There is a test
driving the same trajectory into both drills and asserting each counts it — and
that a foot placed elsewhere counts nothing.

### The purpose-built detector

The general model knows "sports ball" from photographs. It does not reliably
see a 6cm ball moving at speed against a wall, and it cannot tell a basketball
from an orange thing in the background because it has no idea how far away
anything is. Every ball drill now uses the purpose-built detector instead.

**`ballvision.js` is classical computer vision, not a trained model.** No
network was trained and none is downloaded. That is a deliberate choice, not a
shortcut: training one needs thousands of labelled frames of real athletes,
which do not exist for this product and could not be collected without
uploading exactly the footage the architecture promises never to upload. It
exploits four things about a lacrosse ball instead, none of which a general
model can use.

**Its size is regulated.** Every ball in the table below has a diameter fixed by
rule. Pose gives the athlete's torso in the same frame and a youth torso is about
45cm, so the expected radius in pixels is *computed*, not guessed — and anything
twice or half that is not the ball. A general detector cannot do this.

| Sport | Ball | Colour profile |
|---|---|---|
| Lacrosse | 6.35cm | white |
| Tennis | 6.7cm | optic |
| Baseball | 7.4cm | white |
| Softball | 9.7cm | optic |
| Soccer | 20.5cm | white |
| Volleyball | 21cm | white |
| Basketball | 23cm | basketball |

Where a sport has youth sizes the middle one is used; the spread is about ten
percent, which the radius tolerance absorbs several times over. A basketball is
nearly four times a lacrosse ball across, so using one number for everything
would have made the size gate useless.

**Its colour is regulated too.** Five profiles — white, yellow, orange,
basketball and optic — with centroids measured from real ball colours in sun and
shade, in illumination-normalised chroma so a ball in shadow lands on the same
point as one in sun. Tolerances come from the distance to the nearest thing that
is *not* a ball, and a test asserts every ball matches its profile while no
distractor matches any:

| Profile | Nearest distractor | Distance | Tolerance |
|---|---|---|---|
| Yellow | skin | 0.134 | 0.055 |
| Orange | brick | 0.120 | 0.050 |
| Optic | skin | 0.126 | 0.050 |
| **Basketball** | **brick** | **0.056** | **0.030** |

Basketball is the tight one, and worth naming: an orange-brown ball against an
orange-brown wall is the least separable pair in the product, so it leans hardest
on size and shape. Better than any preset, "Show the app your ball" samples the
athlete's actual ball under their actual light — which is also the answer for a
purple soccer ball or anything else the presets do not anticipate.

**It is a solid disc**, so matched pixels must fill the circle they imply. A
yellow jacket sleeve matches on every pixel and is rejected for being a streak.

**It flies ballistically**, which the tracker already checks.

Working width is **480px, and that number is the crux**. At a realistic framing
the torso spans about 30% of frame height, so a lacrosse ball is roughly *two
pixels across* in a 192-wide image — a large part of why the general detector
could not find one. At 480 the same ball is about six pixels, which is findable,
for about a millisecond a frame. Below a resolvable size the detector says so
rather than silently counting nothing.

A white ball on a white wall is the genuinely hard case and colour cannot solve
it — a pale wall matches the white profile *better* than the ball does. The
motion gate carries it, and it is **directional**: a bright ball arriving makes a
pixel brighter, a bright ball leaving makes it darker, and a plain
change-magnitude test followed the hole the ball left instead of the ball.

**Motion decides where to look; colour and shape measure what is there.** That
split matters more than it sounds. Gating pixels on motion directly worked for
small fast balls and quietly broke large ones: a basketball moving at normal
speed overlaps itself almost completely between frames, so only a thin crescent
changes and the ball measured as a sliver — detection sat at 41%. Measuring by
colour first and falling back to the moving pixels only when colour
over-segments fixed it, and detection across every sport on a normal background
is now 100% in simulation.

### Two modes: counting, and confirming

A ball spec does one of two jobs, and which one matters more than any threshold
in it.

**`count`** — the ball *is* the rep. Juggling with no ball is not juggling, so
these refuse below the quality floor. The five new drills.

**`confirm`** — the body still counts the reps and the ball corroborates them.
`lax_wall_ball` works this way. Its pose signal already counts throw–catch
cycles well and attributes the top hand; replacing that with contact counting
would break every existing athlete's history for no gain. What the ball adds is
the one thing pose cannot see: that there was no ball.

The rule is **deliberately asymmetric**, and the asymmetry is the design.

| What happened | Result |
|---|---|
| Client sent no ball data at all | Counts exactly as before ball tracking existed |
| Ball never detected | Counts, with a note saying so — **no penalty** |
| Ball tracked, throws corroborated | Counts quietly |
| Ball tracked clearly, involved in <25% of throws | **Held for review** |
| Ball tracked clearly, never leaves the hands | **Held for review** |

Not seeing a ball proves nothing. A lacrosse ball is outside COCO's vocabulary —
the detector knows basketballs and tennis balls, not a 6cm ball moving at speed
against a wall — so a miss is at least as likely to be the model's blind spot as
the athlete's honesty, and it never costs them anything. Seeing the ball clearly
for a whole session and watching it never leave a hand while the arms threw
forty times proves quite a lot. Penalising only on positive evidence is what
stops this becoming a feature that quietly marks down every kid whose ball
happens to be white.

That last row is the one contact counting could not see. An arm whipping
through a throwing motion with the ball still in it produces the same impulse
beside the same wrist as a real release — in simulation, **twelve contacts for
twelve fake throws, identical to the real session**. What cannot be faked is the
ball leaving: real wall ball sends it metres away and brings it back, so the
client reports the share of tracked frames the ball spent more than 1.5 torsos
from the nearest hand. Real: 0.45. Waving it around: 0.00.

Short sessions are never judged this way, an older client that predates ball
tracking is unaffected, and the count-mode checks (metronomic timing, an
impossible left/right split) do not apply — wall-ball reps come from pose, which
has its own integrity layer for that.

The capture screen never nags on a confirm drill either. It says "Ball
confirmed" when it can see one and stays silent when it cannot, because telling
a child to fix a detector's blind spot is asking them to solve something they
cannot.

### When it cannot see the ball, it says so

`required=True` on every ball drill is enforced, not advisory. Below the
track-quality floor the session is **held for review** rather than counted, and
the athlete sees the ball-seen percentage live while recording, because someone
who can see the app losing the ball can move the phone. A drill that quietly
degraded to pose-only would report "42 juggles" for a kid standing still, which
is worse than not shipping the feature.

The server checks it too, because the browser did the tracking and so the
browser cannot be trusted with the result — the same reasoning that produced the
pose integrity layer, applied to a payload that is easier to fake because a
contact is a timestamp rather than a whole skeleton. It rejects contacts closer
together than the drill's own refractory window (a real client enforces that
itself, so their presence means the payload did not come from one), rates faster
than the ball can come back, metronomic timing, and a left/right split too exact
to have happened. A missing quality figure is itself a reason to hold: a real
client always knows that number.

Ball drills carry **no form score**. Range of motion is a pose idea; a contact
has none, and claiming one would be inventing a number.

### Either way up, and no perfect angle

An athlete should be training, not deciding how to prop a phone. Three things
make that true rather than aspirational.

**Distances are measured in frame heights, not raw normalised units.** Pose
landmarks and ball positions both arrive normalised 0-1 against their own axis,
which makes that space *anisotropic*: in a 16:9 landscape frame one x-unit is
1.78 times wider on the ground than one y-unit, and in portrait it is the
reverse. Every radius here is a real distance, so measuring in raw units meant
turning the phone silently changed what "next to the ball" meant — a foot
0.1 across from the ball counted as a touch in one orientation and not the
other. There is a test asserting the same physical contact classifies the same
either way up.

**The working image is budgeted on area, not width.** Sizing by width meant a
phone held upright produced a 480×854 working image — three times the pixels and
three times the cost — purely because the athlete turned it. Both orientations
now cost the same and resolve the ball to the same number of pixels for the same
physical scene.

**The body scale has fallbacks and a memory.** The size prior needed a shoulder
*and* a hip, so an athlete framed from the chest up — which is most of them,
because a phone propped against a bag points where it points — lost the
detector's strongest filter entirely. It now tries torso, then shoulder width,
then head-to-shoulder, then thigh, and remembers the last good reading for four
seconds so turning away or being briefly hidden by your own stick does not lose
it mid-rally.

The capture screen replaces the setup paragraph with one line that says whether
the app can see what it needs — *"Got you and the ball"* — and mentions, once,
that the other orientation works just as well. The camera request stopped
insisting on a portrait shape, and turning the phone mid-session is handled
rather than tolerated. Drill hints no longer prescribe distances: *"Prop the
phone up anywhere it can see you and the ball. Any angle."*

### What the coach sees about skill work

Touches, not minutes, and nobody ranked by how many — the same rule every other
board here follows. Sessions held for review are shown but not framed as an
accusation.

The genuinely useful column is **"sees the ball"**, and it comes first as an
action list. An athlete whose sessions keep coming back with the ball barely
visible is not slacking and is not cheating: their phone is somewhere it cannot
see, and that is two minutes of a coach's time at the next practice. Nothing
else in this product can tell a coach that.

```
Athlete     Touches  Sessions  Sees ball  Held
Dev P.          120         2        48%
Ava R.           84         2        66%
Ben T.           56         2        55%
Cleo M.           0         2         9%     2

Worth two minutes at practice:
  Cleo M. — ball visible in 9% of frames
```

Flagged only after two or more sessions, because one badly propped phone is an
accident and three is a habit.

## Film study

Reps build hands. Watching builds the other half — reading a slide, seeing a cut
two passes early, knowing where the help is coming from. That half is normally
only available to a kid whose coach happens to run film sessions, and short
clips with a coach's voice over them are the cheapest way to give it to everyone.

Coaches curate clips by pasting a link. Athletes get a short shortlist, filtered
by age, and it disappears when the day's allowance is gone.

### Nothing is uploaded, and the honest caveat

A clip is a **provider and an id** — nothing is downloaded, re-hosted, or
stripped of its ads. It plays in the provider's own embedded player, which is
what embedding is for. Coaches can paste any shape of YouTube link (`watch?v=`,
`youtu.be`, `shorts/`, `embed/`, or a bare id) and it is parsed and validated
before it goes anywhere near an embed URL.

**This is a genuine change of posture from the rest of the product**, and the
README says so rather than glossing it. Everywhere else, video never leaves the
phone. Here the athlete's browser talks to YouTube, and YouTube knows about it.
Mitigations, not cures:

- `youtube-nocookie.com`, YouTube's privacy-enhanced host
- `rel=0`, so a clip aimed at a child does not end in a grid of unrelated video
- the IFrame API script is loaded **on demand**, so an athlete who never opens
  film never talks to Google at all
- the `link` provider exists for programs that host their own clips

A program that cannot accept a child's browser reaching YouTube should self-host
and use `link`. Worth checking your own obligations here — youth programs and
schools often have rules about third-party embeds that this README cannot know.

### Attention, not playback

A tab left running is not film study, and neither is a muted clip — the coaching
is in the audio. The client is untrusted exactly as it is for rep counting.

Heartbeats carry **position, never elapsed time**: the server measures elapsed
itself from its own record of the previous beat, because a payload that reports
its own clock can report whatever makes the numbers work.

| What happened | Verdict |
|---|---|
| Watched through, sound on, ≤1.5× | `watched` |
| Muted, or the tab was hidden | `background` |
| 2× speed, or scrubbed repeatedly | `skimmed` |
| Stopped early | `partial` |

Only `watched` counts for anything. Coverage tracks **distinct seconds seen**, so
looping the first ten seconds forty times racks up playback and almost no
coverage. A jump forward earns nothing and is recorded as a seek. A gap between
beats longer than 20 seconds is a locked phone, not attention, and is not
credited. 1.25× is how people watch things, so the line sits above it.

### Minutes are capped hard, by age

A daily film budget is screen time dressed up as training, and it would be very
easy for this to become the thing a kid does for forty minutes because it is
easier than going outside.

| Band | Longest clip | Daily minutes | Daily clips |
|---|---|---|---|
| Under 11 | 75s | 4 | 2 |
| 11-12 | 100s | 6 | 3 |
| 13-14 | 140s | 9 | 4 |
| 15-16 | 170s | 12 | 5 |
| 17-18 | 200s | 15 | 6 |
| 19+ | 240s | 20 | 8 |

Clips longer than a band's cap are simply not offered to it, and a clip over the
longest cap **cannot be curated at all** — a ten-minute "short clip" is how a
film feature turns into homework. When the day is spent the shortlist returns
**empty**, not greyed out: a grid of clips an athlete cannot watch is an
invitation to go and find them somewhere else. A clip already started can always
be finished, because stopping a kid halfway through is worse than a minute over.

### Gamification, deliberately weak

Film earns 12 XP a clip, capped at 40 a day — under a fifteenth of the daily XP
cap, and asserted as such in a test. A kid must not be able to out-earn training
by watching video.

**Film keeps its own streak** rather than feeding the training one. Letting film
hold the training streak would mean a streak maintained from the sofa, which is
the opposite of what the streak is for. There is a test asserting film alone does
*not* hold it.

The question after a clip is a comprehension check, not a grade: getting it wrong
costs nothing, awards the same XP, and is never reported to a coach as a score.
The answer is not sent to the client until it has been given. What a coach sees
is who is watching, not who is clever — **completions and days, never minutes**,
because minutes are not a thing to rank children by here either.

## Soreness and injury reporting

The most sensitive data in the product: health information about children.
Three failure modes decided the design, and two of them are not privacy
failures at all.

### Telling the truth is free

**A kid who loses something by reporting pain will stop reporting pain.** If a
check-in costs a streak, XP, or a place on a board, athletes learn within a
fortnight to tick "fine" — and the data becomes worse than useless, because it
becomes a record saying everyone is healthy.

So a wellness check-in **protects the streak exactly as a recovery day does**,
awards nothing, costs nothing, and never appears on any leaderboard. Reporting
something that hurts *is* a check-in, so a kid who just described a sore knee is
not then asked to tick a mood face. There is a test asserting the streak
survives, one asserting XP does not move, and a structural one that greps the
leaderboard and standings payloads for any trace of it — the same shape as the
no-video rule.

### It never says what it is

Nothing here names a condition. No "tendinitis", no "probable strain", no
severity score out of ten a parent can search. Every output is a thing to do or
a thing to notice. Two tests enforce it across every area × severity × flag
combination: one bans a vocabulary of diagnoses, the other requires each message
to contain an actual instruction.

Severity is four phrasings rather than a number, because a ten-point scale
invites a twelve-year-old to compare their 6 with a teammate's 8:

| | |
|---|---|
| `fine` | All good |
| `niggle` | I notice it, but it doesn't stop me |
| `sore` | It changes how I move |
| `hurts` | I can't do it properly |

### The note is not the coach's

Coaches get what changes a training decision — area, side, severity band, days
running, direction of travel, and which flags were ticked. The free-text note
the athlete writes goes to them and their guardian, and nobody else. The form
says so before they type.

The coach shape **omits the key entirely** rather than blanking it: an empty box
invites someone to ask what it said. The split is enforced server-side, because
a client-side filter is a suggestion.

### Head and neck are not on the ladder

Any report there stops training outright and escalates to an adult, **at any
severity**, with no gradations and no algorithm — the mildest possible head
report still names the hospital question. Being wrong about a head knock in a
twelve-year-old is not symmetrical with an unnecessary rest day.

### What escalates, and what it holds back

Flags escalate regardless of how bad it feels — a niggle that gives way is not a
niggle. So does "I can't do it properly", anything getting worse, and anything
dragging past a week.

| Assessment | Guardian told | Drills held |
|---|---|---|
| `monitor` | no | none |
| `ease_off` | no | that area's tissues |
| `tell_someone` | **yes** | that area's tissues |
| `stop` | **yes** | everything |

Holds map through the existing `Tissue` taxonomy on each `DrillSpec`, so a sore
shoulder hides wall ball and leaves squats, and a sore knee does the reverse.
Held drills are **dimmed and sorted last, not removed** — the app is not anyone's
physio and should not pretend it can stop a determined thirteen-year-old, but it
should not put a sore knee on the home screen with a button next to it either.

Guardian escalation fires on the *assessment*, not the severity, and happens on
the request rather than in a nightly job — a joint that gives way is not a thing
to mention to a parent tomorrow morning. The athlete's note is **not** in the
notification: a guardian can read it in the app, logged in as themselves, but a
push notification is read on a lock screen in front of whoever is standing there.

### Keeping it only as long as it is useful

Repeat reports on one area update that area's row rather than stacking new ones,
so "day 4" stays meaningful and a coach does not see a wall of duplicates.
Direction of travel is persisted alongside, and only moves when the severity
actually changes — otherwise a kid correcting a typo would erase the trend.

An open report goes stale after 10 days and stops blocking, because a kid who
got better and forgot to close it should not be locked out forever. Resolved
reports are purged after 400 days by the notifications cron; open ones never
are, since an open report is a live thing about a body that still hurts.
Everything is in the guardian export and is deleted by the erase path.

### Coming back afterwards

The most important thing in `rtp.py` is what it refuses to do: **it never clears
anyone.** A graduated return after an injury is a medical decision, and an app
that produces a green tick saying "you are ready" is dangerous however carefully
the stages are worded. Clearance is always a human's, recorded here as a fact
with a name and a date — this stores the sentence *"Jordan's guardian recorded
that a doctor cleared them on the 3rd"*, and never generates it.

What it is good for is the part after that decision. A ramp is a schedule, and
schedules are what software does well.

Saying "better now" about something that had escalated does not simply close the
report — it opens a ramp behind it. A stiff thigh still closes outright; not
everything that aches is an injury to come back from.

| Stage | Min days | Session cap | Loads the injured area |
|---|---|---|---|
| Resting | — | none | no — *ends when an adult says it can* |
| Moving again | 1 | 15 min | no |
| Back to drills, easy | 2 | 25 min | yes |
| Full solo training | 2 | uncapped | yes |
| Done | — | — | *"your coach's call and your parent's, not this app's"* |

Advancing needs three things: time served at the stage, a check-in **today**
saying they feel fine, and — for the first step — an adult. Every refusal
returns a sentence explaining itself, because a greyed-out button with no reason
is how a kid decides the app is broken and goes back to training on their own.

### Who can authorise what

| | Ordinary return | Head or neck |
|---|---|---|
| The athlete | **never** | **never** |
| Coach or director | yes | **no** |
| Guardian | yes | yes, with a named clinician |

A coach can clear the ordinary ones — a judgement coaches already make at every
practice. A head or neck return can only be recorded by a guardian, because it
needs what a doctor told the family and a coach has no standing to report that.
The clinician's name is required, not because the app can verify it, but because
typing one makes the step deliberate rather than a tap on the way to the pitch.
It is stored as an *attestation by the person who typed it*, never as a fact
about the clinician. In the coach view that button is simply absent rather than
present and failing.

Every plan carries an append-only history — opened, cleared, advanced, setback,
with actor and date. This is the one place in the product where "who decided
what, and when" may genuinely need answering later.

### Setbacks are survivable

Reporting the same area during a ramp steps it back **one stage, never to the
start.** Resetting the plan is the same mistake as charging a streak for
reporting soreness: if speaking up costs a week, a thirteen-year-old who wants
to play on Saturday stops speaking up, and the ramp becomes a formality they
walk through while hurt. The copy says so outright:

> Your knee spoke up, so you have gone back one stage. That is not a punishment
> and it is not starting over — it is the ramp doing exactly what it is for.
> Telling us is the right call every time.

A second setback returns the plan to `awaiting_clearance`, because at that point
the ramp itself is not the answer and an adult should look again. Reporting
during a ramp still protects the streak, like every other check-in.

A drill held back by a ramp says so differently from one held back by pain —
*"Not at this stage of your knee ramp yet"* rather than *"Resting your knee"*,
which would confuse an athlete whose knee stopped hurting a week ago. A ramp
nobody has touched for 45 days is treated as abandoned and stops holding
anything.

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

1. **Coach video is a real hole in the on-device promise, by request.** The
   default is off and every gate above is enforced, but a program that turns
   it on is storing children's video in a database — with the retention,
   backup and breach exposure that implies. The clips live as BLOBs in SQLite
   with no encryption at rest beyond whatever the host provides. A program
   with meaningful obligations here should keep the consent off, or host
   somewhere that encrypts the volume.
2. **Recognition can be gamed by a determined athlete.** Streaks count days
   with a counted session, and the integrity layer decides what counts — so
   the same weaknesses it has, this inherits. A kid who can fool the rep
   counter can fool the milestone. Nothing here awards anything a coach would
   otherwise have to withhold, so the cost of being wrong is a nice message
   somebody did not earn.
3. **Film study sends a child's browser to a third party.** Everywhere else
   in this product video never leaves the phone; film is the exception, and
   the privacy-enhanced host is a mitigation rather than a fix. Programs with
   obligations around third-party embeds — schools especially — should check
   them before enabling it, and self-host with the `link` provider if in
   doubt. Clip availability is also outside our control: an uploader can
   disable embedding or delete a video, and a curated clip can go dead.
4. **Attention scoring can be fooled by someone determined.** It catches the
   ordinary ways of not watching — muted, backgrounded, scrubbed, raced — but
   a kid who leaves a clip playing at normal speed with the sound on and walks
   away is indistinguishable from one who watched it. The comprehension
   question is the better signal, and it is optional per clip.
5. **Nothing here is a medical device, and the return ramp least of all.** The
   stages are a load schedule, not a protocol, and completing one means the
   athlete pressed a button five times over five symptom-free days — not that
   any tissue has healed. The app records that a human cleared them and cannot
   verify that the human was right, that a named clinician exists, or that the
   athlete answered honestly. It should never be the reason a young athlete
   goes back, and finishing a ramp should never be the reason one is picked.
6. **Soreness reporting is not a medical device and must not be relied on as
   one.** It is a prompt to involve an adult, and its most important output is
   "tell someone" rather than any assessment of its own. It cannot see an
   athlete who says nothing, it takes every report at face value, and a child
   who is hurt and silent looks identical to one who is fine. Nothing in it
   should ever delay getting a young athlete looked at.
7. **Thresholds are calibrated against synthetic motion, not real athletes.**
   The calibration harness makes every drill self-consistent — a textbook rep
   counts and measures what its spec claims — but "textbook" is still a
   sine wave, not a 13-year-old. Filming 20-30 real athletes and re-running
   the calibration against hand-counted ground truth remains the
   highest-value next task, and the reason the specs are data rather than code.
8. **The ball detector is validated on synthetic frames, not real footage.**
   Rendered discs on rendered backgrounds prove the logic — colour separation,
   the size gate, shape rejection, motion direction, the large-ball fix — and
   say nothing about motion blur on a hard throw, a ball leaving frame between
   detections, or a cluttered garden. Filming real athletes and measuring the
   detection rate is the highest-value next task, exactly as it is for the pose
   thresholds. Treat every detection percentage quoted above as arithmetic
   rather than evidence.
9. **A large white ball against a pale wall is the weakest case.** Colour
   cannot separate them, and a big ball barely displaces itself between frames
   so the motion fallback has little to work with: in simulation soccer and
   volleyball detect at about 55% against a pale indoor wall, against 100% on
   grass or anything with contrast. Still above the quality floor, so those
   drills count, but indoor volleyball is where this is thinnest. Small balls
   are unaffected — a lacrosse or tennis ball fully displaces itself between
   frames, so motion sees all of it.
10. **A session with no ball at all is still counted.** Wall-ball confirmation
   only ever penalises on positive evidence, so an athlete who films with no
   ball in shot, or against a background where it is never detected, gets a
   note and full credit. That is the deliberate trade — the alternative marks
   down every kid whose lighting is poor — but it means the shadow-throwing
   hole is narrowed, not sealed.
11. **Multi-sport participation is self-reported and unverified.** An athlete
   who ticks three sports gets an earlier specialisation gate and a lighter
   weekly budget, and nothing stops them ticking sports they do not play. The
   incentive is weak in both directions — the reward is a different drill mix,
   not points or a leaderboard place, and the lighter budget asks *less* of
   them — and a coach sees the list on the roster, which is the check that
   matters. But it is a self-report, and the gate treats it as fact.
12. **Seasons are a coarse proxy for training load.** Three seasons of
   recreational soccer and three seasons of travel soccer score identically,
   though they are not remotely the same week. Capturing sessions per week per
   sport would sharpen it, at the cost of a form a twelve-year-old will not
   fill in — which is the trade the season picker deliberately takes.
13. **Positions are modelled for lacrosse only.** Another sport gets honest
   silence — `for_sport` returns nothing, athletes fall back to the generic
   mix, and the join form falls back to free text. Adding a sport means adding
   its positions *and* the sport-specific drills their emphasis would point at;
   half of that is worse than neither, since a soccer emphasis built only from
   the general strength drills would recommend the same mix to every position
   on the pitch.
14. **The age bands are heuristics, not a clinical instrument.** They are drawn
   from general paediatric sports-medicine guidance and rounded to numbers a
   twelve-year-old can act on. They know nothing about the individual athlete's
   growth stage, injury history, or what else their week already contains, and
   they are not a substitute for a clinician. Treat `ATHLETEIQ_BUDGET_SCALE`
   as a program-level dial, not a per-athlete prescription.
15. **Handedness is inferred from wrist height**, which is reliable for standard
   lacrosse form and less so for unusual grips.
16. **"Before 8am" badges use UTC.** Athlete-local timezones are not stored yet,
   so that badge is wrong outside UTC. Noted in `store.py`.
17. **Single-process SQLite.** Fine for a program or two; a district-wide rollout
   wants Postgres. `store.py` is the only module to change. Schema upgrades run
   automatically on connect (`db.migrate`), probing the actual database rather
   than trusting a version counter.
18. **Auth is bearer tokens with no rotation or expiry.** Adequate for a pilot,
   not for a public launch.
19. **Revocation soft-fails by default**, though pre-fetched staples make strict
   mode practical — see **Stapling** above. Left soft by default because a
   deployment that has not set up the refresh job would otherwise start
   refusing webhooks; turn on `ATHLETEIQ_SNS_REVOCATION_STRICT=1` once
   `/api/coach/staples` shows them fresh.
20. **No TLS-level stapling on outbound fetches.** Python's `ssl` cannot read a
   stapled response, and doing it needs pyOpenSSL. It would only cover AWS's
   *TLS* certificate rather than the SNS signing certificate, so it was left
   out rather than added untested.
21. **No payment processor.** The billing model, entitlements, and invoicing are
   real; taking money is a `Gateway` implementation away, and nothing here has
   been through a PCI review.
22. **Offline slots are per-drill.** A drill you have never opened online has no
   banked slot, so its first-ever session needs a connection. The app says so
   plainly rather than failing silently.
23. **Web Push needs credentials.** Notifications generate and display in-app
   with nothing configured, but reaching a locked phone needs VAPID keys.
24. **Form quality is pose-only.** It reads how the body moved, not where the
   ball went. A wall-ball rep with perfect mechanics and a bad release still
   scores well, and stick position is invisible to it.
25. **Guardian identity is proven by the invite code alone.** There is no email
    verification, so a code handed to the wrong adult creates a valid account.
    Short expiry, single use, and revocation limit the window; real
    verification is a launch requirement.
26. **Roster import reads delimited text only.** CSV, TSV, and
    semicolon-separated files work; a native `.xlsx` has to be exported to CSV
    first. Direct TeamSnap/SportsEngine API sync is a separate integration.
27. **Load coefficients are reasoned estimates, not measured values.** The
    per-drill numbers in `catalog.py` are a defensible ordering rather than
    validated physiology, and the app sees only self-directed work — so the
    workload picture is directionally useful and absolutely not a clinical
    assessment.
