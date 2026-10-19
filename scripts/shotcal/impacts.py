"""What does each impact sound like? Net, pipe, wall, rebounder, or a step.

Shot speed times the ball from the swing to the IMPACT, and the impact
detector (`ShotListener` in shotspeed.js) is one compromise across every
surface: a slack net rings for 80 ms and arrives in one hop; a pipe is a
single sharp edge; a wall is a crack with a long bright tail; a step on the
follow-through is dull and low. The detector's three tests (ratio, sharpness,
jump) were tuned on net clips from 10 yd and nothing else.

Before building a per-surface detector, or a goal-vs-pipe-vs-wide call, the
question is whether the surfaces are separable in the audio the phone hears.
This script takes every impact the bench replay found and prints, per impact,
a few features a per-surface rule could be written on:

    rise_ms      hops from the floor to the peak -- a pipe and a wall arrive in
                 one, a slack net in one or two, a step in three or more
    ring_ms      how long the sound stays within 10 dB of its peak -- a pipe
                 rings, a net thuds, a step is over at once
    centroid_hz  spectral centroid of the 50 ms after the onset -- a pipe is
                 bright (2-5 kHz), a net is mid, a step is low
    peak_db      peak energy over the clip's own floor

plus the same for every OTHER onset the sound layer heard in the clip, so the
things that get mistaken for shots are in the same table.

Labels come from `truth.csv`'s `note` column where the user wrote one (net,
pipe, wall, rebounder); unlabelled impacts are printed with a `?`. With the
seven radar clips (all net) this cannot separate anything -- it lays the table
out so the next filming session (net AND rebounder AND wall, as the brief
asks) can fill it in. Nothing in the product reads it.

    "$LOCALAPPDATA/offdays-calvenv/Scripts/python.exe" scripts/shotcal/impacts.py \
        [--replayed data/shotcal/work/replay_10yd.json] [--extracted data/shotcal/extracted]
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

#: Analysis hop and window, matching the phone's ImpactDetector (10 ms hops).
HOP_MS = 10
#: Spectral window after the onset. 50 ms is the first ring of a pipe and the
#: whole of a net thud.
SPEC_MS = 50
#: Rings while within this of the peak.
RING_DB = 10
#: Energy floor: the clip's 20th percentile hop energy, as a stand-in for the
#: detector's running floor.
FLOOR_PCT = 20


def hop_energy(audio: np.ndarray, sr: int) -> np.ndarray:
    n = int(sr * HOP_MS / 1000)
    m = len(audio) // n
    return (audio[: m * n].reshape(m, n) ** 2).mean(axis=1) + 1e-12


def features(audio: np.ndarray, sr: int, energy: np.ndarray, floor: float, t_ms: int) -> dict:
    h = int(t_ms / HOP_MS)
    lo, hi = max(h - 10, 0), min(h + 30, len(energy))
    seg = energy[lo:hi]
    if not len(seg):
        return {}
    pk = lo + int(np.argmax(seg))
    peak_db = 10 * np.log10(energy[pk] / floor)
    # Rise: hops back from the peak until under floor * 2 (3 dB over the floor).
    rise = 0
    k = pk
    while k > 0 and energy[k - 1] > floor * 2 and rise < 30:
        k -= 1
        rise += 1
    # Ring: hops forward from the peak while within RING_DB of it.
    ring = 0
    k = pk
    while k + 1 < len(energy) and 10 * np.log10(energy[pk] / energy[k + 1]) < RING_DB and ring < 100:
        k += 1
        ring += 1
    s0 = pk * int(sr * HOP_MS / 1000)
    s1 = s0 + int(sr * SPEC_MS / 1000)
    win = audio[s0:s1]
    centroid = None
    if len(win) > 16:
        spec = np.abs(np.fft.rfft(win * np.hanning(len(win)))) ** 2
        freqs = np.fft.rfftfreq(len(win), 1 / sr)
        centroid = float((spec * freqs).sum() / (spec.sum() + 1e-12))
    return {"peak_ms": pk * HOP_MS, "peak_db": round(float(peak_db), 1),
            "rise_ms": rise * HOP_MS, "ring_ms": ring * HOP_MS,
            "centroid_hz": None if centroid is None else int(centroid)}


def read_labels(path: Path) -> dict[tuple[str, int], str]:
    out = {}
    if not path.exists():
        return out
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            note = (row.get("note") or "").strip().lower()
            if note:
                out[(Path(row["clip"]).stem, int(row["shot_no"]))] = note
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--replayed", type=Path, default=Path("data/shotcal/work/replay_10yd.json"))
    ap.add_argument("--extracted", type=Path, default=Path("data/shotcal/extracted"))
    ap.add_argument("--truth", type=Path, default=Path("data/shotcal/truth.csv"))
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    replay = json.loads(args.replayed.read_text(encoding="utf-8"))
    labels = read_labels(args.truth)
    rows = []
    for clip in replay["clips"]:
        stem = clip["stem"]
        meta = json.loads((args.extracted / f"{stem}.meta.json").read_text())
        sr = meta["sample_rate"]
        audio = np.fromfile(args.extracted / f"{stem}.audio.f32", dtype=np.float32)
        energy = hop_energy(audio, sr)
        floor = float(np.percentile(energy, FLOOR_PCT))
        shot_impacts = {s["impact_ms"]: i + 1 for i, s in enumerate(clip["shots"])}
        for t in clip["impacts_ms"]:
            f = features(audio, sr, energy, floor, t)
            no = shot_impacts.get(t)
            rows.append({"clip": stem, "t_ms": t, "kind": "shot" if no else "impact",
                         "label": labels.get((stem, no), "?") if no else "-", **f})
        heard = set(clip["impacts_ms"])
        for t in clip["onsets_ms"]:
            if any(abs(t - i) < 150 for i in heard):
                continue
            f = features(audio, sr, energy, floor, t)
            rows.append({"clip": stem, "t_ms": t, "kind": "other", "label": "-", **f})

    print(f"{'clip':<10}{'t_ms':>6}  {'kind':<7}{'label':<10}{'peak_dB':>8}{'rise':>6}{'ring':>6}{'centroid':>9}")
    for r in sorted(rows, key=lambda r: (r["kind"] != "shot", r["clip"], r["t_ms"])):
        g = lambda k, w: (str(r[k]) if r.get(k) is not None else "-").rjust(w)
        print(f"{r['clip']:<10}{g('t_ms', 6)}  {r['kind']:<7}{r['label']:<10}{g('peak_db', 8)}"
              f"{g('rise_ms', 6)}{g('ring_ms', 6)}{g('centroid_hz', 9)}")

    shots = [r for r in rows if r["kind"] == "shot" and r.get("centroid_hz")]
    others = [r for r in rows if r["kind"] == "other" and r.get("centroid_hz")]
    if shots:
        med = lambda rs, k: float(np.median([r[k] for r in rs]))
        print(f"\nshots ({len(shots)}): median peak {med(shots, 'peak_db'):.0f} dB, rise "
              f"{med(shots, 'rise_ms'):.0f} ms, ring {med(shots, 'ring_ms'):.0f} ms, centroid "
              f"{med(shots, 'centroid_hz'):.0f} Hz")
        if others:
            print(f"other sounds ({len(others)}): median peak {med(others, 'peak_db'):.0f} dB, "
                  f"rise {med(others, 'rise_ms'):.0f} ms, ring {med(others, 'ring_ms'):.0f} ms, "
                  f"centroid {med(others, 'centroid_hz'):.0f} Hz")
    surfaces = {r["label"] for r in shots if r["label"] not in ("?", "-")}
    if len(surfaces) < 2:
        print("\nOne surface (or none labelled): nothing to separate yet. Film net AND rebounder "
              "AND wall, and write the surface in truth.csv's note column per shot.")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
