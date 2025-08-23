#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compute_angles_and_parts.py — calculate angles, houses, and Arabic Parts
for each natal chart defined in config/live_config.json, based on the
current live feed (docs/feed_now.json).

Inputs:
  --feed docs/feed_now.json
  --config config/live_config.json
  --out docs/feed_angles.json

Outputs:
  JSON containing ASC, MC, Houses, Part of Fortune, Part of Spirit
  for each natal chart.
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from dateutil import parser as dtparse
import swisseph as swe

HOUSE_SYSTEM = b'P'  # Placidus default


# ---- Helpers ----

def julday(dt: datetime) -> float:
    return swe.julday(
        dt.year, dt.month, dt.day,
        dt.hour + dt.minute/60.0 + dt.second/3600.0,
        swe.GREG_CAL
    )


def compute_angles(lat: float, lon: float, dt: datetime):
    """Compute ASC, MC, Houses, Part of Fortune, Part of Spirit for given coords/time."""
    jd = julday(dt)
    cusp, ascmc = swe.houses_ex(jd, lat, lon, HOUSE_SYSTEM)

    asc = ascmc[0]
    mc = ascmc[1]

    # Sun & Moon positions
    sun, _ = swe.calc_ut(jd, swe.SUN)
    moon, _ = swe.calc_ut(jd, swe.MOON)

    fortune = (asc + moon[0] - sun[0]) % 360
    spirit = (asc + sun[0] - moon[0]) % 360

    return {
        "ASC": asc,
        "MC": mc,
        "houses": cusp,
        "PartOfFortune": fortune,
        "PartOfSpirit": spirit
    }


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERROR] Failed to load {path}: {e}", file=sys.stderr)
        sys.exit(1)


# ---- Main ----

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", required=True, help="Path to feed_now.json")
    ap.add_argument("--config", required=True, help="Path to live_config.json")
    ap.add_argument("--out", required=True, help="Path to output feed_angles.json")
    args = ap.parse_args()

    feed = load_json(Path(args.feed))
    cfg = load_json(Path(args.config))

    # Use the feed's timestamp as reference time
    gen_str = feed.get("generated_at_utc")
    if not gen_str:
        print("[WARN] feed missing generated_at_utc, using now()", file=sys.stderr)
        dt = datetime.utcnow()
    else:
        dt = dtparse.parse(gen_str)

    results = {"generated_at_utc": dt.isoformat(), "angles": {}}

    for entry in cfg.get("natal_charts", []):
        name = entry.get("name")
        lat = entry.get("lat")
        lon = entry.get("lon")

        if name is None or lat is None or lon is None:
            print(f"[WARN] Skipping malformed entry: {entry}", file=sys.stderr)
            continue

        angles = compute_angles(float(lat), float(lon), dt)
        results["angles"][name] = angles

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"[OK] wrote {args.out} with {len(results['angles'])} natal charts")


if __name__ == "__main__":
    main()
