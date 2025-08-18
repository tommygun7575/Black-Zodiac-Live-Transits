#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
compute_angles_and_parts.py — add ASC/MC/houses (Swiss) + Arabic Parts

- Robust Sun/Moon lookup (by id or name)
- Accepts numeric or string longitudes
- If ecliptic longitude missing, derives from RA/DEC (astropy)
- Day/night via Sun altitude (sidereal time + RA/Dec) — no house_pos()
"""

import json, sys, argparse, pathlib, math
from datetime import datetime, timezone
from dateutil import parser as dtparse

# Fallback RA/DEC -> ecliptic conversion
from astropy.coordinates import SkyCoord, FK5, GeocentricTrueEcliptic
from astropy.time import Time
import astropy.units as u

try:
    import swisseph as swe
except Exception as e:
    print(f"[FATAL] pyswisseph not available: {e}", file=sys.stderr)
    sys.exit(2)

# ---------- helpers

def norm360(x: float) -> float:
    x = x % 360.0
    return x if x >= 0 else x + 360.0

ALIASES = {"asc": "ASC", "ascendant": "ASC", "mc": "MC", "sun": "Sun", "moon": "Moon"}

def canonicalize(name: str) -> str:
    return ALIASES.get(str(name).strip().lower(), name)

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

def get_body_lon_from_feed(feed: dict, want: str):
    """Return ecliptic longitude for Sun/Moon; fallback to RA/DEC if needed."""
    want = canonicalize(want)
    want_id = {"Sun": "10", "Moon": "301"}.get(want)
    gen_time = feed.get("generated_at_utc") or feed.get("datetime_utc")

    # gather candidates
    cands = []
    for obj in feed.get("objects", []):
        tid = str(obj.get("id", ""))
        tname = str(obj.get("targetname", ""))
        if tid == (want_id or "") or tname.startswith(want):
            cands.append(obj)

    if not cands:
        return None

    # prefer direct ecliptic
    for obj in cands:
        lon = _to_float(obj.get("ecl_lon_deg"))
        if lon is not None: return lon

    # fallback from RA/DEC
    for obj in cands:
        lon = _ecliptic_from_ra_dec(obj, gen_time)
        if lon is not None: return lon

    return None

def julday(dt_utc: datetime) -> float:
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day,
                      dt_utc.hour + dt_utc.minute/60 + dt_utc.second/3600.0)

def swiss_angles(dt_utc: datetime, lat: float, lon: float, hsys: str = "P"):
    jd_ut = julday(dt_utc)
    swe.set_ephe_path(str(pathlib.Path(".eph").resolve()))
    cusps, ascmc = swe.houses(jd_ut, lat, lon, hsys.encode("ascii"))
    return {
        "ASC_deg": norm360(ascmc[0]),
        "MC_deg":  norm360(ascmc[1]),
        "houses_deg": [None] + [norm360(c) for c in cusps[1:13]]
    }

def is_daytime(dt_utc: datetime, lat_deg: float, lon_deg: float) -> bool:
    """
    True if Sun altitude > 0° (above horizon) at given UTC, lat, lon.
    Uses sidereal time + Sun RA/Dec from Swiss Ephemeris.
    """
    jd_ut = julday(dt_utc)

    # Sun RA/Dec (apparent, equatorial)
    flags = swe.FLG_SWIEPH | swe.FLG_EQUATORIAL
    xx, _ = swe.calc_ut(jd_ut, swe.SUN, flags)
    ra_deg, dec_deg = xx[0], xx[1]  # RA, Dec in degrees

    # Local sidereal time in degrees (sidtime returns hours)
    lst_hours = swe.sidtime(jd_ut)  # Greenwich sidereal time (hours)
    lst_local_deg = (lst_hours * 15.0 + lon_deg) % 360.0

    # Hour angle (degrees)
    ha_deg = (lst_local_deg - ra_deg) % 360.0
    if ha_deg > 180.0:
        ha_deg -= 360.0  # range (-180, 180]

    # Altitude
    lat_rad = math.radians(lat_deg)
    dec_rad = math.radians(dec_deg)
    ha_rad  = math.radians(ha_deg)
    sin_alt = math.sin(lat_rad)*math.sin(dec_rad) + math.cos(lat_rad)*math.cos(dec_rad)*math.cos(ha_rad)
    alt_deg = math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))
    return alt_deg > 0.0

def part_fortune(asc, sun, moon, day):  # Fortune
    return norm360(asc + (moon - sun) if day else asc + (sun - moon))

def part_spirit(asc, sun, moon, day):   # Spirit
    return norm360(asc + (sun - moon) if day else asc + (moon - sun))

def load_json(p):  return json.load(open(p, "r", encoding="utf-8"))
def save_json(p, d): json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
def append_obj(feed, obj): feed.setdefault("objects", []).append(obj)

# ---------- main

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
        print("[ERROR] feed missing generated_at_utc", file=sys.stderr)
        sys.exit(1)
    dt_utc = dtparse.isoparse(gen).astimezone(timezone.utc).replace(tzinfo=None)

    sun = get_body_lon_from_feed(feed, "Sun")
    moon = get_body_lon_from_feed(feed, "Moon")
    if sun is None or moon is None:
        print("[ERROR] feed missing Sun and/or Moon longitudes", file=sys.stderr)
        for o in feed.get("objects", []):
            if o.get("id") in ("10", "301") or str(o.get("targetname", "")).startswith(("Sun", "Moon")):
                print("[DEBUG candidate]", json.dumps(o)[:1000], file=sys.stderr)
        sys.exit(1)

    for t in targets:
        name = t["name"]; lat = float(t["lat"]); lon = float(t["lon"])
        hsys = t.get("house_system", args.house_system)

        ang = swiss_angles(dt_utc, lat, lon, hsys)
        day = is_daytime(dt_utc, lat, lon)

        asc, mc = ang["ASC_deg"], ang["MC_deg"]
        pof = part_fortune(asc, sun, moon, day)
        pos = part_spirit(asc, sun, moon, day)

        ts = dt_utc.isoformat() + "Z"
        append_obj(feed, {"id": f"ASC@{name}", "targetname": f"ASC ({name})",
                          "datetime_utc": ts, "ecl_lon_deg": asc,
                          "notes": {"system": hsys, "provider": "swiss_ephemeris"}})
        append_obj(feed, {"id": f"MC@{name}", "targetname": f"MC ({name})",
                          "datetime_utc": ts, "ecl_lon_deg": mc,
                          "notes": {"system": hsys, "provider": "swiss_ephemeris"}})
        append_obj(feed, {"id": f"Houses@{name}", "targetname": f"Houses ({name})",
                          "datetime_utc": ts, "houses_deg": ang["houses_deg"][1:],
                          "notes": {"system": hsys, "provider": "swiss_ephemeris"}})

        branch = "day" if day else "night"
        append_obj(feed, {"id": f"PartOfFortune@{name}", "targetname": f"Pars Fortuna ({name})",
                          "datetime_utc": ts, "ecl_lon_deg": pof, "branch": branch,
                          "source_tags": {"longitudes": "jpl", "angles": "swiss"}})
        append_obj(feed, {"id": f"PartOfSpirit@{name}", "targetname": f"Pars Spiritus ({name})",
                          "datetime_utc": ts, "ecl_lon_deg": pos, "branch": branch,
                          "source_tags": {"longitudes": "jpl", "angles": "swiss"}})

    feed["source_tags"] = {"longitudes": "jpl_horizons", "angles": "swiss_ephemeris"}
    save_json(args.out, feed)
    print("[OK] Angles + Arabic Parts updated:", args.out)

if __name__ == "__main__":
    main()
