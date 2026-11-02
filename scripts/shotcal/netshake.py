"""Objective wall-ball truth from pixels: when does the net get hit?

Frame-differences inside the rebounder ROI; a ball hitting the net makes the
net shake for a few frames, a sharp peak well above the background sway.
Prints peak times so audio onsets can be checked against something the mic
did not produce. Bench-only; keeps no pixels.
"""
import sys, subprocess, json
import numpy as np, cv2

clip, x, y, w, h = sys.argv[1], *map(int, sys.argv[2:6])
proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", clip, "-vf", "fps=30,scale=540:960",
                         "-pix_fmt", "gray", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
W, H = 540, 960
prev = None
energy = []
while True:
    buf = proc.stdout.read(W * H)
    if len(buf) < W * H: break
    f = np.frombuffer(buf, np.uint8).reshape(H, W)[y:y+h, x:x+w].astype(np.float32)
    f = cv2.GaussianBlur(f, (5, 5), 0)
    if prev is not None:
        energy.append(float(np.mean(np.abs(f - prev))))
    prev = f
e = np.array(energy)
base = np.median(e)
mad = np.median(np.abs(e - base)) + 1e-6
z = (e - base) / mad
peaks = []
i = 0
while i < len(z):
    if z[i] > float(sys.argv[6]) if len(sys.argv) > 6 else z[i] > 6:
        j = i
        while j < len(z) and z[j] > 2: j += 1
        k = i + int(np.argmax(z[i:j]))
        peaks.append(((k + 1) / 30, float(z[k])))
        i = j + 6
    else:
        i += 1
print("net-shake peaks (s, z):", " ".join(f"{t:.2f}({zz:.0f})" for t, zz in peaks))
print("count:", len(peaks))
