#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.calculate_aspects import fixed_star_conjunctions, harmonic_aspects
from scripts.fetch_ephemeris import fetch_all_positions, load_catalog

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs"


def _sanitize_nans(value):
    if isinstance(value, dict):
        return {k: _sanitize_nans(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_nans(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def utc_midnight_for_day(day: str | None = None) -> datetime:
    if day:
        parsed = datetime.strptime(day, "%Y-%m-%d")
        return parsed.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main() -> Path:
    parser = argparse.ArgumentParser(description="Generate daily transit snapshot")
    parser.add_argument("--date", help="UTC day in YYYY-MM-DD; defaults to current UTC day")
    args = parser.parse_args()

    transit_dt_utc = utc_midnight_for_day(args.date) if args.date else datetime.utcnow().replace(tzinfo=timezone.utc)
    pacific_now = transit_dt_utc.astimezone(ZoneInfo("America/Los_Angeles"))
    catalog = load_catalog()
    transit_positions = fetch_all_positions(transit_dt_utc, catalog=catalog)

    output = {
        "generated_at_utc": transit_dt_utc.isoformat(),
        "generated_at_pacific": pacific_now.isoformat(),
        "transit_positions": transit_positions,
        "calculated_harmonics": harmonic_aspects(transit_positions),
        "aether_points": {
            name: data for name, data in transit_positions.items() if data.get("category") == "aether_points"
        },
        "fixed_star_positions": {
            name: data for name, data in transit_positions.items() if data.get("category") == "fixed_stars"
        },
        "fixed_star_conjunctions": fixed_star_conjunctions(transit_positions),
    }

    output = _sanitize_nans(output)

    date_tag = pacific_now.strftime("%Y_%m_%d")
    output_path = OUTPUT_DIR / f"feed_overlay_{date_tag}.json"
    _write_json(output_path, output)

    print(f"[OK] Generated {output_path}")
    return output_path


if __name__ == "__main__":
    main()
