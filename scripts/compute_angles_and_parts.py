#!/usr/bin/env python3
"""
compute_angles_and_parts.py
Computes ASC, MC, Houses, all 10 Angles (ascmc array),
and basic Arabic Parts (Fortune & Spirit).
"""

import swisseph as swe
import json
from pathlib import Path

OUTPUT_FILE = Path("docs/feed_angles.json")

# Natal data
NATALS = {
    "Tommy": {"year": 1975, "month": 9, "day": 12, "hour": 9, "minute": 20, "lat": 40.84478, "lon": -73.86483},
    "Milena": {"year": 1992, "month": 3, "day": 29, "hour": 14, "minute": 4, "lat": 39.1638, "lon": -119.7674},
    "Christine": {"year": 1989, "month": 7, "day": 5, "hour": 15, "minute": 1, "lat": 40.72982, "lon": -73.21039}
}

def safe_houses_ex(jd, lat, lon, hsys=b"P"):
    """
    Wraps swe.houses_ex to handle both 2-value and 4-value returns.
    Returns (houses, ascmc).
    """
    result = swe.houses_ex(jd, lat, lon, hsys)
    if isinstance(result, tuple):
        if len(result) == 2:
            houses, ascmc = result
        elif len(result) == 4:
            houses, ascmc, _, _ = result
        else:
            raise ValueError(f"Unexpected houses_ex return length: {len(result)}")
        return houses, ascmc
    raise ValueError("houses
