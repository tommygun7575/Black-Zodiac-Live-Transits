#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_transits.py — fetch planetary transits from JPL Horizons with Swiss Ephemeris fallback

- Uses live_config.json for planets, minor bodies, fixed stars
- Writes ecl_lon_deg / ecl_lat_deg so downstream scripts work
"""

import argparse, json, datetime, sys
from pathlib import Path
import numpy as np
from astroquery.jplhorizons import Horizons
import swisseph as swe

def julday(dt: datetime.datetime) -> float:
    return swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute/60.0)

def fetch_from_horizons(obj_id, epoch):
    try:
        h = Horizons(id=obj_id, location='500@399', epochs=epoch, id_type=None)
        eph = h.ephemerides(quantities="1")  # RA/Dec, lon/lat
        lon = float(eph["EclLon"][0])
        lat = float(eph["EclLat"][0])
        return lon, lat, "horizons"
    except Exception as e:
        print(f"[WARN] Horizons failed for {obj_id}: {e}", file=sys.stderr)
        return None, None, None

def fetch_from_swiss(obj_swe, jd):
    try:
        xx, _ = swe.calc_ut(jd, obj_swe)
        lon, lat = xx[0], xx[1]
        return lon, lat, "swiss"
    except Exception as e:
        print(f"[FATAL] Swiss failed for {obj_swe}: {e}", file=sys.stderr)
        return None, None, None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to live_config.json")
    ap.add_argument("--out", required=True, help="Output feed file (JSON)")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text())

    now = datetime.datetime.utcnow()
    jd = julday(now)
    epoch = now.strftime("%Y-%m-%d %H:%M")

    feed = {
        "generated_at_utc": now.isoformat() + "Z",
        "objects": [],
        "source": "JPL Horizons via astroquery + Swiss fallback"
    }

    # Planets
    for p in cfg.get("planets", []):
        name, obj_id = p["label"], p["id"]
        lon, lat, src = fetch_from_horizons(obj_id, epoch)
        if lon is None or np.isnan(lon):
            lon, lat, src = fetch_from_swiss(int(obj_id), jd)
        feed["objects"].append({
            "id": str(obj_id),
            "targetname": name,
            "ecl_lon_deg": lon,
            "ecl_lat_deg": lat,
            "source": src
        })

    # Minor bodies
    for obj_id in cfg.get("minor_bodies", []):
        lon, lat, src = fetch_from_horizons(obj_id, epoch)
        if lon is None:
            # Swiss can’t resolve most asteroids by ID
            continue
        feed["objects"].append({
            "id": str(obj_id),
            "targetname": f"MinorBody {obj_id}",
            "ecl_lon_deg": lon,
            "ecl_lat_deg": lat,
            "source": src
        })

    # Fixed stars (from config, RA/Dec)
    for star in cfg.get("fixed_stars", []):
        feed["objects"].append({
            "id": star["id"],
            "targetname": star["label"],
            "ra_deg": star["ra_deg"],
            "dec_deg": star["dec_deg"]_]()_
