#!/usr/bin/env python3
import json, os
from datetime import datetime, timezone
from typing import Any, Dict, List
from astroquery.jplhorizons import Horizons
from astropy import units as u  # kept for future extensions

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG = os.path.join(ROOT, "config", "targets.json")
OUTDIR = os.path.join(ROOT, "docs")
OUTFILE = os.path.join(OUTDIR, "feed_now.json")

def load_targets(p: str) -> List[Dict[str, Any]]:
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f).get("targets", [])
    return [{"id": "Sun", "label": "Sun"}, {"id": "Moon", "label": "Moon"}]

def _as_float(v):
    try: return float(v)
    except Exception:
        try: return float(v.value)
        except Exception: return None

def query_body(target_id: str) -> Dict[str, Any]:
    obj = Horizons(id=str(target_id), location=None, epochs=None)  # geocentric, now
    eph = obj.ephemerides(refplane="earth")
    row = eph[0]
    return {
        "id": str(target_id),
        "targetname": str(row["targetname"]),
        "datetime_utc": str(row["datetime_str"]),
        "jd": _as_float(row["datetime_jd"]),
        "ecl_lon_deg": _as_float(row["EclLon"]),
        "ecl_lat_deg": _as_float(row["EclLat"]),
        "ra_deg": _as_float(row["RA"]),
        "dec_deg": _as_float(row["DEC"]),
        "delta_au": _as_float(row["delta"]),
        "r_au": _as_float(row["r"]),
        "elong_deg": _as_float(row["elong"]),
        "phase_angle_deg": _as_float(row["alpha"]),
        "constellation": str(row["constellation"]),
    }

def main():
    targets = load_targets(CONFIG)
    results = []
    for t in targets:
        tid = str(t.get("id"))
        try:
            results.append(query_body(tid))
        except Exception as e:
            results.append({"id": tid, "error": f"{type(e).__name__}: {e}"})
    os.makedirs(OUTDIR, exist_ok=True)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "observer": "geocentric (Earth center)",
        "refplane": "earth",
        "source": "JPL Horizons via astroquery",
        "objects": results,
    }
    with open(OUTFILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Wrote {OUTFILE} with {len(results)} objects.")

if __name__ == "__main__":
    main()
