#!/usr/bin/env python3
"""Validate overlay JSON against schemas/daily_overlay.schema.json (or alternate).

Lightweight validator: required keys, types, and nested required fields for
mission-critical sections (midpoints, harmonics, patterns, aether, declination
aspects, arabic parts, unresolved, provenance). Does not invent positions.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas" / "daily_overlay.schema.json"
VERIFIED_AETHER = (
    "Aetheric_SunMoon_Midpoint",
    "Aetheric_Jovian_Arc",
    "Aetheric_Elemental_Balance",
)


def _assert_type(value: Any, schema_type: str) -> bool:
    mapping = {
        "object": dict,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    expected = mapping[schema_type]
    # JSON numbers: bool is subclass of int in Python — reject bool for number/integer
    if schema_type in {"number", "integer"} and isinstance(value, bool):
        return False
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, expected)


def _type_ok(value: Any, allowed: Union[str, List[str], None]) -> bool:
    if allowed is None:
        return True
    if isinstance(allowed, list):
        return any(_assert_type(value, t) for t in allowed)
    return _assert_type(value, allowed)


def _validate_required(payload: Dict[str, Any], schema: Dict[str, Any], path: str = "$") -> None:
    for key in schema.get("required", []):
        if key not in payload:
            raise ValueError(f"Missing required key: {path}.{key}")


def _validate_object(payload: Dict[str, Any], schema: Dict[str, Any], path: str = "$") -> None:
    _validate_required(payload, schema, path=path)
    properties = schema.get("properties", {})
    for key, subschema in properties.items():
        if key not in payload:
            continue
        _validate_value(payload[key], subschema, path=f"{path}.{key}")

    if schema.get("additionalProperties") is False:
        extras = set(payload) - set(properties)
        if extras:
            raise ValueError(f"Unexpected keys at {path}: {sorted(extras)}")


def _validate_value(value: Any, schema: Dict[str, Any], path: str) -> None:
    allowed = schema.get("type")
    if not _type_ok(value, allowed):
        raise ValueError(f"Type mismatch for {path}: expected {allowed}, got {type(value).__name__}")

    if "const" in schema and value != schema["const"]:
        raise ValueError(f"Const mismatch for {path}: expected {schema['const']!r}")

    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"Enum mismatch for {path}: {value!r} not in {schema['enum']}")

    if isinstance(value, dict) and (schema.get("type") == "object" or "properties" in schema or "required" in schema):
        # Resolve local $ref shallowly for position defs
        if "$ref" in schema:
            return  # top-level refs handled via mission checks
        _validate_object(value, schema, path=path)

    if isinstance(value, list) and schema.get("type") == "array":
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                _validate_value(item, item_schema, path=f"{path}[{idx}]")
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise ValueError(f"{path} has fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ValueError(f"{path} has more than {schema['maxItems']} items")


def _mission_checks(payload: Dict[str, Any], schema_path: Path) -> None:
    """Extra constraints for the daily overlay mission."""
    if schema_path.name != "daily_overlay.schema.json":
        return

    unresolved = payload.get("unresolved")
    if not isinstance(unresolved, list):
        raise ValueError("unresolved must be an array of body names")
    for name in unresolved:
        if not isinstance(name, str):
            raise ValueError("unresolved entries must be strings")

    aether = payload.get("aether_points") or {}
    if set(aether.keys()) != set(VERIFIED_AETHER):
        raise ValueError(
            "aether_points must contain exactly the three verified formulas; "
            f"got {sorted(aether.keys())}"
        )

    provenance = payload.get("provenance") or {}
    formulas = provenance.get("aether_formulas")
    if formulas is not None:
        normalized = []
        for item in formulas:
            if not isinstance(item, str):
                raise ValueError("provenance.aether_formulas entries must be strings")
            normalized.append(item.split("=", 1)[0].strip())
        if normalized != list(VERIFIED_AETHER):
            raise ValueError(
                "provenance.aether_formulas must match verified set in order; "
                f"got {formulas}"
            )
    if provenance.get("no_fabricated_positions") is not True:
        raise ValueError("provenance.no_fabricated_positions must be true")

    houses = payload.get("houses_and_angles") or {}
    if houses.get("status") != "user_specific_downstream":
        raise ValueError("houses_and_angles.status must be user_specific_downstream")

    arabic = payload.get("arabic_parts") or {}
    if arabic.get("status") != "unavailable":
        raise ValueError("arabic_parts.status must be unavailable without observer location")

    for section, required_keys in (
        ("midpoints", ("body_a", "body_b", "longitude")),
        ("declination_aspects", ("body_a", "body_b", "type", "declination_a", "declination_b", "orb")),
        ("geometric_patterns", ("type", "bodies")),
        ("calculated_harmonics", ("body_a", "body_b", "harmonic", "exact_angle", "separation", "orb", "motion")),
    ):
        items = payload.get(section) or []
        if not isinstance(items, list):
            raise ValueError(f"{section} must be an array")
        for idx, item in enumerate(items[:5]):  # sample first entries
            if not isinstance(item, dict):
                raise ValueError(f"{section}[{idx}] must be an object")
            missing = [k for k in required_keys if k not in item]
            if missing:
                raise ValueError(f"{section}[{idx}] missing {missing}")


def validate_payload(
    payload: Dict[str, Any],
    schema_path: Path = DEFAULT_SCHEMA,
) -> None:
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object")
    _validate_object(payload, schema, path="$")
    _mission_checks(payload, schema_path)


def validate_file(json_file: Path, schema_path: Path = DEFAULT_SCHEMA) -> None:
    with json_file.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    validate_payload(payload, schema_path=schema_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate overlay output against JSON schema")
    parser.add_argument("json_file", help="Path to generated overlay file")
    parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="Schema path (default: daily_overlay.schema.json; use schemas/sixmonth_overlay.schema.json for 6mo)",
    )
    args = parser.parse_args()

    json_path = Path(args.json_file)
    schema_path = args.schema or DEFAULT_SCHEMA
    if not schema_path.is_absolute():
        schema_path = (ROOT / schema_path).resolve() if not schema_path.exists() else schema_path.resolve()

    try:
        validate_file(json_path, schema_path=schema_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Schema validation for {json_path}: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] Schema validation passed for {json_path} (schema={schema_path.name})")


if __name__ == "__main__":
    main()
