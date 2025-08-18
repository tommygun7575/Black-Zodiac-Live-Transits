#!/usr/bin/env python3
"""
augment_feed.py — add Swiss Angles (ASC, MC, IC, DSC) and Arabic Parts
to feed_now.json, merging into the existing structure.

Requires: pyswisseph, python-dateutil
"""

import json
import swisseph as swe
from datetime import datetime, timezone
from dateutil import parser

# Observer defaults (Spanish Springs / Reno approx.)
OBS_LAT = 39.653
OBS_LON = -119.706
OBS_ELEV = 1340

# Arabic Part formulas (deg arithmetic)
# Convention: Part = A + B - C
ARABIC_PARTS = {
    "Fortune":      ("Asc", "Moon", "Sun"),
    "Spirit":       ("Asc", "Sun", "Moon"),
    "Karma":        ("Saturn", "Asc", "Moon"),
    "Treachery":    ("Neptune", "Mercury", "Asc"),
    "Victory":      ("Jupiter", "Sun", "Asc"),
    "Marriage":     ("Desc", "Venus", "Sun"),
    "Vengeance":    ("Mars", "Moon", "Asc"),
    "Deliverance":  ("Pluto", "Asc", "Saturn"),
}

# Utility: normalize degrees 0–360
def norm(x: float) -> float:
    return x % 360.0

def compute_angles(jd_ut, lat, lon):
    """Compute ASC, MC, DSC, IC using Swiss Ephemeris house system (Placidus)."""
    # houses returns cusps[1..12], ascendant, mc, armc, vertex, equasc, coasc1, coasc2, polarasc
    houses, ascmc, _, _, _, _, _, _, _, _ = swe.houses_ex(
        jd_ut,
        lat,
        lon,
        b'P'  # Placidus
    )
    return {
        "Asc": norm(ascmc[0]),
        "MC": norm(ascmc[1]),
        "IC": norm(ascmc[1] + 180.0),
        "Desc": norm(ascmc[0] + 180.0),
    }

def main():
    # Load feed_now.json
    with open("docs/feed_now.json", "r") as f:
        feed = json.load(f)

    # Parse timestamp of first object (assumes all same epoch)
    if "objects" not in feed or not feed["objects"]:
        raise RuntimeError("feed_now.json missing objects")
    dt_str = feed["objects"][0]["datetime"]
    dt = parser.parse(dt_str).astimezone(timezone.utc)

    # Julian Day
    jd_ut = swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute/60.0, swe.GREG_CAL)

    # Angles
    angles = compute_angles(jd_ut, OBS_LAT, OBS_LON)

    # Index positions by name for easy lookup
    positions = {obj["targetname"]: obj for obj in feed["objects"]}

    # Arabic Parts
    parts = {}
    for name, (a, b, c) in ARABIC_PARTS.items():
        if a not in angles and a not in positions:
            continue
        if b not in angles and b not in positions:
            continue
        if c not in angles and c not in positions:
            continue

        def get_lon(key):
            if key in angles:
                return angles[key]
            elif key in positions:
                return positions[key]["ecl_lon"]
            else:
                raise KeyError(key)

        lon = norm(get_lon(a) + get_lon(b) - get_lon(c))
        parts[name] = lon

    # Merge into feed
    feed["angles"] = angles
    feed["arabic_parts"] = parts

    # Save
    with open("docs/feed_now.json", "w") as f:
        json.dump(feed, f, indent=2)

    print(f"Augmented docs/feed_now.json with {len(angles)} angles and {len(parts)} Arabic Parts.")

if __name__ == "__main__":
    main()
