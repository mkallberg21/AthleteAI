"""What a footwork drill says about how a session moved.

The everyday ground-ball routine is minutes of scooping, pushing and chasing
one ball in every direction. The touches themselves are wrist and stick work a
single camera cannot see on the body, so this product does not pretend to
count them. What it reports is the part the camera genuinely sees:

* **Moving time** -- the clock only ran while the athlete was moving.
* **Direction changes** -- each time travel across the frame reversed, after a
  real stretch of movement, not a sway.
* **Ground covered** -- in torso lengths, so it reads the same whatever the
  distance to the phone, and turned into rough yards for the athlete.

Counted, never scored: nothing here changes XP. The client's figures are taken
as reported but bounded, and a payload claiming more movement than its session
could hold is simply clipped.
"""

from __future__ import annotations

from typing import Any

#: A youth torso (shoulder to hip) is roughly 0.45m; this turns torso lengths
#: into the yards a kid understands. Approximate, and said so on screen.
TORSO_YARDS = 0.45 / 0.9144

#: The fastest a kid can honestly change direction, so no claim of more
#: changes than this per minute of moving time is believed.
MAX_CHANGES_PER_MINUTE = 90

#: Ground covered per minute of moving time beyond this is a camera being
#: carried around, not a kid shuffling. About 400 yards a minute.
MAX_TORSOS_PER_MINUTE = 800


def summarise(
    footwork: dict[str, Any] | None, *, hold_ms: int, duration_ms: int,
) -> dict[str, Any]:
    """The movement card for one footwork session."""
    moving_minutes = max(0.0, hold_ms) / 60_000
    changes = int((footwork or {}).get("direction_changes") or 0)
    ground = float((footwork or {}).get("ground_torsos") or 0.0)
    changes = min(changes, int(MAX_CHANGES_PER_MINUTE * moving_minutes) + 1)
    ground = min(ground, MAX_TORSOS_PER_MINUTE * moving_minutes)

    share = (hold_ms / duration_ms) if duration_ms > 0 else 0.0
    yards = round(ground * TORSO_YARDS)
    per_minute = round(changes / moving_minutes, 1) if moving_minutes >= 0.5 else None

    if moving_minutes < 0.5:
        note = ("Keep moving for longer next time. The clock only runs while "
                "your feet and stick are working.")
    elif share < 0.6:
        note = (f"You were moving for {share:.0%} of the session. Keep the ball "
                "going the whole time, with no standing over it.")
    elif changes < 4:
        note = ("Good, steady work. Next time change direction more: forward, "
                "back and side to side, the way a loose ball really moves.")
    else:
        note = (f"{changes} direction changes in {moving_minutes:.1f} minutes of "
                "moving. That's the footwork that wins ground balls.")

    return {
        "moving_seconds": round(hold_ms / 1000),
        "moving_share": round(share, 2),
        "direction_changes": changes,
        "changes_per_minute": per_minute,
        "ground_yards": yards,
        "note": note,
        "limits": [
            "It times your movement and counts direction changes. It cannot "
            "see the ball go into your stick, so it does not count pickups.",
            "Yards are a rough estimate from your body size on camera.",
        ],
    }
