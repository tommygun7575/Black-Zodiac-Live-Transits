import json
import datetime
import time
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

# --- JPL batch with retry + validation ---
def get_jpl_batch(dt, retries=3):
    ids = ",".join(str(v) for v in JPL_IDS.values())
    delay = 2
    for attempt in range(retries):
        try:
            obj = Horizons(
                id=ids,
                location="500@399",  # Earth geocentric
                epochs=dt.strftime("%Y-%m-%d %H:%M")
            )
            eph = obj.ephemerides()

            if "EclLon" not in eph.columns or "EclLat" not in eph.columns:
                raise RuntimeError("Horizons returned malformed ephemeris")

            result = {}
            for name, jpl_id in JPL_IDS.items():
                row = eph[eph["targetname"].str.contains(name, case=False)]
                if len(row) > 0:
                    lon = float(row["EclLon"].values[0])
                    lat = float(row["EclLat"].values[0])
                    if not (0.0 <= lon < 360.0):
                        raise ValueError(f"Bad longitude for {name}: {lon}")
                    result[name] = (lon, lat, "jpl")
            if result:
                return result

        except Exception as e:
            print(f"[WARN] JPL batch attempt {attempt+1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
    return {}

# --- Swiss safe wrapper (no ValueError) ---
def get_swiss(body, jd):
    if body in SWISS_IDS:
        res = swe.calc_ut(jd, SWISS_IDS[body])
        lon, lat = res[0], res[1]   # <-- ONLY TWO VALUES
        return lon, lat, "swiss"
    if body in SWISS_MINORS:
        res = swe.calc_ut(jd, SWISS_MINORS[body])
        lon, lat = res[0], res[1]   # <-- ONLY TWO VALUES
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

    return {
        "PartOfFortune": normalize_deg(asc + moon - sun),
        "PartOfSpirit": normalize_deg(asc + sun - moon),
        "PartOfKarma": normalize_deg(asc + moon - sun + 30),
        "PartOfTreachery": angles["MC"],
        "PartOfDeliverance": normalize_deg(asc + moon - sun + 106),
        "PartOfRebirth": normalize_deg(asc + sun - moon + 49),
        "PartOfVengeance": normalize_deg(asc - moon + sun),
        "PartOfVictory": normalize_deg(asc + sun - moon + 60),
        "PartOfDelirium": normalize_deg(asc + moon + sun),
        "PartOfIntelligence": normalize_deg(asc + sun - moon - 30),
    }

# -------------------------------
# 5. Main
# -------------------------------

def main():
    dt = datetime.datetime.utcnow()
    jd = swe.julday(
        dt.year, dt.month, dt.day,
        dt.hour + dt.minute/60.0 + dt.second/3600.0
    )

    obs_lat, obs_lon = 0.0, 0.0
    angles = compute_angles(jd, obs_lat, obs_lon)

    bodies = list(JPL_IDS.keys()) + \
             [b for b in SWISS_IDS.keys() if b not in JPL_IDS] + \
             list(SWISS_MINORS.keys())

    objs, overlay = {}, {
        "meta": {
            "generated_at_utc": dt.isoformat(),
            "observer": "geocentric Earth",
            "source_hierarchy": ["jpl", "swiss", "swiss_minor", "fixed"],
            "black_zodiac_version": "3.3.0"
        },
        "objects": [],
        "angles": angles
    }

    # --- JPL batch majors ---
    jpl_results = get_jpl_batch(dt)

    # Majors (Sun–Pluto)
    for b in JPL_IDS.keys():
        if b in jpl_results:
            lon, lat, src = jpl_results[b]
        else:
            lon, lat, src = get_swiss(b, jd)
        objs[b] = {"lon": lon, "lat": lat}
        overlay["objects"].append({
            "id": b, "targetname": b,
            "ecl_lon_deg": lon,
            "ecl_lat_deg": lat,
            "source": src
        })

    # Swiss-only (Chiron, Pholus, minors, TNOs)
    for b in [bb for bb in bodies if bb not in JPL_IDS]:
        lon, lat, src = get_swiss(b, jd)
        objs[b] = {"lon": lon, "lat": lat}
        overlay["objects"].append({
            "id": b, "targetname": b,
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

    # Arabic Parts
    overlay["angles"].update(compute_parts(angles, objs))

    with open("docs/feed_overlay.json", "w") as f:
        json.dump(overlay, f, indent=2)

    print("[INFO] Overlay file written → docs/feed_overlay.json")

if __name__ == "__main__":
    main()
