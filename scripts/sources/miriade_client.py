import json
import requests
from typing import Tuple, Optional
from scripts.utils.coords import ra_dec_to_ecl   # ✅ import at the top

MIRIADE_BASE = "https://ssp.imcce.fr/webservices/miriade/api/ephemcc.php"
PREFIX_MAP = {
    "Sun":"p:","Mercury":"p:","Venus":"p:","Earth":"p:","Moon":"s:",
    "Mars":"p:","Jupiter":"p:","Saturn":"p:","Uranus":"p:","Neptune":"p:",
    "Pluto":"dp:","Chiron":"a:","Ceres":"dp:","Pallas":"a:","Juno":"a:","Vesta":"a:"
}

def _qualify(name: str) -> str:
    return f"{PREFIX_MAP.get(name,'a:')}{name}"

def get_ecliptic_lonlat(name: str, when_iso: str) -> Optional[Tuple[float, float]]:
    """
    Query Miriade ephemeris service for ecliptic lon/lat.
    Falls back to RA/DEC -> ecliptic if lon/lat missing.
    """
    params = {
        "-name": _qualify(name),
        "-ep": when_iso,
        "-observer": "500",
        "-theory": "DE431",
        "-teph": "2",  # apparent, equinox of date (1 = astrometric J2000)
        "-tcoor": "1",
        "-rplane": "2",
        "-nbd": "1",
        "-mime": "json"
    }
    try:
        r = requests.get(MIRIADE_BASE, params=params, timeout=30)
        data = r.json()
        if isinstance(data, dict) and "data" not in data:
            data = data.get("result", {})
        if isinstance(data, str):
            data = json.loads(data)

        rows = data.get("data", [])
        if not rows:
            return None

        row = {k.lower(): v for k, v in rows[0].items()}
        from scripts.utils.frames import miriade_row_lon_lat
        elon, elat = miriade_row_lon_lat(row)

        if elon is None or elat is None:
            return None

        return (float(elon) % 360.0, float(elat))

    except Exception:
        return None
