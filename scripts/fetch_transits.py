#!/usr/bin/env python3
"""
Robust transit fetcher for JPL Horizons → docs/feed_now.json

- Retries ambiguous-name errors using explicit numeric IDs for major solar-system bodies.
- Computes ecliptic lon/lat from RA/DEC using astropy with a sensible distance fallback
  (avoids NaNs for the Sun and other special cases).
"""
import json
import os
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


# Map common names to safe numeric IDs for Horizons (use barycenter/IAU numeric IDs)
NUMERIC_ID_MAP = {
    "Sun": "10",
    "Moon": "301",            # Luna (Moon)
    "Mercury": "199",
    "Venus": "299",
    "Earth": "399",
    "Mars": "499",
    "Jupiter": "599",
    "Saturn": "699",
    "Uranus": "799",
    "Neptune": "899",
    "Pluto": "999",
}


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
            return float(val.value)  # astropy Quantity
        except Exception:
            return None


def _attempt_query(target_id: str):
    """
    Query Horizons for a single id string. Return (success, result_or_exception).
    """
    try:
        obj = Horizons(id=str(target_id), location=None, epochs=None)
        eph = obj.ephemerides()
        row = eph[0]
        return True, row
    except Exception as e:
        return False, e


def _compute_ecliptic_from_ra_dec(ra_deg, dec_deg, datetime_str, delta_au):
    """
    Compute ecliptic lon/lat from RA/DEC using astropy.
    - Use provided distance if > tiny threshold; otherwise use 1 AU to avoid zero-distance NaNs.
    - Use the datetime_str (if available) to set the transformation time.
    """
    try:
        obstime = None
        try:
            if datetime_str:
                # Horizons returns formats like "2025-Aug-16 12:12:40"
                # astropy Time can parse many common formats
                obstime = Time(datetime_str)
        except Exception:
            obstime = None

        dist = None
        try:
            if delta_au is not None and delta_au > 1e-6:
                dist = delta_au * u.AU
            else:
                dist = 1.0 * u.AU
        except Exception:
            dist = 1.0 * u.AU

        sc = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, distance=dist, frame="icrs", obstime=obstime)
        if obstime is not None:
            ecl_frame = GeocentricTrueEcliptic(obstime=obstime)
        else:
            ecl_frame = GeocentricTrueEcliptic()
        ecl = sc.transform_to(ecl_frame)
        lon = float(ecl.lon.to(u.deg).value)
        lat = float(ecl.lat.to(u.deg).value)
        return lon, lat
    except Exception:
        return None, None


def query_body(target_spec: str) -> Dict[str, Any]:
    """
    Wrapper that tries to query Horizons. If ambiguous-name error occurs,
    retry with a numeric ID from NUMERIC_ID_MAP (when mapping exists).
    """
    # First attempt with exactly what the config specified
    ok, res = _attempt_query(target_spec)
    if ok:
        row = res
    else:
        # If Horizons complained about ambiguous names, try a mapped numeric ID
        err = res
        msg = str(err)
        mapped = NUMERIC_ID_MAP.get(str(target_spec))
        if mapped:
            ok2, res2 = _attempt_query(mapped)
            if ok2:
                row = res2
            else:
                return {"id": str(target_spec), "error": f"{type(res2).__name__}: {res2}"}
        else:
            # no mapping; return original error
            return {"id": str(target_spec), "error": f"{type(err).__name__}: {err}"}

    # Extract fields
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

        # Prefer Horizons EclLon/EclLat when available and numeric
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

        # Fallback: compute from RA/DEC
        if (ecl_lon is None or ecl_lat is None) and (ra is not None and dec is not None):
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
