#!/usr/bin/env python3
"""
compute_angles_and_parts.py
Computes angles (ASC, MC, Houses) and Arabic Parts for natal charts.
"""

import swisseph as swe
import datetime
import json
from pathlib import Path

OUTPUT_FILE = Path("docs/feed_angles.json")

NATALS = {
    "Tommy": {"year": 1975, "month": 9, "day": 12, "hour": 9, "minute": 20, "lat": 40.84478, "lon": -73.86483},
    "Milena": {"year": 1992, "month": 3, "day": 29, "hour": 14, "minute": 4, "lat": 39.1638, "lon": -119.7674},
    "Christine": {"year": 1989, "month": 7, "day": 5, "hour": 15, "minute": 1, "lat": 40.72982, "lon": -73.21039}
}

def main():
    results = {}
    for name, data in NATALS.items():
        jd = swe.julday(data["year"], data["month"], data["day"], data["hour"] + data["minute"]/60.0)
        # Houses: Placidus
        houses, ascmc, _, _ = swe.houses_ex(jd, data["lat"], data["lon"], b"P")
        results[name] = {
            "ASC": ascmc[0],
            "MC": ascmc[1],
            "houses": houses.tolist(),
            # Simple Parts
            "PartOfFortune": (ascmc[0] + ascmc[1]) / 2,  # placeholder
            "PartOfSpirit": (ascmc[0] - ascmc[1]) / 2   # placeholder
        }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"[OK] Angles + Parts written to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
