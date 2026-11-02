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

**Now in the product** (`offdays/distance.py`, `web/static/scene.js` +
`distance.js`): the phone watches the goal and the shooter during the session
and sends the medians; the server fuses goal width, goal height, shooter size,
placement, the ground plane (with the phone's tilt) and the typed distance by
inverse variance, learns the lens per athlete when camera and pace agree, and
the speed carries the distance error. `scenecal.mjs` runs that exact path on
a clip:

```bash
node scripts/shotcal/scenecal.mjs data/shotcal/clips/*.mov --pitch 5
```

On the 7 radar clips (tape 10 yd, phone 1-2 yd behind the spot, default lens):
estimate 8.8-9.7 yd +-0.8, goal found in 5/8 to 10/12 looks, every clip
`camera+set`. The camera reads short by about the yard the phone stood
behind the shooter -- which is the placement rule in the setup hint, not a
bug -- and the shooter-size factor is rough from behind (priced at 55%).

The goal's colour is learned, not fixed (`GoalColour` in scene.js): seeds
for orange / red / yellow / white / dark are tried until the two-posts-and-a-
bar structure appears, the post pixels are sampled, and the window tightens
to that goal in that light; misses widen it back, enough misses reseed.
Checked on IMG_1634 relit with ffmpeg: dim+blue (fixed window 3/6 looks,
adaptive 6/6), warm+bright (6/6, 5/6), hue shifted +25 deg (fixed 0/6,
adaptive 6/6). About 5 ms a look at the work size.

What it still needs, in order:

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

## What does the impact sound like? (`impacts.py`) -- waiting on footage

A per-surface impact rule (net / pipe / wall / rebounder) would tighten the
impact timing and is the only route to a goal-vs-pipe call without the goal in
frame. `impacts.py` prints, per impact the replay found, its peak over the
floor, rise time, ring time and spectral centroid, with the surface from
`truth.csv`'s `note` column where written.

```bash
"$LOCALAPPDATA/offdays-calvenv/Scripts/python.exe" scripts/shotcal/impacts.py
```

On the 7 radar clips (all net, 10 yd): shots median peak 11 dB, rise 10 ms,
ring 50 ms, centroid 281 Hz; the other sounds the mic heard (steps, the ball
dropping, the bucket) median 10 dB, 10 ms, 30 ms, 407 Hz. Overlapping, n=7,
one surface: **nothing to separate yet.** It needs the multi-surface clips
the filming brief already asks for, with `net` / `pipe` / `wall` /
`rebounder` in the note column per shot.

## Would a bigger pose model help? (`extract.py --model full`)

`extract.py --model full --out data/shotcal/extracted_full` extracts with
MediaPipe's `full` model (the product runs `lite`). Replayed on the 7 radar
clips: every mph identical (the swing is the release, so pose does not enter
the timing), and `full` found a pose in FEWER frames than `lite` on 6 of 7
clips (1626: 93 vs 110; 1627: 77 vs 103; 1629: 60 vs 68) -- from behind the
shooter, at night, the bigger model is pickier, not better. Not worth the
phone's battery for shooting. Re-run on side-on footage before deciding for
the quality scores.

## Wall ball rep count on a phone clip (`wallreplay.mjs`) -- first clip, counted right

`wallreplay.mjs` drives the production `RepCounter -> SoundRepCounter` on an
extracted clip for a wall-ball drill (no ShotSpeedCounter; wall ball has no
ShotSpec), and prints what the app would have recorded: pose count, heard
count, per-hand split, period, catch coverage, plus every onset for diagnosis.

```
node scripts/shotcal/wallreplay.mjs --specs "$LOCALAPPDATA/Temp/specs.json" \
     --in data/wallcal/extracted --drill lax_wall_ball_strong
```

**Portrait clips**: a phone held upright writes a landscape sensor frame
with a rotation tag, ffmpeg applies the tag, and the old `probe()` reported
the un-rotated size -- every portrait clip was squashed to 16:9 and the pose
model found a body in 64% of frames. `extract.py` now reads the tag and
scales the LONG side to 1280 (720x1280, what `capture.html` gets upright).
The radar clips were landscape, so none of the shot-speed numbers move.

IMG_5058 (25 s, portrait, phone on the grass ~2 yd behind-left of a
right-handed player, rebounder net ~8 yd away in frame, backyard, birds):

| | pose | sound (what the app records) | by eye |
|---|---|---|---|
| reps | 2 | **12** (12 R / 0 L) | **10** throws, all right-handed |
| frames with pose | 745/757 (98%) | | |
| period | | 1680 ms | ~1.7 s |

The 12 = 10 real throws (every one the loudest sound of its cycle, 40-385x
floor) + 2 phantom reps at 22.89 s and 24.07 s (18x and 15x floor), when the
kid had stopped and was walking to the phone -- the rhythm tracker carried the
beat on through soft sounds (footsteps, stick on grass) because a gap costs
score and a quiet sound still earns 1 - 0.5. The pose counter alone would
have said 2: from behind-left the top-hand signal barely crosses the gate,
which is why wall ball counts from sound.

Lever, NOT shipped on one clip: drop a chosen rep quieter than 1/4 of the
chosen median strength -- here 10/12 at 0.25 and 0.33, 8/12 at 0.5 (too
tight; two real throws at 40-44x are near the 44 cut). Needs clips with
pauses mid-session (a drink, a dropped ball) to prove it does not eat a real
quiet throw, and a brick-wall clip (louder catches). Floor before changing
`sound.js`: 6 clips / 100 by-eye throws, same as the shot bench.

Also unmeasured: the ball detector is not driven by the bench (pixels are not
kept), so `hand_from = ball` drills cannot be replayed yet.

### Second clip: IMG_5059, left hand, same spot -- app 13, true 9

`netshake.py <clip> x y w h [z]` gives an objective truth on rebounder clips:
frame-difference energy inside the net's box (540x960 frame), peaks = the
net being hit. On 5058 it finds the same 10 the eye found (its 11th, z=140,
is the kid walking through the box); on 5059 it finds 9 at 3.60 .. 17.07 s
every 1.6-1.8 s, then nothing -- the kid lost the ball after the ninth, went
out of frame left to fetch it (19.6-21.6 s) and walked to the phone.

| | app (sound) | net shake / eye | note |
|---|---|---|---|
| reps | **13** | **9** | |
| hand | 3 L / 1 R / 9 none | 9 L | from behind-left the top-hand signal is mostly unreadable |
| onsets heard | 20 | | every real throw 10-43x floor; 5058's were 40-385x |

Where the 13 came from: 8 real cycles found (one of them on the catch at
7.19 s rather than the throw at 6.82 s -- same count), the throw at 8.67 s
NOT heard at all (no onset within 0.5 s; a softer left-hand throw, phone
further from the net than the stick side), and 5 phantoms after the last
throw (18.62, 19.87, 21.81, 22.95, 25.52 s: footsteps, stick on grass, the
phone being picked up) carried by the rhythm tracker across 8 s of no
throwing. Net +4.

What this says, across both clips (19 real throws, 25 recorded):
- Every miscount so far is AFTER the kid stopped. The tracker has no notion
  of "the session ended"; it keeps buying soft sounds at the old period
  because MAX_GAP_COST (2) is cheaper than the worth of a quiet sound (0.5).
  The lever is a tail rule, not a loudness rule: stop extending the beat
  once N consecutive chosen sounds are under 1/4 of the chosen median.
  A loudness-only cut (1/4 median) would also have eaten real left-hand
  throws here (10-15x vs median 28x) -- the two clips disagree on it.
- Left-hand throws are quieter from this placement and one was missed
  outright. Not a threshold problem (nothing to choose from); a placement
  one. The app's instruction should put the phone on the STICK side.
- Hand from pose is not usable from behind: 9 of 13 reps 'none'. The
  strong/off-hand drills need the phone side-on or the ball tracker.

Still not shipped: 2 clips / 19 throws against a 6 / 100 floor.

### Third clip: IMG_5060, right hand, D-pole -- app 11, true 10

| | app (sound) | net shake | note |
|---|---|---|---|
| reps | **11** | **10** (3.3 .. 17.6 s, every 1.6 s) | |
| hand | 6 R / 0 L / 5 none | 10 R | |
| throws heard | 8-55x floor | | the loudest sound (445x, 17.76 s) is the 10th ball landing in the head -- a catch, not a throw |

All 10 real throws counted (9 on the throw, the 10th on its catch -- same
count). One phantom at 19.13 s (11x) while he walked to the phone. The long
pole changes nothing the counter sees: same period, same loudness band as
the short stick on the same hand.

**Three clips, 29 real throws, app 36.** Every one of the 7 extras is in
the tail after the kid stopped (2 + 5 + 1 at 11-18x floor); one real throw
was missed (left hand, quiet). The tail rule is the lever; the floor is
still 6 clips.

Tried on the replays (not shipped): "trim chosen reps after the last one
that is both within 1.5 periods of its predecessor and >= 1/4 of the chosen
median" gives 10 / 12 / 11 against 10 / 9 / 10. It fixes 5058 only. On 5059
the phantoms are evenly spaced at the old period and 11-14x floor against a
median of 28x -- indistinguishable from a quiet left-hand throw by spacing
or loudness alone; on 5060 the one phantom (11x) sits one period after the
445x catch. What separates a phantom from a throw on all three is the NET
(netshake sees nothing) and the KID (pose: walking toward the camera, body
growing in frame). The pose counter already has the frames; a "session
over" gate on torso scale / walking cadence is the next thing to bench,
and it is footage-free -- the three extracted clips carry the landmarks.

### Fourth clip: IMG_5062, left hand, D-pole -- app 12, true 10 (phone moved)

The phone is behind-RIGHT this time (stick side for a lefty) and the kid's
body covers the net for most of the clip, so `netshake.py` sees only the
walk-out (3 peaks, all after 23 s). Truth from `stickburst.py` instead
(motion in a sky box above the head: the pole cocks up into it and swings
out, one burst per throw): 10 bursts 4.0-20.3 s at 1.4-1.9 s spacing,
then the walk. Checked by eye at 5 fps across 3.5-21 s: 10 throws, the last
at ~19.9 s, a scoop of the 10th ball at 21.2 s, stick raised and walking
from 21.5.

| | app (sound) | stickburst / eye | note |
|---|---|---|---|
| reps | **12** | **10** | |
| hand | 5 L / 3 R / 4 none | 10 L | 3 wrong-hand reps -- worst of the four |
| throws heard | 18-178x floor | | stick-side placement: louder than 5059's 10-43x |

Extras: 21.95 s (98x) and 23.36 s (17x) -- the scoop/stick-on-ground and the
walk; both after the last throw. The 10 real throws are all there, and
being on the stick side, none was missed (5059, same hand, phone on the
far side, missed one). Period 1820 ms, the slowest of the four -- the pole.

**Four clips, 39 real throws, app 48 (+9, every one after the last throw;
1 missed, far-side placement).** Stick-side placement fixed the miss.
Wrong hand from pose: 0 / 1 / 0 / 3 wrong, 'none' on 9 / 9 / 5 / 4 -- from
behind, the hand is a guess; the app should not record it from pose at
this placement. Side-on or the ball tracker.

`bodyscale.mjs` (torso span per second, 1.00 = session median) on all
four: flat at 0.9-1.1 through every throw, then 1.3 / 1.1 / 1.3 / 1.3
within a second of the last real rep and climbing (1.8-4.3 by the phone).
That is the "session over" signal the sound tracker lacks, and it is in
frames the pose counter already has. Rule to bench next: once the torso
span exceeds 1.25x its session median, stop accepting new reps (the kid is
coming to the phone). On these four it would remove every phantom that
came 1 s or more after the scale crossed -- 5058 both, 5059 the last three
of five, 5060 the one, 5062 both. 5059's first two phantoms (18.6, 19.9 s,
kid out of frame fetching the ball -- no pose at all) need the companion:
no pose for > 1.5 periods = session paused, no reps until a throw-loud
sound (>= median) returns.

Bench truth tools, when the net is hidden: `stickburst.py` (sky box above
the head) and `handpeaks.mjs` (wrist speed from landmarks -- useless from
behind, 1-6 peaks on 10-throw clips; kept as the measurement, not a tool).

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
