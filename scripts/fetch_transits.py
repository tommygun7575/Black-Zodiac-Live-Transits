#!/usr/bin/env python3
"""
fetch_transits.py — fetch planetary transits from JPL Horizons, fallback to Swiss Ephemeris
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from astroquery.jplhorizons import Horizons
import swisseph as swe
import datetime

# Map IDs for Horizons + Swiss
OBJECTS = {
    "Sun": {"id": 10, "swe": swe.SUN},
    "Moon": {"id": 301, "swe": swe.MOON},
    "Mercury": {"id": 199, "swe": swe.MERCURY},
    "Venus": {"id": 299, "swe": swe.VENUS},
    "Mars": {"id": 499, "swe": swe.MARS},
    "Jupiter": {"id": 599, "swe": swe.JUPITER},
    "Saturn": {"id": 699, "swe": swe.SATURN},
    "Uranus": {"id": 799, "swe": swe.URANUS},
    "Neptune": {"id": 899, "swe": swe.NEPTUNE},
    "Pluto": {"id": 999, "swe": swe.PLUTO},
}

def fetch_from_horizons(obj_id, epoch):
    try:
        h = Horizons(id=obj_id, location='500@399', epochs=epoch, id_type=None)
        eph = h.elements()
        if "EclLon" in eph.colnames and "EclLat" in eph.colnames:
            lon = float(eph["EclLon"][0])
            lat = float(eph["EclLat"][0])
            return lon, lat
    except Exception as e:
        print(f"[WARN] Horizons failed for {obj_id}: {e}")
    return None, None

def fetch_from_swiss(obj_swe, jd):
    lon, lat, dist = swe.calc_ut(jd, obj_swe)[0:3]
    return lon, lat

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to live_config.json")
    parser.add_argument("--out", required=True, help="Output file path")
    args = parser.parse_args()

    # Load config
    with open(args.config, "r") as f:
        cfg = json.load(f)

    now = datetime.datetime.utcnow()
    jd = swe.julday(now.year, now.month, now.day, now.hour + now.minute/60.0)

    feed = {
        "generated_at_utc": now.isoformat(),
        "objects": []
    }

    for name, ids in OBJECTS.items():
        lon, lat = fetch_from_horizons(ids["id"], now)
        if lon is None or np.isnan(lon):
            lon, lat = fetch_from_swiss(ids["swe"], jd)
            source = "swiss"
        else:
            source = "horizons"

        feed["objects"].append({
            "name": name,
            "id": ids["id"],
            "lon": lon,
            "lat": lat,
            "source": source
        })

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(feed, f, indent=2)

    print(f"[OK] wrote {args.out}")

if __name__ == "__main__":
    main()
