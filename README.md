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
python -m pytest tests/ -q          # 433 tests

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
7. **Offline slots are per-drill.** A drill you have never opened online has no
   banked slot, so its first-ever session needs a connection. The app says so
   plainly rather than failing silently.
8. **Web Push needs credentials.** Notifications generate and display in-app
   with nothing configured, but reaching a locked phone needs VAPID keys.
9. **Form quality is pose-only.** It reads how the body moved, not where the
   ball went. A wall-ball rep with perfect mechanics and a bad release still
   scores well, and stick position is invisible to it.
10. **Guardian identity is proven by the invite code alone.** There is no email
    verification, so a code handed to the wrong adult creates a valid account.
    Short expiry, single use, and revocation limit the window; real
    verification is a launch requirement.
11. **Load coefficients are reasoned estimates, not measured values.** The
    per-drill numbers in `catalog.py` are a defensible ordering rather than
    validated physiology, and the app sees only self-directed work — so the
    workload picture is directionally useful and absolutely not a clinical
    assessment.
