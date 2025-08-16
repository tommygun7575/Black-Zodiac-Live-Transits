#!/usr/bin/env python3
"""
Robust transit fetcher for JPL Horizons → docs/feed_now.json

- Uses numeric IDs where appropriate (config should contain numeric ids for planets).
- Uses astroquery.horizons.ephemerides (no refplane) and falls back to astropy conversion.
- If astropy transform fails or returns NaN, uses a manual spherical trig conversion
  (equatorial -> ecliptic using obliquity).
"""
import json
import os
import math
from datetime import datetime, timezone
from typing import Any, Dict, List

from astroquery.jplhorizons import Horizons  # type: ignore
from astropy import units as u  # type: ignore
from astropy.coordinates import SkyCoord, GeocentricTrueEcliptic  # type: ignore
from astropy.time import Time  # type: ignore

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG = os.path.join(ROOT, "config", "targets.json")
OUTDIR = os.path.join(ROOT, "docs")
OUTFILE = os.path.join(OUTDIR, "feed_now.json")

# Mean obliquity (approx) for manual fallback (degrees)
OBLIQUITY_DEG = 23.439291


def load_targets(config_path: str) -> List[Dict[str, Any]]:
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("targets", [])
    return [{"id": "10", "label": "Sun"}, {"id": "301", "label": "Moon"}]


def _as_float(val):
    try:
        return float(val)
    except Exception:
        try:
            return float(val.value)
        except Exception:
            return None


def _attempt_query(target_id: str):
    try:
        obj = Horizons(id=str(target_id), location=None, epochs=None)
        eph = obj.ephemerides()
        row = eph[0]
        return True, row
    except Exception as e:
        return False, e


def _manual_ecl_from_ra_dec(ra_deg: float, dec_deg: float):
    """
    Manual conversion from equatorial (RA/DEC in degrees) to ecliptic lon/lat in degrees.
    Uses rotation about x-axis by obliquity (epsilon).
    """
    try:
        ra = math.radians(ra_deg)
        dec = math.radians(dec_deg)
        eps = math.radians(OBLIQUITY_DEG)

        x = math.cos(dec) * math.cos(ra)
        y = math.cos(dec) * math.sin(ra)
        z = math.sin(dec)

        # rotate coordinates by +epsilon about X: (x' = x; y' = cosε*y + sinε*z; z' = -sinε*y + cosε*z)
        y_e = math.cos(eps) * y + math.sin(eps) * z
        z_e = -math.sin(eps) * y + math.cos(eps) * z
        x_e = x

        r = math.sqrt(x_e * x_e + y_e * y_e + z_e * z_e)
        if r == 0:
            return None, None

        lon = math.degrees(math.atan2(y_e, x_e)) % 360.0
        lat = math.degrees(math.asin(z_e / r))
        return lon, lat
    except Exception:
        return None, None


def _compute_ecliptic_from_ra_dec(ra_deg, dec_deg, datetime_str, delta_au):
    """
    Try astropy conversion first (with sensible distance). If that returns NaN or fails,
    fall back to manual trig conversion.
    """
    try:
        # set a sensible distance (avoid zero)
        try:
            if delta_au is not None and delta_au > 1e-6:
                dist = delta_au * u.AU
            else:
                dist = 1.0 * u.AU
        except Exception:
            dist = 1.0 * u.AU

        obstime = None
        try:
            if datetime_str:
                obstime = Time(datetime_str)
        except Exception:
            obstime = None

        sc = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, distance=dist, frame="icrs", obstime=obstime)
        if obstime is not None:
            ecl_frame = GeocentricTrueEcliptic(obstime=obstime)
        else:
            ecl_frame = GeocentricTrueEcliptic()
        ecl = sc.transform_to(ecl_frame)
        lon = float(ecl.lon.to(u.deg).value)
        lat = float(ecl.lat.to(u.deg).value)

        # guard against NaN
        if math.isnan(lon) or math.isnan(lat):
            return _manual_ecl_from_ra_dec(ra_deg, dec_deg)
        return lon, lat
    except Exception:
        # final manual fallback
        return _manual_ecl_from_ra_dec(ra_deg, dec_deg)


def query_body(target_spec: str) -> Dict[str, Any]:
    ok, res = _attempt_query(target_spec)
    if ok:
        row = res
    else:
        err = res
        # if ambiguous name: just return the error (we prefer numeric ids in config)
        return {"id": str(target_spec), "error": f"{type(err).__name__}: {err}"}

    try:
        targetname = str(row.get("targetname", str(target_spec)))
        datetime_utc = str(row.get("datetime_str", ""))
        jd = _as_float(row.get("datetime_jd"))
        ra = _as_float(row.get("RA"))
        dec = _as_float(row.get("DEC"))
        delta_au = _as_float(row.get("delta"))
        r_au = _as_float(row.get("r"))
        elong_deg = _as_float(row.get("elong"))
        phase_angle_deg = _as_float(row.get("alpha"))
        constellation = str(row.get("constellation", ""))

        # prefer Horizons EclLon/EclLat
        ecl_lon = None
        ecl_lat = None
        try:
            if "EclLon" in getattr(row, "colnames", []):
                ecl_lon = _as_float(row.get("EclLon"))
            if "EclLat" in getattr(row, "colnames", []):
                ecl_lat = _as_float(row.get("EclLat"))
        except Exception:
            ecl_lon = None
            ecl_lat = None

        # fallback compute if missing or NaN
        if (ecl_lon is None or ecl_lat is None or (isinstance(ecl_lon, float) and math.isnan(ecl_lon))) and (ra is not None and dec is not None):
            lon_fallback, lat_fallback = _compute_ecliptic_from_ra_dec(ra, dec, datetime_utc, delta_au)
            if lon_fallback is not None:
                ecl_lon = lon_fallback
                ecl_lat = lat_fallback

        return {
            "id": str(target_spec),
            "targetname": targetname,
            "datetime_utc": datetime_utc,
            "jd": jd,
            "ecl_lon_deg": ecl_lon,
            "ecl_lat_deg": ecl_lat,
            "ra_deg": ra,
            "dec_deg": dec,
            "delta_au": delta_au,
            "r_au": r_au,
            "elong_deg": elong_deg,
            "phase_angle_deg": phase_angle_deg,
            "constellation": constellation,
        }
    except Exception as e:
        return {"id": str(target_spec), "error": f"{type(e).__name__}: {e}"}


def main() -> None:
    targets = load_targets(CONFIG)
    results: List[Dict[str, Any]] = []
    for t in targets:
        tid = str(t.get("id"))
        results.append(query_body(tid))

    os.makedirs(OUTDIR, exist_ok=True)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "observer": "geocentric (Earth center)",
        "refplane": "earth",
        "source": "JPL Horizons via astroquery",
        "objects": results,
    }
    with open(OUTFILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Wrote {OUTFILE} with {len(results)} objects.")


if __name__ == "__main__":
    main()
