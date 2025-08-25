#!/usr/bin/env python3
import json
import datetime
import pytz
import numpy as np
import pandas as pd

from astroquery.jplhorizons import Horizons
import swisseph as swe
import os

# Paths
SE_EPHE_PATH = os.environ.get("SE_EPHE_PATH", "ephe")

# Objects to calculate
HORIZONS_OBJECTS = {
    "Sun": 10,
    "Moon": 301,
    "Mercury": 199,
    "Venus": 299,
    "Mars": 499,
    "Jupiter": 599,
    "Saturn": 699,
    "Uranus": 799,
    "Neptune": 899,
    "Pluto": 999,
    "Chiron": 2060,
}

SWISS_OBJECTS = {
    "Ceres": swe.CERES,
    "Pallas": swe.PALLAS,
    "Juno": swe.JUNO,
    "Vesta": swe.VESTA,
    "Haumea": swe.HAUMEA,
    "Makemake": swe.MAKEMAKE,
    "Varuna": 20000,
    "Ixion": 28978,
    "Typhon": 42355,
    "Salacia": 120347,
}

def fetch_from_horizons(obj_id, jd):
    try:
        eph = Horizons(id=obj_id, location="500@399", epochs=jd).ephemerides()
        lon = float(eph["EclLon"][0])
        lat = float(eph["EclLat"][0])
        return lon, lat, "jpl"
    except Exception as e:
        print(f"[Fallback] Horizons failed for {obj_id} → {e}")
        return None

def fetch_from_swiss(obj_id, jd):
    try:
        lon, lat, _ = swe.calc_ut(jd, obj_id)
        return lon, lat, "swiss"
    except Exception as e:
        print(f"Error: Swiss failed for {obj_id}: {e}")
        return None

def main():
    # Start Aug 24, 2025 18:00 UTC, step daily, 6 months
    start = datetime.datetime(2025, 8, 24, 18, 0, tzinfo=pytz.utc)
    days = 183  # ~6 months
    results = {}

    for i in range(days):
        dt = start + datetime.timedelta(days=i)
        jd = swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute/60.0)
        date_key = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        results[date_key] = {}

        # Horizons first
        for name, hid in HORIZONS_OBJECTS.items():
            res = fetch_from_horizons(hid, jd)
            if res is None:
                res = fetch_from_swiss(getattr(swe, name.upper(), None), jd)
            if res is None:
                results[date_key][name] = {"ecl_lon": None, "ecl_lat": None, "src": "nan"}
            else:
                lon, lat, src = res
                results[date_key][name] = {"ecl_lon": lon, "ecl_lat": lat, "src": src}

        # Swiss for minor bodies
        for name, sid in SWISS_OBJECTS.items():
            res = fetch_from_swiss(sid, jd)
            if res is None:
                results[date_key][name] = {"ecl_lon": None, "ecl_lat": None, "src": "nan"}
            else:
                lon, lat, src = res
                results[date_key][name] = {"ecl_lon": lon, "ecl_lat": lat, "src": src}

    # Metadata
    utc_now = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
    pacific_now = utc_now.astimezone(pytz.timezone("America/Los_Angeles"))

    meta = {
        "generated_at_utc": utc_now.isoformat(),
        "generated_at_pacific": pacific_now.isoformat(),
        "source_order": ["jpl", "swiss", "calculated"],
    }

    out = {"meta": meta, "results": results}
    with open("docs/feed_6month.json", "w") as f:
        json.dump(out, f, indent=2)

    print("✅ 6-month feed written to docs/feed_6month.json")

if __name__ == "__main__":
    main()
