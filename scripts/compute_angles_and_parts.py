#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
compute_angles_and_parts.py — Add Swiss Angles + Arabic Parts using live_config.json.
Robust Sun/Moon lookup: accepts id int/str, ecl_lon_deg or ecl_lon, or RA/Dec fallback.
"""

import json, sys, argparse, pathlib, math
from datetime import datetime, timezone
from dateutil import parser as dtparse

from astropy.coordinates import SkyCoord, FK5, GeocentricTrueEcliptic
from astropy.time import Time
import astropy.units as u
import swisseph as swe


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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", required=True)
    ap.add_argument("--config", required=True)  # live_config.json
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    feed = json.loads(open(args.feed, "r", encoding="utf-8").read())
    cfg  = json.loads(open(args.config, "r", encoding="utf-8").read())

    gen_time = feed.get("generated_at_utc") or feed.get("datetime_utc")
    if not gen_time:
        print("[ERROR] feed missing generated_at_utc", file=sys.stderr)
        sys.exit(1)
    dt_utc = dtparse.isoparse(gen_time).astimezone(timezone.utc).replace(tzinfo=None)

    # Robust Sun/Moon
    sun  = find_lon(feed, {"10","Sun"}, gen_time)
    moon = find_lon(feed, {"301","Moon"}, gen_time)
    if sun is None or moon is None:
        print("[ERROR] feed missing Sun/Moon", file=sys.stderr)
        try:
            preview = json.dumps(feed.get("objects", [])[:5], indent=2)[:800]
            print("[DEBUG objects preview]\n" + preview, file=sys.stderr)
        except: pass
        sys.exit(1)

    # Angles + Arabic Parts for each target
    for t in cfg.get("targets", []):
        name, lat, lon = t["name"], float(t["lat"]), float(t["lon"])
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

        for part in cfg.get("arabic_parts", {}).get("parts", []):
            formula = part.get("formula_day") if day else part.get("formula_night")
            val = eval_formula(formula, {"ASC":asc, "Sun":sun, "Moon":moon, "MC":mc})
            if val is None: continue
            feed["objects"].append({
                "id": part["output_id_pattern"].format(name=name),
                "targetname": f"{part['label']} ({name})",
                "datetime_utc": gen_time,
                "ecl_lon_deg": val,
                "branch": branch,
                "source": "swiss+config"
            })

    open(args.out, "w", encoding="utf-8").write(json.dumps(feed, indent=2))
    print(f"[OK] angles + parts added -> {args.out}")


if __name__ == "__main__":
    main()
