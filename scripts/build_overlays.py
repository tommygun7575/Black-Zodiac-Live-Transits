import json
import datetime
import swisseph as swe
from astroquery.jplhorizons import Horizons

# -------------------------------
# 1. Body ID maps
# -------------------------------

# JPL Horizons major bodies
JPL_IDS = {
    "Sun": 10, "Moon": 301,
    "Mercury": 199, "Venus": 299, "Mars": 499,
    "Jupiter": 599, "Saturn": 699, "Uranus": 799,
    "Neptune": 899, "Pluto": 999,
}

# Swiss built-ins
SWISS_IDS = {
    "Sun": swe.SUN, "Moon": swe.MOON,
    "Mercury": swe.MERCURY, "Venus": swe.VENUS,
    "Mars": swe.MARS, "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN, "Uranus": swe.URANUS,
    "Neptune": swe.NEPTUNE, "Pluto": swe.PLUTO,
    "Chiron": swe.CHIRON, "Pholus": swe.PHOLUS
}

# Swiss minor planets / TNOs — by MPC number
# (numbers come from MPC catalog; need se1 files present)
SWISS_MINORS = {
    "Eris": 136199,
    "Sedna": 90377,
    "Haumea": 136108,
    "Makemake": 136472,
    "Ixion": 28978,
    "Varuna": 20000,
    "Salacia": 120347,
    "Typhon": 42355,
}

# Extra asteroids
SWISS_MINORS.update({
    "Vesta": 4,
    "Psyche": 16,
    "Amor": 1221,
    "Eros": 433,
    "Sappho": 80,
    "Karma": 3811,
    "Bacchus": 2063,
    "Astraea": 5,
    "Euphrosyne": 31,
    "Chariklo": 10199,
})

# -------------------------------
# 2. JPL Horizons resolver
# -------------------------------

def get_jpl(body, dt):
    if body not in JPL_IDS:
        raise ValueError(f"No JPL ID for {body}")
    obj = Horizons(
        id=JPL_IDS[body],
        location="500@399",  # Earth geocentric
        epochs=dt.strftime("%Y-%m-%d %H:%M")
    )
    eph = obj.ephemerides()
    lon = float(eph["EclLon"][0])
    lat = float(eph["EclLat"][0])
    return lon, lat, "jpl"

# -------------------------------
# 3. Swiss Ephemeris resolver
# -------------------------------

def get_swiss(body, jd):
    if body in SWISS_IDS:
        lon, lat, _ = swe.calc_ut(jd, SWISS_IDS[body])
        return lon, lat, "swiss"

    if body in SWISS_MINORS:
        lon, lat, _ = swe.calc_ut(jd, SWISS_MINORS[body])
        return lon, lat, "swiss_minor"

    raise ValueError(f"No Swiss ID for {body}")

# -------------------------------
# 4. Resolver logic
# -------------------------------

def resolve_position(body, dt, jd):
    # For classical planets: JPL → Swiss fallback
    if body in JPL_IDS:
