"""House cusps and Arabic Parts for the reference natal observer.

Uses Swiss Ephemeris Placidus (same engine as generate_feed_overlay /
calculate_aspects). Arabic Part formulas are only those already defined
in-repo; missing formulas stay unavailable (no fabrication).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import swisseph as swe

from scripts.utils.celestial_math import normalize, position_longitude

ROOT = Path(__file__).resolve().parents[2]

# Core natal bodies resolved via Swiss when mapped — Horizons historical
# observer-table ecliptic parse in this repo is unreliable for Moon/Venus
# (e.g. 1975-09-12 Moon ~349° vs Swiss/kitchen-sink ~259.8°).
NATAL_SWISS_PREF_BODIES = (
    "Sun", "Moon", "Mercury", "Venus", "Mars",
    "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto",
    "Chiron", "True_Node", "Mean_Node",
)
NATAL_OBSERVER_PATH = ROOT / "config" / "natal_observer.json"
EPHE_PATH = ROOT / "ephe"

# Formulas already present in scripts/generate_feed_overlay.compute_arabic_parts
# plus Part_of_Eros from scripts/calculate_aspects.arabic_parts.
# Part_of_Necessity is NOT defined anywhere in-repo → unavailable.

FORMULA_FORTUNE_DAY = "ASC + Moon - Sun"
FORMULA_FORTUNE_NIGHT = "ASC + Sun - Moon"
FORMULA_SPIRIT_DAY = "ASC + Sun - Moon"
FORMULA_SPIRIT_NIGHT = "ASC + Moon - Sun"
FORMULA_EROS = "ASC + Moon - Venus"
FORMULA_KARMA = "ASC + (Sun + Moon) / 2"
FORMULA_TREACHERY = "ASC + Moon - Karma"
FORMULA_VICTORY = "ASC + Sun - Karma"
FORMULA_DELIVERANCE = "ASC + Spirit - Fortune"

SECT_RULE = (
    "day = Sun in Placidus houses 7–12 (above horizon); "
    "night = Sun in houses 1–6. "
    "Replaces the inverted (sun-asc)%360<180 check in legacy "
    "generate_feed_overlay so sect matches classical above-horizon day charts."
)


def _ensure_ephe() -> None:
    swe.set_ephe_path(str(EPHE_PATH))


def load_natal_observer(path: Path = NATAL_OBSERVER_PATH) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def birth_datetime_utc(observer: Dict[str, Any]) -> datetime:
    birth = observer["birth"]
    # Prefer explicit UTC if present; else compose from local + timezone.
    utc_iso = birth.get("datetime_utc_iso")
    if utc_iso:
        cleaned = str(utc_iso).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).astimezone(timezone.utc)

    date = birth["date"]
    time_local = birth["time_local"]
    tz = ZoneInfo(birth["timezone"])
    local = datetime.strptime(f"{date} {time_local}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    return local.astimezone(timezone.utc)


def datetime_to_jd_ut(dt: datetime) -> float:
    dt_utc = dt.astimezone(timezone.utc)
    hour = (
        dt_utc.hour
        + dt_utc.minute / 60.0
        + dt_utc.second / 3600.0
        + dt_utc.microsecond / 3_600_000_000.0
    )
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour)


def house_number_for_longitude(lon: float, cusps_1_to_12: List[float]) -> int:
    """Return Placidus house 1..12 for ecliptic longitude."""
    lon_n = normalize(lon)
    for i in range(12):
        a = normalize(cusps_1_to_12[i])
        b = normalize(cusps_1_to_12[(i + 1) % 12])
        if a < b:
            if a <= lon_n < b:
                return i + 1
        else:
            # wrap across 0°
            if lon_n >= a or lon_n < b:
                return i + 1
    return 12


def compute_houses_and_angles(
    dt: datetime,
    latitude: float,
    longitude: float,
    *,
    hsys: str = "P",
    context: str = "transit",
    place_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Swiss Placidus house cusps + ASC/MC/DSC/IC at dt/lat/lon."""
    _ensure_ephe()
    jd = datetime_to_jd_ut(dt)
    cusps, ascmc = swe.houses(float(jd), float(latitude), float(longitude), hsys.encode("utf-8"))
    # pyswisseph returns 12 cusps (House 1..12). Older C API used 13 with [0] unused.
    if len(cusps) == 13:
        cusp_list = [float(cusps[i]) for i in range(1, 13)]
    else:
        cusp_list = [float(c) for c in cusps]

    asc = normalize(float(ascmc[0]))
    mc = normalize(float(ascmc[1]))
    dsc = normalize(asc + 180.0)
    ic = normalize(mc + 180.0)

    houses = {f"House_{i}": normalize(cusp_list[i - 1]) for i in range(1, 13)}
    return {
        "status": "computed",
        "context": context,
        "system": hsys,
        "system_name": "Placidus" if hsys == "P" else hsys,
        "engine": "swisseph.houses",
        "timestamp_utc": dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "latitude": float(latitude),
        "longitude": float(longitude),
        "place_name": place_name,
        "julian_day_ut": float(jd),
        "cusps": houses,
        "angles": {
            "ASC": asc,
            "MC": mc,
            "DSC": dsc,
            "IC": ic,
        },
        "reason": None,
        "provenance": (
            f"{context} houses at observer lat/lon via Swiss Placidus; "
            "DSC=ASC+180, IC=MC+180; cusps not fabricated."
        ),
    }


def _part_entry(
    *,
    name: str,
    longitude: Optional[float],
    formula: str,
    inputs: Dict[str, Any],
    status: str = "computed",
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "longitude": None if longitude is None else normalize(longitude),
        "formula": formula,
        "inputs": inputs,
        "reason": reason,
        "provenance": "in-repo formula" if status == "computed" else "unavailable",
    }


def compute_arabic_parts_from_longitudes(
    *,
    asc: float,
    sun: float,
    moon: float,
    venus: Optional[float],
    sun_house: Optional[int],
    chart_context: str = "natal",
) -> Dict[str, Any]:
    """Sect-aware Fortune/Spirit + in-repo extended parts. Necessity stays unavailable."""
    if sun_house is None:
        return {
            "status": "unavailable",
            "reason": "Sun house placement required for sect; missing inputs",
            "chart_context": chart_context,
            "sect": None,
            "parts": {},
            "unresolved": ["Part_of_Fortune", "Part_of_Spirit", "Part_of_Eros",
                           "Part_of_Karma", "Part_of_Victory", "Part_of_Treachery",
                           "Part_of_Deliverance", "Part_of_Necessity"],
        }

    is_day = int(sun_house) >= 7
    sect = "day" if is_day else "night"

    if is_day:
        fortune = normalize(asc + moon - sun)
        spirit = normalize(asc + sun - moon)
        f_formula, s_formula = FORMULA_FORTUNE_DAY, FORMULA_SPIRIT_DAY
    else:
        fortune = normalize(asc + sun - moon)
        spirit = normalize(asc + moon - sun)
        f_formula, s_formula = FORMULA_FORTUNE_NIGHT, FORMULA_SPIRIT_NIGHT

    base_inputs = {
        "ASC": normalize(asc),
        "Sun": normalize(sun),
        "Moon": normalize(moon),
        "sect": sect,
        "sun_house": sun_house,
        "sect_rule": SECT_RULE,
    }

    parts: Dict[str, Any] = {
        "Part_of_Fortune": _part_entry(
            name="Part_of_Fortune",
            longitude=fortune,
            formula=f_formula,
            inputs=base_inputs,
        ),
        "Part_of_Spirit": _part_entry(
            name="Part_of_Spirit",
            longitude=spirit,
            formula=s_formula,
            inputs=base_inputs,
        ),
    }

    # Eros — calculate_aspects.arabic_parts (ASC + Moon - Venus); no sect variant in-repo
    if venus is not None:
        eros = normalize(asc + moon - venus)
        parts["Part_of_Eros"] = _part_entry(
            name="Part_of_Eros",
            longitude=eros,
            formula=FORMULA_EROS,
            inputs={**base_inputs, "Venus": normalize(venus)},
        )
    else:
        parts["Part_of_Eros"] = _part_entry(
            name="Part_of_Eros",
            longitude=None,
            formula=FORMULA_EROS,
            inputs=base_inputs,
            status="unavailable",
            reason="Venus longitude missing",
        )

    # Extended parts from generate_feed_overlay.compute_arabic_parts
    karma = normalize(asc + (sun + moon) / 2.0)
    treachery = normalize(asc + moon - karma)
    victory = normalize(asc + sun - karma)
    deliverance = normalize(asc + spirit - fortune)

    parts["Part_of_Karma"] = _part_entry(
        name="Part_of_Karma",
        longitude=karma,
        formula=FORMULA_KARMA,
        inputs=base_inputs,
    )
    parts["Part_of_Treachery"] = _part_entry(
        name="Part_of_Treachery",
        longitude=treachery,
        formula=FORMULA_TREACHERY,
        inputs={**base_inputs, "Karma": karma},
    )
    parts["Part_of_Victory"] = _part_entry(
        name="Part_of_Victory",
        longitude=victory,
        formula=FORMULA_VICTORY,
        inputs={**base_inputs, "Karma": karma},
    )
    parts["Part_of_Deliverance"] = _part_entry(
        name="Part_of_Deliverance",
        longitude=deliverance,
        formula=FORMULA_DELIVERANCE,
        inputs={**base_inputs, "Spirit": spirit, "Fortune": fortune},
    )

    # Necessity — no in-repo formula
    parts["Part_of_Necessity"] = _part_entry(
        name="Part_of_Necessity",
        longitude=None,
        formula="",
        inputs={},
        status="unavailable",
        reason="No Part_of_Necessity formula defined in-repo; not fabricated",
    )

    unresolved = [
        name for name, entry in parts.items() if entry.get("status") != "computed"
    ]

    # Flat legacy keys for schema consumers (nullable numbers)
    flat = {
        "Part_of_Fortune": parts["Part_of_Fortune"]["longitude"],
        "Part_of_Spirit": parts["Part_of_Spirit"]["longitude"],
        "Part_of_Eros": parts["Part_of_Eros"]["longitude"],
        "Part_of_Karma": parts["Part_of_Karma"]["longitude"],
        "Part_of_Victory": parts["Part_of_Victory"]["longitude"],
        "Part_of_Treachery": parts["Part_of_Treachery"]["longitude"],
        "Part_of_Deliverance": parts["Part_of_Deliverance"]["longitude"],
        "Part_of_Necessity": None,
    }

    return {
        "status": "computed",
        "chart_context": chart_context,
        "sect": sect,
        "sect_rule": SECT_RULE,
        "reason": None,
        "parts": parts,
        "unresolved": unresolved,
        **flat,
    }


def compute_arabic_parts_for_chart(
    positions: Dict[str, Dict[str, Any]],
    houses_payload: Dict[str, Any],
    *,
    chart_context: str = "natal",
) -> Dict[str, Any]:
    asc = (houses_payload.get("angles") or {}).get("ASC")
    if asc is None:
        return {
            "status": "unavailable",
            "reason": "ASC missing from houses payload",
            "chart_context": chart_context,
            "Part_of_Fortune": None,
            "Part_of_Spirit": None,
            "Part_of_Eros": None,
            "parts": {},
            "unresolved": ["ASC"],
        }

    sun = position_longitude(positions.get("Sun", {}))
    moon = position_longitude(positions.get("Moon", {}))
    venus = position_longitude(positions.get("Venus", {}))
    if sun is None or moon is None:
        return {
            "status": "unavailable",
            "reason": "Sun and/or Moon longitude missing",
            "chart_context": chart_context,
            "Part_of_Fortune": None,
            "Part_of_Spirit": None,
            "Part_of_Eros": None,
            "parts": {},
            "unresolved": ["Sun" if sun is None else None, "Moon" if moon is None else None],
        }

    cusp_map = houses_payload.get("cusps") or {}
    cusps = [float(cusp_map[f"House_{i}"]) for i in range(1, 13)]
    sun_house = house_number_for_longitude(sun, cusps)
    return compute_arabic_parts_from_longitudes(
        asc=float(asc),
        sun=float(sun),
        moon=float(moon),
        venus=None if venus is None else float(venus),
        sun_house=sun_house,
        chart_context=chart_context,
    )



def apply_swiss_preference_for_natal(
    positions: Dict[str, Dict[str, Any]],
    dt: datetime,
) -> Dict[str, Dict[str, Any]]:
    """Overlay Swiss longitudes for natal core bodies when Swiss resolves.

    Preserves category/timestamp; records preference reason on each body.
    Does not invent coordinates — Swiss miss leaves prior provider value.
    """
    from scripts.fetch_ephemeris import SWISS_CODES, _swiss_position

    out = dict(positions)
    for name in NATAL_SWISS_PREF_BODIES:
        body = {
            "name": name,
            "swiss_code": SWISS_CODES.get(name.lower()),
        }
        try:
            swiss = _swiss_position(body, dt)
        except Exception:
            swiss = None
        if not swiss or not isinstance(swiss.get("longitude"), (int, float)):
            continue
        prior = out.get(name) or {}
        merged = dict(prior)
        merged.update(swiss)
        if prior.get("category"):
            merged["category"] = prior["category"]
        merged["source"] = "swiss"
        merged["natal_provider_preference"] = (
            "swiss_preferred_for_natal; Horizons historical ecliptic "
            "in this client disagreed with Swiss/kitchen-sink for Moon/Venus"
        )
        if prior.get("source") and prior.get("source") != "swiss":
            merged["replaced_provider"] = prior.get("source")
            prior_lon = position_longitude(prior)
            if prior_lon is not None:
                merged["replaced_longitude"] = prior_lon
        out[name] = merged

    true_lon = position_longitude(out.get("True_Node", {}))
    if true_lon is not None:
        prior = out.get("South_Node") or {}
        out["South_Node"] = {
            **prior,
            "longitude": normalize(true_lon + 180.0),
            "latitude": 0.0,
            "source": "calculated",
            "category": prior.get("category") or "lunar_nodes",
            "timestamp": (out.get("True_Node") or {}).get("timestamp"),
            "natal_provider_preference": "derived from Swiss True_Node",
        }
    return out


def build_observer_layers(
    *,
    transit_dt_utc: datetime,
    transit_positions: Dict[str, Dict[str, Any]],
    natal_positions: Dict[str, Dict[str, Any]],
    observer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Daily houses at Bronx+transit time; natal chart + natal Arabic Parts."""
    observer = observer or load_natal_observer()
    birth = observer["birth"]
    lat = float(birth["latitude"])
    lon = float(birth["longitude"])
    place = birth.get("place_name")

    transit_houses = compute_houses_and_angles(
        transit_dt_utc,
        lat,
        lon,
        hsys=str(observer.get("houses", {}).get("system") or "P"),
        context="daily_transit",
        place_name=place,
    )

    natal_dt = birth_datetime_utc(observer)
    natal_positions = apply_swiss_preference_for_natal(natal_positions, natal_dt)
    natal_houses = compute_houses_and_angles(
        natal_dt,
        lat,
        lon,
        hsys=str(observer.get("houses", {}).get("system") or "P"),
        context="natal",
        place_name=place,
    )

    natal_parts = compute_arabic_parts_for_chart(
        natal_positions,
        natal_houses,
        chart_context="natal",
    )

    # Core natal planet longitudes for the feed block (resolved only)
    natal_core = {}
    for name in (
        "Sun", "Moon", "Mercury", "Venus", "Mars",
        "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto", "Chiron",
        "True_Node", "Mean_Node", "South_Node",
    ):
        pos = natal_positions.get(name)
        if not isinstance(pos, dict):
            continue
        lon_v = position_longitude(pos)
        if lon_v is None:
            natal_core[name] = {
                "longitude": None,
                "latitude": pos.get("latitude"),
                "source": pos.get("source", "unresolved"),
                "status": "unresolved",
                "reason": pos.get("reason"),
            }
        else:
            natal_core[name] = {
                "longitude": lon_v,
                "latitude": pos.get("latitude"),
                "source": pos.get("source"),
                "status": "ok",
                "category": pos.get("category"),
            }

    natal_chart = {
        "status": "computed",
        "person": observer.get("person"),
        "observer_id": observer.get("id"),
        "birth": {
            "date": birth["date"],
            "time_local": birth["time_local"],
            "timezone": birth["timezone"],
            "datetime_utc": natal_dt.isoformat().replace("+00:00", "Z"),
            "place_name": place,
            "latitude": lat,
            "longitude": lon,
            "geocode_provider": (birth.get("geocode") or {}).get("provider"),
        },
        "houses_and_angles": natal_houses,
        "planets": natal_core,
        "arabic_parts": natal_parts,
        "provenance": (
            "Natal chart at birth datetime America/New_York Bronx; "
            "planets via daily provider stack (Horizons→Miriade→Swiss); "
            "houses via Swiss Placidus; Arabic Parts from natal ASC + natal planets."
        ),
    }

    # Top-level arabic_parts = natal parts (mission: parts from natal ASC + planets)
    # Top-level houses_and_angles = daily transit @ Bronx
    decision_note = (
        "HOUSE DECISION: daily_transit timestamp + Bronx observer location "
        "(Placidus). Natal chart is a separate block. Arabic Parts use natal "
        "ASC + natal planets (sect-aware Fortune/Spirit)."
    )

    return {
        "houses_and_angles": {
            **transit_houses,
            "natal_vs_transit": decision_note,
            "observer_id": observer.get("id"),
        },
        "arabic_parts": natal_parts,
        "natal_chart": natal_chart,
        "observer": {
            "id": observer.get("id"),
            "person": observer.get("person"),
            "place_name": place,
            "latitude": lat,
            "longitude": lon,
            "timezone": birth["timezone"],
            "config_path": "config/natal_observer.json",
            "geocode": birth.get("geocode"),
        },
    }
