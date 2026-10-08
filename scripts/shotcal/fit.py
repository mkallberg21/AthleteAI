"""Compare what the app timed against what the radar gun read, and tune.

Reads `replay.mjs` output and a truth file, joins them shot by shot, and reports
the only numbers that matter: how many shots were heard and timed, how far each
timed shot was from the gun, the bias (systematic under-read of a flight
average against a radar's muzzle speed) and the spread. Then, with --sweep,
re-runs the replay across release-detector thresholds and says which setting
is closest -- without ever touching the product's constants itself. Change
them by hand, as a single-number change, once the sweep has made its case.

Truth file: `data/shotcal/truth.csv`, one row per shot the radar clocked

    clip,shot_no,radar_mph,distance_yd,hand,note
    shots_8yd_a.mp4,1,58,8,right,
    shots_8yd_a.mp4,2,61,8,right,hit pipe

`shot_no` is the shot's order in the clip BY EYE (1-based). A shot the phone
did not hear has a truth row and no replay row; that is a miss, counted. A
shot heard but not clocked by the gun has `radar_mph` blank; it still counts
toward detection, not toward error. `distance_yd` per clip must match what the
clip was shot at; the replay is run once per distance.

Standard: the same one `offdays/calibration.py` applies to rep counts. Below
MIN_CLIPS clips or MIN_SHOTS clocked shots the report is printed and marked
"not enough to settle anything"; nothing in the product should change on it.

    .venv/Scripts/python.exe scripts/shotcal/fit.py --truth data/shotcal/truth.csv \
        --specs $LOCALAPPDATA/Temp/specs.json --in data/shotcal/extracted [--sweep]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

#: Same floors as calibration.py: fewer and a median is one afternoon's habits.
MIN_CLIPS = 6
MIN_SHOTS = 30

#: Pairing: a replay shot is the truth shot with the same shot_no. The replay
#: numbers heard shots, truth numbers shots by eye, so a missed shot shifts
#: every later pair by one. `--align` fixes that by matching on order within a
#: clip and letting the user mark misses; until then, the report shows both.

#: Sweep grid for the release detector. Centre is the shipped value.
SWEEP = {
    "minHandSpeed": [1.5, 2.0, 2.5, 3.0, 3.5],
    "minHeight": [-0.5, -0.25, 0.0, 0.25],
}


def read_truth(path: Path) -> dict[str, list[dict]]:
    by_clip: dict[str, list[dict]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            clip = Path(row["clip"]).stem
            mph = row.get("radar_mph", "").strip()
            by_clip[clip].append({
                "shot_no": int(row["shot_no"]),
                "radar_mph": float(mph) if mph else None,
                "distance_yd": float(row["distance_yd"]) if row.get("distance_yd") else None,
                "hand": (row.get("hand") or "").strip() or None,
                "miss": (row.get("note") or "").strip().lower() in ("miss", "wide", "no sound"),
            })
    for rows in by_clip.values():
        rows.sort(key=lambda r: r["shot_no"])
    return by_clip


def run_replay(specs: Path, in_dir: Path, distance: float, params: dict, out: Path) -> dict:
    cmd = ["node", str(HERE / "replay.mjs"), "--specs", str(specs), "--in", str(in_dir),
           "--out", str(out), "--distance", str(distance), "--params", json.dumps(params)]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        raise SystemExit(f"replay failed: {' '.join(cmd)}")
    return json.loads(out.read_text(encoding="utf-8"))


def pair(truth: list[dict], shots: list[dict]) -> list[tuple[dict, dict | None]]:
    """Truth shots in order, each with the replay shot it corresponds to.

    Truth rows marked as misses (wide, no sound) consume no replay shot: the
    phone could not have heard them. Everything else pairs in order.
    """
    out = []
    i = 0
    for t in truth:
        if t["miss"]:
            out.append((t, None))
            continue
        out.append((t, shots[i] if i < len(shots) else None))
        i += 1
    return out


def evaluate(truth_by_clip: dict, replay: dict) -> dict:
    clips = {c["stem"]: c for c in replay["clips"]}
    rows = []
    heard = timed = clocked = 0
    extra_heard = 0
    for clip, truth in truth_by_clip.items():
        rep = clips.get(clip)
        if rep is None:
            print(f"  {clip}: in truth but not extracted/replayed -- skipped", file=sys.stderr)
            continue
        audible = [t for t in truth if not t["miss"]]
        extra_heard += max(0, len(rep["shots"]) - len(audible))
        for t, s in pair(truth, rep["shots"]):
            if t["miss"]:
                continue
            clocked += t["radar_mph"] is not None
            if s is None:
                rows.append({**t, "clip": clip, "measured": None, "status": "not heard"})
                continue
            heard += 1
            if s["mph"] is None:
                rows.append({**t, "clip": clip, "measured": None, "status": "heard, no release"})
                continue
            timed += 1
            rows.append({**t, "clip": clip, "measured": s["mph"], "flight_ms": s["flight_ms"],
                         "status": "timed"})
    audible_total = sum(1 for tr in truth_by_clip.values() for t in tr if not t["miss"])
    errs = [(r["measured"] - r["radar_mph"]) for r in rows
            if r["status"] == "timed" and r["radar_mph"] is not None]
    ratios = [r["measured"] / r["radar_mph"] for r in rows
              if r["status"] == "timed" and r["radar_mph"]]
    summary = {
        "clips": len([c for c in truth_by_clip if c in clips]),
        "shots_by_eye": audible_total,
        "heard": heard,
        "extra_sounds_counted_as_shots": extra_heard,
        "timed": timed,
        "with_radar": len(errs),
        "bias_mph": round(statistics.mean(errs), 1) if errs else None,
        "median_error_mph": round(statistics.median(errs), 1) if errs else None,
        "mad_mph": round(statistics.median([abs(e - statistics.median(errs)) for e in errs]), 1)
        if errs else None,
        "mean_abs_error_mph": round(statistics.mean(abs(e) for e in errs), 1) if errs else None,
        "within_5mph": round(100 * sum(abs(e) <= 5 for e in errs) / len(errs)) if errs else None,
        "ratio_measured_over_radar": round(statistics.median(ratios), 3) if ratios else None,
    }
    return {"summary": summary, "rows": rows}


def enough(summary: dict) -> bool:
    return summary["clips"] >= MIN_CLIPS and summary["with_radar"] >= MIN_SHOTS


def print_report(ev: dict) -> None:
    s = ev["summary"]
    print("\n== shot speed vs radar ==")
    print(f"clips {s['clips']}  shots by eye {s['shots_by_eye']}  heard {s['heard']}  "
          f"timed {s['timed']}  with radar {s['with_radar']}  "
          f"extra sounds counted as shots {s['extra_sounds_counted_as_shots']}")
    if s["with_radar"]:
        print(f"bias {s['bias_mph']:+} mph (median {s['median_error_mph']:+}), "
              f"spread (MAD) {s['mad_mph']} mph, mean |err| {s['mean_abs_error_mph']} mph, "
              f"{s['within_5mph']}% within 5 mph")
        print(f"measured / radar median ratio {s['ratio_measured_over_radar']} "
              f"(flight average reads under a gun at the stick; <1 is expected)")
    print(f"{'clip':<24}{'#':>3}{'radar':>7}{'app':>7}{'err':>7}  status")
    for r in ev["rows"]:
        radar = "" if r["radar_mph"] is None else f"{r['radar_mph']:.0f}"
        app = "" if r["measured"] is None else f"{r['measured']:.1f}"
        err = ("" if r["measured"] is None or r["radar_mph"] is None
               else f"{r['measured'] - r['radar_mph']:+.1f}")
        print(f"{r['clip'][:24]:<24}{r['shot_no']:>3}{radar:>7}{app:>7}{err:>7}  {r['status']}")
    print()
    if enough(s):
        print(f"Enough to act on ({s['clips']} clips, {s['with_radar']} clocked shots).")
    else:
        print(f"NOT enough to settle anything: need {MIN_CLIPS} clips and {MIN_SHOTS} clocked "
              f"shots, have {s['clips']} and {s['with_radar']}. Report only; change nothing.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--truth", type=Path, default=Path("data/shotcal/truth.csv"))
    ap.add_argument("--specs", type=Path, default=Path(os.environ.get("LOCALAPPDATA", "/tmp")) / "Temp/specs.json")
    ap.add_argument("--in", dest="in_dir", type=Path, default=Path("data/shotcal/extracted"))
    ap.add_argument("--work", type=Path, default=Path("data/shotcal/work"))
    ap.add_argument("--sweep", action="store_true", help="also sweep the release thresholds")
    ap.add_argument("--json", type=Path, help="write the evaluation here too")
    args = ap.parse_args()

    if not args.specs.exists():
        raise SystemExit(f"{args.specs} missing: export drill specs first (see README / skill)")
    truth = read_truth(args.truth)
    args.work.mkdir(parents=True, exist_ok=True)

    # One replay per distance in the truth file; clips at another distance are
    # evaluated only in their own run.
    by_distance: dict[float, dict] = defaultdict(dict)
    for clip, rows in truth.items():
        d = rows[0]["distance_yd"]
        if d is None:
            raise SystemExit(f"{clip}: distance_yd is required")
        by_distance[d][clip] = rows

    def evaluate_params(params: dict) -> dict:
        merged = {"summary": None, "rows": []}
        totals = []
        for d, clips in sorted(by_distance.items()):
            rep = run_replay(args.specs, args.in_dir, d, params, args.work / f"replay_{d:g}yd.json")
            ev = evaluate(clips, rep)
            merged["rows"].extend(ev["rows"])
            totals.append(ev["summary"])
        # Pool the summaries.
        rows = merged["rows"]
        errs = [r["measured"] - r["radar_mph"] for r in rows
                if r["status"] == "timed" and r["radar_mph"] is not None]
        ratios = [r["measured"] / r["radar_mph"] for r in rows
                  if r["status"] == "timed" and r["radar_mph"]]
        merged["summary"] = {
            "clips": sum(t["clips"] for t in totals),
            "shots_by_eye": sum(t["shots_by_eye"] for t in totals),
            "heard": sum(t["heard"] for t in totals),
            "extra_sounds_counted_as_shots": sum(t["extra_sounds_counted_as_shots"] for t in totals),
            "timed": sum(t["timed"] for t in totals),
            "with_radar": len(errs),
            "bias_mph": round(statistics.mean(errs), 1) if errs else None,
            "median_error_mph": round(statistics.median(errs), 1) if errs else None,
            "mad_mph": round(statistics.median([abs(e - statistics.median(errs)) for e in errs]), 1)
            if errs else None,
            "mean_abs_error_mph": round(statistics.mean(abs(e) for e in errs), 1) if errs else None,
            "within_5mph": round(100 * sum(abs(e) <= 5 for e in errs) / len(errs)) if errs else None,
            "ratio_measured_over_radar": round(statistics.median(ratios), 3) if ratios else None,
        }
        return merged

    base = evaluate_params({})
    print_report(base)
    if args.json:
        args.json.write_text(json.dumps(base, indent=1), encoding="utf-8")

    if args.sweep:
        print("\n== release threshold sweep (shipped values in the first row) ==")
        print(f"{'params':<44}{'timed':>6}{'bias':>7}{'MAD':>6}{'|err|':>7}{'<=5':>5}")
        results = []
        for speed in SWEEP["minHandSpeed"]:
            for height in SWEEP["minHeight"]:
                params = {"minHandSpeed": speed, "minHeight": height}
                s = evaluate_params(params)["summary"]
                results.append((params, s))
        shipped = {"minHandSpeed": 2.5, "minHeight": -0.25}
        results.sort(key=lambda r: (r[0] != shipped, r[1]["mean_abs_error_mph"] or 999,
                                    -(r[1]["timed"] or 0)))
        for params, s in results:
            print(f"{json.dumps(params):<44}{s['timed']:>6}"
                  f"{'' if s['bias_mph'] is None else format(s['bias_mph'], '+'):>7}"
                  f"{'' if s['mad_mph'] is None else s['mad_mph']:>6}"
                  f"{'' if s['mean_abs_error_mph'] is None else s['mean_abs_error_mph']:>7}"
                  f"{'' if s['within_5mph'] is None else s['within_5mph']:>5}")
        print("\nA row beats the shipped one only if |err| falls AND timed does not. Apply as a "
              "single-number change to RELEASE_MIN_HAND_SPEED / RELEASE_MIN_HEIGHT in "
              "shotspeed.js, re-run this, and quote both tables in the PR.")


if __name__ == "__main__":
    main()
