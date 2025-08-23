#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
augment_feed.py — enrich feed_overlay.json with Black Zodiac overlays.

- Reads feed_overlay.json (planets + asteroids/TNOs + natal overlays)
- Injects system metadata for Master Config
- Ensures objects have consistent IDs and sources
- Adds placeholder slots for deep TNOs / Aether Planets (config-driven)
- Writes docs/feed_overlay.json (augmented in-place)

Author: Black Zodiac System v3.3.0
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime


# ---- Config
AETHER_PLANETS = ["Vulcan", "Persephone", "Hades", "Proserpina", "Isis"]
DEEP_TNOS = ["Varuna", "Ixion", "Typhon", "Salacia"]


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERROR] Failed to load {path}: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", required=True, help="Path to feed_overlay.json")
    args = ap.parse_args()

    path = Path(args.feed)
    overlay = load_json(path)

    # ---- Augment metadata
    overlay["meta"]["augmented_at_utc"] = datetime.utcnow().isoformat() + "Z"
    overlay["meta"]["black_zodiac_version"] = "3.3.0"
    overlay["meta"]["includes"] = [
        "Planets", "Asteroids", "TNOs", "Angles", "Arabic Parts",
        "Fixed Stars", "Aether Planets (symbolic placeholders)"
    ]

    # ---- Ensure placeholders for Aether planets
    for name in AETHER_PLANETS:
        exists = any(obj.get("targetname") == name for obj in overlay.get("objects", []))
        if not exists:
            overlay["objects"].append({
                "id": name,
                "targetname": name,
                "note": "Symbolic Aether Planet (not ephemeris-tracked)",
                "source": "symbolic"
            })

    # ---- Ensure placeholders for deep TNOs if missing
    for name in DEEP_TNOS:
        exists = any(obj.get("targetname") == name for obj in overlay.get("objects", []))
        if not exists:
            overlay["objects"].append({
                "id": name,
                "targetname": name,
                "error": "no data available",
                "source": "deep-TNO-placeholder"
            })

    # ---- Normalize IDs
    for obj in overlay.get("objects", []):
        if "id" not in obj:
            obj["id"] = obj.get("targetname", "unknown")

    # ---- Write back augmented overlay
    path.write_text(json.dumps(overlay, indent=2), encoding="utf-8")
    print(f"[OK] Augmented {args.feed} with {len(AETHER_PLANETS)} aether placeholders and {len(DEEP_TNOS)} deep TNO placeholders")


if __name__ == "__main__":
    main()
