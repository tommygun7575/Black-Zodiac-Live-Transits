import json
import datetime
import swisseph as swe
from astroquery.jplhorizons import Horizons

# -------------------------------
# 1. Body ID maps
# -------------------------------

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
}

SWISS_MINORS = {
    "Eris": 136199, "Sedna": 90377,
    "Haumea": 136108, "Makemake": 136472,
    "Ixion": 28978, "Varuna": 20000,
    "Salacia": 120347, "Typhon": 42355,
    "Vesta": 4, "Psyche": 16,
    "Amor": 1221, "Eros": 433,
    "Sappho": 80, "Karma": 3811,
    "Bacchus": 2063, "Astraea": 5,
    "Euphrosyne": 31, "Chariklo": 10199,
}

FIXED_STARS = {
    "Regulus": 150.0,
    "Spica": 204.75,
    "Sirius": 104.0,
    "Aldebaran": 69.0
}

# -------------------------------
# 2. Helpers
# -------------------------------

def normalize_deg(x):
    return x % 360.0

def get_jpl(body, dt):
    obj = Horizons(
        id=JPL_IDS[body],
        location="500@399",  # Earth geocentric
        epochs=dt.strftime("%Y-%m-%d %H:%M")
    )
    eph = obj.ephemerides()
    lon = float(eph["EclLon"][0])
    lat = float(eph["EclLat"][0])
    return lon, lat, "jpl"

def get_swiss(body, jd):
    if body in SWISS_IDS:
        res = swe.calc_ut(jd, SWISS_IDS[body])
        lon, lat = res[0], res[1]
        return lon, lat, "swiss"
    if body in SWISS_MINORS:
        res = swe.calc_ut(jd, SWISS_MINORS[body])
        lon, lat = res[0], res[1]
        return lon, lat, "swiss_minor"
    raise ValueError(f"No Swiss ID for {body}")

def resolve_position(body, dt, jd):
    if body in JPL_IDS:
        try:
            return get_jpl(body, dt)
        except Exception as e:
            print(f"[WARN] JPL fail for {body}: {e}")
        return get_swiss(body, jd)
    return get_swiss(body, jd)

# -------------------------------
# 3. Houses & Angles
# -------------------------------

def compute_angles(jd, lat, lon):
    ascmc, cusps = swe.houses(jd, lat, lon, b'P')
    return {
        "ASC": normalize_deg(ascmc[0]),
        "MC": normalize_deg(ascmc[1]),
        "houses": [normalize_deg(c) for c in cusps],
        "ascmc_all": [normalize_deg(a) for a in ascmc]
    }

# -------------------------------
# 4. Arabic Parts
# -------------------------------

def compute_parts(angles, objs):
    sun = objs["Sun"]["lon"]
    moon = objs["Moon"]["lon"]
    asc = angles["ASC"]

    parts = {}
    parts["PartOfFortune"]      = normalize_deg(asc + moon - sun)
    parts["PartOfSpirit"]       = normalize_deg(asc + sun - moon)
    parts["PartOfKarma"]        = normalize_deg(asc + moon - sun + 30)
    parts["PartOfTreachery"]    = angles["MC"]
    parts["PartOfDeliverance"]  = normalize_deg(parts["PartOfFortune"] + 106)
    parts["PartOfRebirth"]      = normalize_deg(parts["PartOfSpirit"] + 49)
    parts["PartOfVengeance"]    = normalize_deg(asc - moon + sun)
    parts["PartOfVictory"]      = normalize_deg(asc + sun - moon + 60)
    parts["PartOfDelirium"]     = normalize_deg(asc + moon + sun)
    parts["PartOfIntelligence"] = normalize_deg(parts["PartOfSpirit"] - 30)

    return parts

# -------------------------------
# 5. Main
# -------------------------------

def main():
    dt = datetime.datetime.utcnow()
    jd = swe.julday(
        dt.year, dt.month, dt.day,
        dt.hour + dt.minute/60.0 + dt.second/3600.0
    )

    # Observer = geocentric overlay
    obs_lat, obs_lon = 0.0, 0.0
    angles = compute_angles(jd, obs_lat, obs_lon)

    # Body list
    bodies = list(JPL_IDS.keys()) + \
             [b for b in SWISS_IDS.keys() if b not in JPL_IDS] + \
             list(SWISS_MINORS.keys())

    objs = {}
    overlay = {
        "meta": {
            "generated_at_utc": dt.isoformat(),
            "observer": "geocentric Earth",
            "source_hierarchy": ["jpl", "swiss", "swiss_minor", "fixed"],
            "black_zodiac_version": "3.3.0"
        },
        "objects": [],
        "angles": angles
    }

    # Planets, asteroids, TNOs
    for b in bodies:
        lon, lat, src = resolve_position(b, dt, jd)
        objs[b] = {"lon": lon, "lat": lat}
        overlay["objects"].append({
            "id": b,
            "targetname": b,
            "ecl_lon_deg": lon,
            "ecl_lat_deg": lat,
            "source": src
        })

    # Fixed stars
    for star, lon in FIXED_STARS.items():
        overlay["objects"].append({
            "id": star,
            "targetname": star,
            "ecl_lon_deg": lon,
            "ecl_lat_deg": 0.0,
            "source": "fixed"
        })

    # Arabic parts
    overlay["angles"].update(compute_parts(angles, objs))

    with open("docs/feed_overlay.json", "w") as f:
        json.dump(overlay, f, indent=2)

    print("[INFO] Overlay file written → docs/feed_overlay.json")

if __name__ == "__main__":
    main()
