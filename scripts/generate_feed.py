#!/usr/bin/env python3
"""
generate_feed.py — Fetch planetary positions from JPL Horizons
and save them into docs/feed_now.json
"""

import json
from datetime import datetime, timezone
from astroquery.jplhorizons import Horizons

# Targets: Sun, Moon, planets, Chiron, etc.
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

def fetch_body(eph_id):
    try:
        obj = Horizons(
            id=eph_id,
            id_type=None,  # <-- critical fix (works across astropy>=5.3)
            location="500@399",  # geocentric Earth center
            epochs=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        )
        vec = obj.ephemerides()[0]
        return {
            "targetname": TARGETS.get(str(eph_id), eph_id),
            "id": eph_id,
            "datetime": vec["datetime_str"],
            "RA": float(vec["RA"]),
            "DEC": float(vec["DEC"]),
            "ELONG": float(vec["elong"]),
            "LAT": float(vec["dec"]),
            "ecl_lon": float(vec["ECL_LON"]),
            "ecl_lat": float(vec["ECL_LAT"])
        }
    except Exception as e:
        raise RuntimeError(f"Failed for {eph_id}: {e}")

def main():
    data = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "observer": "geocentric (Earth center)",
        "refplane": "earth",
        "source": "JPL Horizons via astroquery",
        "objects": []
    }

    for eph_id in TARGETS.keys():
        body = fetch_body(eph_id)
        data["objects"].append(body)

    with open("docs/feed_now.json", "w") as f:
        json.dump(data, f, indent=2)

    print("Wrote docs/feed_now.json with", len(data["objects"]), "objects.")

if __name__ == "__main__":
    main()
