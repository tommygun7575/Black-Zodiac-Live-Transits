#!/usr/bin/env python3
"""
fetch_transits.py — robust CLI-ready transit & parts generator + public-GitHub fetch mode.

New: If --fetch-url is provided (public raw.githubusercontent URL), the script will:
 - download the JSON,
 - optionally save it to OUT_DIR/feed_now.json (--save-remote),
 - extract and print the transits for --date (UTC) or --today.

Otherwise it runs the existing generator behavior (query Horizons, compute parts, write feeds).
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
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Tuple, Optional

# third-party libs
import requests
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

# logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ")
log = logging.getLogger("fetch_transits")


# ---------------------------
# Small helpers: JSON I/O & sanitizers
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
# Remote fetch utility (public raw GitHub)
# ---------------------------
def fetch_public_raw_json(raw_url: str, timeout: int = 30) -> Any:
    """
    Fetch a public raw.githubusercontent.com URL and return parsed JSON.
    Raises on HTTP errors or JSON errors.
    """
    log.info("Fetching remote feed: %s", raw_url)
    r = requests.get(raw_url, timeout=timeout)
    r.raise_for_status()
    try:
        return r.json()
    except Exception as e:
        raise RuntimeError(f"Remote content is not valid JSON: {e}")


# ---------------------------
# Quick day-extraction from feed JSON
# ---------------------------
def parse_iso_datetime_str(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        # try common ISO formats
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        try:
            # fallback: detect numeric jd or other forms not supported
            return None
        except Exception:
            return None


def find_transits_for_day(feed_json: Any, target_date: date) -> List[Dict[str, Any]]:
    """
    Generic scanner: find dicts in feed_json that contain a time-like field whose date == target_date.
    Returns list of matched dicts (events).
    """
    hits: List[Dict[str, Any]] = []

    def walk(obj: Any):
        if isinstance(obj, dict):
            # if this dict looks like an event with a datetime-like key, try it
            for key in ("time", "datetime", "generated_at_utc", "timestamp", "date", "datetime_utc"):
                if key in obj:
                    dt = parse_iso_datetime_str(obj.get(key))
                    if dt and dt.date() == target_date:
                        hits.append(obj)
                        return  # consider this dict handled
            # otherwise deeper walk
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for itm in obj:
                walk(itm)

    walk(feed_json)
    return hits


def pretty_print_events(events: List[Dict[str, Any]], target_date: date) -> None:
    if not events:
        print(f"No transit events found for {target_date.isoformat()}.")
        return
    for ev in events:
        ts = ev.get("time") or ev.get("datetime") or ev.get("generated_at_utc") or ev.get("datetime_utc") or ev.get("timestamp")
        print("----")
        if ts:
            print("time:", ts)
        # print the most useful keys succinctly
        for k in ("object", "targetname", "aspect", "notes", "desc", "description"):
            if k in ev:
                v = ev[k]
                if isinstance(v, (dict, list)):
                    s = json.dumps(v, ensure_ascii=False)
                else:
                    s = str(v)
                print(f"{k}: {s}")
        # fallback short dump
        other = {k: v for k, v in ev.items() if k not in ("time", "datetime", "generated_at_utc", "datetime_utc")}
        if other:
            s = json.dumps(other, ensure_ascii=False)
            print(s if len(s) < 500 else s[:500] + " ... (truncated)")


# ---------------------------
# Horizons + ecliptic conversion (kept from previous robust version)
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
            log.warning("Horizons query failed for %s (attempt %d/%d): %s — retrying in %.1fs",
                        idstr, attempt, max_attempts, getattr(e, "message", str(e)), wait)
            time.sleep(wait)
    return False, last_exc


def compute_ecl_from_ra_dec(ra_deg: float, dec_deg: float, datetime_str: Optional[str] = None,
                            delta_au: Optional[float] = None) -> Tuple[Optional[float], Optional[float]]:
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
        log.debug("Astropy transform failed; falling back to manual computation", exc_info=True)
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
# Arabic parts evaluator (safe AST)
# ---------------------------
_ALLOWED_NODES = {
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Num, ast.Name, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.USub, ast.UAdd,
    ast.Tuple, ast.List, ast.Subscript, ast.Index, ast.Slice
}


def _is_safe_ast(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Call) or isinstance(n, ast.Attribute):
            return False
        if type(n) not in _ALLOWED_NODES:
            return False
    return True


def evaluate_arabic_formula(formula: str, env: Dict[str, float]) -> Tuple[Optional[float], Optional[str]]:
    if not formula or not isinstance(formula, str):
        return None, "empty formula"
    expr = formula.strip()
    if re.search(r"[a-zA-Z_][a-zA-Z0-9_]*\s*\(", expr):
        return None, "function calls not allowed"
    try:
        node = ast.parse(expr, mode="eval")
    except Exception as e:
        return None, f"parse error: {e}"
    if not _is_safe_ast(node):
        return None, "unsafe formula content (calls/attributes or disallowed nodes)"
    names_in_expr = {n.id.lower() for n in ast.walk(node) if isinstance(n, ast.Name)}
    allowed_names = {k.lower() for k in env.keys()}
    unknown = names_in_expr - allowed_names
    if unknown:
        return None, f"unknown identifier(s) in formula: {', '.join(sorted(unknown))}"
    names_map = {k.lower(): float(v) for k, v in env.items() if v is not None}
    try:
        code = compile(node, "<expr>", "eval")
        val = eval(code, {"__builtins__": {}}, names_map)
        valf = float(val) % 360.0
        return valf, None
    except Exception as e:
        return None, f"eval error: {e}"


# ---------------------------
# Process Horizons/fixed stars (kept)
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
    p = argparse.ArgumentParser(description="Generate feed_now.json and per-natal transit/part files or fetch remote feed.")
    p.add_argument("--config", "-c", default=DEFAULT_CONFIG_PATH, help="Path to targets config (JSON).")
    p.add_argument("--natal-dir", default=DEFAULT_NATAL_DIR, help="Directory containing natal JSON files.")
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Output directory for feed files.")
    p.add_argument("--fetch-url", help="Public raw.githubusercontent URL for feed_now.json (overrides generator when present).")
    p.add_argument("--save-remote", action="store_true", help="When fetching remote, save the JSON to --out-dir/feed_now.json.")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--today", action="store_true", help="Show transits for today (UTC).")
    grp.add_argument("--date", help="Show transits for ISO date YYYY-MM-DD (UTC).")
    p.add_argument("--overlay-charts", "-o", help="Comma-separated natal names to create overlay feed (overrides OVERLAY_CHARTS env).")
    p.add_argument("--dry-run", action="store_true", help="Run but do not write files (generator mode).")
    p.add_argument("--workers", type=int, default=1, help="Parallel workers (unused currently).")
    args = p.parse_args(argv)

    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    # If user asked to fetch remote feed (public raw GitHub)
    if args.fetch_url:
        try:
            feed = fetch_public_raw_json(args.fetch_url)
        except Exception as e:
            log.error("Failed to fetch remote feed: %s", e)
            return 3

        # Optionally save remote JSON to out-dir
        if args.save_remote:
            out_file = os.path.join(out_dir, "feed_now.json")
            try:
                write_json(out_file, feed)
                log.info("Saved remote feed to %s", out_file)
            except Exception as e:
                log.error("Failed to save remote feed: %s", e)

        # Determine target date (UTC)
        if args.today or not args.date:
            tgt = datetime.now(timezone.utc).date()
        else:
            try:
                tgt = datetime.fromisoformat(args.date).date()
            except Exception:
                log.error("Bad --date format; use YYYY-MM-DD")
                return 2

        events = find_transits_for_day(feed, tgt)
        pretty_print_events(events, tgt)
        return 0

    # Otherwise run generator behavior (original script)
    try:
        cfg = load_json(args.config)
    except Exception as e:
        log.error("Failed to load config %s: %s", args.config, e)
        return 2

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

    natal_files = sorted(glob.glob(os.path.join(args.natal_dir, "*.json")))
    log.info("Found %d natal files in %s", len(natal_files), args.natal_dir)

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
                    "constellation": None,
                }
            per_objs.append(entry)
            combined_objects.append(entry)

        per_natal_feeds[natal_name] = per_objs

    # Combined output payload
    payload_combined = {
        "generated_at_utc": now_iso,
        "observer": "geocentric (Earth center)",
        "refplane": "earth",
        "source": "JPL Horizons via astroquery + local fixed stars + computed parts",
        "objects": combined_objects,
    }

    # Write combined feed
    out_file = os.path.join(out_dir, "feed_now.json")
    if args.dry_run:
        log.info("Dry run: would write combined feed to %s (objects=%d)", out_file, len(combined_objects))
    else:
        write_json(out_file, payload_combined)
        log.info("Wrote combined feed to %s (objects=%d)", out_file, len(combined_objects))

    # Write per-natal feeds
    for natal_name, objs in per_natal_feeds.items():
        safe = sanitize_name(natal_name)
        fname = os.path.join(out_dir, f"feed_{safe}.json")
        payload = {
            "generated_at_utc": now_iso,
            "natal": natal_name,
            "observer": "geocentric (Earth center)",
            "source": "JPL Horizons + computed parts",
            "objects": objs,
        }
        if args.dry_run:
            log.info("Dry run: would write per-natal feed %s (objects=%d)", fname, len(objs))
        else:
            write_json(fname, payload)
            log.info("Wrote per-natal feed %s (objects=%d)", fname, len(objs))

    # Overlay support (CLI or env)
    overlay_env = args.overlay_charts or os.environ.get("OVERLAY_CHARTS", "") or ""
    overlay_env = overlay_env.strip()
    if overlay_env:
        chart_names = [n.strip() for n in overlay_env.split(",") if n.strip()]
        overlay_objs: List[Dict[str, Any]] = list(results_core)
        missing = []
        for name in chart_names:
            objs = per_natal_feeds.get(name)
            if objs is None:
                missing.append(name)
            else:
                for o in objs:
                    oid = o.get("id", "")
                    if isinstance(oid, str) and oid.endswith(f"@{name}"):
                        overlay_objs.append(o)
        overlay_fname = os.path.join(out_dir, f"feed_overlay_{sanitize_name('_'.join(chart_names))}.json")
        payload_overlay = {
            "generated_at_utc": now_iso,
            "overlay_charts": chart_names,
            "missing_charts": missing,
            "observer": "geocentric (Earth center)",
            "source": "JPL Horizons + overlay parts",
            "objects": overlay_objs,
        }
        if args.dry_run:
            log.info("Dry run: would write overlay feed %s (objects=%d) missing=%s", overlay_fname, len(overlay_objs), missing)
        else:
            write_json(overlay_fname, payload_overlay)
            log.info("Wrote overlay feed to %s (objects=%d) missing=%s", overlay_fname, len(overlay_objs), missing)

    log.info("Done. Combined objects: %d, per-natal feeds: %d", len(combined_objects), len(per_natal_feeds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
