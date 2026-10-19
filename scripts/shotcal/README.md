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

## Distance from the goal frame (`goal.py`)

The biggest error in a shot speed is the typed distance, not the timing: one
pace short at 8 yards is 12% of every speed in the session, and the session
median does not wash out an error every shot shares. A goal is 6 ft wide by
rule, so a camera that can see it knows how far away it is:
`distance = f * 6 ft / goal_width_px`. `goal.py` finds the orange goal in a
clip, measures it, and prints the camera's distance next to the tape's.

```bash
"$LOCALAPPDATA/offdays-calvenv/Scripts/python.exe" scripts/shotcal/goal.py data/shotcal/clips/*.mov --fit-focal
```

What the first seven radar clips said (all tape 10 yd, phone behind the shooter):

| clip | goal px wide | fitted f (share of frame width) | note |
|---|---|---|---|
| IMG_1633 | 87 | 1.176 | |
| IMG_1634 | 85.5 | 1.155 | within 2% of 1633 |
| IMG_1626 | 42 | 0.568 | phone much further back |
| 1627/28/29/32 | - | - | goal cut off at the frame edge |

Two clips from one placement agree on f within 2%, which is the result that
matters: the lens is one number per phone, and 2% of distance is 1.5 mph at
75 -- under the timing error. The rest of the spread is the phone standing a
yard or more behind the spot, which this frame cannot separate from the lens.

What it needs to become a product measurement, in order:

1. **Placement rule**: phone level with the shooting spot, beside the athlete,
   facing the goal, whole goal in frame. The camera's distance is then the
   shooting distance; a phone behind the spot reads long by exactly that much.
2. **One paced calibration per phone** to learn f (or the lens's advertised
   field of view, where the browser exposes it), then every session after is
   measured, not typed. The kid still types nothing; the app says "10 yards"
   and the coach can check it against the tape once.
3. **Clips to prove it**: 6+ at known tape distances (7, 8, 10, 12, 15) from
   one phone with the goal fully in frame, so the fitted f can be shown flat
   across distance. Fewer still gets this table, marked as not enough.

Things it cannot do, said plainly: the shooter's own distance (needs the
camera's pitch, which a head-on square does not carry -- the phone's
accelerometer would, in the product); a goal half out of shot (refused, not
guessed); a non-orange goal (the mask is orange; a white or black goal needs
its own colour, as the ball presets do).

## Can the camera see the ball leave? (`ballsee.mjs`) -- no

A visual "ball departed" moment would let a heard swing with no ball behind it
be dropped before pairing (a fake, a stick tap, a shot that hit nothing).
`ballsee.mjs` runs the production ball detector (`ballvision.js`, at the work
size the phone uses) over a clip and prints detections around each heard
release.

```bash
node scripts/shotcal/ballsee.mjs --clip data/shotcal/clips/IMG_1634.mov
```

On the radar clips (phone 10+ yd from the goal, 1280 wide, work frame
509x255): expected ball radius **1.8 px**, under the detector's own 2.2 px
floor (`MIN_RESOLVABLE_RADIUS_PX`) in 71 of 75 frames, **0 detections in 89
frames** on every clip tried. That is the detector refusing by design, not
failing: a 6.35 cm ball a dozen yards off is three pixels across, and at 75
mph it moves about a metre between 30 fps frames. The cross-check is not
buildable from this placement. It would need the phone within ~3 yd of the
release (side-on, where the goal is out of frame) -- the opposite of what the
goal-frame distance needs -- or a much higher-resolution work frame, which the
cheapest phones cannot run per frame. Parked; the mic's swing + impact pairing
stays the release signal.

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
