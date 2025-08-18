#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
compute_angles_and_parts.py — add ASC/MC/houses (Swiss) + Arabic Parts

Robust Sun/Moon lookup:
- match by id ("10","301") or name prefix ("Sun","Moon")
- accept numeric or string longitudes
- if ecliptic longitude missing, derive from RA/DEC

Usage:
  python scripts/compute_angles_and_parts.py --feed docs/feed_now.json --targets config/targets.json --out docs/feed_now.json
"""

import json, sys, argparse, pathlib
from datetime import datetime, timezone
from dateutil import parser as dtparse

# astropy just for fallback conversion RA/DEC -> ecliptic lon
from astropy.coordinates import SkyCoord, FK5, GeocentricTrueEcliptic
from astropy.time import Time
import astropy.units as u

try:
    import swisseph as swe
except Exception as e:
    print(f"[FATAL] pyswisseph not available: {e}", file=sys.stderr)
    sys.exit(2)

def norm360(x: float) -> float:
    x = x % 360.0
    return x if x >= 0 else x + 360.0

ALIASES = {"asc":"ASC","ascendant":"ASC","mc":"MC","sun":"Sun","moon":"Moon"}

def canonicalize(name: str) -> str:
    return ALIASES.get(name.strip().lower(), name)

def _to_float(val):
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.strip())
        except Exception:
            return None
    return None

def _ecliptic_from_ra_dec(obj, obstime_iso: str):
    ra = _to_float(obj.get("ra_deg"))
    dec = _to_float(obj.get("dec_deg"))
    if ra is None or dec is None:
        return None
    t = Time(obstime_iso) if obstime_iso else Time.now()
    c = SkyCoord(ra=ra*u.deg, dec=dec*u.deg, frame=FK5(equinox="J2000"))
    ecl = c.transform_to(GeocentricTrueEcliptic(obstime=t))
    return float(ecl.lon.to(u.deg).value)

def get_body_lon_from_feed(feed, want: str):
    """Return ecliptic longitude (deg) for Sun/Moon, with fallbacks."""
    want = canonicalize(want)
    want_id = {"Sun":"10","Moon":"301"}.get(want)
    gen_time = feed.get("generated_at_utc") or feed.get("datetime_utc")

    # 1) find matching object(s)
    candidates = []
    for obj in feed.get("objects", []):
        tid = str(obj.get("id",""))
        tname = str(obj.get("targetname",""))
        if tid == (want_id or "") or tname.startswith(want):
            candidates.append(obj)

    if not candidates:
        return None

    # 2) try ecl_lon_deg directly
    for obj in candidates:
        lon = _to_float(obj.get("ecl_lon_deg"))
        if lon is not None:
            return lon

    # 3) derive from RA/DEC if needed
    for obj in candidates:
        lon = _ecliptic_from_ra_dec(obj, gen_time)
        if lon is not None:
            return lon

    return None

def julday(dt_utc: datetime) -> float:
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day,
                      dt_utc.hour + dt_utc.minute/60 + dt_utc.second/3600.0)

def swiss_angles(dt_utc: datetime, lat: float, lon: float, hsys: str = "P"):
    jd_ut = julday(dt_utc)
    swe.set_ephe_path(str(pathlib.Path(".eph").resolve()))
    cusps, ascmc = swe.houses(jd_ut, lat, lon, hsys.encode("ascii"))
    return {"ASC_deg": norm360(ascmc[0]), "MC_deg": norm360(ascmc[1]),
            "houses_deg": [None] + [norm360(c) for c in cusps[1:13]]}

def is_daytime(dt_utc: datetime, lat: float, lon: float, hsys: str, sun_lon: float) -> bool:
    jd_ut = julday(dt_utc)
    h = swe.house_pos(jd_ut, lat, lon, hsys.encode("ascii"), sun_lon, 0.0)
    return 7.0 <= h < 13.0

def part_fortune(asc, sun, moon, day):  return norm360(asc + (moon - sun) if day else asc + (sun - moon))
def part_spirit(asc, sun, moon, day):   return norm360(asc + (sun - moon) if day else asc + (moon - sun))

def load_json(p):  return json.load(open(p,"r",encoding="utf-8"))
def save_json(p,d): json.dump(d, open(p,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
def append_obj(feed,obj): feed.setdefault("objects",[]).append(obj)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", required=True)
    ap.add_argument("--targets", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--house-system", default="P")
    args = ap.parse_args()

    feed = load_json(args.feed)
    targets = load_json(args.targets).get("targets", [])

    gen = feed.get("generated_at_utc") or feed.get("datetime_utc")
    if not gen:
        print("[ERROR] feed missing generated_at_utc", file=sys.stderr); sys.exit(1)
    dt_utc = dtparse.isoparse(gen).astimezone(timezone.utc).replace(tzinfo=None)

    sun = get_body_lon_from_feed(feed, "Sun")
    moon = get_body_lon_from_feed(feed, "Moon")

    if sun is None or moon is None:
        print("[ERROR] feed missing Sun and/or Moon longitudes", file=sys.stderr)
        # helpful dump: show any objects that look like Sun/Moon
        for o in feed.get("objects", []):
            if o.get("id") in ("10","301") or str(o.get("targetname","")).startswith(("Sun","Moon")):
                print("[DEBUG candidate]", json.dumps(o)[:1000], file=sys.stderr)
        sys.exit(1)

    for t in targets:
        name=t["name"]; lat=float(t["lat"]); lon=float(t["lon"]); hsys=t.get("house_system", args.house_system)
        try:
            ang = swiss_angles(dt_utc, lat, lon, hsys)
            day = is_daytime(dt_utc, lat, lon, hsys, sun)
            asc, mc = ang["ASC_deg"], ang["MC_deg"]
            pof = part_fortune(asc, sun, moon, day)
            pos
