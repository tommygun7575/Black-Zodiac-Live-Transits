#!/usr/bin/env python3
"""
convert_flat_astroseek.py
Handles Astro-Seek flat export (aug_2025_to_feb_2026_asteroids_tnos_flat.json).
Converts it into fallback_aug2025_2026.json for overlay builder.
"""

import sys
import json
import datetime
from pathlib import Path

OUTPUT_FILE = Path("data/fallback_aug2025_2026.json")

def load_flat_file(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def pick_date_key(data: dict, target_date: datetime.date) -> str:
    """
    Try to pick today's date if present, otherwise first valid date-like key.
    """
    # If keys are ISO dates
    date_keys = []
    for k in data.keys():
        try:
            _ = datetime.date.fromisoformat(k)
            date_keys.append(k)
        except Exception:
            continue

    if date_keys:
        # Choose closest
        closest = min(
            date_keys,
            key=lambda d: abs(datetime.date.fromisoformat(d) - target_date)
        )
        return closest

    # If no ISO-format dates, fallback to first key
    return list(data.keys())[0]

def convert_row(row: dict) -> dict:
    fallback = {}
    for body, lon_str in row.items():
        try:
            clean = str(lon_str).replace("°", "").replace("'", "").strip()
            lon_val = float(clean)
            fallback[body] = {"lon": lon_val, "lat": 0.0}
        except Exception:
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

    chosen_key = pick_date_key(data, today)
    print(f"[INFO] Using key: {chosen_key}")

    row = data[chosen_key] if isinstance(data[chosen_key], dict) else data
    fallback = convert_row(row)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(fallback, f, indent=2)

    print(f"[OK] Converted {len(fallback)} objects → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
