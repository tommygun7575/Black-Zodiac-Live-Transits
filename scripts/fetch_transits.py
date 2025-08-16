#!/usr/bin/env python3
"""
Comprehensive transit fetcher:
- Planets/minor bodies via JPL Horizons (numeric IDs)
- Fixed stars via RA/DEC -> ecliptic using Astropy
- Arabic parts computed from natal chart values (requires natal JSON files)
- Writes docs/feed_now.json
"""

import json, os, math
from datetime import datetime, timezone
from typing import Any, Dict, List

# astroquery + astropy
from astroquery.jplhorizons import Horizons  # type: ignore
from astropy import units as u  # type: ignore
from astropy.coordinates import SkyCoord, GeocentricTrueEcliptic  # type: ignore
from astropy.time import Time  # type: ignore

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(ROOT, "config", "targets.json")
OUT_DIR = os.path.join(ROOT, "docs")
OUT_FILE = os.path.join(OUT_DIR, "feed_now.json")

OBLIQUITY_DEG = 23.439291

def load_config(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _as_float(v):
    try:
        return float(v)
    except Exception:
        try:
            return float(v.value)
        except Exception:
            return None

def query_horizons_id(idstr: str):
    try:
        obj = Horizons(id=str(idstr), location=None, epochs=None)
        eph = obj.ephemerides()
        row = eph[0]
        return True, row
    except Exception as e:
        return False, e

def compute_ecl_from_ra_dec(ra_deg, dec_deg, datetime_str=None, delta_au=None):
    # prefer astropy transform; fallback to manual trig if necessary
    try:
        dist = 1.0 * u.AU
        if delta_au is not None:
            try:
                if float(delta_au) > 1e-6:
                    dist = float(delta_au) * u.AU
            except Exception:
                pass

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
        if math.isnan(lon) or math.isnan(lat):
            # fallback
            raise ValueError("astropy returned NaN")
        return lon, lat
    except Exception:
        # manual conversion
        try:
            ra = math.radians(ra_deg)
            dec = math.radians(dec_deg)
            eps = math.radians(OBLIQUITY_DEG)
            x = math.cos(dec) * math.cos(ra)
            y = math.cos(dec) * math.sin(ra)
            z = math.sin(dec)
            y_e = math.cos(eps) * y + math.sin(eps) * z
            z_e = -math.sin(eps) * y + math.cos(eps) * z
            lon = math.degrees(math.atan2(y_e, x)) % 360.0
            lat = math.degrees(math.asin(z_e / math.sqrt(x*x+y_e*y_e+z_e*z_e)))
            return lon, lat
        except Exception as e:
            return None, None

def process_horizons_entry(idval):
    ok, res = query_horizons_id(idval)
    if not ok:
        return {"id": str(idval), "error": f"{type(res).__name__}: {res}"}
    row = res
    try:
        targetname = str(row.get("targetname", idval))
        datetime_utc = str(row.get("datetime_str",""))
        jd = _as_float(row.get("datetime_jd"))
        ra = _as_float(row.get("RA"))
        dec = _as_float(row.get("DEC"))
        delta = _as_float(row.get("delta"))
        r_au = _as_float(row.get("r"))
        elong = _as_float(row.get("elong"))
        alpha = _as_float(row.get("alpha"))
        const = str(row.get("constellation",""))

        # try Horizons ecliptic fields if present
        ecl_lon = None
        ecl_lat = None
        try:
            colnames = getattr(row, "colnames", [])
            if "EclLon" in colnames:
                ecl_lon = _as_float(row.get("EclLon"))
            if "EclLat" in colnames:
                ecl_lat = _as_float(row.get("EclLat"))
        except Exception:
            ecl_lon = None
            ecl_lat = None

        if (ecl_lon is None or ecl_lat is None) and (ra is not None and dec is not None):
            lon, lat = compute_ecl_from_ra_dec(ra, dec, datetime_utc, delta)
            ecl_lon = lon
            ecl_lat = lat

        return {
            "id": str(idval),
            "targetname": targetname,
            "datetime_utc": datetime_utc,
            "jd": jd,
            "ecl_lon_deg": ecl_lon,
            "ecl_lat_deg": ecl_lat,
            "ra_deg": ra,
            "dec_deg": dec,
            "delta_au": delta,
            "r_au": r_au,
            "elong_deg": elong,
            "phase_angle_deg": alpha,
            "constellation": const
        }
    except Exception as e:
        return {"id": str(idval), "error": f"{type(e).__name__}: {e}"}

def process_fixed_star(star):
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

def compute_arabic_part(formula: str, natal: Dict[str, Any]):
    """
    Very small arithmetic parser for common formulas like:
      asc + moon - sun
    natal must contain numeric longitudes in degrees keyed by 'asc', 'sun', 'moon'
    Returns a longitude in degrees 0-360.
    """
    try:
        # build a small eval environment
        env = {}
        for k in ('asc','sun','moon','mc','vertex'):
            if k in natal:
                env[k] = float(natal[k])
        # safe tokens only: letters, numbers, + - * / parenthesis and spaces
        allowed = set("abcdefghijklmnopqrstuvwxyz0123456789+-*/(). _")
        if not set(formula.lower()) <= allowed:
            return None, "unsafe formula"
        expr = formula.lower()
        # replace tokens with env values
        for k,v in env.items():
            expr = expr.replace(k, f"({v})")
        val = eval(expr, {"__builtins__": {}})
        # normalize
        lon = float(val) % 360.0
        return lon, None
    except Exception as e:
        return None, str(e)

def process_arabic_part(part):
    natal_file = part.get("natal_chart_file")
    if not natal_file:
        return {"id": part.get("id"), "error": "no natal_chart_file specified"}
    if not os.path.exists(natal_file):
        # allow relative to repo root
        path = os.path.join(ROOT, natal_file)
    else:
        path = natal_file
    try:
        with open(path, "r", encoding="utf-8") as f:
            natal = json.load(f)
    except Exception as e:
        return {"id": part.get("id"), "error": f"failed to open natal chart {path}: {e}"}
    # natal must contain 'asc','sun','moon' as longitudes in degrees
    lon, err = compute_arabic_part(part.get("formula",""), natal)
    if err:
        return {"id": part.get("id"), "error": err}
    return {
        "id": part.get("id"),
        "targetname": part.get("label"),
        "datetime_utc": datetime.now(timezone.utc).isoformat(),
        "jd": None,
        "ecl_lon_deg": lon,
        "ecl_lat_deg": None,
        "ra_deg": None,
        "dec_deg": None,
        "delta_au": None,
        "r_au": None,
        "constellation": None
    }

def main():
    cfg = load_config(CONFIG_PATH)
    now = datetime.now(timezone.utc).isoformat()
    results = []

    # planets
    for p in cfg.get("planets", []):
        pid = p.get("id") if isinstance(p, dict) else p
        results.append(process_horizons_entry(pid))

    # minor bodies
    for mb in cfg.get("minor_bodies", []):
        results.append(process_horizons_entry(mb))

    # fixed stars
    for star in cfg.get("fixed_stars", []):
        results.append(process_fixed_star(star))

    # arabic parts
    for part in cfg.get("arabic_parts", []):
        results.append(process_arabic_part(part))

    os.makedirs(OUT_DIR, exist_ok=True)
    payload = {
        "generated_at_utc": now,
        "observer": "geocentric (Earth center)",
        "refplane": "earth",
        "source": "JPL Horizons via astroquery + local fixed stars + computed parts",
        "objects": results
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("Wrote", OUT_FILE, "objects:", len(results))

if __name__ == "__main__":
    main()
