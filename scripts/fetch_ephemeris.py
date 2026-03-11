from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
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

EPHEMERIS_PATH = ROOT / "ephemeris"
if not EPHEMERIS_PATH.exists():
    EPHEMERIS_PATH = ROOT / "ephe"
swe.set_ephe_path(str(EPHEMERIS_PATH))

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
PRIMARY_HORIZONS_CATEGORIES = {"core_bodies", "dwarf_planets", "major_asteroids"}
SECONDARY_MIRIADE_CATEGORIES = {"expanded_asteroids", "centaurs", "trans_neptunian_objects"}


def _normalize_minor_body_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().rstrip(";")
    return text or None


def _miriade_identifiers(body: Dict[str, Any]) -> List[str]:
    name = body["name"]
    identifiers: List[str] = []

    explicit = body.get("miriade_name")
    if explicit:
        identifiers.append(str(explicit))

    minor_body_id = _normalize_minor_body_id(body.get("mpc_designation") or body.get("horizons_id") or body.get("id"))
    if minor_body_id:
        identifiers.extend([
            f"a:{minor_body_id}",
            f"a:{minor_body_id} {name}",
        ])

    lowered = name.lower()
    if lowered == "moon":
        identifiers.append("s:Moon")
    elif lowered in {"sun", "mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune"}:
        identifiers.append(f"p:{name}")
    elif lowered == "pluto":
        identifiers.append("dp:Pluto")
    else:
        identifiers.append(f"a:{name}")

    identifiers.append(name)

    deduped: List[str] = []
    for ident in identifiers:
        if ident and ident not in deduped:
            deduped.append(ident)
    return deduped


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
    for identifier in _miriade_identifiers(body):
        params = {
            "-name": identifier,
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
            continue
        row = {k.lower(): v for k, v in rows[0].items()}

        lon = row.get("elon") or row.get("ecllon")
        lat = row.get("elat") or row.get("ecllat")
        if lon is None or lat is None:
            ra, dec = row.get("ra"), row.get("dec")
            if ra is None or dec is None:
                continue
            lon, lat = ra_dec_to_ecl(float(ra), float(dec), _utc_iso(dt))

        distance = float(row.get("delta") or row.get("dist") or 0.0)
        velocity = float(row.get("deldot") or row.get("vel") or 0.0)
        timestamp = row.get("epoch") or row.get("date") or row.get("datetime") or _utc_iso(dt)
        return {
            "longitude": float(lon) % 360.0,
            "latitude": float(lat),
            "distance": distance,
            "velocity": velocity,
            "timestamp": str(timestamp),
        }

    return None


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
    if body["name"].lower() == "sun":
        return ["horizons", "swiss"]

    if category in PRIMARY_HORIZONS_CATEGORIES or category in SECONDARY_MIRIADE_CATEGORIES:
        return ["horizons", "miriade", "swiss"]
    if category == "fixed_stars":
        return ["fixed_star_catalog"]
    if category == "aether_points":
        return ["calculated"]
    return ["horizons", "miriade", "swiss"]


def _compute_single(provider: str, body: Dict[str, Any], dt: datetime) -> Dict[str, Any]:
    loader_map: Dict[str, Callable[[Dict[str, Any], datetime], Optional[Dict[str, float]]]] = {
        "horizons": _horizons_position,
        "miriade": _miriade_position,
        "swiss": _swiss_position,
    }
    loader = loader_map[provider]
    name = body["name"]
    category = body.get("category") or body.get("_catalog_category", "unknown")

    try:
        data = loader(body, dt)
        if data:
            return {
                name: {
                    **data,
                    "source": provider,
                    "category": category,
                    "timestamp": str(data.get("timestamp") or _utc_iso(dt)),
                }
            }
        return {
            name: {
                "longitude": None,
                "latitude": None,
                "distance": None,
                "velocity": None,
                "source": "unresolved",
                "category": category,
                "timestamp": _utc_iso(dt),
                "errors": [f"{provider}: unresolved"],
            }
        }
    except Exception as exc:
        return {
            name: {
                "longitude": None,
                "latitude": None,
                "distance": None,
                "velocity": None,
                "source": "unresolved",
                "category": category,
                "timestamp": _utc_iso(dt),
                "errors": [f"{provider}: {exc}"],
            }
        }


def _fetch_group(
    provider: str,
    bodies: List[Dict[str, Any]],
    dt: datetime,
) -> Dict[str, Dict[str, Any]]:
    if not bodies:
        return {}

    results: Dict[str, Dict[str, Any]] = {}
    max_workers = min(8, len(bodies))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_compute_single, provider, body, dt) for body in bodies]
        for future in as_completed(futures):
            results.update(future.result())
    return results


def _compute_aether_points(
    positions: Dict[str, Dict[str, Any]],
    aether_bodies: List[Dict[str, Any]],
    dt: datetime,
) -> Dict[str, Dict[str, Any]]:
    def lon(name: str) -> Optional[float]:
        entry = positions.get(name)
        if not entry:
            return None
        value = entry.get("longitude")
        return float(value) if value is not None else None

    sun = lon("Sun")
    moon = lon("Moon")
    mars = lon("Mars")
    jupiter = lon("Jupiter")
    saturn = lon("Saturn")
    venus = lon("Venus")

    formulas = {
        "Aetheric_SunMoon_Midpoint": None if sun is None or moon is None else ((sun + moon) / 2.0) % 360.0,
        "Aetheric_Jovian_Arc": None if jupiter is None or saturn is None else ((jupiter - saturn) + 360.0) % 360.0,
        "Aetheric_Elemental_Balance": None if mars is None or venus is None or moon is None else ((mars + venus + moon) / 3.0) % 360.0,
    }

    computed: Dict[str, Dict[str, Any]] = {}
    for body in aether_bodies:
        name = body["name"]
        category = body.get("category", "aether_points")
        value = formulas.get(name)
        computed[name] = {
            "longitude": value,
            "latitude": 0.0 if value is not None else None,
            "distance": 0.0 if value is not None else None,
            "velocity": 0.0,
            "timestamp": _utc_iso(dt),
            "source": "calculated",
            "category": category,
        }
    return computed


def _resolve_body(body: Dict[str, Any], dt: datetime) -> Dict[str, Any]:
    name = body["name"]
    category = body.get("category") or body.get("_catalog_category", "unknown")
    errors: List[str] = []

    for provider in body.get("_provider_chain", ["horizons", "miriade", "swiss"]):
        result = _compute_single(provider, body, dt)[name]
        if result.get("source") != "unresolved" and result.get("longitude") is not None:
            if errors:
                result["errors"] = errors
            return {name: result}
        errors.extend(result.get("errors", [f"{provider}: unresolved"]))

    return {
        name: {
            "longitude": None,
            "latitude": None,
            "distance": None,
            "velocity": None,
            "source": "unresolved",
            "category": category,
            "timestamp": _utc_iso(dt),
            "errors": errors,
        }
    }


def fetch_all_positions(dt: datetime, catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    catalog_data = catalog or load_catalog()
    categories = catalog_data.get("categories", {})

    all_bodies: List[Dict[str, Any]] = []
    fixed_star_names: set[str] = set()
    aether_bodies: List[Dict[str, Any]] = []

    for category, objects in categories.items():
        for body in objects:
            enriched = dict(body)
            enriched.setdefault("category", category)
            enriched["_catalog_category"] = category
            enriched["_provider_chain"] = _normalize_provider_priority(enriched, category)

            if category == "fixed_stars":
                fixed_star_names.add(enriched["name"])
                continue
            if category == "aether_points":
                aether_bodies.append(enriched)
                continue
            all_bodies.append(enriched)

    positions: Dict[str, Dict[str, Any]] = {}
    for body in all_bodies:
        resolved = _resolve_body(body, dt)
        for name, candidate in resolved.items():
            existing = positions.get(name)
            if existing is None:
                positions[name] = candidate
                continue

            existing_ok = existing.get("longitude") is not None
            candidate_ok = candidate.get("longitude") is not None
            if candidate_ok and not existing_ok:
                positions[name] = candidate

    if FIXED_STARS_PATH.exists() and fixed_star_names:
        with FIXED_STARS_PATH.open("r", encoding="utf-8") as f:
            stars = json.load(f).get("stars", [])
        for star in stars:
            if star["id"] not in fixed_star_names:
                continue
            lon, lat = ra_dec_to_ecl(star["ra_deg"], star["dec_deg"], _utc_iso(dt))
            positions[star["id"]] = {
                "longitude": lon,
                "latitude": lat,
                "distance": 0.0,
                "velocity": 0.0,
                "timestamp": _utc_iso(dt),
                "source": "fixed_star_catalog",
                "category": "fixed_stars",
            }

    positions.update(_compute_aether_points(positions, aether_bodies, dt))
    return positions


if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    print(json.dumps(fetch_all_positions(now), indent=2))
