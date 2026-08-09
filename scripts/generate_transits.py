#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set
from zoneinfo import ZoneInfo

from scripts.calculate_aspects import (
    fixed_star_conjunctions,
    harmonic_aspects,
)

from scripts.fetch_ephemeris import (
    fetch_all_positions,
    load_catalog,
)


# ---------------------------------------------------------------------------
# PATHS / CONSTANTS
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]

OUTPUT_DIR = ROOT / "docs"

PACIFIC_ZONE = ZoneInfo(
    "America/Los_Angeles"
)

ENGINE_VERSION = (
    "ZodiacOracle.DailyTransit.v2"
)

SOURCE_ORDER = [
    "horizons",
    "miriade",
    "swiss",
    "fixed_star_catalog",
    "calculated",
]


# ---------------------------------------------------------------------------
# BASIC HELPERS
# ---------------------------------------------------------------------------


def _is_valid_number(
    value: Any,
) -> bool:
    """Return True only for finite numeric values."""

    if value is None:
        return False

    try:
        number = float(value)

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return False

    return math.isfinite(number)


def _position_is_resolved(
    position: Dict[str, Any],
) -> bool:
    """A position counts as resolved only with valid lon/lat values."""

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

    return (
        _is_valid_number(
            position.get(
                "longitude"
            )
        )
        and
        _is_valid_number(
            position.get(
                "latitude"
            )
        )
    )


def _sanitize_nans(
    value: Any,
) -> Any:
    """Convert non-finite numeric values to JSON-safe nulls."""

    if isinstance(
        value,
        dict,
    ):
        return {
            key: _sanitize_nans(item)
            for key, item
            in value.items()
        }

    if isinstance(
        value,
        list,
    ):
        return [
            _sanitize_nans(item)
            for item in value
        ]

    if isinstance(
        value,
        tuple,
    ):
        return [
            _sanitize_nans(item)
            for item in value
        ]

    if isinstance(
        value,
        float,
    ):
        if not math.isfinite(
            value
        ):
            return None

    return value


def _utc_iso(
    dt: datetime,
) -> str:
    """Return canonical UTC ISO timestamp."""

    return (
        dt.astimezone(
            timezone.utc
        )
        .isoformat()
    )


def _pacific_iso(
    dt: datetime,
) -> str:
    """Return canonical Pacific timestamp."""

    return (
        dt.astimezone(
            PACIFIC_ZONE
        )
        .isoformat()
    )


def _write_json(
    path: Path,
    payload: Dict[str, Any],
) -> None:
    """Write deterministic, readable JSON."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            payload,
            f,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )

        f.write("\n")


# ---------------------------------------------------------------------------
# DATE HANDLING
# ---------------------------------------------------------------------------


def resolve_transit_datetime(
    requested_date: str | None,
) -> datetime:
    """Resolve the timestamp used for the daily feed.

    Normal scheduled/manual execution:
        use the actual current UTC timestamp.

    Explicit --date execution:
        use UTC midnight for the requested YYYY-MM-DD date.
    """

    if requested_date:
        parsed = datetime.strptime(
            requested_date,
            "%Y-%m-%d",
        )

        return parsed.replace(
            tzinfo=timezone.utc
        )

    return datetime.now(
        timezone.utc
    )


# ---------------------------------------------------------------------------
# CATALOG AUDIT
# ---------------------------------------------------------------------------


def _catalog_target_sets(
    catalog: Dict[str, Any],
) -> Dict[str, Set[str]]:
    """Return expected object names grouped by catalog layer."""

    categories = catalog.get(
        "categories",
        {},
    )

    moving: Set[str] = set()
    fixed: Set[str] = set()
    aether: Set[str] = set()

    for category, objects in categories.items():
        if not isinstance(
            objects,
            list,
        ):
            continue

        for body in objects:
            if not isinstance(
                body,
                dict,
            ):
                continue

            name = str(
                body.get("name")
                or ""
            ).strip()

            if not name:
                continue

            if category == "fixed_stars":
                fixed.add(
                    name
                )

            elif category == "aether_points":
                aether.add(
                    name
                )

            else:
                moving.add(
                    name
                )

    return {
        "moving": moving,
        "fixed": fixed,
        "aether": aether,
    }


def _build_coverage_report(
    transit_positions: Dict[
        str,
        Dict[str, Any],
    ],
    catalog: Dict[str, Any],
) -> Dict[str, Any]:
    """Audit actual daily output against the configured catalog."""

    target_sets = _catalog_target_sets(
        catalog
    )

    moving = target_sets[
        "moving"
    ]

    fixed = target_sets[
        "fixed"
    ]

    aether = target_sets[
        "aether"
    ]

    expected = (
        moving
        | fixed
        | aether
    )

    resolved_names: Set[str] = set()

    unresolved_names: List[str] = []

    missing_names: List[str] = []

    for name in sorted(
        expected
    ):
        position = transit_positions.get(
            name
        )

        if position is None:
            missing_names.append(
                name
            )
            continue

        if _position_is_resolved(
            position
        ):
            resolved_names.add(
                name
            )

        else:
            unresolved_names.append(
                name
            )

    total_targets = len(
        expected
    )

    resolved_count = len(
        resolved_names
    )

    coverage = (
        resolved_count
        / total_targets
        if total_targets
        else 1.0
    )

    moving_resolved = sum(
        1
        for name in moving
        if _position_is_resolved(
            transit_positions.get(
                name,
                {},
            )
        )
    )

    fixed_resolved = sum(
        1
        for name in fixed
        if _position_is_resolved(
            transit_positions.get(
                name,
                {},
            )
        )
    )

    aether_resolved = sum(
        1
        for name in aether
        if _position_is_resolved(
            transit_positions.get(
                name,
                {},
            )
        )
    )

    return {
        "coverage":
            round(
                coverage,
                6,
            ),

        "resolved_targets":
            resolved_count,

        "total_targets":
            total_targets,

        "missing":
            missing_names,

        "unresolved":
            unresolved_names,

        "moving_body_count":
            len(
                moving
            ),

        "moving_body_resolved":
            moving_resolved,

        "fixed_star_count":
            len(
                fixed
            ),

        "fixed_star_resolved":
            fixed_resolved,

        "aether_point_count":
            len(
                aether
            ),

        "aether_point_resolved":
            aether_resolved,
    }


# ---------------------------------------------------------------------------
# PROVIDER AUDIT
# ---------------------------------------------------------------------------


def _build_provider_report(
    transit_positions: Dict[
        str,
        Dict[str, Any],
    ],
) -> Dict[str, Any]:
    """Count which provider actually resolved each object."""

    source_counts: Counter = Counter()

    for position in transit_positions.values():
        if not isinstance(
            position,
            dict,
        ):
            continue

        source = str(
            position.get(
                "source"
            )
            or "unknown"
        )

        source_counts[
            source
        ] += 1

    return {
        "source_order":
            list(
                SOURCE_ORDER
            ),

        "source_counts":
            dict(
                sorted(
                    source_counts.items()
                )
            ),
    }


# ---------------------------------------------------------------------------
# ERROR AUDIT
# ---------------------------------------------------------------------------


def _build_error_report(
    transit_positions: Dict[
        str,
        Dict[str, Any],
    ],
) -> Dict[str, Any]:
    """Collect fallback and unresolved provider errors."""

    body_errors: Dict[
        str,
        List[str],
    ] = {}

    for name, position in transit_positions.items():
        if not isinstance(
            position,
            dict,
        ):
            continue

        errors = position.get(
            "errors"
        )

        if not errors:
            continue

        if isinstance(
            errors,
            list,
        ):
            body_errors[
                name
            ] = [
                str(error)
                for error in errors
            ]

        else:
            body_errors[
                name
            ] = [
                str(errors)
            ]

    return {
        "bodies_with_provider_errors":
            len(
                body_errors
            ),

        "provider_errors":
            body_errors,
    }


# ---------------------------------------------------------------------------
# MAIN GENERATOR
# ---------------------------------------------------------------------------


def main() -> Path:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the Zodiac Oracle "
            "daily transit overlay"
        )
    )

    parser.add_argument(
        "--date",
        help=(
            "UTC date in YYYY-MM-DD. "
            "If omitted, use the actual "
            "current UTC timestamp."
        ),
    )

    args = parser.parse_args()

    transit_dt_utc = (
        resolve_transit_datetime(
            args.date
        )
    )

    pacific_now = (
        transit_dt_utc.astimezone(
            PACIFIC_ZONE
        )
    )

    print(
        "[INFO] "
        f"Daily transit timestamp UTC: "
        f"{_utc_iso(transit_dt_utc)}"
    )

    print(
        "[INFO] "
        f"Daily transit timestamp Pacific: "
        f"{_pacific_iso(transit_dt_utc)}"
    )

    # -------------------------------------------------------------------
    # LOAD CATALOG
    # -------------------------------------------------------------------

    catalog = load_catalog()

    target_sets = (
        _catalog_target_sets(
            catalog
        )
    )

    print(
        "[INFO] "
        f"Catalog moving bodies: "
        f"{len(target_sets['moving'])}"
    )

    print(
        "[INFO] "
        f"Catalog fixed stars: "
        f"{len(target_sets['fixed'])}"
    )

    print(
        "[INFO] "
        f"Catalog Aether points: "
        f"{len(target_sets['aether'])}"
    )

    # -------------------------------------------------------------------
    # RESOLVE CELESTIAL POSITIONS
    # -------------------------------------------------------------------

    transit_positions = (
        fetch_all_positions(
            transit_dt_utc,
            catalog=catalog,
        )
    )

    # -------------------------------------------------------------------
    # COVERAGE / PROVIDER / ERROR REPORTS
    # -------------------------------------------------------------------

    coverage_report = (
        _build_coverage_report(
            transit_positions,
            catalog,
        )
    )

    provider_report = (
        _build_provider_report(
            transit_positions
        )
    )

    error_report = (
        _build_error_report(
            transit_positions
        )
    )

    # -------------------------------------------------------------------
    # DERIVED LAYERS
    # -------------------------------------------------------------------

    calculated_harmonics = (
        harmonic_aspects(
            transit_positions
        )
    )

    aether_points = {
        name: data
        for name, data
        in transit_positions.items()
        if data.get(
            "category"
        ) == "aether_points"
    }

    fixed_star_positions = {
        name: data
        for name, data
        in transit_positions.items()
        if data.get(
            "category"
        ) == "fixed_stars"
    }

    calculated_fixed_star_conjunctions = (
        fixed_star_conjunctions(
            transit_positions
        )
    )

    # -------------------------------------------------------------------
    # OUTPUT
    # -------------------------------------------------------------------

    output = {
        "engine_version":
            ENGINE_VERSION,

        "generated_at_utc":
            _utc_iso(
                transit_dt_utc
            ),

        "generated_at_pacific":
            _pacific_iso(
                transit_dt_utc
            ),

        "type":
            "daily overlay",

        "coverage":
            coverage_report[
                "coverage"
            ],

        "resolved_targets":
            coverage_report[
                "resolved_targets"
            ],

        "total_targets":
            coverage_report[
                "total_targets"
            ],

        "missing":
            coverage_report[
                "missing"
            ],

        "unresolved":
            coverage_report[
                "unresolved"
            ],

        "population": {
            "moving_body_count":
                coverage_report[
                    "moving_body_count"
                ],

            "moving_body_resolved":
                coverage_report[
                    "moving_body_resolved"
                ],

            "fixed_star_count":
                coverage_report[
                    "fixed_star_count"
                ],

            "fixed_star_resolved":
                coverage_report[
                    "fixed_star_resolved"
                ],

            "aether_point_count":
                coverage_report[
                    "aether_point_count"
                ],

            "aether_point_resolved":
                coverage_report[
                    "aether_point_resolved"
                ],
        },

        "provider_runtime": {
            **provider_report,
            **error_report,
        },

        "transit_positions":
            transit_positions,

        "calculated_harmonics":
            calculated_harmonics,

        "aether_points":
            aether_points,

        "fixed_star_positions":
            fixed_star_positions,

        "fixed_star_conjunctions":
            calculated_fixed_star_conjunctions,
    }

    output = _sanitize_nans(
        output
    )

    # -------------------------------------------------------------------
    # OUTPUT FILE NAME
    # -------------------------------------------------------------------

    if args.date:
        # Explicit historical/test date:
        # preserve the date the user requested.
        date_tag = (
            args.date.replace(
                "-",
                "_",
            )
        )

    else:
        # Normal production feed:
        # use current Pacific calendar date.
        date_tag = (
            pacific_now.strftime(
                "%Y_%m_%d"
            )
        )

    output_path = (
        OUTPUT_DIR
        / f"feed_overlay_{date_tag}.json"
    )

    _write_json(
        output_path,
        output,
    )

    # -------------------------------------------------------------------
    # WORKFLOW DIAGNOSTICS
    # -------------------------------------------------------------------

    print(
        "[OK] "
        f"Generated {output_path}"
    )

    print(
        "[INFO] "
        f"Coverage: "
        f"{coverage_report['resolved_targets']}"
        f"/"
        f"{coverage_report['total_targets']} "
        f"("
        f"{coverage_report['coverage'] * 100:.2f}%"
        f")"
    )

    print(
        "[INFO] "
        f"Moving bodies: "
        f"{coverage_report['moving_body_resolved']}"
        f"/"
        f"{coverage_report['moving_body_count']}"
    )

    print(
        "[INFO] "
        f"Fixed stars: "
        f"{coverage_report['fixed_star_resolved']}"
        f"/"
        f"{coverage_report['fixed_star_count']}"
    )

    print(
        "[INFO] "
        f"Aether points: "
        f"{coverage_report['aether_point_resolved']}"
        f"/"
        f"{coverage_report['aether_point_count']}"
    )

    print(
        "[INFO] "
        f"Provider counts: "
        f"{provider_report['source_counts']}"
    )

    if coverage_report[
        "missing"
    ]:
        print(
            "[WARN] "
            "Missing catalog targets: "
            + ", ".join(
                coverage_report[
                    "missing"
                ]
            )
        )

    if coverage_report[
        "unresolved"
    ]:
        print(
            "[WARN] "
            "Unresolved catalog targets: "
            + ", ".join(
                coverage_report[
                    "unresolved"
                ]
            )
        )

    # We intentionally DO NOT fabricate positions and we DO NOT make
    # the workflow fail merely because an upstream astronomy provider
    # temporarily fails. Missing/unresolved targets remain explicitly
    # visible in the generated JSON and workflow log.

    return output_path


if __name__ == "__main__":
    main()
