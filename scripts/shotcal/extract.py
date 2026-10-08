"""Turn a shooting clip into what the phone would have seen and heard.

The capture screen never records anything, so a real session cannot be
replayed. The next best thing is to film the same shots with a phone propped
where the app's phone would be, then feed that file through the SAME code the
app runs: MediaPipe pose for the release, the audio track for the impact. This
script does the first half -- it decodes a clip into

    <out>/<clip>.landmarks.json   one entry per frame: t_ms + 33 landmarks
                                  (x, y, z, visibility), the shape
                                  `PoseLandmarker.detectForVideo` hands the
                                  browser, so `replay.mjs` can push them into
                                  the production counters unchanged
    <out>/<clip>.audio.f32        mono float32 PCM of the clip's audio track
    <out>/<clip>.meta.json        sample rate, fps, frame count, duration

-- and `replay.mjs` does the second half in Node against the real JS.

Frames are pulled at 30fps whatever the clip was shot at, because that is what
a phone browser delivers to the app and the release is read to the frame: a
60fps clip would make the bench look twice as precise as the product.

Runs in its own environment, not the repo venv: MediaPipe is a heavy dependency
the server never needs.

    uv venv --python 3.11 "$LOCALAPPDATA/Temp/calvenv"
    uv pip install --python "$LOCALAPPDATA/Temp/calvenv/Scripts/python.exe" mediapipe numpy
    "$LOCALAPPDATA/Temp/calvenv/Scripts/python.exe" scripts/shotcal/extract.py CLIP... --out data/shotcal/extracted

Needs ffmpeg/ffprobe on PATH. Nothing here uploads anything; the clip never
leaves the machine and only landmark numbers and the audio samples are written.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)
#: The same model, delegate aside, that `capture.html` and `calibrate.html` load.
MODEL_NAME = "pose_landmarker_lite.task"

#: What a phone browser films at; the app's release detector is tuned to it.
FPS = 30
#: `capture.html` asks the camera for 1280 wide. Pose quality tracks input size.
WIDTH = 1280
#: Audio is resampled to this. The ImpactDetector is rate-independent (it works
#: in 10ms hops) and 48k is what a phone's AudioContext usually runs at.
SAMPLE_RATE = 48000


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,width,height,r_frame_rate,duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    streams = json.loads(out)["streams"]
    video = next((s for s in streams if s["codec_type"] == "video"), None)
    audio = next((s for s in streams if s["codec_type"] == "audio"), None)
    if video is None:
        raise SystemExit(f"{path}: no video stream")
    num, den = video["r_frame_rate"].split("/")
    return {
        "width": int(video["width"]), "height": int(video["height"]),
        "source_fps": float(num) / float(den),
        "duration_s": float(video.get("duration") or 0),
        "has_audio": audio is not None,
    }


def ensure_model(cache: Path) -> Path:
    model = cache / MODEL_NAME
    if not model.exists():
        cache.mkdir(parents=True, exist_ok=True)
        print(f"downloading {MODEL_NAME} ...", file=sys.stderr)
        urllib.request.urlretrieve(MODEL_URL, model)
    return model


def extract_audio(path: Path, out: Path) -> int:
    """Mono float32 at SAMPLE_RATE. Returns the number of samples."""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "f32le", str(out)],
        check=True,
    )
    return out.stat().st_size // 4


def frames(path: Path, width: int, fps: int):
    """Yield (t_ms, HxWx3 uint8) at a fixed fps, scaled to `width`."""
    meta = probe(path)
    height = int(round(meta["height"] * width / meta["width"] / 2)) * 2
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-vf", f"fps={fps},scale={width}:{height}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE,
    )
    assert proc.stdout is not None
    frame_bytes = width * height * 3
    i = 0
    while True:
        buf = proc.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        yield round(i * 1000 / fps), np.frombuffer(buf, np.uint8).reshape(height, width, 3)
        i += 1
    proc.wait()


def run_pose(path: Path, model: Path, width: int, fps: int) -> list[dict]:
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    opts = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
    )
    out: list[dict] = []
    with vision.PoseLandmarker.create_from_options(opts) as lm:
        for t_ms, rgb in frames(path, width, fps):
            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
            res = lm.detect_for_video(img, t_ms)
            pts = res.pose_landmarks[0] if res.pose_landmarks else None
            out.append({
                "t_ms": t_ms,
                "landmarks": None if pts is None else [
                    {"x": p.x, "y": p.y, "z": p.z,
                     "visibility": p.visibility if p.visibility is not None else 1.0}
                    for p in pts
                ],
            })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("clips", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=Path("data/shotcal/extracted"))
    ap.add_argument("--fps", type=int, default=FPS, help="frame rate to sample at (phone = 30)")
    ap.add_argument("--width", type=int, default=WIDTH)
    ap.add_argument("--model-cache", type=Path, default=Path("data/shotcal/models"))
    ap.add_argument("--force", action="store_true", help="re-extract clips already done")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    model = ensure_model(args.model_cache)
    for clip in args.clips:
        stem = clip.stem
        meta_path = args.out / f"{stem}.meta.json"
        if meta_path.exists() and not args.force:
            print(f"{stem}: already extracted (--force to redo)")
            continue
        meta = probe(clip)
        if not meta["has_audio"]:
            print(f"{stem}: WARNING no audio track -- impacts cannot be heard, no speeds will "
                  "come out", file=sys.stderr)
        samples = extract_audio(clip, args.out / f"{stem}.audio.f32") if meta["has_audio"] else 0
        print(f"{stem}: {meta['width']}x{meta['height']} @ {meta['source_fps']:.2f}fps, "
              f"{meta['duration_s']:.1f}s, audio {samples} samples; pose at {args.fps}fps ...",
              file=sys.stderr)
        poses = run_pose(clip, model, args.width, args.fps)
        seen = sum(1 for p in poses if p["landmarks"])
        (args.out / f"{stem}.landmarks.json").write_text(json.dumps(poses))
        meta.update(clip=clip.name, fps=args.fps, frames=len(poses), frames_with_pose=seen,
                    sample_rate=SAMPLE_RATE, samples=samples, width=args.width)
        meta_path.write_text(json.dumps(meta, indent=1))
        print(f"{stem}: {len(poses)} frames, pose in {seen} "
              f"({100 * seen / max(len(poses), 1):.0f}%)")


if __name__ == "__main__":
    main()
