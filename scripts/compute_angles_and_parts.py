#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
compute_angles_and_parts.py — Add Swiss Angles + Arabic Parts.

Backwards compatible:
- Preferred:  --config config/live_config.json  (targets + arabic parts come from here)
- Legacy:     --targets config/targets.json     (targets only; uses built-in parts)

Sun/Moon are pulled from the feed (ecl_lon_deg/ecl_lon) or derived from RA/DEC.
"""

import json, sys, argparse, pathlib, math
from datetime import datetime, timezone
from dateutil import parser as dtparse

from astropy.coordinates import SkyCoord, FK5, GeocentricTrueEcliptic
from astropy.time import Time
import astropy.units as u
import swisseph as swe


# ---------- helpers

def norm360(x): return float(x % 360.0)

def _to_float(v):
    try: return float(v)
    except: return None

def _ecliptic_from_ra_dec(obj, obstime_iso: str | None):
    ra = _to_float(obj.get("ra_deg")); dec = _to_float(obj.get("dec_deg"))
    if ra is None or dec is None: return None
    t = Time(obstime_iso) if obstime_iso else Time.now()
    c = SkyCoord(ra=ra*u.deg, dec=dec*u.deg, frame=FK5(equinox="J2000"))
    ecl = c.transform_to(GeocentricTrueEcliptic(obstime=t))
    return float(ecl.lon.to(u.deg).value)

def find_lon(feed, ids_or_names, gen_time):
    """
    Try to find an object's ecliptic longitude in the feed by id or name.
    Accepts ecl_lon_deg, ecl_lon, or derives from RA/Dec.
    """
    for obj in feed.get("objects", []):
        oid = str(obj.get("id"))
        name = str(obj.get("targetname", ""))
        if oid in ids_or_names or name in ids_or_names:
            lon = _to_float(obj.get("ecl_lon_deg"))
            if lon is None:
                lon = _to_float(obj.get("ecl_lon"))
            if lon is None:
                lon = _ecliptic_from_ra_dec(obj, gen_time)
            if lon is not None:
                return norm360(lon)
    return None

def julday(dt_utc):
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day,
                      dt_utc.hour + dt_utc.minute/60 + dt_utc.second/3600.0)

def swiss_angles(dt_utc, lat, lon, hsys="P"):
    jd_ut = julday(dt_utc)
    swe.set_ephe_path(str(pathlib.Path(".eph").resolve()))
    cusps, ascmc = swe.houses(jd_ut, lat, lon, hsys.encode("ascii"))
    return {"ASC": norm360(ascmc[0]), "MC": norm360(ascmc[1]),
            "houses": [norm360(c) for c in cusps[1:13]]}

def is_daytime(dt_utc, lat_deg, lon_deg):
    jd_ut = julday(dt_utc)
    xx, _ = swe.calc_ut(jd_ut, swe.SUN, swe.FLG_SWIEPH | swe.FLG_EQUATORIAL)
    ra, dec = xx[0], xx[1]
    lst = swe.sidtime(jd_ut)*15 + lon_deg
    ha = (lst - ra) % 360
    if ha > 180: ha -= 360
    alt = math.degrees(math.asin(
        math.sin(math.radians(lat_deg))*math.sin(math.radians(dec)) +
        math.cos(math.radians(lat_deg))*math.cos(math.radians(dec))*math.cos(math.radians(ha))
    ))
    return alt > 0

def eval_formula(formula, mapping):
    try:
        expr = formula
        for k,v in mapping.items():
            expr = expr.replace(k, str(v))
        return norm360(eval(expr))
    except Exception as e:
        print(f"[WARN] Formula eval failed '{formula}': {e}", file=sys.stderr)
        return None


# ---------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", required=True, help="docs/feed_now.json")
    # Backward-compatible: allow either config or targets
    ap.add_argument("--config", required=False, help="config/live_config.json")
    ap.add_argument("--targets", required=False, help="legacy targets file (lat/lon list)")
    ap.add_argument("--out", required=True, help="output (overwrite feed)")
    args = ap.parse_args()

    if not args.config and not args.targets:
        print("[ERROR] Need --config (preferred) or --targets (legacy).", file=sys.stderr)
        sys.exit(2)

    feed = json.loads(open(args.feed, "r", encoding="utf-8").read())

    # When using live_config.json, get everything (targets + parts) from there.
    targets = []
    parts_cfg = None
    if args.config:
        cfg = json.loads(open(args.config, "r", encoding="utf-8").read())
        targets = cfg.get("targets", [])
        parts_cfg = cfg.get("arabic_parts", {})
    else:
        # Legacy targets.json mode: only targets are available
        tfile = json.loads(open(args.targets, "r", encoding="utf-8").read())
        targets = tfile.get("targets", [])
        # Minimal built-in Parts so the step still works
        parts_cfg = {
            "parts": [
                {"label": "Part of Fortune", "output_id_pattern": "PartOfFortune@{name}",
                 "formula_day": "ASC + Moon - Sun", "formula_night": "ASC + Sun - Moon"},
                {"label": "Part of Spirit",   "output_id_pattern": "PartOfSpirit@{name}",
                 "formula_day": "ASC + Sun - Moon", "formula_night": "ASC + Moon - Sun"},
            ]
        }

    gen_time = feed.get("generated_at_utc") or feed.get("datetime_utc")
    if not gen_time:
        print("[ERROR] feed missing generated_at_utc", file=sys.stderr)
        sys.exit(1)
    dt_utc = dtparse.isoparse(gen_time).astimezone(timezone.utc).replace(tzinfo=None)

    # Sun/Moon longitudes (robust)
    sun  = find_lon(feed, {"10","Sun"}, gen_time)
    moon = find_lon(feed, {"301","Moon"}, gen_time)
    if sun is None or moon is None:
        print("[ERROR] feed missing Sun/Moon", file=sys.stderr)
        try:
            preview = json.dumps(feed.get("objects", [])[:6], indent=2)[:1200]
            print("[DEBUG objects preview]\n" + preview, file=sys.stderr)
        except: pass
        sys.exit(1)

    # For each target: angles + parts
    for t in targets:
        name = t["name"]; lat = float(t["lat"]); lon = float(t["lon"])
        hsys = t.get("house_system", "P")

        ang = swiss_angles(dt_utc, lat, lon, hsys)
        asc, mc = ang["ASC"], ang["MC"]
        day = is_daytime(dt_utc, lat, lon)
        branch = "day" if day else "night"

        feed["objects"].extend([
            {"id": f"ASC@{name}", "targetname": f"ASC ({name})",
             "datetime_utc": gen_time, "ecl_lon_deg": asc, "source": "swiss"},
            {"id": f"MC@{name}", "targetname": f"MC ({name})",
             "datetime_utc": gen_time, "ecl_lon_deg": mc, "source": "swiss"},
            {"id": f"Houses@{name}", "targetname": f"Houses ({name})",
             "datetime_utc": gen_time, "houses_deg": ang["houses"], "source": "swiss"}
        ])

        for part in parts_cfg.get("parts", []):
            formula = part.get("formula_day") if day else part.get("formula_night")
            val = eval_formula(formula, {"ASC":asc, "Sun":sun, "Moon":moon, "MC":mc})
            if val is None: continue
            feed["objects"].append({
                "id": part.get("output_id_pattern", f"{part.get('label','Part')}@{{name}}").format(name=name),
                "targetname": f"{part.get('label','Part')} ({name})",
                "datetime_utc": gen_time,
                "ecl_lon_deg": val,
                "branch": branch,
                "source": "swiss+config" if args.config else "swiss+legacy"
            })

    open(args.out, "w", encoding="utf-8").write(json.dumps(feed, indent=2))
    print(f"[OK] angles + parts added -> {args.out}")


if __name__ == "__main__":
    main()
