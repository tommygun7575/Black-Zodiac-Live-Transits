#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_feed_60day.py — build a 60-day projected transit feed.
Does not interfere with generate_feed.py (live feed).
Writes docs/feed_60day.json for use by GPT Store app.
"""

import json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import swisseph as swe

# ---- Settings ----
DAYS_AHEAD = 60
HOUSE_SYSTEM = b'P'  # Placidus
OBSERVER = "geocentric Earth"

# Tell Swiss Ephemeris where the ephemeris data files are (downloaded in workflow)
swe.set_ephe_path("ephe")

# Example fixed stars (add more in config if needed)
FIXED_STARS = [
    {"id": "Regulus", "label": "Regulus (Alpha Leo)", "ra_deg": 152.0929625, "dec_deg": 11.9672083},
    {"id": "Spica",   "label": "Spica (Alpha Vir)",   "ra_deg": 201.2982475, "dec_deg": -11.1613194},
    {"id": "Sirius",  "label": "Sirius (Alpha CMa)",  "ra_deg": 101.2871553, "dec_deg": -16.7161159},
    {"id": "Aldebaran","label":"Aldebaran (Alpha Tau)","ra_deg": 68.9801625,"dec_deg": 16.5093028},
]

# ---- Helpers ----

def swe_calc(body, dt):
    """Swiss Ephemeris wrapper for planets."""
    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute/60 + dt.second/3600.0, swe.GREG_CAL)
    xx, _ = swe.calc_ut(jd, body)
    return float(xx[0]), float(xx[1])  # lon, lat

def houses_and_points(lat, lon, dt):
    """Compute ASC, MC, houses, Parts of Fortune/Spirit."""
    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute/60 + dt.second/3600.0, swe.GREG_CAL)
    ascmc, cusp, _ = swe.houses_ex(jd, lat, lon, HOUSE_SYSTEM)

    asc = ascmc[0]
    mc = ascmc[1]

    # Simplified: Fortune/Spirit using day formula
    sun_lon, _ = swe_calc(swe.SUN, dt)
    moon_lon, _ = swe_calc(swe.MOON, dt)
    fortune = (asc + moon_lon - sun_lon) % 360
    spirit = (asc + sun_lon - moon_lon) % 360

    return {
        "ASC": asc,
        "MC": mc,
        "houses": cusp,
        "PartOfFortune": fortune,
        "PartOfSpirit": spirit
    }

def add_fixed_star(star, dt):
    return {
        "targetname": star["label"],
        "id": star["id"],
        "datetime_utc": dt.isoformat(),
        "ra_deg": star["ra_deg"],
        "dec_deg": star["dec_deg"],
        "epoch": "J2000",
        "source": "fixed"
    }

# ---- Main ----

def main():
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    feed = {
        "feed": {
            "generated_at_utc": datetime.utcnow().isoformat(),
            "observer": OBSERVER,
            "range_days": DAYS_AHEAD,
            "object
