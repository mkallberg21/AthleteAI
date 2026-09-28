# Guardian verification: options

**The problem.** A guardian account is created by whoever redeems the invite
code (`guardians.redeem_invite`). The code is single-use, expires in 14 days,
can be revoked, and is now throttled against guessing. But nothing checks that
the person redeeming it is the parent the coach meant. A forwarded email, a
code read off a phone screen, or a typo in the roster's parent-email column
creates a valid account. That account can see the child's training, wellness
flags and monthly report, and can **grant or revoke consent** and **export or
erase** the child's data. README "Known limitations" #27 already calls real
verification a launch requirement.

What the code already gives us to build on:

- `guardian_invites.email`: the roster's parent email is stored on every
  invite (`create_invite(..., email)`).
- `mailer.enqueue`, with retry, suppression and signed tokens
  (`mailer.unsubscribe_token` shows the HMAC pattern using `OFFDAYS_SECRET`).
- The guess throttle (`throttle.py`), which already covers the redeem endpoint.
- An append-only consent ledger, so a later verification step can gate *which*
  consents count without rewriting history.

---

## Option A: Accept the risk for the pilot, with guardrails (0.5 day)

Keep code redemption as the proof and add process plus visibility:

- Coach hands codes out **in person** at a team meeting (printed slip per
  family), not by forwarding email.
- Invite TTL cut from 14 days to 3 for the pilot (`INVITE_TTL_DAYS`).
- Coach dashboard shows, per athlete, *who* redeemed and when (data exists:
  `redeemed_by`, `redeemed_at`). A wrong adult is noticed at the next practice.
- Director can revoke a guardian link.

**Fits:** a 35-kid pilot where the coach knows every parent by sight.
**Doesn't fix:** anything at scale, or a code reaching the wrong household.

## Option B: Email possession check on redeem (1–2 days) ← recommended

The invite is only redeemable through a link sent **to the email on the
roster**. Proving you can read that inbox is the verification.

1. On import, instead of (or as well as) a printed code, send the invite as an
   email to `guardian_invites.email` containing a signed, single-use link
   (HMAC over invite id + expiry with `OFFDAYS_SECRET`, same pattern as
   unsubscribe tokens).
2. Redeeming by **link** marks the guardian `email_verified_at = now`.
3. Redeeming by **bare code** (no link) still works, so a family without email
   isn't locked out, but the guardian is created **unverified**:
   - they can view training and the report;
   - they **cannot** grant `coach_video` or `leaderboard_name`, export, or
     erase until verified (a "verify your email" banner re-sends the link to
     the roster address, *not* to an address they type).
4. Schema: `users.email_verified_at TEXT` (add to `db.ADDED_COLUMNS` so
   upgraded DBs get it, since that bug class was just fixed in 350d927).
5. Tests: link redeem → verified; code redeem → unverified; unverified cannot
   export/erase/grant sensitive scopes; tampered/expired link refused; link
   single-use; the resend goes only to the roster address.

**Needs:** SMTP configured (it is on the checklist anyway).
**Fixes:** a forwarded code or a wrong household, unless they also have the
parent's inbox. **Doesn't fix:** a wrong email typed into the roster by the
coach. The roster preview should show parent emails so the coach catches that.

## Option C: One-time code by email/SMS at redeem (2–3 days)

After the invite code, send a 6-digit OTP to the roster email (or phone) and
require it. Much the same guarantee as B, with more friction and one more code
for a parent to juggle. SMS adds a paid provider (Twilio etc.), which this
project avoids, so email only. Choose C over B only if parents keep redeeming
on a different device from the one that reads their email.

## Option D: Coach/director approval (1 day, pairs with any of the above)

A redeemed guardian sits **pending** until the athlete's coach taps "Yes, that's
Jordan's mum" on the dashboard. Zero external dependencies, and it uses the
human who actually knows the families. Adds a step for the coach and a delay
for the parent, but in a pilot the coach is motivated and the roster is small.

## Option E: Identity verification service (weeks, paid)

Stripe Identity, Persona and the like are ID-document checks. Overkill for a
youth sports club, it costs money per check, and it's a privacy cost of its
own. Listed only to rule it out.

---

## Recommendation

**Pilot:** A (handout in person, short TTL, redeemed-by on the dashboard) **+ D**
(coach approval). About 1.5 days, no email dependency, and it plays to the
pilot's real strength: the coach knows every family.

**Before a second program / public launch:** B. It is the smallest change
that makes the invite itself the proof, and it reuses mailer + HMAC code
that already exists and is tested.

Decision: ________  Date: ________  (record it in `ops/PRODUCTION_CHECKLIST.md` §6)
