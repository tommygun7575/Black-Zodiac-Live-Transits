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
}

# Symbolic Aether planets (not real Swiss bodies)
AETHER_IDS = {
    "VULCAN": 30,       # fictitious ID for Vulcan
    "PERSEPHONE": 31,   # fictitious ID for Persephone
    "HADES": 32,        # fictitious ID for Hades
    "PROSERPINA": 33,   # fictitious ID for Proserpina
    "ISIS": 34          # fictitious ID for Isis
}

def get_ecliptic_lonlat(target: str, when_iso: str):
    """
    Return (lon, lat) in ecliptic degrees for a body at given UTC ISO time.
    Uses Swiss Ephemeris for real bodies, symbolic placeholders for Aethers.
    """
    try:
        dt = parser.isoparse(when_iso)
        jd = swe.julday(dt.year, dt.month, dt.day,
                        dt.hour + dt.minute/60.0 + dt.second/3600.0)

        upper = target.upper()

        # Real Swiss bodies
        if upper in PLANET_IDS:
            lon, lat, dist, lon_speed = swe.calc_ut(jd, PLANET_IDS[upper])
            return lon, lat

        # Symbolic Aethers → placeholder formula
        if upper in AETHER_IDS:
            # Simple deterministic pseudo-position:
            # cycle them around the zodiac at different speeds
            base = {
                "VULCAN": 0.9856,     # ~1°/day (like Sun)
                "PERSEPHONE": 0.083,  # ~30°/year (like Saturn)
                "HADES": 0.014,       # ~1°/70 days
                "PROSERPINA": 0.004,  # ~1°/250 days
                "ISIS": 0.25          # ~90°/year
            }[upper]
            # Fake longitude based on JD * rate, wrap 360
            lon = (jd * base) % 360.0
            return lon, 0.0

        # Unsupported body
        return None

    except Exception:
        return None
