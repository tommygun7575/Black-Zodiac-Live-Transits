#!/usr/bin/env python3
"""
build_overlays.py
Black Zodiac Overlay Feed Generator (V3.3.0)

Pipeline:
1. JPL Horizons (primary)
2. Swiss Ephemeris (fallback)
3. Astro-Seek Aug2025–Feb2026 JSON (final fallback)

Output: docs/feed_overlay.json
"""

import json
import datetime
from pathlib import Path
import swisseph as swe
from astroquery.jplhorizons import Horizons

OUTPUT_FILE = Path("docs/feed_overlay.json")
ASTROSEEK_FILE = Path("data/fallback_aug2025_2026.json")

# Natal data
NATALS = {
    "Tommy": {"year": 1975, "month": 9, "day": 12, "hour": 9, "minute": 20, "lat": 40.84478, "lon": -73.86483},
    "Milena": {"year": 1992, "month": 3, "day": 29, "hour": 14, "minute": 4, "lat": 39.1638, "lon": -119.7674},
    "Christine": {"year": 1989, "month": 7, "day": 5, "hour": 15, "minute": 1, "lat": 40.72982, "lon": -73.21039}
}

BODIES = [
    # majors
    "Sun","Moon","Mercury","Venus","Mars","Jupiter","Saturn","Uranus","Neptune","Pluto",
    # asteroids / minors
    "Chiron","Vesta","Psyche","Amor","Eros","Sappho","Karma",
    "Pholus","Chariklo",
    # TNOs
    "Eris","Sedna","Haumea","Makemake","Varuna","Ixion","Typhon","Salacia"
]

def jpl_position(target, dt):
    try:
        obj = Horizons(id=target, location="500@399", epochs=dt.timestamp(), id_type="majorbody")
        eph = obj.elements()
        return {"lon": float(eph['Q'][0]), "lat": 0.0, "source": "jpl"}
    except Exception:
        return None

def swiss_position(target, jd):
    mapping = {
        "Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY,
        "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
        "Saturn": swe.SATURN, "Uranus": swe.URANUS,
        "Neptune": swe.NEPTUNE, "Pluto": swe.PLUTO,
        "Chiron": swe.CHIRON, "Vesta": swe.VESTA
    }
    if target not in mapping:
        return None
    try:
        lon, lat, _ = swe.calc_ut(jd, mapping[target])
        return {"lon": lon, "lat": lat, "source": "swiss"}
    except Exception:
        return None

def astroseek_lookup(target):
    if not ASTROSEEK_FILE.exists():
        return None
    with open(ASTROSEEK_FILE, "r") as f:
        data = json.load(f)
    if target in data:
        return {"lon": data[target].get("lon"), "lat": data[target].get("lat", 0.0), "source": "astroseek"}
    return None

def main():
    now = datetime.datetime.utcnow()

    overlay = {
        "meta": {
            "generated_at_utc": now.isoformat(),
            "source_hierarchy": ["jpl", "swiss", "astroseek"],
            "black_zodiac_version": "3.3.0"
        },
        "charts": {}
    }

    for person, d in NATALS.items():
        jd = swe.julday(d["year"], d["month"], d["day"], d["hour"] + d["minute"]/60.0)
        chart_objects = []

        for body in BODIES:
            pos = jpl_position(body, now)
            if not pos:
                pos = swiss_position(body, jd)
            if not pos:
                pos = astroseek_lookup(body)
            chart_objects.append({
                "id": body,
                "targetname": body,
                "ecl_lon_deg": pos["lon"] if pos else None,
                "ecl_lat_deg": pos["lat"] if pos else 0.0,
                "source": pos["source"] if pos else "missing"
            })

        overlay["charts"][person] = chart_objects

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(overlay, f, indent=2)

    print(f"[OK] Overlay feed written to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
