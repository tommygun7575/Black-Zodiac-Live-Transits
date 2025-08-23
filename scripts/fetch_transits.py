#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_transits.py — Build the live transit feed (planets + asteroids/TNOs).

- Reads planets, barycenters, asteroids, minor bodies, and fixed stars from config/live_config.json
- Tries JPL Horizons first (planets/barycenters/minor bodies)
- Falls back to Swiss Ephemeris for major planets and known asteroids/TNOs
- If Swiss fails, fills in from aug_2025_to_feb_2026_asteroids_tnos_flat.json
- Writes docs/feed_now.json
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
from astroquery.jplhorizons import Horizons
import swisseph as swe

# ---- Config
FALLBACK_PATH = "aug_2025_to_feb_2026_asteroids_tnos_flat.json"
LOCATION = "500@399"  # geocentric Earth

# ---- Asteroids & TNOs to enrich
ASTEROIDS_TNOS = {
    "Vesta": 4, "Psyche": 16, "Amor": 1221, "Eros": 433,
    "Sappho": 80, "Karma": 3811,
    "Chariklo": 10199, "Pholus": 5145,
    "Eris": 136199, "Sedna": 90377,
    "Haumea": 136108, "Makemake": 136472,
    "Varuna": 20000, "Ixion": 28978, "Typhon": 42355, "Salacia": 120347
}

# ---- Utilities
def jd_ut(dt: datetime) -> float:
    return swe.julday(
        dt.year, dt.month, dt.day,
        dt.hour + dt.minute / 60 + dt.second / 3600.0
    )

def horizons_lonlat(obj_id: str, epoch_str: str):
    """Query JPL Horizons for ecliptic longitude/latitude."""
    try:
        h = Horizons(id=obj_id, id_type=None, location=LOCATION, epochs=epoch_str)
        eph = h.ephemerides(quantities="1")
        lon = float(eph["EclLon"][0]); lat = float(eph["EclLat"][0])
        return lon, lat, "horizons"
    except Exception as e:
        print(f"[WARN] Horizons failed for {obj_id}: {e}", file=sys.stderr)
        return None, None, None

_SWE_MAJOR = {
    "10": swe.SUN, "301": swe.MOON, "199": swe.MERCURY,
    "299": swe.VENUS, "499": swe.MARS, "599": swe.JUPITER,
    "699": swe.SATURN, "799": swe.URANUS, "899": swe.NEPTUNE,
    "999": swe.PLUTO,
}

def swiss_lonlat(eid: str, jd: float):
    """Swiss fallback for majors + asteroids/TNOs."""
    try:
        if eid == "2060":  # Chiron
            body = getattr(swe, "CHIRON", None)
        else:
            body = _SWE_MAJOR.get(eid) or int(eid)
        if body is None:
            return None, None, None
        xx, _ = swe.calc_ut(jd, body)
        return float(xx[0]), float(xx[1]), "swiss"
    except Exception as e:
        print(f"[WARN] Swiss failed for {eid}: {e}", file=sys.stderr)
        return None, None, None

def load_fallback():
    try:
        fb = json.loads(Path(FALLBACK_PATH).read_text(encoding="utf-8"))
        return {row["date"]: row for row in fb["data"]}
    except Exception as e:
        print(f"[WARN] Could not load fallback JSON: {e}", file=sys.stderr)
        return {}

# ---- Main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to config/live_config.json")
    ap.add_argument("--out", required=True, help="Path to write docs/feed_now.json")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))

    now = datetime.utcnow()
    epoch_str = now.strftime("%Y-%m-%d %H:%M")
    jd = jd_ut(now)
    date_key = now.strftime("%Y-%m-%d")

    feed = {
        "generated_at_utc": now.isoformat() + "Z",
        "observer": "geocentric Earth",
        "source": "JPL Horizons (fallback: Swiss + JSON)",
        "objects": []
    }

    fallback_lookup = load_fallback()

    # ---------- Planets (with Swiss fallback)
    for p in cfg.get("planets", []):
        eid = str(p["id"]); label = p.get("label", eid)
        lon, lat, src = horizons_lonlat(eid, epoch_str)
        if lon is None or (isinstance(lon, float) and np.isnan(lon)):
            lon, lat, src = swiss_lonlat(eid, jd)
        feed["objects"].append({
            "id": eid, "targetname": label,
            "ecl_lon_deg": lon, "ecl_lat_deg": lat,
            "source": src or "unknown"
        })

    # ---------- Barycenters
    for b in cfg.get("barycenters", []):
        if not b.get("enabled", True): continue
        eid = str(b["id"]); label = b.get("label", f"Barycenter {eid}")
        lon, lat, src = horizons_lonlat(eid, epoch_str)
        if lon is None: continue
        feed["objects"].append({
            "id": eid, "targetname": label,
            "ecl_lon_deg": lon, "ecl_lat_deg": lat, "source": src
        })

    # ---------- Minor bodies (Horizons only)
    for mb in cfg.get("minor_bodies", []):
        eid = str(mb)
        lon, lat, src = horizons_lo_
