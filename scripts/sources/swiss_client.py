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
    "LILITH": swe.MEAN_APOG  # mean Black Moon
}

# Symbolic Aether planets (not real Swiss bodies)
AETHER_IDS = {
    "VULCAN": 30,
    "PERSEPHONE": 31,
    "HADES": 32,
    "PROSERPINA": 33,
    "ISIS": 34
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

        # Real Swiss bodies / asteroids / TNOs
        if upper in PLANET_IDS:
            lon, lat, dist = swe.calc_ut(jd, PLANET_IDS[upper])[0:3]
            return lon, lat

        # Symbolic Aethers → deterministic pseudo-positions
        if upper in AETHER_IDS:
            base = {
                "VULCAN": 0.9856,     # ~1°/day
                "PERSEPHONE": 0.083,  # ~30°/year
                "HADES": 0.014,       # ~1°/70 days
                "PROSERPINA": 0.004,  # ~1°/250 days
                "ISIS": 0.25          # ~90°/year
            }[upper]
            lon = (jd * base) % 360.0
            return lon, 0.0

        # Unsupported body
        return None

    except Exception:
        return None
