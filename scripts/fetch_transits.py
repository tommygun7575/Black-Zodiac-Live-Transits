#!/usr/bin/env python3
"""
Full robust fetch_transits.py

- Queries JPL Horizons for numeric IDs (no `refplane` to avoid version issues).
- Computes ecliptic coords via astropy, with guaranteed manual trig fallback to avoid NaNs (Sun).
- Handles fixed stars (given RA/DEC J2000 in config).
- Computes Arabic parts for each natal JSON placed in config/natal/*.json (auto-scan).
- Writes combined docs/feed_now.json and per-natal docs/feed_<name>.json outputs.
- Produces clear "error" entries instead of crashing.
"""

import os
import json
import math
import glob
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple, Optional

# astroquery + astropy
from astroquery.jplhorizons import Horizons  # type: ignore
from astropy import units as u  # type: ignore
from astropy.coordinates import SkyCoord, GeocentricTrueEcliptic  # type: ignore
from astropy.time import Time  # type: ignore

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(ROOT, "config", "targets.json")
OUT_DIR = os.path.join(ROOT, "docs")
OUT_FILE = os.path.join(OUT_DIR, "feed_now.json")

# Manual obliquity for manual fallback
MEAN_OBLIQUITY_DEG = 23.439291

# -------------------------
# Utility helpers
# -------------------------
def load_config(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _as_float(v) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        try:
            return float(v.value)  # astropy Quantity
        except Exception:
            return None


# -------------------------
# Horizons query wrapper
# -------------------------
def query_horizons_id(idstr: Any) -> Tuple[bool, Any]:
    """
    Query Horizons for idstr synchronously (ephemerides()).
    Returns (ok, row_or_exception)
    """
    try:
        # use id as string; location=None gives geocentric Earth center context
        obj = Horizons(id=str(idstr), location=None, epochs=None)
        eph = obj.ephemerides()
        row = eph[0]
        return True, row
    except Exception as e:
        return False, e


# -------------------------
# Ecliptic computation (astropy + manual fallback)
# -------------------------
def compute_ecl_from_ra_dec(ra_deg: float, dec_deg: float, datetime_str: Optional[str] = None, delta_au: Optional[float] = None) -> Tuple[Optional[float], Optional[float]]:
    """
    Convert equatorial RA/DEC (degrees) -> ecliptic lon/lat (degrees).
    Try astropy transform first; if it fails or returns NaN, use stable manual trig.
    """
    # First attempt: astropy transform (preferred)
    try:
        # sensible distance (avoid 0)
        dist = 1.0 * u.AU
        if delta_au is not None:
            try:
                if float(delta_au) > 1e-6:
                    dist = float(delta_au) * u.AU
            except Exception:
                dist = 1.0 * u.AU

        obstime = None
        if datetime_str:
            try:
                obstime = Time(datetime_str)
            except Exception:
                obstime = None

        sc = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, distance=dist, frame="icrs", obstime=obstime)
        ecl_frame = GeocentricTrueEcliptic(obstime=obstime) if obstime is not None else GeocentricTrueEcliptic()
        ecl = sc.transform_to(ecl_frame)
        lon = float(ecl.lon.to(u.deg).value)
        lat = float(ecl.lat.to(u.deg).value)
        if not (math.isnan(lon) or math.isnan(lat)):
            return lon, lat
        # otherwise fall through to manual fallback
    except Exception:
        # fall through to manual fallback
        pass

    # Manual trig fallback: rotate equatorial vector by obliquity about X axis
    try:
        ra_r = math.radians(float(ra_deg))
        dec_r = math.radians(float(dec_deg))
        eps = math.radians(MEAN_OBLIQUITY_DEG)

        x = math.cos(dec_r) * math.cos(ra_r)
        y = math.cos(dec_r) * math.sin(ra_r)
        z = math.sin(dec_r)

        # rotate by +epsilon about X axis
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


# -------------------------
# Process Horizons row into feed object
# -------------------------
def process_horizons_entry(idval: Any) -> Dict[str, Any]:
    ok, res = query_horizons_id(idval)
    if not ok:
        # Provide a friendly skip for observer=target disallowed messages
        errmsg = str(res)
        low = errmsg.lower()
        if "observer" in low and "disallow" in low:
            return {"id": str(idval), "error": "skipped: observer equals target (Horizons disallows this request). Remove this id or use different observer."}
        return {"id": str(idval), "error": f"{type(res).__name__}: {res}"}

    row = res
    try:
        targetname = str(row.get("targetname", idval))
        datetime_utc = str(row.get("datetime_str", ""))
        jd = _as_float(row.get("datetime_jd"))
        ra = _as_float(row.get("RA"))
        dec = _as_float(row.get("DEC"))
        delta_au = _as_float(row.get("delta"))
        r_au = _as_float(row.get("r"))
        elong = _as_float(row.get("elong"))
        alpha = _as_float(row.get("alpha"))
        const = str(row.get("constellation", ""))

        # try Horizons EclLon/EclLat if present
        ecl_lon = None
        ecl_lat = None
        try:
            colnames = getattr(row, "colnames", []) or []
            if "EclLon" in colnames:
                ecl_lon = _as_float(row.get("EclLon"))
            if "EclLat" in colnames:
                ecl_lat = _as_float(row.get("EclLat"))
        except Exception:
            ecl_lon = None
            ecl_lat = None

        # If missing or NaN, compute from RA/DEC using robust function
        if (ecl_lon is None or ecl_lat is None or (isinstance(ecl_lon, float) and math.isnan(ecl_lon))):
            if ra is not None and dec is not None:
                lon_fallback, lat_fallback = compute_ecl_from_ra_dec(ra, dec, datetime_utc, delta_au)
                ecl_lon = lon_fallback
                ecl_lat = lat_fallback

        return {
            "id": str(idval),
            "targetname": targetname,
            "datetime_utc": datetime_utc,
            "jd": jd,
            "ecl_lon_deg": ecl_lon,
            "ecl_lat_deg": ecl_lat,
            "ra_deg": ra,
            "dec_deg": dec,
            "delta_au": delta_au,
            "r_au": r_au,
            "elong_deg": elong,
            "phase_angle_deg": alpha,
            "constellation": const
        }
    except Exception as e:
        return {"id": str(idval), "error": f"{type(e).__name__}: {e}"}


# -------------------------
# Fixed star processing (RA/DEC -> ecl)
# -------------------------
def process_fixed_star(star: Dict[str, Any]) -> Dict[str, Any]:
    try:
        ra = float(star["ra_deg"])
        dec = float(star["dec_deg"])
        lon, lat = compute_ecl_from_ra_dec(ra, dec)
        return {
            "id": star.get("id", star.get("label")),
            "targetname": star.get("label"),
            "datetime_utc": datetime.now(timezone.utc).isoformat(),
            "jd": None,
            "ecl_lon_deg": lon,
            "ecl_lat_deg": lat,
            "ra_deg": ra,
            "dec_deg": dec,
            "delta_au": None,
            "r_au": None,
            "elong_deg": None,
            "phase_angle_deg": None,
            "constellation": None
        }
    except Exception as e:
        return {"id": star.get("id"), "error": f"{type(e).__name__}: {e}"}


# -------------------------
# Arabic parts: safe evaluator
# -------------------------
def compute_arabic_part(formula: str, natal: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    """
    Very small, safe-ish formula evaluator.
    Supported tokens: asc, sun, moon, mc, vertex (replace by numeric values from natal).
    Operators: + - * / ( ) and numbers.
    Returns (lon_deg_or_None, error_or_None)
    """
    try:
        # gather env
        env = {}
        for k in ("asc", "sun", "moon", "mc", "vertex"):
            if k in natal:
                try:
                    env[k] = float(natal[k])
                except Exception:
                    env[k] = None

        # validate characters safe
        allowed = set("abcdefghijklmnopqrstuvwxyz0123456789+-*/(). _")
        lf = formula.lower()
        if not set(lf) <= allowed:
            return None, "unsafe formula characters"

        expr = lf
        # replace tokens with numeric literals where available
        for k, v in env.items():
            if v is None:
                # missing natal value is an error
                return None, f"missing natal value for '{k}'"
            expr = expr.replace(k, f"({v})")

        # eval in safe context
        val = eval(expr, {"__builtins__": {}})
        lon = float(val) % 360.0
        return lon, None
    except Exception as e:
        return None, str(e)


# -------------------------
# Main
# -------------------------
def main() -> None:
    try:
        cfg = load_config(CONFIG_PATH)
    except Exception as e:
        print(f"ERROR: failed to load config: {e}")
        return

    now_iso = datetime.now(timezone.utc).isoformat()

    results_core: List[Dict[str, Any]] = []

    # Planets
    for p in cfg.get("planets", []):
        pid = p.get("id") if isinstance(p, dict) else p
        results_core.append(process_horizons_entry(pid))

    # Minor bodies
    for mb in cfg.get("minor_bodies", []):
        results_core.append(process_horizons_entry(mb))

    # Fixed stars
    for star in cfg.get("fixed_stars", []):
        results_core.append(process_fixed_star(star))

    # Prepare combined plus per-natal outputs
    combined_objects = list(results_core)
    per_natal_feeds: Dict[str, List[Dict[str, Any]]] = {}

    # Autoscan natal dir
    natal_dir = os.path.join(ROOT, "config", "natal")
    natal_files = sorted(glob.glob(os.path.join(natal_dir, "*.json")))
    for nf in natal_files:
        try:
            with open(nf, "r", encoding="utf-8") as fh:
                natal = json.load(fh)
        except Exception as e:
            combined_objects.append({"id": f"natal_load_error:{os.path.basename(nf)}", "error": f"Failed to load natal file: {e}"})
            continue

        natal_name = natal.get("name") or os.path.splitext(os.path.basename(nf))[0]
        per_objs = list(results_core)  # copy core objects

        # For each configured arabic part, compute for this natal
        for part in cfg.get("arabic_parts", []):
            part_id = part.get("id", "Part")
            formula = part.get("formula", "")
            label = part.get("label", part_id)
            lon, err = compute_arabic_part(formula, natal)
            if err:
                entry = {"id": f"{part_id}@{natal_name}", "error": f"Part compute error: {err}"}
            else:
                entry = {
                    "id": f"{part_id}@{natal_name}",
                    "targetname": f"{label} ({natal_name})",
                    "datetime_utc": now_iso,
                    "jd": None,
                    "ecl_lon_deg": lon,
                    "ecl_lat_deg": None,
                    "ra_deg": None,
                    "dec_deg": None,
                    "delta_au": None,
                    "r_au": None,
                    "elong_deg": None,
                    "phase_angle_deg": None,
                    "constellation": None
                }
            per_objs.append(entry)
            combined_objects.append(entry)

        # write per-natal buffer
        per_natal_feeds[natal_name] = per_objs

    # Write combined feed
    os.makedirs(OUT_DIR, exist_ok=True)
    payload_combined = {
        "generated_at_utc": now_iso,
        "observer": "geocentric (Earth center)",
        "refplane": "earth",
        "source": "JPL Horizons via astroquery + local fixed stars + computed parts",
        "objects": combined_objects
    }
    with open(OUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(payload_combined, fh, ensure_ascii=False, indent=2)

    # Write per-natal feeds
    for natal_name, objs in per_natal_feeds.items():
        fname = os.path.join(OUT_DIR, f"feed_{natal_name}.json")
        payload = {
            "generated_at_utc": now_iso,
            "natal": natal_name,
            "observer": "geocentric (Earth center)",
            "source": "JPL Horizons + computed parts",
            "objects": objs
        }
        with open(fname, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(f"Wrote combined feed to {OUT_FILE} and {len(per_natal_feeds)} per-natal feeds.")


if __name__ == "__main__":
    main()
