#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_ephemeris import fetch_all_positions, load_catalog
NATAL_PATH = ROOT / "config" / "natal_profiles.json"
OUTPUT_DIR = ROOT / "natal_charts"


def _sanitize_nans(value):
    if isinstance(value, dict):
        return {k: _sanitize_nans(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_nans(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _birth_utc(profile: dict) -> datetime:
    local = datetime.strptime(f"{profile['birth_date']} {profile['birth_time']}", "%m-%d-%Y %I:%M %p")
    return local.replace(tzinfo=ZoneInfo(profile["timezone"])).astimezone(ZoneInfo("UTC"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _safe_name(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate one-time natal snapshots")
    parser.add_argument("--person", help="Optional person name from config/natal_profiles.json")
    args = parser.parse_args()

    profiles = json.loads(NATAL_PATH.read_text(encoding="utf-8"))
    catalog = load_catalog()

    selected = {args.person: profiles[args.person]} if args.person else profiles

    for name, profile in selected.items():
        birth_dt = _birth_utc(profile)
        positions = fetch_all_positions(birth_dt, catalog=catalog)
        payload = _sanitize_nans(
            {
                "person": name,
                "birth_timestamp_utc": birth_dt.isoformat().replace("+00:00", "Z"),
                "positions": positions,
            }
        )
        path = OUTPUT_DIR / f"{_safe_name(name)}_natal_snapshot.json"
        _write_json(path, payload)
        print(f"[OK] Generated {path}")


if __name__ == "__main__":
    main()
