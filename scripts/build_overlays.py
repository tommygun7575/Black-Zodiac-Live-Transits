import json
import datetime
import swisseph as swe
from astroquery.jplhorizons import Horizons

# --- Body IDs ---
JPL_IDS = {
    "Sun": 10, "Moon": 301,
    "Mercury": 199, "Venus": 299, "Mars": 499,
    "Jupiter": 599, "Saturn": 699, "Uranus": 799,
    "Neptune": 899, "Pluto": 999,
}

SWISS_IDS = {
    "Sun": swe.SUN, "Moon": swe.MOON,
    "Mercury": swe.MERCURY, "Venus": swe.VENUS,
    "Mars": swe.MARS, "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN, "Uranus": swe.URANUS,
    "Neptune": swe.NEPTUNE, "Pluto": swe.PLUTO,
    "Chiron": swe.CHIRON, "Pholus": swe.PHOLUS
    # Add Eris, Sedna, Haumea, Makemake, Ixion, etc. once minor planet .se1 files are in /ephe
}

# --- JPL Horizons resolver ---
def get_jpl(body, dt):
    if body not in JPL_IDS:
        raise ValueError(f"No JPL ID for {body}")
    obj = Horizons(
        id=JPL_IDS[body],
        location='500@399',  # Earth geocentric
        epochs=dt.strftime("%Y-%m-%d %H:%M")
    )
    eph = obj.ephemerides()
    lon = float(eph['EclLon'][0])
    lat = float(eph['EclLat'][0])
    return lon, lat, "jpl"

# --- Swiss Ephemeris resolver ---
def get_swiss(body, jd):
    if body not in SWISS_IDS:
        raise ValueError(f"No Swiss ID for {body}")
    lon, lat, _ = swe.calc_ut(jd, SWISS_IDS[body])
    return lon, lat, "swiss"

# --- Position resolver ---
def resolve_position(body, dt, jd):
    try:
        return get_jpl(body, dt)
    except Exception as e:
        print(f"[WARN] JPL fail for {body}: {e}")
    try:
        return get_swiss(body, jd)
    except Exception as e:
        print(f"[WARN] Swiss fail for {body}: {e}")
    raise RuntimeError(f"Unable to resolve {body} at {dt}")

# --- Main builder ---
def main():
    dt = datetime.datetime.utcnow()
    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute/60.0 + dt.second/3600.0)

    # Bodies to calculate
    bodies = [
        "Sun", "Moon", "Mercury", "Venus", "Mars",
        "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto",
        "Chiron", "Pholus"
    ]

    overlay = {
        "meta": {
            "generated_at_utc": dt.isoformat(),
            "observer": "geocentric Earth",
            "source_hierarchy": ["jpl", "swiss"],
            "black_zodiac_version": "3.3.0"
        },
        "objects": []
    }

    for b in bodies:
        lon, lat, src = resolve_position(b, dt, jd)
        overlay["objects"].append({
            "id": b,
            "targetname": b,
            "ecl_lon_deg": lon,
            "ecl_lat_deg": lat,
            "source": src
        })

    with open("docs/feed_overlay.json", "w") as f:
        json.dump(overlay, f, indent=2)

    print("[INFO] Overlay file written → docs/feed_overlay.json")

if __name__ == "__main__":
    main()
