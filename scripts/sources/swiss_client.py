import swisseph as swe
from dateutil import parser
import os

# --- Set Swiss Ephemeris data path ---
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
swe.set_ephe_path(os.path.join(ROOT, "ephe"))

# Mapping for planets, Sun, Moon etc.
SWISS_IDS = {
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
    # add more asteroids here if you want them Swiss-based
}

def get_ecliptic_lonlat(target: str, when_iso: str):
    """
    Compute ecliptic longitude/latitude using Swiss Ephemeris.
    Reads data from ephe/*.se1 files.
    """
    try:
        tid = SWISS_IDS.get(target.upper())
        if tid is None:
            print(f"[SWISS] Unknown target: {target}")
            return None

        # Convert ISO time → Julian Day
        dt = parser.isoparse(when_iso)
        jd = swe.julday(dt.year, dt.month, dt.day,
                        dt.hour + dt.minute/60.0 + dt.second/3600.0)

        # Calculate position
        lon, lat, dist = swe.calc_ut(jd, tid)
        print(f"[SWISS] {target} @ {when_iso} → lon={lon:.6f}, lat={lat:.6f}")
        return (lon % 360.0, lat)

    except Exception as e:
        print(f"[SWISS] Error for {target}: {e}")
        return None
