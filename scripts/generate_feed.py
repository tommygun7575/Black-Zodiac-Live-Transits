#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_feed.py — orchestrates the overlay build
"""

import subprocess, sys
from pathlib import Path

def run_step(cmd,desc):
    print(f"[STEP] {desc}")
    try: subprocess.run(cmd,check=True)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] {desc}",file=sys.stderr); sys.exit(e.returncode)

def main():
    base=Path(__file__).resolve().parent.parent
    cfg=base/"config"/"live_config.json"
    now=base/"docs"/"feed_now.json"
    ang=base/"docs"/"feed_angles.json"
    ovl=base/"docs"/"feed_overlay.json"

    run_step(["python","scripts/fetch_transits.py","--config",str(cfg),"--out",str(now)],"Fetch transits")
    run_step(["python","scripts/compute_angles_and_parts.py","--feed",str(now),"--config",str(cfg),"--out",str(ang)],"Compute angles")
    run_step(["python","scripts/build_overlays.py","--feed",str(now),"--angles",str(ang),"--out",str(ovl)],"Build overlay")
    run_step(["python","scripts/augment_feed.py","--feed",str(ovl)],"Augment overlay")

    print("[OK] Full overlay pipeline complete")

if __name__=="__main__": main()
