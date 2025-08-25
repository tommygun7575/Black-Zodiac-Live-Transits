#!/usr/bin/env python3
import os
import json
import datetime
import numpy as np
import pandas as pd
from astroquery.jplhorizons import Horizons
import swisseph as swe

# -------------------------------
# Config
# -------------------------------
SE_EPHE_PATH = os.environ.get("SE_EPHE_PATH", "ephe")
swe.set_ephe_path(SE_EPHE_PATH)

OUTPUT_FILE = "docs/feed_6month.json"

# Start at Aug 24 2025 18:00 UTC
START_DATE = datetime.datetime(2025, 8, 24, 18, 0, 0)
DAYS = 180   # 6 months forward

# Horizons target IDs for major planets
HORIZONS_IDS = {
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

SWISS_IDS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,
    "Mars": swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN,
    "Uranus": swe.URANUS,
    "Neptune": swe.NEPTUNE,
    "Pluto": swe.PLUTO,
    "Chiron": swe.CHIRON,
    "Ceres": swe.CERES,
    "Pallas": swe.PALLAS,
    "Juno": swe.JUNO,
    "Vesta": swe.VESTA,
    "Haumea": 136108,
    "Makemake": 136472,
    "Varuna": 20000,
    "Ixion": 28978,
    "Typhon": 42355,
    "Salacia": 120347
}

# -------------------------------
# Helpers
# -------------------------------

def jd_from_datetime(dt):
    """Convert datetime to Julian Day"""
    return swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute/60.0 + dt.second/3600.0)

def get_from_horizons(body, dt):
    """Try to get lon/lat from JPL Horizons"""
    try:
        obj = Horizons(
            id=HORIZONS_IDS[body],
            location="@earth",
            epochs=dt.strftime("%Y-%m-%d %H:%M"),
            id_type="majorbody"
        )
        eph = obj.ephemerides()
        lon = float(eph["EclLon"][0])
        lat = float(eph["EclLat"][0])
        return lon, lat, "jpl"
    except Exception:
        return None

def get_from_swiss(body, dt):
    """Try to get lon/lat from Swiss Ephemeris"""
    try:
        jd = jd_from_datetime(dt)
        lon, lat, dist, speed = swe.calc_ut(jd, SWISS_IDS[body])
        return lon, lat, "swiss"
    except Exception:
        return None

def fallback(body):
    """Last resort if Horizons and Swiss fail"""
    return np.nan, np.nan, "fallback"

def compute_parts_and_harmonics(chart):
    """Dummy placeholder for Arabic Parts and Harmonics"""
    # Expand with your formulas later — right now just adds markers
    chart["arabic_parts"] = {"Part_of_Fortune": np.nan}
    chart["harmonics"] = {"H9": np.nan, "H13": np.nan}
    return chart

# -------------------------------
# Main
# -------------------------------
def main():
    results = {
        "meta": {
            "generated_at_utc": datetime.datetime.utcnow().isoformat(),
            "start_date": START_DATE.isoformat(),
            "days": DAYS,
            "source_order": ["jpl", "swiss", "calculated-fallback"]
        },
        "charts": {}
    }

    for day in range(DAYS):
        dt = START_DATE + datetime.timedelta(days=day)
        date_key = dt.strftime("%Y-%m-%d")

        chart = {}
        for body in SWISS_IDS.keys():
            data = get_from_horizons(body, dt)
            if data is None:
                data = get_from_swiss(body, dt)
            if data is None:
                data = fallback(body)
            lon, lat, source = data
            chart[body] = {"lon": lon, "lat": lat, "source": source}

        chart = compute_parts_and_harmonics(chart)
        results["charts"][date_key] = chart

    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"✅ Wrote {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
