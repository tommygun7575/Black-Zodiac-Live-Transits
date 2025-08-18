#!/usr/bin/env python3
"""
augment_feed.py — add Swiss Angles, Arabic Parts, and extra asteroids/stars
"""

import argparse, json, swisseph as swe, datetime
from pathlib import Path

def compute_angles(jd, lat, lon):
    houses, ascmc = swe.houses_ex(jd, lat, lon, b'A')
    return {
        "ASC": ascmc[0],
        "MC": ascmc[1],
        "Vertex": ascmc[3]
    }

def compute_arabic_parts(angles, planets):
    try:
        asc = angles["ASC"]
        sun = planets["Sun"]["lon"]
        moon = planets["Moon"]["lon"]
        fortune = (asc + moon - sun) % 360
        spirit = (asc + sun - moon) % 360
        return {"Fortune": fortune, "Spirit": spirit}
    except Exception:
        return {}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", required=True)
    parser.add_argument("--asteroids", required=True)
    args = parser.parse_args()

    with open(args.feed) as f:
        feed = json.load(f)
    with open(args.asteroids) as f:
        asteroid_cfg = json.load(f)

    now = datetime.datetime.utcnow()
    jd = swe.julday(now.year, now.month, now.day, now.hour + now.minute/60.0)

    planets = {obj["name"]: obj for obj in feed["objects"]}
    angles = compute_angles(jd, 39.5, -119.8)  # Default Reno NV coords
    parts = compute_arabic_parts(angles, planets)

    feed["angles"] = angles
    feed["arabic_parts"] = parts
    feed["asteroids"] = asteroid_cfg

    Path(args.feed).write_text(json.dumps(feed, indent=2))
    print(f"[OK] augmented {args.feed}")

if __name__ == "__main__":
    main()
