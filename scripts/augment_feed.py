#!/usr/bin/env python3
"""
augment_feed.py — enrich feed_now.json with Swiss Angles, Arabic Parts, and asteroids/fixed stars.
"""

import argparse, json, swisseph as swe, datetime
from pathlib import Path

def compute_angles(jd, lat, lon, house_system="P"):
    """Compute ASC, MC, Vertex using Swiss Ephemeris houses."""
    houses, ascmc = swe.houses_ex(jd, lat, lon, bytes(house_system, 'utf-8'))
    return {
        "ASC": ascmc[0],
        "MC": ascmc[1],
        "Vertex": ascmc[3]
    }

def compute_part(formula, context):
    """Evaluate an Arabic Part formula like 'ASC + Moon - Sun'."""
    try:
        expr = formula
        for k, v in context.items():
            expr = expr.replace(k, str(v))
        return eval(expr) % 360
    except Exception:
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", required=True, help="Path to feed_now.json")
    parser.add_argument("--asteroids", required=True, help="Path to asteroids_master.json")
    parser.add_argument("--config", default="config/live_config.json", help="Path to live_config.json")
    args = parser.parse_args()

    # Load files
    feed = json.loads(Path(args.feed).read_text())
    asteroid_cfg = json.loads(Path(args.asteroids).read_text())
    config = json.loads(Path(args.config).read_text())

    now = datetime.datetime.utcnow()
    jd = swe.julday(now.year, now.month, now.day, now.hour + now.minute/60.0)

    planets = {obj["name"]: obj for obj in feed["objects"]}

    # Angles + Arabic Parts per target
    feed["angles"] = {}
    feed["arabic_parts"] = {}

    for target in config.get("targets", []):
        name = target["name"]
        lat, lon = target["lat"], target["lon"]
        house_system = target.get("house_system", "P")

        # Angles
        angles = compute_angles(jd, lat, lon, house_system)
        feed["angles"][name] = angles

        # Parts
        parts_cfg = config.get("arabic_parts", {}).get("parts", [])
        context = {"ASC": angles["ASC"]}
        context.update({p: planets[p]["lon"] for p in planets if p in ["Sun","Moon"]})
        parts = {}
        for part in parts_cfg:
            day_formula = part.get("formula_day")
            value = compute_part(day_formula, context)
            if value is not None:
                parts[part["id"]] = value
        feed["arabic_parts"][name] = parts

    # Add asteroid catalog
    feed["asteroids"] = asteroid_cfg

    Path(args.feed).write_text(json.dumps(feed, indent=2))
    print(f"[OK] augmented {args.feed}")

if __name__ == "__main__":
    main()
