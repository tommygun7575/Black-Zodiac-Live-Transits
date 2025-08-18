#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_feed.py — build live feed from JPL Horizons (fallback: Swiss Ephemeris).
Uses config/live_config.json to decide which planets, minor bodies, and stars to include.
Writes docs/feed_now.json.
"""

import json, sys
from datetime import datetime, timezone
from pathlib import Path
from astroquery.jplhorizons import Horizons
import swisseph as swe

CONFIG_PATH = "config/live_config.json"
LOCATION = "500@399"  # geocentric Earth


# ---------- Helpers

def fetch_horizons(eph_id, dt):
    """Try JPL Horizons for body id"""
    try:
        obj = Horizons(
            id=eph_id,
            id_type=None,
            location=LOCATION,
            epochs=dt.strftime("%Y-%m-%d %H:%M")
        )
        eph = obj.ephemerides()[0]
        return {
            "targetname": str(eph_id),
            "id": str(eph_id),
            "datetime_utc": eph["datetime_str"],
            "ecl_lon_deg": float(eph["EclLon"]),
            "ecl_lat_deg": float(eph["EclLat"]),
            "source": "horizons"
        }
    except Exception as e:
        print(f"[WARN] Horizons failed for {eph_id}: {e}", file=sys.stderr)
        return None


def fetch_swiss(name, eph_id, dt):
    """Fallback to Swiss Ephemeris for major bodies"""
    swe_map = {
        "10": swe.SUN, "301": swe.MOON, "199": swe.MERCURY,
        "299": swe.VENUS, "499": swe.MARS, "599": swe.JUPITER,
        "699": swe.SATURN, "799": swe.URANUS, "899": swe.NEPTUNE,
        "999": swe.PLUTO
    }

    if str(eph_id) in swe_map:
        body_id = swe_map[str(eph_id)]
    elif str(eph_id) == "2060":  # Chiron
        body_id = getattr(swe, "CHIRON", 15)  # fallback asteroid id
    else:
        # unknown minor bodies not in Swiss fallback
        return None

    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute/60 + dt.second/3600.0, swe.GREG_CAL)
    xx, _ = swe.calc_ut(jd, body_id)
    lon, lat = xx[0], xx[1]
    return {
        "targetname": name,
        "id": str(eph_id),
        "datetime_utc": dt.isoformat(),
        "ecl_lon_deg": float(lon),
        "ecl_lat_deg": float(lat),
        "source": "swiss"
    }


def add_fixed_star(entry, dt):
    """Fixed stars come from RA/Dec in config only."""
    return {
        "targetname": entry["label"],
        "id": entry["id"],
        "datetime_utc": dt.isoformat(),
        "ra_deg": entry["ra_deg"],
        "dec_deg": entry["dec_deg"],
        "epoch": entry.get("epoch", "J2000"),
        "source": "fixed"
    }


# ---------- Main

def main():
    with open(CONFIG_PATH, "r") as f_
