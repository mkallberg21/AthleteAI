# Notes for the app store reviewers

Paste the "Notes for review" section into App Store Connect and Google Play
Console. **The sign-in codes are not in this file on purpose**: generate them
when you submit (below), paste them into the store's review form, and rotate
them afterwards.

## Before you submit: make the review account

The demo program is generated, not real: no child in it exists and no video is
involved. **Do not create it in the production database while real families are
using it.** Either use a separate staging copy of the app, or create it in
production only once, label it clearly, and delete it after review.

```
python scripts/seed_demo.py --db review.db
OFFDAYS_DB_PATH=review.db uvicorn offdays.api:app
```

It prints a sign-in code for each person. A reviewer needs two:
- **the parent** (Travis Anderson): the main path, and where "Delete my account" lives
- **an athlete** (any name in the list): the training screen

Tell the reviewer the codes, and that on the first screen they tap the role
button (Parent or Athlete) and paste the code.

## Notes for review (paste into the store form)

> 0FFDAYS helps young athletes train on their own and counts their reps with
> the phone's camera and microphone. **Video and audio are processed on the
> device and are never uploaded or recorded.** Only counts are sent.
>
> A parent or guardian signs up first and must say yes before a child can
> train. We provide a demo parent and a demo athlete (codes below). Everything
> in the demo is generated; no real child's data is involved.
>
> **To review:**
> 1. Open the app. Tap **Parent**. Paste the parent code. Skip the first-visit
>    walkthrough or follow it.
> 2. You will see the child's results and the permission toggles (the parent
>    controls what the child can do).
> 3. **Account deletion:** scroll to the bottom of the parent page. **Delete my
>    account** deletes the parent's account; a checkbox chooses whether the
>    child's data is deleted too. "Delete their data" on the child's card
>    removes the child's training data.
> 4. To see the athlete side, sign out, tap **Athlete**, paste the athlete code,
>    and choose a drill. The camera asks for permission; point it at any
>    moving object to see counting. A real wall-ball session is not needed.
> 5. Privacy policy: the link at the bottom of the first screen and parent page.
>
> **Camera and microphone** are used only to count reps while a drill is
> running. **Motion** is used to check the phone is propped up steady.
> **Notifications** (when enabled) remind a family about training; they can be
> refused with no loss of function.
>
> Directors and coaches run their programs on our website, not in this app.
>
> Parent code: [PASTE HERE]    Athlete code: [PASTE HERE]

## Things a reviewer is likely to ask, and the honest answer

| Question | Answer |
|---|---|
| Is this just a website in a wrapper? | It is a shell around our web app, with native camera, microphone and motion access and an offline screen. The product logic is shared with the website on purpose, so a fix reaches every phone without a store review. |
| Who is it for? | Families and clubs. Athletes are children; a parent must consent first. |
| Does it collect data from children? | Name, birth year, and training counts, only after a parent says yes. No location, photos, contacts or advertising IDs. |
| Why a camera? | To count reps on the device. Nothing is uploaded. |
| Can a parent delete everything? | Yes, from inside the app, as described above. |
| Third-party SDKs or ads? | None. |

## Before the reviewer arrives

- [ ] A privacy policy that a lawyer has read, with the company name, address and email filled in.
- [ ] Support URL and a monitored support email (both stores require one).
- [ ] Rep counting verified inside the app on a real phone. A reviewer who opens
      the camera and sees nothing happen will reject it.
- [ ] The sign-in codes pasted into the review form; rotate them afterwards.
