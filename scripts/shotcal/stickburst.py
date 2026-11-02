"""Stick-head motion in the sky above the player: frame-difference energy in a
box that holds only sky + the raised stick. Each throw = the head cocks up
into the box then swings out of it -> one burst. Bench truth when the net
is occluded. Args: clip x y w h [z] on a 540x960 frame."""
import sys, subprocess
import numpy as np, cv2
clip, x, y, w, h = sys.argv[1], *map(int, sys.argv[2:6])
zmin = float(sys.argv[6]) if len(sys.argv) > 6 else 6
proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", clip, "-vf", "fps=30,scale=540:960",
                         "-pix_fmt", "gray", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
W, H = 540, 960
prev, energy = None, []
while True:
    buf = proc.stdout.read(W * H)
    if len(buf) < W * H: break
    f = np.frombuffer(buf, np.uint8).reshape(H, W)[y:y+h, x:x+w].astype(np.float32)
    f = cv2.GaussianBlur(f, (5, 5), 0)
    if prev is not None: energy.append(float(np.mean(np.abs(f - prev))))
    prev = f
e = np.array(energy); base = np.median(e); mad = np.median(np.abs(e - base)) + 1e-6
z = (e - base) / mad
bursts, i = [], 0
while i < len(z):
    if z[i] > zmin:
        j = i
        while j < len(z) and (z[j] > 2 or (j + 1 < len(z) and z[j + 1] > 2)): j += 1
        k = i + int(np.argmax(z[i:j]))
        bursts.append(((i + 1) / 30, (j + 1) / 30, float(z[k])))
        i = j + 9
    else: i += 1
print("stick bursts (start-end s, z):", " ".join(f"{a:.2f}-{b:.2f}({c:.0f})" for a, b, c in bursts))
print("count:", len(bursts))
