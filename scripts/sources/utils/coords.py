import math

# Obliquity of the ecliptic at J2000 (deg)
OBLIQUITY_J2000_DEG = 23.43929111

def ra_dec_to_ecl(ra_deg: float, dec_deg: float, when_iso: str):
    """
    Convert equatorial coordinates (RA, Dec) in degrees to
    ecliptic longitude and latitude (degrees) for J2000 obliquity.

    Parameters
    ----------
    ra_deg : float
        Right Ascension in degrees
    dec_deg : float
        Declination in degrees
    when_iso : str
        Timestamp (ISO8601 string). Currently not used, but included for consistency.

    Returns
    -------
    (lon_deg, lat_deg) : tuple of floats
        Ecliptic longitude and latitude in degrees
    """
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    eps = math.radians(OBLIQUITY_J2000_DEG)

    sinb = math.sin(dec) * math.cos(eps) - math.cos(dec) * math.sin(eps) * math.sin(ra)
    b = math.asin(sinb)

    y = math.sin(ra) * math.cos(eps) + math.tan(dec) * math.sin(eps)
    x = math.cos(ra)
    l = math.atan2(y, x)

    return (math.degrees(l) % 360.0, math.degrees(b))
