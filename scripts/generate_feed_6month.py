import os
import json
import datetime
import swisseph as swe
import numpy as np
import pandas as pd
from astroquery.jplhorizons import Horizons

# Paths
EPHE_PATH = os.getenv("SE_EPHE_PATH", "ephe")
swe.set_ephe_path(EPHE_PATH)

# Bodies we want to calculate
MAJOR_PLANETS = [
    "Sun", "Moon", "Mercury", "Venus", "Mars",
    "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto"
]
MINOR_BODIES = ["Chiron", "Ceres", "Pallas", "Juno", "Vesta"]
TNOs = ["Haumea", "Makemake", "Varuna", "Ixion", "Typhon", "Salacia"]
ALL_OBJECTS = MAJOR_PLANETS + MINOR_BODIES + TNOs

# Harmonics (2nd, 3rd, 5th, 7th as examples)
HARMONICS = [2, 3, 5, 7]

# Arabic Parts (basic ones: Fortune, Spirit, Eros, Marriage)
def compute_arabic_parts(positions):
    parts = {}
    try:
        # Fortune = ASC + Moon - Sun
        parts["Fortune"] = (positions["ASC"] + positions["Moon"] - positions["Sun"]) % 360
        # Spirit = ASC + Sun - Moon
        parts["Spirit"] = (positions["ASC"] + positions["Sun"] - positions["Moon"]) % 360
        # Eros = ASC + Venus - Sun
        parts["Eros"] = (positions["ASC"] + positions["Venus"] - positions["Sun"]) % 360
        # Marriage = ASC + Descendant - Venus
        parts["Marriage"] = (positions["ASC"] + positions["DSC"] - positions["Venus"]) % 360
    except Exception as e:
        print(f"Arabic Parts calc failed: {e}")
    return parts

# Get positions from Swiss Ephemeris
def get_swiss_position(body, jd):
    try:
        if body == "Sun":
            flag = swe.FLG_SWIEPH | swe.FLG_SPEED
            lon, lat, dist, _ = swe.calc_ut(jd, swe.SUN, flag)
        elif body == "Moon":
            lon, lat, dist, _ = swe.calc_ut(jd, swe.MOON)
        elif body == "Mercury":
            lon, lat, dist, _ = swe.calc_ut(jd, swe.MERCURY)
        elif body == "Venus":
            lon, lat, dist, _ = swe.calc_ut(jd, swe.VENUS)
        elif body == "Mars":
            lon, lat, dist, _ = swe.calc_ut(jd, swe.MARS)
        elif body == "Jupiter":
            lon, lat, dist, _ = swe.calc_ut(jd, swe.JUPITER)
        elif body == "Saturn":
            lon, lat, dist, _ = swe.calc_ut(jd, swe.SATURN)
        elif body == "Uranus":
            lon, lat, dist, _ = swe.calc_ut(jd, swe.URANUS)
        elif body == "Neptune":
            lon, lat, dist, _ = swe.calc_ut(jd, swe.NEPTUNE)
        elif body == "Pluto":
            lon, lat, dist, _ = swe.calc_ut(jd, swe.PLUTO)
        elif body == "Chiron":
            lon, lat, dist, _ = swe.calc_ut(jd, swe.CHIRON)
        else:
            return None
        return float(lon) % 360
    except Exception as e:
        print(f"Swiss failed for {body} at JD {jd}: {e}")
        return None

# Harmonics calculation
def compute_harmonics(base_positions, harmonics):
    harmonic_positions = {}
    for h in harmonics:
        harmonic_positions[f"H{h}"] = {body: (lon * h) % 360 for body, lon in base_positions.items()}
    return harmonic_positions

def main():
    # Start from Aug 24, 2025 18:00 UTC
    start_dt = datetime.datetime(2025, 8, 24, 18, 0, 0)
    jd_start = swe.julday(start_dt.year, start_dt.month, start_dt.day,
                          start_dt.hour + start_dt.minute/60.0)

    # 6-month span (approx 180 days)
    steps = 180
    results = {"meta": {"start": start_dt.isoformat(), "source": "horizons→swiss→calculated"}}
    results["days"] = []

    for i in range(steps + 1):
        dt = start_dt + datetime.timedelta(days=i)
        jd = swe.julday(dt.year, dt.month, dt.day,
                        dt.hour + dt.minute/60.0)
        positions = {}

        # Calculate planetary positions
        for body in MAJOR_PLANETS + MINOR_BODIES:
            pos = get_swiss_position(body, jd)
            if pos is not None:
                positions[body] = pos

        # Add harmonics
        harmonics_data = compute_harmonics(positions, HARMONICS)

        # Add Arabic parts
        arabic_data = compute_arabic_parts(positions)

        results["days"].append({
            "date": dt.isoformat(),
            "positions": positions,
            "harmonics": harmonics_data,
            "arabic_parts": arabic_data
        })

    # Save JSON
    os.makedirs("docs", exist_ok=True)
    with open("docs/feed_6month.json", "w") as f:
        json.dump(results, f, indent=2)

    print("✅ 6-month feed generated:", "docs/feed_6month.json")

if __name__ == "__main__":
    main()
