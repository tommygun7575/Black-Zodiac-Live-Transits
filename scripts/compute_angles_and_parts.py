#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
compute_angles_and_parts.py — add ASC/MC/houses (Swiss) + Arabic Parts

Robust body lookup (by id or targetname) so it never misses Sun/Moon
if JPL changes labels.

Usage:
  python scripts/compute_angles_and_parts.py --feed docs/feed_now.json --targets config/targets.json --out docs/feed_now.json
"""

import json, sys, argparse, pathlib
from datetime import datetime, timezone
from dateutil import parser as dtparse

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

def get_body_lon_from_feed(feed, want: str):
    want = canonicalize(want)
    want_id = {"Sun":"10","Moon":"301"}.get(want)
    for obj in feed.get("objects", []):
        tid = str(obj.get("id",""))
        tname = str(obj.get("targetname",""))
        if tid == (want_id or "") or tname.startswith(want):
            val = obj.get("ecl_lon_deg")
            if isinstance(val, (int,float)): return float(val)
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
    if not gen: print("[ERROR] feed missing generated_at_utc", file=sys.stderr); sys.exit(1)
    dt_utc = dtparse.isoparse(gen).astimezone(timezone.utc).replace(tzinfo=None)

    sun = get_body_lon_from_feed(feed, "Sun")
    moon = get_body_lon_from_feed(feed, "Moon")
    if sun is None or moon is None:
        print("[ERROR] feed missing Sun and/or Moon longitudes", file=sys.stderr)
        # helpful dump
        for o in feed.get("objects", []):
            if o.get("id") in ("10","301") or str(o.get("targetname","")).startswith(("Sun","Moon")):
                print("[DEBUG]", o, file=sys.stderr)
        sys.exit(1)

    for t in targets:
        name=t["name"]; lat=float(t["lat"]); lon=float(t["lon"]); hsys=t.get("house_system", args.house_system)
        try:
            ang = swiss_angles(dt_utc, lat, lon, hsys)
            day = is_daytime(dt_utc, lat, lon, hsys, sun)
            asc, mc = ang["ASC_deg"], ang["MC_deg"]
            pof = part_fortune(asc, sun, moon, day)
            pos = part_spirit(asc, sun, moon, day)

            ts = dt_utc.isoformat() + "Z"
            append_obj(feed, {"id": f"ASC@{name}", "targetname": f"ASC ({name})", "datetime_utc": ts, "ecl_lon_deg": asc, "notes": {"system": hsys, "provider": "swiss_ephemeris"}})
            append_obj(feed, {"id": f"MC@{name}",  "targetname": f"MC ({name})",  "datetime_utc": ts, "ecl_lon_deg": mc,  "notes": {"system": hsys, "provider": "swiss_ephemeris"}})
            append_obj(feed, {"id": f"Houses@{name}", "targetname": f"Houses ({name})", "datetime_utc": ts, "houses_deg": ang["houses_deg"][1:], "notes": {"system": hsys, "provider": "swiss_ephemeris"}})

            branch = "day" if day else "night"
            append_obj(feed, {"id": f"PartOfFortune@{name}", "targetname": f"Pars Fortuna ({name})", "datetime_utc": ts, "ecl_lon_deg": pof, "branch": branch, "source_tags": {"longitudes":"jpl","angles":"swiss"}})
            append_obj(feed, {"id": f"PartOfSpirit@{name}",  "targetname": f"Pars Spiritus ({name})", "datetime_utc": ts, "ecl_lon_deg": pos, "branch": branch, "source_tags": {"longitudes":"jpl","angles":"swiss"}})
        except Exception as e:
            append_obj(feed, {"id": f"AnglesAndParts@{name}", "error": f"angles/parts compute failed: {e}"})

    feed["source_tags"] = {"longitudes":"jpl_horizons","angles":"swiss_ephemeris"}
    save_json(args.out, feed)
    print("[OK] Angles + Arabic Parts updated:", args.out)

if __name__ == "__main__":
    main()
