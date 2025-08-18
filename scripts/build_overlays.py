#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_overlays.py — merge natal charts listed in live_config.json with the current feed
"""

import argparse, json
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", required=True)
    ap.add_argument("--config", required=True)   # live_config.json
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    feed = json.loads(Path(args.feed).read_text(encoding="utf-8"))
    cfg  = json.loads(Path(args.config).read_text(encoding="utf-8"))

    natal = {}
    for entry in cfg.get("natal_charts", []):
        name = entry["name"]; file = Path(entry["file"])
        if file.exists():
            natal[name] = json.loads(file.read_text(encoding="utf-8"))
        else:
            print(f"[WARN] Missing natal file: {file}")

    overlay = {"feed": feed, "natal": natal,
               "meta": {"config_version": cfg.get("meta",{}).get("version","unknown")}}
    Path(args.out).write_text(json.dumps(overlay, indent=2), encoding="utf-8")
    print(f"[OK] overlay written -> {args.out}")

if __name__ == "__main__":
    main()
