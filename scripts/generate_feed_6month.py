#!/usr/bin/env python3
import json
import datetime
import os
from astroquery.jplhorizons import Horizons
import swisseph as swe

# === CONFIG ===
OUTPUT_FILE = "docs/feed_6month.json"
START_DATE = datetime.date.today()
DAYS_AHEAD = 180

# === OBJECT LIST (mirrors overlay) ===
HORIZONS_IDS = {
    "Sun": "10",
    "Moon": "301",
    "Mercury": "199",
    "Venus": "299",
    "Mars": "499",
    "Jupiter": "599",
    "Saturn": "699",
    "Uranus": "799",
    "Neptune": "899",
    "Pluto": "999",
    # Asteroids/TNOs
    "Chiron": "2060",
    "Ceres": "1",
    "Pallas": "2",
    "Juno": "3",
    "Vesta": "4",
    "Haumea": "136108",
    "Makemake": "136472",
    "Varuna": "20000",
    "Ixion": "28978",
    "Typhon": "42355",
    "Salacia": "120347",
}

# === HELPERS ===
def get_from_horizons(hid, jd):
    try:
        obj = Horizons(id=hid, location="@0", epochs=jd)
        eph = obj.ephemerides()
        lon = float(eph["EclLon"][0])
        lat = float(eph["EclLat"][0])
        return lon, lat, "jpl"
    except Exception:
        return None

def get_from_swiss(jd, body_const):
    try:
        if body_const is None:
            return None
        res = swe.calc_ut(jd, body_const)
        if isinstance(res, (list, tuple)):
            lon = float(res[0]) % 360
            lat = float(res[1])
            return lon, lat, "swiss"
    except Exception:
        return None

def fallback_calculated(name, jd):
    # simple placeholder for calc fallback (parts, harmonics etc.)
    if name == "Sun":
        lon = (swe.calc_ut(jd, swe.SUN)[0] + 180.0) % 360.0
        lat = 0.0
        return lon, lat, "calculated"
    return None

def compute_extras(date_iso, chart):
    chart["harmonics"] = {"example": "harmonic data"}
    chart["arabic_parts"] = {"example": "arabic parts"}
    chart["houses"] = {"example": "house cusps"}
    chart["fixed_stars"] = {"example": "fixed stars"}
    return chart

# === MAIN ===
def main():
    timeline = {}
    jd0 = swe.julday(START_DATE.year, START_DATE.month, START_DATE.day, 0.0)

    for d in range(DAYS_AHEAD):
        date = START_DATE + datetime.timedelta(days=d)
        jd = jd0 + d
        chart = {}

        for name, hid in HORIZONS_IDS.items():
            coords = get_from_horizons(hid, jd)
            if not coords:
                coords = get_from_swiss(jd, getattr(swe, name.upper(), None))
            if not coords:
                coords = fallback_calculated(name, jd)

            if coords:
                lon, lat, src = coords
                chart[name] = {"lon": lon, "lat": lat, "source": src}
            else:
                chart[name] = {"lon": None, "lat": None, "source": "missing"}

        chart = compute_extras(date.isoformat(), chart)
        timeline[date.isoformat()] = chart

    out = {
        "meta": {"generated_at_utc": datetime.datetime.utcnow().isoformat()},
        "timeline": timeline,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(out, f, indent=2)

if __name__ == "__main__":
    main()
