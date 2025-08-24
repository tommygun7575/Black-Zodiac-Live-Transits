# scripts/sources/swiss_client.py
import os
import swisseph as swe
from dateutil import parser

# --- Set Swiss Ephemeris data path ---
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
EPHE_PATH = os.path.join(ROOT, "ephe")
swe.set_ephe_path(EPHE_PATH)

# Map names to Swiss constants / MPC IDs
PLANET_IDS = {
    # Majors
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
    "CERES": 1,
    "PALLAS": 2,
    "JUNO": 3,
    "VESTA": 4,

    # Additional asteroids
    "PSYCHE": 16,
    "EROS": 433,
    "AMOR": 1221,
    "ASTRAEA": 5,
    "SAPPHO": 80,
    "KARMA": 3811,
    "BACCHUS": 2063,
    "HYGIEA": 10,
    "NESSUS": 7066,

    # TNOs
    "ERIS": 136199,
    "SEDNA": 90377,
    "HAUMEA": 136108,
    "MAKEMAKE": 136472,
    "VARUNA": 20000,
    "IXION": 28978,
    "TYPHON": 42355,
    "SALACIA": 120347,
    "2002 AW197": 55565,
    "2003 VS2": 84922,
    "ORCUS": 90482,
    "QUAOAR": 50000,

    # Special point
    "LILITH": swe.MEAN_APOG
}

# Symbolic Aether planets
AETHER_IDS = {
    "VULCAN": 30,
    "PERSEPHONE": 31,
    "HADES": 32,
    "PROSERPINA": 33,
    "ISIS": 34
}

def get_ecliptic_lonlat(target: str, when_iso: str):
    """
    Return (lon, lat) for a body at given UTC ISO time.
    Uses Swiss Ephemeris for real bodies, deterministic pseudo-positions for Aethers.
    """
    try:
        dt = parser.isoparse(when_iso)
        jd = swe.julday(dt.year, dt.month, dt.day,
                        dt.hour + dt.minute/60.0 + dt.second/3600.0)
        upper = target.upper()

        # Real Swiss bodies
        if upper in PLANET_IDS:
            rc, xx = swe.calc_ut(jd, PLANET_IDS[upper])
            if rc < 0:
                return None
            lon, lat = xx[0], xx[1]
            return lon, lat

        # Symbolic Aethers
        if upper in AETHER_IDS:
            base = {
                "VULCAN": 0.9856,
                "PERSEPHONE": 0.083,
                "HADES": 0.014,
                "PROSERPINA": 0.004,
                "ISIS": 0.25
            }[upper]
            lon = (jd * base) % 360.0
            return lon, 0.0

        return None
    except Exception:
        return None
