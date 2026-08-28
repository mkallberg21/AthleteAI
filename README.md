# 0FFDAYS

**On-device training analysis for youth athletes.**

> **On the name.** The brand is **0FFDAYS**, with a zero. The Python package is
> `offdays` and the environment variables are `OFFDAYS_*`, both with a letter
> O — not a stylistic inconsistency but a hard constraint: `import 0ffdays` is
> a syntax error and `0FFDAYS_DB=…` is not a valid shell assignment. The zero
> belongs everywhere a person reads it and nowhere an interpreter does. Please
> do not "fix" either one.

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
Ice Hockey and Rugby. Each ships with its own positions — 63 in total — and each
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
OFFDAYS_DB_PATH=data/demo.db uvicorn offdays.api:app --reload
```

Open <http://127.0.0.1:8000/> and sign in with a token the seeder printed.
Coaches land on the dashboard, athletes on the capture screen.

> **Camera access requires HTTPS** on anything other than `localhost`. Browsers
> refuse `getUserMedia` on plain HTTP, so a phone on your LAN needs a TLS
> terminator in front (Caddy, ngrok, or `mkcert` + any TLS proxy all work).

### Tests

```bash
python -m pytest tests/ -q          # 3427 tests

DRILL_SPECS="$(python -c 'import json;from offdays.drills import ALL_DRILLS;print(json.dumps([d.to_dict() for d in ALL_DRILLS]))')" \
  node --test tests/js/*.test.mjs   # 225 tests
```

The JS tests drive the counter with synthetic pose streams built from known rep
counts — that is how the detector is verified without a camera and a stick.

---

## Architecture

```
offdays/
  config.py         Scoring curves, integrity limits, retention, VAPID keys
  db.py             SQLite schema; tokens stored hashed, never in the clear
  drills/
    base.py         DrillSpec: the declarative counting contract
    catalog.py      The 33 shipped drills
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
  roster_sync.py    Keeping a roster in step with TeamSnap, SportsEngine, et al
  team_goals.py     One number a squad chases together, capped so nobody carries it
  absence.py        Holidays and tournaments: pausing a streak, not forgiving it
  injury_history.py Prior injury, and the one line it is allowed to move
  evaluation.py     The tryout artifact: participation and improvement, no volume
  i18n.py           Spanish on the consent, parent and recognition surfaces
  curriculum.py     The lacrosse IQ film syllabus, minus the videos
  adaptive.py       Athletes the camera was not built for, and what changes
  portability.py    The whole program as documented CSVs — the lock-in answer
  dialect.py        What a Postgres migration would actually cost, measured
  entitlements.py   The free/paid line, and why each free thing is free
  practice.py       The pre-practice card: who is not training, and why
  season.py         Where a program is in its year, and what that does to load
  technique.py      What a good rep looks like, per drill, per weak component
  parent_report.py  The monthly report a guardian gets about their own child
  digest.py         Weekly team KPIs and the coach email
  billing.py        Plans, seats, entitlements, invoicing seam
  recognition.py    Milestones, coach templates, and who signs them
  onboarding.py     Setup checklist derived from state, and what is blocking
  family.py         The household board, which is not a leaderboard
  mailer.py         Outbound queue: retries, suppression, unsubscribe
  webhooks.py       Inbound delivery events: verification, bounce handling
  sns.py            SNS certificate verification for SES notifications
  chain.py          X.509 path validation against pinned Amazon roots
  revocation.py     OCSP and CRL checking for signing certificates
  staple.py         Pre-fetched OCSP responses, refreshed off the request path
  assignments.py    Coach prescriptions and derived compliance
  notifications.py  Nudge generation, dedupe, and delivery channels
  leaderboard.py    Windowed boards, team standings, coach roster rollups
  store.py          The largest SQL surface (~39% of queries; see dialect.py)
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
  migration_scope.py      What a Postgres migration would actually cost
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
`OFFDAYS_STRICT_TEAM_SCOPE=1`, which makes an unassigned coach see nothing
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
ARN is checked against `OFFDAYS_SNS_TOPIC_ARNS`, and an empty allowlist
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
chain — do not depend on this one. Set `OFFDAYS_SNS_REVOCATION_STRICT=1` to
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
schedule — **`OFFDAYS_SNS_REVOCATION_STRICT=1` stops being an availability
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

### The household board

A club leaderboard works because forty athletes of roughly the same age are
already competing for the same places, and seeing where you sit is information
you were going to get anyway. A household is not that. It is a nine-year-old and
a thirteen-year-old, and ranking them against each other by reps says nothing
except which of them is older.

So a family does not get a leaderboard. Each child is measured against **their
own recent self** — this week's days against their own four-week average —
because that is the only fair comparison when the other competitor is their
sibling and four years behind them. No child's line ever mentions another child,
and there is a test asserting it.

Alongside sits one genuinely shared number: **days the household trained**.
Somebody trained on 6 of 7 days; everybody did on 3. That is collaborative
rather than competitive, and it is the thing a family can chase together.

```
The Pierces — 3 days this week everyone trained. That is the hard one.
someone trained 6/7 days · everyone 3 · together streak 3

Robin Pierce   (10)   3d this week   usual 0.5  ↑   streak 3
                      3 days in a row right now.
Jordan Pierce  (14)   6d this week   usual 0.5  ↑   streak 6
                      6 days in a row right now.
```

A parent can turn on a side-by-side, because parents know their own children and
some households genuinely thrive on it. **Even then it compares consistency and
form, never volume** — a younger sibling can win turning up and can win moving
well, and cannot win reps against someone four years older. A board that ranked
them on reps would just be telling the younger one their birthday again.

The streak shown here is the same number the athlete sees on their own screen,
recovery days and wellness check-ins included. Two different numbers for the same
word would be worse than not showing it — and saying you are sore must not cost
a streak on the family board either.

## Setting up a new program

A director who signs up lands on a dashboard of fifteen cards, fourteen of them
empty, with nothing saying which one matters first. Every feature works and none
of them is reachable, because the order is invisible: a team has to exist before
an athlete can join one, an athlete before a code can be handed out, and a code
before anything happens at all.

| | Step | |
|---|---|---|
| 1 | Create your first team | required |
| 2 | Add your athletes | required |
| 3 | Get one athlete training | required |
| 4 | Invite the parents | optional |
| 5 | Write one message in your own voice | optional |
| 6 | Add another coach | optional |

Step 3 is the one that earns its place: it is the only step that proves the
whole chain works — code handed over, app installed, camera pointed, session
counted. And it turns on a session that actually **counted**, so a recording the
integrity layer held for review does not tick it. There is a test for that.

**Every step is computed from the database, never from a flag saying somebody
clicked "done".** A remembered dismissal is a checklist that lies: it stays
ticked after the team is deleted, and it cannot tell a director who got half-way
and came back a week later where they actually are. A step un-ticks itself if
the thing it describes goes away — also tested, by deleting the team.

And it ends. Once the required steps are done the panel collapses, because a
setup guide that never leaves stops being a guide and becomes furniture.

A household gets a shorter list: no team step, because signing up creates one;
no staff or parent steps, because there is nobody to invite. It says "children"
rather than "athletes".

### A coach joining a program someone else built

A different job, so a different panel. The teams, athletes and roster already
exist — handing an assistant coach "create your first team" would be telling
them to redo work that is done.

**Nothing is required of them, and that is honest rather than an oversight.**
Everything that has to happen for an assistant coach to start is done by
somebody else. What they get instead is orientation and three optional steps:

| | |
|---|---|
| Make the milestone messages yours | *These go out signed with your name.* |
| Set some work for your team | |
| Clear the review queue | *only when something is actually in it* |

The first one matters more than it looks. Milestone messages to a coach's
athletes go out **automatically, signed by them** — a coach might otherwise
first learn this when an athlete thanks them for something they did not write.
The step ticks for the person who wrote it, not for the program, so a director's
wording is not this coach's step.

The review step is absent when the queue is empty, because a tick for having
done nothing teaches a coach the list is decorative. The count it shows is the
same query the review queue runs — a number on a checklist that disagrees with
the screen it points at is worse than no number, and there is a test asserting
they match.

### The finding this turned up

The blocker was going to say *"this dashboard is empty because it is scoped to
your teams"*. Writing a test that checked the claim showed it was **false**: an
unassigned coach falls back to seeing the *whole program*, which is a documented
accommodation for accounts predating team assignment, switchable with
`OFFDAYS_STRICT_TEAM_SCOPE=1`.

The two cases are opposites, so the message branches:

| Scoping | What they are told |
|---|---|
| Default | **You can currently see the whole program** — not assigned to a team, so this shows every athlete rather than yours. Ask a director to assign you. |
| Strict | **You are not on a team yet** — nothing is broken; this is empty because it is scoped to your teams, not because the program is. |

Telling someone their dashboard is empty while they are looking at four hundred
children would have been worse than saying nothing at all. Both branches are
tested, and the default one asserts the athlete count matches the roster they
can genuinely see.

### What a new athlete sees

Shorter, on purpose. Someone setting up a program will read six steps; a
twelve-year-old who wants to go outside will read one — so there is exactly one
required step, and it is **record a drill**.

| | Step | |
|---|---|---|
| 1 | Record one drill | required |
| 2 | Put it on your home screen | optional |
| 3 | Say how you feel | optional |
| 4 | Watch one clip | optional, *only if the program has curated any* |

The film step is absent where a program has curated nothing, because telling a
kid to watch a clip that does not exist is a step they cannot take. The install
step is left for the browser to answer — only it knows, so the server reports it
undone rather than guessing, and the client fills it in from `display-mode`.

Above the steps, once and never again, is the thing that makes an athlete and
their parent comfortable — said before anybody points a camera at a child:

> Your phone watches you and counts the reps. The video never leaves it — not to
> us, not to your coach. What they see is the numbers.

### The same gate, in the second person

The consent blocker appears here too, worded for the person who cannot record
rather than about them:

> **Waiting on a parent** — Recording is paused until a parent or guardian says
> yes in their own portal. Nothing is wrong and nothing is lost — give them a
> nudge and everything here switches on.

The athlete already meets this at the moment they press start. Saying it on the
home screen means they find out *before* choosing a drill and being refused,
which is the difference between "waiting on my mum" and "this app is broken".
A test asserts the coach's version names the athlete and this one does not.

### What a new parent is asked

Shortest of the three, and short for a different reason. A director has a
program to set up and an athlete has an app to try; a parent's job here is not
to set anything up at all. It is to make **one decision that is genuinely
theirs**, and padding that with tasks would dress a consent screen up as a
product tour.

| | Step | |
|---|---|---|
| 1 | Decide whether *{name}* can train | required |
| 2 | Choose how they appear on team boards | optional |

Asked **per child**, not per account: a guardian with two children can easily
have decided for one and not the other, and the one still waiting is the one who
cannot train.

### Answered is not the same as granted

The distinction that shapes this whole panel. `current_consents` collapses
"never asked" and "asked and said no" into the same `False` — correct for
enforcement, wrong here. **A parent who said no has decided**, and a checklist
that keeps asking after an answer is not respecting it. So a declined consent
marks the step done and the panel goes quiet.

What does *not* go quiet is the consequence, which is reported separately:

> **Robin Pierce cannot train yet** — Training is paused until you allow it.
> That may be exactly what you intended — if not, the switch is on their card
> below.

Deciding and allowing are different things, and only the second is what the
athlete is waiting on. Tested both ways: saying no completes the decision *and*
leaves the child listed as blocked.

Alongside sits what a guardian can always do — withdraw any permission, download
everything, delete it all, and see every message their athlete is sent.
**Stated, not made into steps.** None of it is a task to complete and all of it
is worth knowing on day one, because it is the difference between granting a
permission and handing something over.

### The gate that surprises people

Separate from the steps is a **blockers** panel, because these are not setup —
they are breakage, and they turn up long after onboarding is finished.

The one that matters is the consent gate. Enforcement begins the *moment a
parent is linked*, so a director who invites parents on Monday finds their
athletes locked out on Tuesday. The athlete sees a clear message; the coach used
to see nothing at all and had to work it out. Now:

> **3 athletes waiting on a parent** — Jordan P., Sam R. and Alex T. cannot
> record anything until their parent accepts in their own portal. Nothing is
> broken — this is the consent gate doing its job, and it switches on the moment
> a parent is linked.

Naming it before it bites is most of the value in this whole module.

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

### Recognition in a household

A family gets a **different set of shipped words**, not the coach set with the
nouns swapped. "See you at practice" and "the thing that separates players" are
things a coach says; a parent saying them sounds like a parent trying to talk
like a coach, and a child hears the difference.

| | |
|---|---|
| Coach | *"{first_name}, ten days straight. That is real work and it will show up on the field. Proud of you."* |
| Parent | *"Ten days straight, {first_name}. Nobody made you do any of them. That is the part that counts."* |

A test asserts no family default contains "practice", "squad", "team", "coached"
or "players" — the tells that give away borrowed language. Both sets are still
placeholders a writer should want to replace.

**A preview, rendered by the server.** A parent writing to their own child has
no coach to notice the wording came out wrong, so the editor shows exactly what
lands — filled with their actual child's name and their own, through *the same
function that sends it* rather than a copy of the token logic in the browser.
That is what stops a preview and the real message quietly drifting apart, and
there is a test comparing the two.

```
Preview
  "Dana Pierce noticed"
  Jordan, 10 days and nobody made you. Love, Dana Pierce
  (as Jordan will read it)
```

**And what actually went out.** A coach can ask their athletes how a message
landed; a parent writing these for their own children is often the only person
who would ever check. So the dashboard lists the messages as sent, to whom, and
from whom — the athlete's own copy rather than a guardian's, so a household with
two parents linked does not read as two messages.

The senior-voice control stays hidden for a household, because there is no chain
of command in a family to be higher up.

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

### What a family inherits for free

Because a family is a program with one household in it, the features written
for a club work for a household without a second code path. **Wellness, injury
reporting and return-to-play have no family-specific view and do not need one** —
verified end to end rather than assumed:

| | |
|---|---|
| Parent (as coach) sees the report | ✓ |
| Parent (as guardian) gets the escalation alert | ✓ |
| Parent can clear a head or neck return | ✓ — they *are* the guardian the rule requires |
| The athlete's private note stays out of the coach view | ✓ |
| ...and is readable in the parent portal | ✓ |

Two rough edges, deliberately left rather than overlooked. The private note
lands in the right place by a slightly odd route: hidden from the dashboard by
design, visible in the parent portal because that parent is the guardian — so a
household switches screens to get the whole picture. And the coach-side wellness
copy still reads for a club ("goes to them and their parent or guardian, and not
here"), which is odd when the parent is both. Neither is broken; both are
wording, not behaviour.

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

### What a parent sees of the clips

A parent could already turn video sharing on and off and had **no way to see
what it produced** — which made the consent a switch in the dark. The point of
asking someone to allow something is that they can then look at what they
allowed.

The parent portal now shows every clip their athlete sent, with the note the
athlete attached, who has watched it, and the date it deletes itself. Any of
them can be taken back on the spot. A parent can watch too, and **that view is
logged and shown to the athlete** like any other — a teenager who can see that a
coach watched should be able to see that a parent did. The audit trail is for
them, not only about them.

With sharing switched off the panel says so plainly rather than looking broken,
and with it on but nothing sent it says that instead — because "nothing here"
should never be ambiguous about whether the feature is off or simply unused.

### In a family, the parent is the coach

Which changes the wording, not the gates. The consent reads *"Let clips your
athlete sends reach your dashboard"* rather than *"Let a coach watch"* — in a
household the person granting the permission and the person who would watch are
the same, and a consent screen describing somebody else's situation is not
informed consent. The coach-side card is reworded the same way, since a family
parent is reading it about themselves.

Everything else holds exactly as it does for a club, deliberately:

- **The child still chooses each clip.** Being their parent does not remove
  their say in it, and there is a test asserting a completed session still
  uploads nothing.
- **The consent is still a real decision**, because the clip still leaves the
  phone and lands in a database — with the backup and breach exposure that
  implies, parent-owned or not.
- **Withdrawal still deletes**, and every view is still logged.

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
clinical instrument, and a program can scale them with `OFFDAYS_BUDGET_SCALE`.

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

Eighty drills: twenty-one bodyweight movements that work for any sport —
squats, lunges, glute bridges, push-ups, pull-ups, planks, side planks, hollow
holds, wall sits, dead bugs, mountain climbers, burpees, squat jumps, tuck
jumps, lateral bounds, high knees, jumping jacks, sit-ups, calf raises, wall
handstands, dead hangs — and skill work for the eight sports built out so far:
lacrosse (11), basketball (9), soccer, volleyball and tennis (7 each), hockey
(6), football (5), and baseball and softball (7 between them, sharing
everything except the mound).

**A drill only pays for what the camera can confirm.** Every skill drill has an
unambiguous pose signal, and where several drills share one signal their
thresholds have to separate them physically — a catalogue-wide guard fails the
build if doing drill X necessarily satisfies drill Y's thresholds while Y pays
more. It has fired across sports three times, most recently when a bat swing's
reach band swallowed a goalie's save.

Everything is driven by the calibration harness, which has caught several real
errors: mountain climbers declared at a `target_rom` of 0.33 when a textbook rep
measures 0.42, a softball windmill's range guessed at 1.30 against a real arc
nearer 1.60, and squat jumps smoothed so heavily they counted one rep in
twenty-four. The harness used to skip any drill with no calibration sweep,
silently, so a newly added drill was unguarded and looked green; it now fails
instead. It also used to drive every drill at one rep a second regardless of the
drill's own refractory window, which meant the slow drills were driven faster
than they are allowed to count — two of them turned out to have had their
`target_rom` fitted to that distorted signal.

**Gymnastics, cheer and dance get conditioning and nothing else, deliberately.**
They are judged on how the movement looks, and a number on a child's line about
how their body looked is the most dangerous thing this product could produce. So
nothing scores a tumbling pass, a stunt or a combination — but their position
plans, their film syllabus and the three newest drills are all built for them,
because getting stronger is measurable and is most of what a solo hour in those
sports should be. The last three general drills came out of that build: the
catalogue had eighteen bodyweight movements that between them never measured an
ankle, never went overhead and never asked anybody to hang.

The remaining four — rugby, track, cross country and swimming — get positions,
benchmarks, load monitoring and the bodyweight catalogue, and are honest about
having no skill drills rather than being handed another sport's with the labels
changed.

### Position benchmarks

Three problems sit between a `position` column and a useful benchmark, and the
first two are the ones usually skipped.

**Sixteen sports ship with positions.** Lacrosse, Basketball, Soccer,
Volleyball, Baseball, Softball, Cheer, Dance, Swimming, Track & Field, Football,
Gymnastics, Tennis, Cross Country, Ice Hockey and Rugby — 63 positions, each
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

## Roster sync

A CSV upload is a snapshot. The friction that kills a pilot is not the first
import — it is week three, when two players join and nobody remembers to
re-export. So a team can be connected to whatever system its roster already
lives in, and stay current on its own.

Adapters ship for **TeamSnap** and **SportsEngine**, plus a generic
export-link provider so a league product nobody here has heard of still works
if it can produce a CSV at a URL. Synced rows are rendered back to CSV and fed
through the same forgiving parser the upload button uses, so there is one
import path rather than two that drift.

**Honesty about what is tested.** There are no TeamSnap or SportsEngine
credentials in this environment, so those two adapters are written against
published API shapes and have never been run against a live account. They
carry `verified=False`, the coach UI says so in as many words, and tests
assert they keep saying so. Only the export-link provider is genuinely
verified end to end.

Two decisions are load-bearing. The credential is **write-only above the
store** — it goes in, the sync uses it, and no dashboard, API response, or log
reads it back, because it reaches into a system holding children's contact
details. And **departures are reported, never applied**: a child missing from
a team-management app has not left the program, and that is a call for a
person. A drop of more than half the roster refuses outright, because a wrong
team id and a real exodus look identical from here and only one of them is
plausible. Auto-sync stays off until a run has actually succeeded — putting a
wrong team id on a nightly schedule is how it stops being noticed.

---

## The pre-practice card

A coach standing on a field with a whistle in one hand and a phone in the
other will not open five tabs. They have time for one card, read once, and
what they need from it is not a report — it is the short list of decisions
they have to make differently in the next hour: who is not training, who is on
modified work, who is worth an eye, and what the squad has not got through.

It composes the coach views that already exist rather than deriving its own
numbers, so it cannot drift from the screen the coach opens next. It stops
naming people after six and counts the rest, because a card that lists
everybody is a card nobody reads — and a card nobody reads is worse than none,
since it looks like diligence.

**An athlete on a hold or a ramp never appears on the behind-on-work list**,
and is out of its denominator too. A naive join of "who is behind" with "who
is on the roster" tells a coach to go and push the child who is hurt: the
exact wrong instruction, delivered at the exact moment they are deciding what
to make them do. Most of that file's tests are about this one property.

Building it turned up a bug in the harmful direction: the headline counted
only the six people the card had room to show, so two athletes who needed
modified work were reported as merely worth an eye. Counts now come from
everyone.

---

## Season phases

The age bands know how old a child is. They do not know whether it is
February, and that changes the answer more than a birthday does. A program
picks a phase, and it scales the weekly self-directed budget.

| Phase | Scale | Why |
|---|---|---|
| Off-season | ×1.25 | Nothing on the team calendar, so their own work has room |
| Pre-season | ×1.0 | The published budget, unmodified. The default |
| In-season | ×0.6 | Practices and games already fill the week |
| Post-season | ×0.4 | A deliberate break, and the lowest of the four |

**In-season the budget goes down, not up.** That is the opposite of what a
training app usually does, and it follows directly from what these numbers
have always meant: work *on top of* team practice. A child in-season already
has three practices and a game in their week, and holding a full off-season
target on top of that is not ambition.

Post-season is lower still, and the wording changes with the number. Scaling a
budget down and then nudging a child to fill it anyway gives away the whole
point of having a break, so the two branches that ask for more work go quiet —
a blank week in November reads *"enjoy the break"* rather than *"nothing
logged this week"*. The ceiling stays, though: a child training through their
rest period is exactly who that message should still reach.

The phase is **chosen, never inferred**. Sports do not share a season, a club
may run two, and a wrong guess silently changes what every child in the
program is told to do. Directors only, for the same reason. The squad roll-up
takes the same scale as the athlete's own screen, so a coach counting "over
budget" is counting against the number the child was shown.

---

## Technique references

Form scoring could already tell a child their range was short. It could not
tell them what *not short* looks like, and a score without a fix is a mark out
of ten — which is the thing this product is otherwise careful not to hand a
twelve-year-old.

Every one of the 34 drills has cues written for it, keyed to the same
component keys the scorer emits. `quality.weakest` is recorded on the report
rather than re-derived by the caller, so the fix a child reads is always about
the thing that actually scored lowest; a note and a fix disagreeing about what
went wrong would be worse than no fix. Generic fallbacks exist for every
component but are flagged `bespoke: false`, because "go deeper" is not advice
and should not be dressed as coverage.

The reference itself is **generated from each drill's own thresholds rather
than filmed**. That sidesteps the third-party embed problem film study carries
— an ad before a drill, a sidebar of recommendations, a way out of the app, in
front of a child mid-session — but the better reason is that a generated
reference is built from the same numbers the scorer marks against, so it
cannot drift out of agreement with the score. A clip shot once and a threshold
tuned later disagree silently, and the child pays for that. Tests assert the
demonstrated tempo sits inside each drill's own scoring band and that every
trace reaches the target it is demonstrating.

A program that films its own can drop a file in `web/static/technique/` and it
is offered alongside the trace. Nothing is shipped, and `has_clip` is read off
the filesystem, so it cannot claim a clip that is not on the server.

---

## The monthly parent report

The weekly team digest names nobody on purpose — it gets forwarded, pasted
into team channels, and read aloud in car parks. The monthly parent report is
the opposite object: one household, one child, and naming them is the point.
That inversion is why it has its own rules rather than being a filter over the
digest.

**No child is compared to another.** Not a rank, not a percentile, not "above
average for the squad". This product refuses volume comparison between
children everywhere else, and a parent report is both the easiest place to
quietly drop that refusal and the most damaging place to drop it — it is the
document held up at a kitchen table next to a sibling's. What a child is
measured against is their own last month and their own age-band budget, both
of which a family can act on.

**A quiet month is honest and kind.** Two sessions with exams on is a fact,
not a failing. Writing those tests caught the first version swallowing a real
drop in order to stay gentle: twelve sessions down to two came out as "a few
sessions, which some months are". A big drop is now named in the quiet branch
too, because a report that softens away the truth is not one a parent should
be paying for. The subject line names the child and the month and never the
session count — a notification preview is the last place a parent should first
read a verdict.

**Nothing in it is a medical claim.** Soreness appears as what the app did
about it, never as an injury a parent is being informed of by software.
Anything needing a grown-up reached that household the day it happened, and a
monthly summary arriving as the first anyone hears of an injury would be a
serious failure. It is not mirrored into the child's own alerts either: it is
written for an adult, about them, and reads that way.

---

## Team goals

Every other board here ranks individuals. The household board already showed
the better pattern for a group that should not be ranked — one shared number,
chased collaboratively — and the digest already leads on participation because
it is the only metric whose marginal contributor is the athlete you want to
reach.

The shape is the design. **A goal counts athletes who each clear a small
personal bar**, so contribution is binary and capped: the keen one doing six
sessions moves it exactly as much as the quiet one doing three, and the only
way it goes up is somebody new turning up. A goal denominated in reps or XP
would do the opposite — let one athlete carry the squad, teaching everyone
else they are not needed, and make a quiet one visibly the shortfall. That is
a worse object than the leaderboard it replaces, because a leaderboard at
least does not frame a child as the reason their team failed.

**Nobody is ever named** — not who is in, not who is not, and deliberately not
a *count* of who is not, because a shortfall count on a ten-person squad is a
name with the name removed. An athlete sees their own standing and the squad
total; a coach sees the squad total and uses their roster for names. The
near-miss copy is the whole point: *"one more day and you are in"* is small,
achievable, and aimed exactly where a participation metric should aim.

An athlete on a hold or mid-ramp leaves the denominator rather than counting
as missing — the same rule the pre-practice card uses.

---

## Planned absence

Streaks forgive one missed day, which covers a bad week. They do not cover a
family holiday or a tournament weekend, and those are predictable — which
makes losing a streak to one a churn moment the product walked into with its
eyes open.

There are two ways to build this and only one is honest. Counting absence days
as active days is easy and turns a fortnight away into twenty-one days of
streak, which describes nothing the child did; a number nobody believes is a
number nobody protects. So **the days are removed from the timeline instead**.
The gap either side closes and the athlete comes back to exactly the streak
they earned — eight, not twenty-two, in the test that pins it. They do not
gain, they just do not lose.

**A parent or a coach sets it, never the athlete.** A child who can declare
their own absence has a button that undoes a missed day, and a streak with an
undo button is not a streak. Windows are capped at a month, cannot start more
than a week back, and cannot be booked a year out — each of those, unbounded,
is the undo button wearing a hat.

The nudges go quiet too, which is half the value: *"train today or lose it"* is
exactly the message a booked holiday exists to stop sending.

---

## Injury history across seasons

Prior injury is among the strongest predictors of the next one, so an athlete
who ramped back from an ankle in March should not start August on the same
thresholds as a teammate who never has.

**It moves the caution line and nothing else.** A prior injury pulls the point
at which this app raises a question down on the tissues involved. The stop line
is deliberately untouched — moving it would mean a child with a history is told
to stop on a week their teammate is told is fine. It never blocks training and
never shrinks a budget. Influence decays with time and does not stack: three
ankle niggles in a year is not three times the risk of one, and a scheme that
added them up would eventually tighten a child's thresholds until the app told
them to stop moving.

**A coach does not get an injury history.** This is the line everything else
rests on. They already see what an athlete is carrying *today*, because that
changes today's session. A career count changes nothing about today's session
and would change a tryout — and a child who learns that reporting pain costs
them a place stops reporting pain, which takes the whole wellness subsystem
with it. Tests assert nothing derived here reaches the coach roster, the
pre-practice card, or the evaluation export.

Building this found a real defect: completed return plans were never purged at
all, despite the wellness module stating plainly that health data about a minor
is not kept indefinitely. They now have a bounded two-year horizon — long
enough to inform the season after the one it happened in, and no longer.

---

## The evaluation export

Coaches will use this data at selection whether or not anybody designs for it.
The realistic choice is not whether that happens — it is between shipping
something deliberate and leaving a coach to screenshot a leaderboard, which is
the worst version: ranked by volume, with a child's name at the bottom.

**Volume is not in it.** Not reps, not XP, not minutes, not session counts.
Volume mostly measures opportunity — a garage, a wall, and a lift to practice —
and none of that is about the athlete. A test gives one athlete five times
another's work and asserts the two rows come out identical. What is in it,
turning up and getting better, is what a child controls.

**It is not sorted by anything measured.** Alphabetical, always: a list ordered
by form score reads top-down as best-to-worst whatever the header says, and a
composite number is a ranking with one column.

A blank form score is stated rather than left to inference. An athlete whose
technique is not scored — because the camera could not read the movement, or
because our analysis does not fit how they train — would otherwise show twelve
weeks of training against an empty form column, and on a tryout document that
is a signature for exactly the children who must not be identifiable there.
The sample count is not published, the row is byte-identical to a camera
failure, and the file itself tells the coach what a blank means and asks them
not to draw the inference. It cannot be made perfectly non-inferable without
fabricating a score, which would be far worse.

The hard part was the collision with the injury rule. An athlete who missed six
weeks hurt has terrible participation and a selector must not be told why —
hiding it makes them look lazy, showing it leaks health data at the exact
moment somebody decides who to cut. The answer is neither: **weeks an athlete
was told not to train, or was away with permission, leave their denominator.**
Six of twelve weeks becomes six of seven, the rate is fair, and nothing in the
rows says the word *ankle*.

The caveats ride in the CSV as comment lines rather than living in the web
page, because the file is what reaches the selection meeting.

---

## Spanish

A meaningful share of youth-sports families in the United States speak Spanish
at home. The places that matters are not the leaderboard or the drill picker —
a child navigates those from icons and numbers regardless. They are the
**parent portal, the consent flow, and the messages a coach sends home**: the
surfaces where a guardian is asked to understand something and then agree to
it. A consent screen somebody cannot read is not consent, and that is the whole
argument.

**The language belongs to the person, not the program.** A Spanish-speaking
household inside an English-speaking club is the common case, so the preference
is per user — a guardian sets their own, and a Spanish-speaking parent of an
English-preferring teenager is an entirely ordinary household.

`scopes_for` is where consent copy is built, so translating there rather than
at each call site is the difference between a rule and an intention. Every
consent surface inherits it.

**We translate what we ship, not what a coach types.** The shipped recognition
bodies have Spanish versions, including the separate warmer parent-voice set. A
coach who rewrites one in English produces English: there is no translation
service in this application, and inventing one silently would be worse than the
gap. The payload carries a `translated` flag so the parent view can say which
case it is in rather than leaving a reader to wonder.

Register is *usted* throughout for guardians, which is what US Spanish-language
school and club communication uses, with neutral vocabulary over regional.
`i18n.missing()` reports untranslated keys, because a half-translated language
is a promise the product does not keep and the gap should be visible rather
than turning up on a consent form.

> **These translations are not certified.** They were written for this codebase
> rather than by a professional translator, and the consent copy is legally
> adjacent. A program relying on it should have a native speaker review it
> first.

---

## Adaptive athletes

Pose estimation assumes a body with two arms, two legs, and a typical range of
motion at every joint. That assumption runs through every layer here: the
counter reads joint angles, form scoring marks a rep against a target range,
the off-hand comparison assumes two sides that should match, and the integrity
layer treats an unusual movement pattern as evidence of cheating.

For an athlete who moves differently, each of those becomes a small insult
delivered by software. **Saying nothing is not neutral** — a product that
scores an adaptive athlete as a deficient typical athlete has taken a position
and simply not admitted to it.

**The framing is deliberate.** This is not a disability flag and it records no
diagnosis. It records that *our camera analysis does not fit how this athlete
trains* — a limitation of the tool, stated as one. Tests assert that no option
or piece of copy uses clinical language, and the sentence an athlete finds on
their own settings screen is about the app's limits and ends *"not of you"*.

| Accommodation | What changes |
|---|---|
| Do not score technique | Form scoring goes **silent, not to zero** — 34/100 against a range their body does not have is worse than no score |
| Do not compare sides | The off-hand gap disappears from their screens and their coach's |
| Own history only | Peer benchmarks drop to their own trend; they are not a poor version of a pool that is not theirs |
| Let them log a session | Work the camera could not count still happened |

**Integrity never auto-rejects them.** Any accommodation at all buys this, and
it is not separately switchable. Where the usual rules would reject, the
session is held for review instead — the score untouched, with a note saying
why so a coach reading the queue is not guessing. A held session gets a person;
a rejected one gets a child told by software that they cheated, and that must
not happen because a movement looked unfamiliar.

Self-reported sessions are marked for ever, earn flat XP that does not scale
with the reps claimed, and stay out of the reps board — nobody has an incentive
to overstate a number that only tightens their own load advisories, and a
strong one to overstate a number on a board. Their reps *do* reach their own
load history, because overuse protection matters most for an athlete whose
training this app structurally cannot see.

The honest limit: this makes the product usable and fair. It does not make the
pose counter work for a movement it cannot see, and no setting can.

---

## Program export, and the lock-in question

A cautious director asks it and is right to. The answer is an artifact rather
than a promise: a zip of documented CSVs they can take to a competitor, a
spreadsheet, or their own analyst.

Three things make it portability rather than a checkbox. It is **complete** —
every table a program owns, because an export that drops the inconvenient parts
is the lock-in it claims to answer. It **documents itself from inside** — a
README travels in the archive naming every file, column and unit, since an
export whose meaning lives in our documentation stops making sense the day a
program leaves. And **the roster comes back in**: `athletes.csv` is written in
the shape our own importer reads, and a test re-imports it and asserts it
updates the same squad rather than duplicating it. If it parses here it parses
anywhere.

What is left out took more thought than what is in. **No wellness or injury
records** — the one that would be wrong by default. A guardian can already
export their own child's complete record and that is their right; a director
exporting the program does not get a bulk health file on every child in the
club. The whole wellness subsystem rests on a child believing that saying *"my
knee hurts"* does not travel. **No credentials** either: token hashes, claim
codes and provider tokens are keys to accounts rather than program data. The
README inside says both, and says why.

That exclusion is enforced structurally rather than by inspection. Each export
table carries the query that produced it, and tests assert those queries read
nothing outside a named allowlist — the same discipline the binary-column
privacy guard uses, so a table added next year is excluded by default and
somebody has to add it in a diff with a test asking them why. A further test
scans the schema for anything that looks like health data and fails if it is
not on the list of things known to be excluded. `adaptive_profiles` is on that
list deliberately: it records what our tool cannot do rather than anything
clinical, but a downloadable list of which children have accommodations is the
same object by another name.

None of this hides anything from the family it belongs to — a guardian's own
export still carries their child's complete record, and a test pins that too.

---

## What a Postgres migration would cost

This README used to say `store.py` was "the only module that speaks SQL", and
an outside review repeated it back as a reason a district-wide migration would
be cheap. It was not true. **Twenty-four modules execute SQL across 371 call
sites, and store.py holds 39% of them** — an estimate built on that sentence
would have been wrong by a factor of two and a half.

So the inventory is now measured rather than remembered. `dialect.py` scans for
every SQLite-specific construct and reports where it lives; `scripts/migration_scope.py`
prints it; and tests assert both that the README matches the code and that the
tool is not over-counting itself.

```
SQL lives in 24 modules across 371 call sites.
store.py holds 39% of them.

866 occurrences are mechanical (search-and-replace with tests behind it).
55 need judgement.
```

The judgement work is the real cost: `lastrowid` has to become `INSERT ...
RETURNING` threaded back through nineteen call sites, `INSERT OR REPLACE`
fires different cascades than `ON CONFLICT DO UPDATE`, and the SQLite date
functions sit inside comparisons where a timezone assumption changes what a
child is told about their training week.

> **This scopes the migration; it does not perform one.** No Postgres driver is
> installed in this environment and nothing has been run against a server. A
> blind port of a working, heavily-tested system against a database you cannot
> run is how a silently wrong query about a child's training load ships.

---

## How this is sold

**The club buys a seat for every rostered athlete — $25 per athlete per
season — and covers it by adding a line to its own season fee.**

The money still comes from parents, but through the channel they already pay
through, at the moment they are already paying. No second checkout, no
chasing, no coach explaining a subscription. And every athlete is covered, so
coverage is never partial and a coach's view is never a function of who bought
what.

### What a 200-athlete club sees

| | |
|---|---|
| We invoice the club | **$5,000** / season |
| Club adds to dues | $40 / player → collects $8,000 |
| Club margin | $3,000 |
| Sponsorship rebate (7.5%) | $375 |
| **Into their scholarship fund** | **$3,375** |
| **Out of the club's own budget** | **$0** |

A director is not being asked to find budget. They are shown a line that funds
their own scholarship fund. The $40 is a recommendation, not a rule — it is
about two per cent of a season fee that runs into four figures, and the club
sets its own number.

### The rebate is a fund, not a discount

5–10% of what a club pays comes back, earmarked for families who cannot afford
the season at all. It is **accrued as a ledger with a balance**, not netted off
the invoice, and that is deliberate: a discount disappears into a smaller
number nobody looks at, while a fund is something a director can point at in a
board meeting and spend on a named family. Spending it records what it went to,
because a director will be asked.

The rate is a commercial lever within a bounded band. What is *not* negotiable
is what it is for — it is the club's scholarship money, not a volume discount
in disguise.

### Late joiners are prorated

A player who turns up in week ten costs a fraction of a season. A club billed
in full for a late joiner will stop adding late joiners, which turns a billing
rule into a reason to leave a child off a roster.

### One price for a paying club

The seat-metered tiers — Team at $49/mo, Program at $149, Club at $399 — are
**retired**. They stay resolvable so clubs already on them keep working, and
they are offered to nobody.

The reason is worth recording, because it is the second time the same mistake
appeared in this pricing. A sponsorship SKU was priced *above* the seat plans
and would never have been chosen. The seat plans were then priced 3.4× to 7.5×
*below* per-athlete, and would have won every time:

| Club size | Roster plan @ $25 | Old seat plan |
|---|---|---|
| 40 | $1,000/season | $245 (Team) |
| 200 | $5,000/season | $745 (Program) |
| 600 | $15,000/season | $1,995 (Club) |

A price that always loses to another price you publish is not an option — it
is a trap for whoever reads the pricing page carefully. There is now exactly
one plan offered to a paying club, and a test asserts it.

### If a club will not buy

`club_free` remains: the club pays nothing, and parents who want the
parent-facing product buy it for their own child at $29 a season ($19 sibling,
free from the third, $48 household cap). A club buying for its whole roster
pays less per head than a family buying alone, which is the right direction —
a club committing its entire roster with no acquisition cost should not pay
more than one family.

That tier is where the free/paid line matters, and the line is drawn by **who
consumes a feature**, never by how valuable it is.

| Free for ever | Why |
|---|---|
| Training, streaks, XP, badges | A child can always train. An adult's payment problem is not a reason to lock a fourteen-year-old out |
| Everything a coach sees | Roster, assignments, compliance, pre-practice card, digest, evaluation export — if coverage could break a coach's view, a club at partial adoption would drop the product |
| Soreness, injury, return-to-play, load | Charging a family for injury prevention for a child is indefensible, and an unpaid child who stays quiet is the outcome |
| Adaptive accommodations | Charging for accessibility is indefensible |
| Technique cues and reference | Form scoring without the fix is a mark out of ten. Charging to say *how to be right* is the worst thing that could go behind this paywall |
| Consent, export, erasure, guardian alert copies | Rights, not features |

What a parent buys is the parent product: the monthly report, history beyond
30 days, peer context, film study, coach video review, and other-sport
tracking.

### Hardship, and who is allowed to know

A parent can grant themselves the full parent product free, in one click, with
**no coach involved and nobody notified** — a family that has to ask their
child's coach for a discount is a family that will not ask.

And **no coach-facing surface reveals which families pay.** Not a badge, not a
count, not an ordering. This matters less under the roster plan, where
everyone is covered, and the guarantee holds anyway because a club can move
between plans mid-season. Tests assert the coach roster, the pre-practice card
and the evaluation export carry no billing signal, and that no coach-facing
module even imports the entitlement layer.

### What lapsing costs a child

Nothing. Training, safety, consent and everything a coach sees carry on
untouched; the parent product goes dormant. Nobody is told, least of all a
coach.

---

## Diagnosing a drill without sending video

The normal way to debug a detector is to send the developer a clip. This
product cannot do that: footage of a child training never leaves their phone,
and that is enforced by tests rather than policy. So the diagnostic is
**numbers instead of pixels**.

Open the capture screen with `?debug=1` and a panel appears under the drill
hint showing the live signal, both thresholds, and whether the counter armed.

```
raw 143.2   smoothed 138.7   state ARMED   reps 6
excursion 61.4   needs 60.0   confidence 94%   frames 812
gen_squat · joint_angle · deg · arm 100.0 → fire 160.0
```

The trace underneath is the part that replaces a video. A rep either crosses
two thresholds or it does not, so the signal is drawn against both lines —
raw behind in grey, smoothed in front, a tick wherever a rep fired. One glance
answers *why is it not counting*:

- **Smoothed never reaches the arm line** → the athlete is not going deep
  enough, or the threshold is wrong for their body.
- **Raw crosses but smoothed does not** → smoothing has flattened the
  excursion; the constant is too aggressive for this movement.
- **Excursion smaller than "needs"** → the drill *cannot* fire as configured.
  That is a threshold bug, not an athlete problem.
- **Ticks missing where reps happened** → refractory period or hand
  attribution.

**Copy diagnostics** puts the same thing on the clipboard as text, including
the last 60 signal samples, which is exact where a screenshot is approximate.

Two properties are enforced structurally, because this is the substitute for
sending video and would be a particularly bad place to grow a way of sending
some. Tests assert the diagnostics block contains **no network path** — no
`fetch`, no `sendBeacon`, no URL — and **never reads pixels**: no
`getImageData`, `toDataURL`, `toBlob`, `drawImage` or `captureStream`. Both
guards were verified to fail when a violation is planted.

It is **off unless asked for**, partly because it is noise to an athlete and
mostly because a child who found it would learn exactly which number to game.

---

## The lacrosse IQ curriculum

The film module shipped empty for the life of this product. The machinery to
teach the half of the game learned by watching — reading a slide, seeing a cut
two passes early, knowing where help is coming from — existed, and nothing had
been loaded into it.

`curriculum.py` is twenty topics of lacrosse IQ: what to teach, at what age, to
which positions, how long the cut should be, a note on what footage to look
for, and a comprehension question with the reason its answer is right. Every
position is covered, including goalie and face-off.

**It deliberately ships no video links.** Picking real clips means watching
them, and a catalogue of plausible-looking YouTube ids that turn out dead,
wrong, or somebody's unrelated highlight reel would be far worse than an empty
shelf — it would look full. A coach supplies the id per topic; that is a few
minutes each against an evening of writing the questions. Loading is
idempotent, so five links today and the rest next week adds five clips rather
than duplicating the syllabus, and a topic with no video simply does not
become a clip.

### Length is a hard cap, not a suggestion

`film.py` filters out any clip longer than its age band's ceiling, so a clip
over it is silently never shown. That constrains the syllabus more than it
first appears:

| Band | Ceiling | What fits |
|---|---|---|
| Under 11 | 75 s | Short fundamentals only |
| 11–12 | 100 s | Short fundamentals only |
| 13–14 | 140 s | Up to 2:20 |
| 15–16 | 170 s | Up to 2:50 |
| 17–18 | 200 s | Up to 3:20 |
| 19+ | 240 s | Up to 4:00 |

So a four-minute clip is visible only to adults. The syllabus therefore sits at
two to three minutes for 13+ and 15+, where the athletes actually are, with a
short fundamentals set cut under 75 seconds so under-11s get something rather
than an empty module. A test asserts every topic's target length is inside the
ceiling for its own minimum age, and another asserts nothing has drifted to
19-and-over.

---

## The face-off clamp

Face-off was a position with no position-specific work — a FOGO's whole craft
happens in the first half second of a whistle, and the plan was wall ball and
push-ups.

`lax_faceoff_clamp` is the first drill that addresses it: from the down stance,
clamp, rip, come up to ready, reset. It is the only drill in the catalogue
where **tempo outweighs range**, because a face-off is decided on speed rather
than on doing a movement fully, and the face-off position now leads on it at
24% of its plan.

**What it measures is the hand snap, not the clamp.** The clamp is a wrist
rotation around a stick the camera does not know exists; what pose can see is
the vertical travel of the hands from the ground back to ready. So the drill
scores how fast and how repeatably the hands move, and the description, the
cues and this paragraph all say so rather than letting a face-off athlete
assume the app is grading whether they won the ball. It also carries no
throwing load — nothing goes overhead, and counting it as throwing volume
would trip a shoulder advisory for work that never touched the shoulder.

---

## Goalie save positions

Goalie was the last position on the roster still training somebody else's
practice. Its whole plan was stick work and lateral jumps standing in for a job
the app could not see, because every drill in the catalogue asked the same
self-paced question — how many, and how well shaped — and a goalie's actual job
is a different question entirely: given a spot somebody else picked, how fast
and how accurately do the hands get there.

`lax_goalie_saves` is the first **cued** drill. The app calls a spot — high,
hip or low, either side, or five hole — and the athlete drives their hands and
lead foot to it and resets. Goalie now leads on it at 26% of its plan.

### The app calls the spot, so the app cannot be trusted to mark it

The moment the app chooses the target, two problems appear that no self-paced
drill has. If the sequence were random per device, two goalies on the same team
would face different drills and their numbers would not compare. And reaction
time is measured from the moment the cue appeared — if the client both picks
that moment and reports the elapsed time, the client is grading its own
homework.

Both go away if the sequence is a pure function of the **session nonce**, which
the server issues at session start:

- the browser derives the sequence in order to display it,
- the server derives the identical sequence in order to mark it,
- neither sends the sequence to the other, so there is nothing to tamper with,
- and because cues fire on a fixed cadence, the server knows what time every
  cue appeared without being told.

A hostile client can still lie about where the hands went — that is true of
every count in this system and is what the integrity layer is for. What it
cannot do is invent a friendlier set of targets after the fact. A test submits
one athlete's reps against a different nonce and asserts the score collapses.

This means `offdays/cues.py` and `static/cues.js` are a deliberate duplicate of
each other, down to the bit. Both implement FNV-1a and mulberry32 with every
intermediate masked to 32 bits, and **both test suites check the same
hand-written golden vectors**. If the two ever drift, the browser shows an
athlete one spot while the server marks them against another — silently, on
every rep, with no error raised anywhere. Nothing else would catch it.

Cues are drawn in *bags* — a shuffled copy of the whole vocabulary, then
another — rather than picked independently, so "every seven cues covers every
spot once" is a guarantee rather than an expectation. The per-spot breakdown
this drill exists to produce is worth nothing if some corner never came up.

### A fifth signal kind, and why it had to exist

Every height signal in the catalogue breaks on this drill: a high save drives
the hands up and a low save drives them down, so no single pair of thresholds
counts both. What every save has in common is that the hands leave the ready
position and come back, so `save_reach` measures the leading hand's distance
from the chest, in torso lengths. That oscillates the same way whichever
direction the save went, and the direction is recovered separately by
classifying where the hands were at full extension.

Two details in that classifier are load-bearing:

**Sides are anatomical, not the picture's.** The lateral position is a
projection onto the shoulder axis rather than a raw x coordinate, so it does
not matter which way the athlete faces. Turned side-on, the shoulders collapse
and there is no axis left to project onto — so it returns `unknown` rather than
calling a stick-side save an off-stick one.

**The zone follows the raw peak, not the smoothed one.** This drill runs the
lightest smoothing in the catalogue (0.55 against a usual 0.35) because it
measures *when* rather than only *how much* — a filter that lags four frames
puts a fifth of the reported reaction time into the filter itself, in the same
direction every time, which is a bias rather than noise. Even so, the smoothed
peak arrives after the hands have turned around, and following it filed every
low save as a hip save. A test drives a low save and asserts it comes back low.

### "Could not see" is never "went to the wrong place"

An unreadable rep and a wrong rep are different facts, one about a phone and
one about a child, and a scorer that blends them tells a goalie they are bad at
a corner the app simply could not watch. So `unknown` is a first-class value:
the browser sends it rather than omitting the field, the scorer counts it
separately, and a session that is mostly unreadable is **withheld** with a
message about framing rather than scored.

The sharpest version of this was a bug the tests caught: the zone was seeded at
the moment the rep armed, which is the *closest* point of the cycle — the ready
position. A save whose every extended frame was unreadable reported the ready
position instead, which the server scored as "drifted to the middle": a miss
invented out of a camera problem.

### What comes back is a pattern, not a mark

Goalie is the position where a blunt score does the most damage — it is the one
place on the field where every mistake is public and final, and a child who
already knows that does not need an app agreeing with them. So the report names
**one** thing: which side lags, which height band lags, or which single spot is
behind. One, because a goalie handed four fixes works on none of them.

A side is only reported as a side when *more than one spot on it* is genuinely
behind. One broken corner drags its whole half down far enough to look like a
half-wide problem, and sending an athlete away to drill three corners when two
were already fine is worse advice than naming the one.

The language follows the athlete: "stick side" is not a fixed direction but
whichever side the top hand is on, so the same region is stick-side for one
goalie and off-stick for another. Where the top hand is not known it falls back
to plain left and right — worse coaching language, never wrong.

### What it does not do

Three limits ride along with every result, shown to coaches and athletes rather
than kept in a docstring, because the gap between "quick hands to the right
spot" and "good goalie" is exactly the gap a number on a screen will be assumed
to have closed:

- **The app calls the spot out loud**, so this trains the path to the ball, not
  reading a shooter. A real goalie knows where it is going before it goes
  there, and no phone drill can ask that of them.
- **There is no ball and no shooter.** Nothing here is a save percentage and it
  should never be read next to one.
- **The camera tracks hands, not the stick head**, which sits about a foot
  above the top hand. "High" here means the hands got high.

It carries no throwing load — nothing goes overhead, and a goalie's shoulder
problem is not a throwing problem.

---

## Second looks

An athlete who reruns the slide-and-recovery clip before Tuesday's practice
because they want to be sure is doing exactly what film study is for. Every
instinct a piece of software has about repeated views — that they mean
confusion, that a number should go down — is wrong here.

Two things were in the way. The feed **removed a clip the moment it was
watched**, so the one thing an athlete is most likely to want was the one thing
the screen would not give them. And a rewatch on a later day created a fresh
row and **paid XP again**, which made the cheapest points in the product
replaying yesterday's clip with the sound on.

Both are fixed. Watched clips come back in their own `again` list so a revisit
never displaces new material, and a clip pays **once, ever**.

### The rules that keep it from becoming an accusation

**A second look is never worth XP and never costs any.** The moment it pays,
somebody farms it; the moment it costs, nobody does it. It sits outside the
economy, which is also the honest description of what it is.

**A second look is never blocked.** The daily cap still gates *new* material —
that burnout guard survives this feature intact — but re-checking something
already seen is allowed past it. Capping it would make the feature useless
exactly when it matters, the night before a game. Restarting resets none of the
watch state, so a second pass cannot manufacture credit a first one did not
earn.

**The athlete is told.** The film screen carries a plain sentence, in English
and Spanish, saying the coach can see when they have gone back — before
anything is recorded. Nothing else in this product watches a child quietly, and
a kid who finds out later that rewatching was reported is a kid who stops
rewatching.

**The clip is the subject, never the athlete.** What a coach gets is "three
athletes went back to Sliding and Recovery", which is a practice plan. The
per-athlete list sits underneath, and there is no ranking of who rewatched
most — that list would be read as a list of the kids who are slow within a week
of shipping. The response carries the sentence explaining how to read it, and a
test asserts no note or phrase next to a child's name contains the words
"struggling", "behind", "weak", or "slow".

The one number that genuinely points at the material rather than the athletes
is `unsettled`: how many came back and *still* have the comprehension question
wrong. Two or more, and the note stops suggesting a five-minute chat and starts
saying to walk it through on the field.

A bug worth recording: `answered` stores the option index the athlete picked,
not a flag. The first version tested it for truthiness, which read every
athlete who picked the first option as having never answered at all.

### The shelf stays IQ clips

A highlight reel is not a bad video. It is a video that **teaches nothing while
looking exactly like film study** — it fills the shelf, it earns the same XP,
and the athlete comes away having watched somebody else be good at lacrosse for
four minutes.

Nobody here can watch the video, so the coach's own title is the entire
evidence. Clips whose titles read as highlight reels — "Top 10", "Best of",
"Mixtape", "Compilation", "Highlights" — are **refused**, not warned about: a
warning on a screen a coach sees once is a warning nobody reads, and the fix is
to retitle it, which costs nothing.

The marker list is deliberately narrow, multi-word phrases rather than bare
words, because lacrosse is full of vocabulary a keen filter would eat. A test
asserts "Top of the fan spacing" and "Best angle to take on a ground ball" both
sail through, because a filter coaches route around protects nothing at all.

The curriculum response now carries `what_to_cut` and `not_this`, read at the
one moment the advice can still change what a coach picks — immediately before
they go looking for footage. The same rule is enforced on the way back in.

---

## Paying for what is measured, not what was selected

An audit of the catalogue turned up a live defect, and it is worth writing down
because the shape of it is easy to reproduce.

**Eight drills share one signal.** The whole wall-ball family — plain, strong
hand, off hand, one handed, cross handed, behind the back, split dodge, and
quick stick — is read the same way: the top hand rises above the shoulder line
and comes back. Their thresholds nest inside one another, so a single plain
wall-ball rep satisfies all eight.

**They were paying 1.0 to 1.6 XP per rep.** Feeding one identical synthetic
wall-ball stream into every counter produced 24 reps in all eight, worth 24 XP
as a plain wall ball and 38 as a split dodge. The highest-earning thing an
athlete could do was pick the fanciest name in the menu and then do the easy
movement — and they would not have been cheating, because the app told them it
counted.

That is not a tuning problem. One camera, no stick in the model, and the hands
travel the same path whether the rep was a plain wall ball or a split dodge.
The information is not in the frame, so no future model recovers it.

**The fix is to stop paying for the label.** Every wall-ball-family drill now
pays the same base rate. The patterns stay — each carries its own coaching cues
and technique reference, and choosing one is a statement of what the athlete
means to practise — but the reward comes only from things actually measured:

- **which hand was on top**, which the counter genuinely reads, and which earns
  the off-hand premium on any handedness-tracking drill; and
- **how well the reps were shaped**, which the form score already measures.

`gen_lunge` had the same problem against `gen_squat` on the knee-angle signal,
at a much smaller 10%, and is levelled too.

Drills the app cannot confirm now carry `pattern_verified = False`, and their
descriptions say so in the athlete's own words: *"The app counts the hands and
cannot see the split, so this earns the same as any other wall ball."*

Two tests pin it. The first is the general rule — **if doing drill X
necessarily satisfies drill Y's thresholds, Y must not pay more than X** — which
catches this whole class rather than these eight cases. The second asserts the
unverifiable set by name, so a pattern becoming genuinely detectable is a
deliberate edit rather than a drift.

**The off-hand premium moved rather than shrank.** Levelling the base rates
would have halved the reward for the one habit this product most wants to buy —
an off-hand rep used to reach 1.6 × 1.5 = 2.4 and would have landed at
1.0 × 1.5 = 1.5. So `offhand_bonus_multiplier` went from 1.5 to **2.4**, and an
off-hand rep earns 2.4 again.

That is a restoration, not an inflation, and it is better targeted than what it
replaced:

| | old | new |
|---|---|---|
| Off-hand rep, plain wall ball | 1.5 | **2.4** |
| Off-hand rep, "Off Hand" drill | 2.4 | **2.4** |
| Strong-hand rep, "Off Hand" drill | **1.6** | 1.0 |
| Strong-hand rep, plain wall ball | 1.0 | 1.0 |

The premium now lands on off-hand reps *wherever they happen* rather than only
inside one drill, and on none of the strong-hand reps that used to collect it by
association. It is paid per rep against the hand actually detected on top, which
is measured rather than selected from a menu.

The daily XP cap is unchanged and still binds, so this changes what a day
rewards rather than how much a day can earn — and a test asserts that, because a
bigger multiplier quietly becoming a bigger day is exactly the failure worth
guarding against.

---

## Ground balls belong to everyone, and the goalie trains both hands

Two changes to the position plans, both of which removed an assumption the code
was quietly teaching.

### Ground balls were ranked, and should not have been

The plans gave an attacker **6%** of their solo time to ground balls and a long
pole **20%**. Nothing decided that; it fell out of tuning each position
separately, and the result taught an attacker that picking the ball up is
somebody else's job. Ground balls are the one part of lacrosse that belongs to
nobody in particular.

Every lacrosse position now gives them the same **16%**, with the rest of each
plan scaled to fit and every mix still summing to 1.00. Sixteen rather than the
average of the old spread, because at 16% the defender's plan needed no change
at all — it was already there.

Three tests hold it: the shares are equal, the share is a real allocation
rather than a token 2%, and ground balls are never the thing a position is told
to do *least*.

### The goalie carve-out read the grip and missed the job

Goalie was the one position carrying `offhand_matters = False`, so off-hand work
was never prescribed and weak-hand balance was never compared. The reasoning was
that a goalie's hands do not swap on the stick.

That is true of the grip and false of the job. The save is made with both hands,
the outlet that follows it is a real throw, and a keeper who can only clear to
one side is the one a ride aims at. Goalies now get off-hand wall ball in their
plan and the off-hand comparison like everyone else — and the flag survives for
sports where it genuinely measures nothing, which is why basketball still
carries it.

A test asserted the old behaviour by name. It has been flipped rather than
deleted, and it now says why.

### And the save drill enforces two hands

The reach signal took whichever wrist was further from the chest — so throwing
one arm at the ball, the habit every goalie coach spends a season removing,
scored exactly like a proper save, at full marks.

Reach is now measured from the **midpoint of the two wrists**, and is null
unless both are visible. That makes the requirement arithmetic rather than a
rule that has to detect intent and argue about it: reach out with one hand and
the midpoint travels half as far, which does not clear the firing threshold, so
the rep simply does not count.

Measured against the test skeleton: a two-handed save to the high corner reads
**1.20**, the same movement one-armed reads **0.54**, and the firing line is at
0.95. Six one-armed stabs count zero; six two-handed saves count six.

---

## The other fifteen sports

Running the same audit across every sport it was worth running it on, and the
result is the headline rather than the fixes.

### The pay-differential bug does not exist anywhere else

The wall-ball defect needed **two drills sharing one signal** before it could
happen. Fifteen of the sixteen sports have at most one drill, so the audit comes
back clean for all of them — not because they are well built, but because there
is nothing there to be wrong.

### What is actually wrong is much simpler

**Every sport-specific drill outside lacrosse was in nobody's plan.** Juggling,
dribbling, setting, wall throws and wall rally all existed, counted, scored and
had tests — and no position prescribed any of them. A soccer player following
their position's guidance did push-ups, squats and lateral bounds, and never
touched a ball.

Measured as the share of a plan made of that sport's own work:

| | before | after |
|---|---|---|
| Lacrosse | 44–72% | 44–72% |
| Basketball | **0%** | 8–24% |
| Volleyball | **0%** | 9–24% |
| Tennis | **0%** | 19–21% |
| Soccer | **0%** | 12–19% |
| Baseball / softball | **0%** | 5–16% |
| The other ten sports | **0%** | **0%** |

The ten with nothing are cheer, cross country, dance, football, gymnastics,
hockey, rugby, softball, swimming and track. They have positions, aliases,
focus lines and conditioning plans — and no drill of their own to prescribe.
Softball is the near-miss: its athletes now get wall throws, but the drill is
filed under baseball, so its own-sport share still reads zero.

The pitcher's plan is deliberately the lightest at 5%. Wall throws cost a full
throw per rep against a growing shoulder, and a solo plan that quietly adds
throwing volume to a twelve-year-old pitcher's week is exactly what the load
model exists to prevent. A test pins it.

### And a second stale premise, in the same shape as the goalie one

The blanket `offhand_matters = False` on all fifty-one non-lacrosse positions
was justified in a comment reading *"the only drills that report a left/right
split are the two stick drills"*. That stopped being true the moment the other
sports' drills were prescribed: juggling reports which foot, dribbling reports
which hand.

Weak-hand parity is now compared for **lacrosse, soccer and basketball**, and
stays off elsewhere for stated reasons rather than by default:

- **Baseball and softball** — wall throws do report an arm, but bilateral
  throwing is not a goal in these sports, it is a way to hurt a growing elbow.
  This is the one place parity would be actively harmful, and a test enforces
  that it is never switched on.
- **Tennis** — the wall rally reports a hand, but a player has one racket hand.
  The two wings that matter are forehand and backhand, which it does not
  measure and should not pretend to.
- **Everything with no reporting drill** — a metric that reads zero for every
  child in the sport ranks them on nothing.

The sports that do compare it are listed in `BILATERAL_SPORTS`, and a test
asserts each one actually has a prescribed drill of its own that reports the
split — so adding a sport there without the drill to back it fails rather than
shipping a comparison that means nothing.

### Two lacrosse drills are deliberately unprescribed

`lax_wall_ball_strong` and `lax_wall_ball_btb` are on the menu but in no plan.
Strong-hand-only duplicates what an athlete does by default, and behind-the-back
is a trick before it is a skill. They are listed by name in the test rather than
inferred, so a genuinely stranded drill still fails.

---

## Basketball, built to lacrosse depth

The audit said the ten empty sports needed building rather than auditing, and
that one sport taken all the way beats a token drill in fifteen. Basketball
went first: the drill already existed, dribbling is the most universal solo
skill in youth sport, and both hands genuinely matter — so the parity machinery
already in place has something real to measure.

### Seven drills, and every one of them earns its rate

The wall-ball family is what happens when a catalogue pays for a name the app
cannot verify. Basketball was built *after* that lesson, so each variant either
differs in something checkable or is marked unverifiable and paid the plain
rate.

| Drill | What separates it | Verified |
|---|---|---|
| Dribbling | the baseline | — |
| **Crossover** | the ball must keep changing hands | ✅ hand attribution |
| **Weak-Hand Pound** | the ball must stay on one hand, and which | ✅ hand attribution |
| **Low Pound** | a rate *floor* a slow dribble cannot clear | ✅ tempo |
| **Wall Passes** | contact off the body, not the floor | ✅ contact type |
| Between the Legs | the hands do what a crossover does | ❌ pays the plain rate |
| **Defensive Stance** | a hold, scored in seconds | ✅ different metric |

`BallSpec` gained an `alternation` rule — `any`, `alternating`, or `same_hand` —
enforced server-side in `ball.review()`. It is what lets a crossover honestly
pay more than a dribble, and it is validated at construction: a rule without
`attribute_side` raises, because there would be no hands to check it against.

Failing the pattern is a **note, never a refusal**. An athlete who meant to
cross over and mostly dribbled on their strong hand has done real work and
should be told what happened, not have the session thrown away.

`bkb_between_legs` is the interesting one. Its hands alternate exactly as a
crossover's do; the legs are the difference and the camera has no view of them.
It ships marked `pattern_verified = False` at the same rate as the crossover —
the discipline applied *before* the mistake rather than after it.

### Plans that lead on basketball

| | own-sport share | leads on |
|---|---|---|
| Guard | **69%** | Dribbling 14% · Crossover 14% · Weak-Hand Pound 11% |
| Wing | **56%** | Dribbling 12% · Crossover 9% · Weak-Hand Pound 9% |
| Post | **31%** | Squats 12% · Squat Jumps 12% · Weak-Hand Pound 9% |

Guard and Wing sit inside lacrosse's 44–72% band. The post is deliberately
lower: strength stays the priority, so the ball work there is the two drills
that survive contact. Every plan includes the weak-hand pound, because it is
the one drill here whose pattern the app can genuinely confirm and the hand
nobody practises is the hand a defender plays.

### Fourteen film topics, and a curriculum module that is no longer one sport

`curriculum.py` held a lacrosse syllabus and a `catalogue()` that returned
`"sport": "lacrosse"` as a literal. It now holds a `BY_SPORT` registry, and the
endpoints are `/api/curriculum/{sport}` and `/api/coach/curriculum/{sport}` —
so a third sport is a data change and nothing else. There is no branch anywhere
that names a sport.

A sport with no syllabus returns an **empty list and a note saying so**, rather
than a 404. "Nothing written yet" is a real answer to that question and a coach
asking it deserves to be told rather than shown an error.

The basketball syllabus runs 3 fundamentals (65–70s, all ages), 6 core topics
(115–130s, 13+) and 5 advanced (150–165s, 15+), every target length already
inside the ceiling for its own age band. Where lacrosse IQ is mostly about a
slide and who is hot, basketball IQ is mostly about spacing and what the second
defender does. Same rule as lacrosse on video ids: there are none, and a test
asserts no topic smuggles one in.

### What basketball still does not have

- **No videos**, same as lacrosse. Fourteen topics, an empty shelf.
- **Shooting is absent**, and that is the big one. The motion is detectable;
  whether the ball went in is not, and a shooting drill that cannot see the
  result would be measuring form while staying silent on the only thing a
  twelve-year-old cares about.
- **No lateral movement drill.** Defensive slides are the position's actual
  footwork and there is no lateral signal in the library — every signal here is
  vertical or angular. The stance hold covers the legs; it does not cover the
  sliding.
- **Between the legs is unverifiable**, and behind-the-back handling is not
  attempted for the same reason.

---

## The lateral signal

Every signal in the library measured a height or an angle. That is why the most
common footwork in basketball, tennis, soccer defending and goaltending —
the defensive slide — had no drill in any sport: there was nothing to count it
with.

`stance_width` is the first horizontal measurement. It is the **signed** distance
from the left ankle to the right ankle, projected onto the shoulder axis, in
torso lengths. Projected rather than read off the picture's x, so it does not
matter which way the athlete faces or how square they are to the phone.

Against a real skeleton:

| | reads |
|---|---|
| Feet together | 0.24 |
| Defensive stance | 1.28 |
| Mid slide | 1.76 |
| Full slide step | 2.08 |
| **Feet crossed** | **−0.40** |

### The sign is the point

Crossing your feet is the one thing every defensive coach spends a season
shouting about, and because the signal is signed it is **not an inference about
form — it is a number going below zero**. That makes it the only technique fault
anywhere in this product the camera can *establish* rather than estimate.

`bkb_slide` counts one rep per push, arming at 1.30 and firing at 1.80 — so a
shuffle that never widens the stance counts nothing, which is the failure mode
the drill exists to catch.

### Attributing a cross took three attempts

The first version watched only the armed phase, and missed crossings entirely:
the trail foot swings through during the *recovery*, after the rep has already
fired.

The second version watched every frame — and tagged **two** reps for one
mistake. A cross drives the signal to its minimum, and the minimum is exactly
where the next rep arms.

The rule that works: while the signal is still down at the arming end, we are
between steps and the cross belongs to the one that just finished. Once it has
risen away from there, the new push has begun and the cross is the new step's.
And a cross between steps attaches to the finished rep **or to nothing** — never
passed along to the step about to start, since `lastRep` is cleared the moment
that step arms and falling through to the new one is what caused the
double-tagging.

A test drives three slides with the middle one crossed and asserts exactly
`[false, true, false]`.

### Counted, never punished

`footwork.py` reports the count, the share and one sentence. There is no
penalty, no deduction, and nothing subtracted — a test asserts the same twenty
steps earn identical XP whether every one crossed or none did.

A twelve-year-old learning to slide **will** cross their feet, and the useful
response is a coach saying so, not the app quietly paying them less for it. The
note is addressed to the athlete on their own screen: a fault the app can see
and only tells the coach about is surveillance; one it tells the athlete about
is coaching.

Below ten steps it says nothing at all — one crossed step out of four is 25% and
means nothing.

### What it does not measure

Stance width sees the *step*, not the *travel*. An athlete sliding on the spot
with a wide, committed push scores the same as one covering ground. Distance
travelled would need a signal with memory — a baseline that follows the athlete
across the frame — and every signal here is deliberately memoryless so that
`computeSignal` stays a pure function of one frame.

---

## The shooting drill

Called too hard twice, and the reason was never the motion. A shot is a clean
elbow cycle and pose reads it easily. The problem is that **the app cannot see
whether the ball went in** — there is no hoop in a driveway drill, and a phone
propped against a water bottle would not find one if there were.

So it does not try. `bkb_form_shot` scores nothing about accuracy, reports no
makes, and says so in the description, the setup hint and the `LIMITS` carried
on every result. What it measures instead is the thing every shooting coach says
first and pose genuinely sees: **whether the elbow stayed under the ball.**

### A third signal kind, and a lefty is the reason

`shooting_arm` is the elbow angle of whichever arm is actually shooting, picked
per frame as the one whose wrist is higher.

A plain `joint_angle` names one side in the spec, and the mirror fallback only
swaps when the named side leaves the frame — so a **left-handed shooter with
both arms visible would have been measured on the arm that is not shooting.**
Handedness cannot live in the spec either, because one record is shared by every
athlete. Picking the arm from the frame is the only version of this that works
for a lefty, and it records which hand shot as a side effect.

### Elbow flare, captured at release

"Elbow under the ball" has a geometric meaning: at release the elbow should sit
beneath the wrist rather than flared out to the side. `elbowFlare()` measures
that offset along the shoulder axis, in torso lengths, as a magnitude — a flare
is a flare whichever side it goes.

It is captured at the **extreme of the extension**, which is release, the same
way the goalie zone and the crossed-foot flag are captured. And it is null when
the athlete is side-on: from there the elbow is *behind* the wrist rather than
beside it, and the projection would report a perfect shot for any shot at all.

Null rather than absent, because "we could not see the elbow" and "the elbow was
under the ball" are different facts and must not collapse into one. A test
asserts unreadable releases never dilute the median.

### Counted, never scored

Same rule as the goalie report and the footwork one. The flare is a number and
one sentence; it subtracts nothing. A child rebuilding a shot will flare for
weeks, and an app that quietly paid them less would teach them to stop using the
app rather than to fix the elbow.

A bug worth recording: the first version checked *"is the median under the
ball"* first, and told a shooter with two flared shots in twenty that everything
was fine — which is exactly the rep they need to hear about. The clean message
now requires zero flared releases, not just a good median.

### What it cannot do

- **No hoop, no makes, no percentage.** Nothing it produces belongs next to a
  shooting percentage.
- **It watches the elbow, not the ball's flight.** A shot can have a perfect
  elbow and still be short, flat or wide.
- **Side-on it says nothing** rather than flattering the session.

The ball is in **confirm** mode and not required — it establishes there was a
ball and nothing more, the same rule every lacrosse drill follows. And a shot is
an overhead *push*, not a throw: `throws_per_rep` is zero, because on the
throwing axis an evening of form shooting would read as an evening of throwing
and trip a shoulder advisory for work that never went near one.

---

## Volleyball, built to lacrosse depth

One drill and four plans of conditioning becomes **seven drills, four plans that
lead on volleyball, and a fourteen-topic film syllabus.**

Volleyball turns out to be the best sport in this catalogue for honest
differentiation, because its three basic skills contact the ball in three
different places: a **set** above the head, a **forearm pass** below the
shoulders, a **hit** off one hand overhead.

### A hands gate, because a set and a pass were the same event

To the detector they were identical — the wrist is the nearest listed part
either way. `BallSpec` gained `hands`: `any`, `above_shoulders`, or
`below_shoulders`, checked in `ball.js` when a contact fires.

That single field turns the sport's two most fundamental skills from one drill
with two names into two drills that can each be verified. A test asserts the
gates are mutually exclusive, so a rep counts for one skill or the other and
never both.

The gate is **permissive when it cannot see the shoulders**. A half-resolved
skeleton should cost a contact its attribution, not its existence — otherwise
the drill silently counts nothing and the athlete is told they did no work.

| Drill | What separates it | Verified |
|---|---|---|
| **Setting** | hands above the shoulders | ✅ hands gate |
| **Forearm Passing** | hands below the shoulders | ✅ hands gate |
| **Serving** | one hand, same hand, overhead | ✅ hands + attribution |
| **Arm Swing** | elbow angle of the swinging arm | ✅ shooting_arm |
| **Approach Jump** | hip travel, band clear of every other jump | ✅ body height |
| **Block Jump** | hands against the shoulder line, not the hips | ✅ different landmark |
| Wall Setting | hands above the shoulders, same as a set | ❌ pays the baseline |

### The guard caught a cross-sport confusion

`bkb_form_shot` (95–155°) sits inside `vb_arm_swing` (90–158°), so a volleyball
arm swing fires the basketball shot's thresholds — and the shot was paying more.

That is real: **the app cannot tell a jump shot from a volleyball arm swing.**
Both are one-armed overhead extensions. The signal generalises across the two
sports and so does the ambiguity, so they now pay the same. Paying one more
would be paying for the sport's name.

This is the first time that guard has fired *across* sports rather than within
one, and it is the reason it was written as a catalogue-wide rule.

### The load model finally has something to say

Volleyball is the sport where this matters most, and the plans say so:

- **Serving and arm swings count as throwing.** They are the same overhead
  mechanism a pitch count exists to watch, and a serving shoulder gets hurt the
  same way. Serving stays under 12% of every plan for exactly that reason.
- **The approach jump is the heaviest landing in the catalogue** at 2.6 per rep,
  above a tuck jump, because a maximal jump off a run-up comes down from higher
  than a standing one. Jumper's knee is what this sport hands teenagers, and a
  hundred approach jumps in a driveway is a real week's landing volume.

I claimed in a test that it was the heaviest rep in the catalogue. A pull-up is
3.0, so that was false — the claim is now "heaviest *landing*", which is true
and is the thing that matters.

### Plans that lead on volleyball

| | own-sport | leads on |
|---|---|---|
| Setter | 57% | Setting 20% · Wall Setting 13% · Passing 10% |
| Hitter | 53% | Approach Jump 17% · Arm Swing 13% · Passing 10% |
| Middle Blocker | 53% | Block Jump 17% · Approach 13% · Arm Swing 10% |
| Libero | 43% | Passing 25% · Lateral Bounds 14% · Setting 11% |

Everybody passes and everybody serves. **The libero never hits** — no approach,
no arm swing — because prescribing them would be prescribing somebody else's
practice, and a test enforces it.

### Fourteen film topics

Where lacrosse IQ is about a slide and basketball IQ is about spacing,
volleyball IQ is about **reading a set before it is set** and about where the
six of you are standing. The sport is played in a small box and almost every
error is a positioning error.

Three sports now have a syllabus. Adding the third was a data change and
nothing else.

---

## Soccer, built to lacrosse depth

One drill and four plans of conditioning becomes **seven drills, four plans that
lead on soccer, and a fourteen-topic film syllabus.**

The first sport here played with the feet, and most of the machinery transferred
unchanged. `attribute_side` reads *which foot* took the ball exactly as it reads
which hand — so the alternation rules written for basketball make a weak-foot
drill and an alternating drill genuinely verifiable, with no new code at all.

### The thing that stopped the build for a while: heading

`soc_juggle` had `nose` in its contact parts. **A child heading a ball in a
garden was being counted and paid for it** — with no age floor anywhere in the
catalogue, and no separate volume tracked.

Youth football bans heading below about eleven and limits it for years after, on
concussion grounds. This product's entire argument for the throwing axis is that
*repetitive volume nobody counts* is what hurts children. Counting headers as
juggles and rewarding them was the same mistake with the stakes raised.

The head is out of the parts list. A header now simply **does not register** —
the touch is not punished and nothing is said about it, it just earns nothing,
which is the most a juggling drill should have to say about heading.

**And there is no heading drill.** That is a decision, not a gap. Building one
would mean an app encouraging a twelve-year-old towards heading volume, which is
precisely what the load model exists to argue against. Two tests hold the line:
no soccer drill counts a head touch, and no drill or film topic is about
heading.

I considered adding a `min_age` gate to `DrillSpec` to make an age-restricted
heading drill possible. I decided against building the drill, which left the
field with no use — so it is not there either. Unused machinery added for a
feature I talked myself out of would have been worse than the gap.

### Seven drills, every one verified

| Drill | What separates it |
|---|---|
| Juggling | the baseline |
| **Weak-Foot Juggling** | one foot, and the app knows which |
| **Alternating Juggling** | the ball must keep changing feet |
| **Thigh Juggling** | only the knees are listed — a foot touch is not a contact |
| **Wall Passing** | a strike-speed floor a juggling touch cannot clear |
| **Toe Taps** | a rate floor — nobody taps that fast by accident |
| **Defending Shuffle** | stance width, the lateral signal |

Nothing in soccer is marked unverifiable, and a test asserts it. Every drill
differs in something checkable: which foot, whether the feet alternate, where
the contact was, how hard it was struck, or how fast it repeats.

### The shuffle pays exactly what the basketball slide pays

It is the same movement measured the same way, and the app cannot tell a
defender jockeying a winger from a guard sliding. Identical bands, identical
rate — paying differently would be paying for the sport's name. The
subsumption guard would have caught it if I had tried.

### Plans

| | own-sport | leads on |
|---|---|---|
| Goalkeeper | 43% | Wall Passing 18% · Lateral Bounds 14% · Juggling 11% |
| Defender | 55% | Defending Shuffle 17% · Wall Passing 14% · Juggling 10% |
| Midfielder | 67% | Wall Passing 15% · Alternating Juggling 12% · Juggling 9% |
| Forward | 59% | Toe Taps 12% · Alternating Juggling 12% · Juggling 9% |

The keeper gets no defending shuffle — they are the one position that does not
jockey a winger — but they do get real footwork, because distribution is half a
modern keeper's job and a plan of nothing but jumps would be the old mistake in
a new place. Every outfield plan carries weak-foot work.

### Fourteen film topics

Lacrosse IQ is about a slide, basketball about spacing, volleyball about where
the six of you stand. **Soccer IQ is mostly about what happens *before* you get
the ball** — the scan over the shoulder, the body shape you receive in, the run
that drags a defender somewhere useful. Almost none of the thinking in this
sport happens while you have possession.

Four sports now have a syllabus.

---

## Tennis, built to lacrosse depth

One drill and two plans of conditioning becomes **seven drills, two plans that
lead on tennis, and a fourteen-topic film syllabus.**

Both of the signals built for other sports paid off here without a line of new
code: `shooting_arm` reads the service motion, and `stance_width` reads the
baseline recovery.

### The limit that shaped the whole build

Tennis is the only sport in the catalogue where **the ball never touches the
athlete.** It comes off a racket head roughly sixty centimetres beyond the hand,
and the detector attributes the contact to the nearest wrist — so what these
drills really measure is *"the ball left from near this hand"*.

That is enough to tell that the wing **changed**. It is not enough to tell
**which wing** either shot was: a right-hander's backhand and a left-hander's
forehand look identical from the front, and the spec cannot know handedness
because one record is shared by every athlete.

So nothing claims to. `ten_one_wing` says it in its own description — *"it
cannot tell a forehand from a backhand, so which wing you pick is yours to
decide and worth making the weaker one"* — and a test asserts no drill name
contains the word forehand or backhand.

### Seven drills, all verified

| Drill | What separates it |
|---|---|
| Wall Rally | the baseline |
| **Alternating Wings** | the ball must keep leaving from alternate sides |
| **One Wing** | it must keep leaving from the same side |
| **Wall Volleys** | a rate floor a groundstroke rally cannot sustain |
| **Serve Motion** | a different signal entirely — the hitting arm |
| **Split Steps** | a small hop, in a band well clear of every jump drill |
| **Recovery Shuffle** | stance width |

Nothing is marked unverifiable, and a test asserts it.

**The recovery shuffle pays exactly what the basketball slide and the soccer
shuffle pay.** Three sports, one movement, one measurement — the app cannot tell
a player recovering across a baseline from a guard sliding or a defender
jockeying, so all three pay the same. That is now a three-way tie held by a
test.

### The serve is a throw

It is the same overhead chain a pitch count exists to watch, and a serving
shoulder at fifteen gets hurt exactly the way a pitching one does. `ten_serve`
carries throwing load, is capped at 150 reps a day, and no plan gives it more
than 12%. Nothing else in tennis touches the throwing axis, and a test enforces
both halves of that.

### Two positions that are genuinely different

| | own-sport | leads on |
|---|---|---|
| Singles | 67% | Alternating Wings 13% · One Wing 13% · Wall Rally 10% |
| Doubles | 63% | Wall Volleys 17% · Split Steps 13% · Serve Motion 10% |

Two positions is few enough that identical plans would make the distinction
meaningless, so a test asserts they differ and that the doubles player gets more
than twice the volley work. Both get the split step, because it is the one
movement that precedes every shot either of them will ever hit.

### The calibration sweep caught a bad number

I set `target_rom` for the split step at 0.16. The sweep measured a textbook rep
at 0.21 against a counter band spanning 0.18, and refused it at a ratio of 1.32.
The 0.16 was guesswork; 0.20 is what the band actually implies.

### Fourteen film topics, and one thing the other sports do not need

Tennis is the only sport here played **alone**, so there is nothing about where
to stand relative to five other people. Tennis IQ is about *patterns* — what you
are trying to make happen over the next three balls — and about something no
team sport syllabus needs: **what your own body language is telling the other
end**, and how to think about a scoreline when nobody else can help.

Five sports now have a syllabus.

---

## Baseball and softball, built to lacrosse depth

Two sports and eight position plans from one build, because they share almost
everything. **One drill becomes seven**, plus a fourteen-topic syllabus
registered under both keys.

This is the sport where the load model matters most and where it had the least
to say — so the centrepiece is not a drill.

### The throwing model had no ceiling

`load.py` carried one throwing check: a **50% week-on-week spike** above a
150-throw baseline. That is a *relative* measure, and it is blind to exactly the
athlete it should catch — the one who throws a lot every week and always has.
A relative measure calls that normal.

There is now an absolute, **age-scaled daily ceiling**:

| age | ceiling |
|---|---|
| ≤ 8 | 60 |
| ≤ 10 | 90 |
| ≤ 12 | 105 |
| ≤ 14 | 120 |
| ≤ 16 | 135 |
| 17+ | 150 |

Two things about those numbers matter more than the numbers.

**They are shaped by published pitch-count guidance, not equal to it.** That
guidance counts *pitches in a game* — maximal effort from a mound, counted by an
adult with a clicker — and is as low as it is for that reason. A wall throw in a
driveway is not a pitch. So these sit deliberately above it: what is borrowed is
the shape of the thing (that a ceiling exists, and scales with age), not any
specific figure, and nothing here should be quoted as though it were the
published guidance.

**The app can only count throws it saw.** A pitcher who threw eighty in a game
on Saturday and then does fifty in the garden is at a hundred and thirty, and
this knows about fifty. That caveat rides on the advisory itself — *"and only
counting throws the app saw, not games or practice"* — because a number that
looks complete and is not is worse than no number.

An unknown age gets **no ceiling rather than a guess**: too low and it nags a
seventeen-year-old, too high and it says nothing to the eleven-year-old it
exists for.

### What goes on the arm's ledger

| Drill | throws/rep |
|---|---|
| Long Toss | **1.5** — a harder throw than a wall throw, and the arm knows it |
| Wall Throws | 1.0 |
| Windmill Pitching | 1.0 |
| Quick Hands | **0.4** — short and submaximal, but still overhead and repeated |
| Tee Swings, Fielding, Catcher's Stance | **0** |

Putting a swing on the arm's ledger would make an afternoon of hitting read as
an afternoon of throwing and hide the number that matters. A test enforces both
halves.

### Softball stops sharing at the mound

Softball inherited baseball's plans entirely, which meant **a softball pitcher
was prescribed a baseball pitcher's plan.** A windmill is a full underhand arm
circle — a different motion, a different injury profile, and the single
highest-volume action anyone on a softball field performs.

`sb_windmill` is its own drill, on its own signal (the pitching hand from below
the hip to fully overhead — by far the largest vertical excursion in the
catalogue), and softball's pitcher now gets its own plan. A test asserts the two
sports differ at **exactly one position** and no other.

### The pitcher's plan is deliberately the least sport-specific

Baseball's pitcher sits at **27% own-sport**, the lowest of any position in any
sport built so far. That is correct rather than a shortfall: a pitcher's solo
hours should be legs, hips and core, because the throwing is what the rest of
their week is already full of. A test asserts the pitcher is the *minimum*, and
another caps throwing work at 30% of any plan in either sport.

### Two things the guards caught

The subsumption guard fired **cross-sport again**: `bb_tee_swing` at
[0.55, 1.25] swallowed `lax_goalie_saves` at [0.70, 0.95], so a bat swing fired
the goalie drill's thresholds. The band was wrong physically — a batter's load
puts the hands *further* from the chest than a goalie's ready position, not
closer. Corrected to 0.72, which is both accurate and clear of the goalie band.

The calibration sweep caught the windmill's `target_rom` at 1.30. A real arc
runs from about a torso below the shoulder to nearly a torso above it, so 1.30
undershot it and only 1 of 24 textbook reps counted. It is 1.60 now.

### And one piece of bookkeeping the guards forced into the open

Sharing drills across two sports broke two guards, and both were right to break.

The **uniqueness check** on film-topic keys iterated the registry and saw the
shared syllabus twice, so every key looked duplicated. It now counts distinct
syllabuses, which is what it always meant.

The **own-sport check** read key prefixes, so a softball catcher's plan — more
than half of it the sport — registered as pure conditioning, because five of the
six diamond drills are keyed `bb_`. Rather than duplicate five drills under a
second prefix, the sharing is now *declared*:

```python
SHARES_DRILLS_WITH = {"softball": "baseball"}
```

One entry, and a test asserts it stays one unless another pair of sports
genuinely performs the same movements. Guards that ask "does this position
prescribe its own sport's work" now get a true answer instead of one that
depends on how a drill happens to be named.

Seven sports have a film syllabus.

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

## Closing the assignment loop

Assignments reported compliance passively. A coach who set one and did not open
the dashboard never learned it had gone nowhere — the loop ran outward and
never came back.

Two touches now close it, and **both are deliberately about the assignment
rather than about the children.** At the halfway point, if under a third of the
squad has finished, the coach hears that it is not landing and is asked whether
it was too much, unclear, or badly timed — while there is still time to change
it. On the due date they get the outcome whether it went well or badly, because
somebody who set an assignment deserves to know how it went without going
looking.

The framing is the design. *"Four of eighteen with three days left"* invites a
coach to ask what was wrong with the assignment. A list of names invites them
to chase four kids — and a stalling assignment is more often a coaching problem
than a compliance one. So when one closes below a third the copy says plainly
that it is usually the assignment rather than the squad, and suggests a smaller
target or a longer window next time. **No child is named**, in either touch.
The names live on the compliance table behind a login, already sorted
worst-first, which is the right place for a nudge and the wrong place for a
broadcast.

Athletes who are hurt or away leave the denominator, the same rule the
pre-practice card, team goals and the evaluation export all use — a coach told
that eleven of eighteen finished, when four of the seven were on a
return-to-play ramp, has been handed a worse assignment than they set. A squad
where nobody could train produces no notification at all: nought of nought is
noise.

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
0 * * * *  cd /srv/offdays && python scripts/run_notifications.py
```

Rules that fire today, all from `run_all`:

| Rule | Goes to | Fires |
|---|---|---|
| Streak at risk | athlete | Only for streaks of 3+ — warning someone about a one-day streak is noise, and noise costs you push permission |
| Assignment due | athlete | Two days out, and again on the due date. Two touches only |
| Assignment stalled | the coach who set it | Halfway if under a third have finished, and again when it closes |
| Rest nudge | athlete | When the load picture says a day off is worth more than a session |
| Inactivity | athlete | After a week quiet — suppressed entirely during a planned absence |
| Guardian digest | guardian | Weekly, per household |
| Monthly parent report | guardian | Once a month, deduped on the month so a nightly cron sends one and not thirty |

Badge unlocks and coach broadcasts fire from the events themselves rather than
from the scheduler.

To enable phone-level push, set `OFFDAYS_VAPID_PUBLIC_KEY`,
`OFFDAYS_VAPID_PRIVATE_KEY`, and `OFFDAYS_VAPID_EMAIL`, and install
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
13. **Lacrosse is the only sport with a real drill routine.** It has nine
   drills — a full wall ball routine plus ground balls — because it is the
   sport this was built for. Every other sport has one skill drill or none,
   and gets the same eighteen general movements. That imbalance is honest
   rather than accidental: the depth exists where somebody has actually
   coached the sport.
14. **The wall ball patterns are declared, not recognised.** The detector
   reads top-hand height and counts cycles; it cannot see whether a ball went
   behind a back or whether a split dodge was sold. An athlete picks the
   pattern the way they pick squats over lunges, and each spec encodes the
   shape a good rep of that pattern has. A child could log behind-the-back
   reps while throwing normally, and nothing would catch it.
15. **Every sport shares one bodyweight drill catalog.** All sixteen sports
   have their own positions and their own emphasis, but that emphasis is drawn
   from the same eighteen general movements — a volleyball middle and a rugby
   prop get different *proportions* of the same exercises, not different
   exercises. That is honest for physical preparation, which really is largely
   shared. Sport-specific *skill* drills exist in six sports only (the five
   ball drills plus lacrosse stick work); the other ten get physical
   preparation and film. A sport with no position model at all still falls
   back to the generic mix, but no shipped sport is in that state.
16. **The age bands are heuristics, not a clinical instrument.** They are drawn
   from general paediatric sports-medicine guidance and rounded to numbers a
   twelve-year-old can act on. They know nothing about the individual athlete's
   growth stage, injury history, or what else their week already contains, and
   they are not a substitute for a clinician. Treat `OFFDAYS_BUDGET_SCALE`
   as a program-level dial, not a per-athlete prescription.
17. **Handedness is inferred from wrist height**, which is reliable for standard
   lacrosse form and less so for unusual grips.
18. **"Before 8am" badges use UTC.** Athlete-local timezones are not stored yet,
   so that badge is wrong outside UTC. Noted in `store.py`.
19. **Single-process SQLite.** Fine for a program or two; a district-wide rollout
   wants Postgres. `store.py` is the only module to change. Schema upgrades run
   automatically on connect (`db.migrate`), probing the actual database rather
   than trusting a version counter.
20. **Auth is bearer tokens with no rotation or expiry.** Adequate for a pilot,
   not for a public launch.
21. **Revocation soft-fails by default**, though pre-fetched staples make strict
   mode practical — see **Stapling** above. Left soft by default because a
   deployment that has not set up the refresh job would otherwise start
   refusing webhooks; turn on `OFFDAYS_SNS_REVOCATION_STRICT=1` once
   `/api/coach/staples` shows them fresh.
22. **No TLS-level stapling on outbound fetches.** Python's `ssl` cannot read a
   stapled response, and doing it needs pyOpenSSL. It would only cover AWS's
   *TLS* certificate rather than the SNS signing certificate, so it was left
   out rather than added untested.
23. **No payment processor.** The billing model, entitlements, and invoicing are
   real; taking money is a `Gateway` implementation away, and nothing here has
   been through a PCI review.
24. **Offline slots are per-drill.** A drill you have never opened online has no
   banked slot, so its first-ever session needs a connection. The app says so
   plainly rather than failing silently.
25. **Web Push needs credentials.** Notifications generate and display in-app
   with nothing configured, but reaching a locked phone needs VAPID keys.
26. **Form quality is pose-only.** It reads how the body moved, not where the
   ball went. A wall-ball rep with perfect mechanics and a bad release still
   scores well, and stick position is invisible to it.
27. **Guardian identity is proven by the invite code alone.** There is no email
    verification, so a code handed to the wrong adult creates a valid account.
    Short expiry, single use, and revocation limit the window; real
    verification is a launch requirement.
28. **Roster import reads delimited text only.** CSV, TSV, and
    semicolon-separated files work; a native `.xlsx` has to be exported to CSV
    first. The same is true of what a sync fetches, since it is rendered back
    to CSV and fed through the same parser.
29. **Load coefficients are reasoned estimates, not measured values.** The
    per-drill numbers in `catalog.py` are a defensible ordering rather than
    validated physiology, and the app sees only self-directed work — so the
    workload picture is directionally useful and absolutely not a clinical
    assessment.
30. **The TeamSnap and SportsEngine adapters have never run against a live
    account.** There are no credentials for either in this environment, so
    both are written against published API shapes and are unverified — they
    say so in `verified`, in the API payload, and in the coach UI, and tests
    assert they keep saying so. Expect the first real connection to need
    fixes. Only the export-link provider is verified end to end. Neither
    adapter refreshes an OAuth token either: a credential that expires has to
    be re-entered, and the failure is recorded on the link where that team's
    coach will see it.
31. **Roster sync never removes anybody.** Departures are counted and named,
    and applying them is left to a person. A program with heavy mid-season
    turnover will accumulate athletes who have actually left, and will have
    to prune them by hand. This is the deliberate side of a real cost.
32. **The pre-practice card is only as current as the last submission.** It
    reads what athletes have logged, so a squad that trains and submits after
    practice gives their coach a card describing yesterday. There is nothing
    live in it.
33. **Season phase is program-wide.** A club running two sports in opposite
    seasons has to pick one, and the other sport's athletes get the wrong
    scale. Per-team phase is the obvious fix and is not built.
34. **Technique references are diagrams, not demonstrations.** The generated
    trace shows the shape, range and tempo of a rep — it cannot show grip,
    stance, or where to look, and a written cue is a poor substitute for
    watching someone do it. No clips ship, so until a program films its own,
    the reference is a curve and four sentences.
35. **The parent report is monthly and derived from logged sessions only.**
    Work done at practice, at another club, or on a bike is invisible to it,
    so a child who trained hard all month in ways this app never saw appears
    quiet. The copy is careful not to scold, but it cannot know what it
    cannot see.
36. **The Spanish translations are not certified.** They were written for this
    codebase, not by a professional translator, and the consent copy is
    legally adjacent — a program relying on it should have a native speaker
    review it before launch. Coverage is also deliberately partial: the parent
    portal, consent flow and shipped recognition messages are translated; the
    athlete capture app, coach dashboard and drill catalog are not, because a
    half-translated surface is worse than an honest boundary.
37. **A coach's own words are never translated.** Custom recognition text
    reaches a family in whatever language the coach typed it in. There is no
    translation service in this application and adding one would mean sending
    children's message content to a third party, which is a trade this product
    should not make quietly. The payload flags which messages are shipped
    defaults so a client can say so.
38. **Team goals are only as fair as the integrity layer.** Clearing the
    personal bar depends on sessions being counted, so an athlete who can fool
    the rep counter can put themselves in the count. The cost is low by
    design — the bar is small, contribution is binary, and nothing is awarded
    to an individual for it.
39. **Planned absence is trusted, not verified.** Nothing checks that a family
    was actually away. A parent could book a month a year and keep a streak
    alive through it; the caps make that visible rather than impossible, and
    the judgement that this is a family's business rather than the app's is
    deliberate.
40. **The evaluation export cannot stop being misused.** It is designed to
    resist the obvious misreadings — no ranking, no volume, no injury history,
    caveats in the file itself — but a coach determined to sort the CSV by
    form score can still do it. What the design buys is that the number they
    sort by is one the athlete controls.
41. **Injury history reads only completed return-to-play plans.** A child who
    was hurt but never reported it, or reported it and never opened a ramp,
    carries no history here. The signal is real when present and absent
    fairly often, which makes it a reason to ask a question rather than
    evidence of anything.
42. **Nothing here makes the pose counter work for a movement it cannot see.**
    The adaptive accommodations make the product usable and fair for an
    athlete the camera misreads — they suppress a score rather than compute a
    fair one, and they open a self-report path rather than a measurement. A
    genuinely inclusive counter would need a different model and probably a
    different sensor, and no setting substitutes for that.
43. **Self-reported sessions are unverified by construction.** They are gated
    on an accommodation an adult sets, marked for ever, earn flat XP and stay
    off the reps board — but an athlete who wanted to inflate their own streak
    could. The trade is deliberate: the alternative is a child whose training
    this app structurally cannot see, punished by a streak for it.
44. **The Postgres migration is scoped, not done.** No driver is installed
    here and nothing has been run against a server. `dialect.py` measures what
    the work is; it does not do any of it, and the product runs on SQLite
    only.
45. **The program export is a snapshot, not a sync.** There is no incremental
    feed and no API for another product to pull from continuously. A director
    leaving takes a file; they do not get a migration path that keeps two
    systems in step while they move.
46. **The assignment-stall notification cannot tell a bad assignment from a
    bad week.** It reports that completion is low and suggests the assignment
    may be the problem, which is usually right and sometimes is not — exam
    week and a flu going round look identical from here.
47. **A blank form score on the evaluation export is still a weak signal.**
    The row is made identical to a camera failure, the sample count is
    withheld, and the file asks a coach not to infer from it — but an athlete
    who trains every week and never has a score is distinguishable from one
    who does, and no amount of copy removes that entirely. The alternative is
    fabricating a number, which would be worse. Programs using this at
    selection should read the preamble aloud.
48. **The club-free tier is a conversion bet, not a certainty.** Its revenue
    depends on parent adoption, which for consumer freemium is commonly
    15–25% rather than the 35%+ that would match the seat-metered Club plan.
    A club of 200 at 20% is roughly $1,160 a season. The bet is that zero
    friction to the club buys far more clubs; if it does not, the seat-metered
    plan is still there and is the better per-club number.
49. **There is still no payment processor.** `ManualGateway` records what
    happened and charges nothing. Household subscriptions, sponsorship and
    hardship all work end to end against it, so the seam is exercised — but
    no card has ever been charged by this code.
50. **Hardship is unverified by design.** Any guardian can grant it to
    themselves in one click. That is deliberate: verification would mean
    asking a family to prove poverty to their child's sports club, which is a
    worse outcome than some families taking it who could have paid.
51. **The roster plan is priced against club dues, not against costs.** $25
    an athlete works because a club can add $40 to a four-figure season fee
    without a parent noticing. It has never been tested against a club that
    negotiates, against a rec league whose season fee is $200 rather than
    $1,800, or against a competitor undercutting it. The seat tiers it
    replaces are retired rather than deleted, so reversing this is possible.
52. **The sponsorship rebate is tracked but not settled.** The ledger accrues
    and draws down correctly; whether the balance is paid as cash, credited
    against next season, or drawn as software seats is a commercial decision
    nobody has made, and no money moves either way without a processor.
53. **The film curriculum has no videos in it.** Twenty topics are written and
    every one needs a coach to supply a link before an athlete sees anything.
    That is the honest state: choosing clips requires watching them, and this
    environment cannot. Until links are added the film module is still empty
    in practice, however complete the syllabus is.
54. **The clamp drill cannot see a clamp.** It measures the hand speed around
    the movement, not the wrist rotation that traps the ball, and a face-off
    athlete could score well on it while clamping badly. It is a hand-speed
    drill honestly labelled, not face-off coaching.

55. **The goalie drill calls the shot.** Reading a shooter is most of
    goaltending and this trains none of it — the app names the spot, so what is
    measured is the path to a known target. It is a reaction-and-positioning
    drill, and no number it produces belongs anywhere near a save percentage.

56. **It watches hands, not the stick head.** The head sits roughly a foot
    above the top hand, so "high" means the hands got high. A goalie can reach
    the called cell and still not have covered the shot.

57. **Reaction time is measured to the firing line, not to full extension.**
    The rep fires when reach crosses a threshold below full stretch, which is
    consistent across reps and so comparable — but it is not the same quantity
    a stopwatch on the stick head would give, and it is not comparable to
    published reaction figures.

58. **The cue sequence is tamper-proof; the zone is not.** Deriving targets
    from the nonce stops a client choosing easier ones, but the client still
    reports where the hands went and could lie about that — exactly as it could
    about any other count here. The integrity layer is what covers it, not this
    design.

59. **The highlight filter reads titles, not video.** Nothing here can watch
    the clip, so a montage titled "Defensive rotations" sails straight
    through. It raises the cost of putting the wrong thing on the shelf; it
    does not prevent it.

60. **A second look is a weak signal about understanding.** An athlete may
    rewatch because they were interrupted, because a sibling walked in, or
    because they liked it. It says they went back, and the coach-facing text
    is careful to claim nothing more.

61. **Second looks are visible to coaches with no opt-out.** An athlete who
    would rather not have that seen has only one way to avoid it, which is not
    to rewatch — the exact behaviour the feature exists to encourage. The
    notice makes it honest rather than making it optional, and whether that
    trade is right is worth revisiting with real athletes.

62. **Wall-ball patterns are athlete-selected, not measured.** The app counts
    the reps honestly and cannot tell a split dodge from a plain wall ball —
    one camera, no stick, same hand path. They all pay the same for that
    reason, but a coach reading "200 split dodge reps" is reading the
    athlete's own label, not a measurement.

63. **Two of the nine cells are never called.** A ball straight at the chest
    needs the hands to come forward, and forward is what a single camera reads
    worst, so chest-high and hip-high middle are observable but never targets.
    A goalie who only ever gets beaten straight on will not learn it here.

