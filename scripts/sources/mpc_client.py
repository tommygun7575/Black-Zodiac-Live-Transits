from typing import Tuple, Optional
from scripts.utils.coords import ra_dec_to_ecl   # ✅ top-level import
from astroquery.mpc import MPC                   # ✅ top-level import

def get_ecliptic_lonlat(name: str, when_iso: str) -> Optional[Tuple[float, float]]:
    """
    Query MPC for ephemeris and convert RA/DEC to ecliptic lon/lat.
    """
    try:
        tab = MPC.get_ephemeris(
            target=name,
            location="500",
            start=when_iso,
            step="1d",
            number=1,
            eph_type="equatorial",
            perturbed=True
        )
        if len(tab) == 0:
            return None

        return ra_dec_to_ecl(float(tab["RA"][0]), float(tab["Dec"][0]), when_iso)

    except Exception:
        return None
