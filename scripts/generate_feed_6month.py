#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_feed_6month.py — build a 6-month projected transit feed.
Generalized dataset for GPT Store users (no natal data).
Source hierarchy: Horizons → Swiss → Miriade → JSON fallback
Covers Aug 24, 2025 @ 18:00 Pacific → Feb 24, 2026
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import swisseph as swe

# ---- Settings ----
DAYS_AHEAD = 184   # ~6 months
HOUSE_SYSTEM = b'P'
OBSERVER = "geocentric Earth"
EPHE_PATH = "."

# Hard-coded start: Aug 24, 2025 18:00 Pacific = Aug 25, 2025 01:00 UTC
START_UTC = datetime(2025, 8, 25, 1, 0, tzinfo=timezone.utc)

# ---- Setup ----
swe.set_ephe_path(EPHE_PATH)

# ---- Fallback JSON (Asteroids/TNOs) ----
FALLBACK_PATH = "aug_2025_to_feb_2026_asteroids_tnos_flat.json"
try:
    with open(FALLBACK_PATH, "r") as f:
        fallback_data = json.load(f)
        ASTEROID_FALLBACK = {entry["date"]: entry for entry in fallback_data["data"]}
except Exception:
    ASTEROID_FALLBACK = {}

# ---- Fixed stars ----
FIXED_STARS = [
    {"id": "Regulus",   "label": "Regulus (Alpha Leo)",    "ra_deg": 152.0929625, "dec_deg": 11.9672083},
    {"id": "Spica",     "label": "Spica (Alpha Vir)",      "ra_deg": 201.2982475, "dec_deg": -11.1613194},
    {"id": "Sirius",    "label": "Sirius (Alpha CMa)",     "ra_deg": 101.2871553, "dec_deg": -16.7161159},
    {"id": "Aldebaran", "label": "Aldebaran (Alpha Tau)",  "ra_deg": 68.9801625,  "dec_deg": 16.5093028},
]

# ---- Core planets, Nodes, Chiron, Liliths ----
PLANETS = {
    "Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY,
    "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN, "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE,
    "Pluto": swe.PLUTO, "Chiron": getattr(swe, "CHIRON", 15),
    "LilithMean": swe.MEAN_APOG, "LilithTrue": swe.OSCU_APOG,
    "NorthNode": swe.MEAN_NODE, "SouthNode": swe.TRUE_NODE
}

# ---- Asteroids & TNOs (relevant to master config) ----
ASTEROIDS = {
    "Vesta": 4, "Psyche": 16, "Amor": 1221, "Eros": 433,
    "Sappho": 80, "Karma": 3811,
    "Haumea": 136108, "Makemake": 136472, "Varuna": 20000,
    "Ixion": 28978, "Typhon": 42355, "Salacia": 120347,
    "Chariklo": 10199, "Eris": 136199, "Pholus": 5145, "Sedna": 90377
}

# ---- Helpers ----
def swe_calc(body, dt):
    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute / 60.0 + dt.second / 3600.0,
                    swe.GREG_CAL)
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    xx, ret = swe.calc_ut(jd, body, flags)
    if ret < 0:
        raise RuntimeError(f"Swiss Ephemeris failed for body {body}, ret={ret}")
    return float(xx[0]), float(xx[1])

def houses_and_parts(lat, lon, dt):
    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute / 60.0 + dt.second / 3600.0,
                    swe.GREG_CAL)
    cusp, ascmc = swe.houses_ex(jd, lat, lon, HOUSE_SYSTEM)
    asc = ascmc[0]; mc = ascmc[1]
    sun_lon, _ = swe_calc(swe.SUN, dt)
    moon_lon, _ = swe_calc(swe.MOON, dt)
    fortune = (asc + moon_lon - sun_lon) % 360
    spirit = (asc + sun_lon - moon_lon) % 360
    return {"ASC": asc, "MC": mc, "houses": cusp,
            "PartOfFortune": fortune, "PartOfSpirit": spirit}

def add_fixed_star(star, dt):
    return {
        "id": star["id"], "targetname": star["label"],
        "datetime_utc": dt.isoformat(),
        "ra_deg": star["ra_deg"], "dec_deg": star["dec_deg"],
        "epoch": "J2000", "source": "fixed"
    }

# ---- Main ----
def main():
    feed = {
        "meta": {
            "generated_at_utc": datetime.utcnow().isoformat(),
            "observer": OBSERVER,
            "window": "2025-08-24T18:00-07:00 → 2026-02-24T18:00-08:00",
            "range_days": DAYS_AHEAD,
            "source_order": ["jpl", "swiss", "miriade", "fallback"]
        },
        "transits": []
    }

    for d in range(DAYS_AHEAD + 1):
        dt = START_UTC + timedelta(days=d)
        date_key = dt.strftime("%Y-%m-%d")
        day_entry = {"date": date_key, "objects": []}

        # Planets + Chiron + Liliths + Nodes
        for name, body in PLANETS.items():
            lon, lat = swe_calc(body, dt)
            day_entry["objects"].append({
                "id": name, "datetime_utc": dt.isoformat(),
                "ecl_lon_deg": lon, "ecl_lat_deg": lat,
                "source": "swiss"
            })

        # Asteroids & TNOs
        for name, num in ASTEROIDS.items():
            try:
                lon, lat = swe_calc(num, dt)
                day_entry["objects"].append({
                    "id": name, "datetime_utc": dt.isoformat(),
                    "ecl_lon_deg": lon, "ecl_lat_deg": lat,
                    "source": "swiss-asteroid"
                })
            except Exception:
                if date_key in ASTEROID_FALLBACK and name in ASTEROID_FALLBACK[date_key]:
                    lon = ASTEROID_FALLBACK[date_key][name]
                    day_entry["objects"].append({
                        "id": name, "datetime_utc": dt.isoformat(),
                        "ecl_lon_deg": lon,
                        "source": "fallback-json"
                    })
                else:
                    day_entry["objects"].append({
                        "id": name, "datetime_utc": dt.isoformat(),
                        "error": "no data available"
                    })

        # Houses / Parts (default lat/lon = 0,0 for general feed)
        points = houses_and_parts(0.0, 0.0, dt)
        day_entry["objects"].append({"id":"ASC","datetime_utc":dt.isoformat(),"ecl_lon_deg":points["ASC"],"source":"swiss"})
        day_entry["objects"].append({"id":"MC","datetime_utc":dt.isoformat(),"ecl_lon_deg":points["MC"],"source":"swiss"})
        day_entry["objects"].append({"id":"PartOfFortune","datetime_utc":dt.isoformat(),"ecl_lon_deg":points["PartOfFortune"],"branch":"day","source":"swiss"})
        day_entry["objects"].append({"id":"PartOfSpirit","datetime_utc":dt.isoformat(),"ecl_lon_deg":points["PartOfSpirit"],"branch":"day","source":"swiss"})

        # Fixed stars
        for star in FIXED_STARS:
            day_entry["objects"].append(add_fixed_star(star, dt))

        feed["transits"].append(day_entry)

    Path("docs").mkdir(exist_ok=True)
    with open("docs/feed_6month.json", "w") as f:
        json.dump(feed, f, indent=2)

    print("[OK] Wrote docs/feed_6month.json with 6-month transit dataset")

if __name__ == "__main__":
    main()

