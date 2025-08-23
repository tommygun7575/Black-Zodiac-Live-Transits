#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_feed_60day.py — build a 60-day projected transit feed.
Full Black Zodiac 3.3.0 set: planets, Chiron, asteroids, TNOs,
Arabic Parts, houses, fixed stars.
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
EPHE_PATH = "."  # .se1 files are in repo root

# ---- Setup ----
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

# Archetype asteroids & TNOs (numeric IDs for Swiss Ephemeris)
ASTEROIDS = {
    "Vesta": 4, "Psyche": 16, "Amor": 1221, "Eros": 433,
    "Sappho": 80, "Karma": 3811,
    "Haumea": 136108, "Makemake": 136472, "Varuna": 20000,
    "Ixion": 28978, "Typhon": 42355, "Salacia": 120347
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

def houses_and_points(lat, lon, dt):
    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute / 60.0 + dt.second / 3600.0,
                    swe.GREG_CAL)
    cusp, ascmc = swe.houses_ex(jd, lat, lon, HOUSE_SYSTEM)
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
        for name, num in ASTEROIDS.items():
            try:
                lon, lat = swe_calc(num, dt)
                feed["feed"]["objects"].append({
                    "id": str(num), "targetname": name,
                    "datetime_utc": dt.isoformat(),
                    "ecl_lon_deg": lon, "ecl_lat_deg": lat,
                    "source": "swiss-asteroid"
                })
            except Exception as e:
                feed["feed"]["objects"].append({"id": str(num), "targetname": name, "error": str(e)})

        # Houses / Arabic Parts
        points = houses_and_points(51.5, 0.0, dt)
        feed["feed"]["objects"].append({
            "id": "ASC", "targetname": "Ascendant",
            "datetime_utc": dt.isoformat(),
            "ecl_lon_deg": points["ASC"], "source": "swiss"
        })
        feed["feed"]["objects"].append({
            "id": "MC", "targetname": "Midheaven",
            "datetime_utc": dt.isoformat(),
            "ecl_lon_deg": points["MC"], "source": "swiss"
        })
        feed["feed"]["objects"].append({
            "id": "Houses", "targetname": "Houses",
            "datetime_utc": dt.isoformat(),
            "houses_deg": points["houses"], "source": "swiss"
        })
        feed["feed"]["objects"].append({
            "id": "PartOfFortune", "targetname": "Part of Fortune",
            "datetime_utc": dt.isoformat(),
            "ecl_lon_deg": points["PartOfFortune"],
            "branch": "day", "source": "swiss"
        })
        feed["feed"]["objects"].append({
            "id": "PartOfSpirit", "targetname": "Part of Spirit",
            "datetime_utc": dt.isoformat(),
            "ecl_lon_deg": points["PartOfSpirit"],
            "branch": "day", "source": "swiss"
        })

        # Fixed stars
        for star in FIXED_STARS:
            feed["feed"]["objects"].append(add_fixed_star(star, dt))

    Path("docs").mkdir(exist_ok=True)
    with open("docs/feed_60day.json", "w") as f:
        json.dump(feed, f, indent=2)

    print("[OK] Wrote docs/feed_60day.json")

if __name__ == "__main__":
    main()
