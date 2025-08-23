#!/usr/bin/env python3
"""
convert_flat_astroseek.py
Converts an Astro-Seek asteroid/TNO flat export file
(aug_2025_to_feb_2026_asteroids_tnos_flat.json at repo root)
into fallback_aug2025_2026.json for Black Zodiac overlay.

Pipeline:
- Load flat Astro-Seek file (date-indexed with daily longitudes)
- Pick the row closest to today's UTC date
- Convert into { "Body": {"lon": X, "lat": 0.0} } format

Usage:
python scripts/convert_flat_astroseek.py aug_2025_to_feb_2026_asteroids_tnos_flat.json
"""

import sys
import json
import datetime
from pathlib import Path

OUTPUT_FILE = Path("data/fallback_aug2025_2026.json")

def load_flat_file(path: Path):
    """Load the Astro-Seek flat JSON file (date-indexed)."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def pick_closest_date(data: dict, target_date: datetime.date) -> str:
    """Find the row closest to today's date."""
    available_dates = list(data.keys())
    available_dates.sort()
    closest = min(
        available_dates,
        key=lambda d: abs(datetime.date.fromisoformat(d) - target_date)
    )
    return closest

def convert_row(row: dict) -> dict:
    """Convert a single day's row into fallback overlay format."""
    fallback = {}
    for body, lon_str in row.items():
        try:
            # Remove degree symbols if present and parse as float
            clean = str(lon_str).replace("°", "").replace("'", "").strip()
            lon_val = float(clean)
            fallback[body] = {"lon": lon_val, "lat": 0.0}
        except Exception:
            # Skip any body we can't parse
            continue
    return fallback

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/convert_flat_astroseek.py <astroseek_flat_file>")
        sys.exit(1)

    input_file = Path(sys.argv[1])
    if not input_file.exists():
        print(f"❌ Input file not found: {input_file}")
        sys.exit(1)

    today = datetime.date.today()
    data = load_flat_file(input_file)
    chosen_date = pick_closest_date(data, today)
    row = data[chosen_date]

    fallback = convert_row(row)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(fallback, f, indent=2)

    print(f"[OK] Converted {len(fallback)} objects from {chosen_date} → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
