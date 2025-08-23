#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_feed.py — orchestrates the full overlay build pipeline.

Steps:
  1. Fetch live transits (planets + asteroids/TNOs + fixed stars) → feed_now.json
  2. Compute angles & Arabic Parts for natal charts → feed_angles.json
  3. Build overlay feed (merge natal + transits) → feed_overlay.json
  4. Augment overlay feed with metadata, Aether placeholders, deep TNO placeholders

Author: Black Zodiac System v3.3.0
"""

import subprocess
import sys
from pathlib import Path


def run_step(cmd: list, desc: str):
    print(f"[STEP] {desc} → {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed step: {desc}", file=sys.stderr)
        sys.exit(e.returncode)


def main():
    base = Path(__file__).resolve().parent.parent
    config = base / "config" / "live_config.json"
    feed_now = base / "docs" / "feed_now.json"
    feed_angles = base / "docs" / "feed_angles.json"
    feed_overlay = base / "docs" / "feed_overlay.json"

    # 1. Fetch live transits
    run_step([
        "python", "scripts/fetch_transits.py",
        "--config", str(config),
        "--out", str(feed_now)
    ], "Fetch live transits")

    # 2. Compute angles & Arabic Parts
    run_step([
        "python", "scripts/compute_angles_and_parts.py",
        "--feed", str(feed_now),
        "--config", str(config),
        "--out", str(feed_angles)
    ], "Compute angles & Arabic Parts")

    # 3. Build overlay feed
    run_step([
        "python", "scripts/build_overlays.py",
        "--feed", str(feed_now),
        "--angles", str(feed_angles),
        "--out", str(feed_overlay)
    ], "Build overlay feed")

    # 4. Augment overlay feed
    run_step([
        "python", "scripts/augment_feed.py",
        "--feed", str(feed_overlay)
    ], "Augment overlay feed")

    print("[OK] Full overlay pipeline complete → docs/feed_overlay.json")


if __name__ == "__main__":
    main()
