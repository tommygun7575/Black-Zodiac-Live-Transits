#!/usr/bin/env python3
"""
augment_feed.py — add Swiss Angles, Arabic Parts, Asteroids, Fixed Stars
to docs/feed_now.json (which already contains major bodies).
"""

import json
import swisseph as swe
from datetime import datetime, timezone
from dateutil import parser

OBS_LAT = 39.653
OBS_LON = -119.706

SWE_MAP = {
    "Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY,
    "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN, "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE,
    "Pluto": swe.PLUTO, "Chiron": swe.CHIRON,
}

ARABIC_PARTS = {
    "Fortune": ("Asc", "Moon", "Sun"),
    "Spirit": ("Asc", "Sun", "Moon"),
    "Karma": ("Saturn", "Asc", "Moon"),
    "Treachery": ("Neptune", "Mercury", "Asc"),
    "Victory": ("Jupiter", "Sun", "Asc"),
    "Marriage": ("Desc", "Venus", "Sun"),
    "Vengeance": ("Mars", "Moon", "Asc"),
    "Deliverance": ("Pluto", "Asc", "Saturn"),
}

def norm(x): return x % 360

def swiss_pos(body, jd):
    if body not in SWE_MAP: return None
    lon, lat, _ = swe.calc_ut(jd, SWE_MAP[body])[0:3]
    return lon, lat

def compute_angles(jd, lat, lon):
    houses, ascmc, *_ = swe.houses_ex(jd, lat, lon, b'P')
    return {
        "Asc": norm(ascmc[0]), "MC": norm(ascmc[1]),
        "IC": norm(ascmc[1] + 180), "Desc": norm(ascmc[0] + 180)
    }

def main():
    with open("docs/feed_now.json", "r") as f:
        feed = json.load(f)

    dt = parser.parse(feed["objects"][0]["datetime"]).astimezone(timezone.utc)
    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute/60 + dt.second/3600.0, swe.GREG_CAL)

    # Angles
    angles = compute_angles(jd, OBS_LAT, OBS_LON)

    # Arabic Parts
    pos = {o["targetname"]: o for o in feed["objects"]}
    parts = {}
    for name, (a, b, c) in ARABIC_PARTS.items():
        try:
            la = angles[a] if a in angles else pos[a]["ecl_lon"]
            lb = angles[b] if b in angles else pos[b]["ecl_lon"]
            lc = angles[c] if c in angles else pos[c]["ecl_lon"]
            parts[name] = norm(la + lb - lc)
        except Exception as e:
            print(f"[WARN] Skipped {name}: {e}")

    # Load asteroids/fixed stars
    try:
        with open("config/asteroids_master.json") as f:
            asteroids = json.load(f)
    except FileNotFoundError:
        asteroids = {}

    feed["angles"] = angles
    feed["arabic_parts"] = parts
    feed["asteroids"] = asteroids.get("asteroids", [])
    feed["fixed_stars"] = asteroids.get("fixed_stars", [])

    with open("docs/feed_now.json", "w") as f:
        json.dump(feed, f, indent=2)

if __name__ == "__main__":
    main()
