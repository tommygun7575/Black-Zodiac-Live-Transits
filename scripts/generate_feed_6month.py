#!/usr/bin/env python3
"""6-month transit feed generator — ZodiacOracle.SixMonthTransit.v2."""

from __future__ import annotations

import datetime
import json
import math
import os
import socket
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pytz
import requests
from astroquery import conf as astroquery_conf
from astroquery.jplhorizons import Horizons
from dateutil import parser as date_parser

from scripts.utils.coords import ra_dec_to_ecl

try:
    import swisseph as swe  # Linux / GitHub Actions
except ImportError:  # pragma: no cover
    import pyswisseph as swe  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "config" / "celestial_catalog.json"
FIXED_STARS_PRIMARY = ROOT / "data" / "fixed_star_catalog.json"
FIXED_STARS_FALLBACK = ROOT / "data" / "fixed_stars.json"

EPHE_PATH = ROOT / "ephe"
swe.set_ephe_path(str(EPHE_PATH))

SAMPLE_DAYS = 182
HORIZONS_LOCATION = "500@399"
MIRIADE_BASE = "https://ssp.imcce.fr/webservices/miriade/api/ephemcc.php"
REQUEST_TIMEOUT_HORIZONS = 30
REQUEST_TIMEOUT_MIRIADE = 20
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.5

# JPL Horizons range requests are range-level (one request per body per
# attempt), so retries must stay small and bounded: the initial attempt plus
# at most one additional retry.
JPL_RETRY_ATTEMPTS = 2
JPL_RETRY_BACKOFF_SECONDS = 2.0

PROVIDER_LABELS = {
    "jpl": "JPL",
    "miriade": "Miriade",
    "swiss": "Swiss",
}

SWISS_IDS = {
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


def _is_valid_number(value: Any) -> bool:
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _normalize_lon(lon: float) -> float:
    return float(lon) % 360.0


def _iso_utc(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _date_key(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _daily_samples(start_dt: datetime.datetime, days: int = SAMPLE_DAYS) -> List[datetime.datetime]:
    start = start_dt.astimezone(datetime.timezone.utc)
    return [start + datetime.timedelta(days=offset) for offset in range(days)]


def _normalize_provider(provider: str) -> str:
    lowered = provider.lower().strip()
    if lowered in {"horizons", "jpl"}:
        return "jpl"
    if lowered in {"miriade", "imcce"}:
        return "miriade"
    if lowered in {"swiss", "swisseph", "swiss_ephemeris"}:
        return "swiss"
    if lowered in {"fixed_star_catalog", "fixed"}:
        return "fixed"
    if lowered == "calculated":
        return "calculated"
    return lowered


def _is_moving_entry(category: str, body: Dict[str, Any]) -> bool:
    if category in {"fixed_stars", "aether_points"}:
        return False
    providers = [_normalize_provider(p) for p in body.get("provider_priority", [])]
    if "calculated" in providers or "fixed" in providers:
        return False
    return True


def _normalize_horizons_id(body: Dict[str, Any]) -> Optional[str]:
    raw = body.get("horizons_id")
    if raw is None:
        return body.get("name")
    text = str(raw).strip()
    if not text:
        return body.get("name")

    id_type = str(body.get("horizons_id_type") or "").lower()
    category = str(body.get("category") or "").lower()
    if id_type != "majorbody" and category != "core_bodies" and not text.endswith(";"):
        return f"{text};"
    return text


def _has_valid_jpl_mapping(body: Dict[str, Any]) -> bool:
    """A body is JPL-capable only if it carries an actual Horizons identifier.

    This is a real capability check (not a guess): it inspects the
    repository's own catalog field (`horizons_id`) rather than assuming
    every body supports JPL just because "jpl"/"horizons" appears in its
    provider_priority list.
    """
    raw = body.get("horizons_id")
    if raw is None:
        return False
    return bool(str(raw).strip())


def _has_valid_miriade_mapping(body: Dict[str, Any]) -> bool:
    """A body is Miriade-capable only if it has a usable Miriade identifier.

    Falls back to the generic "a:<Name>" convention used elsewhere in this
    repository (see _miriade_name / scripts/fetch_ephemeris.py) when no
    explicit miriade_name is present, since that convention is an actual,
    already-used repository mapping rather than a guess.
    """
    explicit = body.get("miriade_name")
    if explicit and str(explicit).strip():
        return True
    return bool(body.get("name"))


def _has_valid_swiss_mapping(body: Dict[str, Any]) -> bool:
    """A body is Swiss-capable only if it maps to an actual Swiss Ephemeris
    planet/body code, either explicitly via `swiss_code` in the catalog or
    via the repository's existing SWISS_IDS name lookup table.
    """
    code = body.get("swiss_code")
    if code is not None:
        return True
    name = body.get("name")
    if not name:
        return False
    return SWISS_IDS.get(str(name).lower()) is not None


def _provider_chain(body: Dict[str, Any]) -> List[str]:
    """Build the effective provider chain for a body from actual repository
    capability mappings (horizons_id, miriade_name, swiss_code/SWISS_IDS),
    preserving the catalog's intended priority order and never including a
    provider the body cannot actually be resolved through.
    """
    providers = body.get("provider_priority") or ["horizons", "miriade", "swiss"]
    capability_checks = {
        "jpl": _has_valid_jpl_mapping,
        "miriade": _has_valid_miriade_mapping,
        "swiss": _has_valid_swiss_mapping,
    }

    normalized: List[str] = []
    for p in providers:
        mapped = _normalize_provider(str(p))
        if mapped not in capability_checks or mapped in normalized:
            continue
        if capability_checks[mapped](body):
            normalized.append(mapped)

    return normalized


def load_catalog_targets(path: Path = CATALOG_PATH) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    with path.open("r", encoding="utf-8") as f:
        catalog = json.load(f)

    categories = catalog.get("categories", {})
    moving: List[Dict[str, Any]] = []
    fixed_star_names: List[str] = []
    aether_names: List[str] = []

    for category, bodies in categories.items():
        for body in bodies:
            entry = dict(body)
            entry.setdefault("category", category)
            if category == "fixed_stars":
                fixed_star_names.append(entry["name"])
                continue
            if category == "aether_points":
                aether_names.append(entry["name"])
                continue
            if not _is_moving_entry(category, entry):
                continue
            # Provider chain is computed ONCE per body here, at catalog load
            # time — never rediscovered per date during the 182-day range
            # resolution.
            entry["_provider_chain"] = _provider_chain(entry)
            entry["_horizons_id"] = _normalize_horizons_id(entry)
            moving.append(entry)

    return moving, fixed_star_names, aether_names


def _extract_lon_lat(row: Any, colnames: Sequence[str], dt: datetime.datetime) -> Optional[Tuple[float, float]]:
    lon = lat = None
    for key in ("EclLon", "EclipticLon", "ELON"):
        if key in colnames:
            lon = row[key]
            break
    for key in ("EclLat", "EclipticLat", "ELAT"):
        if key in colnames:
            lat = row[key]
            break

    if (lon is None or lat is None) and "RA" in colnames and "DEC" in colnames:
        try:
            lon, lat = ra_dec_to_ecl(float(row["RA"]), float(row["DEC"]), _iso_utc(dt))
        except Exception:
            return None

    if not _is_valid_number(lon) or not _is_valid_number(lat):
        return None

    return _normalize_lon(float(lon)), float(lat)


def _parse_row_date(
    row: Any,
    colnames: Sequence[str],
    fallback_dt: Optional[datetime.datetime],
) -> Optional[datetime.date]:
    if "datetime_str" in colnames:
        raw = str(row["datetime_str"]).strip()
        try:
            parsed = date_parser.parse(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            return parsed.astimezone(datetime.timezone.utc).date()
        except Exception:
            pass
    if "datetime_jd" in colnames:
        try:
            jd = float(row["datetime_jd"])
            year, month, day, ut = swe.revjul(jd, swe.GREG_CAL)
            hour = int(ut)
            minute = int((ut - hour) * 60)
            second = int(round((((ut - hour) * 60) - minute) * 60))
            parsed = datetime.datetime(year, month, day, hour, minute, second, tzinfo=datetime.timezone.utc)
            return parsed.date()
        except Exception:
            pass
    if fallback_dt is None:
        return None
    return fallback_dt.date()


def _parse_miriade_row_date(row: Dict[str, Any], fallback_dt: Optional[datetime.datetime]) -> Optional[datetime.date]:
    raw = row.get("datetime_str") or row.get("date") or row.get("epoch")
    if raw is not None:
        try:
            parsed = date_parser.parse(str(raw).strip())
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            return parsed.astimezone(datetime.timezone.utc).date()
        except Exception:
            pass
    if row.get("datetime_jd") is not None:
        try:
            jd = float(row["datetime_jd"])
            year, month, day, ut = swe.revjul(jd, swe.GREG_CAL)
            hour = int(ut)
            minute = int((ut - hour) * 60)
            second = int(round((((ut - hour) * 60) - minute) * 60))
            parsed = datetime.datetime(year, month, day, hour, minute, second, tzinfo=datetime.timezone.utc)
            return parsed.date()
        except Exception:
            pass
    if fallback_dt is None:
        return None
    return fallback_dt.date()


def _call_with_retries(fn, attempts: int = RETRY_ATTEMPTS):
    last_exc = None
    for idx in range(attempts):
        try:
            return fn()
        except Exception as exc:  # pragma: no cover - network variability
            last_exc = exc
            if idx < attempts - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (idx + 1))
    if last_exc:
        raise last_exc
    raise RuntimeError("retry helper failed without exception")


def _is_timeout_exception(exc: Exception) -> bool:
    """Detect timeout-flavored exceptions across requests/socket/builtins."""
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    if isinstance(exc, requests.exceptions.Timeout):
        return True
    # astroquery sometimes wraps the underlying requests exception; fall back
    # to a message-based check as a last resort.
    return "timed out" in str(exc).lower() or "timeout" in str(exc).lower()


def fetch_horizons_range(
    body: Dict[str, Any],
    dt_list: Sequence[datetime.datetime],
    stats: Dict[str, int],
) -> Dict[str, Dict[str, Any]]:
    if not dt_list:
        return {}

    start_dt = dt_list[0]
    stop_dt = dt_list[-1]
    body_id = body.get("_horizons_id") or body["name"]
    id_type = body.get("horizons_id_type")
    body_name = body.get("name", "unknown")

    def _request():
        # Apply a finite timeout to the actual astroquery/requests HTTP call.
        # astroquery routes its HTTP layer through astroquery.conf.timeout,
        # so this is the supported mechanism for bounding the Horizons call.
        astroquery_conf.timeout = REQUEST_TIMEOUT_HORIZONS
        kwargs = {
            "id": body_id,
            "location": HORIZONS_LOCATION,
            "epochs": {
                "start": start_dt.strftime("%Y-%m-%d %H:%M"),
                "stop": stop_dt.strftime("%Y-%m-%d %H:%M"),
                "step": "1d",
            },
        }
        if id_type:
            kwargs["id_type"] = id_type
        return Horizons(**kwargs).ephemerides()

    eph = None
    for attempt in range(JPL_RETRY_ATTEMPTS):
        stats["jpl_range_requests"] = stats.get("jpl_range_requests", 0) + 1
        try:
            eph = _request()
            break
        except Exception as exc:
            if _is_timeout_exception(exc):
                stats["jpl_timeouts"] = stats.get("jpl_timeouts", 0) + 1
                print(f"[6M] {body_name}: JPL range request timed out after {REQUEST_TIMEOUT_HORIZONS}s")
            if attempt < JPL_RETRY_ATTEMPTS - 1:
                stats["jpl_retries"] = stats.get("jpl_retries", 0) + 1
                print(f"[6M] {body_name}: retry {attempt + 1}/{JPL_RETRY_ATTEMPTS - 1}")
                time.sleep(JPL_RETRY_BACKOFF_SECONDS)

    if eph is None:
        stats["jpl_range_failures"] = stats.get("jpl_range_failures", 0) + 1
        print(f"[6M] {body_name}: JPL failed, continuing to Miriade")
        return {}

    results: Dict[str, Dict[str, Any]] = {}
    colnames = list(getattr(eph, "colnames", []))
    dt_by_idx = list(dt_list)
    expected_dates = {d.date() for d in dt_by_idx}
    dt_by_date = {d.date(): d for d in dt_by_idx}

    for idx in range(len(eph)):
        row = eph[idx]
        fallback_dt = dt_by_idx[idx] if idx < len(dt_by_idx) else None
        row_date = _parse_row_date(row, colnames, fallback_dt)
        if row_date is None:
            continue
        if row_date not in expected_dates:
            continue
        expected_dt = dt_by_date[row_date]

        lonlat = _extract_lon_lat(row, colnames, expected_dt)
        if lonlat is None:
            continue

        lon, lat = lonlat
        key = row_date.strftime("%Y-%m-%d")
        results[key] = {
            "ecl_lon_deg": lon,
            "ecl_lat_deg": lat,
            "source": "jpl",
        }

    return results


def _miriade_name(body: Dict[str, Any]) -> str:
    if body.get("miriade_name"):
        return str(body["miriade_name"])
    return f"a:{body['name']}"


def _group_contiguous_dates(sorted_dts: Sequence[datetime.datetime]) -> List[List[datetime.datetime]]:
    """Group a sorted sequence of datetimes into contiguous daily runs."""
    groups: List[List[datetime.datetime]] = []
    current: List[datetime.datetime] = []
    prev_date: Optional[datetime.date] = None

    for dt in sorted_dts:
        if prev_date is not None and (dt.date() - prev_date).days == 1:
            current.append(dt)
        else:
            if current:
                groups.append(current)
            current = [dt]
        prev_date = dt.date()

    if current:
        groups.append(current)

    return groups


def fetch_miriade_range(
    body: Dict[str, Any],
    missing_dates: Sequence[datetime.datetime],
    stats: Dict[str, int],
) -> Dict[str, Dict[str, Any]]:
    """Fetch a contiguous run of dates from Miriade in ONE HTTP request.

    Uses Miriade ephemcc's native multi-epoch support (-ep start, -nbd count,
    -step 1d) instead of issuing one request per missing date.
    """
    if not missing_dates:
        return {}

    ordered = sorted(missing_dates)
    start_dt = ordered[0]
    nbd = len(ordered)

    params = {
        "-name": _miriade_name(body),
        "-ep": _iso_utc(start_dt),
        "-observer": "500",
        "-theory": "DE431",
        "-teph": "1",
        "-tcoor": "1",
        "-rplane": "2",
        "-nbd": str(nbd),
        "-step": "1d",
        "-mime": "json",
    }

    def _request_json():
        r = requests.get(MIRIADE_BASE, params=params, timeout=REQUEST_TIMEOUT_MIRIADE)
        r.raise_for_status()
        payload = r.json().get("result", {})
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload

    stats["miriade_range_requests"] = stats.get("miriade_range_requests", 0) + 1
    stats["miriade_fallback_requests"] = stats.get("miriade_fallback_requests", 0) + 1

    try:
        payload = _call_with_retries(_request_json)
    except Exception:
        return {}

    rows = payload.get("data", [])
    if not rows:
        return {}

    results: Dict[str, Dict[str, Any]] = {}

    for idx, raw_row in enumerate(rows):
        if idx >= len(ordered):
            break
        row = {k.lower(): v for k, v in raw_row.items()}
        fallback_dt = ordered[idx]

        row_date = _parse_miriade_row_date(row, fallback_dt)
        if row_date is None:
            continue

        lon = row.get("elon") or row.get("ecllon")
        lat = row.get("elat") or row.get("ecllat")
        if (lon is None or lat is None) and row.get("ra") is not None and row.get("dec") is not None:
            try:
                lon, lat = ra_dec_to_ecl(float(row["ra"]), float(row["dec"]), _iso_utc(fallback_dt))
            except Exception:
                continue

        if not _is_valid_number(lon) or not _is_valid_number(lat):
            continue

        key = row_date.strftime("%Y-%m-%d")
        results[key] = {
            "ecl_lon_deg": _normalize_lon(float(lon)),
            "ecl_lat_deg": float(lat),
            "source": "miriade",
        }
        stats["miriade_points_resolved"] = stats.get("miriade_points_resolved", 0) + 1

    return results


def fetch_swiss_point(body: Dict[str, Any], dt: datetime.datetime, stats: Dict[str, int]) -> Optional[Dict[str, Any]]:
    stats["swiss_fallback_requests"] += 1
    code = body.get("swiss_code")
    if code is None:
        code = SWISS_IDS.get(body["name"].lower())
    if code is None:
        return None

    jd = swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute / 60.0 + dt.second / 3600.0)

    try:
        result = swe.calc_ut(jd, int(code))
    except Exception:
        return None

    values = result[0] if isinstance(result, tuple) and len(result) == 2 else result
    if not isinstance(values, (list, tuple)) or len(values) < 2:
        return None

    lon, lat = values[0], values[1]
    if not _is_valid_number(lon) or not _is_valid_number(lat):
        return None

    return {
        "ecl_lon_deg": _normalize_lon(float(lon)),
        "ecl_lat_deg": float(lat),
        "source": "swiss",
    }


def load_fixed_stars_for_catalog(
    names: Iterable[str],
    reference_dt: Optional[datetime.datetime] = None,
) -> Dict[str, Dict[str, float]]:
    selected = set(names)
    if not selected:
        return {}

    path = FIXED_STARS_PRIMARY if FIXED_STARS_PRIMARY.exists() else FIXED_STARS_FALLBACK
    if not path.exists():
        return {}
    epoch = reference_dt or datetime.datetime.now(datetime.timezone.utc)

    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    stars = payload.get("stars", [])
    output: Dict[str, Dict[str, float]] = {}
    for star in stars:
        star_id = star.get("id")
        if star_id not in selected:
            continue
        lon, lat = ra_dec_to_ecl(float(star["ra_deg"]), float(star["dec_deg"]), _iso_utc(epoch))
        if _is_valid_number(lon) and _is_valid_number(lat):
            output[star_id] = {
                "ecl_lon_deg": _normalize_lon(float(lon)),
                "ecl_lat_deg": float(lat),
                "source": "fixed",
            }
    return output


def _lon_from_day(day_transits: Dict[str, Dict[str, Any]], name: str) -> Optional[float]:
    entry = day_transits.get(name)
    if not entry:
        return None
    lon = entry.get("ecl_lon_deg")
    if not _is_valid_number(lon):
        return None
    return float(lon)


def add_aether_points(day_transits: Dict[str, Dict[str, Any]], aether_names: Sequence[str]) -> None:
    sun = _lon_from_day(day_transits, "Sun")
    moon = _lon_from_day(day_transits, "Moon")
    mars = _lon_from_day(day_transits, "Mars")
    jupiter = _lon_from_day(day_transits, "Jupiter")
    saturn = _lon_from_day(day_transits, "Saturn")
    venus = _lon_from_day(day_transits, "Venus")

    midpoint = None if sun is None or moon is None else _normalize_lon((sun + moon) % 360.0)
    jovian_arc = None if jupiter is None or saturn is None else _normalize_lon(jupiter - saturn)
    elemental_balance = None if mars is None or venus is None or moon is None else _normalize_lon((mars + venus + moon) / 3.0)

    formulas = {
        "Aetheric_SunMoon_Midpoint": midpoint,
        "Aetheric_Jovian_Arc": jovian_arc,
        "Aetheric_Elemental_Balance": elemental_balance,
    }

    for name in aether_names:
        val = formulas.get(name)
        day_transits[name] = {
            "ecl_lon_deg": None if val is None else float(val),
            "ecl_lat_deg": None if val is None else 0.0,
            "source": "calculated",
        }


def _classify_provider_route(chain: Sequence[str]) -> str:
    """Classify a body's provider chain for aggregate routing statistics."""
    if not chain:
        return "no_valid_provider"
    primary = chain[0]
    if primary == "jpl":
        return "jpl_primary"
    if primary == "miriade":
        return "miriade_primary"
    if primary == "swiss":
        return "swiss_primary"
    return "no_valid_provider"


def resolve_moving_body(
    body: Dict[str, Any],
    dt_list: Sequence[datetime.datetime],
    stats: Dict[str, int],
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    date_keys = [_date_key(dt) for dt in dt_list]
    missing: Set[str] = set(date_keys)
    resolved: Dict[str, Dict[str, Any]] = {}
    attempted: Dict[str, List[str]] = {k: [] for k in date_keys}

    body_name = body.get("name", "unknown")
    # Provider chain was already computed ONCE per body in
    # load_catalog_targets(); it is only read here, never recalculated
    # per-date.
    chain = list(body.get("_provider_chain", []))

    route = _classify_provider_route(chain)
    stats["provider_route_counts"] = stats.get("provider_route_counts") or {
        "jpl_primary": 0,
        "miriade_primary": 0,
        "swiss_primary": 0,
        "no_valid_provider": 0,
    }
    stats["provider_route_counts"][route] = stats["provider_route_counts"].get(route, 0) + 1

    if not chain:
        print(f"[6M] WARNING: {body_name} has no valid configured provider; skipping all network requests")
        missing_entries = [
            {
                "date": key,
                "body": body_name,
                "providers_attempted": [],
                "reason": "no_valid_provider_configured",
            }
            for key in sorted(missing)
        ]
        return resolved, missing_entries

    chain_labels = " -> ".join(PROVIDER_LABELS.get(p, p) for p in chain)
    print(f"[6M] {body_name} providers: {chain_labels}")

    if "jpl" in chain:
        for key in date_keys:
            attempted[key].append("JPL")
        try:
            jpl_results = fetch_horizons_range(body, dt_list, stats)
        except Exception:
            jpl_results = {}
        for key, point in jpl_results.items():
            if key in missing:
                resolved[key] = point
                missing.discard(key)

    dt_lookup = {_date_key(dt): dt for dt in dt_list}

    if "miriade" in chain and missing:
        sorted_keys = sorted(missing, key=lambda k: dt_lookup[k])
        for key in sorted_keys:
            attempted[key].append("Miriade")

        missing_dts = [dt_lookup[k] for k in sorted_keys]
        contiguous_groups = _group_contiguous_dates(missing_dts)

        for group in contiguous_groups:
            group_results = fetch_miriade_range(body, group, stats)
            for key, point in group_results.items():
                if key in missing:
                    resolved[key] = point
                    missing.discard(key)

    if "swiss" in chain and missing:
        for key in list(sorted(missing)):
            attempted[key].append("Swiss")
            point = fetch_swiss_point(body, dt_lookup[key], stats)
            if point is not None:
                resolved[key] = point
                missing.discard(key)

    missing_entries = [
        {
            "date": key,
            "body": body_name,
            "providers_attempted": attempted[key],
        }
        for key in sorted(missing)
    ]

    return resolved, missing_entries


def write_output_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp.json")
    try:
        try:
            fh = os.fdopen(fd, "w", encoding="utf-8")
        except Exception:
            os.close(fd)
            raise
        with fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def generate_six_month_feed(start_dt: Optional[datetime.datetime] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    started = time.perf_counter()
    utc_now = start_dt.astimezone(datetime.timezone.utc) if start_dt else datetime.datetime.now(datetime.timezone.utc)
    dt_list = _daily_samples(utc_now, SAMPLE_DAYS)
    date_keys = [_date_key(dt) for dt in dt_list]

    moving_bodies, fixed_star_names, aether_names = load_catalog_targets()
    fixed_star_positions = load_fixed_stars_for_catalog(fixed_star_names, reference_dt=dt_list[0])

    transits = {day: {} for day in date_keys}
    total_points = len(moving_bodies) * len(dt_list)

    stats: Dict[str, Any] = {
        "jpl_range_requests": 0,
        "jpl_range_failures": 0,
        "jpl_retries": 0,
        "jpl_timeouts": 0,
        "miriade_fallback_requests": 0,
        "miriade_range_requests": 0,
        "miriade_points_resolved": 0,
        "swiss_fallback_requests": 0,
        "provider_route_counts": {
            "jpl_primary": 0,
            "miriade_primary": 0,
            "swiss_primary": 0,
            "no_valid_provider": 0,
        },
    }

    missing: List[Dict[str, Any]] = []
    resolved_points = 0

    for body in moving_bodies:
        body_points, body_missing = resolve_moving_body(body, dt_list, stats)
        for day in date_keys:
            if day in body_points:
                transits[day][body["name"]] = body_points[day]
                resolved_points += 1
        missing.extend(body_missing)

    for day in date_keys:
        day_transits = transits[day]
        for star_name, star_data in fixed_star_positions.items():
            day_transits[star_name] = dict(star_data)
        add_aether_points(day_transits, aether_names)

    duration = time.perf_counter() - started
    coverage = (resolved_points / total_points) if total_points else 0.0

    start_range = dt_list[0]
    end_range = dt_list[-1]
    data = {
        "engine_version": "ZodiacOracle.SixMonthTransit.v2",
        "meta": {
            "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "generated_at_pacific": datetime.datetime.now(pytz.timezone("America/Los_Angeles")).isoformat(),
            "type": "6-month overlay",
            "range_utc": [start_range.isoformat(), end_range.isoformat()],
            "range": f"{start_range.strftime('%Y-%m-%d')} to {end_range.strftime('%Y-%m-%d')}",
            "source_order": ["jpl", "miriade", "swiss", "fixed", "calculated"],
        },
        "transits": transits,
        "coverage": coverage,
        "resolved_points": resolved_points,
        "total_points": total_points,
        "missing": missing,
        "moving_body_count": len(moving_bodies),
        "runtime": {
            "duration_seconds": duration,
            "jpl_range_requests": stats["jpl_range_requests"],
            "jpl_range_failures": stats["jpl_range_failures"],
            "jpl_retries": stats["jpl_retries"],
            "jpl_timeouts": stats["jpl_timeouts"],
            "miriade_fallback_requests": stats["miriade_fallback_requests"],
            "miriade_range_requests": stats["miriade_range_requests"],
            "miriade_points_resolved": stats["miriade_points_resolved"],
            "swiss_fallback_requests": stats["swiss_fallback_requests"],
            "provider_route_counts": stats["provider_route_counts"],
            "missing_points": len(missing),
            "resolved_points": resolved_points,
        },
    }

    return data, stats


def main() -> None:
    data, _stats = generate_six_month_feed()

    pacific = datetime.datetime.now(pytz.timezone("America/Los_Angeles"))
    filename = f"feed_overlay_6month_{pacific.strftime('%b-%d-%Y_%I-%M%p')}_Pacific.json"
    outpath = ROOT / "docs" / filename

    write_output_atomic(outpath, data)

    print("✅ 6-month feed generation complete")
    print(f"   moving bodies             : {data['moving_body_count']}")
    print(f"   date samples              : {len(data['transits'])}")
    print(f"   total_points              : {data['total_points']}")
    print(f"   resolved_points           : {data['resolved_points']}")
    print(f"   coverage                  : {data['coverage']:.6f}")
    print(f"   missing points            : {len(data['missing'])}")
    print(f"   jpl range requests        : {data['runtime']['jpl_range_requests']}")
    print(f"   jpl range failures        : {data['runtime']['jpl_range_failures']}")
    print(f"   jpl retries               : {data['runtime']['jpl_retries']}")
    print(f"   jpl timeouts              : {data['runtime']['jpl_timeouts']}")
    print(f"   miriade range requests    : {data['runtime']['miriade_range_requests']}")
    print(f"   miriade points resolved   : {data['runtime']['miriade_points_resolved']}")
    print(f"   miriade fallback requests : {data['runtime']['miriade_fallback_requests']}")
    print(f"   swiss fallback requests   : {data['runtime']['swiss_fallback_requests']}")
    print(f"   provider route counts     : {data['runtime']['provider_route_counts']}")
    print(f"   duration_seconds          : {data['runtime']['duration_seconds']:.2f}")
    print(f"   output                    : {outpath}")


if __name__ == "__main__":
    main()
