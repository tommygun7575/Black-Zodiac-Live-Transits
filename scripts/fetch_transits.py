#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
fetch_transits.py — build docs/feed_now.json from config/live_config.json

- Uses JPL Horizons via astroquery for longitudes.
- Ensures Sun (10) and Moon (301) resolve as MAJOR BODIES (no asteroid 301 Bavaria).
- If Horizons ever returns NaN EclLon (rare), fall back to RA/DEC -> ecliptic conversion.
"""

from __future__ import annotations
import json, sys, argparse, time, datetime, os, math
from typing import Any, Dict

from astropy.time import Time
from astropy.coordinates import SkyCoord, FK5, GeocentricTrueEcliptic
import astropy.units as u
from astroquery.jplhorizons import Horizons
import numpy as np

# include 301 so Moon is NOT treated as an asteroid
MAJOR_IDS = {"10","301","199","299","399","499","599","699","799","899","999","1","2","4","5"}

def now_utc_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def _ecl_from_radec(ra_deg: float, dec_deg: float, jd: float) -> float:
    t = Time(jd, format="jd")
    c = SkyCoord(ra=ra_deg*u.deg, dec=dec_deg*u.deg, frame=FK5(equinox="J2000"))
    ecl = c.transform_to(GeocentricTrueEcliptic(obstime=t))
    return float(ecl.lon.to(u.deg).value)

def horizons_once(target_id: str | int, epoch_jd: float) -> Dict[str, Any]:
    tid = str(target_id)
    if tid == "399":
        return {"id": "399", "error": "skipped: observer equals target (Horizons disallows this request)."}

    id_type = "majorbody" if tid in MAJOR_IDS else "smallbody"
    obj = Horizons(id=tid, id_type=id_type, location="500@399", epochs=epoch_jd)
    eph = obj.ephemerides(extra_precision=True)

    jd = float(eph['datetime_jd'][0])
    ecl_lon = float(eph['EclLon'][0]) if not np.isnan(eph['EclLon'][0]) else None
    ecl_lat = float(eph['EclLat'][0]) if not np.isnan(eph['EclLat'][0]) else None
    ra = float(eph['RA'][0]); dec = float(eph['DEC'][0])

    # fallback: if EclLon is NaN (seen for Sun occasionally), derive from RA/DEC
    if ecl_lon is None:
        try:
            ecl_lon = _ecl_from_radec(ra, dec, jd)
        except Exception:
            pass

    rec = {
        "id": tid,
        "targetname": f"{eph['targetname'][0]}",
        "datetime_utc": Time(jd, format="jd").utc.isot,
        "jd": jd,
        "ecl_lon_deg": ecl_lon if ecl_lon is not None else float("nan"),
        "ecl_lat_deg": ecl_lat if ecl_lat is not None else float("nan"),
        "ra_deg": ra,
        "dec_deg": dec,
        "delta_au": float(eph['delta'][0]),
        "r_au": float(eph['r'][0]),
        "elong_deg": float(eph['elong'][0]),
        "phase_angle_deg": float(eph['alpha'][0]),
        "constellation": None
    }
    return rec

def horizons_retry(target_id: str | int, epoch_jd: float, tries: int = 3, sleep_s: float = 2.0) -> Dict[str, Any]:
    last_err = None
    for _ in range(tries):
        try:
            return horizons_once(target_id, epoch_jd)
        except Exception as e:
            last_err = e
            time.sleep(sleep_s)
    return {"id": str(target_id), "error": f"horizons query failed after {tries} tries: {last_err}"}

def star_ra_dec_to_ecl_lon(ra_deg: float, dec_deg: float, obstime: Time) -> float:
    coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame=FK5(equinox="J2000"))
    ecl = coord.transform_to(GeocentricTrueEcliptic(obstime=obstime))
    return float(ecl.lon.to(u.deg).value)

def build_feed(cfg: Dict[str, Any]) -> Dict[str, Any]:
    t = Time.now()
    epoch_jd = float(t.jd)

    feed: Dict[str, Any] = {
        "generated_at_utc": now_utc_iso(),
        "observer": "geocentric (Earth center)",
        "refplane": "earth",
        "source": "JPL Horizons via astroquery + fixed stars (astropy)",
        "objects": []
    }

    # planets
    for p in cfg.get("planets", []):
        feed["objects"].append(horizons_retry(p["id"], epoch_jd))

    # barycenters
    for b in cfg.get("barycenters", []):
        if b.get("enabled", True):
            feed["objects"].append(horizons_retry(b["id"], epoch_jd))

    # minor bodies
    for mb in cfg.get("minor_bodies", []):
        feed["objects"].append(horizons_retry(mb, epoch_jd))

    # fixed stars
    for star in cfg.get("fixed_stars", []):
        try:
            lon = star_ra_dec_to_ecl_lon(float(star["ra_deg"]), float(star["dec_deg"]), t)
            feed["objects"].append({
                "id": str(star["id"]),
                "targetname": star.get("label", str(star["id"])),
                "datetime_utc": feed["generated_at_utc"],
                "jd": None,
                "ecl_lon_deg": lon,
                "ecl_lat_deg": None,
                "ra_deg": float(star["ra_deg"]),
                "dec_deg": float(star["dec_deg"]),
                "delta_au": None,
                "r_au": None,
                "elong_deg": None,
                "phase_angle_deg": None,
                "constellation": None
            })
        except Exception as e:
            feed["objects"].append({"id": str(star.get("id","star")), "error": f"fixed star conversion failed: {e}"})

    # provenance
    feed["source_tags"] = {"longitudes": "jpl_horizons", "angles": "swiss_ephemeris (next step)"}
    feed["config_used"] = {"ephemeris": cfg.get("ephemeris", {}), "options": cfg.get("options", {})}
    return feed

def require_sun_moon(feed: Dict[str, Any]) -> None:
    sun, moon = None, None
    for obj in feed.get("objects", []):
        tid = str(obj.get("id",""))
        name = str(obj.get("targetname",""))
        if tid == "10" or name.startswith("Sun"):
            sun = obj
        if tid == "301" or name.startswith("Moon"):
            moon = obj
    missing = []
    if not sun or (sun.get("ecl_lon_deg") is None or (isinstance(sun.get("ecl_lon_deg"), float) and math.isnan(sun.get("ecl_lon_deg")))):
        missing.append("Sun (10)")
    if not moon or (moon.get("ecl_lon_deg") is None or (isinstance(moon.get("ecl_lon_deg"), float) and math.isnan(moon.get("ecl_lon_deg")))):
        missing.append("Moon (301)")
    if missing:
        raise SystemExit(f"[FATAL] Missing ecliptic longitude for: {', '.join(missing)}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/live_config.json")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    out_path = args.out
    if not out_path:
        options = cfg.get("options", {})
        output_block = options.get("output", {})
        out_path = output_block.get("feed_now", "docs/feed_now.json")

    feed = build_feed(cfg)
    require_sun_moon(feed)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=2)

    print(f"[OK] wrote {out_path}")

if __name__ == "__main__":
    main()
