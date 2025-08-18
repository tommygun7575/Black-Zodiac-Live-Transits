#!/usr/bin/env python3
"""
build_overlays.py — generate feed_overlay.json
Merges docs/feed_now.json with stored natal charts for Tommy, Milena, Christine.
"""

import json
from pathlib import Path

NATALS = {
    "Tommy": "config/natal/Tommy_NatalChart_HybridOSv3.2.json",
    "Milena": "config/natal/Milena_NatalChart_HybridOSv3.2.json",
    "Christine": "config/natal/Christine_NatalChart_HybridOSv3.2.json",
}

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

def main():
    # Load current sky
    with open("docs/feed_now.json", "r") as f:
        feed = json.load(f)

    overlays = {
        "generated_at": feed["generated_at_utc"],
        "source": "feed_now.json + natal charts",
        "overlays": {}
    }

    # Build overlays per natal
    for name, path in NATALS.items():
        if not Path(path).exists():
            print(f"[WARN] Missing natal file for {name}: {path}")
            continue

        natal = load_json(path)
        overlays["overlays"][name] = {
            "natal": natal,
            "transits": feed
        }

    with open("docs/feed_overlay.json", "w") as f:
        json.dump(overlays, f, indent=2)

    print("Wrote docs/feed_overlay.json")

if __name__ == "__main__":
    main()
