#!/usr/bin/env python3
"""
fetch_transits.py — robust CLI-ready transit & parts generator.

Features:
- Loads targets config (default: config/targets.json).
- Queries JPL Horizons via astroquery with retry/backoff.
- Computes ecliptic coords via astropy; manual fallback if needed.
- Scans config/natal/*.json for natal charts; computes Arabic parts using a safe AST-based evaluator.
- Writes docs/feed_now.json and docs/feed_<sanitized_name>.json (per-natal).
- Optional overlay generation via CLI arg or OVERLAY_CHARTS env var (comma-separated names).
- Safe logging, clear errors, --dry-run support.
"""
from __future__ import annotations

import os
import sys
import json
import time
import glob
import math
import logging
import argparse
import re
import ast
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple, Optional

# External libs (must be installed in the environment)
from astroquery.jplhorizons import Horizons  # type: ignore
from astropy import units as u  # type: ignore
from astropy.coordinates import SkyCoord, GeocentricTrueEcliptic  # type: ignore
from astropy.time import Time  # type: ignore

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_CONFIG_PATH = os.path.join(ROOT, "config", "targets.json")
DEFAULT_NATAL_DIR = os.path.join(ROOT, "config", "natal")
DEFAULT_OUT_DIR = os.path.join(ROOT, "docs")
DEFAULT_OUT_FILE = os.path.join(DEFAULT_OUT_DIR, "feed_now.json")

MEAN_OBLIQUITY_DEG = 23.439291

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("fetch_transits")


# ---------------------------
# Utilities
# ---------------------------
def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)


def _as_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        try:
            return float(getattr(v, "value", None))
        except Exception:
            return None


def sanitize_name(n: str) -> str:
    n = re.sub(r"[^\w\-_\. ]+", "_", n)
    return n.replace(" ", "_")


# ---------------------------
# Horizons query with retry/backoff
# ---------------------------
def query_horizons_id(idstr: Any, max_attempts: int = 3, backoff_base: float = 1.0) -> Tuple[bool, Any]:
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            obj = Horizons(id=str(idstr), location=None, epochs=None)
            eph = obj.ephemerides()
            if len(eph) == 0:
                return False, RuntimeError("Horizons returned empty ephemerides")
            return True, eph[0]
        except Exception as e:
            last_exc = e
            wait = backoff_base * (2 ** (attempt - 1))
            log.warning(
                "Horizons query failed for %s (attempt %d/%d): %s — retrying in %.1fs",
                idstr,
                attempt,
                max_attempts,
                getattr(e, "message", str(e)),
                wait,
            )
            time.sleep(wait)
    return False, last_exc


# ---------------------------
# Ecliptic computation
# ---------------------------
def compute_ecl_from_ra_dec(
    ra_deg: float, dec_deg: float, datetime_str: Optional[str] = None, delta_au: Optional[float] = None
) -> Tuple[Optional[float], Optional[float]]:
    """
    Convert RA/DEC (ICRS/J2000-like) to geocentric true ecliptic lon/lat degrees.
    Prefer astropy transform; fallback to manual mean-obliquity transform.
    """
    try:
        dist = 1.0 * u.AU
        if delta_au is not None:
            try:
                dd = float(delta_au)
                if dd > 1e-9:
                    dist = dd * u.AU
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
            return lon % 360.0, lat
    except Exception:
        log.debug("Astropy ecliptic transform failed; falling back to manual.", exc_info=True)

    # Manual fallback: mean obliquity J2000
    try:
        ra_r = math.radians(float(ra_deg))
        dec_r = math.radians(float(dec_deg))
        eps = math.radians(MEAN_OBLIQUITY_DEG)

        x = math.cos(dec_r) * math.cos(ra_r)
        y = math.cos(dec_r) * math.sin(ra_r)
        z = math.sin(dec_r)

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


# ---------------------------
# Safe expression evaluation for Arabic parts
# ---------------------------
# Allowed AST node types (no Call, no Attribute)
_ALLOWED_NODES = {
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,  # py3.8+: numbers/strings
    ast.Num,  # fallback for older versions
    ast.Name,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Tuple,
    ast.List,
    ast.Subscript,
    ast.Index,
    ast.Slice,
}


def _is_safe_ast(node: ast.AST) -> bool:
    """
    Structural AST check: disallow Call, Attribute, or any node not in the allowed set.
    """
    for n in ast.walk(node):
        if isinstance(n, ast.Call) or isinstance(n, ast.Attribute):
            return False
        if type(n) not in _ALLOWED_NODES:
            return False
    return True


def evaluate_arabic_formula(formula: str, env: Dict[str, float]) -> Tuple[Optional[float], Optional[str]]:
    """
    Safely evaluate arithmetic expressions that can only reference names in `env`.
    - Allowed operations: + - * / % ** parentheses.
    - Disallows function calls and attribute access.
    Returns (value_mod360, error_message_or_None).
    """
    if not formula or not isinstance(formula, str):
        return None, "empty formula"

    expr = formula.strip()
    # Quick reject of function-call looking patterns
    if re.search(r"[a-zA-Z_][a-zA-Z0-9_]*\s*\(", expr):
        return None, "function calls not allowed"

    try:
        node = ast.parse(expr, mode="eval")
    except Exception as e:
        return None, f"parse error: {e}"

    if not _is_safe_ast(node):
        return None, "unsafe formula content (calls/attributes or disallowed nodes)"

    # Collect identifiers used and ensure they're in env (case-insensitive)
    names_in_expr = {n.id.lower() for n in ast.walk(node) if isinstance(n, ast.Name)}
    allowed_names = {k.lower() for k in env.keys()}
    unknown = names_in_expr - allowed_names
    if unknown:
        return None, f"unknown identifier(s) in formula: {', '.join(sorted(unknown))}"

    # Build safe mapping (case-insensitive)
    names_map = {k.lower(): float(v) for k, v in env.items() if v is not None}
    try:
        code = compile(node, "<expr>", "eval")
        val = eval(code, {"__builtins__": {}}, names_map)
        valf = float(val) % 360.0
        return valf, None
    except Exception as e:
        return None, f"eval error: {e}"


# ---------------------------
# Process Horizons / fixed stars
# ---------------------------
def process_horizons_entry(idval: Any) -> Dict[str, Any]:
    ok, res = query_horizons_id(idval)
    if not ok:
        errmsg = str(res)
        low = errmsg.lower()
        if "observer" in low and "disallow" in low:
            return {"id": str(idval), "error": "skipped: observer equals target (Horizons disallows this request)."}
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
            "constellation": const,
        }
    except Exception as e:
        return {"id": str(idval), "error": f"{type(e).__name__}: {e}"}


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
            "constellation": None,
        }
    except Exception as e:
        return {"id": star.get("id"), "error": f"{type(e).__name__}: {e}"}


# ---------------------------
# Main runner
# ---------------------------
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Generate feed_now.json and per-natal transit/part files.")
    p.add_argument("--config", "-c", default=DEFAULT_CONFIG_PATH, help="Path to targets config (JSON).")
    p.add_argument("--natal-dir", default=DEFAULT_NATAL_DIR, help="Directory containing natal JSON files.")
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Output directory for feed files.")
    p.add_argument(
        "--overlay-charts",
        "-o",
        help="Comma-separated natal names to create overlay feed (overrides OVERLAY_CHARTS env).",
    )
    p.add_argument("--dry-run", action="store_true", help="Run but do not write files.")
    p.add_argument("--workers", type=int, default=1, help="Parallel workers for querying (1 = serial).")
    args = p.parse_args(argv)

    try:
        cfg = load_json(args.config)
    except Exception as e:
        log.error("Failed to load config %s: %s", args.config, e)
        return 2

    natal_dir = args.natal_dir
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    now_iso = datetime.now(timezone.utc).isoformat()
    results_core: List[Dict[str, Any]] = []

    # Planets
    planets = cfg.get("planets", [])
    log.info("Processing %d planet IDs...", len(planets))
    for p_id in planets:
        pid = p_id.get("id") if isinstance(p_id, dict) else p_id
        res = process_horizons_entry(pid)
        results_core.append(res)

    # Minor bodies
    minor_bodies = cfg.get("minor_bodies", [])
    log.info("Processing %d minor bodies...", len(minor_bodies))
    for mb in minor_bodies:
        mb_id = mb.get("id") if isinstance(mb, dict) else mb
        res = process_horizons_entry(mb_id)
        results_core.append(res)

    # Fixed stars
    fixed_stars = cfg.get("fixed_stars", [])
    log.info("Processing %d fixed stars...", len(fixed_stars))
    for star in fixed_stars:
        results_core.append(process_fixed_star(star))

    combined_objects = list(results_core)
    per_natal_feeds: Dict[str, List[Dict[str, Any]]] = {}

    natal_files = sorted(glob.glob(os.path.join(natal_dir, "*.json")))
    log.info("Found %d natal files in %s", len(natal_files), natal_dir)

    for nf in natal_files:
        try:
            natal = load_json(nf)
        except Exception as e:
            log.error("Failed to load natal file %s: %s", nf, e)
            combined_objects.append({"id": f"natal_load_error:{os.path.basename(nf)}", "error": f"Failed to load natal file: {e}"})
            continue

        natal_name = natal.get("name") or os.path.splitext(os.path.basename(nf))[0]
        per_objs = list(results_core)  # start with core objects

        # Prepare env for parts evaluation (lowercase keys)
        env: Dict[str, Optional[float]] = {}
        for k in ("asc", "sun", "moon", "mc", "vertex"):
            val = natal.get(k)
            env[k] = float(val) if (val is not None) else None

        for part in cfg.get("arabic_parts", []):
            part_id = part.get("id", "Part")
            formula = part.get("formula", "")
            label = part.get("label", part_id)

            lon, err = evaluate_arabic_formula(formula, {k: v for k, v in env.items() if v is not None})
            if err:
                entry = {"id": f"{part_id}@{natal_name}", "error": f"Part compute error: {err}"}
                log.warning("Arabic part compute error for %s @ %s: %s", part_id, natal_name, err)
            else:
                entry = {
                    "id": f"{part_id}@{natal_name}",
                    "targetname": f"{label} ({natal_name})",
