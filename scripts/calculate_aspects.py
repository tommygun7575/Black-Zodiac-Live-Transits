from __future__ import annotations

from itertools import combinations
from typing import Any, Dict, List


def _norm_diff(a: float, b: float) -> float:
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def harmonic_aspects(positions: Dict[str, Dict[str, Any]], orb: float = 1.5) -> List[Dict[str, Any]]:
    aspects: List[Dict[str, Any]] = []
    valid = {k: v for k, v in positions.items() if v.get("longitude") is not None and v.get("category") != "fixed stars"}
    for left, right in combinations(valid.keys(), 2):
        a = valid[left]["longitude"]
        b = valid[right]["longitude"]
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


def arabic_parts(positions: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    asc = 0.0
    sun = positions.get("Sun", {}).get("longitude")
    moon = positions.get("Moon", {}).get("longitude")
    if sun is None or moon is None:
        return {}
    day_chart = ((sun - asc) % 360.0) < 180.0
    fortune = (asc + ((moon - sun) if day_chart else (sun - moon))) % 360.0
    spirit = (asc + ((sun - moon) if day_chart else (moon - sun))) % 360.0
    eros = (asc + moon - venus) % 360.0 if (venus := positions.get("Venus", {}).get("longitude")) is not None else None
    parts = {"Part_of_Fortune": fortune, "Part_of_Spirit": spirit}
    if eros is not None:
        parts["Part_of_Eros"] = eros
    return parts


def fixed_star_conjunctions(positions: Dict[str, Dict[str, Any]], orb: float = 1.0) -> List[Dict[str, Any]]:
    stars = {k: v for k, v in positions.items() if v.get("category") == "fixed stars" and v.get("longitude") is not None}
    bodies = {k: v for k, v in positions.items() if v.get("category") != "fixed stars" and v.get("longitude") is not None}

    matches: List[Dict[str, Any]] = []
    for body_name, body in bodies.items():
        for star_name, star in stars.items():
            delta = _norm_diff(body["longitude"], star["longitude"])
            if delta <= orb:
                matches.append({"body": body_name, "fixed_star": star_name, "orb": delta})
    return matches
