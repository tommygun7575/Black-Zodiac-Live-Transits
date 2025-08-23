#!/usr/bin/env python3
"""
fetch_transits.py
Wrapper for fetching positions from JPL or Swiss.
"""

import swisseph as swe
import datetime
from astroquery.jplhorizons import Horizons

def get_position(body, dt):
    """Try JPL then Swiss."""
    jd = swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute/60.0)

    try:
        obj = Horizons(id=body, location='500@399', epochs=dt.timestamp(), id_type='majorbody')
        eph = obj.elements()
        return float(eph['Q'][0]), 0.0, "jpl"
    except Exception:
        pass

    try:
        mapping = {
            "Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY,
            "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
            "Saturn": swe.SATURN, "Uranus": swe.URANUS,
            "Neptune": swe.NEPTUNE, "Pluto": swe.PLUTO
        }
        if body in mapping:
            lon, lat, _ = swe.calc_ut(jd, mapping[body])
            return lon, lat, "swiss"
    except Exception:
        pass

    return None, None, "missing"
