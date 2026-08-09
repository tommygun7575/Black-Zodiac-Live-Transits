#!/usr/bin/env python3
"""6-month transit feed generator — ZodiacOracle.SixMonthTransit.v2

Provider priority (per body/date):
  1. JPL Horizons — tried first for all moving bodies
  2. Swiss Ephemeris — fallback when JPL fails or returns invalid data
  3. If neither resolves the position the point is recorded as missing;
     generation continues for all remaining bodies and dates.

JPL identifier notes:
  - Planets/major bodies use NAIF integer-style string IDs.
  - MPC small bodies (Chiron, Ceres, Pallas, Juno, Vesta) use IDs with a
    trailing semicolon so Horizons resolves them as small bodies, not planets.

Atomic file writing:
  The completed JSON is written to a temp file first.  Only after successful
  serialization is the temp file atomically renamed to the final output path,
  so a serialization failure never corrupts the previously valid output file.
"""
import math
import os
import json
import datetime
import tempfile
import pytz
from astroquery.jplhorizons import Horizons

# --- Dual import: Linux (swisseph) vs Windows (pyswisseph) ---
try:
    import swisseph as swe   # Linux / GitHub Actions
except ImportError:
    import pyswisseph as swe   # Windows local

# --- Configure Swiss Ephemeris path ---
EPHE_PATH = os.path.join(os.getcwd(), "ephe")
swe.set_ephe_path(EPHE_PATH)
if not os.path.exists(EPHE_PATH):
    raise RuntimeError(f"❌ Swiss ephemeris path not found: {EPHE_PATH}")

# --- Moving-body target population (exactly 15 bodies — do not modify) ---
MOVING_BODIES = [
    "Sun", "Moon", "Mercury", "Venus", "Mars",
    "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto",
    "Chiron", "Ceres", "Pallas", "Juno", "Vesta",
]

# --- JPL Horizons identifiers ---
# Planets/major bodies: NAIF integer IDs as strings.
# Small bodies (Chiron, Ceres, Pallas, Juno, Vesta): MPC IDs with a trailing
# semicolon so Horizons resolves them via the small-body search path, not the
# planet/satellite table.  The semicolon is intentional — do not remove it.
JPL_IDS = {
    "Sun":     "10",
    "Moon":    "301",
    "Mercury": "199",
    "Venus":   "299",
    "Mars":    "499",
    "Jupiter": "599",
    "Saturn":  "699",
    "Uranus":  "799",
    "Neptune": "899",
    "Pluto":   "999",
    "Chiron":  "2060;",
    "Ceres":   "1;",
    "Pallas":  "2;",
    "Juno":    "3;",
    "Vesta":   "4;",
}

# Swiss Ephemeris body constants
SWISS_IDS = {
    "Sun":     swe.SUN,
    "Moon":    swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus":   swe.VENUS,
    "Mars":    swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn":  swe.SATURN,
    "Uranus":  swe.URANUS,
    "Neptune": swe.NEPTUNE,
    "Pluto":   swe.PLUTO,
    "Chiron":  swe.CHIRON,
    "Ceres":   swe.CERES,
    "Pallas":  swe.PALLAS,
    "Juno":    swe.JUNO,
    "Vesta":   swe.VESTA,
}

FIXED_STAR_FILE = "sefstars.txt"


# ------------------------------------------------------------
#  Coordinate validation
# ------------------------------------------------------------
def _is_valid(lon, lat) -> bool:
    """Return True only when both coordinates are finite real numbers.

    Validation rejects NaN, infinity, and None so that fabricated or
    corrupted values are never written to the output feed.
    """
    try:
        return (
            lon is not None and lat is not None
            and math.isfinite(float(lon))
            and math.isfinite(float(lat))
        )
    except (TypeError, ValueError):
        return False


def _normalize_lon(lon: float) -> float:
    """Normalize longitude to [0, 360)."""
    return float(lon) % 360.0


# ------------------------------------------------------------
#  Fixed star loader (preserved exactly — not counted in coverage)
# ------------------------------------------------------------
def get_fixed_stars():
    stars = {}
    if not os.path.exists(FIXED_STAR_FILE):
        return stars
    with open(FIXED_STAR_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if len(parts) < 3:
                continue
            try:
                name = parts[0]
                lon = float(parts[1])
                lat = float(parts[2])
                stars[name] = (lon, lat, "fixed")
            except ValueError:
                continue
    return stars


# ------------------------------------------------------------
#  Swiss Ephemeris calculator
# ------------------------------------------------------------
def swe_calc(body: str, dt: datetime.datetime):
    """Return (lon, lat) from Swiss Ephemeris, or raise on failure."""
    jd = swe.julday(
        dt.year, dt.month, dt.day,
        dt.hour + dt.minute / 60.0 + dt.second / 3600.0,
    )
    result = swe.calc_ut(jd, SWISS_IDS[body])

    # Linux swisseph returns ((lon, lat, dist, ...), retflag)
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], (list, tuple)):
        lon, lat, *_ = result[0]
        return float(lon), float(lat)

    # Windows pyswisseph returns (lon, lat, dist, ...)
    if isinstance(result, (list, tuple)) and len(result) >= 3:
        lon, lat, *_ = result
        return float(lon), float(lat)

    raise RuntimeError(f"Unexpected Swiss Ephemeris return format: {result!r}")


# ------------------------------------------------------------
#  JPL Horizons fetch
# ------------------------------------------------------------
def get_jpl_ephemeris(body: str, dt: datetime.datetime):
    """Return (lon, lat) from JPL Horizons, or None on failure.

    Uses MPC trailing-semicolon IDs for small bodies (Chiron, Ceres, etc.)
    so Horizons routes the lookup through the small-body search table.
    """
    try:
        obj = Horizons(
            id=JPL_IDS[body],
            location="500@399",
            epochs=dt.strftime("%Y-%m-%d %H:%M"),
            id_type=None,
        )
        eph = obj.ephemerides()
        if len(eph) == 0:
            return None
        lon = float(eph["EclLon"][0])
        lat = float(eph["EclLat"][0])
        return lon, lat
    except Exception:
        return None


# ------------------------------------------------------------
#  Per-body resolver: JPL → Swiss → unresolved
# ------------------------------------------------------------
def resolve_body(body: str, dt: datetime.datetime, day_key: str) -> dict:
    """Resolve one body for one date.

    Provider priority: JPL Horizons first, Swiss Ephemeris as fallback.
    Validates each result strictly; fabrication or interpolation is never
    used.  Returns a result dict with keys (ecl_lon_deg, ecl_lat_deg,
    source) on success, or None on failure (caller tracks missing points).
    Also returns the list of providers that were attempted.
    """
    attempted = []

    # 1. Try JPL Horizons
    attempted.append("JPL")
    coords = get_jpl_ephemeris(body, dt)
    if coords is not None:
        lon, lat = coords
        if _is_valid(lon, lat):
            return {
                "result": {
                    "ecl_lon_deg": _normalize_lon(lon),
                    "ecl_lat_deg": float(lat),
                    "source": "jpl",
                },
                "attempted": attempted,
            }

    # 2. Try Swiss Ephemeris (only for bodies that have a Swiss ID)
    if body in SWISS_IDS:
        attempted.append("Swiss")
        try:
            lon, lat = swe_calc(body, dt)
            if _is_valid(lon, lat):
                return {
                    "result": {
                        "ecl_lon_deg": _normalize_lon(lon),
                        "ecl_lat_deg": float(lat),
                        "source": "swiss",
                    },
                    "attempted": attempted,
                }
        except Exception as exc:
            print(f"  [WARN] Swiss failed for {body} on {day_key}: {exc}")

    # Neither provider resolved the position
    return {"result": None, "attempted": attempted}


# ------------------------------------------------------------
#  Main generator
# ------------------------------------------------------------
def main():
    # Dynamic 6-month window starting from "now" — ≈ 182 days, daily sampling
    now = datetime.datetime.now(pytz.UTC)
    start = now
    end = now + datetime.timedelta(days=182)
    step_days = 1

    # Build the list of dates that will be generated
    date_list = []
    dt = start
    while dt <= end:
        date_list.append(dt)
        dt += datetime.timedelta(days=step_days)

    # Coverage counters (fixed stars are excluded from moving-body coverage)
    total_points = len(MOVING_BODIES) * len(date_list)
    resolved_points = 0
    missing = []  # structured unresolved-point entries

    # Meta header
    data = {
        "engine_version": "ZodiacOracle.SixMonthTransit.v2",
        "meta": {
            "generated_at_utc": datetime.datetime.utcnow().replace(tzinfo=pytz.UTC).isoformat(),
            "generated_at_pacific": datetime.datetime.now(pytz.timezone("America/Los_Angeles")).isoformat(),
            "type": "6-month overlay",
            "range_utc": [start.isoformat(), end.isoformat()],
            "range": f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}",
            "source_order": ["jpl", "swiss", "fixed"],
        },
        "transits": {},
    }

    stars = get_fixed_stars()

    # Build daily data — one failed body/date does NOT abort the whole run
    for dt in date_list:
        day_key = dt.strftime("%Y-%m-%d")
        data["transits"][day_key] = {}

        # Resolve each moving body independently
        for body in MOVING_BODIES:
            outcome = resolve_body(body, dt, day_key)
            if outcome["result"] is not None:
                data["transits"][day_key][body] = outcome["result"]
                resolved_points += 1
            else:
                # Record the unresolved point with which providers were tried
                missing.append({
                    "date": day_key,
                    "body": body,
                    "providers_attempted": outcome["attempted"],
                })
                print(f"  [MISSING] {body} on {day_key} — tried: {outcome['attempted']}")

        # Fixed stars are written per day but not counted in moving-body coverage
        for star, (lon, lat, src) in stars.items():
            data["transits"][day_key][star] = {
                "ecl_lon_deg": lon,
                "ecl_lat_deg": lat,
                "source": src,
            }

    # Coverage calculation: resolved_points / total_points
    coverage = resolved_points / total_points if total_points > 0 else 0.0

    # Attach top-level diagnostics
    data["coverage"] = coverage
    data["resolved_points"] = resolved_points
    data["total_points"] = total_points
    data["missing"] = missing

    # Filename & output path (preserves existing naming convention)
    pacific = datetime.datetime.now(pytz.timezone("America/Los_Angeles"))
    filename = f"feed_overlay_6month_{pacific.strftime('%b-%d-%Y_%I-%M%p')}_Pacific.json"
    outdir = "docs"
    outpath = os.path.join(outdir, filename)
    os.makedirs(outdir, exist_ok=True)

    # Atomic file writing: serialize to a temp file first so that a
    # serialization failure never overwrites a previously valid output file.
    tmp_fd, tmp_path = tempfile.mkstemp(dir=outdir, suffix=".tmp.json")
    try:
        # os.fdopen takes ownership of tmp_fd; close it if that fails
        try:
            fh = os.fdopen(tmp_fd, "w", encoding="utf-8")
        except Exception:
            os.close(tmp_fd)
            raise
        with fh:
            json.dump(data, fh, indent=2)
        # Serialization succeeded — atomically replace the final output file
        os.replace(tmp_path, outpath)
    except Exception as exc:
        # Clean up the temp file; the previously valid output file is untouched
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise RuntimeError(f"❌ Serialization failed; output file unchanged: {exc}") from exc

    # Final status report
    if missing:
        print(f"⚠️  6-month feed written with incomplete coverage.")
        print(f"   resolved_points : {resolved_points}")
        print(f"   total_points    : {total_points}")
        print(f"   coverage        : {coverage:.4f}")
        print(f"   missing points  : {len(missing)}")
        print(f"   output          : {outpath}")
    else:
        print(f"✅ 6-month feed written — full coverage.")
        print(f"   resolved_points : {resolved_points}/{total_points}")
        print(f"   output          : {outpath}")


# ------------------------------------------------------------
if __name__ == "__main__":
    main()
