#!/usr/bin/env python3
"""
compute_angles_and_parts.py
Computes angles (ASC, MC, Houses) and basic Arabic Parts
for core natal charts (Tommy, Milena, Christine).

Output: docs/feed_angles.json
"""

import swisseph as swe
import json
from pathlib import Path

OUTPUT_FILE = Path("docs/feed_angles.json")

# Natal data
NATALS = {
    "Tommy": {
        "year": 1975, "month": 9, "day": 12,
        "hour": 9, "minute": 20,
        "lat": 40.84478, "lon": -73.86483
    },
    "Milena": {
        "year": 1992, "month": 3, "day": 29,
        "hour": 14, "minute": 4,
        "lat": 39.1638, "lon": -119.7674
    },
    "Christine": {
        "year": 1989, "month": 7, "day": 5,
        "hour": 15, "minute": 1,
        "lat": 40.72982, "lon": -73.21039
    }
}

def main():
    results = {}

    for name, d in NATALS.items():
        # Julian Day
        jd = swe.julday(
            d["year"], d["month"], d["day"],
            d["hour"] + d["minute"] / 60.0
        )

        # Houses + Angles (Placidus system)
        houses, ascmc, _, _ = swe.houses_ex(jd, d["lat"], d["lon"], b"P")

        # Store ASC, MC, house cusps
        results[name] = {
            "ASC": ascmc[0],
            "MC": ascmc[1],
            "houses": houses.tolist()
        }

        # Basic Arabic Parts
        # These can be expanded later with full formulas
        results[name]["PartOfFortune"] = (ascmc[0] + ascmc[1]) / 2
        results[name]["PartOfSpirit"] = (ascmc[0] - ascmc[1]) / 2

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"[OK] Angles + Parts written to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
