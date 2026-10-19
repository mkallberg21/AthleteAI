"""Shooting distance from everything the phone has: the server's own copy.

Mirrors `web/static/distance.js` line for line. The phone sends the raw
observations (goal size and position in the frame, the shooter's torso and
feet, the tilt, the typed distance, the lens it thinks it has); this works
the distance out again and `shotspeed.analyze` uses THIS answer, never the
phone's. tests/test_distance.py pins the two implementations on one case.

Each factor is its own estimate with its own error bar, combined by inverse
variance. A factor that cannot be read is listed as unused with the reason;
a camera that disagrees with the pace beyond reason loses to the pace and
says so. Nothing here is a guess dressed as a measurement: the error bar is
part of the answer and the report carries it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

#: Regulation goal mouth, posts outside-to-outside: 6 ft plus a 2 in pipe.
GOAL_WIDTH_M = (6 * 12 + 2) * 0.0254
GOAL_HEIGHT_M = GOAL_WIDTH_M

DEFAULT_FOCAL = 1.15
DEFAULT_FOCAL_REL_SIGMA = 0.15
LEARNED_FOCAL_REL_SIGMA = 0.05
FOCAL_RANGE = (0.5, 2.5)

TYPED_SIGMA_M = 0.9

TORSO_M_BY_AGE = ((9, 0.39), (10, 0.41), (11, 0.43), (12, 0.45), (13, 0.47), (14, 0.49),
                  (15, 0.51), (16, 0.52), (17, 0.53), (200, 0.53))
TORSO_REL_SIGMA = 0.20
TORSO_POSE_REL_SIGMA = 0.55
PLACEMENT_M = 0.9
PLACEMENT_SIGMA_M = 2.0
DEFAULT_AGE = 12

EDGE_PX_720 = 2
HEIGHT_EXTRA_REL_SIGMA = 0.30
GROUND_REL_SIGMA = 0.5
MIN_GROUND_ANGLE_RAD = 2 * math.pi / 180

MIN_GOAL_WIDTH = 0.06
MIN_GOAL_SEEN = 0.3
DISAGREE_SIGMAS = 3

YD_PER_M = 1 / 0.9144


#: How much one session moves the remembered lens. Slow on purpose: a lens
#: is a constant, and one odd session (a goal half-seen, a kid who paced
#: short) must not swing it. Twelve agreeing sessions settle it.
FOCAL_LEARN_RATE = 0.25


def learn_focal(current: float | None, hint: float) -> float | None:
    """The lens to remember after a session where the camera and the pace agreed."""
    if not (FOCAL_RANGE[0] <= hint <= FOCAL_RANGE[1]):
        return current
    if current is None or not (FOCAL_RANGE[0] <= current <= FOCAL_RANGE[1]):
        return round(hint, 3)
    return round(current + FOCAL_LEARN_RATE * (hint - current), 3)


def torso_for_age(age: int | None) -> float:
    a = age if isinstance(age, (int, float)) and math.isfinite(age) else DEFAULT_AGE
    for max_age, m in TORSO_M_BY_AGE:
        if a <= max_age:
            return m
    return TORSO_M_BY_AGE[-1][1]


def fuse(estimates: list[tuple[float, float] | None]) -> tuple[float, float] | None:
    usable = [e for e in estimates if e and math.isfinite(e[0]) and e[1] > 0]
    if not usable:
        return None
    w = sum(1 / (s * s) for _, s in usable)
    v = sum(x / (s * s) for x, s in usable)
    return v / w, math.sqrt(1 / w)


def _r2(x: float) -> float:
    return round(x * 100) / 100


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and math.isfinite(v) else None


def _factor(name: str, m: float, sigma: float, used: bool, why: str = "") -> dict[str, Any]:
    return {"name": name, "yd": _r2(m * YD_PER_M), "plus_minus_yd": _r2(sigma * YD_PER_M),
            "used": used, "why": why}


def _unused(name: str, why: str) -> dict[str, Any]:
    return {"name": name, "yd": None, "plus_minus_yd": None, "used": False, "why": why}


@dataclass
class DistanceReport:
    distance_m: float | None = None
    plus_minus_m: float | None = None
    source: str = "none"
    factors: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""
    focal_hint: float | None = None
    focal_learned: bool = False

    @property
    def distance_yd(self) -> float | None:
        return None if self.distance_m is None else _r2(self.distance_m * YD_PER_M)

    @property
    def plus_minus_yd(self) -> float | None:
        return None if self.plus_minus_m is None else _r2(self.plus_minus_m * YD_PER_M)

    def to_dict(self) -> dict[str, Any]:
        return {
            "distance_yd": self.distance_yd,
            "plus_minus_yd": self.plus_minus_yd,
            "source": self.source,
            "factors": self.factors,
            "note": self.note,
            "focal_hint": self.focal_hint,
            "focal_learned": self.focal_learned,
        }


def estimate(scene: dict[str, Any] | None, age: int | None = None) -> DistanceReport:
    """See distance.js `estimateDistance`; same inputs, same outputs."""
    s = scene or {}
    rep = DistanceReport()
    factors = rep.factors
    fw, fh = _num(s.get("view_w")) or 0, _num(s.get("view_h")) or 0
    short = min(fw, fh)
    edge = EDGE_PX_720 * (720 / short) / 720 if short > 0 else 0.0

    f, f_rel, learned = DEFAULT_FOCAL, DEFAULT_FOCAL_REL_SIGMA, False
    focal = _num(s.get("focal"))
    if focal is not None and FOCAL_RANGE[0] <= focal <= FOCAL_RANGE[1]:
        f, f_rel, learned = focal, LEARNED_FOCAL_REL_SIGMA, True

    typed_yd = _num(s.get("typed_yd"))
    typed = (typed_yd / YD_PER_M, TYPED_SIGMA_M) if typed_yd and typed_yd > 0 else None
    if typed:
        factors.append(_factor("set", typed[0], typed[1], True, "paced out, about a yard"))

    g = s.get("goal") if isinstance(s.get("goal"), dict) else None
    gw = _num(g.get("w")) if g else None
    g_of = _num(g.get("of")) if g else None
    g_seen = _num(g.get("seen")) if g else None
    goal_ok = bool(g and short > 0 and gw is not None and gw >= MIN_GOAL_WIDTH
                   and (not g_of or (g_seen or 0) / g_of >= MIN_GOAL_SEEN))
    zg = None
    if goal_ok:
        by_w = (f * GOAL_WIDTH_M / gw, 0.0)
        by_w = (by_w[0], by_w[0] * (edge / gw))
        factors.append(_factor("goal width", by_w[0], by_w[0] * math.hypot(edge / gw, f_rel), True,
                               "posts are 6 ft apart"))
        ests = [by_w]
        gh = _num(g.get("h"))
        if gh is not None and gh >= MIN_GOAL_WIDTH:
            v = f * GOAL_HEIGHT_M / gh
            by_h = (v, v * math.hypot(edge / gh, HEIGHT_EXTRA_REL_SIGMA))
            factors.append(_factor("goal height", v, v * math.hypot(edge / gh, HEIGHT_EXTRA_REL_SIGMA, f_rel),
                                   True, "crossbar is 6 ft up"))
            ests.append(by_h)
        zg = fuse(ests)
    elif g and g_of:
        factors.append(_unused("goal width", "goal too small in frame"
                               if gw is not None and gw < MIN_GOAL_WIDTH else "goal not seen enough"))

    a = s.get("athlete") if isinstance(s.get("athlete"), dict) else None
    torso = _num(a.get("torso")) if a else None
    za = None
    if zg and torso and torso > 0:
        torso_m = torso_for_age(age)
        v = f * torso_m / torso
        by_t = (v, v * math.hypot(TORSO_REL_SIGMA, TORSO_POSE_REL_SIGMA))
        factors.append(_factor("shooter size", v, v * math.hypot(TORSO_REL_SIGMA, TORSO_POSE_REL_SIGMA, f_rel),
                               True, f"torso about {round(torso_m * 100)} cm at this age"))
        placed = (PLACEMENT_M, PLACEMENT_SIGMA_M)
        factors.append(_factor("placement", placed[0], placed[1], True, "phone beside the shooter, as asked"))
        ests = [by_t, placed]
        pitch = _num(s.get("pitch_deg"))
        base_y, feet_y = _num(g.get("base_y")), _num(a.get("feet_y"))
        if pitch is not None and base_y is not None and feet_y is not None:
            p = pitch * math.pi / 180
            ang_goal = p + math.atan2(base_y, f)
            ang_feet = p + math.atan2(feet_y, f)
            if ang_goal > MIN_GROUND_ANGLE_RAD and ang_feet > MIN_GROUND_ANGLE_RAD:
                cam_h = zg[0] * math.tan(ang_goal)
                v = cam_h / math.tan(ang_feet)
                by_g = (v, v * math.hypot(GROUND_REL_SIGMA, zg[1] / zg[0]))
                factors.append(_factor("ground plane", v, v * math.hypot(GROUND_REL_SIGMA, f_rel), True,
                                       f"phone tilted {round(pitch)} deg, camera about {_r2(cam_h)} m up"))
                ests.append(by_g)
            else:
                factors.append(_unused("ground plane", "too close to the horizon to read"))
        za = fuse(ests)

    camera = None
    if zg:
        d, sigma = zg
        if za:
            bg = math.atan2(_num(g.get("cx")) or 0.0, f)
            ba = math.atan2(_num(a.get("cx")) or 0.0, f)
            cos_d = math.cos(ba - bg)
            d = math.sqrt(max(0.0, zg[0] ** 2 + za[0] ** 2 - 2 * zg[0] * za[0] * cos_d))
            d_zg = (zg[0] - za[0] * cos_d) / d if d > 0 else 1.0
            d_za = (za[0] - zg[0] * cos_d) / d if d > 0 else 1.0
            sigma = math.hypot(d_zg * zg[1], d_za * za[1])
        sigma = math.hypot(sigma, d * f_rel)
        camera = (d, sigma)
        factors.append(_factor("camera", d, sigma, True,
                               "goal and shooter, by triangle" if za else "goal only; shooter not sized"))

    if camera and typed:
        gap = abs(camera[0] - typed[0])
        together = math.hypot(camera[1], typed[1])
        if gap > DISAGREE_SIGMAS * together:
            out, rep.source = typed, "set"
            for x in factors:
                if x["name"] == "camera":
                    x["used"] = False
            rep.note = (f"The camera makes it {_r2(camera[0] * YD_PER_M):.1f} yards, not "
                        f"{_r2(typed[0] * YD_PER_M):.1f}. Check the spot, or that the whole goal is in view.")
        else:
            out, rep.source = fuse([camera, typed]), "camera+set"
            rep.focal_hint = round(f * typed[0] / camera[0] * 1000) / 1000
            rep.note = (f"Distance measured from the goal in view: about {_r2(out[0] * YD_PER_M):.1f} yards"
                        f" (you set {_r2(typed[0] * YD_PER_M):.1f}).")
    elif camera:
        out, rep.source = camera, "camera"
        rep.note = f"Distance measured from the goal in view: about {_r2(camera[0] * YD_PER_M):.1f} yards."
    elif typed:
        out, rep.source = typed, "set"
        rep.note = "The goal was not in view, so the distance is the one you set." if g and g_of else ""
    else:
        return rep
    rep.distance_m, rep.plus_minus_m = out[0], out[1]
    rep.focal_learned = learned
    return rep
