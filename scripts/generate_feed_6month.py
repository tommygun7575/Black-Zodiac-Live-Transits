#!/usr/bin/env python3
import json
import datetime
from astroquery.jplhorizons import Horizons
import swisseph as swe
import pytz
import os

# Force Swiss to use repo ephemeris folder
swe.set_ephe_path(os.path.join(os.getcwd(), "ephe"))

# Hardcoded start epoch: Aug 24, 2025 @ 18:00 UTC
START_EPOCH = datetime.datetime(2025, 8, 24, 18, 0, 0, tzinfo=datetime.timezone.utc)
DAYS = 180

# Object ID mapping (same as overlay)
OBJECTS = {
    "Sun": {"jpl": "10", "swiss": swe.SUN},
    "Moon": {"jpl": "301", "swiss": swe.MOON},
    "Mercury": {"jpl": "199", "swiss": swe.MERCURY},
    "Venus": {"jpl": "299", "swiss": swe.VENUS},
    "Mars": {"jpl": "499", "swiss": swe.MARS},
    "Jupiter": {"jpl": "599", "swiss": swe.JUPITER},
    "Saturn": {"jpl": "699", "swiss": swe.SATURN},
    "Uranus": {"jpl": "799", "swiss": swe.URANUS},
    "Neptune": {"jpl": "899", "swiss": swe.NEPTUNE},
    "Pluto": {"jpl": "999", "swiss": swe.PLUTO},
    "Chiron": {"jpl": "2060", "swiss": swe.CHIRON},
    "Ceres": {"jpl": "1", "swiss": swe.CERES},
    "Pallas": {"jpl": "2", "swiss": swe.PALLAS},
    "Juno": {"jpl": "3", "swiss": swe.JUNO},
    "Vesta": {"jpl": "4", "swiss": swe.VESTA},
    "Haumea": {"jpl": "136108"},
    "Makemake": {"jpl": "136472"},
    "Varuna": {"jpl": "20000"},
    "Ixion": {"jpl": "28978"},
    "Typhon": {"jpl": "42355"},
    "Salacia": {"jpl": "120347"},
}

def get_from_horizons(jd, objid):
    """Try Horizons first"""
    try:
        obj = Horizons(id=objid, location="500@399", epochs=jd)
        eph = obj.ephemerides()
        if "EclLon" not in eph.columns or "EclLat" not in eph.columns:
            raise RuntimeError("Horizons returned malformed ephemeris")
        lon = float(eph["EclLon"][0])
        lat = float(eph["EclLat"][0])
        if not (0.0 <= lon < 360.0):
            raise ValueError(f"Bad longitude for {objid}: {lon}")
        return lon, lat, "jpl"
    except Exception:
        return None

def get_from_swiss(jd, body):
    """Swiss fallback"""
    try:
        lon, lat, dist, _ = swe.calc_ut(jd, body)
        return lon % 360.0, lat, "swiss"
    except Exception:
        return None

def get_from_miriade(objid, jd):
    """Miriade fallback placeholder (not implemented)"""
    return None

def main():
    charts = {}
    for day in range(DAYS):
        dt = START_EPOCH + datetime.timedelta(days=day)
        jd = swe.julday(dt.year, dt.month, dt.day, 
                        dt.hour + dt.minute/60.0, swe.GREG_CAL)
        charts[str(dt.date())] = {}

        for name, ids in OBJECTS.items():
            res = None
            # Try Horizons first
            if "jpl" in ids:
                res = get_from_horizons(jd, ids["jpl"])
            # Then Swiss fallback
            if res is None and "swiss" in ids:
                res = get_from_swiss(jd, ids["swiss"])
            # Then Miriade (stub)
            if res is None:
                res = get_from_miriade(ids["jpl"], jd)
            if res:
                lon, lat, source = res
                charts[str(dt.date())][name] = {
                    "lon": lon,
                    "lat": lat,
                    "source": source,
                }

        # TODO: add fixed stars, houses, Arabic Parts, harmonics
        # Same functions as in overlay.py

    out = {
        "meta": {
            "start_epoch_utc": START_EPOCH.isoformat(),
            "days": DAYS,
            "source_order": [
                "jpl (majors/asteroids/tnos)",
                "swiss (fallback)",
                "miriade (fallback)",
                "fixed (stars)",
                "houses (cusps, ASC, MC)",
                "calculated (arabic parts)",
                "calculated (harmonics)",
                "calculated-fallback"
            ],
        },
        "charts": charts,
    }

    with open("docs/feed_6month.json", "w") as f:
        json.dump(out, f, indent=2)

if __name__ == "__main__":
    main()
