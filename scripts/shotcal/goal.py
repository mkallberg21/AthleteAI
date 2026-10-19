"""Measure the shooting distance from the goal frame instead of the kid's pacing.

The biggest error in a shot speed today is not the timing: it is the distance
the athlete typed. One pace short at 8 yards is 12% of the distance and 12% of
every speed in the session -- about 9 mph at 75 -- and because every shot in
the session shares it, the session median does not wash it out.

A lacrosse goal is a known object, 6 ft between the posts by rule. Seen by a
camera of focal length f (pixels), a goal W pixels wide is at

    distance = f * goal_width / W

from the camera. So if the phone is propped LEVEL WITH THE SHOOTING SPOT,
facing the goal -- beside the athlete rather than side-on -- the camera's own
distance to the goal plane is the shooting distance, and nothing is typed.
Beside, not behind: a phone a yard behind the spot reads a yard long.

Two things this frame does not give, found out on the radar clips:

  * The SHOOTER's distance, as opposed to the camera's. Putting the athlete's
    feet on the ground plane needs the camera's pitch, and a square seen
    head-on carries no pitch at all -- a phone low and level and a phone high
    and tilted down put the goal on the same pixels. In the product the
    phone's own accelerometer knows the pitch; on a clip nothing does. Hence
    the placement rule above, which needs no pitch.
  * The focal length. One planar square recovers f only when the view is
    angled enough to show perspective (`--fit-focal` reports how much), and a
    phone facing the goal shows none. f is therefore a per-phone constant to
    be learned once: `--fit-focal` finds the f that reproduces the tape on
    each clip and prints the spread, which is the question that matters --
    is it one number per phone? If it is, the product calibrates it with one
    paced session and measures every session after.

This is a bench tool: it runs on the clips in data/shotcal and prints what the
camera would have said next to what the tape said. Nothing in the product
reads it until the bench shows it is within the timing error.

    "$LOCALAPPDATA/offdays-calvenv/Scripts/python.exe" scripts/shotcal/goal.py \
        data/shotcal/clips/*.mov --truth data/shotcal/truth.csv --fit-focal
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import cv2
import numpy as np

#: Regulation goal: 6 ft between the inside of the posts, 6 ft under the bar.
GOAL_FT = 6.0
#: Pipe outside diameter on a steel practice goal, so the OUTER square the
#: orange mask finds is this much wider than the regulation inside measure.
PIPE_IN = 2.0
YD_PER_M = 1 / 0.9144

#: Orange, in OpenCV's 0-180 hue. Measured on the floodlit radar clips: the
#: pipes read hue 6-15, saturation 65-150, value 150-230; the net behind them
#: is the same hue and a little dimmer and fills the square in, which is
#: useful -- a filled square is one blob where an outline is four thin ones.
#: A daytime clip may need the hue widened.
ORANGE_LO = np.array([3, 55, 100])
ORANGE_HI = np.array([20, 255, 255])

#: The orange sideline runs through the goal's feet on every clip and joins
#: the two into one blob. It is a thin horizontal band, so an opening with a
#: tall thin kernel removes it and leaves anything taller than this.
SIDELINE_PX = 14

#: Frames sampled across the clip for the goal. The camera does not move, so a
#: median over a dozen frames beats any single one, and a ball or a body
#: passing in front of a post is voted out.
GOAL_SAMPLES = 12


def goal_width_m() -> float:
    return (GOAL_FT * 12 + PIPE_IN) * 0.0254


def find_goal(frame: np.ndarray) -> dict | None:
    """Bounding box of the largest orange, roughly square thing in frame.

    None when there is no such thing, and None when the best candidate touches
    the frame edge: a goal half out of shot has no width to measure, and a
    confident number from half a goal is the failure this whole script exists
    to remove.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, ORANGE_LO, ORANGE_HI)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((SIDELINE_PX, 1), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((1, SIDELINE_PX), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    H, W = mask.shape
    best = None
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w < 25 or h < 25:
            continue
        # A goal is square head-on and narrower from the side; a cone or a
        # pinnie is neither big enough nor this shape.
        if not 0.5 <= w / h <= 1.8:
            continue
        if best is None or w * h > best["area"]:
            best = {"area": int(w * h), "x": int(x), "y": int(y), "w": int(w), "h": int(h),
                    "clipped": bool(x <= 0 or y <= 0 or x + w >= W or y + h >= H)}
    return best


def sample_frames(path: Path, n: int):
    cap = cv2.VideoCapture(str(path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    for i in np.linspace(0, max(total - 1, 0), n).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, frame = cap.read()
        if ok:
            yield frame
    cap.release()


def goal_in_clip(path: Path) -> dict:
    """Median goal box over the sampled frames, with how many frames saw one."""
    boxes, size, clipped = [], (0, 0), 0
    for frame in sample_frames(path, GOAL_SAMPLES):
        size = (frame.shape[1], frame.shape[0])
        g = find_goal(frame)
        if g is None:
            continue
        if g["clipped"]:
            clipped += 1
            continue
        boxes.append([g["x"], g["y"], g["w"], g["h"]])
    out = {"size": size, "frames": len(boxes), "clipped_frames": clipped}
    if len(boxes) >= GOAL_SAMPLES // 2:
        med = np.median(np.array(boxes, dtype=np.float64), axis=0)
        out.update(x=med[0], y=med[1], w=med[2], h=med[3])
    return out


def perspective(box: dict, frame: np.ndarray) -> float:
    """How much of a trapezoid the goal is: |left post - right post| / mean.

    Zero head-on. Only a goal seen at an angle can give up the focal length,
    and this says whether that is on offer.
    """
    # Post heights from the mask's column extents at each side of the box.
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, ORANGE_LO, ORANGE_HI)
    x0, x1 = int(box["x"]) + 1, int(box["x"] + box["w"]) - 2
    y0, y1 = int(box["y"]), int(box["y"] + box["h"])

    def post_height(x: int) -> float:
        ys = np.nonzero(mask[y0:y1 + 1, max(x - 1, 0):x + 2].any(axis=1))[0]
        return float(ys.max() - ys.min()) if len(ys) else 0.0

    hl, hr = post_height(x0), post_height(x1)
    return abs(hl - hr) / max((hl + hr) / 2, 1.0)


def distance_yd(width_px: float, f_px: float) -> float:
    return f_px * goal_width_m() / width_px * YD_PER_M


def read_truth(path: Path | None) -> dict[str, float]:
    if not path or not path.exists():
        return {}
    out: dict[str, float] = {}
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("distance_yd"):
                out[Path(row["clip"]).stem] = float(row["distance_yd"])
    return out


def solve_clip(clip: Path, args, truth: dict) -> dict:
    stem = clip.stem
    g = goal_in_clip(clip)
    row = {"clip": stem, "goal_frames": g["frames"], "tape_yd": truth.get(stem),
           "frame_w": g["size"][0]}
    if "w" not in g:
        row["error"] = ("goal cut off at the frame edge" if g["clipped_frames"] >= GOAL_SAMPLES // 2
                        else "goal not found")
        return row
    row.update(width_px=round(g["w"], 1), width_frac=round(g["w"] / g["size"][0], 4))
    first = next(sample_frames(clip, 1))
    row["perspective"] = round(perspective(g, first), 3)
    if args.focal is not None:
        row["f_used"] = args.focal
        row["camera_yd"] = round(distance_yd(g["w"], args.focal * g["size"][0]), 2)
    if args.fit_focal and truth.get(stem):
        # f such that the camera's distance equals the tape, as a share of
        # frame width so phones at different resolutions compare.
        row["f_fit"] = round(truth[stem] / YD_PER_M * g["w"] / goal_width_m() / g["size"][0], 3)
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("clips", nargs="+", type=Path)
    ap.add_argument("--truth", type=Path, default=Path("data/shotcal/truth.csv"))
    ap.add_argument("--focal", type=float, default=None,
                    help="focal length as a fraction of frame width; the per-phone constant")
    ap.add_argument("--fit-focal", action="store_true",
                    help="per clip, the focal length that reproduces the tape distance")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    truth = read_truth(args.truth)
    rows = [solve_clip(c, args, truth) for c in args.clips]

    print(f"{'clip':<12}{'goal':>5}{'w_px':>7}{'w/W':>7}{'persp':>7}{'f':>6}{'camera':>8}{'tape':>6}{'f_fit':>7}")
    for r in rows:
        if "error" in r:
            print(f"{r['clip']:<12}  {r['error']}")
            continue
        g = lambda k, w: (str(r[k]) if r.get(k) is not None else "-").rjust(w)
        print(f"{r['clip']:<12}{g('goal_frames', 5)}{g('width_px', 7)}{g('width_frac', 7)}"
              f"{g('perspective', 7)}{g('f_used', 6)}{g('camera_yd', 8)}{g('tape_yd', 6)}{g('f_fit', 7)}")
    fits = [r["f_fit"] for r in rows if r.get("f_fit")]
    if len(fits) >= 2:
        mean = sum(fits) / len(fits)
        spread = (max(fits) - min(fits)) / mean
        print(f"\nfitted focal length across {len(fits)} clips: mean {mean:.3f} of frame width, "
              f"spread {spread * 100:.1f}%. At one fixed f the camera's distance would scatter "
              f"by the same share: +-{spread * 50:.1f}% of the distance, "
              f"+-{spread * 50 * 0.75:.1f} mph at 75.")
        print("A spread this size is the phone's placement relative to the spot as much as "
              "the lens; the clips were not filmed with the phone level with the shooter.")
    meas = [(r["camera_yd"], r["tape_yd"]) for r in rows if r.get("camera_yd") and r.get("tape_yd")]
    if meas:
        errs = [c - t for c, t in meas]
        print(f"camera vs tape over {len(errs)} clips: mean {sum(errs) / len(errs):+.2f} yd, "
              f"max |err| {max(abs(e) for e in errs):.2f} yd")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
