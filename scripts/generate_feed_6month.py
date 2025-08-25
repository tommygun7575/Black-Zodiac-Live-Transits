#!/usr/bin/env python3
import os, sys, json, warnings
from datetime import datetime, timedelta
from astroquery.jplhorizons import Horizons
import swisseph as swe

warnings.filterwarnings("ignore", message=".*masked element.*")

# Split bodies into two groups
HORIZONS_BODIES = [
    "Sun", "Moon", "Mercury", "Venus", "Mars",
    "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto"
    # add "Chiron" here if you want it from Horizons
]

SWISS_BODIES = [
    "Chiron", "Ceres", "Pallas", "Juno", "Vesta",
    "Haumea", "Makemake", "Varuna", "Ixion", "Typhon", "Salacia"
    # add other asteroids or minor bodies here
]

OUTPUT_FILE = "docs/feed_6month.json"

def get_from_horizons(body, jd):
    try:
        obj = Horizons(id=body, id_type="majorbody",
                       location="@earth", epochs=jd)
        eph = obj.ephemerides()
        lon = float(eph["EclLon"][0])
        lat = float(eph["EclLat"][0])
        if not (0.0 <= lon < 360.0):
            raise ValueError("Bad longitude")
        return lon, lat, "jpl"
    except Exception as e:
        print(f"[Error] Horizons failed for {body} at JD {jd}: {e}")
        return None

def get_from_swiss(body, jd, flag=swe.FLG_SWIEPH):
    try:
        # Map common bodies to Swiss constants
        mapping = {
            "sun": swe.SUN, "moon": swe.MOON,
            "mercury": swe.MERCURY, "venus": swe.VENUS,
            "mars": swe.MARS, "jupiter": swe.JUPITER,
            "saturn": swe.SATURN, "uranus": swe.URANUS,
            "neptune": swe.NEPTUNE, "pluto": swe.PLUTO,
            "chiron": swe.CHIRON, "ceres": swe.CERES,
            "pallas": swe.PALLAS, "juno": swe.JUNO,
            "vesta": swe.VESTA
        }
        bid = mapping.get(body.lower(), swe.PLUTO)  # fallback id

        result = swe.calc_ut(jd, bid, flag)
        if isinstance(result, (list, tuple)):
            if len(result) >= 2:
                lon = result[0] % 360
                lat = result[1]
                return lon, lat, "swiss"
        raise ValueError(f"Unexpected Swiss return for {body}: {result}")
    except Exception as e:
        print(f"[Error] Swiss failed for {body} at JD {jd}: {e}")
        return None

def main():
    start = datetime(2025, 8, 24)
    end   = datetime(2026, 2, 24)
    delta = timedelta(days=1)

    swe.set_ephe_path("ephe")
    results = {}
    d = start
    while d <= end:
        jd = swe.julday(d.year, d.month, d.day, 0.0)
        results[str(d.date())] = {}

        # Horizons group
        for body in HORIZONS_BODIES:
            pos = get_from_horizons(body, jd)
            if pos is None:
                pos = get_from_swiss(body, jd)
            results[str(d.date())][body] = pos

        # Swiss-only group
        for body in SWISS_BODIES:
            pos = get_from_swiss(body, jd)
            results[str(d.date())][body] = pos

        d += delta

    with open(OUTPUT_FILE, "w") as f:
        json.dump({
            "generated_at_utc": datetime.utcnow().isoformat(),
            "results": results
        }, f, indent=2)

    print(f"Finished generating {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
