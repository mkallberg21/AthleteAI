"""Per-sport facts for the program-director summaries.

Everything here is read out of the shipped catalog rather than typed, so a
number in a PDF cannot drift from the product. Anything the catalog does not
know, the document does not claim.
"""
import json, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from offdays.drills import ALL_DRILLS
from offdays.positions import BY_SPORT, BILATERAL_SPORTS
from offdays.curriculum import BY_SPORT as FILM_BY_SPORT
from offdays.load import THROW_CEILING_BY_AGE, CONFIG
import offdays.sports as SPORTS
import offdays.film as FILM

DRILL = {d.key: d for d in ALL_DRILLS}
SPORT_META = {s.key: s for s in SPORTS.CATALOG}


def drill_row(key, weight=None):
    d = DRILL[key]
    return {
        "key": key, "name": d.name, "sport": d.sport,
        "metric": d.metric, "description": d.description,
        "stimulus": d.stimulus.name.title(),
        # Whether the camera looks for a ball at all, which is not the same
        # as whether one is required: lacrosse counts off the stick and uses
        # the ball only to corroborate, so its ball is optional.
        "uses_ball": bool(d.ball and d.ball.detector == "vision"),
        "ball_required": bool(d.ball and d.ball.required),
        "ball_colours": list(d.ball.colours) if d.ball else [],
        "setup_hint": d.setup_hint,
        "xp_per_rep": d.scoring.xp_per_rep,
        "daily_cap": d.scoring.daily_rep_cap,
        "handedness": d.tracks_handedness,
        "weight": weight,
    }


def build():
    out = {}
    for sport, positions in sorted(BY_SPORT.items()):
        used, plans = {}, []
        for p in positions:
            top = sorted(p.emphasis.items(), key=lambda kv: -kv[1])
            plans.append({
                "key": p.key, "label": p.label, "focus": p.focus,
                "group": p.group, "offhand": p.offhand_matters,
                "n_drills": len(p.emphasis),
                "top": [{"name": DRILL[k].name, "share": round(w * 100)}
                        for k, w in top[:4]],
            })
            for k, w in p.emphasis.items():
                used[k] = max(used.get(k, 0), w)

        # Split by what the drill IS, not whose catalog it sits in. A softball
        # plan leans on the baseball fielding drills and a rugby plan on the
        # football passing ones -- calling those "shared athleticism" because
        # the key says baseball would be a lie about what the athlete does.
        own = [drill_row(k, used[k]) for k in used if DRILL[k].sport != "general"]
        gen = [drill_row(k, used[k]) for k in used if DRILL[k].sport == "general"]
        own.sort(key=lambda r: -r["weight"])
        gen.sort(key=lambda r: -r["weight"])
        borrowed = sorted({r["sport"] for r in own if r["sport"] != sport})

        mix = {}
        for k, w in used.items():
            mix[DRILL[k].stimulus.name.title()] = round(
                mix.get(DRILL[k].stimulus.name.title(), 0) + w, 3)

        # Share of every plan's weight that is explosive work, the floor the
        # test suite enforces across all 63 plans.
        expl = []
        for p in positions:
            s = sum(w for k, w in p.emphasis.items()
                    if DRILL[k].stimulus.name in ("POWER", "QUICKNESS"))
            expl.append(round(s * 100))

        topics = FILM_BY_SPORT.get(sport, ())
        meta = SPORT_META.get(sport)
        out[sport] = {
            "sport": sport,
            "label": meta.label if meta else sport.replace("_", " ").title(),
            "seasons": list(meta.typical_seasons) if meta else [],
            "positions": plans,
            "own_drills": own,
            "borrowed_from": borrowed,
            "skill_drills": len(own),
            "general_drills": gen,
            "n_drills": len(used),
            "stimulus_mix": mix,
            "explosive_min": min(expl) if expl else 0,
            "explosive_max": max(expl) if expl else 0,
            "film_topics": len(topics),
            "bilateral": sport in BILATERAL_SPORTS,
            "ball_sport": any(r["uses_ball"] for r in own),
            "ball_optional": any(r["uses_ball"] and not r["ball_required"]
                                 for r in own),
        }
    return out


if __name__ == "__main__":
    data = build()
    here = pathlib.Path(__file__).parent
    (here / "sports.json").write_text(json.dumps(data, indent=1))
    print(f"{len(data)} sports")
    for k, v in sorted(data.items()):
        print(f"  {v['label']:24} {len(v['positions'])}p  {v['n_drills']:2}d  "
              f"film {v['film_topics']:3}  explosive {v['explosive_min']}-{v['explosive_max']}%")
