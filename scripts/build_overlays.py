#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_overlays.py — merge transits and natal overlays into one feed.

Inputs:
  --feed docs/feed_now.json
  --angles docs/feed_angles.json
  --out docs/feed_overlay.json

- Combines live planetary/asteroid/TNO data from feed_now.json
- Adds angles and parts for each natal chart from feed_angles.json
- Preserves natal chart metadata from config/live_config.json
- Outputs a single feed_overlay.json for Master Config

Author: Black Zodiac System v3.3.0
"""

import argparse
import json
import sys
from pathlib import Path


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERROR] Failed to load {path}: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", required=True, help="Path to feed_now.json")
    ap.add_argument("--angles", required=True, help="Path to feed_angles.json")
    ap.add_argument("--out", required=True, help="Path to write feed_overlay.json")
    args = ap.parse_args()

    feed_now = load_json(Path(args.feed))
    feed_angles = load_json(Path(args.angles))

    overlay = {
        "meta": {
            "generated_at_utc": feed_now.get("generated_at_utc"),
            "observer": feed_now.get("observer", "geocentric Earth"),
            "source": "overlay-builder",
        },
        "objects": feed_now.get("objects", []),
        "angles": feed_angles.get("angles", {}),
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(overlay, indent=2), encoding="utf-8")
    print(f"[OK] wrote {args.out} with {len(overlay['objects'])} objects and {len(overlay['angles'])} natal overlays")


if __name__ == "__main__":
    main()
