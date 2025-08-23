#!/usr/bin/env python3
"""
augment_feed.py
Augments overlay feed with fallback datasets (SEAS, SE1, SEPL, fallback JSON).
"""

import json
from pathlib import Path

INPUT_FILE = Path("docs/feed_overlay.json")
OUTPUT_FILE = Path("docs/feed_overlay.json")

FALLBACK_FILES = [
    Path("data/seas18.json"),
    Path("data/se1.json"),
    Path("data/sepl.json"),
    Path("data/se_extra.json"),
    Path("data/fallback_aug2025_2026.json"),
]

def load_fallbacks():
    merged = {}
    for file in FALLBACK_FILES:
        if file.exists():
            with open(file, "r") as f:
                data = json.load(f)
            merged.update(data)
    return merged

def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"{INPUT_FILE} missing")

    with open(INPUT_FILE, "r") as f:
        feed = json.load(f)

    fallbacks = load_fallbacks()

    for obj in feed["objects"]:
        if obj["ecl_lon_deg"] is None:
            target = obj["id"]
            if target in fallbacks:
                obj["ecl_lon_deg"] = fallbacks[target].get("lon")
                obj["ecl_lat_deg"] = fallbacks[target].get("lat", 0.0)
                obj["source"] = f"fallback:{target}"

    with open(OUTPUT_FILE, "w") as f:
        json.dump(feed, f, indent=2)

    print("[OK] Overlay feed augmented with fallback datasets.")

if __name__ == "__main__":
    main()
