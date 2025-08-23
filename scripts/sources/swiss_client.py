import os
import swisseph as swe
from dateutil import parser

# --- Set Swiss Ephemeris data path ---
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
EPHE_PATH = os.path.join(ROOT, "ephe")
swe.set_ephe_path(EPHE_PATH)

# Map names to Swiss constants
PLANET_IDS = {
    "SUN": swe.SUN,
    "MOON": swe.MOON,
    "MERCURY": swe.MERCURY,
    "VENUS": swe.VENUS,
    "MARS": swe.MARS,
    "JUPITER": swe.JUPITER,
    "SATURN": swe.SATURN,
    "URANUS": swe.URANUS,
    "NEPTUNE": swe.NEPTUNE,
    "PLUTO": swe.PLUTO,
    "CHIRON": swe.CHIRON,
    # Classical asteroids
    "CERES": swe.CERES,
    "PALLAS": swe.PALLAS,
    "JUNO": swe.JUNO,
    "VESTA": swe.VESTA,
    # You can extend with TNOs / fictitious bodies if you have elements
}

def get_ecliptic_lonlat(target: str, when_iso: str):
    """
    Return (lon, lat) in ecliptic degrees for a body at given UTC ISO time.
    """
    try:
        dt = parser.isoparse(when_iso)
        jd = swe.julday(dt.year, dt.month, dt.day,
                        dt.hour + dt.minute/60.0 + dt.second/3600.0)

        body = PLANET_IDS.get(target.upper())
        if body is None:
            # Unsupported body → Swiss can’t calculate
            return None

        lon, lat, dist, lon_speed = swe.calc_ut(jd, body)
        return lon, lat
    except Exception:
        return None
