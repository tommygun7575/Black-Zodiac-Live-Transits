#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_transits.py — Build the live transit feed (planets + asteroids/TNOs + stars).

- JPL Horizons (preferred) + Swiss fallback
- Augmented with fallback JSON for asteroids/TNOs
- Normalized schema across feeds:
  id, targetname, ecl_lon_deg, ecl_lat_deg, source
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from astroquery.jplhorizons import Horizons
import swisseph as swe
import numpy as np

FALLBACK_PATH = "aug_2025_to_feb_2026_asteroids_tnos_flat.json"
LOCATION = "500@399"  # geocentric Earth

ASTEROIDS_TNOS = {
    "Vesta": 4, "Psyche": 16, "Amor": 1221, "Eros": 433,
    "Sappho": 80, "Karma": 3811,
    "Chariklo": 10199, "Pholus": 5145,
    "Eris": 136199, "Sedna": 90377,
    "Haumea": 136108, "Makemake": 136472,
    "Varuna": 20000, "Ixion": 28978, "Typhon": 42355, "Salacia": 120347
}

_SWE_MAJOR = {
    "10": swe.SUN, "301": swe.MOON, "199": swe.MERCURY,
    "299": swe.VENUS, "499": swe.MARS, "599": swe.JUPITER,
    "699": swe.SATURN, "799": swe.URANUS, "899": swe.NEPTUNE,
    "999": swe.PLUTO, "2060": getattr(swe, "CHIRON", 15),
}

def jd_ut(dt): 
    return swe.julday(dt.year, dt.month, dt.day,
                      dt.hour + dt.minute/60 + dt.second/3600.0)

def horizons_lonlat(eid, epoch):
    try:
        h = Horizons(id=eid, location=LOCATION, epochs=epoch)
        eph = h.ephemerides(quantities="1")
        return float(eph["EclLon"][0]), float(eph["EclLat"][0]), "horizons"
    except Exception:
        return None, None, None

def swiss_lonlat(eid, jd):
    try:
        body = _SWE_MAJOR.get(eid, None)
        if body is None:
            body = int(eid)
        xx, _ = swe.calc_ut(jd, body)
        return float(xx[0]), float(xx[1]), "swiss"
    except Exception:
        return None, None, None

def load_fallback():
    try:
        fb = json.loads(Path(FALLBACK_PATH).read_text())
        return {row["date"]: row for row in fb["data"]}
    except Exception:
        return {}

def normalize_obj(obj):
    base = {"id": obj.get("id", ""), "targetname": obj.get("targetname", "")}
    if "ecl_lon_deg" in obj: base["ecl_lon_deg"] = obj["ecl_lon_deg"]
    if "ecl_lat_deg" in obj: base["ecl_lat_deg"] = obj.get("ecl_lat_deg", 0.0)
    base["source"] = obj.get("source", "unknown")
    return base

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    now = datetime.utcnow()
    epoch_str = now.strftime("%Y-%m-%d %H:%M")
    jd = jd_ut(now)
    date_key = now.strftime("%Y-%m-%d")

    feed = {
        "generated_at_utc": now.isoformat() + "Z",
        "observer": "geocentric Earth",
        "source": "JPL Horizons + Swiss + fallback JSON",
        "objects": []
    }

    fallback = load_fallback()

    # Planets
    for p in cfg["planets"]:
        eid = str(p["id"]); label = p["label"]
        lon, lat, src = horizons_lonlat(eid, epoch_str)
        if lon is None: lon, lat, src = swiss_lonlat(eid, jd)
        feed["objects"].append(normalize_obj({
            "id": eid, "targetname": label,
            "ecl_lon_deg": lon, "ecl_lat_deg": lat, "source": src
        }))

    # Asteroids / TNOs
    for name, num in ASTEROIDS_TNOS.items():
        lon, lat, src = swiss_lonlat(str(num), jd)
        if lon is not None:
            feed["objects"].append(normalize_obj({
                "id": str(num), "targetname": name,
                "ecl_lon_deg": lon, "ecl_lat_deg": lat, "source": src
            }))
        elif date_key in fallback and name in fallback[date_key]:
            feed["objects"].append(normalize_obj({
                "id": name, "targetname": name,
                "ecl_lon_deg": fallback[date_key][name],
                "ecl_lat_deg": 0.0,
                "source": "fallback-json"
            }))
        else:
            feed["objects"].append(normalize_obj({
                "id": name, "targetname": name,
                "source": "missing"
            }))

    # Fixed Stars
    for star in cfg["fixed_stars"]:
        feed["objects"].append(normalize_obj({
            "id": star["id"], "targetname": star["label"],
            "ecl_lon_deg": star["ra_deg"], "ecl_lat_deg": star["dec_deg"],
            "source": "fixed"
        }))

    Path(args.out).parent.mkdir(exist_ok=True)
    Path(args.out).write_text(json.dumps(feed, indent=2))
    print(f"[OK] wrote {args.out} with {len(feed['objects'])} objects")

if __name__ == "__main__":
    main()
`
