#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compute_angles_and_parts.py — calculate ASC, MC, Houses, Fortune, Spirit
Normalized schema output for each natal chart
"""

import argparse, json, sys
from pathlib import Path
from datetime import datetime
from dateutil import parser as dtparse
import swisseph as swe

HOUSE_SYSTEM = b'P'

def julday(dt): 
    return swe.julday(dt.year, dt.month, dt.day,
                      dt.hour + dt.minute/60 + dt.second/3600.0)

def compute_angles(lat, lon, dt):
    jd = julday(dt)
    cusp, ascmc = swe.houses_ex(jd, lat, lon, HOUSE_SYSTEM)
    asc, mc = ascmc[0], ascmc[1]
    sun, _ = swe.calc_ut(jd, swe.SUN); moon, _ = swe.calc_ut(jd, swe.MOON)
    fortune = (asc + moon[0] - sun[0]) % 360
    spirit  = (asc + sun[0] - moon[0]) % 360
    return [
        {"id":"ASC","targetname":"Ascendant","ecl_lon_deg":asc,"ecl_lat_deg":0.0,"source":"swiss"},
        {"id":"MC","targetname":"Midheaven","ecl_lon_deg":mc,"ecl_lat_deg":0.0,"source":"swiss"},
        {"id":"Houses","targetname":"House Cusps","houses_deg":list(cusp),"source":"swiss"},
        {"id":"PartOfFortune","targetname":"Part of Fortune","ecl_lon_deg":fortune,"ecl_lat_deg":0.0,"source":"swiss"},
        {"id":"PartOfSpirit","targetname":"Part of Spirit","ecl_lon_deg":spirit,"ecl_lat_deg":0.0,"source":"swiss"}
    ]

def load(path): return json.loads(Path(path).read_text())

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--feed",required=True)
    ap.add_argument("--config",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()

    feed, cfg = load(args.feed), load(args.config)
    dt = dtparse.parse(feed["generated_at_utc"]) if "generated_at_utc" in feed else datetime.utcnow()
    results={"generated_at_utc":dt.isoformat()+"Z","angles":{}}

    for entry in cfg["natal_charts"]:
        results["angles"][entry["name"]] = compute_angles(float(entry["lat"]), float(entry["lon"]), dt)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(results, indent=2))
    print(f"[OK] wrote {args.out} with {len(results['angles'])} charts")

if __name__=="__main__": main()
