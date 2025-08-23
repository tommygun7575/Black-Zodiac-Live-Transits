#!/usr/bin/env python3
import json, os, sys
from datetime import datetime, timezone
from typing import Dict, Any, List

# Explicit imports with scripts.* prefix
from scripts.sources import horizons_client, miriade_client, mpc_client, swiss_client
from scripts.utils.coords import ra_dec_to_ecl

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA = os.path.join(ROOT, "data")
NATAL = os.path.join("config", "natal", "3_combined_kitchen_sink.json")

def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

SOURCE_ORDER = (
    ("jpl", horizons_client.get_ecliptic_lonlat),
    ("miriade", miriade_client.get_ecliptic_lonlat),
    ("mpc", mpc_client.get_ecliptic_lonlat),
    ("swiss", swiss_client.get_ecliptic_lonlat),
)

def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def load_existing(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception:
            return {}
    return {}

def compute_positions(when_iso: str) -> Dict[str, Dict[str, Any]]:
    out = {}

    # majors
    majors = ["Sun", "Moon", "Mercury", "Venus", "Mars",
              "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto", "Chiron"]
    for name in majors:
        got, used = None, None
        for label, func in SOURCE_ORDER:
            pos = func(name, when_iso)
            if pos:
                got, used = pos, label
                break
        out[name] = {
            "ecl_lon_deg": None if not got else float(got[0]),
            "ecl_lat_deg": 0.0 if not got else float(got[1]),
            "source": "missing" if not used else used,
        }

    # small bodies
    sb_cfg = load_json(os.path.join(DATA, "small_bodies_master.json"))
    for bucket in ("asteroids", "centaurs", "tnos"):
        for rec in sb_cfg.get(bucket, []):
            name, sid = rec["name"], rec["id"]
            got, used = None, None
            for label, func in SOURCE_ORDER:
                pos = func(sid, when_iso)
                if pos:
                    got, used = pos, label
                    break
            out[name] = {
                "ecl_lon_deg": None if not got else float(got[0]),
                "ecl_lat_deg": 0.0 if not got else float(got[1]),
                "source": "missing" if not used else used,
            }

    # fixed stars
    stars = load_json(os.path.join(DATA, "fixed_stars.json"))["stars"]
    for s in stars:
        lam, bet = ra_dec_to_ecl(s["ra_deg"], s["dec_deg"], when_iso)
        out[s["id"]] = {"ecl_lon_deg": lam, "ecl_lat_deg": bet, "source": "fixed"}

    return out

def merge_into(natal_bundle: Dict[str, Any],
               positions: Dict[str, Dict[str, Any]],
               when_iso: str) -> Dict[str, Any]:
    meta = {
        "generated_at_utc": when_iso,
        "source_order": [s for s, _ in SOURCE_ORDER]
    }

    charts = {}
    for who, natal in natal_bundle.items():
        if who.startswith("_meta"):
            continue
        charts[who] = {
            "birth": natal.get("birth", {}),
            "natal": natal.get("planets", {}),
            "objects": positions
        }

    return {"meta": meta, "charts": charts}

def main(argv: List[str]):
    out_path = os.environ.get("OVERLAY_OUT",
                              os.path.join("docs", "feed_overlay.json"))
    when_iso = os.environ.get("OVERLAY_TIME_UTC", iso_now())
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    natal_bundle = load_json(NATAL)
    positions = compute_positions(when_iso)
    merged = merge_into(natal_bundle, positions, when_iso)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"wrote {out_path}")

if __name__ == "__main__":
    main(sys.argv[1:])
