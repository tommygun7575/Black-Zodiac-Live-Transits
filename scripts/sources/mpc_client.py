from typing import Tuple, Optional

def get_ecliptic_lonlat(name: str, when_iso: str) -> Optional[Tuple[float, float]]:
    try:
        from astroquery.mpc import MPC
        tab = MPC.get_ephemeris(
            target=name, location='500',
            start=when_iso, step='1d', number=1,
            eph_type='equatorial', perturbed=True
        )
        if len(tab)==0:
            return None
        from scripts.utils.coords import ra_dec_to_ecl
        return ra_dec_to_ecl(float(tab['RA'][0]), float(tab['Dec'][0]), when_iso)
    except Exception:
        return None
