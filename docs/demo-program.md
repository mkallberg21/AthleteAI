# The demo program

`scripts/seed_demo.py` builds a complete, believable lacrosse club so the
product can be shown without a real one. Everything below is generated — no
child in it exists, and no video is involved at any point.

```bash
python scripts/seed_demo.py --db demo.db
OFFDAYS_DB_PATH=demo.db uvicorn offdays.api:app --reload
```

The script prints a sign-in token for every person it creates. Paste one into
`localStorage.setItem('offdays.token', '<token>')` on any app page.

## The club

**Nashville Dogs**, one squad: **2031 Red** — an age-group name, so "2031" is
the graduation year and the whole roster shares a school year rather than
spanning three.

| Person | Role | Sees |
| --- | --- | --- |
| Joel White | Director | The whole program, and can switch to any squad |
| Coach Tommy, Coach Matt, Coach Mike | Coach | Only the teams they are assigned to |
| Travis Anderson | Guardian | Scott Anderson only, and only what consent allows |

The director/coach difference is enforced on the request rather than hidden in
the page: a coach carries `team_ids` and every query runs through
`Principal.scope_filter()`; a director carries `None`. `tests/test_access.py`
covers a coach reaching for another team's athlete and a director reaching any.

> **Caveat worth knowing.** With one squad seeded, Joel's team selector lists
> "All teams" and "2031 Red", so the distinction is real but invisible in a
> screenshot. Seed a second team to demonstrate it visually.

## The roster

Thirteen athletes, each carrying a behaviour some part of the dashboard exists
to catch. That is the point of the seed — a roster of thirteen healthy,
identical athletes demonstrates nothing.

| Athlete | Position | What it demonstrates |
| --- | --- | --- |
| Scott Anderson | Midfield | Trains hard, never rests — the workload warning |
| Ryder Kallberg | Attack | Doing it right: steady, balanced, long streak |
| Gray Freeman | Midfield | Badly neglected weak hand, and frames badly — fills the review queue |
| Dane Early | Attack | Volume up 172% on last week — the load advisory |
| Finn Cannan | Defense | Quiet a fortnight — the nudge list |
| Parker Browne | Midfield | Half reps, form falling apart, then three weeks of nothing |
| Tanner Dobyns | Attack | Best on both counts — what the standings should reward |
| Rush Corn | Defense | Weekend-only trainer — a pattern, not a failing |
| Miles Herndon | Long-Stick Midfield | Visibly improving week on week |
| Ben Amden | Midfield | Bursts and gaps — the hardest kind to notice unaided |
| Fite Paine | Face-Off | Joined this week: almost no history, the state demos forget |
| Warren Richards | Goalie | Hands quicker to one side — a pattern, never a mark out of ten |
| Cole Dretler | Goalie | Fewer sessions, even on both sides |

Gray Freeman is seeded **without guardian consent**, so the leaderboard's
name-masking is visible rather than merely claimed.

## Drills

A lacrosse program is offered **36** of the 89 shipped drills: its own 11 plus
the 25 general conditioning drills, its own sport first. Other sports' work is
not offered at all — see `drills.for_sport()`.

## Film — "Lacrosse IQ"

Five clips, with an uneven spread of who has watched them, because a coverage
screen where everyone has seen everything demonstrates nothing:

| Clip | Reach |
| --- | --- |
| Sliding from the crease | widest — most of the squad |
| Man-down: the rotation | most |
| Clearing under pressure | about half |
| Riding as a unit | a few |
| Off-ball cutting | newest, barely anyone |

Two carry a comprehension question, so the per-clip check result has something
to report.

Clips use the `link` provider on a `.invalid` host. An eleven-character
YouTube id invented for a demo can collide with somebody's real video, and
`.invalid` is reserved precisely so it never resolves — nothing here points at
anyone's content.

The coverage view is named from the program's sport, so a hockey club sees
"Hockey IQ". It is grouped by clip, never by athlete, and names inside a
bucket are alphabetical rather than ordered by minutes: the same rows sorted
athlete-first are a list of who is behind, and get read that way whatever the
heading says.

## Capturing the screens

The screenshot pack is built from a running server against this seed. Two
things are worth knowing before regenerating it:

- **The camera cannot run in a sandbox.** The pose model is fetched from a CDN
  that is usually blocked, so the capture screen's video panel is blanked in
  the screenshots rather than shown as a fake test pattern or a network error.
  Both would say something untrue about the product.
- **Match panels by exact title.** `Roster` is a substring of `Keep a roster in
  step` and `Import a roster`, and a loose match silently screenshots the
  wrong card.
