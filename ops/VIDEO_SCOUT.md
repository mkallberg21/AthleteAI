# Suggested videos (the weekly YouTube scan)

Every Monday the server looks on YouTube for lacrosse clips about **reading the game** and lists the
ones that qualify on each coach's dashboard under **Suggested videos**. A coach watches one (the title is a
link), edits the "what players should watch for" line if they like, and taps **Add for my players** or
**Not for us**. **Nothing reaches an athlete unless a coach taps Add.**

## Why only YouTube

A suggestion has to become a clip an athlete can watch **with attention tracking** and that a coach can
verify. Only YouTube gives that (IFrame API: position, mute, visibility, rate). TikTok, Instagram and
Facebook have no search a server can use without a reviewed developer account and no embed with playback
telemetry, and give nothing to check that someone is teaching. A coach can still paste any link by hand:
the existing "link" provider opens it with no tracking and is labelled weaker.

## What the machine checks, and what it cannot

For every candidate (`offdays/video_scout.py: assess`): public, embeddable, not age-restricted, English,
15 s to 200 s (the 19+ band's 240 s is adults-only and is refused), lacrosse in the **title or tags** (not
only the description), no highlight / recruiting / vlog wording, none of the box, women's, indoor or other
sports wording, and no swearing in the title, tags or the start of the description. It is placed by its own
length into the film age caps, and a coach may raise the age but never lower it below what the length allows.

**Not checked: whether the coaching is correct.** That is why a person watches it first and why nothing is
added automatically. Captions are not read (the API does not return them without the video owner's
permission), so unlike the starter shelf nobody has confirmed a person is speaking: the coach's preview does.

## How a program uses it

| Action | What happens |
|---|---|
| Open the title | The video on YouTube, to watch first |
| **Add for my players** | Creates an ordinary clip through `Store.create_clip` (age caps and the highlight refusal bind), credited to the uploader, first in every eligible player's list. A goalie clip is added for goalies only |
| **Not for us** | Gone for good for that program (`video_suggestion_decisions`); a rescan never brings it back. Other programs still see it |

Suggestions are global rows; each program's decisions are its own. A video a program already has, or removed,
is not suggested to it again. A suggestion that YouTube later stops returning as playable is withdrawn at the
next scan (and a failed lookup never empties a coach's list).

## Switching it on (one-off, about five minutes, free)

1. **Get a key.** console.cloud.google.com -> create a project -> APIs & Services -> Library -> enable
   **YouTube Data API v3** -> Credentials -> Create credentials -> API key. Edit the key and **restrict it to
   the YouTube Data API v3 only** (no website or IP restriction: the server calls from its own address).
2. **On the server** (`ssh k6-server`; the prompt must read `jason@k6-prod-server`):

   ```
   cd ~/offdays
   python3 scripts/setup_youtube.py
   ```

   It asks for the key at a **hidden prompt** (paste, Enter; nothing shows), checks it with one tiny request,
   writes only `OFFDAYS_YOUTUBE_API_KEY` into `~/offdays/infra/.env.prod` (mode 600) and recreates the app
   container. It prints how many characters it received, never the key. **Never paste the key into chat.**
3. **Try it:** `podman exec offdays_app_1 python scripts/run_video_scout.py`. It prints how many it searched,
   added and turned away, and why.

`~/offdays` on the server is a deploy copy, not a git checkout, so the scripts arrive with the next deploy.

## Running it

* **Weekly:** `infra/crontab.offdays` runs `scripts/run_video_scout.py` Mondays 06:17 UTC. Without a key it prints
  "no OFFDAYS_YOUTUBE_API_KEY set" and exits 0.
* **Cost:** 12 searches a run x 100 units + a few lookups ~ 1,300 of the free 10,000 units a day, once a week.
  Each run covers a different slice of 28 queries, so every query gets a turn over about three weeks.
* **Limits:** at most 40 suggestions pending at once; the best-ranked are kept when there is not room for all.
* **If quota runs out or the network fails,** the run stops quietly, keeps what it found and records why
  (`meta.video_scout_last`).

## The key

Read from the environment only (`CONFIG.youtube_api_key`, `repr=False`). It is sent only to
`www.googleapis.com`. Errors raised from a failed call carry a short reason code and nothing else: the
original exception, whose text contains the request URL and so the key, is deliberately not chained
(`tests/test_video_scout.py::TestTheKeyStaysSecret`). If it ever leaks, delete it in Google Cloud and rerun
`setup_youtube.py`.

## Adding another sport

`QUERIES`, `_OTHER_GAME` and `_LACROSSE` are lacrosse-specific, and the dashboard card hides itself for any
other sport. A new sport is a new query list and wording filters, plus a shelf in `iq_shelf.SHELVES` if wanted.
