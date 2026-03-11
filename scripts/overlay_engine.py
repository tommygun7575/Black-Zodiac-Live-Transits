from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, List

from scripts.fetch_ephemeris import fetch_all_positions


def _norm_diff(a: float, b: float) -> float:
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def _birth_utc(profile: Dict[str, Any]) -> datetime:
    local = datetime.strptime(f"{profile['birth_date']} {profile['birth_time']}", "%m-%d-%Y %I:%M %p")
    return local.replace(tzinfo=ZoneInfo(profile["timezone"])).astimezone(ZoneInfo("UTC"))


def build_natal_positions(natal_profiles: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    natal_positions: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for name, profile in natal_profiles.items():
        natal_positions[name] = fetch_all_positions(_birth_utc(profile))
    return natal_positions


def generate_overlays(
    transit_positions: Dict[str, Dict[str, Any]],
    natal_positions: Dict[str, Dict[str, Dict[str, Any]]],
    orb: float = 2.0,
) -> Dict[str, List[Dict[str, Any]]]:
    overlays: Dict[str, List[Dict[str, Any]]] = {}
    for person, natal in natal_positions.items():
        matches: List[Dict[str, Any]] = []
        for body, tpos in transit_positions.items():
            if tpos.get("longitude") is None or tpos.get("category") == "fixed stars":
                continue
            npos = natal.get(body)
            if not npos or npos.get("longitude") is None:
                continue
            delta = _norm_diff(tpos["longitude"], npos["longitude"])
            if delta <= orb:
                matches.append({"body": body, "natal_longitude": npos["longitude"], "transit_longitude": tpos["longitude"], "orb": delta})
        overlays[person] = matches
    return overlays
