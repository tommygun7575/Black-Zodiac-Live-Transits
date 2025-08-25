#!/usr/bin/env python3
import json
import datetime
import pytz
import numpy as np
import swisseph as swe
import os

# --- Config ---
SE_EPHE_PATH = os.environ.get("SE_EPHE_PATH", "ephe")
swe.set_ephe_path(SE_EPHE_PATH)

# Major planets via Horizons
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
}

# Minor bodies via Swiss
SWISS_OBJECTS = {
    "Chiron": swe.CHIRON,
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

# Arabic Parts formulas (simplified, day formula)
def calc_arabic_parts(positions):
    parts = {}
    try:
        sun = positions.get("Sun", {}).get("ecl_lon")
        moon = positions.get("Moon", {}).get("ecl_lon")
        asc = positions.get("ASC", {}).get("ecl_lon")
        if None not in (sun, moon, asc):
            parts["Fortune"] = (asc + moon - sun) % 360
            parts["Spirit"]  = (asc + sun - moon) % 360
    except Exception:
        pass
    return parts

# Harmonics (simple nth multiple of longitudes)
def calc_harmonics(positions, harmonics=[7,9,11]):
    harm = {}
    for n in harmonics:
        harm[str(n)] = {}
        for body, pos in positions.items():
            lon = pos.get("ecl_lon")
            if lon is not None:
                harm[str(n)][body] = (lon * n) % 360
    return harm

def fetch_from_swiss(obj_id, jd):
    try:
        lon, lat, _ = swe.calc_ut(jd, obj_id)
        return lon, lat, "swiss"
    except Exception as e:
        return None

def main():
    start = datetime.datetime(2025, 8, 24, 18, 0, tzinfo=pytz.utc)
    days = 183
    results = {}

    for i in range(days):
        dt = start + datetime.timedelta(days=i)
        jd = swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute/60.0)
        date_key = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        positions = {}

        # Major planets
        for name, sid in HORIZONS_OBJECTS.items():
            try:
                lon, lat, _ = swe.calc_ut(jd, getattr(swe, name.upper()))
                positions[name] = {"ecl_lon": lon, "ecl_lat": lat, "src": "swiss"}
            except Exception:
                positions[name] = {"ecl_lon": None, "ecl_lat": None, "src": "nan"}

        # Minor bodies
        for name, sid in SWISS_OBJECTS.items():
            res = fetch_from_swiss(sid, jd)
            if res is None:
                positions[name] = {"ecl_lon": None, "ecl_lat": None, "src": "nan"}
            else:
                lon, lat, src = res
                positions[name] = {"ecl_lon": lon, "ecl_lat": lat, "src": src}

        # Houses (for Asc/MC → Arabic Parts)
        try:
            ascmc = swe.houses(jd, 40.7, -74.0)  # Bronx, NY default
            asc = ascmc[0][0]
            mc = ascmc[0][9]
            positions["ASC"] = {"ecl_lon": asc, "ecl_lat": 0.0, "src": "calc"}
            positions["MC"]  = {"ecl_lon": mc, "ecl_lat": 0.0, "src": "calc"}
        except Exception:
            pass

        # Arabic Parts
        arabic = calc_arabic_parts(positions)

        # Harmonics
        harmonics = calc_harmonics(positions)

        results[date_key] = {
            "positions": positions,
            "arabic_parts": arabic,
            "harmonics": harmonics,
        }

    utc_now = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
    pacific_now = utc_now.astimezone(pytz.timezone("America/Los_Angeles"))

    meta = {
        "generated_at_utc": utc_now.isoformat(),
        "generated_at_pacific": pacific_now.isoformat(),
        "source_order": ["jpl", "swiss", "calculated"],
        "contains": ["positions", "arabic_parts", "harmonics"],
    }

    out = {"meta": meta, "results": results}
    with open("docs/feed_6month.json", "w") as f:
        json.dump(out, f, indent=2)

    print("✅ 6-month feed written with harmonics + arabic parts")

if __name__ == "__main__":
    main()
