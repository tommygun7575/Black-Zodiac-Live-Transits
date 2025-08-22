#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_feed_60day.py — build a 60-day projected transit feed.
Does not interfere with generate_feed.py (live feed).
Writes docs/feed_60day.json for use by GPT Store app.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import swisseph as swe

# ---- Settings ----
DAYS_AHEAD = 60
HOUSE_SYSTEM = b'P'  # Placidus
OBSERVER = "geocentric Earth"
EPHE_PATH = "ephe"

# ---- Setup ----
if not os.path.isdir(EPHE_PATH):
    raise RuntimeError(f"Ephemeris path '{EPHE_PATH}' not found. Did workflow fetch files?")

swe.set_ephe_path(EPHE_PATH)
print("Using Swiss Ephemeris path:", EPHE_PATH)

# Example fixed stars (expand if needed)
FIXED_STARS = [
    {"id": "Regulus",   "label": "Regulus (Alpha Leo)",    "ra_deg": 152.0929625, "dec_deg": 11.9672083},
    {"id": "Spica",     "label": "Spica (Alpha Vir)",      "ra_deg": 201.2982475, "dec_deg": -11.1613194},
    {"id": "Sirius",    "label": "Sirius (Alpha CMa)",     "ra_deg": 101.2871553, "dec_deg": -16.7161159},
    {"id": "Aldebaran", "label": "Aldebaran (Alpha Tau)",  "ra_deg": 68.9801625,  "dec_deg": 16.5093028},
]

# ---- Helpers ----

def swe_calc(body, dt):
    """Swiss Ephemeris wrapper for planets."""
    jd = swe.julday(
        dt.year, dt.month, dt.day,
        dt.hour + dt.minute / 60 + dt.second / 3600.0,
        swe.GREG_CAL
    )
    try:
        xx, _ = swe.calc_ut(jd, body)
        return float(xx[0]), float(xx[1])  # lon, lat
    except Exception as e:
        raise RuntimeError(f"Swiss Ephemeris failed for body {body}: {e}")

def houses_and_points(lat, lon, dt):
    """Compute ASC, MC, houses, Parts of Fortune/Spirit."""
    jd = swe.julday(
        dt.year, dt.month, dt.day,
        dt.hour + dt.minute / 60 + dt.second / 3600.0,
        swe.GREG_CAL
    )
    ascmc, cusp, _ = swe.houses_ex(jd, lat, lon, HOUSE_SYSTEM)

    asc = ascmc[0]
    mc = ascmc[1]

    # Simplified: Fortune/Spirit using day formula
    sun_lon, _ = swe_calc(swe.SUN, dt)
    moon_lon, _ = swe_calc(swe.MOON, dt)
    fortune = (asc + moon_lon - sun_lon) % 360
    spirit = (asc + sun_lon - moon_lon) % 360

    return {
        "ASC": asc,
        "MC": mc,
        "houses": cusp,
        "PartOfFortune": fortune,
        "PartOfSpirit": spirit
    }

def add_fixed_star(star, dt):
    """Add fixed star entry."""
    return {
        "targetname": star["label"],
        "id": star["id"],
        "datetime_utc": dt.isoformat(),
        "ra_deg": star["ra_deg"],
        "dec_deg": star["dec_deg"],
        "epoch": "J2000",
        "source": "fixed"
    }

# ---- Main ----

def main():
    start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    feed = {
        "feed": {
            "generated_at_utc": datetime.utcnow().isoformat(),
            "observer": OBSERVER,
            "range_days": DAYS_AHEAD,
            "objects": []
        }
    }

    for d in range(DAYS_AHEAD):
        dt = start + timedelta(days=d)

        # Planets Sun → Pluto + Chiron
        planet_map = {
            "10": swe.SUN, "301": swe.MOON, "199": swe.MERCURY,
            "299": swe.VENUS, "499": swe.MARS, "599": swe.JUPITER,
            "699": swe.SATURN, "799": swe.URANUS, "899": swe.NEPTUNE,
            "999": swe.PLUTO, "2060": getattr(swe, "CHIRON", 15)
        }

        for pid, body in planet_map.items():
            lon, lat = swe_calc(body, dt)
            feed["feed"]["objects"].append({
                "id": pid,
                "targetname": str(body),
                "datetime_utc": dt.isoformat(),
                "ecl_lon_deg": lon,
                "ecl_lat_deg": lat,
                "source": "swiss"
            })

        # Houses, ASC, MC, Parts (using Greenwich lat/lon = 51.5N, 0W)
        points = houses_and_points(51.5, 0.0, dt)
        feed["feed"]["objects"].append({
            "id": "ASC",
            "targetname": "Ascendant",
            "datetime_utc": dt.isoformat(),
            "ecl_lon_deg": points["ASC"],
            "source": "swiss"
        })
        feed["feed"]["objects"].append({
            "id": "MC",
            "targetname": "Midheaven",
            "datetime_utc": dt.isoformat(),
            "ecl_lon_deg": points["MC"],
            "source": "swiss"
        })
        feed["feed"]["objects"].append({
            "id": "Houses",
            "targetname": "Houses",
            "datetime_utc": dt.isoformat(),
            "houses_deg": points["houses"],
            "source": "swiss"
        })
        feed["feed"]["objects"].append({
            "id": "PartOfFortune",
            "targetname": "Part of Fortune",
            "datetime_utc": dt.isoformat(),
            "ecl_lon_deg": points["PartOfFortune"],
            "branch": "day",
            "source": "swiss"
        })
        feed["feed"]["objects"].append({
            "id": "PartOfSpirit",
            "targetname": "Part of Spirit",
            "datetime_utc": dt.isoformat(),
            "ecl_lon_deg": points["PartOfSpirit"],
            "branch": "day",
            "source": "swiss"
        })

        # Fixed stars
        for star in FIXED_STARS:
            feed["feed"]["objects"].append(add_fixed_star(star, dt))

    Path("docs").mkdir(exist_ok=True)
    with open("docs/feed_60day.json", "w") as f:
        json.dump(feed, f, indent=2)

    print("[OK] Wrote docs/feed_60day.json")

if __name__ == "__main__":
    main()
