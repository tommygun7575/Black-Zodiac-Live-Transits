from typing import Tuple, Optional
from scripts.utils.coords import ra_dec_to_ecl
from astroquery.jplhorizons import Horizons
from dateutil import parser
import swisseph as swe

def get_ecliptic_lonlat(name: str, when_iso: str) -> Optional[Tuple[float, float]]:
    """
    Query JPL Horizons for ecliptic longitude/latitude (geocentric).
    Falls back to RA/DEC conversion if needed.
    """
    try:
        # Convert ISO time → Julian Date for Horizons
        dt = parser.isoparse(when_iso)
        jd = swe.julday(dt.year, dt.month, dt.day,
                        dt.hour + dt.minute/60.0 + dt.second/3600.0)

        # Horizons object
        obj = Horizons(id=name, location="500@0", epochs=[jd])
        eph = obj.ephemerides()

        ecl_lon, ecl_lat = None, None

        # longitude
        for lon_key in ("EclLon", "EclipticLon", "ELON"):
            if lon_key in eph.colnames:
                ecl_lon = float(eph[lon_key][0])
                break

        # latitude
        for lat_key in ("EclLat", "EclipticLat", "ELAT"):
            if lat_key in eph.colnames:
                ecl_lat = float(eph[lat_key][0])
                break

        # fallback RA/DEC -> ecliptic
        if (ecl_lon is None or ecl_lat is None) and {"RA", "DEC"}.issubset(eph.colnames):
            ecl_lon, ecl_lat = ra_dec_to_ecl(float(eph["RA"][0]), float(eph["DEC"][0]), when_iso)

        if ecl_lon is None or ecl_lat is None:
            return None

        return (ecl_lon % 360.0, ecl_lat)

    except Exception as e:
        print(f"[Horizons] error for {name} at {when_iso}: {e}")
        return None
