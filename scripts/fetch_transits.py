#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
fetch_transits.py — build docs/feed_now.json from config/live_config.json

Hardens JPL pulls with retries and guarantees Sun (10) and Moon (301)
exist with ecliptic longitudes before writing the feed.

Usage:
  python scripts/fetch_transits.py --config config/live_config.json --out docs/feed_now.json
"""

from __future__ import annotations
import json, sys, argparse, time, datetime
from typing import Any, Dict, List

from astropy.time import Time
from astropy.coordinates import SkyCoord, FK5, GeocentricTrueEcliptic
import astropy.units as u
from astroquery.jplhorizons import Horizons

MAJOR_IDS = {"10","199","299","399","499","599","699","799","899","999","1","2","4","5"}

def now_utc_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def horizons_once(target_id: str | int, epoch_jd: float) -> Dict[str, Any]:
    id_str = str(target_id)
    if id_str == "399":
        return {"id": "399", "error": "skipped: observer equals target (Horizons disallows this request)."}
    id_type = "majorbody" if id_str in MAJOR_IDS else "smallbody"
    obj = Horizons(id=id_str, id_type=id_type, location="500@399", epochs=epoch_jd)
    eph = obj.ephemerides(extra_precision=True)
    return {
        "id": id_str,
        "targetname": f"{eph['targetname'][0]}",
        "datetime_utc": Time(eph['datetime_jd'][0], format="jd").utc.isot,
        "jd": float(eph['datetime_jd'][0]),
        "ecl_lon_deg": float(eph['EclLon'][0]),
        "ecl_lat_deg": float(eph['EclLat'][0]),
        "ra_deg": float(eph['RA'][0]),
        "dec_deg": float(eph['DEC'][0]),
        "delta_au": float(eph['delta'][0]),
        "r_au": float(eph['r'][0]),
        "elong_deg": float(eph['elong'][0]),
        "phase_angle_deg": float(eph['alpha'][0]),
        "constellation": None
    }

def horizons_safe_with_retry(target_id: str | int, epoch_jd: float, tries: int = 3, sleep_s: float = 2.0) -> Dict[str, Any]:
    err = None
    for i in range(tries):
        try:
            return horizons_once(target_id, epoch_jd)
        except Exception as e:
            err = e
            time.sleep(sleep_s)
    return {"id": str(target_id), "error": f"horizons query failed after {tries} tries: {err}"}

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

    # majors
    for p in cfg.get("planets", []):
        feed["objects"].append(horizons_safe_with_retry(p["id"], epoch_jd))

    # barycenters
    for b in cfg.get("barycenters", []):
        if b.get("enabled", True):
            feed["objects"].append(horizons_safe_with_retry(b["id"], epoch_jd))

    # minors
    for mb in cfg.get("minor_bodies", []):
        feed["objects"].append(horizons_safe_with_retry(mb, epoch_jd))

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

    # Tags
    feed["source_tags"] = {"longitudes": "jpl_horizons", "angles": "swiss_ephemeris (next step)"}
    feed["config_used"] = {"ephemeris": cfg.get("ephemeris", {}), "options": cfg.get("options", {})}
    return feed

def require_sun_moon(feed: Dict[str, Any]) -> None:
    """Fail fast if Sun/Moon are missing or malformed."""
    sun = None
    moon = None
    for obj in feed.get("objects", []):
        if obj.get("id") == "10" or str(obj.get("targetname","")).startswith("Sun"):
            sun = obj
        if obj.get("id") == "301" or str(obj.get("targetname","")).startswith("Moon"):
            moon = obj
    problems = []
    if not sun or "ecl_lon_deg" not in (sun or {}):
        problems.append("Sun (10)")
    if not moon or "ecl_lon_deg" not in (moon or {}):
        problems.append("Moon (301)")
    if problems:
        raise SystemExit(f"[FATAL] Missing ecliptic longitude for: {', '.join(problems)}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/live_config.json")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    out_path = args.out or cfg.get("options", {}).get("output", {}).get("feed_now",
