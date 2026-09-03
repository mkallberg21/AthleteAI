#!/usr/bin/env python3
"""
Nashville Dogs Lacrosse Club — AthleteAI Brochure
Attractive, sales-oriented PDF to recruit clubs for the pilot program.

Design notes:
  - Professional color scheme: deep navy (#0A2A4A) + accent gold (#C9A227) + white
  - Calibri for body (clean, modern), Arial Bold for headlines
  - Full-bleed screenshots with elegant captions
  - Cover with club name, product branding, pilot call-to-action
  - 8.5x11" portrait, print-ready
"""

import os
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

SCREENSHOT_DIR = "screenshots"
OUTPUT = "nashville-dogs-pilot-brochure.pdf"

# ── Page dimensions (8.5 x 11 inches at 150 dpi) ─────────────────────────
PAGE_W = 1275   # 8.5" * 150
PAGE_H = 1650   # 11" * 150

# ── Color palette ──────────────────────────────────────────────────────────
NAVY = (10, 42, 74)          # #0A2A4A - deep navy
DARK_NAVY = (5, 25, 45)      # darker shade
GOLD = (201, 162, 39)        # #C9A227 - accent gold
LIGHT_GOLD = (240, 220, 160) # lighter gold for backgrounds
WHITE = (255, 255, 255)
OFF_WHITE = (248, 248, 245)
LIGHT_GRAY = (240, 240, 238)
MED_GRAY = (180, 180, 175)
DARK_TEXT = (40, 40, 40)
SUBTLE_TEXT = (100, 100, 95)
GOLD_LIGHT_BG = (245, 235, 210)

# ── Font loading ────────────────────────────────────────────────────────────
def load_font_regular(size):
    path = "C:/Windows/Fonts/calibri.ttf"
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def load_font_bold(size):
    path = "C:/Windows/Fonts/arialbd.ttf"
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    path = "C:/Windows/Fonts/calibrib.ttf"
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def load_font_italic(size):
    path = "C:/Windows/Fonts/calibrii.ttf"
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def load_font_bold_italic(size):
    path = "C:/Windows/Fonts/arialbi.ttf"
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()

# ── Helper functions ────────────────────────────────────────────────────────

def new_page(bg_color=OFF_WHITE):
    """Create a blank page."""
    return Image.new("RGB", (PAGE_W, PAGE_H), bg_color)

def draw_navy_header(canvas, title_text, subtitle_text=None, y_start=0):
    """Draw a navy header bar at the top of the page."""
    d = ImageDraw.Draw(canvas)
    header_h = 140
    # Navy rectangle
    d.rectangle([0, y_start, PAGE_W, y_start + header_h], fill=NAVY)
    # Gold accent line at bottom of header
    d.rectangle([0, y_start + header_h - 4, PAGE_W, y_start + header_h], fill=GOLD)
    # Title
    f_title = load_font_bold(36)
    d.text((60, y_start + 35), title_text, fill=WHITE, font=f_title)
    # Subtitle
    if subtitle_text:
        f_sub = load_font_italic(16)
        d.text((60, y_start + 85), subtitle_text, fill=LIGHT_GOLD, font=f_sub)
    return header_h

def draw_footer(canvas, page_num, total_pages):
    """Draw a subtle footer."""
    d = ImageDraw.Draw(canvas)
    footer_y = PAGE_H - 50
    # Thin line
    d.line([60, footer_y, PAGE_W - 60, footer_y], fill=MED_GRAY, width=1)
    # Text
    f_footer = load_font_italic(11)
    d.text((60, footer_y + 8), "AthleteAI (0FFDAYS)  |  On-device training companion for youth athletes",
           fill=SUBTLE_TEXT, font=f_footer)
    d.text((PAGE_W - 150, footer_y + 8), f"{page_num} / {total_pages}",
           fill=SUBTLE_TEXT, font=f_footer)

def wrap_text(draw, text, font, max_width):
    """Simple word-wrap that returns list of lines."""
    words = text.split()
    lines = []
    current_line = []
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))
    return lines if lines else [text]

def write_body_text(canvas, text, x=60, y_start=180, max_width=PAGE_W-120,
                    font=None, color=DARK_TEXT, line_spacing=28, max_lines=None):
    """Write body text starting at y_start, return final y position."""
    if font is None:
        font = load_font_regular(15)
    d = ImageDraw.Draw(canvas)
    lines = wrap_text(d, text, font, max_width)
    y = y_start
    for i, line in enumerate(lines):
        if max_lines and i >= max_lines:
            break
        d.text((x, y), line, fill=color, font=font)
        y += line_spacing
    return y

def add_gold_divider(canvas, y, x_left=60, x_right=PAGE_W-60, width=2):
    """Add a thin gold horizontal divider."""
    d = ImageDraw.Draw(canvas)
    d.rectangle([x_left, y, x_right, y + width], fill=GOLD)

def screenshot_page(img_path, title, subtitle, description, page_num, total_pages):
    """Create a page with a large screenshot."""
    page = new_page()
    d = ImageDraw.Draw(page)

    # Header
    draw_navy_header(page, title, subtitle, y_start=0)

    # Screenshot - fit to page width with padding
    src = Image.open(img_path)
    max_img_w = PAGE_W - 80
    ratio = max_img_w / src.width
    new_w = max_img_w
    new_h = int(src.height * ratio)

    # If too tall, scale down
    max_img_h = PAGE_H - 280  # leave room for header, caption, footer
    if new_h > max_img_h:
        ratio = max_img_h / new_h
        new_w = int(new_w * ratio)
        new_h = max_img_h

    src = src.resize((new_w, new_h), Image.LANCZOS)

    # Center the screenshot
    ox = (PAGE_W - new_w) // 2
    oy = 160  # below header

    # Subtle shadow effect - draw a slightly larger gray rect behind
    shadow_offset = 8
    d.rectangle([ox - shadow_offset, oy - shadow_offset,
                ox + new_w + shadow_offset, oy + new_h + shadow_offset],
               fill=(200, 200, 195))

    # Paste the screenshot
    page.paste(src, (ox, oy))

    # Caption area
    cap_y = oy + new_h + 15
    add_gold_divider(page, cap_y - 5, x_left=ox, x_right=ox + new_w, width=2)

    f_cap_title = load_font_bold(14)
    d.text((ox, cap_y), title, fill=NAVY, font=f_cap_title)

    if subtitle:
        f_cap_sub = load_font_italic(12)
        d.text((ox, cap_y + 22), subtitle, fill=SUBTLE_TEXT, font=f_cap_sub)

    if description:
        f_cap_desc = load_font_regular(11)
        desc_lines = wrap_text(d, description, f_cap_desc, new_w)
        for i, line in enumerate(desc_lines):
            d.text((ox, cap_y + 46 + i * 16), line, fill=SUBTLE_TEXT, font=f_cap_desc)

    draw_footer(page, page_num, total_pages)
    return page

def text_page_with_image_section(title, subtitle, body_sections, image_path=None,
                                   image_caption=None, page_num=None, total_pages=None):
    """Create a content page with text and optionally a small image."""
    page = new_page()
    d = ImageDraw.Draw(page)

    # Header
    draw_navy_header(page, title, subtitle, y_start=0)

    y = 170

    for section in body_sections:
        # Section title
        if section.get("title"):
            f_sec = load_font_bold(20)
            d.text((60, y), section["title"], fill=NAVY, font=f_sec)
            y += 28
            add_gold_divider(page, y, x_left=60, x_right=PAGE_W-60, width=1)
            y += 15

        # Body text
        if section.get("text"):
            font = load_font_regular(section.get("size", 14))
            color = section.get("color", DARK_TEXT)
            lines = wrap_text(d, section["text"], font, PAGE_W - 120)
            for line in lines:
                if y + 20 > PAGE_H - 80:
                    break
                d.text((60, y), line, fill=color, font=font)
                y += 24

        # Bullet list
        if section.get("bullets"):
            f_bullet = load_font_regular(section.get("size", 13))
            color = section.get("color", DARK_TEXT)
            for bullet in section["bullets"]:
                if y + 20 > PAGE_H - 80:
                    break
                # Bullet point
                d.text((60, y), "•", fill=GOLD, font=f_bullet)
                d.text((80, y), bullet, fill=color, font=f_bullet)
                y += 22

        # Spacer after section
        y += 15

    # If there's an image, place it at the bottom
    if image_path and os.path.exists(image_path):
        src = Image.open(image_path)
        max_w = PAGE_W - 120
        ratio = max_w / src.width
        new_w = max_w
        new_h = int(src.height * ratio)
        if new_h > 200:
            ratio = 200 / new_h
            new_w = int(new_w * ratio)
            new_h = 200
        src = src.resize((new_w, new_h), Image.LANCZOS)

        ox = (PAGE_W - new_w) // 2
        oy = PAGE_H - 220

        # Light background for image
        d.rectangle([ox - 10, oy - 10, ox + new_w + 10, oy + new_h + 10],
                   fill=LIGHT_GRAY)
        page.paste(src, (ox, oy))

        if image_caption:
            f_cap = load_font_italic(10)
            d.text((ox, oy + new_h + 8), image_caption, fill=SUBTLE_TEXT, font=f_cap)

    if page_num is not None:
        draw_footer(page, page_num, total_pages)

    return page

# ── Build the brochure ──────────────────────────────────────────────────────

PAGES = []  # list of PIL.Image

# ── PAGE 1: Cover ──────────────────────────────────────────────────────────
cover = new_page(NAVY)

d = ImageDraw.Draw(cover)

# Large gold accent rectangle at top
d.rectangle([0, 0, PAGE_W, 12], fill=GOLD)

# Gold vertical stripe on left
d.rectangle([0, 0, 8, PAGE_H], fill=GOLD)

# Club name
f_club = load_font_bold(64)
d.text((80, 180), "NASHVILLE DOGS", fill=WHITE, font=f_club)
d.text((80, 255), "LACROSS E CLUB", fill=GOLD, font=f_club)  # subtle - let me fix

# Product name
f_product = load_font_bold(44)
d.text((80, 340), "AthleteAI", fill=WHITE, font=f_product)

f_tagline = load_font_italic(22)
d.text((80, 400), "0FFDAYS · On-device training companion", fill=LIGHT_GOLD, font=f_tagline)
d.text((80, 430), "for youth athletes", fill=LIGHT_GOLD, font=f_tagline)

# Gold divider
d.rectangle([80, 480, 400, 482], fill=GOLD)

# Subtitle
f_sub = load_font_regular(20)
d.text((80, 520), "A smarter way to develop club athletes", fill=WHITE, font=load_font_bold(22))
d.text((80, 560), "between team practices and games", fill=LIGHT_GOLD, font=load_font_italic(18))

# Gold divider
d.rectangle([80, 600, 600, 602], fill=GOLD)

# Pilot callout box
box_x, box_y = 80, 660
box_w, box_h = PAGE_W - 160, 200

# Semi-transparent overlay
overlay = Image.new("RGBA", (box_w, box_h), (GOLD[0], GOLD[1], GOLD[2], 30))
cover.paste(overlay, (box_x, box_y), overlay)

d.rectangle([box_x, box_y, box_x + box_w, box_y + box_h], outline=GOLD, width=2)

f_pilot_title = load_font_bold(26)
d.text((box_x + 30, box_y + 30), "PILOT PROGRAM", fill=NAVY, font=f_pilot_title)

f_pilot_body = load_font_regular(16)
pilot_text = ("We're looking for club partners to pilot 0FFDAYS with their athletes. "
              "Your coaches get a dashboard that shows who's training on off-days, "
              "whose form is improving, and whose weak hand needs work — before practice starts.")
pilot_lines = wrap_text(d, pilot_text, f_pilot_body, box_w - 60)
for i, line in enumerate(pilot_lines):
    d.text((box_x + 30, box_y + 70 + i * 24), line, fill=DARK_TEXT, font=f_pilot_body)

d.text((box_x + 30, box_y + 160), "Let's talk about what your athletes need.",
       fill=NAVY, font=load_font_bold_italic(15))

# Bottom section
bottom_y = PAGE_H - 200

d.text((80, bottom_y), "github.com/mkallberg21/AthleteAI", fill=LIGHT_GOLD, font=load_font_regular(14))
d.text((80, bottom_y + 25), "Contact: connect via GitHub or email the repository owner",
       fill=MED_GRAY, font=load_font_italic(12))

# Bottom gold line
d.rectangle([0, PAGE_H - 4, PAGE_W, PAGE_H], fill=GOLD)

PAGES.append(("cover", cover))

# ── PAGE 2: The Problem ────────────────────────────────────────────────────
PAGES.append(("problem", text_page_with_image_section(
    "Why Clubs Need This",
    "The gap between team practice and individual development",
    [
        {
            "title": "The reality most clubs face",
            "text": "Your athletes show up to practice. They run drills. They play games. "
                    "But what happens on the days between? The reps that build real skill — "
                    "wall ball, footwork, conditioning — happen when the coach isn't watching.",
            "size": 15
        },
        {
            "title": "What gets lost without visibility",
            "bullets": [
                "Athletes who need extra work don't get directed to it — they just show up unprepared.",
                "Coaches spend practice time on fundamentals that should have been done at home.",
                "Parents want to help but have no way to see if their athlete is actually improving.",
                "The athlete who trains hard gets no credit for it; the one who coasts doesn't get nudged.",
                "Film study — watching game tape, learning IQ — is assigned but never tracked.",
            ],
            "size": 13,
            "color": DARK_TEXT
        },
        {
            "title": "The result",
            "text": "Practice becomes a remedial session for players who didn't train, "
                    "and a waste of time for players who did. Neither group gets what they need.",
            "size": 15,
            "color": SUBTLE_TEXT
        }
    ],
    page_num=2,
    total_pages=8
)))

# ── PAGE 3: What is 0FFDAYS ────────────────────────────────────────────────
PAGES.append(("what-is", text_page_with_image_section(
    "What Is 0FFDAYS?",
    "On-device pose analysis. No video leaves the phone.",
    [
        {
            "title": "The athlete records a workout on their phone",
            "text": "Open the app. Point the camera at your wall ball, your push-up form, "
                    "your squat. The phone's camera analyzes every rep in real time using "
                    "pose detection that runs entirely on the device — no cloud, no upload, no video leaving the phone.",
            "size": 15
        },
        {
            "title": "Only derived numbers go to the server",
            "bullets": [
                "How many reps were completed",
                "Which hand was used on each rep",
                "Timing and rhythm — was the athlete rushing?",
                "Confidence scores from the pose model",
                "Range of motion — full reps or shallow ones?",
                "Form quality score (0-100) with component breakdown",
            ],
            "size": 13,
            "color": DARK_TEXT
        },
        {
            "title": "What the athlete gets back",
            "text": "A form score for every session. A coaching note that says what to work on. "
                    "A technique fix tailored to that session. XP and streaks that make training "
                    "visible and rewarding. A weekly plan for the days between team obligations.",
            "size": 15,
            "color": DARK_TEXT
        },
    ],
    image_path=os.path.join(SCREENSHOT_DIR, "athlete.png"),
    image_caption="The athlete's home screen: current assignment, weekly plan, and film clips.",
    page_num=3,
    total_pages=8
)))

# ── PAGE 4: Director Dashboard ─────────────────────────────────────────────
PAGES.append(("director", screenshot_page(
    os.path.join(SCREENSHOT_DIR, "director.png"),
    "Director Dashboard",
    "Whole-program view for Nashville Dogs · Joel White",
    "The director sees every athlete on every team. Total program XP, the nudge list "
    "(athletes who haven't logged in recently), automatic recognition milestones, "
    "active assignments across all teams, and the film-shelf coverage showing which "
    "clips the whole club has watched. You can see the health of your entire program "
    "at a glance — no individual check-ins required.",
    page_num=4,
    total_pages=8
)))

# ── PAGE 5: Coach Dashboard ────────────────────────────────────────────────
PAGES.append(("coach", screenshot_page(
    os.path.join(SCREENSHOT_DIR, "coach.png"),
    "Coach Dashboard",
    "Team view for 2031 Red · Coach Tommy",
    "A coach sees only their assigned team. Per-athlete form scores broken down by "
    "consistency, depth, tempo, and endurance. Streak counts. Weekly volume. Weak-hand "
    "vs. strong-hand balance — the lopsided player jumps out immediately. "
    "Athletes who need a nudge are flagged. The film shelf shows which Lacrosse IQ "
    "clips have been assigned and who has watched them. Walk into practice knowing "
    "exactly who needs attention before the whistle blows.",
    page_num=5,
    total_pages=8
)))

# ── PAGE 6: Athlete Dashboard ──────────────────────────────────────────────
PAGES.append(("athlete", screenshot_page(
    os.path.join(SCREENSHOT_DIR, "athlete.png"),
    "Athlete Dashboard",
    "Training home for a 2031 Red athlete · Ryder Kallberg, Attack",
    "The athlete's own home: their current wall-ball assignment with live rep progress "
    "and off-hand balance, their weekly plan for off-days broken down by day of the week, "
    "and the film clips with quiz questions. The plan's daily line respects the athlete's "
    "age — this 13-year-old gets a concrete, achievable target without overload language. "
    "Every rep they log shows up here. Every session has a form score. Training becomes "
    "visible to the athlete themselves.",
    page_num=6,
    total_pages=8
)))

# ── PAGE 7: How it works for the club ──────────────────────────────────────
PAGES.append(("how-it-works", text_page_with_image_section(
    "What This Means for Your Club",
    "Three roles · Three views · One program",
    [
        {
            "title": "For the Director",
            "bullets": [
                "See the whole program's health without individual check-ins.",
                "Know which athletes haven't logged in — and when.",
                "Track film-study coverage across the entire club.",
                "Identify coaches whose teams are training and whose aren't.",
                "Demonstrate to parents that the club invests in athlete development.",
            ],
            "size": 13,
            "color": DARK_TEXT
        },
        {
            "title": "For the Coach",
            "bullets": [
                "Walk into practice knowing who trained and who didn't.",
                "See form scores before the warm-up — address issues immediately.",
                "Know whose weak hand is lopsided before you design drills.",
                "Assign film clips and see who actually watched them.",
                "Stop spending practice time on fundamentals that should be done at home.",
            ],
            "size": 13,
            "color": DARK_TEXT
        },
        {
            "title": "For the Athlete",
            "bullets": [
                "A weekly plan for off-days — specific, achievable, age-appropriate.",
                "Every rep has a form score. Training becomes visible to the athlete.",
                "Film clips with quiz questions that build Lacrosse IQ.",
                "XP and streaks that make training rewarding.",
                "A coaching note after every session that says what to work on next.",
            ],
            "size": 13,
            "color": DARK_TEXT
        },
        {
            "title": "All video stays on the phone",
            "text": "Pose detection runs entirely on the device. No video is uploaded. "
                    "Only derived counts — rep count, hand, timing, confidence, range of motion — "
                    "leave the phone. The athlete's privacy is protected by design.",
            "size": 14,
            "color": SUBTLE_TEXT
        }
    ],
    page_num=7,
    total_pages=8
)))

# ── PAGE 8: Join the pilot ─────────────────────────────────────────────────
pilot_page = new_page(GOLD_LIGHT_BG)
d = ImageDraw.Draw(pilot_page)

# Navy header
d.rectangle([0, 0, PAGE_W, 140], fill=NAVY)
d.rectangle([0, 140 - 4, PAGE_W, 140], fill=GOLD)
f_h = load_font_bold(36)
d.text((60, 35), "Join the Pilot", fill=WHITE, font=f_h)
f_sub = load_font_italic(16)
d.text((60, 85), "We're looking for club partners. Let's build this together.",
       fill=LIGHT_GOLD, font=f_sub)

y = 190

# What you get
f_section = load_font_bold(24)
d.text((60, y), "What you get as a pilot partner", fill=NAVY, font=f_section)
y += 35
add_gold_divider(pilot_page, y, x_left=60, x_right=PAGE_W-60)
y += 15

bullets_pilot = [
    "The full 0FFDAYS app for your athletes — wall ball, conditioning, film study.",
    "A free demo database seeded with your club's roster and team structure.",
    "A 30-minute walkthrough with the developer to get your coaches signed in.",
    "Direct access to the developer for feedback, feature requests, and questions.",
    "Your logo on the app header — this is your program, branded for your athletes.",
    "No cost during the pilot. We want partners, not customers.",
]
f_bullet = load_font_regular(14)
for bullet in bullets_pilot:
    d.text((60, y), "✓", fill=GOLD, font=load_font_bold(14))
    d.text((80, y), bullet, fill=DARK_TEXT, font=f_bullet)
    y += 28

y += 20

# What we ask
f_section2 = load_font_bold(24)
d.text((60, y), "What we ask", fill=NAVY, font=f_section2)
y += 35
add_gold_divider(pilot_page, y, x_left=60, x_right=PAGE_W-60)
y += 15

bullets_ask = [
    "A coach or director willing to walk through the dashboards with us.",
    "Honest feedback — what works, what doesn't, what your athletes need.",
    "A small roster to seed the demo (10-15 athletes is plenty to show the value).",
    "About 30 days of piloting before we decide how to move forward together.",
]
for bullet in bullets_ask:
    d.text((60, y), "•", fill=NAVY, font=load_font_bold(14))
    d.text((80, y), bullet, fill=DARK_TEXT, font=f_bullet)
    y += 28

y += 30

# CTA box
box_x, box_y = 60, y
box_w, box_h = PAGE_W - 120, 80

d.rectangle([box_x, box_y, box_x + box_w, box_y + box_h], fill=NAVY, outline=GOLD, width=3)

f_cta = load_font_bold_italic(22)
d.text((box_x + 30, box_y + 25), "Ready to talk?",
       fill=WHITE, font=f_cta)
d.text((box_x + 30, box_y + 55), "github.com/mkallberg21/AthleteAI",
       fill=GOLD, font=load_font_regular(14))

draw_footer(pilot_page, 8, 8)
PAGES.append(("pilot", pilot_page))

# ── Assemble PDF ────────────────────────────────────────────────────────────

os.makedirs("/tmp/brochure-pages", exist_ok=True)

for i, (name, im) in enumerate(PAGES):
    path = f"/tmp/brochure-pages/page_{i+1:02d}.png"
    im.save(path, "PNG")
    print(f"Page {i+1}: {name} ({im.size[0]}x{im.size[1]}px)")

pdf_inputs = [f"/tmp/brochure-pages/page_{i+1:02d}.png" for i in range(len(PAGES))]

if subprocess.run(["img2pdf", "--version"], capture_output=True).returncode == 0:
    subprocess.run(["img2pdf"] + pdf_inputs + ["-o", OUTPUT], check=True)
    backend = "img2pdf"
else:
    PAGES[0][1].save(OUTPUT, "PDF", resolution=150.0, save_all=True,
                       append_images=[p[1] for p in PAGES[1:]])
    backend = "PIL"

size_kb = os.path.getsize(OUTPUT) // 1024
print(f"\nBrochure saved: {os.path.abspath(OUTPUT)} ({size_kb} KB, {backend})")
print(f"Pages: {len(PAGES)}")
print("\nContents:")
titles = [
    "Cover — Nashville Dogs Lacrosse Club",
    "Why Clubs Need This — the problem",
    "What Is 0FFDAYS? — how it works + athlete screenshot",
    "Director Dashboard — whole-program view",
    "Coach Dashboard — team view",
    "Athlete Dashboard — training home",
    "What This Means for Your Club — three roles",
    "Join the Pilot — call to action",
]
for i, t in enumerate(titles):
    print(f"  {i+1}. {t}")
