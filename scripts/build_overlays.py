#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_overlays.py — merge feed + angles into overlay
"""

import argparse, json, sys
from pathlib import Path

def load(path): return json.loads(Path(path).read_text())

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--feed",required=True)
    ap.add_argument("--angles",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    feed, angles=load(args.feed),load(args.angles)
    overlay={"meta":{"generated_at_utc":feed["generated_at_utc"],
                     "observer":feed.get("observer","geocentric Earth"),
                     "source":"overlay-builder"},
             "objects":feed.get("objects",[]),"angles":angles.get("angles",{})}

    Path(args.out).write_text(json.dumps(overlay,indent=2))
    print(f"[OK] wrote {args.out}")

if __name__=="__main__": main()
