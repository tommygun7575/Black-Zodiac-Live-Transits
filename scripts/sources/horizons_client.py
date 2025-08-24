from typing import Tuple, Optional
from astroquery.jplhorizons import Horizons
from dateutil import parser
import swisseph as swe
from scripts.utils.coords import ra_dec_to_ecl

# Mapping of names to Horizons IDs
# Planets use NASA NAIF IDs (10 = Sun, 301 = Moon, etc.)
# Asteroids use MPC numbers, with semicolon (;) to force Horizons asteroid context.
HORIZONS_IDS = {
    # Major bodies
    "SUN": "10",
    "MOON": "301",
    "MERCURY": "199",
    "VENUS": "299",
    "EARTH": "399",
    "MARS": "499",
    "JUPITER": "599",
    "SATURN": "699",
    "URANUS": "799",
    "NEPTUNE": "899",
    "PLUTO": "999",

    # Centaurs / minor bodies
    "CHIRON": "2060",
    "NESSUS": "7066",

    # Main asteroids
    "CERES": "1;",
    "PALLAS": "2;",
    "JUNO": "3;",
    "VESTA": "4;",
    "PSYCHE": "16;",
    "EROS": "433;",
    "AMOR": "1221;",
    "ASTRAEA": "5;",
    "SAPPHO": "80;",
    "KARMA": "3811;",
    "BACCHUS": "2063;",
    "HYGIEA": "10;",   # ✅ asteroid #10 (semicolon distinguishes it from Sun)

    # TNOs / dwarf planets
    "ERIS": "136199",
    "SEDNA": "90377",
    "HAUMEA": "136108",
    "MAKEMAKE": "136472",
    "VARUNA": "20000",
    "IXION": "28978",
    "ORCUS": "90482",
    "QUAOAR": "50000",
    "SALACIA": "120347",
    "TYPHON": "42355",
    "2002 AW197": "55565",
    "2003 VS2": "84922"
}

def get_ecliptic_lonlat(target: str, when_iso: str) -> Optional[Tuple[float, float]]:
    """
    Query JPL Horizons for ecliptic longitude/latitude of a target.
    Handles both numeric IDs and asteroid semicolon syntax.
    """
    try:
        tid = HORIZONS_IDS.get(target.upper(), target)

        # Parse ISO datetime → Julian Day
        dt = parser.isoparse(when_iso)
        jd = swe.julday(dt.year, dt.month, dt.day,
                        dt.hour + dt.minute/60.0 + dt.second/3600.0)

        obj = Horizons(id=tid, location="500@399", epochs=[jd])
        eph = obj.ephemerides()

        ecl_lon, ecl_lat = None, None

        # Try different possible column names for lon/lat
        for lon_key in ("EclLon", "EclipticLon", "ELON"):
            if lon_key in eph.colnames:
                ecl_lon = float(eph[lon_key][0])
                break
        for lat_key in ("EclLat", "EclipticLat", "ELAT"):
            if lat_key in eph.colnames:
                ecl_lat = float(eph[lat_key][0])
                break

        # If Horizons gave RA/DEC instead, convert
        if (ecl_lon is None or ecl_lat is None) and {"RA", "DEC"}.issubset(eph.colnames):
            ecl_lon, ecl_lat = ra_dec_to_ecl(float(eph["RA"][0]), float(eph["DEC"][0]), when_iso)

        if ecl_lon is None or ecl_lat is None:
            return None

        return (ecl_lon % 360.0, ecl_lat)

    except Exception as e:
        print(f"[Horizons] error for {target} at {when_iso}: {e}")
        return None
