from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import requests
import swisseph as swe
from astroquery.jplhorizons import Horizons

from scripts.utils.coords import ra_dec_to_ecl


ROOT = Path(__file__).resolve().parents[1]

CATALOG_PATH = ROOT / "config" / "celestial_catalog.json"

FIXED_STARS_PATH = ROOT / "data" / "fixed_stars.json"
ALT_FIXED_STARS_PATH = ROOT / "data" / "fixed_star_catalog.json"


EPHEMERIS_PATH = ROOT / "ephemeris"

if not EPHEMERIS_PATH.exists():
    EPHEMERIS_PATH = ROOT / "ephe"

swe.set_ephe_path(str(EPHEMERIS_PATH))


# ---------------------------------------------------------------------------
# PROVIDER SETTINGS
# ---------------------------------------------------------------------------

HORIZONS_LOCATION = "500@399"

REQUEST_TIMEOUT_HORIZONS = 30
REQUEST_TIMEOUT_MIRIADE = 20


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


MIRIADE_BASE = (
    "https://ssp.imcce.fr/"
    "webservices/miriade/api/ephemcc.php"
)


ASTEROID_MIRIADE_IDS = {
    "Ceres": "1",
    "Pallas": "2",
    "Juno": "3",
    "Vesta": "4",
    "Hygiea": "10",
    "Eros": "433",
    "Psyche": "16",
    "Sappho": "80",
    "Hekate": "100",
    "Nemesis": "128",
    "Karma": "3811",
    "Destinn": "6583",
    "Aura": "1488",
    "Merlin": "2598",
}


HORIZONS_API = (
    "https://ssd.jpl.nasa.gov/"
    "api/horizons.api"
)


# ---------------------------------------------------------------------------
# BASIC HELPERS
# ---------------------------------------------------------------------------


def _is_valid_number(
    value: Any,
) -> bool:
    """Return True only for finite, non-masked numeric values."""

    if value is None:
        return False

    try:
        if np.ma.is_masked(value):
            return False
    except Exception:
        pass

    try:
        number = float(value)
    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return False

    return math.isfinite(number)


def _normalize_minor_body_id(
    value: Any,
) -> Optional[str]:
    """Return a plain minor-body identifier without a trailing semicolon."""

    if value is None:
        return None

    text = str(value).strip().rstrip(";")

    return text or None


def _normalize_horizons_id(
    body: Dict[str, Any],
) -> Optional[str]:
    """Return the Horizons identifier appropriate for this body.

    Major/core bodies retain their normal Horizons identifier.

    Small bodies use the Horizons semicolon form:

        1;
        2;
        2060;
        90377;

    This avoids relying on the deprecated explicit id_type argument.
    """

    raw = body.get("horizons_id")

    if raw is None:
        name = body.get("name")
        return str(name).strip() if name else None

    text = str(raw).strip()

    if not text:
        name = body.get("name")
        return str(name).strip() if name else None

    category = str(
        body.get("category")
        or body.get("_catalog_category")
        or ""
    ).lower()

    id_type = str(
        body.get("horizons_id_type")
        or ""
    ).lower()

    # Core planets / major bodies must not receive the small-body semicolon.
    if (
        category == "core_bodies"
        or id_type == "majorbody"
    ):
        return text.rstrip(";")

    # Everything else using a configured numeric/minor-body Horizons ID
    # receives the explicit small-body semicolon.
    if not text.endswith(";"):
        text = f"{text};"

    return text


def _miriade_identifiers(
    body: Dict[str, Any],
) -> List[str]:
    """Build possible Miriade identifiers for a body."""

    name = body["name"]

    identifiers: List[str] = []

    explicit = body.get("miriade_name")

    if explicit:
        identifiers.append(str(explicit))

    minor_body_id = _normalize_minor_body_id(
        body.get("mpc_designation")
        or body.get("horizons_id")
        or body.get("id")
    )

    if minor_body_id:
        identifiers.extend(
            [
                f"a:{minor_body_id}",
                f"a:{minor_body_id} {name}",
            ]
        )

    lowered = name.lower()

    if lowered == "moon":
        identifiers.append("s:Moon")

    elif lowered in {
        "sun",
        "mercury",
        "venus",
        "mars",
        "jupiter",
        "saturn",
        "uranus",
        "neptune",
    }:
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


def load_catalog(
    path: Path = CATALOG_PATH,
) -> Dict[str, Any]:
    with path.open(
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


def _utc_iso(
    dt: datetime,
) -> str:
    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _to_jd(
    dt: datetime,
) -> float:
    dt_utc = dt.astimezone(timezone.utc)

    return swe.julday(
        dt_utc.year,
        dt_utc.month,
        dt_utc.day,
        (
            dt_utc.hour
            + dt_utc.minute / 60.0
            + dt_utc.second / 3600.0
        ),
    )


# ---------------------------------------------------------------------------
# JPL HORIZONS
# ---------------------------------------------------------------------------


def _safe_table_number(
    table: Any,
    column: str,
    index: int = 0,
    default: float = 0.0,
) -> float:
    """Safely extract a finite numeric value from an Astropy table."""

    try:
        if column not in table.colnames:
            return default

        value = table[column][index]

        if not _is_valid_number(value):
            return default

        return float(value)

    except Exception:
        return default


def _horizons_position(
    body: Dict[str, Any],
    dt: datetime,
) -> Optional[Dict[str, float]]:
    """Resolve one geocentric ecliptic position through JPL Horizons."""

    prefetched = body.get("_horizons_prefetch")

    if (
        isinstance(prefetched, dict)
        and body["name"] in prefetched
    ):
        return prefetched[body["name"]]

    body_id = _normalize_horizons_id(body)

    if not body_id:
        return None

    # Astroquery's Horizons instance exposes TIMEOUT directly.
    Horizons.TIMEOUT = REQUEST_TIMEOUT_HORIZONS

    eph = Horizons(
        id=body_id,
        location=HORIZONS_LOCATION,
        epochs=[_to_jd(dt)],
    ).ephemerides()

    if len(eph) < 1:
        return None

    lon = None
    lat = None

    for key in (
        "EclLon",
        "EclipticLon",
        "ELON",
    ):
        if key not in eph.colnames:
            continue

        value = eph[key][0]

        if _is_valid_number(value):
            lon = float(value)
            break

    for key in (
        "EclLat",
        "EclipticLat",
        "ELAT",
    ):
        if key not in eph.colnames:
            continue

        value = eph[key][0]

        if _is_valid_number(value):
            lat = float(value)
            break

    # If Horizons does not expose direct ecliptic columns,
    # derive them from RA / DEC.
    if (
        lon is None
        or lat is None
    ) and {
        "RA",
        "DEC",
    }.issubset(eph.colnames):

        ra = eph["RA"][0]
        dec = eph["DEC"][0]

        if (
            _is_valid_number(ra)
            and _is_valid_number(dec)
        ):
            lon, lat = ra_dec_to_ecl(
                float(ra),
                float(dec),
                _utc_iso(dt),
            )

    if (
        not _is_valid_number(lon)
        or not _is_valid_number(lat)
    ):
        return None

    distance = _safe_table_number(
        eph,
        "delta",
        default=0.0,
    )

    velocity = _safe_table_number(
        eph,
        "vel_obs",
        default=0.0,
    )

    return {
        "longitude": float(lon) % 360.0,
        "latitude": float(lat),
        "distance": distance,
        "velocity": velocity,
    }


# ---------------------------------------------------------------------------
# OPTIONAL HORIZONS BATCH SUPPORT
# ---------------------------------------------------------------------------


def _parse_horizons_vector_batch(
    text: str,
    name_by_command: Dict[str, str],
) -> Dict[str, Dict[str, float]]:
    parsed: Dict[str, Dict[str, float]] = {}

    current_name: Optional[str] = None
    in_block = False

    for raw in text.splitlines():
        line = raw.strip()

        if line.startswith("Target body name:"):
            current_name = None

            for command, body_name in name_by_command.items():
                if f"({command})" in line:
                    current_name = body_name
                    break

            continue

        if line == "$$SOE":
            in_block = True
            continue

        if line == "$$EOE":
            in_block = False
            continue

        if not in_block or current_name is None:
            continue

        if line.startswith("X ="):
            tokens = (
                line
                .replace("=", " ")
                .split()
            )

            try:
                x = float(
                    tokens[
                        tokens.index("X") + 1
                    ]
                )

                y = float(
                    tokens[
                        tokens.index("Y") + 1
                    ]
                )

                z = float(
                    tokens[
                        tokens.index("Z") + 1
                    ]
                )

                lon = (
                    math.degrees(
                        math.atan2(y, x)
                    )
                    % 360.0
                )

                lat = math.degrees(
                    math.atan2(
                        z,
                        math.sqrt(
                            x * x + y * y
                        ),
                    )
                )

                parsed[current_name] = {
                    "longitude": lon,
                    "latitude": lat,
                    "distance": math.sqrt(
                        x * x
                        + y * y
                        + z * z
                    ),
                    "velocity": 0.0,
                }

            except (
                ValueError,
                IndexError,
            ):
                continue

    return parsed


def _horizons_batch_positions(
    bodies: List[Dict[str, Any]],
    dt: datetime,
) -> Dict[str, Dict[str, float]]:
    """Optional Horizons vector batch helper.

    The normal daily resolution path currently uses _horizons_position().
    This helper is retained for compatibility/future batching.
    """

    if not bodies:
        return {}

    command_by_name: Dict[str, str] = {}
    name_by_command: Dict[str, str] = {}

    for body in bodies:
        normalized = _normalize_horizons_id(body)

        if not normalized:
            continue

        command = normalized.rstrip(";")

        command_by_name[
            body["name"]
        ] = command

        name_by_command[
            command
        ] = body["name"]

    if not command_by_name:
        return {}

    command_list = ",".join(
        command_by_name.values()
    )

    params = {
        "format": "text",
        "COMMAND": f"'{command_list}'",
        "CENTER": "'500@399'",
        "TABLE_TYPE": "'VECTOR'",
        "REF_PLANE": "'ECLIPTIC'",
        "START_TIME": f"'{_utc_iso(dt)}'",
        "STOP_TIME": f"'{_utc_iso(dt)}'",
        "STEP_SIZE": "'1d'",
    }

    response = requests.get(
        HORIZONS_API,
        params=params,
        timeout=REQUEST_TIMEOUT_HORIZONS,
    )

    response.raise_for_status()

    return _parse_horizons_vector_batch(
        response.text,
        name_by_command,
    )


# ---------------------------------------------------------------------------
# MIRIADE
# ---------------------------------------------------------------------------


def _miriade_position(
    body: Dict[str, Any],
    dt: datetime,
) -> Optional[Dict[str, float]]:
    """Resolve one position through IMCCE Miriade."""

    miriade_designations = {
        "Chiron": "2060",
        "Pholus": "5145",
        "Nessus": "7066",
        "Chariklo": "10199",
        "Hylonome": "10370",
        "Asbolus": "8405",
        "Orcus": "90482",
        "Sedna": "90377",
        "Quaoar": "50000",
        "Ixion": "28978",
        "Varuna": "20000",
        "Huya": "38628",
        "Salacia": "120347",
    }

    body_name = body["name"]

    if body_name in ASTEROID_MIRIADE_IDS:
        query_id = ASTEROID_MIRIADE_IDS[
            body_name
        ]
    else:
        query_id = miriade_designations.get(
            body_name,
            body_name,
        )

    params = {
        "name": query_id,
        "epoch": _utc_iso(dt),
        "observer": "500",
        "eph": "1",
        "-theory": "DE431",
        "-teph": "1",
        "-tcoor": "1",
        "-rplane": "2",
        "-nbd": "1",
        "-mime": "json",
    }

    response = requests.get(
        MIRIADE_BASE,
        params=params,
        timeout=REQUEST_TIMEOUT_MIRIADE,
    )

    try:
        response.raise_for_status()

    except requests.HTTPError:
        if response.status_code == 400:
            print(
                f"[WARN] "
                f"miriade failed for "
                f"{body_name}"
            )
            return None

        raise

    data = (
        response.json()
        .get(
            "result",
            {},
        )
    )

    if isinstance(data, str):
        data = json.loads(data)

    if not isinstance(data, dict):
        return None

    rows = data.get(
        "data",
        [],
    )

    if not rows:
        return None

    if not isinstance(
        rows[0],
        dict,
    ):
        return None

    row = {
        str(k).lower(): v
        for k, v
        in rows[0].items()
    }

    # Do NOT use:
    #
    # row.get("elon") or row.get("ecllon")
    #
    # because 0.0 is a valid astronomical longitude.
    lon = row.get("elon")

    if lon is None:
        lon = row.get("ecllon")

    lat = row.get("elat")

    if lat is None:
        lat = row.get("ecllat")

    if (
        lon is None
        or lat is None
        or not _is_valid_number(lon)
        or not _is_valid_number(lat)
    ):
        ra = row.get("ra")
        dec = row.get("dec")

        if (
            not _is_valid_number(ra)
            or not _is_valid_number(dec)
        ):
            return None

        lon, lat = ra_dec_to_ecl(
            float(ra),
            float(dec),
            _utc_iso(dt),
        )

    if (
        not _is_valid_number(lon)
        or not _is_valid_number(lat)
    ):
        return None

    raw_distance = row.get("delta")

    if raw_distance is None:
        raw_distance = row.get("dist")

    distance = (
        float(raw_distance)
        if _is_valid_number(raw_distance)
        else 0.0
    )

    raw_velocity = row.get("deldot")

    if raw_velocity is None:
        raw_velocity = row.get("vel")

    velocity = (
        float(raw_velocity)
        if _is_valid_number(raw_velocity)
        else 0.0
    )

    timestamp = (
        row.get("epoch")
        or row.get("date")
        or row.get("datetime")
        or _utc_iso(dt)
    )

    return {
        "longitude": float(lon) % 360.0,
        "latitude": float(lat),
        "distance": distance,
        "velocity": velocity,
        "timestamp": str(timestamp),
    }


# ---------------------------------------------------------------------------
# SWISS EPHEMERIS
# ---------------------------------------------------------------------------


def _swiss_position(
    body: Dict[str, Any],
    dt: datetime,
) -> Optional[Dict[str, float]]:
    """Resolve one locally supported position through Swiss Ephemeris."""

    code = body.get("swiss_code")

    if code is None:
        code = SWISS_CODES.get(
            body["name"].lower()
        )

    if code is None:
        return None

    result, _ = swe.calc_ut(
        _to_jd(dt),
        int(code),
        swe.FLG_SPEED,
    )

    lon = result[0]
    lat = result[1]
    distance = result[2]
    lon_speed = result[3]

    if (
        not _is_valid_number(lon)
        or not _is_valid_number(lat)
    ):
        return None

    return {
        "longitude": float(lon) % 360.0,
        "latitude": float(lat),
        "distance": (
            float(distance)
            if _is_valid_number(distance)
            else 0.0
        ),
        "velocity": (
            float(lon_speed)
            if _is_valid_number(lon_speed)
            else 0.0
        ),
    }


# ---------------------------------------------------------------------------
# PROVIDER CAPABILITY
# ---------------------------------------------------------------------------


def _has_valid_horizons_mapping(
    body: Dict[str, Any],
) -> bool:
    value = body.get("horizons_id")

    if value is not None and str(value).strip():
        return True

    # Core major bodies may still be queryable by their canonical name.
    category = str(
        body.get("category")
        or body.get("_catalog_category")
        or ""
    ).lower()

    return (
        category == "core_bodies"
        and bool(
            str(
                body.get("name")
                or ""
            ).strip()
        )
    )


def _has_valid_miriade_mapping(
    body: Dict[str, Any],
) -> bool:
    if body.get("miriade_name"):
        return True

    return bool(
        str(
            body.get("name")
            or ""
        ).strip()
    )


def _has_valid_swiss_mapping(
    body: Dict[str, Any],
) -> bool:
    if body.get("swiss_code") is not None:
        return True

    name = str(
        body.get("name")
        or ""
    ).lower()

    return name in SWISS_CODES


# ---------------------------------------------------------------------------
# PROVIDER ROUTING
# ---------------------------------------------------------------------------


def _normalize_provider_priority(
    body: Dict[str, Any],
    category: str,
) -> List[str]:
    """Return the mandatory provider chain for the daily feed.

    Moving-body priority is ALWAYS:

        JPL Horizons
        -> Miriade
        -> Swiss Ephemeris

    A provider is included only when the body has usable capability
    for that provider.

    Fixed stars and Aether calculations are separate layers.
    """

    if category == "fixed_stars":
        return [
            "fixed_star_catalog"
        ]

    if category == "aether_points":
        return [
            "calculated"
        ]

    chain: List[str] = []

    if _has_valid_horizons_mapping(body):
        chain.append("horizons")

    if _has_valid_miriade_mapping(body):
        chain.append("miriade")

    if _has_valid_swiss_mapping(body):
        chain.append("swiss")

    return chain


# ---------------------------------------------------------------------------
# SINGLE PROVIDER EXECUTION
# ---------------------------------------------------------------------------


def _compute_single(
    provider: str,
    body: Dict[str, Any],
    dt: datetime,
) -> Dict[str, Any]:
    loader_map: Dict[
        str,
        Callable[
            [
                Dict[str, Any],
                datetime,
            ],
            Optional[Dict[str, float]],
        ],
    ] = {
        "horizons": _horizons_position,
        "miriade": _miriade_position,
        "swiss": _swiss_position,
    }

    loader = loader_map[
        provider
    ]

    name = body["name"]

    category = (
        body.get("category")
        or body.get(
            "_catalog_category",
            "unknown",
        )
    )

    try:
        data = loader(
            body,
            dt,
        )

        if (
            data
            and _is_valid_number(
                data.get("longitude")
            )
            and _is_valid_number(
                data.get("latitude")
            )
        ):
            return {
                name: {
                    **data,
                    "source": provider,
                    "category": category,
                    "timestamp": str(
                        data.get("timestamp")
                        or _utc_iso(dt)
                    ),
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
                "errors": [
                    f"{provider}: unresolved"
                ],
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
                "errors": [
                    f"{provider}: {exc}"
                ],
            }
        }


# ---------------------------------------------------------------------------
# PROVIDER GROUP SUPPORT
# ---------------------------------------------------------------------------


def _fetch_group(
    provider: str,
    bodies: List[Dict[str, Any]],
    dt: datetime,
) -> Dict[str, Dict[str, Any]]:
    if not bodies:
        return {}

    results: Dict[
        str,
        Dict[str, Any],
    ] = {}

    max_workers = min(
        8,
        len(bodies),
    )

    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:

        futures = [
            executor.submit(
                _compute_single,
                provider,
                body,
                dt,
            )
            for body in bodies
        ]

        for future in as_completed(
            futures
        ):
            results.update(
                future.result()
            )

    return results


# ---------------------------------------------------------------------------
# AETHER CALCULATIONS
# ---------------------------------------------------------------------------


def _compute_aether_points(
    positions: Dict[
        str,
        Dict[str, Any],
    ],
    aether_bodies: List[
        Dict[str, Any]
    ],
    dt: datetime,
) -> Dict[
    str,
    Dict[str, Any],
]:
    def lon(
        name: str,
    ) -> Optional[float]:
        entry = positions.get(
            name
        )

        if not entry:
            return None

        value = entry.get(
            "longitude"
        )

        if not _is_valid_number(value):
            return None

        return float(value)

    sun = lon("Sun")
    moon = lon("Moon")
    mars = lon("Mars")
    jupiter = lon("Jupiter")
    saturn = lon("Saturn")
    venus = lon("Venus")

    def midpoint(
        a: Optional[float],
        b: Optional[float],
    ) -> Optional[float]:
        if (
            not _is_valid_number(a)
            or not _is_valid_number(b)
        ):
            return None

        return (
            float(a)
            + float(b)
        ) % 360.0

    formulas = {
        "Aetheric_SunMoon_Midpoint":
            midpoint(
                sun,
                moon,
            ),

        "Aetheric_Jovian_Arc":
            (
                None
                if (
                    jupiter is None
                    or saturn is None
                )
                else (
                    (
                        jupiter
                        - saturn
                    )
                    + 360.0
                )
                % 360.0
            ),

        "Aetheric_Elemental_Balance":
            (
                None
                if (
                    mars is None
                    or venus is None
                    or moon is None
                )
                else (
                    (
                        mars
                        + venus
                        + moon
                    )
                    / 3.0
                )
                % 360.0
            ),
    }

    computed: Dict[
        str,
        Dict[str, Any],
    ] = {}

    for body in aether_bodies:
        name = body["name"]

        category = body.get(
            "category",
            "aether_points",
        )

        value = formulas.get(
            name
        )

        computed[name] = {
            "longitude": value,
            "latitude": (
                0.0
                if value is not None
                else None
            ),
            "distance": (
                0.0
                if value is not None
                else None
            ),
            "velocity": 0.0,
            "timestamp": _utc_iso(dt),
            "source": "calculated",
            "category": category,
        }

    return computed


# ---------------------------------------------------------------------------
# BODY FALLBACK RESOLUTION
# ---------------------------------------------------------------------------


def _resolve_body(
    body: Dict[str, Any],
    dt: datetime,
) -> Dict[str, Any]:
    """Resolve one moving body through the fixed provider chain.

    JPL first.
    Miriade only if JPL did not resolve.
    Swiss only if both upstream providers did not resolve.
    """

    name = body["name"]

    category = (
        body.get("category")
        or body.get(
            "_catalog_category",
            "unknown",
        )
    )

    errors: List[str] = []

    provider_chain = body.get(
        "_provider_chain",
        [],
    )

    if not provider_chain:
        return {
            name: {
                "longitude": None,
                "latitude": None,
                "distance": None,
                "velocity": None,
                "source": "unresolved",
                "category": category,
                "timestamp": _utc_iso(dt),
                "errors": [
                    "no valid provider configured"
                ],
            }
        }

    for provider in provider_chain:
        result = _compute_single(
            provider,
            body,
            dt,
        )[name]

        lon_value = result.get(
            "longitude"
        )

        lat_value = result.get(
            "latitude"
        )

        if (
            result.get("source")
            != "unresolved"
            and _is_valid_number(
                lon_value
            )
            and _is_valid_number(
                lat_value
            )
        ):
            if errors:
                result["errors"] = errors

            return {
                name: result
            }

        errors.extend(
            result.get(
                "errors",
                [
                    f"{provider}: unresolved"
                ],
            )
        )

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


# ---------------------------------------------------------------------------
# FULL DAILY POSITION RESOLUTION
# ---------------------------------------------------------------------------


def fetch_all_positions(
    dt: datetime,
    catalog: Optional[
        Dict[str, Any]
    ] = None,
) -> Dict[str, Any]:
    """Resolve the full catalog for one daily transit timestamp."""

    catalog_data = (
        catalog
        or load_catalog()
    )

    categories = catalog_data.get(
        "categories",
        {},
    )

    all_bodies: List[
        Dict[str, Any]
    ] = []

    fixed_star_names: set[
        str
    ] = set()

    aether_bodies: List[
        Dict[str, Any]
    ] = []

    for category, objects in categories.items():
        for body in objects:
            enriched = dict(
                body
            )

            enriched.setdefault(
                "category",
                category,
            )

            enriched[
                "_catalog_category"
            ] = category

            enriched[
                "_provider_chain"
            ] = (
                _normalize_provider_priority(
                    enriched,
                    category,
                )
            )

            # Store the normalized Horizons ID once.
            enriched[
                "_normalized_horizons_id"
            ] = (
                _normalize_horizons_id(
                    enriched
                )
            )

            if category == "fixed_stars":
                fixed_star_names.add(
                    enriched["name"]
                )
                continue

            if category == "aether_points":
                aether_bodies.append(
                    enriched
                )
                continue

            all_bodies.append(
                enriched
            )

    positions: Dict[
        str,
        Dict[str, Any],
    ] = {}

    for body in all_bodies:
        resolved = _resolve_body(
            body,
            dt,
        )

        for name, candidate in resolved.items():
            existing = positions.get(
                name
            )

            if existing is None:
                positions[name] = candidate
                continue

            existing_ok = (
                _is_valid_number(
                    existing.get(
                        "longitude"
                    )
                )
                and _is_valid_number(
                    existing.get(
                        "latitude"
                    )
                )
            )

            candidate_ok = (
                _is_valid_number(
                    candidate.get(
                        "longitude"
                    )
                )
                and _is_valid_number(
                    candidate.get(
                        "latitude"
                    )
                )
            )

            if (
                candidate_ok
                and not existing_ok
            ):
                positions[name] = candidate

    # -------------------------------------------------------------------
    # FIXED STARS
    # -------------------------------------------------------------------

    stars_path = (
        ALT_FIXED_STARS_PATH
        if ALT_FIXED_STARS_PATH.exists()
        else FIXED_STARS_PATH
    )

    if (
        stars_path.exists()
        and fixed_star_names
    ):
        with stars_path.open(
            "r",
            encoding="utf-8",
        ) as f:
            stars = (
                json.load(f)
                .get(
                    "stars",
                    [],
                )
            )

        for star in stars:
            star_id = star.get(
                "id"
            )

            if (
                star_id
                not in fixed_star_names
            ):
                continue

            try:
                ra = star[
                    "ra_deg"
                ]

                dec = star[
                    "dec_deg"
                ]

                if (
                    not _is_valid_number(ra)
                    or not _is_valid_number(dec)
                ):
                    continue

                star_lon, star_lat = (
                    ra_dec_to_ecl(
                        float(ra),
                        float(dec),
                        _utc_iso(dt),
                    )
                )

            except Exception:
                continue

            if (
                not _is_valid_number(
                    star_lon
                )
                or not _is_valid_number(
                    star_lat
                )
            ):
                continue

            positions[
                star_id
            ] = {
                "longitude":
                    float(star_lon)
                    % 360.0,

                "latitude":
                    float(star_lat),

                "distance":
                    0.0,

                "velocity":
                    0.0,

                "timestamp":
                    _utc_iso(dt),

                "source":
                    "fixed_star_catalog",

                "category":
                    "fixed_stars",
            }

    # -------------------------------------------------------------------
    # AETHER POINTS
    # -------------------------------------------------------------------

    positions.update(
        _compute_aether_points(
            positions,
            aether_bodies,
            dt,
        )
    )

    return positions


# ---------------------------------------------------------------------------
# DIRECT EXECUTION
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    now = datetime.now(
        timezone.utc
    )

    print(
        json.dumps(
            fetch_all_positions(
                now
            ),
            indent=2,
        )
    )
