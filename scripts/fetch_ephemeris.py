from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def fetch_body_position(body: Dict[str, Any], dt: datetime) -> Dict[str, Any]:
    attempts = [
        ("horizons", _horizons_position),
        ("miriade", _miriade_position),
        ("swiss", _swiss_position),
    ]
    errors: List[str] = []
    for source, loader in attempts:
        try:
            data = loader(body, dt)
            if data:
                return {**data, "source": source, "timestamp": _utc_iso(dt)}
            errors.append(f"{source}: unresolved")
        except Exception as exc:  # network and object-resolution failures are expected fallbacks
            errors.append(f"{source}: {exc}")

    return {
        "longitude": None,
        "latitude": None,
        "distance": None,
        "velocity": None,
        "timestamp": _utc_iso(dt),
        "source": "unresolved",
        "errors": errors,
    }


def fetch_all_positions(dt: datetime, catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    catalog_data = catalog or load_catalog()
    positions: Dict[str, Dict[str, Any]] = {}
    for category, objects in catalog_data["categories"].items():
        for body in objects:
            body_name = body["name"]
            result = fetch_body_position(body, dt)
            result["category"] = category
            positions[body_name] = result

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
