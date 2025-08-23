import json
import datetime
import swisseph as swe
from astroquery.jplhorizons import Horizons

# -------------------------------
# 1. Body ID maps
# -------------------------------

# JPL IDs for major bodies
JPL_IDS = {
    "Sun": 10, "Moon": 301,
    "Mercury": 199, "Venus": 299, "Mars": 499,
    "Jupiter": 599, "Saturn": 699, "Uranus": 799,
    "Neptune": 899, "Pluto": 999,
}

# Swiss constants
SWISS_IDS = {
    "Sun": swe.SUN, "Moon": swe.MOON,
    "Mercury": swe.MERCURY, "Venus": swe.VENUS,
    "Mars": swe.MARS, "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN, "Uranus": swe.URANUS,
    "Neptune": swe.NEPTUNE, "Pluto": swe.PLUTO,
    "Chiron": swe.CHIRON, "Pholus": swe.PHOLUS
}

# Swiss minor planets / TNOs (MPC numbers)
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

# Fixed stars
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

# Batched Horizons call for majors
def get_jpl_batch(dt):
    ids = ",".join(str(v) for v in JPL_IDS.values())
    obj = Horizons(
        id=ids,
        location="500@399",
        epochs=dt.strftime("%Y-%m-%d %H:%M")
    )
    eph = obj.ephemerides()
    result = {}
    for name, jpl_id in JPL_IDS.items():
        row = eph[eph["targetname"].str.contains(name, case=False)]
        if len(row) > 0:
            lon = float(row["EclLon"].values[0])
            lat = float(row["EclLat"].values[0])
            result[name] = (lon, lat, "jpl")
    return result

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
