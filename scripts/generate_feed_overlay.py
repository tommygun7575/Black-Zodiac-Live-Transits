#!/usr/bin/env python3
import json, os, sys
from datetime import datetime, timezone
from typing import Dict, Any, List

# Explicit imports
from scripts.sources import horizons_client, miriade_client, mpc_client, swiss_client
from scripts.utils.coords import ra_dec_to_ecl

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA = os.path.join(ROOT, "data")
NATAL = os.path.join("config", "natal", "3_combined_kitchen_sink.json")

def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def compute_positions(when_iso: str) -> Dict[str, Dict[str, Any]]:
    out = {}

    # ---- Categories ----
    MAJORS = ["Sun","Moon","Mercury","Venus","Mars",
              "Jupiter","Saturn","Uranus","Neptune","Pluto","Chiron"]

    ASTEROIDS = ["Ceres","Pallas","Juno","Vesta","Psyche",
                 "Amor","Eros","Astraea","Sappho","Karma","Bacchus"]

    TNOs = ["Eris","Sedna","Haumea","Makemake","Varuna",
            "Ixion","Typhon","Salacia","2002 AW197","2003 VS2"]

    AETHERS = ["Vulcan","Persephone","Hades","Proserpina","Isis"]

    # ---- Helper to query with fallbacks ----
    def resolve_body(name: str, sources) -> Dict[str, Any]:
        got, used = None, None
        for label, func in sources:
            try:
                pos = func(name, when_iso)
            except Exception:
                pos = None
            if pos:
                got, used = pos, label
                break
        return {
            "ecl_lon_deg": None if not got else float(got[0]),
            "ecl_lat_deg": None if not got else float(got[1]),
            "source": "missing" if not used else used
        }

    # ---- Majors: JPL first, Swiss fallback ----
    for name in MAJORS:
        out[name] = resolve_body(name, [
            ("jpl", horizons_client.get_ecliptic_lonlat),
            ("swiss", swiss_client.get_ecliptic_lonlat)
        ])

    # ---- Asteroids: JPL first, Swiss fallback ----
    for name in ASTEROIDS:
        out[name] = resolve_body(name, [
            ("jpl", horizons_client.get_ecliptic_lonlat),
            ("swiss", swiss_client.get_ecliptic_lonlat)
        ])

    # ---- TNOs: Swiss first, then Miriade, then JPL fallback ----
    for name in TNOs:
        out[name] = resolve_body(name, [
            ("swiss", swiss_client.get_ecliptic_lonlat),
            ("miriade", miriade_client.get_ecliptic_lonlat),
            ("jpl", horizons_client.get_ecliptic_lonlat)
        ])

    # ---- Aethers: Swiss first (guaranteed now), Miriade fallback ----
    for name in AETHERS:
        out[name] = resolve_body(name, [
            ("swiss", swiss_client.get_ecliptic_lonlat),
            ("miriade", miriade_client.get_ecliptic_lonlat)
        ])

    # ---- Fixed stars: always available ----
    stars = load_json(os.path.join(DATA, "fixed_stars.json"))["stars"]
    for s in stars:
        lam, bet = ra_dec_to_ecl(s["ra_deg"], s["dec_deg"], when_iso)
        out[s["id"]] = {"ecl_lon_deg": lam, "ecl_lat_deg": bet, "source": "fixed"}

    return out

def merge_into(natal_bundle: Dict[str, Any],
               positions: Dict[str, Dict[str, Any]],
               when_iso: str) -> Dict[str, Any]:
    meta = {
        "generated_at_utc": when_iso,
        "source_order": [
            "jpl (majors/asteroids)",
            "swiss (tnos/aethers/fallback)",
            "miriade (tnos/aethers fill)",
            "fixed (stars)"
        ]
    }

    charts = {}
    for who, natal in natal_bundle.items():
        if who.startswith("_meta"):
            continue
        charts[who] = {
            "birth": natal.get("birth", {}),
            "natal": natal.get("planets", {}),
            "objects": positions
        }

    return {"meta": meta, "charts": charts}

def main(argv: List[str]):
    out_path = os.environ.get("OVERLAY_OUT",
                              os.path.join("docs", "feed_overlay.json"))
    when_iso = os.environ.get("OVERLAY_TIME_UTC", iso_now())
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    natal_bundle = load_json(NATAL)
    positions = compute_positions(when_iso)
    merged = merge_into(natal_bundle, positions, when_iso)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"wrote {out_path}")

if __name__ == "__main__":
    main(sys.argv[1:])
