#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_transits.py — Build the live transit feed (planets + asteroids/TNOs + stars).

- JPL Horizons (preferred) + Swiss fallback
- Augmented with fallback JSON for asteroids/TNOs
- Normalized schema across feeds
- Fixes: Chiron always resolved, fallback strings converted to floats
"""

import argparse, json, sys, re
from pathlib import Path
from datetime import datetime
from astroquery.jplhorizons import Horizons
import swisseph as swe

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
    "999": swe.PLUTO,
    "2060": swe.CHIRON  # force Chiron resolution
}

def jd_ut(dt): 
    return swe.julday(dt.year, dt.month, dt.day,
                      dt.hour + dt.minute/60 + dt.second/3600.0)

def horizons_lonlat(eid, epoch):
    try:
        h = Horizons(id=eid, location=LOCATION, epochs=epoch)
        eph = h.ephemerides(quantities="1")
        lon = float(eph["EclLon"][0]); lat = float(eph["EclLat"][0])
        return lon, lat, "horizons"
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

def parse_fallback_value(val):
    """Convert fallback JSON values (e.g. '15° 36') into floats (decimal degrees)."""
    if val is None: 
        return None
    if isinstance(val, (int, float)): 
        return float(val)
    if isinstance(val, str):
        match = re.match(r"(\d+)[°:\s](\d+)", val)
        if match:
            deg, mins = map(float, match.groups())
            return deg + mins/60.0
        try:
            return float(val)
        except: 
            return None
    return None

def load_fallback():
    try:
        fb = json.loads(Path(FALLBACK_PATH).read_text())
        return {row["date"]: row for row in fb["data"]}
    except Exception:
        return {}

def normalize_obj(obj):
    return {
        "id": obj.get("id",""),
        "targetname": obj.get("targetname",""),
        "ecl_lon_deg": obj.get("ecl_lon_deg"),
        "ecl_lat_deg": obj.get("ecl_lat_deg", 0.0),
        "source": obj.get("source","unknown")
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    now = datetime.utcnow()
    epoch = now.strftime("%Y-%m-%d %H:%M")
    jd = jd_ut(now)
    date_key = now.strftime("%Y-%m-%d")

    feed = {
        "generated_at_utc": now.isoformat()+"Z",
        "observer": "geocentric Earth",
        "source": "JPL Horizons + Swiss + fallback JSON",
        "objects": []
    }

    fallback = load_fallback()

    # Planets + Chiron
    for p in cfg["planets"]:
        eid, label = str(p["id"]), p["label"]
        lon, lat,
