#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_feed_60day.py — build a 60-day projected transit feed.
Extended for Black Zodiac 3.3.0 full interpretation set.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import swisseph as swe

# ---- Settings ----
DAYS_AHEAD = 60
HOUSE_SYSTEM = b'P'  # Placidus
OBSERVER = "geocentric Earth"
EPHE_PATH = "ephe"

# ---- Setup ----
if not os.path.isdir(EPHE_PATH):
    raise RuntimeError(
        f"Ephemeris path '{EPHE_PATH}' not found. "
        "Commit ephe/ with sepl_18.se1, seas_18.se1, seasm18.se1, semo_18.se1"
    )

swe.set_ephe_path(EPHE_PATH)

# ---- Fixed stars ----
FIXED_STARS = [
    {"id": "Regulus",   "label": "Regulus (Alpha Leo)",    "ra_deg": 152.0929625, "dec_deg": 11.9672083},
    {"id": "Spica",     "label": "Spica (Alpha Vir)",      "ra_deg": 201.2982475, "dec_deg": -11.1613194},
    {"id": "Sirius",    "label": "Sirius (Alpha CMa)",     "ra_deg": 101.2871553, "dec_deg": -16.7161159},
    {"id": "Aldebaran", "label": "Aldebaran (Alpha Tau)",  "ra_deg": 68.9801625,  "dec_deg": 16.5093028},
]

# ---- Core maps ----
PLANETS = {
    "10": swe.SUN, "301": swe.MOON, "199": swe.MERCURY,
    "299": swe.VENUS, "499": swe.MARS, "599": swe.JUPITER,
    "699": swe.SATURN, "799": swe.URANUS, "899": swe.NEPTUNE,
    "999": swe.PLUTO, "2060": getattr(swe, "CHIRON", 15)
}

# Archetype asteroids & TNOs
ASTEROIDS = [
    "Vesta", "Psyche", "Amor", "Eros", "Sappho", "Karma",
    "Haumea", "Makemake", "Varuna", "Ixion", "Typhon", "Salacia"
]

# ---- Helpers ----
def swe_calc(body, dt):
    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute / 60.0 + dt.second / 3600.0,
                    swe.GREG_CAL)
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    xx, ret = swe.calc_ut(jd, body, flags)
    if ret < 0:
        raise RuntimeError(f"Swiss Ephemeris failed for body {body}, ret={ret}")
    return float(xx[0]), float(xx[1])  # longitude, latitude

def houses_and_points(lat, lon, dt):
    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute / 60.0 + dt.second / 3600.0,
                    swe.GREG_CAL)
    cusp, ascmc, _ = swe.houses_ex(jd, lat, lon, HOUSE_SYSTEM)
    asc = ascmc[0]
    mc = ascmc[1]
    sun_lon, _ = swe_calc(swe.SUN, dt)
    moon_lon, _ = swe_calc(swe.MOON, dt)
    fortune = (asc + moon_lon - sun_lon) % 360
    spirit = (asc + sun_lon - moon_lon) % 360
    return {"ASC": asc, "MC": mc, "houses": cusp,
            "PartOfFortune": fortune, "PartOfSpirit": spirit}

def add_fixed_star(star, dt):
    return {
        "targetname": star["label"], "id": star["id"],
        "datetime_utc": dt.isoformat(),
        "ra_deg": star["ra_deg"], "dec_deg": star["dec_deg"],
        "epoch": "J2000", "source": "fixed"
    }

def add_asteroid(name, dt):
    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute / 60.0 + dt.second / 3600.0,
                    swe.GREG_CAL)
    try:
        xx, ret = swe.calc_ut(jd, name)
        if ret >= 0:
            return {
                "id": name, "targetname": name,
                "datetime_utc": dt.isoformat(),
                "ecl_lon_deg": float(xx[0]),
                "ecl_lat_deg": float(xx[1]),
                "source": "swiss-asteroid"
            }
    except Exception as e:
        return {"id": name, "error": str(e)}
    return None

# ---- Main ----
def main():
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    feed = {
        "feed": {
            "generated_at_utc": datetime.utcnow().isoformat(),
            "observer": OBSERVER,
            "range_days": DAYS_AHEAD,
            "objects": []
        }
    }

    for d in range(DAYS_AHEAD + 1):
        dt = start + timedelta(days=d)

        # Planets + Chiron
        for pid, body in PLANETS.items():
            lon, lat = swe_calc(body, dt)
            feed["feed"]["objects"].append({
                "id": pid, "targetname": str(body),
                "datetime_utc": dt.isoformat(),
                "ecl_lon_deg": lon, "ecl_lat_deg": lat,
                "source": "swiss"
            })

        # Asteroids / TNOs
        for name in ASTEROIDS:
            pos = add_asteroid(name, dt)
            if pos: feed["feed"]["objects"].append(pos)

        # Houses / Arabic Parts
        points = houses_and_points(51.5, 0.0, dt)
        feed["feed"]["objects"].append({"id": "ASC","targetname":"Ascendant","datetime_utc":dt.isoformat(),"ecl_lon_deg":points["ASC"],"source":"swiss"})
        feed["feed"]["objects"].append({"id": "MC","targetname":"Midheaven","datetime_utc":dt.isoformat(),"ecl_lon_deg":points["MC"],"source":"swiss"})
        feed["feed"]["objects"].append({"id": "Houses","targetname":"Houses","datetime_utc":dt.isoformat(),"houses_deg":points["houses"],"source":"swiss"})
        feed["feed"]["objects"].append({"id": "PartOfFortune","targetname":"Part of Fortune","datetime_utc":dt.isoformat(),"ecl_lon_deg":points["PartOfFortune"],"branch":"day","source":"swiss"})
        feed["feed"]["objects"].append({"id": "PartOfSpirit","targetname":"Part of Spirit","datetime_utc":dt.isoformat(),"ecl_lon_deg":points["PartOfSpirit"],"branch":"day","source":"swiss"})

        # Fixed stars
        for star in FIXED_STARS:
            feed["feed"]["objects"].append(add_fixed_star(star, dt))

    Path("docs").mkdir(exist_ok=True)
    with open("docs/feed_60day.json", "w") as f:
        json.dump(feed, f, indent=2)

    print("[OK] Wrote docs/feed_60day.json")

if __name__ == "__main__":
    main()
