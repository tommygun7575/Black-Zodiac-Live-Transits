#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "daily_overlay.schema.json"


def _assert_type(value: Any, schema_type: str) -> bool:
    mapping = {
        "object": dict,
        "array": list,
        "string": str,
        "number": (int, float),
        "null": type(None),
    }
    expected = mapping[schema_type]
    return isinstance(value, expected)


def _validate_required(payload: Dict[str, Any], schema: Dict[str, Any]) -> None:
    for key in schema.get("required", []):
        if key not in payload:
            raise ValueError(f"Missing required key: {key}")


def _validate_top_level(payload: Dict[str, Any], schema: Dict[str, Any]) -> None:
    _validate_required(payload, schema)
    properties = schema.get("properties", {})
    for key, subschema in properties.items():
        if key not in payload:
            continue
        allowed = subschema.get("type")
        if isinstance(allowed, list):
            if not any(_assert_type(payload[key], t) for t in allowed):
                raise ValueError(f"Type mismatch for {key}: expected one of {allowed}")
        elif isinstance(allowed, str) and not _assert_type(payload[key], allowed):
            raise ValueError(f"Type mismatch for {key}: expected {allowed}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate overlay output against JSON schema")
    parser.add_argument("json_file", help="Path to generated overlay file")
    args = parser.parse_args()

    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    with Path(args.json_file).open("r", encoding="utf-8") as f:
        payload = json.load(f)

    _validate_top_level(payload, schema)
    print(f"[OK] Schema validation passed for {args.json_file}")


if __name__ == "__main__":
    main()
