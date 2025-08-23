#!/usr/bin/env python3
"""
build_overlays.py
Black Zodiac Overlay Feed Generator (V3.3.0)

Rewritten: 2025-08-23

Builds a complete overlay JSON for Tommy, Milena, Christine
using strict source hierarchy:

1. JPL Horizons (primary for majors, minors, asteroids, TNOs, fixed stars)
2. Swiss Ephemeris (secondary filler for anything Horizons misses)
3. SEAS / SEPL / SE1 local files (third-tier fallback)
4. Aug 2025–2026 fallback JSON (final patch)

Output: docs/feed_overlay.json
"""

import os
import json
import datetime
from pathlib import Path

import swisseph as swe
from astroquery.jplhorizons import Horizons

# ------------------------
# CONFIG
# ------------------------

OUTPUT_FILE = Path("docs/feed_overlay.json")

NATALS = {
    "Tommy": {"lat": 40.84478, "lon": -73.86483},
    "Milena": {"lat": 39.1638, "lon": -119.7674},
    "Christine": {"lat": 40.72982, "lon": -73.21039}
}

BODIES = [
    # majors
    "Sun","Moon","Mercury","Venus","Mars","Jupiter","Saturn","Uranus","Neptune","Pluto",
    # key asteroids
    "Chiron","Vesta","Psyche","Amor","Eros","Sappho","Karma",
    # centaurs
    "Pholus","Chariklo",
    # TNOs
    "Eris","Sedna","Haumea","Makemake","Varuna","Ixion","Typhon","Salacia",
    # Aether symbolic
    "Vulcan","Persephone","Hades","Proserpina","Isis",
    # Fixed stars
    "Regulus","Spica","Sirius","Aldebaran"
]

FALLBACK_FILES = [
    Path("data/seas18.json"),
    Path("data/se1.json"),
    Path("data/sepl.json"),
    Path("data/se_extra.json"),
    Path("data/fallback_aug2025_2026.json"),
]

# ------------------------
# HELPERS
# ------------------------

def jpl_position(target, dt):
    """Try to fetch body position from JPL Horizons."""
    try:
        obj = Horizons(
            id=target, location='500@399',
            epochs=dt.timestamp(),
            id_type='majorbody'
        )
        eph = obj.elements()
        return {"lon": float(eph['Q'][0]), "lat": 0.0, "source": "jpl"}
    except Exception:
        return None

def swiss_position(target, jd):
    """Fallback to Swiss Ephemeris for major planets."""
    try:
        mapping = {
            "Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY,
            "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
            "Saturn": swe.SATURN, "Uranus": swe.URANUS,
            "Neptune": swe.NEPTUNE, "Pluto": swe.PLUTO
        }
        if target not in mapping:
            return None
        lon, lat, _ = swe.calc_ut(jd, mapping[target])
        return {"lon": lon, "lat": lat, "source": "swiss"}
    except Exception:
        return None

def fallback_lookup(target):
    """Fallback JSON lookup (SEAS/SEPL/SE1/aug2025-2026)."""
    for file in FALLBACK_FILES:
        if not file.exists():
            continue
        with open(file, "r") as f:
            data = json.load(f)
        if target in data:
            return {
                "lon": data[target].get("lon"),
                "lat": data[target].get("lat", 0.0),
                "source": f"fallback:{file.name}"
            }
    return {"lon": None, "lat": 0.0, "source": "missing"}

# ------------------------
# MAIN
# ------------------------

def main():
    now = datetime.datetime.utcnow()
    jd = swe.julday(now.year, now.month, now.day,
                    now.hour + now.minute/60.0)

    overlay = {
        "meta": {
            "generated_at_utc": now.isoformat(),
            "observer": "geocentric Earth",
            "source_hierarchy": ["jpl", "swiss", "seas/sepl/se1", "fallback"],
            "black_zodiac_version": "3.3.0"
        },
        "objects": []
    }

    for body in BODIES:
        pos = jpl_position(body, now)
        if not pos:
            pos = swiss_position(body, jd)
        if not pos:
            pos = fallback_lookup(body)
        overlay["objects"].append({
            "id": body,
            "targetname": body,
            "ecl_lon_deg": pos["lon"],
            "ecl_lat_deg": pos["lat"],
            "source": pos["source"]
        })

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(overlay, f, indent=2)

    print(f"[OK] Overlay feed written to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
