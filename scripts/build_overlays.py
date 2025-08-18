#!/usr/bin/env python3
"""
build_overlays.py — merge natal charts (from live_config.json) with current feed into overlay file
"""

import argparse, json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", required=True, help="Path to feed_now.json")
    parser.add_argument("--config", default="config/live_config.json", help="Path to live_config.json")
    parser.add_argument("--out", required=True, help="Path to output feed_overlay.json")
    args = parser.parse_args()

    # Load feed + config
    feed = json.loads(Path(args.feed).read_text())
    config = json.loads(Path(args.config).read_text())

    # Load natal charts explicitly listed in config
    natal_data = {}
    for entry in config.get("natal_charts", []):
        name = entry["name"]
        file_path = Path(entry["file"])
        if not file_path.exists():
            print(f"[WARN] Natal file missing: {file_path}")
            continue
        natal_data[name] = json.loads(file_path.read_text())

    # Build overlay structure
    overlay = {
        "feed": feed,
        "natal": natal_data,
        "meta": {
            "generated_by": "build_overlays.py",
            "config_version": config.get("meta", {}).get("version", "unknown")
        }
    }

    Path(args.out).write_text(json.dumps(overlay, indent=2))
    print(f"[OK] overlay written to {args.out}")

if __name__ == "__main__":
    main()
