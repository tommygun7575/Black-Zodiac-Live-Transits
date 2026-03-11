from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Dict, List

import swisseph as swe


def _is_valid_longitude(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _norm_diff(a: float, b: float) -> float:
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def harmonic_aspects(positions: Dict[str, Dict[str, Any]], orb: float = 1.5) -> List[Dict[str, Any]]:
    aspects: List[Dict[str, Any]] = []
    valid = {
        k: v
        for k, v in positions.items()
        if _is_valid_longitude(v.get("longitude")) and v.get("category") not in {"fixed stars", "fixed_stars"}
    }
    for left, right in combinations(valid.keys(), 2):
        a = float(valid[left]["longitude"])
        b = float(valid[right]["longitude"])
        diff = _norm_diff(a, b)
        for harmonic in (2, 3, 4, 5, 6, 8, 9, 12):
            angle = 360.0 / harmonic
            if abs(diff - angle) <= orb:
                aspects.append(
                    {
                        "body_a": left,
                        "body_b": right,
                        "harmonic": harmonic,
                        "exact_angle": angle,
                        "separation": diff,
                        "orb": abs(diff - angle),
                    }
                )
    return aspects


def _ascendant_longitude(jd_ut: float, latitude: float, longitude: float) -> float:
    houses = swe.houses(jd_ut, latitude, longitude)
    return float(houses[0][0])


def arabic_parts(
    positions: Dict[str, Dict[str, Any]],
    timestamp: str,
    latitude: float,
    longitude: float,
) -> Dict[str, Any]:
    parts: Dict[str, Any] = {
        "Part_of_Fortune": None,
        "Part_of_Spirit": None,
        "Part_of_Eros": None,
    }
    sun = positions.get("Sun", {}).get("longitude")
    moon = positions.get("Moon", {}).get("longitude")
    venus = positions.get("Venus", {}).get("longitude")
    if not _is_valid_longitude(sun) or not _is_valid_longitude(moon):
        return parts

    try:
        dt = timestamp.replace("Z", "")
        date_part, time_part = dt.split("T")
        y, m, d = [int(x) for x in date_part.split("-")]
        hh, mm, ss = time_part.split(":")
        sec = float(ss)
        jd_ut = swe.julday(y, m, d, int(hh) + int(mm) / 60.0 + sec / 3600.0)
        asc = _ascendant_longitude(jd_ut, latitude, longitude)
    except Exception:
        return parts

    parts["Part_of_Fortune"] = (asc + float(moon) - float(sun)) % 360.0
    parts["Part_of_Spirit"] = (asc + float(sun) - float(moon)) % 360.0
    if _is_valid_longitude(venus):
        parts["Part_of_Eros"] = (asc + float(moon) - float(venus)) % 360.0
    return parts


def fixed_star_conjunctions(positions: Dict[str, Dict[str, Any]], orb: float = 1.0) -> List[Dict[str, Any]]:
    stars = {
        k: v
        for k, v in positions.items()
        if v.get("category") in {"fixed stars", "fixed_stars"} and _is_valid_longitude(v.get("longitude"))
    }
    bodies = {
        k: v
        for k, v in positions.items()
        if v.get("category") not in {"fixed stars", "fixed_stars"} and _is_valid_longitude(v.get("longitude"))
    }

    matches: List[Dict[str, Any]] = []
    for body_name, body in bodies.items():
        for star_name, star in stars.items():
            delta = _norm_diff(float(body["longitude"]), float(star["longitude"]))
            if delta <= orb:
                matches.append({"body": body_name, "fixed_star": star_name, "orb": delta})
    return matches
