#!/usr/bin/env python3
"""
augment_feed.py — Add Swiss-style angles (ASC/MC/DESC/IC) and Arabic Parts to docs/feed_now.json.

Design:
- Uses only astropy/astroquery (no Swiss Ephemeris), so it runs on GitHub Actions reliably.
- Angles are computed for a configurable observer (defaults to Spanish Springs, NV).
- Arabic Parts are computed from the *current* sky (transits) using the feed’s ecliptic longitudes.
- Day/Night sect is derived from the Sun’s apparent altitude at the observer.

Environment overrides (optional):
  OBS_LAT  (default 39.653)    # Spanish Springs, NV
  OBS_LON  (default -119.706)
  OBS_ELEV (default 1340)      # meters

Input:
  docs/feed_now.json  produced by scripts/generate_feed.py

Output (in-place update of docs/feed_now.json):
  Adds:
    "observer_site": {"lat_deg","lon_deg","elev_m"}
    "angles": {"asc_deg","mc_deg","desc_deg","ic_deg"}
    "arabic_parts": {
        "fortune_deg", "spirit_deg", "eros_deg",
        "marriage_deg", "treachery_deg", "karma_deg",
        "vengeance_deg", "victory_deg", "intelligence_deg", "deliverance_deg", "commerce_deg"
    }

Notes:
- Formulas for some traditional parts vary by source. We use one common Hellenistic/medieval variant set.
- Degrees are normalized to [0, 360).

Run:
  python scripts/augment_feed.py
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Dict, Any, Tuple, Optional

import numpy as np
from astropy.time import Time
import astropy.units as u
from astropy.coordinates import (
    SkyCoord,
    AltAz,
    EarthLocation,
    GeocentricTrueEcliptic,
)

# -------------------- Utilities --------------------

def norm_deg(d: float) -> float:
    d = d % 360.0
    return d if d >= 0 else d + 360.0

def degdiff(a: float, b: float) -> float:
    """Smallest absolute difference (deg) on the circle."""
    d = abs((a - b + 180.0) % 360.0 - 180.0)
    return d

@dataclass
class Site:
    lat_deg: float
    lon_deg: float
    elev_m: float

    @classmethod
    def from_env(cls) -> "Site":
        lat = float(os.getenv("OBS_LAT", "39.653"))
        lon = float(os.getenv("OBS_LON", "-119.706"))
        elev = float(os.getenv("OBS_ELEV", "1340"))
        return cls(lat, lon, elev)

    def earth_location(self) -> EarthLocation:
        return EarthLocation(lat=self.lat_deg * u.deg,
                             lon=self.lon_deg * u.deg,
                             height=self.elev_m * u.m)


# -------------------- Angles --------------------

def ascendant_from_site_time(site: Site, t: Time) -> float:
    """
    Compute the Ascendant ecliptic longitude by transforming the EAST point on the local horizon
    (AltAz: az=90°, alt=0°) into the Geocentric True Ecliptic of date.
    """
    loc = site.earth_location()
    altaz = AltAz(obstime=t, location=loc)
    east_horizon = SkyCoord(az=90 * u.deg, alt=0 * u.deg, frame=altaz)
    ecl = east_horizon.transform_to(GeocentricTrueEcliptic(obstime=t))
    asc_lon = float(ecl.lon.wrap_at(360 * u.deg).degree)
    if asc_lon < 0:
        asc_lon += 360.0
    return asc_lon


def mc_from_site_time(site: Site, t: Time) -> float:
    """
    Compute MC (ecliptic longitude) numerically:
    Search the ecliptic (β=0) for the point on the local MERIDIAN (az ≈ 180°, upper).
    We choose the ecliptic longitude with az closest to 180° and maximum altitude.
    """
    loc = site.earth_location()
    altaz = AltAz(obstime=t, location=loc)

    best_lon: Optional[float] = None
    best_score = 1e9
    best_alt = -90.0

    # Coarse grid
    for lon in np.linspace(0, 360, 721):  # 0.5° step
        ecl_pt = SkyCoord(lon * u.deg, 0 * u.deg,
                          frame=GeocentricTrueEcliptic(obstime=t))
        altaz_pt = ecl_pt.transform_to(altaz)
        az = float(altaz_pt.az.degree)
        alt = float(altaz_pt.alt.degree)
        # Distance from the upper meridian (az=180)
        az_err = min(abs(az - 180.0), 360.0 - abs(az - 180.0))
        # Prefer points closer to the meridian; break ties by higher altitude
        score = az_err
        if score < best_score - 1e-6 or (abs(score - best_score) < 1e-6 and alt > best_alt):
            best_score = score
            best_alt = alt
            best_lon = lon

    # Local refine around best_lon
    if best_lon is None:
        raise RuntimeError("MC search failed.")
    span = 2.0
    for step in (0.2, 0.05, 0.01):
        lo = best_lon - span
        hi = best_lon + span
        lons = np.arange(lo, hi + 1e-6, step)
        for lon in lons:
            lon_n = norm_deg(lon)
            ecl_pt = SkyCoord(lon_n * u.deg, 0 * u.deg,
                              frame=GeocentricTrueEcliptic(obstime=t))
            altaz_pt = ecl_pt.transform_to(altaz)
            az = float(altaz_pt.az.degree)
            alt = float(altaz_pt.alt.degree)
            az_err = min(abs(az - 180.0), 360.0 - abs(az - 180.0))
            score = az_err
            if score < best_score - 1e-6 or (abs(score - best_score) < 1e-6 and alt > best_alt):
                best_score = score
                best_alt = alt
                best_lon = lon_n
        span = span / 2.0

    return norm_deg(best_lon)


def is_daytime(site: Site, t: Time) -> bool:
    """Sun altitude > 0° at the observer."""
    loc = site.earth_location()
    altaz = AltAz(obstime=t, location=loc)
    sun = SkyCoord.from_name("Sun").transform_to(altaz)  # fallback name resolver (local, cached by astropy)
    return float(sun.alt.degree) > 0.0


# -------------------- Arabic Parts --------------------

def part_day_night(asc: float, A: float, B: float, is_day: bool, day_expr: str, night_expr: str) -> float:
    """
    Generic day/night chooser for linear parts:
    - Expressions are 'ASC + A - B' or 'ASC + B - A' variants.
    """
    if is_day:
        if day_expr == "ASC + A - B":
            val = asc + A - B
        elif day_expr == "ASC + B - A":
            val = asc + B - A
        else:
            raise ValueError(f"Unsupported day_expr: {day_expr}")
    else:
        if night_expr == "ASC + A - B":
            val = asc + A - B
        elif night_expr == "ASC + B - A":
            val = asc + B - A
        else:
            raise ValueError(f"Unsupported night_expr: {night_expr}")
    return norm_deg(val)


def compute_arabic_parts(transit_long: Dict[str, float], asc_deg: float, is_day: bool) -> Dict[str, float]:
    """
    Compute a standard set of Arabic Parts from current transits + ASC.
    Inputs: transit_long keyed by lowercase body name: 'sun','moon','mercury','venus','mars','jupiter','saturn'
    """
    req = ["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn"]
    for k in req:
        if k not in transit_long:
            raise RuntimeError(f"Arabic Parts: missing {k} longitude")

    sun = transit_long["sun"]
    moon = transit_long["moon"]
    merc = transit_long["mercury"]
    venus = transit_long["venus"]
    mars = transit_long["mars"]
    jup = transit_long["jupiter"]
    sat = transit_long["saturn"]

    parts = {}

    # Fortune / Spirit (Hellenistic standard)
    parts["fortune_deg"] = part_day_night(asc_deg, moon, sun, is_day,
                                          day_expr="ASC + A - B",
                                          night_expr="ASC + B - A")
    parts["spirit_deg"] = part_day_night(asc_deg, sun, moon, is_day,
                                         day_expr="ASC + A - B",
                                         night_expr="ASC + B - A")

    # Eros (Love) — common medieval variant
    parts["eros_deg"] = part_day_night(asc_deg, venus, sun, is_day,
                                       day_expr="ASC + A - B",
                                       night_expr="ASC + B - A")

    # Marriage — one traditional set (there are many variants)
    parts["marriage_deg"] = part_day_night(asc_deg, venus, sat, is_day,
                                           day_expr="ASC + A - B",
                                           night_expr="ASC + B - A")

    # Treachery (discord/malice) — medieval variant
    parts["treachery_deg"] = norm_deg(asc_deg + mars - sat)

    # Karma — variant using Saturn + Nodes is common; without nodes, use Saturn vs Sun
    parts["karma_deg"] = norm_deg(asc_deg + sat - sun)

    # Vengeance — variant using Mars vs Moon
    parts["vengeance_deg"] = norm_deg(asc_deg + mars - moon)

    # Victory — Jupiter vs Sun
    parts["victory_deg"] = norm_deg(asc_deg + jup - sun)

    # Intelligence — Mercury vs Sun
    parts["intelligence_deg"] = norm_deg(asc_deg + merc - sun)

    # Deliverance — Jupiter vs Moon
    parts["deliverance_deg"] = norm_deg(asc_deg + jup - moon)

    # Commerce — Mercury vs Venus
    parts["commerce_deg"] = norm_deg(asc_deg + merc - venus)

    return parts


# -------------------- IO helpers --------------------

def load_feed(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def write_feed(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def map_transit_longitudes(feed: Dict[str, Any]) -> Dict[str, float]:
    """
    Extract ecliptic longitude (deg) for main bodies from the feed.
    Accepts ids like "sun" or labels like "Sun (10)"; normalizes keys.
    """
    objs = feed.get("objects", [])
    out: Dict[str, float] = {}
    key_map = {
        "sun": {"sun", "10", "sun (10)"},
        "moon": {"moon", "301", "moon (301)"},
        "mercury": {"mercury"},
        "venus": {"venus"},
        "mars": {"mars"},
        "jupiter": {"jupiter"},
        "saturn": {"saturn"},
    }

    def canon(s: str) -> str:
        return s.strip().lower()

    for o in objs:
        # prefer 'id', else parse targetname
        candidates = []
        if "id" in o and isinstance(o["id"], str):
            candidates.append(canon(o["id"]))
        if "targetname" in o and isinstance(o["targetname"], str):
            candidates.append(canon(o["targetname"]))
        if not candidates:
            continue

        # find bucket
        bucket = None
        for k, vals in key_map.items():
            if any(c in vals for c in candidates):
                bucket = k
                break
        if bucket is None:
            continue

        ecl = o.get("ecliptic", {})
        if "lon_deg" in ecl:
            out[bucket] = float(ecl["lon_deg"])

    return out


# -------------------- Main --------------------

def main() -> None:
    FEED = "docs/feed_now.json"

    # Load feed
    feed = load_feed(FEED)
    gen_t = feed.get("generated_at_utc")
    if not gen_t:
        raise SystemExit("feed_now.json missing 'generated_at_utc'")

    # Observer site & time
    site = Site.from_env()
    t = Time(gen_t)

    # Compute angles
    asc = ascendant_from_site_time(site, t)
    mc = mc_from_site_time(site, t)
    desc = norm_deg(asc + 180.0)
    ic = norm_deg(mc + 180.0)

    # Day/Night by Sun altitude
    loc = site.earth_location()
    altaz = AltAz(obstime=t, location=loc)
    # Get Sun apparent altitude robustly
    sun_alt = float(SkyCoord.from_name("Sun").transform_to(altaz).alt.degree)
    day_flag = sun_alt > 0.0

    # Pull transit longitudes
    trans_long = map_transit_longitudes(feed)
    missing = {"sun","moon","mercury","venus","mars","jupiter","saturn"} - set(trans_long.keys())
    if missing:
        raise SystemExit(f"Arabic parts cannot be computed; missing: {sorted(missing)}")

    parts = compute_arabic_parts(trans_long, asc, day_flag)

    # Augment feed
    feed["observer_site"] = {
        "lat_deg": site.lat_deg,
        "lon_deg": site.lon_deg,
        "elev_m": site.elev_m,
    }
    feed["angles"] = {
        "asc_deg": asc,
        "mc_deg": mc,
        "desc_deg": desc,
        "ic_deg": ic,
    }
    feed["arabic_parts"] = parts
    feed["meta"] = feed.get("meta", {})
    feed["meta"]["angles_source"] = "astropy AltAz->Ecliptic (no Swiss Ephemeris)"
    feed["meta"]["arabic_parts_variant"] = "Common Hellenistic/medieval mix; day/night aware"
    feed["meta"]["is_daytime"] = day_flag

    write_feed(FEED, feed)
    print(f"Augmented {FEED} with angles + Arabic Parts.")
    print("ASC={:.3f}  MC={:.3f}  Fortune={:.3f}".format(asc, mc, parts["fortune_deg"]))


if __name__ == "__main__":
    main()
