#!/usr/bin/env python3
"""Nashville Dogs Lacrosse Club - AthleteAI Dashboard Bundle (multi-page PDF)

Reads athlete.png / coach.png / director.png from a local `screenshots/`
directory (gitignored; capture them from a running demo server) and writes
nashville-dogs-dashboard-bundle.pdf, which is committed. Needs Pillow.
"""

import os
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont

SCREENSHOT_DIR = "screenshots"
OUTPUT = "nashville-dogs-dashboard-bundle.pdf"
PAGE_W = 1200  # width in px
PAGE_H = 1584  # 1200x1584 ~ 8.3" x 10.6" at 144dpi - fits well on screen and paper

PADDING = 60

def has_cmd(cmd):
    try:
        r = subprocess.run([cmd, "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except:
        return False

def load_font(size):
    for fp in ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/calibri.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()

def make_text_page(title_lines, body_lines):
    """Render text content to a full page image (white background, 1200x1584)."""
    canvas = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    d = ImageDraw.Draw(canvas)
    f_title = load_font(28)
    f_body = load_font(14)
    f_small = load_font(12)
    pad = 60
    y = pad + 10
    # Title
    for line in title_lines:
        d.text((pad, y), line, fill=(10, 40, 80), font=f_title)
        y += 40
    y += 10
    # Divider line
    d.line([pad, y, PAGE_W - pad, y], fill=(180, 190, 200), width=2)
    y += 20
    # Body
    for line in body_lines:
        d.text((pad, y), line, fill=(45, 45, 45), font=f_body)
        y += 22
        if y > PAGE_H - 80:
            break  # page overflow protection
    return canvas

def make_screenshot_page(fname, caption_lines, W=PAGE_W):
    """Screenshot image centered on a white page with caption below."""
    path = os.path.join(SCREENSHOT_DIR, fname)
    if not os.path.exists(path):
        return None
    src = Image.open(path)
    # Fit into page width minus padding
    max_img_w = W - 80
    ratio = max_img_w / src.width
    new_w = max_img_w
    new_h = int(src.height * ratio)
    if new_h > PAGE_H - 200:  # leave room for caption
        ratio = (PAGE_H - 200) / new_h
        new_w = int(new_w * ratio)
        new_h = PAGE_H - 200
    src = src.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGB", (W, PAGE_H), "white")
    ox = (W - new_w) // 2
    oy = 40
    canvas.paste(src, (ox, oy))
    d = ImageDraw.Draw(canvas)
    # Caption bar
    cap_top = oy + new_h + 15
    f_cap = load_font(13)
    line_h = 18
    for i, line in enumerate(caption_lines):
        d.text((PADDING, cap_top + i * line_h), line, fill=(80, 80, 80), font=f_cap)
    return canvas

PADDING = 60

# ── Build pages ────────────────────────────────────────────────────────────

pages = []  # list of PIL.Image

# 1. Cover
pages.append(make_text_page(
    ["Nashville Dogs", "Lacrosse Club"],
    ["AthleteAI (0FFDAYS) Dashboard Screenshots",
     "",
     "A stakeholder walkthrough of the three dashboards",
     "that Directors, Coaches, and Athletes see.",
     "",
     "Real captures from the running application,",
     "seeded with a sample Nashville Dogs roster:",
     "2031 Red team - 13 athletes, 3 coaches, 1 director.",
     "",
     "September 2026",
     "github.com/mkallberg21/AthleteAI"]
))

# 2. What is 0FFDAYS
pages.append(make_text_page(
    ["What is 0FFDAYS / AthleteAI?"],
    ["0FFDAYS (pronounced 'off-days') is an on-device training companion for youth athletes.",
     "",
     "The athlete records a workout on their phone - wall ball, push-ups, squats, high-knees,",
     "squat jumps - and the phone's camera analyzes each rep in real time using pose detection",
     "that runs entirely on the device. No video leaves the phone.",
     "",
     "Only derived counts are uploaded to the server:",
     "  - rep count  |  which hand  |  timing  |  confidence  |  range of motion",
     "",
     "Three dashboards, three roles:",
     "  - Director sees the whole program across all teams.",
     "  - Coach sees only their assigned team.",
     "  - Athlete sees their own home - current assignment, weekly plan, film clips."]
))

# 3. Director dashboard
pages.append(make_screenshot_page("director.png",
    ["Figure 1: Director Dashboard",
     "Joel White - whole-program overview for Nashville Dogs",
     "",
     "The director sees every athlete on every team. Key panels: total program XP,",
     "nudge list (athletes who haven't logged in recently), automatic recognition",
     "milestones, active assignments across all teams, and the film-shelf coverage",
     "showing which clips the whole club has watched."],
    W=PAGE_W))

# 4. Coach dashboard
pages.append(make_screenshot_page("coach.png",
    ["Figure 2: Coach Dashboard",
     "Coach Tommy - team view for 2031 Red",
     "",
     "A coach sees only their assigned team. The panel shows per-athlete form scores",
     "(consistency, depth, tempo, endurance), streak counts, weekly volume, weak-hand vs",
     "strong-hand balance, and athletes who need a nudge. The film shelf shows which",
     "Lacrosse IQ clips have been assigned and who has watched them."],
    W=PAGE_W))

# 5. Athlete dashboard
pages.append(make_screenshot_page("athlete.png",
    ["Figure 3: Athlete Dashboard",
     "Ryder Kallberg - 2031 Red, attack position",
     "",
     "The athlete sees their current assignment (wall ball with live rep progress and",
     "off-hand balance), their weekly plan for off-days broken down by day of the week,",
     "and the film clips with quiz questions. The plan's daily line reflects the",
     "athlete's age: this 13-year-old gets a concrete, achievable target without",
     "overload language."],
    W=PAGE_W))

# 6. Weekly plan detail
pages.append(make_text_page(
    ["Weekly Off-Day Plan - How It Works"],
    ["On days with no team obligation, the athlete gets a short, concrete plan:",
     "which drill to do, how many reps, and a suggested time box.",
     "",
     "The plan respects age so it never burns out a young player and never",
     "under-loads an older one.",
     "",
     "UNDER 11 (U8-U10):",
     "  Short, encouraging lines. 'Today's plan: wall ball, keep your stick busy.'",
     "  No target demand. Soft nudge: 'If you have 10 minutes, wall ball is a great way",
     "  to spend them.' Never tells a young player they're behind.",
     "",
     "AGES 12-15 (U11-U15):",
     "  Concrete 'enough' framing. 'Three sessions this week is right where you want",
     "  to be.' Soft cap on volume - the plan says when enough has been done, not to",
     "  push past it. Recognizes the athlete's existing practice load.",
     "",
     "AGES 16+ / ADULT:",
     "  Honest volume framing - names how many sessions and roughly how many minutes",
     "  the plan expects, with the weekly cap visible so the athlete can see when",
     "  they've hit it. Treats the athlete as a serious trainee.",
     "",
     "The seed data in this bundle uses a 2031 birth-year squad (mostly 13-year-olds).",
     "The plan lines in the athlete screenshot reflect that age band: specific enough",
     "to be motivating, light enough to fit around school and team practice."]
))

# 7. Film study / Lacrosse IQ
pages.append(make_text_page(
    ["Film Study - Lacrosse IQ"],
    ["Short video clips (typically 60-110 seconds) teach sport-specific IQ:",
     "  - Sliding from the crease",
     "  - Man-down rotations",
     "  - Clearing under pressure",
     "  - Riding as a unit",
     "  - Off-ball cutting",
     "",
     "Each clip has a focus line a coach would recognize, and most have a one-question",
     "quiz where a wrong answer comes with a short explanation of why the right answer",
     "matters.",
     "",
     "The coach sees coverage - who has watched what - so film study becomes visible",
     "in the same way off-day training is. This turns 'watch film' from a vague",
     "instruction into something trackable on the dashboard."]
))

# 8. How coaches use this / closing
pages.append(make_text_page(
    ["How Coaches Use This During Practice"],
    ["The dashboard exists so that during practice, coaches are not spending a whole",
     "bunch of time on fundamentals.",
     "",
     "If the dashboard shows that a player has been reliably hitting their off-day",
     "wall-ball target, the coach knows the player's repetition base is there and can",
     "spend practice time on team concepts and game situations.",
     "",
     "If a player's form score is slipping or their weak-hand balance is lopsided, the",
     "coach sees that before practice starts and can address it in the warm-up rather",
     "than discovering it mid-drill.",
     "",
     "ABOUT THIS BUNDLE:",
     "These screenshots were generated from the live 0FFDAYS application",
     "(github.com/mkallberg21/AthleteAI) seeded with a sample Nashville Dogs roster:",
     "the 2031 Red team, 13 athletes, three coaches, one director, six weeks of",
     "training history, one active wall-ball assignment, and five Lacrosse IQ film clips.",
     "",
     "The application runs on the athlete's phone (on-device pose analysis, no video",
     "upload) and on a lightweight server that stores derived training counts, form",
     "scores, streaks, leaderboards, assignments, and film-study progress.",
     "",
     "For questions, feature requests, or to set up a program:",
     "github.com/mkallberg21/AthleteAI"]
))

# ── Save individual PNGs and combine to PDF ────────────────────────────────

os.makedirs("/tmp/nashville-pages", exist_ok=True)
pdf_inputs = []
for i, im in enumerate(pages):
    path = f"/tmp/nashville-pages/page_{i+1:02d}.png"
    im.save(path, "PNG")
    pdf_inputs.append(path)
    print(f"Page {i+1}: {im.size} -> {path}")

# Convert all pages to a single PDF using img2pdf
if has_cmd("img2pdf"):
    cmd = ["img2pdf"] + pdf_inputs + ["-o", OUTPUT]
    subprocess.run(cmd, check=True)
    backend = "img2pdf"
else:
    # Fallback: first page as PDF base, others appended
    pages[0].save(OUTPUT, "PDF", resolution=150.0, save_all=True,
                   append_images=pages[1:])
    backend = "PIL"

size_kb = os.path.getsize(OUTPUT) // 1024
print(f"\nPDF saved: {os.path.abspath(OUTPUT)} ({size_kb} KB, {backend})")
print(f"Pages: {len(pages)}")
print("\nPage breakdown:")
for i, (name, im) in enumerate(zip(
    ["Cover", "What is 0FFDAYS", "Director dashboard", "Coach dashboard",
     "Athlete dashboard", "Weekly plan detail", "Film study - Lacrosse IQ",
     "How coaches use this / closing"][:len(pages)], pages)):
    print(f"  {i+1}. {name} ({im.size[0]}x{im.size[1]}px)")
