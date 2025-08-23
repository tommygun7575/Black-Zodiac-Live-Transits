#!/usr/bin/env python3
"""
convert_flat_astroseek.py
Converts the Astro-Seek daily asteroid/TNO flat export
(aug_2025_to_feb_2026_asteroids_tnos_flat.json)
into fallback_aug2025_2026.json for Black Zodiac overlay.

Pipeline:
- Load flat file (date-indexed with daily longitudes)
- Select today's date (or nearest available)
- Restructure into { "Body": {"lon": X, "lat": 0.0} }

Output: data/fallback_aug2025_2026.json
"""

import sys
import json
import datetime
from pathlib import Path

INPUT_FILE = Path("data/aug_2025_to_feb_2026_asteroids_tnos_flat.json")
OUTPUT_FILE = Path("data/fallback_aug2025_2026.json")

def load_flat_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def pick_closest_date(data, target_date):
    """Find row closest to today's UTC date in the Astro-Seek flat export."""
    available_dates = list(data.keys())
    available_dates.sort()
    # simple nearest date selection
    closest = min(available_dates, key=lambda d: abs(datetime.date.fromisoformat(d) - target_date))
    return closest

def convert(data, date_key):
    """Restructure selected day's positions into overlay fallback format."""
    row = data[date_key]
    fallback = {}
    for body, lon_str in row.items():
        try:
            lon_val = float(str(lon_str).replace("°","").replace("'","").strip())
        except:
            continue
        fallback[body] = {"lon": lon_val, "lat": 0.0}
    return fallback

def main():
    today = datetime.date.today()
    data = load_flat_file(INPUT_FILE)
    chosen_date = pick_closest_date(data, today)
    fallback = convert(data, chosen_date)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(fallback, f, indent=2)

    print(f"[OK] Built {len(fallback)} fallback bodies from {chosen_date} → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
