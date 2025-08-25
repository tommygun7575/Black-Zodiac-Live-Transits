#!/usr/bin/env python3
import os
import sys
import json
import datetime
import pytz
import numpy as np
from astroquery.jplhorizons import Horizons

# --- Dual import: Linux (swisseph) vs Windows (pyswisseph) ---
try:
    import swisseph as swe   # Linux / GitHub Actions
except ImportError:
    import pyswisseph as swe   # Windows local

# Configure Swiss Ephemeris path
EPHE_PATH = os.path.join(os.getcwd(), "ephe")
swe.set_ephe_path(EPHE_PATH)

if not os.path.exists(EPHE_PATH):
    raise RuntimeError(f"❌ Swiss ephemeris path not found: {EPHE_PATH}")

# Bodies for Horizons + Swiss fallback
JPL_IDS = {
    "Sun": 10, "Moon": 301, "Mercury": 199, "Venus": 299,
    "Mars": 499, "Jupiter": 599, "Saturn": 699,
    "Uranus": 799, "Neptune": 899, "Pluto": 999,
    "Chiron": 2060, "Ceres": 1, "Pallas": 2, "Juno": 3, "Vesta": 4
}

SWISS_IDS = {
    "Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY,
    "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN, "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE,
    "Pluto": swe.PLUTO, "Chiron": swe.CHIRON,
    "Ceres": swe.CERES, "Pallas": swe.PALLAS,
    "Juno": swe.JUNO, "Vesta": swe.VESTA
}

FIXED_STAR_FILE = "sefstars.txt"

def get_fixed_stars():
    stars = {}
    if not os.path.exists(FIXED_STAR_FILE):
        return stars
    with open(FIXED_STAR_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if len(parts) < 3:
                continue
            try:
                name = parts[0]
                lon = float(parts[1])
                lat = float(parts[2])
                stars[name] = (lon, lat, "fixed")
            except ValueError:
                continue
    return stars

def swe_calc(body, dt):
    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute / 60.0 + dt.second / 3600.0)
    result = swe.calc_ut(jd, SWISS_IDS[body])

    # Normalize return format
    if isinstance(result, tuple):
        # Case 1: (lon, lat)
        if len(result) == 2 and all(isinstance(x, (int, float)) for x in result):
            lon, lat = result
            return lon % 360.0, lat
        # Case 2: (lon, lat, dist)
        if len(result) == 3:
            lon, lat, dist = result
            return lon % 360.0, lat
        # Case 3: ((lon, lat, dist), retflag)
        if len(result) == 2 and isinstance(result[0], (list, tuple)):
            lon, lat, dist = result[0]
            return lon % 360.0, lat

    raise RuntimeError(f"Unexpected Swiss return format: {result}")

def get_jpl_ephemeris(body, dt):
    try:
        obj = Horizons(id=JPL_IDS[body], location="500@399",
                       epochs=dt.strftime("%Y-%m-%d %H:%M"),
                       id_type=None)
        eph = obj.ephemerides()
        if len(eph) == 0:
            return None
        lon = float(eph["EclLon"][0])
        lat = float(eph["EclLat"][0])
        return lon, lat
    except Exception:
        return None

def get_positions(dt):
    result = {}
    for body in JPL_IDS.keys():
        coords = get_jpl_ephemeris(body, dt)

        if coords:  # JPL success
            result[body] = (coords[0], coords[1], "jpl")
        else:  # fallback to Swiss
            try:
                lon, lat = swe_calc(body, dt)
                result[body] = (lon, lat, "swiss")
            except Exception as e:
                raise RuntimeError(f"❌ Swiss failed for {body} on {dt}: {e}")
    return result

def main():
    now = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
    six_months = now + datetime.timedelta(days=180)
    step_days = 1  # daily sampling

    data = {
        "meta": {
            "generated_at_utc": now.isoformat(),
            "range_utc": [now.isoformat(), six_months.isoformat()],
            "source_order": ["jpl", "swiss", "fixed"]
        },
        "transits": {}
    }

    stars = get_fixed_stars()

    dt = now
    while dt <= six_months:
        day_key = dt.strftime("%Y-%m-%d")
        data["transits"][day_key] = {}
        positions = get_positions(dt)
        for body, (lon, lat, src) in positions.items():
            data["transits"][day_key][body] = {
                "ecl_lon_deg": lon,
                "ecl_lat_deg": lat,
                "source": src
            }
        for star, (lon, lat, src) in stars.items():
            data["transits"][day_key][star] = {
                "ecl_lon_deg": lon,
                "ecl_lat_deg": lat,
                "source": src
            }
        dt += datetime.timedelta(days=step_days)

    outpath = os.path.join("docs", "feed_6month.json")
    os.makedirs("docs", exist_ok=True)
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"✅ 6-month feed written to {outpath}")

if __name__ == "__main__":
    main()
