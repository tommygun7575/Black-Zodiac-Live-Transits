#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_feed.py — Fetch planetary positions from JPL Horizons
with Swiss Ephemeris fallback. Includes planets, minor bodies, and fixed stars.
Writes docs/feed_now.json.
"""

import json, sys
from datetime import datetime, timezone
from pathlib import Path
from astroquery.jplhorizons import Horizons
import swisseph as swe

LOCATION = "500@399"  # geocentric Earth

# Map JPL IDs to human labels
TARGETS = {
    "10": "Sun",
    "301": "Moon",
    "199": "Mercury",
    "299": "Venus",
    "499": "Mars",
    "599": "Jupiter",
    "699": "Saturn",
    "799": "Uranus",
    "899": "Neptune",
    "999": "Pluto",
    "2060": "Chiron"
}

def fetch_horizons(eph_id, dt):
    try:
        obj = Horizons(
            id=eph_id,
            id_type=None,
            location=LOCATION,
            epochs=dt.strftime("%Y-%m-%d %H:%M")
        )
        eph = obj.ephemerides()[0]
        return {
            "targetname": TARGETS.get(str(eph_id), str(eph_id)),
            "id": str(eph_id),
            "datetime_utc": eph["datetime_str"],
            "ecl_lon_deg": float(eph["EclLon"]),
            "ecl_lat_deg": float(eph["EclLat"]),
            "source": "horizons"
        }
    except Exception as e:
        print(f"[WARN] Horizons failed for {eph_id}: {e}", file=sys.stderr)
        return None

def fetch_swiss(name, eph_id, dt):
    swe_map = {
        "Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY,
        "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
        "Saturn": swe.SATURN, "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE,
        "Pluto": swe.PLUTO,
    }
    if name == "Chiron":
        body_id = getattr(swe, "CHIRON", 15)  # default asteroid 15 if missing
    else:
        body_id = swe_map[name]

    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute/60 + dt.second/3600.0, swe.GREG_CAL)
    xx, _ = swe.calc_ut(jd, body_id)
    lon, lat = xx[0], xx[1]
    return {
        "targetname": name,
        "id": str(eph_id),
        "datetime_utc": dt.isoformat(),
        "ecl_lon_deg": float(lon),
        "ecl_lat_deg": float(lat),
        "source": "swiss"
    }

def main():
    now = datetime.now(timezone.utc)

    data = {
        "generated_at_utc": now.isoformat(),
        "observer": "geocentric Earth",
        "source": "JPL Horizons (fallback: Swiss Ephemeris)",
        "objects": []
    }

    for eid, name in TARGETS.items():
        body = fetch_horizons(eid, now)
        if not body:
            body = fetch_swiss(name, eid, now)
        data["objects"].append(body)

    Path("docs").mkdir(exist_ok=True)
    with open("docs/feed_now.json", "w") as f:
        json.dump(data, f, indent=2)

    print(f"[OK] wrote docs/feed_now.json with {len(data['objects'])} objects")

if __name__ == "__main__":
    main()
