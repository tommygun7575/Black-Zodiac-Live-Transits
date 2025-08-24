from typing import Tuple, Optional
from astroquery.jplhorizons import Horizons
from dateutil import parser
import swisseph as swe
from scripts.utils.coords import ra_dec_to_ecl

# Mapping of names to JPL Horizons target IDs
HORIZONS_IDS = {
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
    "CHIRON": "2060",
    "CERES": "1", "PALLAS": "2", "JUNO": "3", "VESTA": "4",
    "PSYCHE": "16", "EROS": "433", "AMOR": "1221", "ASTRAEA": "5",
    "SAPPHO": "80", "KARMA": "3811", "BACCHUS": "2063",
    "HYGIEA": "10", "NESSUS": "7066",
    "ERIS": "136199", "SEDNA": "90377", "HAUMEA": "136108",
    "MAKEMAKE": "136472", "VARUNA": "20000", "IXION": "28978",
    "TYPHON": "42355", "SALACIA": "120347", "2002 AW197": "55565",
    "2003 VS2": "84922", "ORCUS": "90482", "QUAOAR": "50000"
}

def get_ecliptic_lonlat(target: str, when_iso: str) -> Optional[Tuple[float, float]]:
    """
    Query JPL Horizons for ecliptic longitude/latitude.
    Handles both numeric IDs and body names.
    """
    try:
        # Normalize
        tid = HORIZONS_IDS.get(target.upper(), target)

        # Parse ISO → JD
        dt = parser.isoparse(when_iso)
        jd = swe.julday(dt.year, dt.month, dt.day,
                        dt.hour + dt.minute/60.0 + dt.second/3600.0)

        obj = Horizons(id=tid, location="500@0", epochs=[jd])
        eph = obj.ephemerides()

        ecl_lon, ecl_lat = None, None

        # Extract columns
        for lon_key in ("EclLon", "EclipticLon", "ELON"):
            if lon_key in eph.colnames:
                ecl_lon = float(eph[lon_key][0])
                break
        for lat_key in ("EclLat", "EclipticLat", "ELAT"):
            if lat_key in eph.colnames:
                ecl_lat = float(eph[lat_key][0])
                break

        # fallback RA/DEC
        if (ecl_lon is None or ecl_lat is None) and {"RA", "DEC"}.issubset(eph.colnames):
            ecl_lon, ecl_lat = ra_dec_to_ecl(float(eph["RA"][0]), float(eph["DEC"][0]), when_iso)

        if ecl_lon is None or ecl_lat is None:
            return None

        return (ecl_lon % 360.0, ecl_lat)

    except Exception as e:
        print(f"[Horizons] error for {target} at {when_iso}: {e}")
        return None
