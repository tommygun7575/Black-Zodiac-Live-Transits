#!/usr/bin/env python3
"""
augment_feed.py — add Swiss Angles (ASC, MC, IC, DSC) and Arabic Parts
to feed_now.json, with Swiss Ephemeris fallback for missing values.
"""

import json
import swisseph as swe
from datetime import datetime, timezone
from dateutil import parser

# Observer defaults (Spanish Springs / Reno approx.)
OBS_LAT = 39.653
OBS_LON = -119.706
OBS_ELEV = 1340

# Map target names to Swiss Ephemeris IDs
SWE_MAP = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,
    "Mars": swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN,
    "Uranus": swe.URANUS,
    "Neptune": swe.NEPTUNE,
    "Pluto": swe.PLUTO,
    "Chiron": swe.CHIRON,
}

# Arabic Part formulas (deg arithmetic) — A + B - C
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

def norm(x: float) -> float:
    return x % 360.0

def swiss_position(body, jd_ut):
    """Compute geocentric ecliptic lon/lat from Swiss Ephemeris."""
    if body not in SWE_MAP:
        return None
    lon, lat, dist = swe.calc_ut(jd_ut, SWE_MAP[body])[0:3]
    return {"ecl_lon": float(lon), "ecl_lat": float(lat)}

def compute_angles(jd_ut, lat, lon):
    """Compute Asc, MC, Desc, IC via Placidus houses."""
    houses, ascmc, *_ = swe.houses_ex(jd_ut, lat, lon, b'P')
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

    if "objects" not in feed or not feed["objects"]:
        raise RuntimeError("feed_now.json missing objects")

    # Parse epoch
    dt_str = feed["objects"][0]["datetime"]
    dt = parser.parse(dt_str).astimezone(timezone.utc)
    jd_ut = swe.julday(dt.year, dt.month, dt.day,
                       dt.hour + dt.minute/60.0 + dt.second/3600.0,
                       swe.GREG_CAL)

    # Angles
    angles = compute_angles(jd_ut, OBS_LAT, OBS_LON)

    # Build position index with fallback
    positions = {}
    for obj in feed["objects"]:
        name = obj["targetname"]
        lon = obj.get("ecl_lon")
        lat = obj.get("ecl_lat")

        if lon is None:  # fallback to Swiss Ephemeris
            print(f"[INFO] Filling missing {name} with Swiss Ephemeris")
            swiss = swiss_position(name, jd_ut)
            if swiss:
                lon, lat = swiss["ecl_lon"], swiss["ecl_lat"]

        if lon is not None:
            positions[name] = {"ecl_lon": lon, "ecl_lat": lat}

    # Arabic Parts
    parts = {}
    for pname, (a, b, c) in ARABIC_PARTS.items():
        def get_lon(key):
            if key in angles:
                return angles[key]
            if key in positions:
                return positions[key]["ecl_lon"]
            raise KeyError(key)

        try:
            lon = norm(get_lon(a) + get_lon(b) - get_lon(c))
            parts[pname] = lon
        except KeyError as e:
            print(f"[WARN] Missing key for {pname}: {e}")

    # Merge into feed
    feed["angles"] = angles
    feed["arabic_parts"] = parts

    with open("docs/feed_now.json", "w") as f:
        json.dump(feed, f, indent=2)

    print(f"Augmented feed with {len(angles)} angles and {len(parts)} Arabic Parts.")

if __name__ == "__main__":
    main()
