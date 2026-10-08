# Shot-speed calibration bench

Checks the app's shot speed against a radar gun, using the **production code**
(`counter.js` -> `sound.js` -> `shotspeed.js`) on footage filmed the way the
app is used. Nothing here is a second implementation: if the bench says 54 mph,
the phone would have said 54 mph.

The number the app shows today is unverified. It is the ball's average speed
over the flight (release seen by the camera, impact heard by the mic, distance
typed by the kid), and it is expected to read **under** a radar gun, which
clocks the ball at the stick. How far under, and how much it scatters, is what
this bench measures. Until it has run on enough clips, every speed the app shows
stays labelled approximate.

## Film it like the app sees it

- Phone propped **beside the shooter, side-on**, 1-3 yards away, where the app's
  phone would stand. Camera sees the whole body; mic hears the net/wall.
- A **marked spot**: tape at 8 yards (also 6 and 10/12 if you can). One clip per
  distance. Note the distance; the bench needs it per clip.
- **Radar gun behind the goal** reading each shot. Say the reading out loud on
  camera or write it down in shot order. Hits only -- a shot that misses
  everything makes no sound and the app cannot time it (mark it `wide`).
- Normal phone video, 30 fps, sound ON. 6-15 shots per clip, a second or more
  between shots. No slow-mo, no editing, no music.
- Need **6+ clips and 30+ clocked shots** before anything in the product
  changes. Fewer still gets a report, marked as not enough.

Footage of athletes stays on this machine. `data/` is gitignored; nothing in
the bench uploads.

## Run

```bash
# once: MediaPipe in its own venv (the server never needs it)
uv venv --python 3.11 "$LOCALAPPDATA/Temp/calvenv"
uv pip install --python "$LOCALAPPDATA/Temp/calvenv/Scripts/python.exe" mediapipe numpy

# 1. clips -> landmarks (30 fps, 1280 wide, same model the browser loads) + audio
"$LOCALAPPDATA/Temp/calvenv/Scripts/python.exe" scripts/shotcal/extract.py data/shotcal/clips/*.mp4

# 2. drill specs, as the browser receives them
.venv/Scripts/python.exe -c "import json; from offdays.drills import ALL_DRILLS; print(json.dumps([d.to_dict() for d in ALL_DRILLS]))" > "$LOCALAPPDATA/Temp/specs.json"

# 3. truth: one row per shot, in order, as the eye and the gun saw it
#    data/shotcal/truth.csv
#    clip,shot_no,radar_mph,distance_yd,hand,note
#    shots_8yd_a.mp4,1,58,8,right,
#    shots_8yd_a.mp4,2,,8,right,wide

# 4. compare, and sweep the release thresholds
.venv/Scripts/python.exe scripts/shotcal/fit.py --truth data/shotcal/truth.csv --sweep
```

`replay.mjs` can be run alone to see every onset heard and every release seen
for one clip (`--clip <stem>`), which is how a shot the pairing missed gets
diagnosed.

## What comes out, and what to do with it

| Figure | Meaning | Action |
|---|---|---|
| heard / shots by eye | the mic + rhythm grouping found the shot | low: phone too far from the net, or `ONSET_RATIO`/`min_cycle_ms` in sound.js |
| timed / heard | a release was paired with the impact | low: release detector thresholds -- the sweep table says which |
| bias (mph) | systematic app - radar; negative is expected | a stable ratio becomes a declared correction on `ShotSpec`, applied identically in `shotspeed.js` and `shotspeed.py` |
| MAD / mean abs error | scatter | the 33 ms frame on the release dominates; sub-frame release estimation is the next lever |
| extra sounds counted as shots | stick taps, pipes, voices grouped as shots | sound.js grouping, not shot speed |

Every change to the product that comes out of this is a **single-number change
with the before/after table quoted in the PR**, and the radar-verified claim
goes into `shotspeed.LIMITS` wording only once the bench has met the floor.
