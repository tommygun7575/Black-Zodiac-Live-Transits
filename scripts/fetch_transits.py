#!/usr/bin/env python3
"""
Fetch geocentric ecliptic positions (EclLon/EclLat) for a set of Solar System bodies
from JPL Horizons (via astroquery), and write docs/feed_now.json.

- Defaults to observer at Earth's center (geocentric).
- Epoch = 'now' (UTC).
- Output is a compact JSON payload suitable for downstream use.
"""
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from astroquery.jplhorizons import Horizons  # type: ignore
from astropy import units as u  # type: ignore

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG = os.path.join(ROOT, "config", "targets.json")
OUTDIR = os.path.join(ROOT, "docs")
OUTFILE = os.path.join(OUTDIR, "feed_now.json")

def load_targets(config_path: str) -> List[Dict[str, Any]]:
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("targets", [])
    # Fallback minimal list
    return [{"id": "Sun", "label": "Sun"}, {"id": "Moon", "label": "Moon"}]

def query_body(target_id: str) -> Dict[str, Any]:
    # Geocentric by default: location=None => Earth center for ephemerides
    obj = Horizons(id=target_id, location=None, epochs=None)
    eph = obj.ephemerides(refplane="earth")
    row = eph[0]  # 'now' returns a single row

    def as_float(val):
        try:
            return float(val)
        except Exception:
            # astropy Quantities / masked values
            try:
                return float(val.value)
            except Exception:
                return None

    return {
        "id": target_id,
        "targetname": str(row["targetname"]),
        "datetime_utc": str(row["datetime_str"]),
        "jd": as_float(row["datetime_jd"]),
        "ecl_lon_deg": as_float(row["EclLon"]),
        "ecl_lat_deg": as_float(row["EclLat"]),
        "ra_deg": as_float(row["RA"]),
        "dec_deg": as_float(row["DEC"]),
        "delta_au": as_float(row["delta"]),  # distance from Earth
        "r_au": as_float(row["r"]),          # heliocentric
        "elong_deg": as_float(row["elong"]),
        "phase_angle_deg": as_float(row["alpha"]),
        "constellation": str(row["constellation"]),
    }

def main() -> None:
    targets = load_targets(CONFIG)
    results = []
    for t in targets:
        tid = str(t.get("id"))
        try:
            results.append(query_body(tid))
        except Exception as e:
            results.append({
                "id": tid,
                "error": f"{type(e).__name__}: {e}"
            })

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
