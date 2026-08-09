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

import numpy as np
import pytz
import requests
from astroquery.jplhorizons import Horizons
from dateutil import parser as date_parser

from scripts.utils.coords import ra_dec_to_ecl

try:
    import swisseph as swe
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

MIRIADE_BASE = (
    "https://ssp.imcce.fr/webservices/miriade/api/ephemcc.php"
)

REQUEST_TIMEOUT_HORIZONS = 30
REQUEST_TIMEOUT_MIRIADE = 20

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.5

# JPL requests operate at RANGE level.
# Initial attempt + one retry maximum.
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


# ---------------------------------------------------------------------------
# BASIC HELPERS
# ---------------------------------------------------------------------------


def _is_valid_number(value: Any) -> bool:
    """Return True only for finite, unmasked numeric values."""

    if value is None:
        return False

    # Astropy tables can contain masked values for unavailable ephemeris
    # fields. Detect these BEFORE converting to float.
    try:
        if np.ma.is_masked(value):
            return False
    except Exception:
        pass

    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False

    return math.isfinite(number)


def _normalize_lon(lon: float) -> float:
    return float(lon) % 360.0


def _iso_utc(dt: datetime.datetime) -> str:
    return (
        dt.astimezone(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _date_key(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _daily_samples(
    start_dt: datetime.datetime,
    days: int = SAMPLE_DAYS,
) -> List[datetime.datetime]:
    """Generate exactly `days` daily UTC samples."""

    start = start_dt.astimezone(datetime.timezone.utc)

    return [
        start + datetime.timedelta(days=offset)
        for offset in range(days)
    ]


# ---------------------------------------------------------------------------
# PROVIDER / CATALOG ROUTING
# ---------------------------------------------------------------------------


def _normalize_provider(provider: str) -> str:
    lowered = provider.lower().strip()

    if lowered in {"horizons", "jpl"}:
        return "jpl"

    if lowered in {"miriade", "imcce"}:
        return "miriade"

    if lowered in {
        "swiss",
        "swisseph",
        "swiss_ephemeris",
    }:
        return "swiss"

    if lowered in {"fixed_star_catalog", "fixed"}:
        return "fixed"

    if lowered == "calculated":
        return "calculated"

    return lowered


def _is_moving_entry(
    category: str,
    body: Dict[str, Any],
) -> bool:
    if category in {"fixed_stars", "aether_points"}:
        return False

    providers = [
        _normalize_provider(p)
        for p in body.get("provider_priority", [])
    ]

    if "calculated" in providers:
        return False

    if "fixed" in providers:
        return False

    return True


def _normalize_horizons_id(
    body: Dict[str, Any],
) -> Optional[str]:
    """Normalize Horizons identifiers.

    Numeric small-body identifiers receive a trailing semicolon so Horizons
    treats them as small-body identifiers rather than major-body IDs.
    """

    raw = body.get("horizons_id")

    if raw is None:
        return body.get("name")

    text = str(raw).strip()

    if not text:
        return body.get("name")

    id_type = str(
        body.get("horizons_id_type") or ""
    ).lower()

    category = str(
        body.get("category") or ""
    ).lower()

    if (
        id_type != "majorbody"
        and category != "core_bodies"
        and not text.endswith(";")
    ):
        return f"{text};"

    return text


def _has_valid_jpl_mapping(
    body: Dict[str, Any],
) -> bool:
    """Return True only when the body has a configured Horizons ID."""

    raw = body.get("horizons_id")

    if raw is None:
        return False

    return bool(str(raw).strip())


def _has_valid_miriade_mapping(
    body: Dict[str, Any],
) -> bool:
    """Return True when the body can be addressed through Miriade."""

    explicit = body.get("miriade_name")

    if explicit and str(explicit).strip():
        return True

    # Existing repository convention:
    # Miriade may be addressed using a:<Name>.
    return bool(body.get("name"))


def _has_valid_swiss_mapping(
    body: Dict[str, Any],
) -> bool:
    """Return True only when Swiss has an actual local mapping."""

    code = body.get("swiss_code")

    if code is not None:
        return True

    name = body.get("name")

    if not name:
        return False

    return (
        SWISS_IDS.get(str(name).lower())
        is not None
    )


def _provider_chain(
    body: Dict[str, Any],
) -> List[str]:
    """Build the mandatory 6-month provider chain.

    Provider priority is ALWAYS:

        JPL Horizons -> Miriade -> Swiss Ephemeris

    Unsupported providers are skipped.

    The celestial catalog supplies body/provider capability information,
    but it does not override this mandatory 6-month priority.
    """

    chain: List[str] = []

    # PRIMARY
    if _has_valid_jpl_mapping(body):
        chain.append("jpl")

    # SECONDARY
    if _has_valid_miriade_mapping(body):
        chain.append("miriade")

    # FINAL LOCAL FALLBACK
    if _has_valid_swiss_mapping(body):
        chain.append("swiss")

    return chain


def load_catalog_targets(
    path: Path = CATALOG_PATH,
) -> Tuple[
    List[Dict[str, Any]],
    List[str],
    List[str],
]:
    """Load moving bodies, fixed stars, and Aether points."""

    with path.open(
        "r",
        encoding="utf-8",
    ) as f:
        catalog = json.load(f)

    categories = catalog.get(
        "categories",
        {},
    )

    moving: List[Dict[str, Any]] = []
    fixed_star_names: List[str] = []
    aether_names: List[str] = []

    for category, bodies in categories.items():

        for body in bodies:

            entry = dict(body)

            entry.setdefault(
                "category",
                category,
            )

            if category == "fixed_stars":

                fixed_star_names.append(
                    entry["name"]
                )

                continue

            if category == "aether_points":

                aether_names.append(
                    entry["name"]
                )

                continue

            if not _is_moving_entry(
                category,
                entry,
            ):
                continue

            # Provider capability is determined once per body.
            # Mandatory 6-month priority:
            # JPL -> Miriade -> Swiss.
            entry["_provider_chain"] = (
                _provider_chain(entry)
            )

            entry["_horizons_id"] = (
                _normalize_horizons_id(entry)
            )

            moving.append(entry)

    return (
        moving,
        fixed_star_names,
        aether_names,
    )


# ---------------------------------------------------------------------------
# COORDINATE / DATE PARSING
# ---------------------------------------------------------------------------


def _extract_lon_lat(
    row: Any,
    colnames: Sequence[str],
    dt: datetime.datetime,
) -> Optional[Tuple[float, float]]:

    lon = None
    lat = None

    for key in (
        "EclLon",
        "EclipticLon",
        "ELON",
    ):
        if key in colnames:
            lon = row[key]
            break

    for key in (
        "EclLat",
        "EclipticLat",
        "ELAT",
    ):
        if key in colnames:
            lat = row[key]
            break

    # If direct ecliptic coordinates are unavailable,
    # derive them from RA/DEC.
    if (
        lon is None
        or lat is None
    ) and (
        "RA" in colnames
        and "DEC" in colnames
    ):

        try:

            ra = row["RA"]
            dec = row["DEC"]

            if (
                not _is_valid_number(ra)
                or not _is_valid_number(dec)
            ):
                return None

            lon, lat = ra_dec_to_ecl(
                float(ra),
                float(dec),
                _iso_utc(dt),
            )

        except Exception:
            return None

    if (
        not _is_valid_number(lon)
        or not _is_valid_number(lat)
    ):
        return None

    return (
        _normalize_lon(float(lon)),
        float(lat),
    )


def _parse_row_date(
    row: Any,
    colnames: Sequence[str],
    fallback_dt: Optional[
        datetime.datetime
    ],
) -> Optional[datetime.date]:

    if "datetime_str" in colnames:

        raw = row["datetime_str"]

        if not np.ma.is_masked(raw):

            try:

                parsed = date_parser.parse(
                    str(raw).strip()
                )

                if parsed.tzinfo is None:
                    parsed = parsed.replace(
                        tzinfo=datetime.timezone.utc
                    )

                return (
                    parsed.astimezone(
                        datetime.timezone.utc
                    ).date()
                )

            except Exception:
                pass

    if "datetime_jd" in colnames:

        raw_jd = row["datetime_jd"]

        if _is_valid_number(raw_jd):

            try:

                jd = float(raw_jd)

                year, month, day, ut = (
                    swe.revjul(
                        jd,
                        swe.GREG_CAL,
                    )
                )

                hour = int(ut)

                minute_float = (
                    (ut - hour) * 60
                )

                minute = int(
                    minute_float
                )

                second = int(
                    round(
                        (
                            minute_float
                            - minute
                        )
                        * 60
                    )
                )

                if second >= 60:
                    second = 59

                parsed = datetime.datetime(
                    year,
                    month,
                    day,
                    hour,
                    minute,
                    second,
                    tzinfo=datetime.timezone.utc,
                )

                return parsed.date()

            except Exception:
                pass

    if fallback_dt is None:
        return None

    return fallback_dt.date()


def _parse_miriade_row_date(
    row: Dict[str, Any],
    fallback_dt: Optional[
        datetime.datetime
    ],
) -> Optional[datetime.date]:

    raw = (
        row.get("datetime_str")
        or row.get("date")
        or row.get("epoch")
    )

    if raw is not None:

        try:

            parsed = date_parser.parse(
                str(raw).strip()
            )

            if parsed.tzinfo is None:
                parsed = parsed.replace(
                    tzinfo=datetime.timezone.utc
                )

            return (
                parsed.astimezone(
                    datetime.timezone.utc
                ).date()
            )

        except Exception:
            pass

    raw_jd = row.get(
        "datetime_jd"
    )

    if _is_valid_number(raw_jd):

        try:

            jd = float(raw_jd)

            year, month, day, ut = (
                swe.revjul(
                    jd,
                    swe.GREG_CAL,
                )
            )

            hour = int(ut)

            minute_float = (
                (ut - hour) * 60
            )

            minute = int(
                minute_float
            )

            second = int(
                round(
                    (
                        minute_float
                        - minute
                    )
                    * 60
                )
            )

            if second >= 60:
                second = 59

            parsed = datetime.datetime(
                year,
                month,
                day,
                hour,
                minute,
                second,
                tzinfo=datetime.timezone.utc,
            )

            return parsed.date()

        except Exception:
            pass

    if fallback_dt is None:
        return None

    return fallback_dt.date()


# ---------------------------------------------------------------------------
# RETRY HELPERS
# ---------------------------------------------------------------------------


def _call_with_retries(
    fn,
    attempts: int = RETRY_ATTEMPTS,
):
    last_exc = None

    for idx in range(attempts):

        try:
            return fn()

        except Exception as exc:

            last_exc = exc

            if idx < attempts - 1:

                time.sleep(
                    RETRY_BACKOFF_SECONDS
                    * (idx + 1)
                )

    if last_exc:
        raise last_exc

    raise RuntimeError(
        "retry helper failed without exception"
    )


def _is_timeout_exception(
    exc: Exception,
) -> bool:

    if isinstance(
        exc,
        (
            socket.timeout,
            TimeoutError,
        ),
    ):
        return True

    if isinstance(
        exc,
        requests.exceptions.Timeout,
    ):
        return True

    text = str(exc).lower()

    return (
        "timed out" in text
        or "timeout" in text
    )


# ---------------------------------------------------------------------------
# JPL HORIZONS RANGE RESOLUTION
# ---------------------------------------------------------------------------


def fetch_horizons_range(
    body: Dict[str, Any],
    dt_list: Sequence[
        datetime.datetime
    ],
    stats: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:

    if not dt_list:
        return {}

    ordered = sorted(
        dt_list
    )

    start_dt = ordered[0]
    stop_dt = ordered[-1]

    body_id = (
        body.get("_horizons_id")
        or body["name"]
    )

    body_name = body.get(
        "name",
        "unknown",
    )

    def _request():

        # Apply timeout to Horizons requests.
        Horizons.TIMEOUT = (
            REQUEST_TIMEOUT_HORIZONS
        )

        # One range request returns the complete contiguous daily interval.
        return Horizons(
            id=body_id,
            location=HORIZONS_LOCATION,
            epochs={
                "start": start_dt.strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "stop": stop_dt.strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "step": "1d",
            },
        ).ephemerides()

    eph = None

    for attempt in range(
        JPL_RETRY_ATTEMPTS
    ):

        stats["jpl_range_requests"] = (
            stats.get(
                "jpl_range_requests",
                0,
            )
            + 1
        )

        try:

            eph = _request()

            break

        except Exception as exc:

            if _is_timeout_exception(exc):

                stats["jpl_timeouts"] = (
                    stats.get(
                        "jpl_timeouts",
                        0,
                    )
                    + 1
                )

                print(
                    f"[6M] {body_name}: "
                    f"JPL range request timed out "
                    f"after "
                    f"{REQUEST_TIMEOUT_HORIZONS}s"
                )

            else:

                print(
                    f"[6M] {body_name}: "
                    f"JPL range request failed: "
                    f"{exc}"
                )

            if (
                attempt
                < JPL_RETRY_ATTEMPTS - 1
            ):

                stats["jpl_retries"] = (
                    stats.get(
                        "jpl_retries",
                        0,
                    )
                    + 1
                )

                print(
                    f"[6M] {body_name}: "
                    f"retry "
                    f"{attempt + 1}/"
                    f"{JPL_RETRY_ATTEMPTS - 1}"
                )

                time.sleep(
                    JPL_RETRY_BACKOFF_SECONDS
                )

    if eph is None:

        stats["jpl_range_failures"] = (
            stats.get(
                "jpl_range_failures",
                0,
            )
            + 1
        )

        print(
            f"[6M] {body_name}: "
            "JPL unresolved; "
            "continuing to next provider"
        )

        return {}

    results: Dict[
        str,
        Dict[str, Any],
    ] = {}

    colnames = list(
        getattr(
            eph,
            "colnames",
            [],
        )
    )

    expected_dates = {
        dt.date()
        for dt in ordered
    }

    dt_by_date = {
        dt.date(): dt
        for dt in ordered
    }

    for idx in range(
        len(eph)
    ):

        row = eph[idx]

        fallback_dt = (
            ordered[idx]
            if idx < len(ordered)
            else None
        )

        row_date = (
            _parse_row_date(
                row,
                colnames,
                fallback_dt,
            )
        )

        if row_date is None:
            continue

        if row_date not in expected_dates:
            continue

        expected_dt = (
            dt_by_date[
                row_date
            ]
        )

        lonlat = (
            _extract_lon_lat(
                row,
                colnames,
                expected_dt,
            )
        )

        if lonlat is None:
            continue

        lon, lat = lonlat

        key = (
            row_date.strftime(
                "%Y-%m-%d"
            )
        )

        results[key] = {
            "ecl_lon_deg": lon,
            "ecl_lat_deg": lat,
            "source": "jpl",
        }

    print(
        f"[6M] {body_name}: "
        f"JPL resolved "
        f"{len(results)}/"
        f"{len(ordered)} points"
    )

    return results


# ---------------------------------------------------------------------------
# MIRIADE RANGE RESOLUTION
# ---------------------------------------------------------------------------


def _miriade_name(
    body: Dict[str, Any],
) -> str:

    if body.get(
        "miriade_name"
    ):
        return str(
            body[
                "miriade_name"
            ]
        )

    return (
        f"a:{body['name']}"
    )


def _group_contiguous_dates(
    sorted_dts: Sequence[
        datetime.datetime
    ],
) -> List[
    List[
        datetime.datetime
    ]
]:

    if not sorted_dts:
        return []

    ordered = sorted(
        sorted_dts
    )

    groups: List[
        List[
            datetime.datetime
        ]
    ] = []

    current: List[
        datetime.datetime
    ] = []

    prev_date: Optional[
        datetime.date
    ] = None

    for dt in ordered:

        if (
            prev_date is not None
            and (
                dt.date()
                - prev_date
            ).days
            == 1
        ):

            current.append(
                dt
            )

        else:

            if current:
                groups.append(
                    current
                )

            current = [dt]

        prev_date = (
            dt.date()
        )

    if current:

        groups.append(
            current
        )

    return groups


def fetch_miriade_range(
    body: Dict[str, Any],
    missing_dates: Sequence[
        datetime.datetime
    ],
    stats: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Resolve one contiguous date range with a single Miriade request."""

    if not missing_dates:
        return {}

    ordered = sorted(
        missing_dates
    )

    start_dt = ordered[0]

    nbd = len(
        ordered
    )

    body_name = body.get(
        "name",
        "unknown",
    )

    params = {
        "-name": _miriade_name(
            body
        ),
        "-ep": _iso_utc(
            start_dt
        ),
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

        response = requests.get(
            MIRIADE_BASE,
            params=params,
            timeout=(
                REQUEST_TIMEOUT_MIRIADE
            ),
        )

        response.raise_for_status()

        raw_payload = (
            response.json()
        )

        payload = (
            raw_payload.get(
                "result",
                {},
            )
        )

        if isinstance(
            payload,
            str,
        ):

            payload = (
                json.loads(
                    payload
                )
            )

        if not isinstance(
            payload,
            dict,
        ):

            return {}

        return payload

    stats[
        "miriade_range_requests"
    ] = (
        stats.get(
            "miriade_range_requests",
            0,
        )
        + 1
    )

    stats[
        "miriade_fallback_requests"
    ] = (
        stats.get(
            "miriade_fallback_requests",
            0,
        )
        + 1
    )

    try:

        payload = (
            _call_with_retries(
                _request_json
            )
        )

    except Exception as exc:

        print(
            f"[6M] {body_name}: "
            f"Miriade range failed: "
            f"{exc}"
        )

        return {}

    rows = payload.get(
        "data",
        [],
    )

    if not isinstance(
        rows,
        list,
    ):
        return {}

    if not rows:
        return {}

    results: Dict[
        str,
        Dict[str, Any],
    ] = {}

    expected_dates = {
        dt.date()
        for dt in ordered
    }

    dt_by_date = {
        dt.date(): dt
        for dt in ordered
    }

    for idx, raw_row in enumerate(
        rows
    ):

        if not isinstance(
            raw_row,
            dict,
        ):
            continue

        row = {
            str(k).lower(): v
            for k, v
            in raw_row.items()
        }

        fallback_dt = (
            ordered[idx]
            if idx < len(ordered)
            else None
        )

        row_date = (
            _parse_miriade_row_date(
                row,
                fallback_dt,
            )
        )

        if row_date is None:
            continue

        if (
            row_date
            not in expected_dates
        ):
            continue

        expected_dt = (
            dt_by_date[
                row_date
            ]
        )

        # 0.0 is valid, so do not use Python "or" when choosing
        # coordinate columns.
        lon = row.get(
            "elon"
        )

        if lon is None:
            lon = row.get(
                "ecllon"
            )

        lat = row.get(
            "elat"
        )

        if lat is None:
            lat = row.get(
                "ecllat"
            )

        if (
            lon is None
            or lat is None
        ):

            ra = row.get(
                "ra"
            )

            dec = row.get(
                "dec"
            )

            if (
                _is_valid_number(
                    ra
                )
                and _is_valid_number(
                    dec
                )
            ):

                try:

                    lon, lat = (
                        ra_dec_to_ecl(
                            float(ra),
                            float(dec),
                            _iso_utc(
                                expected_dt
                            ),
                        )
                    )

                except Exception:
                    continue

        if (
            not _is_valid_number(
                lon
            )
            or not _is_valid_number(
                lat
            )
        ):
            continue

        key = (
            row_date.strftime(
                "%Y-%m-%d"
            )
        )

        results[key] = {
            "ecl_lon_deg":
                _normalize_lon(
                    float(lon)
                ),

            "ecl_lat_deg":
                float(lat),

            "source":
                "miriade",
        }

        stats[
            "miriade_points_resolved"
        ] = (
            stats.get(
                "miriade_points_resolved",
                0,
            )
            + 1
        )

    print(
        f"[6M] {body_name}: "
        f"Miriade resolved "
        f"{len(results)}/"
        f"{len(ordered)} points"
    )

    return results


# ---------------------------------------------------------------------------
# SWISS LOCAL FALLBACK
# ---------------------------------------------------------------------------


def fetch_swiss_point(
    body: Dict[str, Any],
    dt: datetime.datetime,
    stats: Dict[str, Any],
) -> Optional[
    Dict[str, Any]
]:

    stats[
        "swiss_fallback_requests"
    ] = (
        stats.get(
            "swiss_fallback_requests",
            0,
        )
        + 1
    )

    code = body.get(
        "swiss_code"
    )

    if code is None:

        code = (
            SWISS_IDS.get(
                body[
                    "name"
                ].lower()
            )
        )

    if code is None:
        return None

    jd = swe.julday(
        dt.year,
        dt.month,
        dt.day,
        (
            dt.hour
            + dt.minute / 60.0
            + dt.second / 3600.0
        ),
    )

    try:

        result = swe.calc_ut(
            jd,
            int(code),
        )

    except Exception:
        return None

    values = (
        result[0]
        if (
            isinstance(
                result,
                tuple,
            )
            and len(result) == 2
        )
        else result
    )

    if (
        not isinstance(
            values,
            (list, tuple),
        )
        or len(values) < 2
    ):
        return None

    lon = values[0]
    lat = values[1]

    if (
        not _is_valid_number(
            lon
        )
        or not _is_valid_number(
            lat
        )
    ):
        return None

    return {
        "ecl_lon_deg":
            _normalize_lon(
                float(lon)
            ),

        "ecl_lat_deg":
            float(lat),

        "source":
            "swiss",
    }


# ---------------------------------------------------------------------------
# FIXED STARS
# ---------------------------------------------------------------------------


def load_fixed_stars_for_catalog(
    names: Iterable[str],
    reference_dt: Optional[
        datetime.datetime
    ] = None,
) -> Dict[
    str,
    Dict[str, float],
]:

    selected = set(
        names
    )

    if not selected:
        return {}

    path = (
        FIXED_STARS_PRIMARY
        if FIXED_STARS_PRIMARY.exists()
        else FIXED_STARS_FALLBACK
    )

    if not path.exists():
        return {}

    epoch = (
        reference_dt
        or datetime.datetime.now(
            datetime.timezone.utc
        )
    )

    with path.open(
        "r",
        encoding="utf-8",
    ) as f:

        payload = (
            json.load(f)
        )

    stars = payload.get(
        "stars",
        [],
    )

    output: Dict[
        str,
        Dict[str, float],
    ] = {}

    for star in stars:

        star_id = (
            star.get("id")
        )

        if (
            star_id
            not in selected
        ):
            continue

        try:

            ra = float(
                star[
                    "ra_deg"
                ]
            )

            dec = float(
                star[
                    "dec_deg"
                ]
            )

            lon, lat = (
                ra_dec_to_ecl(
                    ra,
                    dec,
                    _iso_utc(
                        epoch
                    ),
                )
            )

        except Exception:
            continue

        if (
            _is_valid_number(
                lon
            )
            and _is_valid_number(
                lat
            )
        ):

            output[
                star_id
            ] = {
                "ecl_lon_deg":
                    _normalize_lon(
                        float(lon)
                    ),

                "ecl_lat_deg":
                    float(lat),

                "source":
                    "fixed",
            }

    return output


# ---------------------------------------------------------------------------
# AETHER POINTS
# ---------------------------------------------------------------------------


def _lon_from_day(
    day_transits: Dict[
        str,
        Dict[str, Any],
    ],
    name: str,
) -> Optional[float]:

    entry = (
        day_transits.get(
            name
        )
    )

    if not entry:
        return None

    lon = entry.get(
        "ecl_lon_deg"
    )

    if not _is_valid_number(
        lon
    ):
        return None

    return float(
        lon
    )


def add_aether_points(
    day_transits: Dict[
        str,
        Dict[str, Any],
    ],
    aether_names: Sequence[str],
) -> None:

    sun = _lon_from_day(
        day_transits,
        "Sun",
    )

    moon = _lon_from_day(
        day_transits,
        "Moon",
    )

    mars = _lon_from_day(
        day_transits,
        "Mars",
    )

    jupiter = _lon_from_day(
        day_transits,
        "Jupiter",
    )

    saturn = _lon_from_day(
        day_transits,
        "Saturn",
    )

    venus = _lon_from_day(
        day_transits,
        "Venus",
    )

    midpoint = (
        None
        if (
            sun is None
            or moon is None
        )
        else _normalize_lon(
            (
                sun
                + moon
            )
            % 360.0
        )
    )

    jovian_arc = (
        None
        if (
            jupiter is None
            or saturn is None
        )
        else _normalize_lon(
            jupiter
            - saturn
        )
    )

    elemental_balance = (
        None
        if (
            mars is None
            or venus is None
            or moon is None
        )
        else _normalize_lon(
            (
                mars
                + venus
                + moon
            )
            / 3.0
        )
    )

    formulas = {
        "Aetheric_SunMoon_Midpoint":
            midpoint,

        "Aetheric_Jovian_Arc":
            jovian_arc,

        "Aetheric_Elemental_Balance":
            elemental_balance,
    }

    for name in aether_names:

        value = (
            formulas.get(
                name
            )
        )

        day_transits[
            name
        ] = {
            "ecl_lon_deg":
                (
                    None
                    if value is None
                    else float(value)
                ),

            "ecl_lat_deg":
                (
                    None
                    if value is None
                    else 0.0
                ),

            "source":
                "calculated",
        }


# ---------------------------------------------------------------------------
# BODY RESOLUTION
# ---------------------------------------------------------------------------


def _classify_provider_route(
    chain: Sequence[str],
) -> str:

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
    dt_list: Sequence[
        datetime.datetime
    ],
    stats: Dict[str, Any],
) -> Tuple[
    Dict[
        str,
        Dict[str, Any],
    ],
    List[
        Dict[str, Any]
    ],
]:
    """Resolve one body across the complete 182-day range.

    Mandatory provider priority:

        1. JPL Horizons
        2. Miriade
        3. Swiss Ephemeris

    Unsupported providers are skipped.

    Each subsequent provider receives only dates not resolved by the
    previous provider.

    JPL and Miriade operate using range requests.
    Swiss is local and resolves only remaining dates.
    """

    date_keys = [
        _date_key(dt)
        for dt in dt_list
    ]

    dt_lookup = {
        _date_key(dt):
            dt
        for dt in dt_list
    }

    missing: Set[str] = (
        set(date_keys)
    )

    resolved: Dict[
        str,
        Dict[str, Any],
    ] = {}

    attempted: Dict[
        str,
        List[str],
    ] = {
        key: []
        for key in date_keys
    }

    body_name = body.get(
        "name",
        "unknown",
    )

    # Chain is already ordered:
    #
    # JPL -> Miriade -> Swiss
    #
    # Unsupported providers are absent.
    chain = list(
        body.get(
            "_provider_chain",
            [],
        )
    )

    route = (
        _classify_provider_route(
            chain
        )
    )

    stats.setdefault(
        "provider_route_counts",
        {
            "jpl_primary": 0,
            "miriade_primary": 0,
            "swiss_primary": 0,
            "no_valid_provider": 0,
        },
    )

    stats[
        "provider_route_counts"
    ][route] = (
        stats[
            "provider_route_counts"
        ].get(
            route,
            0,
        )
        + 1
    )

    if not chain:

        print(
            f"[6M] WARNING: "
            f"{body_name} has no "
            "valid provider"
        )

        missing_entries = [
            {
                "date": key,
                "body":
                    body_name,

                "providers_attempted":
                    [],

                "reason":
                    "no_valid_provider_configured",
            }

            for key
            in sorted(
                missing
            )
        ]

        return (
            resolved,
            missing_entries,
        )

    chain_labels = (
        " -> ".join(
            PROVIDER_LABELS.get(
                provider,
                provider,
            )
            for provider
            in chain
        )
    )

    print(
        f"[6M] {body_name} providers: "
        f"{chain_labels}"
    )

    # Execute provider chain exactly as built:
    #
    # JPL -> Miriade -> Swiss
    #
    # Only unresolved dates continue downstream.

    for provider in chain:

        if not missing:
            break

        # ===============================================================
        # JPL HORIZONS — PRIMARY
        # ===============================================================

        if provider == "jpl":

            missing_keys = sorted(
                missing,
                key=lambda key:
                    dt_lookup[key],
            )

            for key in missing_keys:

                attempted[
                    key
                ].append(
                    "JPL"
                )

            missing_dts = [
                dt_lookup[key]
                for key in missing_keys
            ]

            groups = (
                _group_contiguous_dates(
                    missing_dts
                )
            )

            for group in groups:

                if not group:
                    continue

                try:

                    jpl_results = (
                        fetch_horizons_range(
                            body,
                            group,
                            stats,
                        )
                    )

                except Exception as exc:

                    print(
                        f"[6M] "
                        f"{body_name}: "
                        f"JPL range failure: "
                        f"{exc}"
                    )

                    jpl_results = {}

                for (
                    key,
                    point,
                ) in (
                    jpl_results.items()
                ):

                    if (
                        key
                        not in missing
                    ):
                        continue

                    resolved[
                        key
                    ] = point

                    missing.discard(
                        key
                    )

        # ===============================================================
        # MIRIADE — SECONDARY
        # ===============================================================

        elif provider == "miriade":

            missing_keys = sorted(
                missing,
                key=lambda key:
                    dt_lookup[key],
            )

            for key in missing_keys:

                attempted[
                    key
                ].append(
                    "Miriade"
                )

            missing_dts = [
                dt_lookup[key]
                for key
                in missing_keys
            ]

            groups = (
                _group_contiguous_dates(
                    missing_dts
                )
            )

            for group in groups:

                if not group:
                    continue

                try:

                    miriade_results = (
                        fetch_miriade_range(
                            body,
                            group,
                            stats,
                        )
                    )

                except Exception as exc:

                    print(
                        f"[6M] "
                        f"{body_name}: "
                        f"Miriade range failure: "
                        f"{exc}"
                    )

                    miriade_results = {}

                for (
                    key,
                    point,
                ) in (
                    miriade_results.items()
                ):

                    if (
                        key
                        not in missing
                    ):
                        continue

                    resolved[
                        key
                    ] = point

                    missing.discard(
                        key
                    )

        # ===============================================================
        # SWISS EPHEMERIS — FINAL LOCAL FALLBACK
        # ===============================================================

        elif provider == "swiss":

            for key in sorted(
                list(
                    missing
                )
            ):

                attempted[
                    key
                ].append(
                    "Swiss"
                )

                point = (
                    fetch_swiss_point(
                        body,
                        dt_lookup[key],
                        stats,
                    )
                )

                if point is None:
                    continue

                resolved[
                    key
                ] = point

                missing.discard(
                    key
                )

    missing_entries = [
        {
            "date":
                key,

            "body":
                body_name,

            "providers_attempted":
                attempted[key],
        }

        for key
        in sorted(
            missing
        )
    ]

    print(
        f"[6M] "
        f"{body_name}: "
        f"resolved "
        f"{len(resolved)}/"
        f"{len(date_keys)}"
    )

    return (
        resolved,
        missing_entries,
    )


# ---------------------------------------------------------------------------
# ATOMIC OUTPUT
# ---------------------------------------------------------------------------


def write_output_atomic(
    path: Path,
    payload: Dict[str, Any],
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fd, tmp_name = (
        tempfile.mkstemp(
            dir=str(
                path.parent
            ),
            suffix=".tmp.json",
        )
    )

    try:

        try:

            fh = os.fdopen(
                fd,
                "w",
                encoding="utf-8",
            )

        except Exception:

            os.close(
                fd
            )

            raise

        with fh:

            json.dump(
                payload,
                fh,
                indent=2,
            )

        os.replace(
            tmp_name,
            path,
        )

    except Exception:

        try:

            os.unlink(
                tmp_name
            )

        except OSError:
            pass

        raise


# ---------------------------------------------------------------------------
# COMPLETE SIX-MONTH GENERATION
# ---------------------------------------------------------------------------


def generate_six_month_feed(
    start_dt: Optional[
        datetime.datetime
    ] = None,
) -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
]:

    started = (
        time.perf_counter()
    )

    utc_now = (
        start_dt.astimezone(
            datetime.timezone.utc
        )
        if start_dt
        else datetime.datetime.now(
            datetime.timezone.utc
        )
    )

    dt_list = (
        _daily_samples(
            utc_now,
            SAMPLE_DAYS,
        )
    )

    date_keys = [
        _date_key(dt)
        for dt
        in dt_list
    ]

    (
        moving_bodies,
        fixed_star_names,
        aether_names,
    ) = (
        load_catalog_targets()
    )

    fixed_star_positions = (
        load_fixed_stars_for_catalog(
            fixed_star_names,
            reference_dt=(
                dt_list[0]
            ),
        )
    )

    transits: Dict[
        str,
        Dict[
            str,
            Dict[str, Any],
        ],
    ] = {
        day: {}
        for day
        in date_keys
    }

    total_points = (
        len(moving_bodies)
        * len(dt_list)
    )

    stats: Dict[
        str,
        Any,
    ] = {
        "jpl_range_requests":
            0,

        "jpl_range_failures":
            0,

        "jpl_retries":
            0,

        "jpl_timeouts":
            0,

        "miriade_fallback_requests":
            0,

        "miriade_range_requests":
            0,

        "miriade_points_resolved":
            0,

        "swiss_fallback_requests":
            0,

        "provider_route_counts": {
            "jpl_primary":
                0,

            "miriade_primary":
                0,

            "swiss_primary":
                0,

            "no_valid_provider":
                0,
        },
    }

    missing: List[
        Dict[str, Any]
    ] = []

    resolved_points = 0

    for body in moving_bodies:

        (
            body_points,
            body_missing,
        ) = (
            resolve_moving_body(
                body,
                dt_list,
                stats,
            )
        )

        for day in date_keys:

            point = (
                body_points.get(
                    day
                )
            )

            if point is None:
                continue

            transits[
                day
            ][
                body["name"]
            ] = point

            resolved_points += 1

        missing.extend(
            body_missing
        )

    # Fixed stars and Aether points are added after moving-body resolution.
    # They do not affect moving-body coverage.
    for day in date_keys:

        day_transits = (
            transits[day]
        )

        for (
            star_name,
            star_data,
        ) in (
            fixed_star_positions.items()
        ):

            day_transits[
                star_name
            ] = dict(
                star_data
            )

        add_aether_points(
            day_transits,
            aether_names,
        )

    duration = (
        time.perf_counter()
        - started
    )

    coverage = (
        resolved_points
        / total_points
        if total_points
        else 0.0
    )

    start_range = (
        dt_list[0]
    )

    end_range = (
        dt_list[-1]
    )

    data: Dict[
        str,
        Any,
    ] = {
        "engine_version":
            "ZodiacOracle.SixMonthTransit.v2",

        "meta": {
            "generated_at_utc":
                datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),

            "generated_at_pacific":
                datetime.datetime.now(
                    pytz.timezone(
                        "America/Los_Angeles"
                    )
                ).isoformat(),

            "type":
                "6-month overlay",

            "range_utc": [
                start_range.isoformat(),
                end_range.isoformat(),
            ],

            "range":
                (
                    f"{start_range.strftime('%Y-%m-%d')} "
                    f"to "
                    f"{end_range.strftime('%Y-%m-%d')}"
                ),

            "source_order": [
                "jpl",
                "miriade",
                "swiss",
                "fixed",
                "calculated",
            ],
        },

        "transits":
            transits,

        "coverage":
            coverage,

        "resolved_points":
            resolved_points,

        "total_points":
            total_points,

        "missing":
            missing,

        "moving_body_count":
            len(
                moving_bodies
            ),

        "runtime": {
            "duration_seconds":
                duration,

            "jpl_range_requests":
                stats[
                    "jpl_range_requests"
                ],

            "jpl_range_failures":
                stats[
                    "jpl_range_failures"
                ],

            "jpl_retries":
                stats[
                    "jpl_retries"
                ],

            "jpl_timeouts":
                stats[
                    "jpl_timeouts"
                ],

            "miriade_fallback_requests":
                stats[
                    "miriade_fallback_requests"
                ],

            "miriade_range_requests":
                stats[
                    "miriade_range_requests"
                ],

            "miriade_points_resolved":
                stats[
                    "miriade_points_resolved"
                ],

            "swiss_fallback_requests":
                stats[
                    "swiss_fallback_requests"
                ],

            "provider_route_counts":
                stats[
                    "provider_route_counts"
                ],

            "missing_points":
                len(
                    missing
                ),

            "resolved_points":
                resolved_points,
        },
    }

    return (
        data,
        stats,
    )


# ---------------------------------------------------------------------------
# CLI ENTRY
# ---------------------------------------------------------------------------


def main() -> None:

    data, _stats = (
        generate_six_month_feed()
    )

    pacific = (
        datetime.datetime.now(
            pytz.timezone(
                "America/Los_Angeles"
            )
        )
    )

    filename = (
        "feed_overlay_6month_"
        f"{pacific.strftime('%b-%d-%Y_%I-%M%p')}"
        "_Pacific.json"
    )

    outpath = (
        ROOT
        / "docs"
        / filename
    )

    write_output_atomic(
        outpath,
        data,
    )

    print(
        "✅ 6-month feed generation complete"
    )

    print(
        f"   moving bodies             : "
        f"{data['moving_body_count']}"
    )

    print(
        f"   date samples              : "
        f"{len(data['transits'])}"
    )

    print(
        f"   total_points              : "
        f"{data['total_points']}"
    )

    print(
        f"   resolved_points           : "
        f"{data['resolved_points']}"
    )

    print(
        f"   coverage                  : "
        f"{data['coverage']:.6f}"
    )

    print(
        f"   missing points            : "
        f"{len(data['missing'])}"
    )

    print(
        f"   jpl range requests        : "
        f"{data['runtime']['jpl_range_requests']}"
    )

    print(
        f"   jpl range failures        : "
        f"{data['runtime']['jpl_range_failures']}"
    )

    print(
        f"   jpl retries               : "
        f"{data['runtime']['jpl_retries']}"
    )

    print(
        f"   jpl timeouts              : "
        f"{data['runtime']['jpl_timeouts']}"
    )

    print(
        f"   miriade range requests    : "
        f"{data['runtime']['miriade_range_requests']}"
    )

    print(
        f"   miriade points resolved   : "
        f"{data['runtime']['miriade_points_resolved']}"
    )

    print(
        f"   miriade fallback requests : "
        f"{data['runtime']['miriade_fallback_requests']}"
    )

    print(
        f"   swiss fallback requests   : "
        f"{data['runtime']['swiss_fallback_requests']}"
    )

    print(
        f"   provider route counts     : "
        f"{data['runtime']['provider_route_counts']}"
    )

    print(
        f"   duration_seconds          : "
        f"{data['runtime']['duration_seconds']:.2f}"
    )

    print(
        f"   output                    : "
        f"{outpath}"
    )


if __name__ == "__main__":
    main()
