#!/usr/bin/env python3
import os, sys, json, warnings
from datetime import datetime, timedelta
from astroquery.jplhorizons import Horizons
import swisseph as swe

warnings.filterwarnings("ignore", message=".*masked element.*")

# Horizons (majors only)
HORIZONS_BODIES = [
    "Sun", "Moon", "Mercury", "Venus", "Mars",
    "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto"
]

# Swiss (minor planets, asteroids, TNOs)
SWISS_BODIES = [
    "Chiron", "Ceres", "Pallas", "Juno", "Vesta",
    "Haumea", "Makemake", "Varuna", "Ixion", "Typhon", "Salacia"
]

# Harmonics we want
HARMONICS = [2, 3, 5, 7, 9]

OUTPUT_FILE = "docs/feed_6month.json"
STARS_FILE = "sefstars.txt"

def load_fixed_stars(path=STARS_FILE):
    stars = {}
    if not os.path.exists(path):
        print(f"[Warn] Fixed stars file {path} not found, skipping.")
        return stars
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                parts = [p.strip() for p in line.replace(",", " ").split()]
                if len(parts) < 3:
                    continue
                name = parts[0]
                lon = float(parts[1])
                lat = float(parts[2])
                stars[name] = (lon, lat, "fixed")
            except Exception as e:
                print(f"[Skip] Could not parse star line: {line} ({e})")
    return stars

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
        bid = mapping.get(body.lower(), swe.PLUTO)
        result = swe.calc_ut(jd, bid, flag)
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            lon = result[0] % 360
            lat = result[1]
            return lon, lat, "swiss"
        raise ValueError(f"Unexpected Swiss return for {body}: {result}")
    except Exception as e:
        print(f"[Error] Swiss failed for {body} at JD {jd}: {e}")
        return None

def apply_harmonics(day_data):
    """Add harmonic overlays for each body in a given day's dataset."""
    for h in HARMONICS:
        for body, pos in list(day_data.items()):
            if pos is None or not isinstance(pos, (list, tuple)):
                continue
            try:
                lon = pos[0]
                # Harmonic longitude calculation
                h_lon = (lon * h) % 360
                key = f"{body}_H{h}"
                day_data[key] = (h_lon, pos[1], f"h{h}")
            except Exception:
                continue
    return day_data

def main():
    start = datetime(2025, 8, 24)
    end   = datetime(2026, 2, 24)
    delta = timedelta(days=1)

    swe.set_ephe_path("ephe")
    fixed_stars = load_fixed_stars()

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

        # Fixed stars (same each day)
        for name, starpos in fixed_stars.items():
            results[str(d.date())][name] = starpos

        # Apply harmonics
        results[str(d.date())] = apply_harmonics(results[str(d.date())])

        d += delta

    with open(OUTPUT_FILE, "w") as f:
        json.dump({
            "generated_at_utc": datetime.utcnow().isoformat(),
            "results": results
        }, f, indent=2)

    print(f"Finished generating {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
