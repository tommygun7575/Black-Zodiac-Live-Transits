import swisseph as swe
from dateutil import parser
import os

# --- Set Swiss Ephemeris data path ---
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
swe.set_ephe_path(os.path.join(ROOT, "ephe"))

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
}

def get_ecliptic_lonlat(target: str, when_iso: str):
    try:
        tid = SWISS_IDS.get(target.upper())
        if tid is None:
            print(f"[SWISS] Unknown target: {target}")
            return None

        dt = parser.isoparse(when_iso)
        jd = swe.julday(dt.year, dt.month, dt.day,
                        dt.hour + dt.minute/60.0 + dt.second/3600.0)

        lon, lat, dist = swe.calc_ut(jd, tid)
        print(f"[SWISS] {target.upper()} @ {when_iso} → lon={lon:.6f}, lat={lat:.6f}, dist={dist:.6f}")
        return (lon % 360.0, lat)

    except Exception as e:
        print(f"[SWISS] Error for {target}: {e}")
        return None
