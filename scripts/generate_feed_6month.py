#!/usr/bin/env python3
import os, sys, json, warnings
from datetime import datetime, timedelta
from astroquery.jplhorizons import Horizons
import swisseph as swe

warnings.filterwarnings("ignore", message=".*masked element.*")

# Bodies to compute (simplified list; extend as needed)
BODIES = [
    "Sun", "Moon", "Mercury", "Venus", "Mars",
    "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto",
    "Chiron", "Ceres", "Pallas", "Juno", "Vesta",
    "Haumea", "Makemake", "Varuna", "Ixion", "Typhon", "Salacia"
]

OUTPUT_FILE = "docs/feed_6month.json"

def get_from_horizons(body, jd, id_type="majorbody"):
    try:
        obj = Horizons(id=body, id_type=id_type,
                       location="@earth", epochs=jd)
        eph = obj.ephemerides()
        lon = float(eph["EclLon"][0])
        lat = float(eph["EclLat"][0])
        if not (0.0 <= lon < 360.0):
            raise ValueError("Bad longitude")
        return lon, lat, "jpl"
    except Exception:
        print(f"[Fallback] Horizons failed for {body} at JD {jd} → using Swiss")
        return None

def get_from_swiss(body, jd, flag=swe.FLG_SWIEPH):
    try:
        if body.lower() == "sun": bid = swe.SUN
        elif body.lower() == "moon": bid = swe.MOON
        elif body.lower() == "mercury": bid = swe.MERCURY
        elif body.lower() == "venus": bid = swe.VENUS
        elif body.lower() == "mars": bid = swe.MARS
        elif body.lower() == "jupiter": bid = swe.JUPITER
        elif body.lower() == "saturn": bid = swe.SATURN
        elif body.lower() == "uranus": bid = swe.URANUS
        elif body.lower() == "neptune": bid = swe.NEPTUNE
        elif body.lower() == "pluto": bid = swe.PLUTO
        else: bid = swe.PLUTO  # default if unmapped
        lon, lat, dist, _ = swe.calc_ut(jd, bid, flag)
        return lon % 360, lat, "swiss"
    except Exception as e:
        print(f"[Error] Swiss failed for {body} at JD {jd}: {e}")
        return None

def main():
    start = datetime(2025, 8, 24)
    end   = datetime(2026, 2, 24)
    delta = timedelta(days=1)

    swe.set_ephe_path("ephe")  # Swiss ephemeris files
    jd_start = swe.julday(start.year, start.month, start.day, 0.0)

    results = {}
    d = start
    while d <= end:
        jd = swe.julday(d.year, d.month, d.day, 0.0)
        results[str(d.date())] = {}
        for body in BODIES:
            pos = get_from_horizons(body, jd)
            if pos is None:
                pos = get_from_swiss(body, jd)
            results[str(d.date())][body] = pos
        d += delta

    with open(OUTPUT_FILE, "w") as f:
        json.dump({"generated_at_utc": datetime.utcnow().isoformat(),
                   "results": results}, f, indent=2)

    print(f"Finished generating {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
