#!/usr/bin/env python3
"""
generate_feed.py — Build docs/feed_now.json from JPL Horizons vectors with
robust ecliptic fallback (no reliance on Horizons-provided ecliptic columns).

Why this exists:
- Previous job crashed: "Missing ecliptic longitude for: Sun (10)".
- We now ALWAYS compute ecliptic lon/lat from vectors via Astropy transforms.
- Removes deprecated id_type use and fragile column assumptions.

Output:
- docs/feed_now.json

Dependencies:
- astroquery, astropy, numpy

Run locally:
  python scripts/generate_feed.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, Any, List

import numpy as np
from astroquery.jplhorizons import Horizons
from astropy.coordinates import SkyCoord, GeocentricTrueEcliptic
from astropy.time import Time
import astropy.units as u

# ---------- Config ----------

# Earth geocenter (500@399) — consistent with your previous pipeline
OBSERVING_CENTER = "500@399"

# Targets to include. Use Horizons-resolvable names (strings are safest).
# Labels keep your preferred display (e.g., "Sun (10)"), but the 'id' key is
# what we pass to Horizons. You can expand this list anytime.
TARGETS: List[Dict[str, str]] = [
    {"id": "sun",      "label": "Sun (10)"},
    {"id": "moon",     "label": "Moon (301)"},
    {"id": "mercury",  "label": "Mercury"},
    {"id": "venus",    "label": "Venus"},
    {"id": "earth",    "label": "Earth"},   # useful reference
    {"id": "mars",     "label": "Mars"},
    {"id": "jupiter",  "label": "Jupiter"},
    {"id": "saturn",   "label": "Saturn"},
    {"id": "uranus",   "label": "Uranus"},
    {"id": "neptune",  "label": "Neptune"},
    {"id": "pluto",    "label": "Pluto"},
]

# Optional: extend with your asteroid/TNO pack by adding more dicts above
# (e.g., {"id": "433", "label": "Eros (433)"}). Strings like "433" or names
# like "Eros" both work with Horizons.


# Where to write the feed
FEED_OUT = os.environ.get("FEED_OUT", "docs/feed_now.json")


# ---------- Helpers ----------

def _vectors_to_ecliptic_lonlat(x_au: float, y_au: float, z_au: float, t: Time) -> Dict[str, float]:
    """
    Convert ICRS cartesian vectors (Earth-centered) to Geocentric True Ecliptic (of date).
    Returns degrees for lon/lat and AU for distance.
    """
    coord_icrs = SkyCoord(x=x_au*u.au, y=y_au*u.au, z=z_au*u.au,
                          representation_type="cartesian", frame="icrs")
    ecl = coord_icrs.transform_to(GeocentricTrueEcliptic(obstime=t))
    lon = float(ecl.lon.wrap_at(360*u.deg).degree)
    lat = float(ecl.lat.degree)
    dist = float(ecl.distance.to(u.au).value)
    # Normalize longitude to [0, 360)
    if lon < 0:
        lon += 360.0
    return {"lon_deg": lon, "lat_deg": lat, "distance_au": dist}


def _fetch_vectors(target_id: str, epochs_jd: float) -> Dict[str, float]:
    """
    Query Horizons vectors for a single target relative to Earth center.
    Returns x,y,z in AU.
    """
    # id_type is intentionally omitted to avoid astroquery deprecation warnings
    h = Horizons(id=target_id, location=OBSERVING_CENTER, epochs=epochs_jd)
    tbl = h.vectors()
    if len(tbl) == 0:
        raise RuntimeError(f"No vector rows returned for {target_id!r}")
    # Horizons vectors table keys are typically 'x', 'y', 'z' (AU) in J2000/ICRF
    x = float(tbl["x"][0])
    y = float(tbl["y"][0])
    z = float(tbl["z"][0])
    return {"x_au": x, "y_au": y, "z_au": z}


def build_feed() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    t = Time(now.isoformat())

    out: Dict[str, Any] = {
        "generated_at_utc": now.isoformat(),
        "observer": "geocentric (Earth center)",
        "refplane": "earth",
        "source": "JPL Horizons via astroquery + computed ecliptic from vectors",
        "objects": []
    }

    epochs_jd = float(t.jd)

    for tgt in TARGETS:
        tid = tgt["id"]
        label = tgt["label"]
        try:
            vec = _fetch_vectors(tid, epochs_jd)
            ecl = _vectors_to_ecliptic_lonlat(vec["x_au"], vec["y_au"], vec["z_au"], t)
            out["objects"].append({
                "id": tid,
                "targetname": label,
                "vector_au": {"x": vec["x_au"], "y": vec["y_au"], "z": vec["z_au"]},
                "ecliptic": ecl
            })
        except Exception as exc:
            # Do NOT hard-crash the job; record the failure and continue
            out["objects"].append({
                "id": tid,
                "targetname": label,
                "error": f"{type(exc).__name__}: {exc}"
            })

    # Simple health check: require at least Sun & Moon to succeed
    have_sun = any(o.get("id") in ("sun", "10") and "ecliptic" in o for o in out["objects"])
    have_moon = any(o.get("id") in ("moon", "301") and "ecliptic" in o for o in out["objects"])
    if not (have_sun and have_moon):
        # Still write the file for debug, but exit non-zero so CI shows red for visibility
        with open(FEED_OUT, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        raise SystemExit("FATAL: Sun and/or Moon missing ecliptic data after fallback computation.")

    return out


def main() -> None:
    feed = build_feed()
    os.makedirs(os.path.dirname(FEED_OUT), exist_ok=True)
    with open(FEED_OUT, "w", encoding="utf-8") as f:
        json.dump(feed, f, indent=2)
    print(f"Wrote {FEED_OUT} with {len(feed['objects'])} objects.")


if __name__ == "__main__":
    main()
