#!/usr/bin/env python3
"""
build_overlays.py — merge natal charts with current feed into overlay file
"""

import argparse, json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", required=True)
    parser.add_argument("--natal_dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.feed) as f:
        feed = json.load(f)

    natal_data = {}
    for natal_file in Path(args.natal_dir).glob("*.json"):
        with open(natal_file) as nf:
            natal_data[natal_file.stem] = json.load(nf)

    overlay = {
        "feed": feed,
        "natal": natal_data
    }

    Path(args.out).write_text(json.dumps(overlay, indent=2))
    print(f"[OK] overlay written to {args.out}")

if __name__ == "__main__":
    main()
