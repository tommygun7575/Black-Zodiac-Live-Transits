#!/usr/bin/env python3
"""Validate shared celestial catalog config used by daily and 6-month feeds.

Fails CI before tests/generate if the catalog drifts from mission constraints:
- Exactly three verified Aether formulas (no Vulcan/Hades expansions)
- Lunar nodes present (True/Mean/South)
- Fixed stars cover the verified catalog (>= 19)
- Provider priorities stay within the allowed set
- Daily and 6-month loaders agree on catalog path and population counts
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "config" / "celestial_catalog.json"

ALLOWED_PROVIDERS = {
    "horizons",
    "miriade",
    "swiss",
    "fixed_star_catalog",
    "calculated",
}

REQUIRED_AETHER = (
    "Aetheric_SunMoon_Midpoint",
    "Aetheric_Jovian_Arc",
    "Aetheric_Elemental_Balance",
)

REQUIRED_NODES = ("True_Node", "Mean_Node", "South_Node")


def _load_catalog(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _category_names(categories: Dict[str, Any], key: str) -> List[str]:
    entries = categories.get(key) or []
    if not isinstance(entries, list):
        raise ValueError(f"categories.{key} must be a list")
    names: List[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or "name" not in entry:
            raise ValueError(f"categories.{key} entries must be objects with name")
        names.append(str(entry["name"]))
    return names


def validate_catalog(path: Path = CATALOG_PATH) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Catalog missing: {path}")

    payload = _load_catalog(path)
    categories = payload.get("categories")
    if not isinstance(categories, dict):
        raise ValueError("celestial_catalog.json missing categories object")

    aether = _category_names(categories, "aether_points")
    if tuple(aether) != REQUIRED_AETHER:
        raise ValueError(
            "aether_points must be exactly the three verified formulas in order: "
            + ", ".join(REQUIRED_AETHER)
            + f"; got {aether}"
        )

    nodes = set(_category_names(categories, "lunar_nodes"))
    missing_nodes = [n for n in REQUIRED_NODES if n not in nodes]
    if missing_nodes:
        raise ValueError(f"lunar_nodes missing required entries: {missing_nodes}")

    fixed = _category_names(categories, "fixed_stars")
    if len(fixed) < 19:
        raise ValueError(f"fixed_stars must include >= 19 verified stars; got {len(fixed)}")

    moving_keys = (
        "core_bodies",
        "lunar_nodes",
        "dwarf_planets",
        "major_asteroids",
        "expanded_asteroids",
        "centaurs",
        "trans_neptunian_objects",
    )
    moving_names: Set[str] = set()
    for key in moving_keys:
        for name in _category_names(categories, key):
            if name in moving_names and name != "South_Node":
                # South_Node may be calculated; True/Mean are provider bodies.
                pass
            moving_names.add(name)

    # South_Node is calculated from True_Node; catalog may list it under lunar_nodes.
    for key, entries in categories.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            priority = entry.get("provider_priority") or []
            if not isinstance(priority, list):
                raise ValueError(
                    f"{entry.get('name')}: provider_priority must be a list"
                )
            unknown = sorted(set(priority) - ALLOWED_PROVIDERS)
            if unknown:
                raise ValueError(
                    f"{entry.get('name')}: unknown providers {unknown}; "
                    f"allowed={sorted(ALLOWED_PROVIDERS)}"
                )

    return {
        "path": str(path.relative_to(ROOT)),
        "aether_count": len(aether),
        "aether": aether,
        "fixed_star_count": len(fixed),
        "lunar_nodes": sorted(nodes),
        "moving_name_count": len(moving_names),
    }


def validate_daily_6mo_parity() -> Dict[str, Any]:
    """Ensure daily and 6-month generators share the same catalog path + counts."""
    sys.path.insert(0, str(ROOT))
    from scripts import generate_feed_6month as six
    from scripts import generate_transits as daily
    from scripts.fetch_ephemeris import CATALOG_PATH as fetch_catalog
    from scripts.fetch_ephemeris import load_catalog

    if six.CATALOG_PATH.resolve() != fetch_catalog.resolve():
        raise ValueError(
            f"Catalog path mismatch: 6mo={six.CATALOG_PATH} fetch={fetch_catalog}"
        )

    moving, fixed, aether = six.load_catalog_targets(six.CATALOG_PATH)
    catalog = load_catalog(fetch_catalog)
    daily_sets = daily._catalog_target_sets(catalog)

    six_moving = {b["name"] for b in moving}
    # Daily treats South_Node as moving/catalog target; 6mo may calculate it.
    daily_moving = set(daily_sets["moving"])
    # Parity on shared provider-backed moving bodies (exclude calculated South_Node).
    shared_expected = six_moving | {"South_Node"}
    if not six_moving.issubset(daily_moving | {"South_Node"}):
        raise ValueError(
            "Daily/6mo moving-body mismatch: "
            f"only_in_6mo={sorted(six_moving - daily_moving)}"
        )
    if not set(fixed).issubset(set(daily_sets["fixed"])):
        raise ValueError(
            "Daily/6mo fixed-star mismatch: "
            f"only_in_6mo={sorted(set(fixed) - set(daily_sets['fixed']))}"
        )
    if set(aether) != set(daily_sets["aether"]):
        raise ValueError(
            f"Daily/6mo aether mismatch: 6mo={sorted(aether)} "
            f"daily={sorted(daily_sets['aether'])}"
        )
    if set(aether) != set(REQUIRED_AETHER):
        raise ValueError(f"Aether set drifted from verified formulas: {sorted(aether)}")

    return {
        "catalog": str(fetch_catalog.relative_to(ROOT)),
        "six_moving": len(six_moving),
        "daily_moving": len(daily_moving),
        "fixed_stars": len(fixed),
        "aether": list(REQUIRED_AETHER),
        "shared_expected_includes_south_node": "South_Node" in shared_expected,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate celestial catalog config")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=CATALOG_PATH,
        help="Path to celestial_catalog.json",
    )
    parser.add_argument(
        "--skip-parity",
        action="store_true",
        help="Skip daily/6mo loader parity checks",
    )
    args = parser.parse_args()

    summary = validate_catalog(args.catalog)
    print("[OK] Catalog validation passed:")
    for key, value in summary.items():
        print(f"     {key}={value}")

    if not args.skip_parity:
        parity = validate_daily_6mo_parity()
        print("[OK] Daily/6mo shared-config parity:")
        for key, value in parity.items():
            print(f"     {key}={value}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — CI wants a clear non-zero exit
        print(f"[FAIL] Config validation: {exc}", file=sys.stderr)
        sys.exit(1)
