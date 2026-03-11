from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests
import swisseph as swe
from astroquery.jplhorizons import Horizons

from scripts.utils.coords import ra_dec_to_ecl

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "config" / "celestial_catalog.json"
FIXED_STARS_PATH = ROOT / "data" / "fixed_stars.json"

swe.set_ephe_path(str(ROOT / "ephe"))

SWISS_CODES = {
    "sun": swe.SUN,
    "moon": swe.MOON,
    "mercury": swe.MERCURY,
    "venus": swe.VENUS,
    "mars": swe.MARS,
    "jupiter": swe.JUPITER,
    "saturn": swe.SATURN,
    "uranus": swe.URANUS,
    "neptune": swe.NEPTUNE,
    "pluto": swe.PLUTO,
    "chiron": swe.CHIRON,
    "ceres": swe.CERES,
    "pallas": swe.PALLAS,
    "juno": swe.JUNO,
    "vesta": swe.VESTA,
}

MIRIADE_BASE = "https://ssp.imcce.fr/webservices/miriade/api/ephemcc.php"
PRIMARY_HORIZONS_CATEGORIES = {"sun_moon", "planets", "dwarf_planets", "major_asteroids"}
SECONDARY_MIRIADE_CATEGORIES = {"centaurs", "trans_neptunian_objects", "minor_bodies"}


def load_catalog(path: Path = CATALOG_PATH) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_jd(dt: datetime) -> float:
    dt_utc = dt.astimezone(timezone.utc)
    return swe.julday(
        dt_utc.year,
        dt_utc.month,
        dt_utc.day,
        dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0,
    )


def _horizons_position(body: Dict[str, Any], dt: datetime) -> Optional[Dict[str, float]]:
    body_id = body.get("horizons_id") or body["name"]
    id_type = body.get("horizons_id_type")
    kwargs: Dict[str, Any] = {
        "id": body_id,
        "location": "500@399",
        "epochs": [_to_jd(dt)],
    }
    if id_type:
        kwargs["id_type"] = id_type

    eph = Horizons(**kwargs).ephemerides()

    lon, lat = None, None
    for key in ("EclLon", "EclipticLon", "ELON"):
        if key in eph.colnames:
            lon = float(eph[key][0])
            break
    for key in ("EclLat", "EclipticLat", "ELAT"):
        if key in eph.colnames:
            lat = float(eph[key][0])
            break

    if (lon is None or lat is None) and {"RA", "DEC"}.issubset(eph.colnames):
        lon, lat = ra_dec_to_ecl(float(eph["RA"][0]), float(eph["DEC"][0]), _utc_iso(dt))

    if lon is None or lat is None:
        return None

    distance = float(eph["delta"][0]) if "delta" in eph.colnames else 0.0
    velocity = float(eph["vel_obs"][0]) if "vel_obs" in eph.colnames else 0.0
    return {"longitude": lon % 360.0, "latitude": lat, "distance": distance, "velocity": velocity}


def _miriade_position(body: Dict[str, Any], dt: datetime) -> Optional[Dict[str, float]]:
    name = body.get("miriade_name") or body["name"]
    params = {
        "-name": name,
        "-ep": _utc_iso(dt),
        "-observer": "500",
        "-theory": "DE431",
        "-teph": "1",
        "-tcoor": "1",
        "-rplane": "2",
        "-nbd": "1",
        "-mime": "json",
    }
    response = requests.get(MIRIADE_BASE, params=params, timeout=20)
    response.raise_for_status()
    data = response.json().get("result", {})
    if isinstance(data, str):
        data = json.loads(data)
    rows = data.get("data", [])
    if not rows:
        return None
    row = {k.lower(): v for k, v in rows[0].items()}

    lon = row.get("elon") or row.get("ecllon")
    lat = row.get("elat") or row.get("ecllat")
    if lon is None or lat is None:
        ra, dec = row.get("ra"), row.get("dec")
        if ra is None or dec is None:
            return None
        lon, lat = ra_dec_to_ecl(float(ra), float(dec), _utc_iso(dt))

    distance = float(row.get("delta") or row.get("dist") or 0.0)
    velocity = float(row.get("deldot") or row.get("vel") or 0.0)
    return {"longitude": float(lon) % 360.0, "latitude": float(lat), "distance": distance, "velocity": velocity}


def _swiss_position(body: Dict[str, Any], dt: datetime) -> Optional[Dict[str, float]]:
    code = body.get("swiss_code")
    if code is None:
        code = SWISS_CODES.get(body["name"].lower())
    if code is None:
        return None

    result, _ = swe.calc_ut(_to_jd(dt), int(code), swe.FLG_SPEED)
    lon, lat, distance, lon_speed = result[0], result[1], result[2], result[3]
    return {
        "longitude": float(lon) % 360.0,
        "latitude": float(lat),
        "distance": float(distance),
        "velocity": float(lon_speed),
    }


def _normalize_provider_priority(body: Dict[str, Any], category: str) -> List[str]:
    declared = [p.lower() for p in body.get("provider_priority", [])]
    if declared:
        if "swiss" not in declared:
            declared.append("swiss")
        else:
            declared = [p for p in declared if p != "swiss"] + ["swiss"]
        return declared

    if category in PRIMARY_HORIZONS_CATEGORIES:
        return ["horizons", "miriade", "swiss"]
    if category in SECONDARY_MIRIADE_CATEGORIES:
        return ["miriade", "horizons", "swiss"]
    return ["horizons", "miriade", "swiss"]


def _fetch_group(
    provider: str,
    bodies: List[Dict[str, Any]],
    dt: datetime,
) -> Dict[str, Dict[str, Any]]:
    loader_map: Dict[str, Callable[[Dict[str, Any], datetime], Optional[Dict[str, float]]]] = {
        "horizons": _horizons_position,
        "miriade": _miriade_position,
        "swiss": _swiss_position,
    }
    loader = loader_map[provider]
    results: Dict[str, Dict[str, Any]] = {}

    for body in bodies:
        name = body["name"]
        category = body.get("category") or body.get("_catalog_category", "unknown")
        try:
            data = loader(body, dt)
            if data:
                results[name] = {**data, "source": provider, "category": category, "timestamp": _utc_iso(dt)}
            else:
                results[name] = {
                    "longitude": None,
                    "latitude": None,
                    "distance": None,
                    "velocity": None,
                    "source": "unresolved",
                    "category": category,
                    "timestamp": _utc_iso(dt),
                    "errors": [f"{provider}: unresolved"],
                }
        except Exception as exc:
            results[name] = {
                "longitude": None,
                "latitude": None,
                "distance": None,
                "velocity": None,
                "source": "unresolved",
                "category": category,
                "timestamp": _utc_iso(dt),
                "errors": [f"{provider}: {exc}"],
            }
    return results


def fetch_all_positions(dt: datetime, catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    catalog_data = catalog or load_catalog()
    categories = catalog_data.get("categories", {})

    all_bodies: List[Dict[str, Any]] = []
    for category, objects in categories.items():
        if category == "fixed_stars":
            continue
        for body in objects:
            enriched = dict(body)
            enriched.setdefault("category", category)
            enriched["_catalog_category"] = category
            enriched["_provider_chain"] = _normalize_provider_priority(enriched, category)
            all_bodies.append(enriched)

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for body in all_bodies:
        grouped[body["_provider_chain"][0]].append(body)

    positions: Dict[str, Dict[str, Any]] = {}
    unresolved = []

    for provider in ("horizons", "miriade"):
        batch = grouped.get(provider, [])
        if not batch:
            continue
        batch_results = _fetch_group(provider, batch, dt)
        for body in batch:
            name = body["name"]
            result = batch_results[name]
            if result["source"] != "unresolved":
                positions[name] = result
                continue
            next_providers = [p for p in body["_provider_chain"] if p != provider]
            body["_provider_chain"] = next_providers
            unresolved.append(body)

    fallback_horizons: List[Dict[str, Any]] = []
    fallback_miriade: List[Dict[str, Any]] = []
    fallback_swiss: List[Dict[str, Any]] = []

    for body in unresolved:
        chain = body.get("_provider_chain", [])
        if not chain:
            fallback_swiss.append(body)
            continue
        next_provider = chain[0]
        if next_provider == "horizons":
            fallback_horizons.append(body)
        elif next_provider == "miriade":
            fallback_miriade.append(body)
        else:
            fallback_swiss.append(body)

    for provider, batch in (("horizons", fallback_horizons), ("miriade", fallback_miriade)):
        if not batch:
            continue
        retry_results = _fetch_group(provider, batch, dt)
        for body in batch:
            name = body["name"]
            result = retry_results[name]
            if result["source"] != "unresolved":
                positions[name] = result
            else:
                fallback_swiss.append(body)

    if fallback_swiss:
        swiss_results = _fetch_group("swiss", fallback_swiss, dt)
        for body in fallback_swiss:
            positions[body["name"]] = swiss_results[body["name"]]

    if FIXED_STARS_PATH.exists():
        with FIXED_STARS_PATH.open("r", encoding="utf-8") as f:
            stars = json.load(f).get("stars", [])
        for star in stars:
            lon, lat = ra_dec_to_ecl(star["ra_deg"], star["dec_deg"], _utc_iso(dt))
            positions[star["id"]] = {
                "longitude": lon,
                "latitude": lat,
                "distance": 0.0,
                "velocity": 0.0,
                "timestamp": _utc_iso(dt),
                "source": "fixed_star_catalog",
                "category": "fixed stars",
            }
    return positions


if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    print(json.dumps(fetch_all_positions(now), indent=2))
