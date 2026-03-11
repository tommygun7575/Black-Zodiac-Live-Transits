#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.calculate_aspects import arabic_parts, fixed_star_conjunctions, harmonic_aspects
from scripts.fetch_ephemeris import fetch_all_positions, load_catalog
from scripts.overlay_engine import build_natal_positions, generate_overlays
from scripts.validate_output_schema import validate_payload

ROOT = Path(__file__).resolve().parents[1]
NATAL_PATH = ROOT / "config" / "natal_profiles.json"
OUTPUT_DIR = ROOT / "output" / "daily_overlays"
DOCS_OUTPUT_DIR = ROOT / "docs" / "overlays"


def load_natal_profiles() -> dict:
    with NATAL_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def utc_midnight_for_day(day: str | None = None) -> datetime:
    if day:
        parsed = datetime.strptime(day, "%Y-%m-%d")
        return parsed.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def to_pacific_string(dt_utc: datetime) -> str:
    return dt_utc.astimezone(ZoneInfo("America/Los_Angeles")).isoformat()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main() -> Path:
    parser = argparse.ArgumentParser(description="Generate deterministic daily transit overlays")
    parser.add_argument("--date", help="UTC day in YYYY-MM-DD; defaults to current UTC day")
    args = parser.parse_args()

    transit_dt_utc = utc_midnight_for_day(args.date)
    catalog = load_catalog()
    transit_positions = fetch_all_positions(transit_dt_utc, catalog=catalog)

    harmonics = harmonic_aspects(transit_positions)
    parts = arabic_parts(transit_positions)
    star_conjunctions = fixed_star_conjunctions(transit_positions)

    natal_profiles = load_natal_profiles()
    natal_positions = build_natal_positions(natal_profiles)
    overlays = generate_overlays(transit_positions, natal_positions)

    pacific_timestamp = to_pacific_string(transit_dt_utc)
    date_tag = transit_dt_utc.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y_%m_%d")

    output = {
        "generated_at_utc": transit_dt_utc.isoformat().replace("+00:00", "Z"),
        "generated_at_pacific": pacific_timestamp,
        "transit_positions": transit_positions,
        "calculated_harmonics": harmonics,
        "arabic_parts": parts,
        "fixed_star_conjunctions": star_conjunctions,
        "natal_overlays": overlays,
    }

    validate_payload(output)

    output_path = OUTPUT_DIR / f"daily_overlay_{date_tag}.json"
    _write_json(output_path, output)

    timestamp_tag = datetime.now(timezone.utc).strftime("%Y_%m_%d_%H%M")
    docs_output_path = DOCS_OUTPUT_DIR / f"daily_overlay_{timestamp_tag}.json"
    _write_json(docs_output_path, output)

    print(f"[OK] Generated {output_path}")
    print(f"[OK] Published {docs_output_path}")
    return output_path


if __name__ == "__main__":
    main()
