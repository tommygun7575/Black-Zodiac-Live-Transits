#!/usr/bin/env python3
import json, os, sys
from datetime import datetime, timezone
from typing import Dict, Any, List

# Explicit imports with scripts.* prefix
from scripts.sources import horizons_client, miriade_client, mpc_client, swiss_client
from scripts.utils.coords import ra_dec_to_ecl

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA = os.path.join(ROOT, "data")

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

def merge_into(existing: Dict[str, Any],
               positions: Dict[str, Dict[str, Any]],
               when_iso: str) -> Dict[str, Any]:
    meta = existing.get("meta", {})
    meta.update({
        "generated_at_utc": when_iso,
        "source_order": [s for s, _ in SOURCE_ORDER]
    })

    charts = existing.get("charts")
    if charts and isinstance(charts, dict):
        for who, chart in charts.items():
            # ensure objects is always a dict
            if not isinstance(chart.get("objects"), dict):
                chart["objects"] = {}
            chart["objects"].update(positions)
        out = {"meta": meta, "charts": charts}
    else:
        out = {"meta": meta, "objects": positions}

    return out


def main(argv: List[str]):
    out_path = os.environ.get("OVERLAY_OUT",
                              os.path.join("docs", "feed_overlay.json"))
    when_iso = os.environ.get("OVERLAY_TIME_UTC", iso_now())
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    existing = load_existing(out_path)
    positions = compute_positions(when_iso)
    merged = merge_into(existing, positions, when_iso)
    json.dump(merged, open(out_path, "w"), indent=2, ensure_ascii=False)
    print(f"wrote {out_path}")

if __name__ == "__main__":
    main(sys.argv[1:])
