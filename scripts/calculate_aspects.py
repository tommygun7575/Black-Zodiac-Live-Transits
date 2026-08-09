from __future__ import annotations

import math
from datetime import datetime, timezone
from itertools import combinations
from typing import Any, Dict, List, Optional

import numpy as np
import swisseph as swe


# ---------------------------------------------------------------------------
# ASPECT CONFIGURATION
# ---------------------------------------------------------------------------

DEFAULT_HARMONIC_ORB_DEG = 1.5
DEFAULT_FIXED_STAR_ORB_DEG = 1.0


# Fundamental harmonic angles used by the existing Oracle transit feed.
#
# These preserve the behavior of the current repository:
#
# H2  = opposition    = 180°
# H3  = trine         = 120°
# H4  = square        = 90°
# H5  = quintile      = 72°
# H6  = sextile       = 60°
# H8  = semisquare    = 45°
# H9  = novile        = 40°
# H12 = semisextile   = 30°
#
# We intentionally preserve this set instead of silently changing the
# interpretation model.

HARMONIC_ANGLES: Dict[int, float] = {
    2: 180.0,
    3: 120.0,
    4: 90.0,
    5: 72.0,
    6: 60.0,
    8: 45.0,
    9: 40.0,
    12: 30.0,
}


FIXED_STAR_CATEGORIES = {
    "fixed_stars",
    "fixed stars",
}


# ---------------------------------------------------------------------------
# NUMERIC HELPERS
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

    return math.isfinite(
        number
    )


def _is_valid_longitude(
    value: Any,
) -> bool:
    """Validate a longitude-like numeric value.

    Longitudes are normalized elsewhere, so values outside 0..360 are
    still accepted here as long as they are finite numbers.
    """

    return _is_valid_number(
        value
    )


def _normalize_longitude(
    value: float,
) -> float:
    """Normalize longitude to the canonical 0 <= value < 360 range."""

    return float(value) % 360.0


def _norm_diff(
    a: float,
    b: float,
) -> float:
    """Return shortest angular separation from 0 to 180 degrees."""

    left = _normalize_longitude(
        a
    )

    right = _normalize_longitude(
        b
    )

    difference = abs(
        left - right
    ) % 360.0

    return min(
        difference,
        360.0 - difference,
    )


def _position_is_resolved(
    position: Any,
) -> bool:
    """Require a usable resolved longitude before aspect calculation."""

    if not isinstance(
        position,
        dict,
    ):
        return False

    if (
        position.get("source")
        == "unresolved"
    ):
        return False

    return _is_valid_longitude(
        position.get(
            "longitude"
        )
    )


def _category_name(
    position: Dict[str, Any],
) -> str:
    """Normalize category names used by older/newer feed formats."""

    return str(
        position.get(
            "category"
        )
        or ""
    ).strip().lower()


def _is_fixed_star(
    position: Dict[str, Any],
) -> bool:
    return (
        _category_name(
            position
        )
        in FIXED_STAR_CATEGORIES
    )


# ---------------------------------------------------------------------------
# HARMONIC ASPECTS
# ---------------------------------------------------------------------------


def harmonic_aspects(
    positions: Dict[
        str,
        Dict[str, Any],
    ],
    orb: float = DEFAULT_HARMONIC_ORB_DEG,
) -> List[
    Dict[str, Any]
]:
    """Calculate configured harmonic relationships.

    Preserves the repository's existing fundamental harmonic set while
    adding stricter validation and deterministic ordering.

    Fixed stars are excluded from harmonic body-to-body calculation.
    Aether/calculated points remain eligible, preserving existing behavior.
    """

    if (
        not _is_valid_number(
            orb
        )
        or float(orb) < 0.0
    ):
        raise ValueError(
            "harmonic aspect orb must be a finite non-negative number"
        )

    allowed_orb = float(
        orb
    )

    valid: Dict[
        str,
        Dict[str, Any],
    ] = {}

    for name, position in positions.items():

        if not _position_is_resolved(
            position
        ):
            continue

        if _is_fixed_star(
            position
        ):
            continue

        valid[
            name
        ] = position

    aspects: List[
        Dict[str, Any]
    ] = []

    # Sorting makes identical input produce identical output regardless
    # of dictionary insertion order.
    names = sorted(
        valid.keys()
    )

    for left, right in combinations(
        names,
        2,
    ):

        left_lon = float(
            valid[left][
                "longitude"
            ]
        )

        right_lon = float(
            valid[right][
                "longitude"
            ]
        )

        separation = _norm_diff(
            left_lon,
            right_lon,
        )

        for harmonic, exact_angle in HARMONIC_ANGLES.items():

            aspect_orb = abs(
                separation
                - exact_angle
            )

            if (
                aspect_orb
                <= allowed_orb
            ):

                aspects.append(
                    {
                        "body_a":
                            left,

                        "body_b":
                            right,

                        "harmonic":
                            harmonic,

                        "exact_angle":
                            exact_angle,

                        "separation":
                            separation,

                        "orb":
                            aspect_orb,
                    }
                )

    aspects.sort(
        key=lambda item: (
            float(
                item[
                    "orb"
                ]
            ),
            int(
                item[
                    "harmonic"
                ]
            ),
            str(
                item[
                    "body_a"
                ]
            ),
            str(
                item[
                    "body_b"
                ]
            ),
        )
    )

    return aspects


# ---------------------------------------------------------------------------
# ASCENDANT / ARABIC PART SUPPORT
# ---------------------------------------------------------------------------


def _ascendant_longitude(
    jd_ut: float,
    latitude: float,
    longitude: float,
) -> float:
    """Calculate tropical Ascendant through Swiss Ephemeris."""

    if not (
        _is_valid_number(
            jd_ut
        )
        and _is_valid_number(
            latitude
        )
        and _is_valid_number(
            longitude
        )
    ):
        raise ValueError(
            "invalid Ascendant calculation inputs"
        )

    cusps, ascmc = swe.houses(
        float(jd_ut),
        float(latitude),
        float(longitude),
    )

    # Swiss Ephemeris ascmc[0] is the Ascendant.
    #
    # The old repository implementation used cusps[0], which generally
    # corresponds to the first-house cusp and therefore usually agrees
    # with the Ascendant, but using ascmc[0] is explicit and correct.
    asc = float(
        ascmc[0]
    )

    return _normalize_longitude(
        asc
    )


def _parse_timestamp(
    timestamp: str,
) -> Optional[datetime]:
    """Parse modern ISO-8601 timestamps safely.

    Accepts:
        2026-08-09T19:02:06Z
        2026-08-09T19:02:06+00:00
        2026-08-09T12:02:06-07:00

    Naive timestamps are interpreted as UTC for backward compatibility.
    """

    if not timestamp:
        return None

    try:
        cleaned = str(
            timestamp
        ).strip()

        if cleaned.endswith(
            "Z"
        ):
            cleaned = (
                cleaned[:-1]
                + "+00:00"
            )

        dt = datetime.fromisoformat(
            cleaned
        )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None


def _datetime_to_jd(
    dt: datetime,
) -> float:
    """Convert timezone-aware datetime to UT Julian day."""

    dt_utc = dt.astimezone(
        timezone.utc
    )

    hour = (
        dt_utc.hour
        + dt_utc.minute / 60.0
        + dt_utc.second / 3600.0
        + dt_utc.microsecond
        / 3_600_000_000.0
    )

    return swe.julday(
        dt_utc.year,
        dt_utc.month,
        dt_utc.day,
        hour,
    )


def arabic_parts(
    positions: Dict[
        str,
        Dict[str, Any],
    ],
    timestamp: str,
    latitude: float,
    longitude: float,
) -> Dict[str, Any]:
    """Calculate the three legacy Arabic Parts supported by this module.

    This function preserves the formulas already used by this repository.
    It does not invent additional Parts or silently alter the configured
    Oracle methodology.
    """

    parts: Dict[str, Any] = {
        "Part_of_Fortune":
            None,

        "Part_of_Spirit":
            None,

        "Part_of_Eros":
            None,
    }

    if (
        not _is_valid_number(
            latitude
        )
        or not _is_valid_number(
            longitude
        )
    ):
        return parts

    sun = (
        positions
        .get(
            "Sun",
            {},
        )
        .get(
            "longitude"
        )
    )

    moon = (
        positions
        .get(
            "Moon",
            {},
        )
        .get(
            "longitude"
        )
    )

    venus = (
        positions
        .get(
            "Venus",
            {},
        )
        .get(
            "longitude"
        )
    )

    if (
        not _is_valid_longitude(
            sun
        )
        or not _is_valid_longitude(
            moon
        )
    ):
        return parts

    parsed_timestamp = (
        _parse_timestamp(
            timestamp
        )
    )

    if parsed_timestamp is None:
        return parts

    try:
        jd_ut = _datetime_to_jd(
            parsed_timestamp
        )

        asc = _ascendant_longitude(
            jd_ut,
            float(latitude),
            float(longitude),
        )

    except Exception:
        return parts

    sun_lon = _normalize_longitude(
        float(sun)
    )

    moon_lon = _normalize_longitude(
        float(moon)
    )

    parts[
        "Part_of_Fortune"
    ] = _normalize_longitude(
        asc
        + moon_lon
        - sun_lon
    )

    parts[
        "Part_of_Spirit"
    ] = _normalize_longitude(
        asc
        + sun_lon
        - moon_lon
    )

    if _is_valid_longitude(
        venus
    ):

        venus_lon = (
            _normalize_longitude(
                float(venus)
            )
        )

        parts[
            "Part_of_Eros"
        ] = _normalize_longitude(
            asc
            + moon_lon
            - venus_lon
        )

    return parts


# ---------------------------------------------------------------------------
# FIXED-STAR CONJUNCTIONS
# ---------------------------------------------------------------------------


def fixed_star_conjunctions(
    positions: Dict[
        str,
        Dict[str, Any],
    ],
    orb: float = DEFAULT_FIXED_STAR_ORB_DEG,
) -> List[
    Dict[str, Any]
]:
    """Calculate longitude conjunctions between bodies and fixed stars.

    The existing repository uses a 1-degree default fixed-star orb.
    That behavior is preserved here.

    Fixed stars are compared against all resolved non-fixed-star points,
    including Aether/calculated points, preserving the prior feed behavior.
    """

    if (
        not _is_valid_number(
            orb
        )
        or float(orb) < 0.0
    ):
        raise ValueError(
            "fixed-star orb must be a finite non-negative number"
        )

    allowed_orb = float(
        orb
    )

    stars: Dict[
        str,
        Dict[str, Any],
    ] = {}

    bodies: Dict[
        str,
        Dict[str, Any],
    ] = {}

    for name, position in positions.items():

        if not _position_is_resolved(
            position
        ):
            continue

        if _is_fixed_star(
            position
        ):
            stars[
                name
            ] = position

        else:
            bodies[
                name
            ] = position

    matches: List[
        Dict[str, Any]
    ] = []

    for body_name in sorted(
        bodies.keys()
    ):

        body = bodies[
            body_name
        ]

        body_lon = float(
            body[
                "longitude"
            ]
        )

        for star_name in sorted(
            stars.keys()
        ):

            star = stars[
                star_name
            ]

            star_lon = float(
                star[
                    "longitude"
                ]
            )

            delta = _norm_diff(
                body_lon,
                star_lon,
            )

            if delta <= allowed_orb:

                matches.append(
                    {
                        "body":
                            body_name,

                        # `star` matches the newer weekly feed schema.
                        "star":
                            star_name,

                        # Keep the older daily key too for compatibility
                        # with any existing downstream consumer.
                        "fixed_star":
                            star_name,

                        "orb":
                            delta,
                    }
                )

    matches.sort(
        key=lambda item: (
            float(
                item[
                    "orb"
                ]
            ),
            str(
                item[
                    "body"
                ]
            ),
            str(
                item[
                    "star"
                ]
            ),
        )
    )

    return matches
