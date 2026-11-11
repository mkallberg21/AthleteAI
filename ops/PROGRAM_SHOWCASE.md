# Terms at sign-up and the programs wall

A director cannot start a program without ticking the box that agrees to the Program Terms
(`offdays/web/static/terms.html`). One of the terms is that the program's name, sport and badge
may be shown on the 0FFDAYS website. The wall of programs there is built from that permission.

## What is stored

On `organizations`: `terms_accepted_at`, `terms_version` (see `Store.TERMS_VERSION`),
`showcase_ok` (the director's switch) and `showcase_approved_logo` (the image 0FFDAYS approved).
Programs created before this shipped have no acceptance and `showcase_ok = 0`, so none of them
appear until the director turns it on.

## Who can do what

| Who | What |
|---|---|
| Director, at sign-up | Must tick the terms box. Permission starts on. |
| Director, Settings > badge | "Show my program on the 0FFDAYS website" switch. Off removes the program at once. |
| Operator, `/admin` > Website wall | Sees each waiting badge as an image, then Approve or Do not use. Live ones can be taken down. |
| Anyone | `GET /api/programs/showcase`: name, sport and image address only. No ids, counts or people. |

## Rules the tests hold

* Nothing is public until the operator has looked at that exact image and approved it.
* Approval belongs to the image, not the file name. A new upload, or removing and re-adding the
  badge, clears it, even though the file is always called `org-<id>.<ext>`.
* Approving while the director has withdrawn does nothing.
* "Do not use" marks that exact image as declined; it is not queued again until a different one is uploaded.
* A file that is missing on disk is never listed. Test programs ("UI health") are never listed.
* Coaches cannot read or change the switch. Only the operator key can review.

## The website

`index.html` in the marketing site reads `/api/programs/showcase` from the app. The section is hidden
when the list is empty or the app cannot be reached, so the page never shows an empty wall.

## Before real programs are shown

The terms are a draft for legal review and have placeholders for the company name, address and
contact email. Fill those in and have a lawyer read them before the first program is approved.
