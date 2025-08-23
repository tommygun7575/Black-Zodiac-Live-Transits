#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_transits.py — Build the live transit feed (planets + asteroids/TNOs + stars).
- JPL Horizons (preferred) + Swiss fallback
- Augmented with fallback JSON for asteroids/TNOs
- Normalized schema: id, targetname, ecl_lon_deg, ecl_lat_deg, source
"""

import argparse, json, re
from pathlib import Path
from datetime import datetime
from astroquery.jplhorizons import Horizons
import swisseph as swe

FALLBACK_PATH = "aug_2025_to_feb_2026_asteroids_tnos_flat.json"
LOCATION = "500@399"  # geocentric Earth

ASTEROIDS_TNOS = {
    "Vesta": 4, "Psyche": 16, "Amor": 1221, "Eros": 433,
    "Sappho": 80, "Karma": 3811, "Chariklo": 10199, "Pholus": 5145,
    "Eris": 136199, "Sedna": 90377, "Haumea": 136108, "Makemake": 136472,
    "Varuna": 20000, "Ixion": 28978, "Typhon": 42355, "Salacia": 120347
}

# Planets + Chiron
_SWE_MAJOR = {
    "10": swe.SUN, "301": swe.MOON, "199": swe.MERCURY, "299": swe.VENUS,
    "499": swe.MARS, "599": swe.JUPITER, "699": swe.SATURN,
    "799": swe.URANUS, "899": swe.NEPTUNE, "999": swe.PLUTO,
    "2060": swe.CHIRON
}

def jd_ut(dt):
    return swe.julday(dt.year, dt.month, dt.day,
                      dt.hour + dt.minute/60 + dt.second/3600.0)

def horizons_lonlat(eid, epoch):
    try:
        h = Horizons(id=eid, location=LOCATION, epochs=epoch)
        eph = h.ephemerides(quantities="1")
        return float(eph["EclLon"][0]), float(eph["EclLat"][0]), "horizons"
    except Exception:
        return None, None, None

def swiss_lonlat(eid, jd):
    try:
        body = _SWE_MAJOR.get(eid, int(eid))
        xx, _ = swe.calc_ut(jd, body)
        return float(xx[0]), float(xx[1]), "swiss"
    except Exception:
        return None, None, None

def parse_fallback(val):
    """Convert '15° 36' → 15.6 (float degrees)."""
    if val is None: return None
    if isinstance(val, (int, float)): return float(val)
    if isinstance(val, str):
        m = re.match(r"(\d+)[°:\s](\d+)", val)
        if m:
            deg, mins = map(float, m.groups())
            return deg + mins/60.0
        try: return float(val)
        except: return None
    return None

def load_fallback():
    try:
        fb = json.loads(Path(FALLBACK_PATH).read_text())
        # Normalize values on load
        for row in fb["data"]:
            for k,v in list(row.items()):
                if k != "date":
                    row[k] = parse_fallback(v)
        return {row["date"]: row for row in fb["data"]}
    except Exception:
        return {}

def normalize(id_, name, lon, lat, src):
    return {
        "id": id_, "targetname": name,
        "ecl_lon_deg": float(lon) if lon is not None else None,
        "ecl_lat_deg": float(lat) if lat is not None else 0.0,
        "source": src or "unknown"
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    now = datetime.utcnow()
    epoch = now.strftime("%Y-%m-%d %H:%M")
    jd = jd_ut(now)
    date_key = now.strftime("%Y-%m-%d")
    fallback = load_fallback()

    feed = {
        "generated_at_utc": now.isoformat()+"Z",
        "observer": "geocentric Earth",
        "source": "JPL Horizons + Swiss + fallback JSON",
        "objects": []
    }

    # Planets + Chiron
    for p in cfg["planets"]:
        eid, label = str(p["id"]), p["label"]
        lon, lat, src = horizons_lonlat(eid, epoch)
        if lon is None or eid == "2060":  # Force Swiss for Chiron
            lon, lat, src = swiss_lonlat(eid, jd)
        feed["objects"].append(normalize(eid, label, lon, lat, src))

    # Asteroids/TNOs
    for name,num in ASTEROIDS_TNOS.items():
        lon, lat, src = swiss_lonlat(str(num), jd)
        if lon is not None:
            feed["objects"].append(normalize(str(num), name, lon, lat, src))
        elif date_key in fallback and name in fallback[date_key]:
            val = fallback[date_key][name]
            feed["objects"].append(normalize(name, name, val, 0.0, "fallback-json"))
        else:
            feed["objects"].append(normalize(name, name, None, 0.0, "missing"))

    # Fixed stars
    for star in cfg["fixed_stars"]:
        feed["objects"].append(normalize(star["id"], star["label"],
            star["ra_deg"], star["dec_deg"], "fixed"))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(feed, indent=2))
    print(f"[OK] wrote {args.out} with {len(feed['objects'])} objects")

if __name__=="__main__":
    main()
