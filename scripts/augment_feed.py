#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
augment_feed.py — enrich overlay with Aether + deep TNO placeholders
"""

import argparse, json, sys
from pathlib import Path
from datetime import datetime

AETHER=["Vulcan","Persephone","Hades","Proserpina","Isis"]
DEEP=["Varuna","Ixion","Typhon","Salacia"]

def load(path): return json.loads(Path(path).read_text())

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--feed",required=True)
    args=ap.parse_args()
    path=Path(args.feed)
    overlay=load(path)

    overlay["meta"]["augmented_at_utc"]=datetime.utcnow().isoformat()+"Z"
    overlay["meta"]["black_zodiac_version"]="3.3.0"

    for name in AETHER:
        if not any(o.get("targetname")==name for o in overlay["objects"]):
            overlay["objects"].append({"id":name,"targetname":name,
                "source":"symbolic","note":"Aether placeholder"})

    for name in DEEP:
        if not any(o.get("targetname")==name for o in overlay["objects"]):
            overlay["objects"].append({"id":name,"targetname":name,
                "source":"deep-TNO-placeholder","error":"no data available"})

    path.write_text(json.dumps(overlay,indent=2))
    print(f"[OK] augmented {args.feed}")

if __name__=="__main__": main()
