# Store listing and compliance notes

Working notes for the Apple App Store and Google Play submissions. Nothing here
has been submitted, and none of the store accounts exist yet. **Every policy
statement below must be re-checked against the store's current rules on the day
you submit: they change, and this was written from memory of them, not from a
live read.**

## What the app is

0FFDAYS: a phone counts a young athlete's reps (wall ball, shooting) using the
camera and microphone, and their coach sees that the work was done. A parent
signs up first, says yes, and sends the child a link.

**Short description (80 chars):** Count your reps. Your video never leaves your phone.

**Long description (draft):**
> Train on your own, get credit for it. Prop your phone up, pick a drill, and
> 0FFDAYS counts your reps. Your coach sees that you put the work in.
>
> Built for families and clubs. A parent or guardian signs up first, decides
> whether their athlete can train, and sends them a link. Nothing starts until
> they say yes.
>
> Your video never leaves your phone. It is analysed on the device and is not
> uploaded or stored. Only the counts are sent: reps, which hand, how long.
>
> Directors and coaches run their program from the website.

Keywords: lacrosse, wall ball, training, youth sports, shooting, reps, team.

## Who the users are, and why it matters

Athletes are children, many under 13. That puts the app under:

- **US COPPA** (children under 13): needs verifiable parental consent before
  collecting personal information. The parent-first flow is built for this, but a
  lawyer must confirm it meets "verifiable" under the FTC rule.
- **Apple:** guideline 1.3 (Kids Category) and 5.1.4 (children's privacy). If the
  app is placed in the Kids Category there are strict limits: no third-party
  analytics or advertising, and a parental gate before any link out of the app.
  Decide on purpose whether to apply for the Kids Category. It is not required, and
  the app is aimed at families and clubs as much as at children.
- **Google Play:** the Families policy applies if children are a target audience.
  It requires declaring the target age groups, and limits SDKs and data collection.

Do not pick an age range casually. Declaring "ages 8 and up" is a promise about
who the app is for, and it changes which rules apply.

## Data the stores ask you to declare

Apple "App Privacy" and Google "Data safety". Based on `offdays/web/static/privacy.html`:

| Data | Collected | Linked to the user | Used for | Shared |
|---|---|---|---|---|
| Name | Yes | Yes | App functionality | No |
| Email address | Yes (parents, coaches) | Yes | App functionality | No |
| Phone number | Yes (parents, coaches) | Yes | App functionality | No |
| Birth year (not full date) | Yes | Yes | App functionality | No |
| Fitness / exercise data (reps, drills) | Yes | Yes | App functionality | No |
| Videos | **Only** if a parent turns on clip sharing, one clip at a time | Yes | App functionality | No |
| Audio | Not collected: processed on device | | | |
| Precise location | No | | | |
| Contacts, photos, browsing history | No | | | |
| Advertising or tracking data | No | | | |

Tracking: **none.** Say "No" to tracking in Apple's App Tracking Transparency.
Encryption: standard HTTPS only (`ITSAppUsesNonExemptEncryption` is already `false`).

## Known gaps that will block or delay review

1. ~~No in-app way for a parent to delete their own account.~~ **Built.** The
   parent portal has "Delete my account" (`POST /api/guardians/erase-account`).
   The parent chooses whether their athlete's data goes too; an athlete with
   another parent is never deleted by it, and a child whose only parent is
   gone is paused. Apple 5.1.1(v) and Google both want this reachable inside
   the app: a reviewer has to be able to find it, so mention where in the
   review notes (parent portal, bottom of the page).
2. **The privacy policy is a draft** with a placeholder company name, address and
   email. It must be reviewed by a lawyer who handles children's privacy.
3. **No reviewer login.** Apple and Google reviewers need a way in. Create a demo
   program with a parent already signed up and give them the link in the review notes.
4. **Camera, microphone and motion inside the app shell are untested** (see
   `mobile/README.md`). If rep counting does not work in the shell, there is no app.
5. **Apple 4.2 (minimum functionality).** An app that is only a website gets
   rejected. This one uses the camera, microphone and motion sensors, which helps,
   but there is no guarantee. Push notifications would help further.
6. **Directors and coaches use the web.** That is fine, but the store listing and
   screenshots should show the athlete and parent experience, which is what the
   app is for. A reviewer who signs in as a director will see a dense dashboard
   built for a computer.

## Accounts and costs (none created yet)

| | Cost | Notes |
|---|---|---|
| Apple Developer Program | $99 per year | Needs an Apple ID. An organization account needs a D-U-N-S number (free, takes days to weeks). An individual account is faster but shows your personal name as the seller. |
| Google Play Console | $25 once | A new personal account must run a closed test with 12 testers for 14 days before it can go to production. An organization account does not. Check the current rule. |
| A Mac, or a cloud Mac | Varies | Required to build for iPhone. |

## Order of work

1. Test the shell on a real Android phone: camera, microphone, motion. (Needs a JDK and Android Studio.)
2. ~~Build in-app deletion of the parent's own account.~~ Done.
3. Lawyer review of the privacy policy; fill in the contact block.
4. Real app icon (1024x1024) and screenshots in each store's sizes.
5. Create the store accounts; set up the demo reviewer program.
6. TestFlight and Google internal testing with a few real families.
7. Submit.
