import math

# Obliquity of the ecliptic at J2000 (deg)
OBLIQUITY_J2000_DEG = 23.43929111

def ra_dec_to_ecl(ra_deg: float, dec_deg: float, when_iso: str = None):
    """
    Convert equatorial coordinates (RA, Dec) in degrees to
    ecliptic longitude and latitude (degrees), using J2000 obliquity.

    Parameters
    ----------
    ra_deg : float
        Right Ascension in degrees
    dec_deg : float
        Declination in degrees
    when_iso : str, optional
        ISO8601 timestamp (currently unused, included for interface consistency)

    Returns
    -------
    (lon_deg, lat_deg) : tuple of floats
        Ecliptic longitude and latitude in degrees
    """
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    eps = math.radians(OBLIQUITY_J2000_DEG)

    # latitude
    sinb = math.sin(dec) * math.cos(eps) - math.cos(dec) * math.sin(eps) * math.sin(ra)
    b = math.asin(sinb)

    # longitude
    y = math.sin(ra) * math.cos(eps) + math.tan(dec) * math.sin(eps)
    x = math.cos(ra)
    l = math.atan2(y, x)

    lon = (math.degrees(l) + 360.0) % 360.0
    lat = math.degrees(b)

    return lon, lat
