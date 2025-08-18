#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_transits.py — Build the live transit feed.

- Reads planets, barycenters, minor bodies, and fixed stars from config/live_config.json
- Tries JPL Horizons first for ecliptic long/lat
- Falls back to Swiss Ephemeris for MAJOR bodies so Sun/Moon never missing
- Writes ecl_lon_deg / ecl_lat_deg keys (consistent with downstream scripts)
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
from astroquery.jplhorizons import Horizons
import swisseph as swe


# ---------------------------- utilities ----------------------------

def jd_ut(dt: datetime) -> float:
    """Julian day (UT) for a naive UTC datetime."""
    return swe.julday(
        dt.year, dt.month, dt.day,
        dt.hour + dt.minute / 60.0 + dt.second / 3600.0
    )


def horizons_lonlat(obj_id: str, epoch_str: str):
    """
    Query JPL Horizons for ecliptic longitude/latitude at epoch_str.
    Returns (lon_deg, lat_deg, "horizons") or (None, None, None).
    """
    try:
        # 500@399 = geocentric Earth
        h = Horizons(id=obj_id, id_type=None, location="500@399", epochs=epoch_str)
        # quantities="1" includes EclLon/EclLat columns (note capitalization)
        eph = h.ephemerides(quantities="1")
        lon = float(eph["EclLon"][0])
        lat = float(eph["EclLat"][0])
        return lon, lat, "horizons"
    except Exception as e:
        print(f"[WARN] Horizons failed for {obj_id}: {e}", file=sys.stderr)
        return None, None, None


# Swiss constants map for majors
_SWE_MAJOR = {
    "10": swe.SUN,
    "301": swe.MOON,
    "199": swe.MERCURY,
    "299": swe.VENUS,
    "499": swe.MARS,
    "599": swe.JUPITER,
    "699": swe.SATURN,
    "799": swe.URANUS,
    "899": swe.NEPTUNE,
    "999": swe.PLUTO,
}


def swiss_lonlat_major(eid: str, jd: float):
    """
    Swiss fallback for major bodies (Sun..Pluto, optional Chiron).
    Returns (lon_deg, lat_deg, "swiss") or (None, None, None).
    """
    try:
        if eid == "2060":  # Chiron if requested as 'planet'
            body = getattr(swe, "CHIRON", None)
            if body is None:
                # Some builds miss CHIRON; skip gracefully
                return None, None, None
        else:
            body = _SWE_MAJOR.get(eid)

        if body is None:
            return None, None, None

        xx, _ = swe.calc_ut(jd, int(body))
        lon, lat = float(xx[0]), float(xx[1])
        return lon, lat, "swiss"
    except Exception as e:
        print(f"[WARN] Swiss failed for {eid}: {e}", file=sys.stderr)
        return None, None, None


def to_str_id(v) -> str:
    return str(v)


# ---------------------------- main ----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to config/live_config.json")
    ap.add_argument("--out", required=True, help="Path to write docs/feed_now.json")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    out_path = Path(args.out)

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    now = datetime.utcnow()
    epoch_str = now.strftime("%Y-%m-%d %H:%M")
    jd = jd_ut(now)

    feed = {
        "generated_at_utc": now.isoformat() + "Z",
        "observer": "geocentric Earth",
        "source": "JPL Horizons (fallback: Swiss for majors)",
        "objects": []
    }

    # ---------- Planets (with Swiss fallback to guarantee Sun/Moon present)
    for p in cfg.get("planets", []):
        eid = to_str_id(p["id"])
        label = p.get("label", eid)

        lon, lat, src = horizons_lonlat(eid, epoch_str)
        if lon is None or (isinstance(lon, float) and np.isnan(lon)):
            lon, lat, src = swiss_lonlat_major(eid, jd)

        feed["objects"].append({
            "id": eid,
            "targetname": label,
            "ecl_lon_deg": lon,
            "ecl_lat_deg": lat,
            "source": src or "unknown"
        })

    # ---------- Barycenters (Horizons only; include if enabled)
    for b in cfg.get("barycenters", []):
        if not b.get("enabled", True):
            continue
        eid = to_str_id(b["id"])
        label = b.get("label", f"Barycenter {eid}")
        lon, lat, src = horizons_lonlat(eid, epoch_str)
        if lon is None:
            continue
        feed["objects"].append({
            "id": eid,
            "targetname": label,
            "ecl_lon_deg": lon,
            "ecl_lat_deg": lat,
            "source": src
        })

    # ---------- Minor bodies (Horizons only; many won’t be available in Swiss)
    for mb in cfg.get("minor_bodies", []):
        eid = to_str_id(mb)
        lon, lat, src = horizons_lonlat(eid, epoch_str)
        if lon is None:
            continue
        feed["objects"].append({
            "id": eid,
            "targetname": f"MinorBody {eid}",
            "ecl_lon_deg": lon,
            "ecl_lat_deg": lat,
            "source": src
        })

    # ---------- Fixed stars (store RA/Dec; downstream can derive ecliptic if needed)
    for star in cfg.get("fixed_stars", []):
        feed["objects"].append({
            "id": star["id"],
            "targetname": star.get("label", star["id"]),
            "ra_deg": float(star["ra_deg"]),
            "dec_deg": float(star["dec_deg"]),
            "epoch": star.get("epoch", "J2000"),
            "source": "fixed"
        })

    # Write output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(feed, indent=2), encoding="utf-8")
    print(f"[OK] wrote {args.out} with {len(feed['objects'])} objects")


if __name__ == "__main__":
    main()
