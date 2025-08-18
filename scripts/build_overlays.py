#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_overlays.py — merge the current feed with natal charts

Backwards compatible:
- Preferred:  --config config/live_config.json   (uses "natal_charts": [{name,file},...])
- Legacy:     --natal_dir config/natal           (loads all *.json in the directory)

Writes a single overlay JSON combining:
  { "feed": <feed_now.json>, "natal": {<name>: <natal_json>, ...}, "meta": {...} }
"""

import argparse, json
from pathlib import Path
import sys

def load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERROR] Failed reading {p}: {e}", file=sys.stderr)
        raise

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", required=True, help="Path to docs/feed_now.json")
    ap.add_argument("--config", required=False, help="Path to live_config.json (preferred)")
    ap.add_argument("--natal_dir", required=False, help="Directory containing *.json natal charts (legacy)")
    ap.add_argument("--out", required=True, help="Output overlay JSON path")
    args = ap.parse_args()

    if not args.config and not args.natal_dir:
        print("[ERROR] Need --config (preferred) or --natal_dir (legacy).", file=sys.stderr)
        sys.exit(2)

    feed_path = Path(args.feed)
    out_path  = Path(args.out)

    feed = load_json(feed_path)

    natal = {}
    if args.config:
        cfg_path = Path(args.config)
        cfg = load_json(cfg_path)
        charts = cfg.get("natal_charts", [])
        if not charts:
            print(f"[WARN] No 'natal_charts' in {cfg_path}", file=sys.stderr)
        for entry in charts:
            name = entry.get("name")
            file = entry.get("file")
            if not name or not file:
                print(f"[WARN] Skipping malformed natal entry: {entry}", file=sys.stderr)
                continue
            fpath = Path(file)
            if not fpath.exists():
                print(f"[WARN] Missing natal file: {fpath}", file=sys.stderr)
                continue
            try:
                natal[name] = load_json(fpath)
            except Exception:
                print(f"[WARN] Could not load natal file: {fpath}", file=sys.stderr)
    else:
        ndir = Path(args.natal_dir)
        if not ndir.exists():
            print(f"[ERROR] natal_dir not found: {ndir}", file=sys.stderr)
            sys.exit(2)
        for f in ndir.glob("*.json"):
            try:
                natal[f.stem] = load_json(f)
            except Exception:
                print(f"[WARN] Could not load natal file: {f}", file=sys.stderr)

    overlay = {
        "feed": feed,
        "natal": natal,
        "meta": {
            "natal_count": len(natal),
            "source": "config" if args.config else "natal_dir"
        }
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(overlay, indent=2), encoding="utf-8")
    print(f"[OK] overlay written -> {out_path} (natal: {len(natal)})")

if __name__ == "__main__":
    main()
