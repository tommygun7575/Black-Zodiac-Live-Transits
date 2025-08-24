# scripts/generate_feed_overlay.py

from astroquery.jplhorizons import Horizons
import swisseph as swe

# JPL Horizons numeric ID map (majors, key asteroids, TNOs)
JPL_IDS = {
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
    "Chiron": "2060",
    "Ceres": "1",
    "Pallas": "2",
    "Juno": "3",
    "Vesta": "4",
    "Eros": "433",
    "Amor": "1221",
    "Psyche": "16",
    "Hygiea": "10",
    "Eris": "136199",
    "Haumea": "136108",
    "Makemake": "136472",
    "Sedna": "90377",
    "Quaoar": "50000",
    "Ixion": "28978",
    "Orcus": "90482",
    "Varuna": "20000",
    "Salacia": "120347",
    "Typhon": "42355"
    # add more as needed
}


def get_body_coords(name: str, jd: float, observer: dict):
    """
    Try JPL Horizons first, then Swiss Ephemeris, then fallback.
    Returns (lon, lat, used_source).
    """
    try:
        # JPL Horizons
        if name in JPL_IDS:
            obj = Horizons(
                id=JPL_IDS[name],
                location="500@399",  # geocentric Earth
                epochs=jd
            )
            eph = obj.ephemerides()
            if "EclLon" in eph.columns and "EclLat" in eph.columns:
                lon = float(eph["EclLon"][0])
                lat = float(eph["EclLat"][0])
                return lon, lat, "jpl"
    except Exception as e:
        print(f"Horizons failed for {name}: {e}")

    try:
        # Swiss Ephemeris fallback
        if name in swe.SWEPH_PLANET_NAMES:
            body_id = list(swe.SWEPH_PLANET_NAMES).index(name)
            lon, lat, _ = swe.calc_ut(jd, body_id)
            return lon, lat, "swiss"
    except Exception as e:
        print(f"Swiss Ephemeris failed for {name}: {e}")

    # Final fallback → zeros
    print(f"Fallback used for {name}")
    return 0.0, 0.0, "calculated-fallback"
