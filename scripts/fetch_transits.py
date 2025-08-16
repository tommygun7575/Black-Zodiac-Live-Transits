#!/usr/bin/env python3
"""
Fetch geocentric positions from JPL Horizons and write docs/feed_now.json.

- Uses astroquery Horizons without passing refplane (avoids ephemerides_async signature mismatch).
- If Horizons doesn't return EclLon/EclLat, compute ecliptic lon/lat from RA/DEC via astropy.
"""
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from astroquery.jplhorizons import Horizons  # type: ignore
from astropy import units as u  # type: ignore
from astropy.coordinates import SkyCoord, GeocentricTrueEcliptic  # type: ignore

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG = os.path.join(ROOT, "config", "targets.json")
OUTDIR = os.path.join(ROOT, "docs")
OUTFILE = os.path.join(OUTDIR, "feed_now.json")


def load_targets(config_path: str) -> List[Dict[str, Any]]:
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("targets", [])
    return [{"id": "Sun", "label": "Sun"}, {"id": "Moon", "label": "Moon"}]


def _as_float(val):
    try:
        return float(val)
    except Exception:
        try:
            # astropy Quantity or masked value
            return float(val.value)
        except Exception:
            return None


def query_body(target_id: str) -> Dict[str, Any]:
    """
    Query Horizons for a single body (geocentric). Return a dict with fields and error if any.
    """
    try:
        obj = Horizons(id=str(target_id), location=None, epochs=None)
        eph = obj.ephemerides()  # do NOT pass refplane here (avoids async signature mismatch)
        row = eph[0]  # 'now' returns one row

        # Common values
        targetname = str(row.get("targetname", str(target_id)))
        datetime_utc = str(row.get("datetime_str", ""))
        jd = _as_float(row.get("datetime_jd"))
        ra = _as_float(row.get("RA"))
        dec = _as_float(row.get("DEC"))
        delta_au = _as_float(row.get("delta"))
        r_au = _as_float(row.get("r"))
        elong_deg = _as_float(row.get("elong"))
        phase_angle_deg = _as_float(row.get("alpha"))
        constellation = str(row.get("constellation", ""))

        # Prefer Horizons' EclLon/EclLat if provided
        ecl_lon = _as_float(row.get("EclLon")) if "EclLon" in row.colnames else None
        ecl_lat = _as_float(row.get("EclLat")) if "EclLat" in row.colnames else None

        # Fallback: compute ecliptic coordinates from RA/DEC (using astropy)
        if (ecl_lon is None or ecl_lat is None) and (ra is not None and dec is not None):
            try:
                sc = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")
                ecl = sc.transform_to(GeocentricTrueEcliptic())
                ecl_lon = float(ecl.lon.to(u.deg).value)
                ecl_lat = float(ecl.lat.to(u.deg).value)
            except Exception:
                # leave as None if transform fails
                ecl_lon = ecl_lon if ecl_lon is not None else None
                ecl_lat = ecl_lat if ecl_lat is not None else None

        return {
            "id": str(target_id),
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
        return {"id": str(target_id), "error": f"{type(e).__name__}: {e}"}


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
