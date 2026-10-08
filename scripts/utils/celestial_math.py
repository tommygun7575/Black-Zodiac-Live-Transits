"""Shared celestial math for daily and 6-month feeds.

All formulas here are explicit geometry or documented Oracle rules.
Unresolvable inputs yield None / unresolved with reason — never invented.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from scripts.utils.coords import OBLIQUITY_J2000_DEG

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STATION_SPEED_THRESHOLD_DEG_PER_DAY = 0.002
DECLINATION_ASPECT_ORB_DEG = 1.0
MIDPOINT_ORB_DEG = 1.5
PATTERN_ORB_DEG = 2.0
EXACT_ASPECT_ORB_DEG = 0.1

# H7 = septile = 360/7 ≈ 51.428571°
SEPTILE_ANGLE_DEG = 360.0 / 7.0

CORE_MIDPOINT_BODIES = (
    "Sun",
    "Moon",
    "Mercury",
    "Venus",
    "Mars",
    "Jupiter",
    "Saturn",
    "Uranus",
    "Neptune",
    "Pluto",
)


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------


def normalize(x: float) -> float:
    """normalize(x) = ((x % 360) + 360) % 360"""
    return ((float(x) % 360.0) + 360.0) % 360.0


def is_finite_number(value: Any) -> bool:
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(number)


def shortest_arc(a: float, b: float) -> float:
    """Shortest angular separation 0..180."""
    diff = abs(normalize(a) - normalize(b)) % 360.0
    return min(diff, 360.0 - diff)


def ecliptic_to_equatorial(
    lon_deg: float,
    lat_deg: float,
    obliquity_deg: float = OBLIQUITY_J2000_DEG,
) -> Tuple[float, float]:
    """Convert ecliptic lon/lat (deg) to equatorial RA/Dec (deg).

    Inverse of coords.ra_dec_to_ecl using the same J2000 obliquity.
    """
    lon = math.radians(normalize(lon_deg))
    lat = math.radians(float(lat_deg))
    eps = math.radians(float(obliquity_deg))

    sin_dec = (
        math.sin(lat) * math.cos(eps)
        + math.cos(lat) * math.sin(eps) * math.sin(lon)
    )
    dec = math.asin(max(-1.0, min(1.0, sin_dec)))

    y = math.sin(lon) * math.cos(eps) - math.tan(lat) * math.sin(eps)
    x = math.cos(lon)
    ra = math.atan2(y, x)

    return normalize(math.degrees(ra)), math.degrees(dec)


def position_longitude(pos: Dict[str, Any]) -> Optional[float]:
    if not isinstance(pos, dict):
        return None
    if pos.get("source") == "unresolved":
        return None
    for key in ("longitude", "ecl_lon_deg"):
        if is_finite_number(pos.get(key)):
            return normalize(float(pos[key]))
    return None


def position_latitude(pos: Dict[str, Any]) -> Optional[float]:
    if not isinstance(pos, dict):
        return None
    for key in ("latitude", "ecl_lat_deg"):
        if is_finite_number(pos.get(key)):
            return float(pos[key])
    return None


def position_declination(pos: Dict[str, Any]) -> Optional[float]:
    if not isinstance(pos, dict):
        return None
    if is_finite_number(pos.get("declination")):
        return float(pos["declination"])
    lon = position_longitude(pos)
    lat = position_latitude(pos)
    if lon is None or lat is None:
        return None
    _, dec = ecliptic_to_equatorial(lon, lat)
    return dec


def position_longitude_speed(pos: Dict[str, Any]) -> Optional[float]:
    """Return λ̇ in deg/day when explicitly present.

    Does NOT treat Horizons vel_obs (km/s) as longitude speed.
    """
    if not isinstance(pos, dict):
        return None
    for key in (
        "longitude_speed",
        "longitude_speed_deg_per_day",
        "lon_speed",
    ):
        if is_finite_number(pos.get(key)):
            return float(pos[key])
    # ``velocity`` is NEVER read as zodiac longitude speed (rule: keep velocity
    # separate from λ̇). Swiss rows already carry an explicit longitude_speed;
    # Horizons rows store vel_obs (km/s) in ``velocity``.
    return None


# ---------------------------------------------------------------------------
# Motion / stations
# ---------------------------------------------------------------------------


# Station eligibility (2026-10-08 transit-workflow rules): only PHYSICAL
# moving bodies may produce true station events. Fixed stars, Aether points,
# the Sun, the Moon and the lunar nodes are excluded (nodes pending approval).
STATION_EXCLUDED_CATEGORIES = frozenset({"fixed_stars", "aether_points", "lunar_nodes"})
STATION_EXCLUDED_BODIES = frozenset(
    {"Sun", "Moon", "True_Node", "Mean_Node", "South_Node"}
)
MOTION_FALLBACK_SOURCES = ["weekly_6h_difference", "six_month_series"]
UNRESOLVED_SPEED_REASON = "longitude_speed_deg_per_day unavailable from resolving provider"


def is_station_eligible(name: str, pos: Optional[Dict[str, Any]] = None) -> bool:
    """True only for physical moving bodies (never stars, Aether, luminaries, nodes)."""
    if str(name) in STATION_EXCLUDED_BODIES:
        return False
    category = (pos or {}).get("category") if isinstance(pos, dict) else None
    if category in STATION_EXCLUDED_CATEGORIES:
        return False
    if isinstance(pos, dict) and pos.get("source") in {"fixed_star_catalog", "fixed"}:
        return False
    return True


def motion_status(
    longitude_speed: Optional[float],
    station_threshold: float = STATION_SPEED_THRESHOLD_DEG_PER_DAY,
    station_eligible: bool = True,
) -> Dict[str, Any]:
    """Classify motion from λ̇ (deg/day) only.

    ``station_eligible=False`` means a near-zero speed is never reported as a
    station (direction is still reported from the sign of λ̇).
    """
    if not is_finite_number(longitude_speed):
        return {
            "retrograde": None,
            "station": None if station_eligible else False,
            "longitude_speed": None,
            "status": "unresolved",
            "reason": UNRESOLVED_SPEED_REASON,
        }
    speed = float(longitude_speed)
    stationary = station_eligible and abs(speed) <= float(station_threshold)
    return {
        "retrograde": speed < 0.0 and not stationary,
        "station": stationary,
        "longitude_speed": speed,
        "status": "station" if stationary else ("retrograde" if speed < 0.0 else "direct"),
        "reason": None,
    }


def classify_position_motion(name: str, pos: Dict[str, Any]) -> Dict[str, Any]:
    """Motion fields for one feed object under the station-eligibility rules."""
    category = pos.get("category") if isinstance(pos, dict) else None
    speed = position_longitude_speed(pos)
    if category == "fixed_stars" or (isinstance(pos, dict) and pos.get("source") == "fixed_star_catalog"):
        return {
            "longitude_speed": speed,
            "retrograde": False,
            "station": False,
            "motion_status": "fixed",
            "station_eligible": False,
            "motion_reason": (
                "fixed star: catalog position (precession only); zero/near-zero "
                "motion is never a station"
            ),
        }
    eligible = is_station_eligible(name, pos)
    motion = motion_status(speed, station_eligible=eligible)
    out: Dict[str, Any] = {
        "longitude_speed": motion["longitude_speed"],
        "retrograde": motion["retrograde"],
        "station": motion["station"],
        "motion_status": motion["status"],
        "station_eligible": eligible,
    }
    if motion["status"] == "unresolved":
        out["motion_reason"] = motion["reason"]
        out["motion_fallback_available"] = list(MOTION_FALLBACK_SOURCES)
    elif not eligible:
        out["motion_reason"] = (
            "not station-eligible (Sun/Moon/nodes/Aether excluded); direction "
            "from longitude_speed sign only"
        )
    return out


def enrich_motion_fields(
    positions: Dict[str, Dict[str, Any]],
    obliquity_deg: float = OBLIQUITY_J2000_DEG,
) -> Dict[str, Dict[str, Any]]:
    """Attach declination + motion fields in-place-safe copy style.

    Pass the TRUE obliquity of date when longitudes are ecliptic-of-date so
    RA/Dec are apparent-of-date and consistent with provider RA/Dec.
    Positions (longitude/latitude/distance/velocity) are never modified.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for name, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        entry = dict(pos)
        lon = position_longitude(entry)
        lat = position_latitude(entry)
        if lon is not None and lat is not None and not is_finite_number(entry.get("declination")):
            ra, dec = ecliptic_to_equatorial(lon, lat, obliquity_deg)
            entry["right_ascension"] = ra
            entry["declination"] = dec
        entry.pop("motion_reason", None)
        entry.pop("motion_fallback_available", None)
        entry.update(classify_position_motion(name, entry))
        out[name] = entry
    return out


def collect_stations(
    positions: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Daily motion summary. Only station-eligible physical bodies are listed.

    The daily feed is NOT the authoritative station source (six-month series
    is). ``items`` lists eligible bodies that are retrograde or within the
    near-zero speed threshold at the daily instant.
    """
    stations: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for name in sorted(positions.keys()):
        pos = positions[name]
        if position_longitude(pos) is None:
            continue
        cls = classify_position_motion(name, pos)
        if not cls["station_eligible"]:
            if pos.get("category") == "lunar_nodes" and cls["motion_status"] != "unresolved":
                excluded.append(
                    {
                        "body": name,
                        "status": cls["motion_status"],
                        "longitude_speed": cls["longitude_speed"],
                        "category": pos.get("category"),
                    }
                )
            continue
        if cls["motion_status"] == "unresolved":
            unresolved.append({"body": name, "reason": cls["motion_reason"]})
            continue
        if cls["station"] or cls["retrograde"]:
            stations.append(
                {
                    "body": name,
                    "status": cls["motion_status"],
                    "longitude_speed": cls["longitude_speed"],
                    "longitude": position_longitude(pos),
                }
            )
    return {
        "items": stations,
        "true_station_source": False,
        "station_events_count": sum(1 for s in stations if s["status"] == "station"),
        "unresolved_motion_count": len(unresolved),
        "unresolved_sample": unresolved[:20],
        "unresolved_motion_fallback": list(MOTION_FALLBACK_SOURCES),
        "excluded_node_motion": excluded,
        "eligibility": (
            "physical moving bodies only; fixed stars, Aether points, Sun, Moon "
            "and lunar nodes never produce station events"
        ),
        "note": (
            "Station/retrograde requires longitude_speed deg/day (velocity is "
            "never used). Daily |λ̇| <= 0.002 deg/day is a near-station "
            "indicator only; authoritative station timing comes from the "
            "six-month series. Null speeds stay unresolved (no fabrication)."
        ),
    }


# ---------------------------------------------------------------------------
# Lunar geometry
# ---------------------------------------------------------------------------


def lunar_geometry(
    positions: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    sun = position_longitude(positions.get("Sun", {}))
    moon = position_longitude(positions.get("Moon", {}))
    if sun is None or moon is None:
        return {
            "status": "unresolved",
            "reason": "Sun and/or Moon longitude missing",
        }

    elongation = normalize(moon - sun)
    # Phase illumination fraction for a spherical Moon illuminated by the Sun:
    # (1 - cos(phase_angle)) / 2 where phase_angle ≈ elongation for geocentric approx.
    illumination = (1.0 - math.cos(math.radians(elongation))) / 2.0

    if elongation < 22.5 or elongation >= 337.5:
        phase_name = "New Moon"
    elif elongation < 67.5:
        phase_name = "Waxing Crescent"
    elif elongation < 112.5:
        phase_name = "First Quarter"
    elif elongation < 157.5:
        phase_name = "Waxing Gibbous"
    elif elongation < 202.5:
        phase_name = "Full Moon"
    elif elongation < 247.5:
        phase_name = "Waning Gibbous"
    elif elongation < 292.5:
        phase_name = "Last Quarter"
    else:
        phase_name = "Waning Crescent"

    true_node = position_longitude(positions.get("True_Node", {}))
    mean_node = position_longitude(positions.get("Mean_Node", {}))
    south_node = position_longitude(positions.get("South_Node", {}))
    if south_node is None and true_node is not None:
        south_node = normalize(true_node + 180.0)

    result: Dict[str, Any] = {
        "status": "ok",
        "sun_moon_elongation_deg": elongation,
        "illumination_fraction": illumination,
        "phase_name": phase_name,
        "moon_longitude": moon,
        "sun_longitude": sun,
    }
    if true_node is not None:
        result["true_node_longitude"] = true_node
        result["moon_node_separation_deg"] = shortest_arc(moon, true_node)
    if mean_node is not None:
        result["mean_node_longitude"] = mean_node
    if south_node is not None:
        result["south_node_longitude"] = south_node
    return result


# ---------------------------------------------------------------------------
# Midpoints
# ---------------------------------------------------------------------------


def body_midpoint(lon_a: float, lon_b: float) -> float:
    """Circular midpoint along the shorter arc."""
    a = normalize(lon_a)
    b = normalize(lon_b)
    diff = ((b - a + 180.0) % 360.0) - 180.0
    return normalize(a + diff / 2.0)


def compute_midpoints(
    positions: Dict[str, Dict[str, Any]],
    bodies: Sequence[str] = CORE_MIDPOINT_BODIES,
) -> List[Dict[str, Any]]:
    resolved = {
        name: position_longitude(positions.get(name, {}))
        for name in bodies
    }
    resolved = {k: v for k, v in resolved.items() if v is not None}
    out: List[Dict[str, Any]] = []
    for a, b in combinations(sorted(resolved.keys()), 2):
        out.append(
            {
                "body_a": a,
                "body_b": b,
                "longitude": body_midpoint(resolved[a], resolved[b]),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Aspect motion (applying / exact / separating)
# ---------------------------------------------------------------------------


def aspect_motion_status(
    lon_a: float,
    lon_b: float,
    speed_a: Optional[float],
    speed_b: Optional[float],
    exact_angle: float,
    orb: float,
    exact_orb: float = EXACT_ASPECT_ORB_DEG,
) -> Dict[str, Any]:
    """Classify aspect as applying / exact / separating using relative λ̇.

    If speeds unavailable → status unresolved with reason (no invention).
    """
    separation = shortest_arc(lon_a, lon_b)
    if orb <= exact_orb:
        return {
            "motion": "exact",
            "reason": None,
            "relative_speed": None,
        }

    if not is_finite_number(speed_a) or not is_finite_number(speed_b):
        return {
            "motion": "unresolved",
            "reason": "longitude_speed unavailable for one or both bodies",
            "relative_speed": None,
        }

    # Signed offset from exact angle along shortest path direction of B-A.
    delta = ((lon_b - lon_a + 180.0) % 360.0) - 180.0
    # Target offsets at ±exact_angle
    # Closing rate: how fast |separation - exact| shrinks.
    # Use d/dt of angular distance to nearest exact target.
    targets = (exact_angle, -exact_angle)
    best_target = min(targets, key=lambda t: abs(delta - t))
    offset = delta - best_target
    rel_speed = float(speed_b) - float(speed_a)  # deg/day of delta

    # If relative motion drives offset toward 0, aspect is applying.
    if abs(offset) <= exact_orb:
        motion = "exact"
    elif offset * rel_speed < 0:
        motion = "applying"
    elif offset * rel_speed > 0:
        motion = "separating"
    else:
        motion = "exact"

    return {
        "motion": motion,
        "reason": None,
        "relative_speed": rel_speed,
    }


# ---------------------------------------------------------------------------
# Declination aspects
# ---------------------------------------------------------------------------


def declination_aspects(
    positions: Dict[str, Dict[str, Any]],
    orb: float = DECLINATION_ASPECT_ORB_DEG,
    bodies: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    names = list(bodies) if bodies is not None else sorted(positions.keys())
    decs: Dict[str, float] = {}
    for name in names:
        pos = positions.get(name)
        if not pos:
            continue
        # Skip fixed stars for body-body declination grid (still allow if wanted)
        cat = str(pos.get("category") or "").lower()
        if cat in {"fixed_stars", "fixed stars"}:
            continue
        dec = position_declination(pos)
        if dec is not None:
            decs[name] = dec

    matches: List[Dict[str, Any]] = []
    for a, b in combinations(sorted(decs.keys()), 2):
        da, db = decs[a], decs[b]
        if abs(da - db) <= orb:
            matches.append(
                {
                    "body_a": a,
                    "body_b": b,
                    "type": "parallel",
                    "declination_a": da,
                    "declination_b": db,
                    "orb": abs(da - db),
                }
            )
        if abs(da + db) <= orb:
            matches.append(
                {
                    "body_a": a,
                    "body_b": b,
                    "type": "contraparallel",
                    "declination_a": da,
                    "declination_b": db,
                    "orb": abs(da + db),
                }
            )
    matches.sort(key=lambda m: (m["orb"], m["body_a"], m["body_b"], m["type"]))
    return matches


# ---------------------------------------------------------------------------
# Geometric patterns
# ---------------------------------------------------------------------------


def _has_aspect(
    lon_a: float,
    lon_b: float,
    angle: float,
    orb: float,
) -> bool:
    return abs(shortest_arc(lon_a, lon_b) - angle) <= orb


def geometric_patterns(
    positions: Dict[str, Dict[str, Any]],
    bodies: Sequence[str] = CORE_MIDPOINT_BODIES,
    orb: float = PATTERN_ORB_DEG,
) -> List[Dict[str, Any]]:
    resolved = {
        name: position_longitude(positions.get(name, {}))
        for name in bodies
    }
    resolved = {k: v for k, v in resolved.items() if v is not None}
    names = sorted(resolved.keys())
    patterns: List[Dict[str, Any]] = []

    # Grand Trine: three mutual 120°
    for a, b, c in combinations(names, 3):
        la, lb, lc = resolved[a], resolved[b], resolved[c]
        if (
            _has_aspect(la, lb, 120.0, orb)
            and _has_aspect(lb, lc, 120.0, orb)
            and _has_aspect(la, lc, 120.0, orb)
        ):
            patterns.append(
                {
                    "type": "grand_trine",
                    "bodies": [a, b, c],
                    "orb_max": max(
                        abs(shortest_arc(la, lb) - 120.0),
                        abs(shortest_arc(lb, lc) - 120.0),
                        abs(shortest_arc(la, lc) - 120.0),
                    ),
                }
            )

    # T-Square: opposition + two squares to a third
    for a, b in combinations(names, 2):
        la, lb = resolved[a], resolved[b]
        if not _has_aspect(la, lb, 180.0, orb):
            continue
        for c in names:
            if c in {a, b}:
                continue
            lc = resolved[c]
            if _has_aspect(la, lc, 90.0, orb) and _has_aspect(lb, lc, 90.0, orb):
                patterns.append(
                    {
                        "type": "t_square",
                        "bodies": [a, b, c],
                        "apex": c,
                        "opposition": [a, b],
                    }
                )

    # Grand Cross: four bodies with two oppositions and squares
    for quartet in combinations(names, 4):
        q = list(quartet)
        opps = []
        squares = 0
        for a, b in combinations(q, 2):
            sep = shortest_arc(resolved[a], resolved[b])
            if abs(sep - 180.0) <= orb:
                opps.append((a, b))
            elif abs(sep - 90.0) <= orb:
                squares += 1
        if len(opps) >= 2 and squares >= 4:
            patterns.append({"type": "grand_cross", "bodies": q})

    # Yod: two quincunxes (150°) from apex to base pair in sextile (60°)
    for a, b in combinations(names, 2):
        la, lb = resolved[a], resolved[b]
        if not _has_aspect(la, lb, 60.0, orb):
            continue
        for c in names:
            if c in {a, b}:
                continue
            lc = resolved[c]
            if _has_aspect(la, lc, 150.0, orb) and _has_aspect(lb, lc, 150.0, orb):
                patterns.append(
                    {
                        "type": "yod",
                        "bodies": [a, b, c],
                        "apex": c,
                        "base": [a, b],
                    }
                )

    # Stellium: 3+ bodies within a tight cluster span
    cluster_orb = 8.0
    for trio in combinations(names, 3):
        lons = [resolved[n] for n in trio]
        # Check pairwise short arcs all <= cluster_orb*2 and circular span
        if all(shortest_arc(x, y) <= cluster_orb for x, y in combinations(lons, 2)):
            patterns.append(
                {
                    "type": "stellium",
                    "bodies": list(trio),
                    "span_deg": max(shortest_arc(x, y) for x, y in combinations(lons, 2)),
                }
            )

    patterns.sort(key=lambda p: (p["type"], ",".join(p["bodies"])))
    return patterns


# ---------------------------------------------------------------------------
# Aether (verified only)
# ---------------------------------------------------------------------------


def compute_aether_longitudes(
    sun: Optional[float],
    moon: Optional[float],
    venus: Optional[float],
    mars: Optional[float],
    jupiter: Optional[float],
    saturn: Optional[float],
) -> Dict[str, Optional[float]]:
    """Exactly the three verified Oracle Aether formulas."""
    return {
        "Aetheric_SunMoon_Midpoint": (
            None
            if sun is None or moon is None
            else normalize(sun + moon)
        ),
        "Aetheric_Jovian_Arc": (
            None
            if jupiter is None or saturn is None
            else normalize(jupiter - saturn)
        ),
        "Aetheric_Elemental_Balance": (
            None
            if moon is None or venus is None or mars is None
            else normalize((moon + venus + mars) / 3.0)
        ),
    }


# ---------------------------------------------------------------------------
# Houses / Arabic parts policy helpers
# ---------------------------------------------------------------------------


HOUSES_POLICY = {
    "status": "user_specific_downstream",
    "reason": (
        "Geocentric public feed has no universal observer location. "
        "House cusps, ASC, and MC require user/natal lat/lon and must be "
        "computed downstream (Swiss swe.houses / generate_feed_overlay."
        "compute_house_cusps). Cusps are not fabricated here."
    ),
}


def arabic_parts_unavailable_payload() -> Dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": (
            "Arabic parts require Ascendant; Ascendant requires observer "
            "lat/lon. Use scripts.calculate_aspects.arabic_parts with a "
            "user location downstream."
        ),
        "Part_of_Fortune": None,
        "Part_of_Spirit": None,
        "Part_of_Eros": None,
    }
