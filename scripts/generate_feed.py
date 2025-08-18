#!/usr/bin/env python3
"""
generate_feed.py — Fetch planetary positions from JPL Horizons
and fall back to Swiss Ephemeris if Horizons data is missing.
Writes docs/feed_now.json (core major bodies).
"""

import json
from datetime import datetime, timezone
from astroquery.jplhorizons import Horizons
import swisseph as swe

LOCATION = "500@399"  # geocentric Earth

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
            "targetname": TARGETS.get(str(eph_id), eph_id),
            "id": eph_id,
            "datetime": eph["datetime_str"],
            "ecl_lon": float(eph["ECL_LON"]),
            "ecl_lat": float(eph["ECL_LAT"]),
        }
    except Exception as e:
        print(f"[WARN] Horizons failed for {eph_id}: {e}")
        return None

def fetch_swiss(name, dt):
    swe_map = {
        "Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY,
        "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
        "Saturn": swe.SATURN, "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE,
        "Pluto": swe.PLUTO, "Chiron": swe.CHIRON,
    }
    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute/60 + dt.second/3600.0, swe.GREG_CAL)
    lon, lat, dist = swe.calc_ut(jd, swe_map[name])[0:3]
    return {
        "targetname": name,
        "id": name,
        "datetime": dt.isoformat(),
        "ecl_lon": float(lon),
        "ecl_lat": float(lat),
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
            body = fetch_swiss(name, now)
        data["objects"].append(body)

    with open("docs/feed_now.json", "w") as f:
        json.dump(data, f, indent=2)

if __name__ == "__main__":
    main()
