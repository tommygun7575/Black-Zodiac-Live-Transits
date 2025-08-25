#!/usr/bin/env python3
import json
import os
import sys
import time
import requests
from datetime import datetime, timedelta, timezone

import swisseph as swe
import numpy as np
import pandas as pd
from astroquery.jplhorizons import Horizons

# --- CONFIG ---
EPHE_PATH = os.environ.get("SE_EPHE_PATH", "ephe")
swe.set_ephe_path(EPHE_PATH)
START_DATE = datetime(2025, 8, 24, 18, 0, tzinfo=timezone.utc)  # Aug 24 2025 18:00 UTC
DAYS = 180
OUTPUT_FILE = "docs/feed_6month.json"

# IDs
PLANETS = {
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
ASTEROIDS = {"Ceres": 1, "Pallas": 2, "Juno": 3, "Vesta": 4}
TNOs = {"Haumea": 136108, "Makemake": 136472, "Varuna": 20000, "Ixion": 28978,
        "Typhon": 42355, "Salacia": 120347}
BODIES = {**PLANETS, **ASTEROIDS, **TNOs}

# --- HELPERS ---
def horizons_ephem(body_id, dt):
    try:
        obj = Horizons(id=body_id, location="500@399",
                       epochs=dt.strftime("%Y-%m-%d %H:%M"),
                       id_type="majorbody")
        eph = obj.ephemerides()
        lon = float(eph["EclLon"][0])
        lat = float(eph["EclLat"][0])
        return lon, lat, "jpl"
    except Exception:
        return None

def swiss_ephem(body_id, dt):
    try:
        jd = swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute/60.0)
        lon, lat, _ = swe.calc_ut(jd, body_id)
        return lon, lat, "swiss"
    except Exception:
        return None

def fallback_calc(name, dt):
    # crude placeholder
    return 0.0, 0.0, "calculated-fallback"

def get_fixed_stars():
    stars = {}
    try:
        with open("sefstars.txt") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    name = parts[0].replace(",", "")
                    try:
                        lon = float(parts[1])
                        stars[name] = (lon, 0.0, "fixed")
                    except ValueError:
                        continue
    except FileNotFoundError:
        pass
    return stars

def compute_houses(dt):
    jd = swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute/60.0)
    try:
        cusps, ascmc = swe.houses(jd, 0, 0)  # geocentric default
        return {
            "ASC": (ascmc[0], 0.0, "houses"),
            "MC": (ascmc[1], 0.0, "houses"),
        }
    except Exception:
        return {}

def compute_arabic_parts(bodies):
    parts = {}
    if "Sun" in bodies and "Moon" in bodies and "ASC" in bodies:
        sun = bodies["Sun"][0]
        moon = bodies["Moon"][0]
        asc = bodies["ASC"][0]
        parts["Part_of_Fortune"] = ((asc + moon - sun) % 360, 0.0, "arabic")
    return parts

def compute_harmonics(bodies, n=9):
    harmonics = {}
    for name, (lon, _, _) in bodies.items():
        harmonics[f"{name}_harmonic{n}"] = ((lon * n) % 360, 0.0, "harmonic")
    return harmonics

# --- MAIN ---
def main():
    out = {
        "meta": {
            "generated_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "observer": "geocentric Earth",
            "black_zodiac_version": "3.3.0",
            "source_order": [
                "jpl (majors/asteroids/tnos)",
                "swiss (fallback)",
                "miriade (asteroid/tno fallback)",
                "fixed (stars)",
                "houses (cusps, ASC, MC)",
                "calculated (arabic parts)",
                "calculated (harmonics)",
                "calculated-fallback"
            ],
        },
        "days": []
    }

    for i in range(DAYS):
        dt = START_DATE + timedelta(days=i)
        date_entry = {"date": dt.strftime("%Y-%m-%d"), "bodies": {}}

        bodies = {}
        # Planets/Asteroids/TNOs
        for name, bid in BODIES.items():
            result = horizons_ephem(bid, dt)
            if not result:
                result = swiss_ephem(bid, dt)
            if not result:
                result = fallback_calc(name, dt)
            bodies[name] = result

            # polite delay for Horizons
            time.sleep(0.2)

        # Fixed stars
        bodies.update(get_fixed_stars())
        # Houses
        bodies.update(compute_houses(dt))
        # Arabic Parts
        bodies.update(compute_arabic_parts(bodies))
        # Harmonics
        bodies.update(compute_harmonics(bodies))

        date_entry["bodies"] = bodies
        out["days"].append(date_entry)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(out, f, indent=2)

    print(f"✅ Wrote {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
