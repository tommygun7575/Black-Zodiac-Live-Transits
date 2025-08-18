#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
compute_angles_and_parts.py — Add ASC/MC/houses (Swiss) + Arabic Parts

- Uses config/live_config.json for arabic_parts definitions
- Robust Sun/Moon lookup (by id or name, fallback RA/Dec)
- Day/night via Sun altitude (Swiss RA/Dec)
"""

import json, sys, argparse, pathlib, math
from datetime import datetime, timezone
from dateutil import parser as dtparse

from astropy.coordinates import SkyCoord, FK5, GeocentricTrueEcliptic
from astropy.time import Time
import astropy.units as u

try:
    import swisseph as swe
except Exception as e:
    print(f"[FATAL] pyswisseph not available: {e}", file=sys.stderr)
    sys.exit(2)

# ---------------- Helpers ---------------- #

def norm360(x): return float(x % 360.0)

def _to_float(v):
    if isinstance(v, (int, float)): return float(v)
    if isinstance(v, str):
        try: return float(v.strip())
        except: return None
    return None

def _ecliptic_from_ra_dec(obj, obstime_iso: str | None):
    ra = _to_float(obj.get("ra_deg")); dec = _to_float(obj.get("dec_deg"))
    if ra is None or dec is None: return None
    t = Time(obstime_iso) if obstime_iso else Time.now()
    c = SkyCoord(ra=ra*u.deg, dec=dec*u.deg, frame=FK5(equinox="J2000"))
    ecl = c.transform_to(GeocentricTrueEcliptic(obstime=t))
    return float(ecl.lon.to(u.deg).value)

def get_body_lon_from_feed(feed, want_id_or_name, gen_time):
    for obj in feed.get("objects", []):
        if str(obj.get("id")) == str(want_id_or_name) or str(obj.get("targetname")) == str(want_id_or_name):
            lon = _to_float(obj.get("ecl_lon_deg"))
            if lon is not None: return lon
            lon = _ecliptic_from_ra_dec(obj, gen_time)
            if lon is not None: return lon
    return None

def julday(dt_utc): 
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day,
                      dt_utc.hour + dt_utc.minute/60 + dt_utc.second/3600.0)

def swiss_angles(dt_utc, lat, lon, hsys="P"):
    jd_ut = julday(dt_utc)
    swe.set_ephe_path(str(pathlib.Path(".eph").resolve()))
    cusps, ascmc = swe.houses(jd_ut, lat, lon, hsys.encode("ascii"))
    return {"ASC": norm360(ascmc[0]), "MC": norm360(ascmc[1]), "houses": [norm360(c) for c in cusps[1:13]]}

def is_daytime(dt_utc, lat_deg, lon_deg):
    jd_ut = julday(dt_utc)
    xx, _ = swe.calc_ut(jd_ut, swe.SUN, swe.FLG_SWIEPH | swe.FLG_EQUATORIAL)
    ra_deg, dec_deg = xx[0], xx[1]
    lst_hours = swe.sidtime(jd_ut)
    lst_local_deg = (lst_hours * 15.0 + lon_deg) % 360.0
    ha_deg = (lst_local_deg - ra_deg) % 360.0
    if ha_deg > 180.0: ha_deg -= 360.0
    alt = math.degrees(math.asin(
        math.sin(math.radians(lat_deg))*math.sin(math.radians(dec_deg)) +
        math.cos(math.radians(lat_deg))*math.cos(math.radians(dec_deg))*math.cos(math.radians(ha_deg))
    ))
    return alt > 0.0

def eval_formula(formula: str, mapping: dict) -> float | None:
    try:
        expr = formula
        for k,v in mapping.items():
            expr = expr.replace(k, f"({v})")
        return norm360(eval(expr))
    except Exception as e:
        print(f"[WARN] Formula eval failed '{formula}': {e}", file=sys.stderr)
        return None

def load_json(p): return json.load(open(p,"r",encoding="utf-8"))
def save_json(p,d): json.dump(d, open(p,"w",encoding="utf-8"), ensure_ascii=False, indent=2)

# ---------------- Main ---------------- #

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", required=True)
    ap.add_argument("--config", required=True)   # live_config.json
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    feed = load_json(args.feed)
    cfg = load_json(args.config)

    gen_time = feed.get("generated_at_utc") or feed.get("datetime_utc")
    if not gen_time:
        print("[ERROR] feed missing generated_at_utc", file=sys.stderr)
        sys.exit(1)
    dt_utc = dtparse.isoparse(gen_time).astimezone(timezone.utc).replace(tzinfo=None)

    # Base Sun/Moon longitudes
    sun = get_body_lon_from_feed(feed, "10", gen_time)
    moon = get_body_lon_from_feed(feed, "301", gen_time)

    for t in cfg.get("targets", []):
        name, lat, lon = t["name"], float(t["lat"]), float(t["lon"])
        hsys = t.get("house_system", "P")

        ang = swiss_angles(dt_utc, lat, lon, hsys)
        asc, mc = ang["ASC"], ang["MC"]
        day = is_daytime(dt_utc, lat, lon)
        branch = "day" if day else "night"

        # Always append ASC/MC/Houses
        feed.setdefault("objects", []).extend([
            {"id": f"ASC@{name}", "targetname": f"ASC ({name})", "datetime_utc": gen_time, "ecl_lon_deg": asc, "source": "swiss"},
            {"id": f"MC@{name}", "targetname": f"MC ({name})", "dat
