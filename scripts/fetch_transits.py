#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_transits.py — fetch planetary transits from JPL Horizons with Swiss Ephemeris fallback
Reads planets/minor_bodies/fixed_stars from config/live_config.json.
Writes docs/feed_now.json using ecl_lon_deg/ecl_lat_deg keys.
"""

import argparse, json, datetime, sys
from pathlib import Path
import numpy as np
from astroquery.jplhorizons import Horizons
import swisseph as swe


def julday(dt: datetime.datetime) -> float:
    return swe.julday(dt.year, dt.month, dt.day,
                      dt.hour + dt.minute/60.0 + dt.second/3600.0)


def fetch_from_horizons(obj_id, epoch):
    """Return (lon, lat, 'horizons') or (None,None,None)."""
    try:
        h = Horizons(id=obj_id, location='500@399', epochs=epoch, id_type=None)
        eph = h.ephemerides(quantities="1")  # includes EclLon/EclLat
        lon = float(eph["EclLon"][0])
        lat = float(eph["EclLat"][0])
        return lon, lat, "horizons"
    except Exception as e:
        print(f"[WARN] Horizons failed for {obj_id}: {e}", file=sys.stderr)
        return None, None, None


def fetch_from_swiss(obj_id_int, jd):
    """Major bodies fallback using Swiss."""
    try:
        xx, _ = swe.calc_ut(jd, obj_id_int)
        return float(xx[0]), float(xx[1]), "swiss"
    except Exception as e:
        print(f"[WARN] Swiss failed for {obj_id_int}: {e}", file=sys.stderr)
        return None, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to live_config.json")
    ap.add_argument("--out", required=True, help="Output feed JSON path")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))

    now = datetime.datetime.utcnow()
    epoch = now.strftime("%Y-%m-%d %H:%M")
    jd = julday(now)

    feed = {
        "generated_at_utc": now.isoformat() + "Z",
        "observer": "geocentric Earth",
        "source": "JPL Horizons (fallback: Swiss)",
        "objects": []
    }

    # Planets
    for p in cfg.get("planets", []):
        eid = str(p["id"]); label = p["label"]
        lon, lat, src = fetch_from_horizons(eid, epoch)
        if lon is None or np.isnan(lon):
            # Map known major body IDs to Swiss constants by numeric code
            swiss_id_map = {
                "10": swe.SUN, "301": swe.MOON, "199": swe.MERCURY, "299": swe.VENUS,
                "499": swe.MARS, "599": swe.JUPITER, "699": swe.SATURN,
                "799": swe.URANUS, "899": swe.NEPTUNE, "999": swe.PLUTO
            }
            if eid == "2060":  # Chiron
                body = getattr(swe, "CHIRON", 15)  # fallback to asteroid 15 if CHIRON missing
            else:
                body = swiss_id_map.get(eid)
            if body is not None:
                lon, lat, src = fetch_from_swiss(int(body), jd)
        feed["objects"].append({
            "id": eid,
            "targetname": label,
            "ecl_lon_deg": lon,
            "ecl_lat_deg": lat,
            "source": src or "unknown"
        })

    # Minor bodies (Horizons only)
    for mb in cfg.get("minor_bodies", []):
        eid = str(mb)
        lon, lat, src = fetch_from_horizons(eid, epoch)
        if lon is None:
            continue
        feed["objects"].append({
            "id": eid,
            "targetname": f"MinorBody {eid}",
            "ecl_lon_deg": lon,
            "ecl_lat_deg": lat,
            "source": src
        })

    # Fixed stars (RA/Dec from config; lon will be derived later if needed)
    for star in cfg.get("fixed_stars", []):
        feed["objects"].append({
            "id": star["id"],
            "targetname": star["label"],
            "ra_deg": float(star["ra_deg"]),
            "dec_deg": float(star["dec_deg"]),
            "epoch": star.get("epoch", "J2000"),
            "source": "fixed"
        })

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(feed, indent=2), encoding="utf-8")
    print(f"[OK] wrote {args.out} with {len(feed['objects'])} objects")


if __name__ == "__main__":
    main()
