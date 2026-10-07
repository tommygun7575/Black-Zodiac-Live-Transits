"""Reference-frame helpers: geocentric apparent, ecliptic & equinox OF DATE.

Every longitude/latitude published by the daily and 6-month feeds must be the
GEOCENTRIC APPARENT ecliptic position referred to the TRUE ecliptic and equinox
OF DATE (tropical). That is exactly what:

* JPL Horizons OBSERVER table, QUANTITIES='31' (astroquery columns
  ``ObsEclLon`` / ``ObsEclLat``), CENTER='500@399' returns;
* IMCCE Miriade ``-teph=2`` (apparent, equinox of date) ``-rplane=2``
  (ecliptic) ``-tcoor=1`` (spherical) returns;
* Swiss Ephemeris ``calc_ut`` with default flags (no HELCTR / J2000 /
  NONUT / TRUEPOS) returns.

WARNING: astroquery's ``EclLon`` / ``EclLat`` columns are Horizons quantity 18
(HELIOCENTRIC ecliptic longitude/latitude of the target). They must never be
used as a geocentric position.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

try:
    import swisseph as swe
except ImportError:  # pragma: no cover
    import pyswisseph as swe  # type: ignore


# astroquery column names for Horizons quantity 31 (observer ecliptic of date).
HORIZONS_GEOCENTRIC_LON_KEYS = ("ObsEclLon",)
HORIZONS_GEOCENTRIC_LAT_KEYS = ("ObsEclLat",)

# Horizons quantity 2: apparent RA/DEC (true equator & equinox of date).
HORIZONS_APPARENT_RA_KEYS = ("RA_app",)
HORIZONS_APPARENT_DEC_KEYS = ("DEC_app",)

# Horizons quantity 18 — heliocentric. Listed only so callers can assert they
# are NOT using these.
HORIZONS_HELIOCENTRIC_KEYS = ("EclLon", "EclLat")

# Miriade query parameters for geocentric apparent ecliptic of date.
MIRIADE_APPARENT_OF_DATE_PARAMS = {
    "-observer": "500",
    "-teph": "2",
    "-tcoor": "1",
    "-rplane": "2",
}


def _finite(value: Any) -> bool:
    if value is None:
        return False
    try:
        import numpy as np

        if np.ma.is_masked(value):
            return False
    except Exception:
        pass
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def jd_ut(dt: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    d = dt.astimezone(timezone.utc)
    return swe.julday(
        d.year,
        d.month,
        d.day,
        d.hour + d.minute / 60.0 + (d.second + d.microsecond / 1e6) / 3600.0,
    )


def nutation_and_obliquity(jd: float) -> Tuple[float, float, float, float]:
    """Return (true_obliquity, mean_obliquity, nut_lon, nut_obl) in degrees."""
    values = swe.calc_ut(float(jd), swe.ECL_NUT)[0]
    return float(values[0]), float(values[1]), float(values[2]), float(values[3])


def true_obliquity_deg(jd: float) -> float:
    return nutation_and_obliquity(jd)[0]


def equatorial_to_ecliptic(
    ra_deg: float, dec_deg: float, obliquity_deg: float
) -> Tuple[float, float]:
    ra = math.radians(float(ra_deg))
    dec = math.radians(float(dec_deg))
    eps = math.radians(float(obliquity_deg))
    sin_b = math.sin(dec) * math.cos(eps) - math.cos(dec) * math.sin(eps) * math.sin(ra)
    b = math.asin(max(-1.0, min(1.0, sin_b)))
    y = math.sin(ra) * math.cos(eps) + math.tan(dec) * math.sin(eps)
    x = math.cos(ra)
    return math.degrees(math.atan2(y, x)) % 360.0, math.degrees(b)


def ecliptic_to_equatorial_of_date(
    lon_deg: float, lat_deg: float, jd: float
) -> Tuple[float, float]:
    """Ecliptic-of-date lon/lat -> apparent RA/Dec of date (true obliquity)."""
    from scripts.utils.celestial_math import ecliptic_to_equatorial

    return ecliptic_to_equatorial(lon_deg, lat_deg, true_obliquity_deg(jd))


def apparent_radec_to_ecliptic_of_date(
    ra_app_deg: float, dec_app_deg: float, jd: float
) -> Tuple[float, float]:
    """Apparent RA/Dec (true equator/equinox of date) -> ecliptic of date."""
    return equatorial_to_ecliptic(ra_app_deg, dec_app_deg, true_obliquity_deg(jd))


# ---------------------------------------------------------------------------
# Precession (IAU 1976, Lieske) for catalog J2000 -> mean equator of date
# ---------------------------------------------------------------------------


def precess_j2000_to_date(ra_deg: float, dec_deg: float, jd: float) -> Tuple[float, float]:
    """Rigorous IAU-1976 precession of J2000 RA/Dec to mean equinox of date."""
    t = (float(jd) - 2451545.0) / 36525.0
    asec = math.pi / (180.0 * 3600.0)
    zeta = (2306.2181 * t + 0.30188 * t * t + 0.017998 * t ** 3) * asec
    z = (2306.2181 * t + 1.09468 * t * t + 0.018203 * t ** 3) * asec
    theta = (2004.3109 * t - 0.42665 * t * t - 0.041833 * t ** 3) * asec
    ra0 = math.radians(float(ra_deg))
    dec0 = math.radians(float(dec_deg))
    a = math.cos(dec0) * math.sin(ra0 + zeta)
    b = math.cos(theta) * math.cos(dec0) * math.cos(ra0 + zeta) - math.sin(theta) * math.sin(dec0)
    c = math.sin(theta) * math.cos(dec0) * math.cos(ra0 + zeta) + math.cos(theta) * math.sin(dec0)
    ra = math.atan2(a, b) + z
    dec = math.asin(max(-1.0, min(1.0, c)))
    return math.degrees(ra) % 360.0, math.degrees(dec)


def fixed_star_of_date(
    name: str,
    ra_j2000_deg: Optional[float],
    dec_j2000_deg: Optional[float],
    jd: float,
) -> Optional[dict]:
    """Fixed star apparent ecliptic lon/lat + RA/Dec OF DATE.

    Primary: Swiss Ephemeris ``fixstar2_ut`` (sefstars.txt; proper motion,
    precession, nutation, aberration) — identical to the Zodiac Oracle feed.
    Fallback: rigorous precession of the catalog J2000 RA/Dec + nutation in
    longitude (no aberration, <= ~0.006 deg difference).
    """
    try:
        ecl = swe.fixstar2_ut(str(name), float(jd), swe.FLG_SWIEPH)[0]
        equ = swe.fixstar2_ut(str(name), float(jd), swe.FLG_SWIEPH | swe.FLG_EQUATORIAL)[0]
        if _finite(ecl[0]) and _finite(ecl[1]):
            return {
                "longitude": float(ecl[0]) % 360.0,
                "latitude": float(ecl[1]),
                "right_ascension": float(equ[0]) % 360.0,
                "declination": float(equ[1]),
                "frame_method": "swiss_fixstar2_apparent_of_date",
            }
    except Exception:
        pass

    if not (_finite(ra_j2000_deg) and _finite(dec_j2000_deg)):
        return None
    true_eps, mean_eps, nut_lon, _ = nutation_and_obliquity(jd)
    ra_m, dec_m = precess_j2000_to_date(float(ra_j2000_deg), float(dec_j2000_deg), jd)
    lon_m, lat = equatorial_to_ecliptic(ra_m, dec_m, mean_eps)
    lon = (lon_m + nut_lon) % 360.0
    from scripts.utils.celestial_math import ecliptic_to_equatorial

    ra_t, dec_t = ecliptic_to_equatorial(lon, lat, true_eps)
    return {
        "longitude": lon,
        "latitude": lat,
        "right_ascension": ra_t,
        "declination": dec_t,
        "frame_method": "precessed_j2000_catalog_plus_nutation",
    }


# ---------------------------------------------------------------------------
# Miriade helpers
# ---------------------------------------------------------------------------

_SEXA_RE = re.compile(r"^\s*([+-]?)(\d+):(\d+):(\d+(?:\.\d*)?)\s*$")


def parse_angle(value: Any) -> Optional[float]:
    """Parse decimal degrees or a sexagesimal 'DDD:MM:SS.s' string."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    text = str(value).strip()
    match = _SEXA_RE.match(text)
    if match:
        sign = -1.0 if match.group(1) == "-" else 1.0
        deg = float(match.group(2)) + float(match.group(3)) / 60.0 + float(match.group(4)) / 3600.0
        return sign * deg
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def miriade_row_lon_lat(row: dict) -> Tuple[Optional[float], Optional[float]]:
    """Return (lon, lat) from a lower-cased Miriade JSON row (ecliptic plane)."""
    lon = None
    lat = None
    for key in ("longitude", "elon", "ecllon"):
        if key in row:
            lon = parse_angle(row.get(key))
            if lon is not None:
                break
    for key in ("latitude", "elat", "ecllat"):
        if key in row:
            lat = parse_angle(row.get(key))
            if lat is not None:
                break
    if lon is not None:
        lon %= 360.0
    return lon, lat
