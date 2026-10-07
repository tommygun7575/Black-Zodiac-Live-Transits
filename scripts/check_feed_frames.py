#!/usr/bin/env python3
"""CI frame-regression assertion for generated Black Zodiac feeds.

Usage:
    python scripts/check_feed_frames.py docs/feed_overlay_YYYY_MM_DD.json
    python scripts/check_feed_frames.py docs/feed_overlay_6month_<stamp>.json

Asserts every published position is GEOCENTRIC apparent ecliptic of date:
  * Mercury within 28 deg of the Sun, Venus within 48 deg (impossible for
    heliocentric / Sun-centred output);
  * Sun..Pluto and Ceres agree with Swiss Ephemeris (default calc_ut = apparent
    geocentric, true ecliptic & equinox of date) at the feed's own instant
    within 0.05 deg;
  * Aldebaran is precessed to of-date (Swiss fixstar2_ut) within 0.05 deg;
  * when the feed contains 2026-10-07 12:00 UTC, JPL Horizons q31 reference
    values are matched within 0.05 deg.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import swisseph as swe

ROOT = Path(__file__).resolve().parents[1]
swe.set_ephe_path(str(ROOT / "ephe"))

TOL_DEG = 0.05
MAX_ELONGATION = {"Mercury": 28.0, "Venus": 48.0}

# JPL Horizons OBSERVER QUANTITIES='31', CENTER='500@399', 2026-10-07 12:00 UTC
JPL_REFERENCE_INSTANT = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
JPL_REFERENCE = {
    "Mercury": 218.7987,
    "Venus": 218.1449,
    "Moon": 155.1954,
    "Mars": 125.4335,
    "Jupiter": 140.7246,
}

SWISS_CHECK = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,
    "Mars": swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN,
    "Uranus": swe.URANUS,
    "Neptune": swe.NEPTUNE,
    "Pluto": swe.PLUTO,
    "Ceres": swe.CERES,
}


def arc(a: float, b: float) -> float:
    d = abs((float(a) - float(b)) % 360.0)
    return min(d, 360.0 - d)


def jd(dt: datetime) -> float:
    d = dt.astimezone(timezone.utc)
    return swe.julday(d.year, d.month, d.day,
                      d.hour + d.minute / 60.0 + (d.second + d.microsecond / 1e6) / 3600.0)


def parse_ts(text: str) -> datetime:
    dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def check_snapshot(label: str, lons: dict, when: datetime, errors: list) -> None:
    sun = lons.get("Sun")
    if sun is not None:
        for body, limit in MAX_ELONGATION.items():
            if lons.get(body) is None:
                continue
            e = arc(lons[body], sun)
            if e > limit:
                errors.append(f"{label}: {body} elongation {e:.2f} > {limit} (Sun={sun:.3f}, {body}={lons[body]:.3f})")
    j = jd(when)
    for body, code in SWISS_CHECK.items():
        if lons.get(body) is None:
            continue
        ref = swe.calc_ut(j, code)[0][0]
        d = arc(lons[body], ref)
        if d > TOL_DEG:
            errors.append(f"{label}: {body} {lons[body]:.4f} vs Swiss of-date {ref:.4f} (diff {d:.4f})")
    if lons.get("Aldebaran") is not None:
        ref = swe.fixstar2_ut("Aldebaran", j)[0][0]
        d = arc(lons["Aldebaran"], ref)
        if d > TOL_DEG:
            errors.append(f"{label}: Aldebaran {lons['Aldebaran']:.4f} vs of-date {ref:.4f} (diff {d:.4f})")
    if abs((when - JPL_REFERENCE_INSTANT).total_seconds()) < 1:
        for body, ref in JPL_REFERENCE.items():
            if lons.get(body) is None:
                continue
            d = arc(lons[body], ref)
            if d > TOL_DEG:
                errors.append(f"{label}: {body} {lons[body]:.4f} vs JPL q31 {ref} (diff {d:.4f})")


def main(path: str) -> int:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    errors: list = []
    checked = 0

    if "transit_positions" in payload:
        tp = payload["transit_positions"]
        when = parse_ts(payload.get("generated_at_utc"))
        lons = {k: v.get("longitude") for k, v in tp.items() if isinstance(v, dict)}
        check_snapshot(f"daily@{when.isoformat()}", lons, when, errors)
        checked += 1
    elif "transits" in payload:
        start = parse_ts(payload["meta"]["range_utc"][0])
        for i, (day, bodies) in enumerate(payload["transits"].items()):
            when = start + timedelta(days=i)
            if when.strftime("%Y-%m-%d") != day:
                errors.append(f"6M day key {day} != sample {when.isoformat()}")
                continue
            lons = {k: v.get("ecl_lon_deg") for k, v in bodies.items() if isinstance(v, dict)}
            check_snapshot(f"6M {day}", lons, when, errors)
            checked += 1
    else:
        print(f"[FAIL] {path}: unrecognised feed shape")
        return 1

    if errors:
        print(f"[FAIL] frame regression in {path} ({len(errors)} problems):")
        for e in errors[:50]:
            print("   ", e)
        return 1
    print(f"[OK] frame regression passed for {path} ({checked} snapshot(s))")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
