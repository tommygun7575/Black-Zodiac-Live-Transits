import os
from typing import Tuple, Optional
import swisseph as swe   # ✅ top-level import
from datetime import datetime

EPHE_PATH = os.environ.get("SE_EPHE_PATH", os.path.join(os.getcwd(), "ephe"))

SWISS_IDS = {
    "Sun": 0, "Moon": 1, "Mercury": 2, "Venus": 3, "Mars": 4,
    "Jupiter": 5, "Saturn": 6, "Uranus": 7, "Neptune": 8,
    "Pluto": 9, "Chiron": 15
}

def get_ecliptic_lonlat(name: str, when_iso: str) -> Optional[Tuple[float, float]]:
    """
    Get ecliptic longitude/latitude using Swiss Ephemeris.
    """
    try:
        swe.set_ephe_path(EPHE_PATH)
        body = SWISS_IDS.get(name)
        if body is None:
            return None
        jd_ut = swe.julday(*_iso_to_ymdhms(when_iso))
        pos, _ = swe.calc_ut(jd_ut, body, swe.FLG_SWIEPH | swe.FLG_SPEED)
        return (float(pos[0]) % 360.0, float(pos[1]))
    except Exception:
        return None

def _iso_to_ymdhms(when_iso: str):
    dt = datetime.fromisoformat(when_iso.replace("Z", "+00:00"))
    return dt.year, dt.month, dt.day, dt.hour + dt.minute / 60.0 + dt.second / 3600.0
