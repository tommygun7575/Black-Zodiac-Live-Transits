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

ROOT = Path(__file__).resolve().parents[1]
NATAL_PATH = ROOT / "config" / "natal_profiles.json"
OUTPUT_DIR = ROOT / "output" / "daily_overlays"


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

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"daily_overlay_{date_tag}.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"[OK] Generated {output_path}")
    return output_path


if __name__ == "__main__":
    main()
