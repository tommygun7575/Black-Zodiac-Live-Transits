#!/usr/bin/env python3
import json, os, sys
from datetime import datetime, timezone
from typing import Dict, Any
from math import fmod
import swisseph as swe
from dateutil import parser

# Source imports
from scripts.sources import horizons_client, miriade_client, mpc_client, swiss_client
from scripts.utils.coords import ra_dec_to_ecl

# ---- Setup ----
ROOT = os.path.dirname(os.path.dirname(__file__))
DATA = os.path.join(ROOT, "data")
NATAL = os.path.join("config", "natal", "3_combined_kitchen_sink.json")

# Point Swiss Ephemeris at the .se1 files in repo root
swe.set_ephe_path(ROOT)

# ---- Helpers ----
def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def normalize(deg: float) -> float:
    return fmod(deg + 360.0, 360.0)

# ---- Arabic Parts ----
def compute_arabic_parts(asc: float, sun: float, moon: float) -> Dict[str, Dict[str, Any]]:
    parts = {}
    is_day = (sun - asc) % 360 < 180
    fortune = asc + (moon - sun if is_day else sun - moon)
    spirit = asc + (sun - moon if is_day else moon - sun)
    karma = asc + (sun + moon) / 2.0
    treachery = asc + (moon - karma)
    victory = asc + (sun - karma)
    deliverance = asc + (spirit - fortune)
    for name, lon in {
        "Part_of_Fortune": fortune,
        "Part_of_Spirit": spirit,
        "Part_of_Karma": karma,
        "Part_of_Treachery": treachery,
        "Part_of_Victory": victory,
        "Part_of_Deliverance": deliverance,
    }.items():
        parts[name] = {"ecl_lon_deg": normalize(lon), "ecl_lat_deg": 0.0, "used_source": "calculated"}
    return parts

# ---- Houses ----
def compute_house_cusps(lat: float, lon: float, when_iso: str, hsys: str = "P") -> Dict[str, Dict[str, Any]]:
    dt = parser.isoparse(when_iso)
    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute/60.0 + dt.second/3600.0)
    cusps, ascmc = swe.houses(jd, lat, lon, hsys.encode("utf-8"))
    houses = {}
    for i, cusp in enumerate(cusps, start=1):
        houses[f"House_{i}"] = {"ecl_lon_deg": cusp, "ecl_lat_deg": 0.0, "used_source": f"houses-{hsys}"}
    houses["ASC"] = {"ecl_lon_deg": ascmc[0], "ecl_lat_deg": 0.0, "used_source": "houses"}
    houses["MC"] = {"ecl_lon_deg": ascmc[1], "ecl_lat_deg": 0.0, "used_source": "houses"}
    return houses

# ---- Harmonics ----
def compute_harmonics(base_positions: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    harmonics = {}
    for body, pos in base_positions.items():
        if pos["ecl_lon_deg"] is None:
            continue
        lon = pos["ecl_lon_deg"]
        harmonics[f"{body}_h8"] = {"ecl_lon_deg": normalize(lon*8 % 360), "ecl_lat_deg": 0.0, "used_source": "harmonic8"}
        harmonics[f"{body}_h9"] = {"ecl_lon_deg": normalize(lon*9 % 360), "ecl_lat_deg": 0.0, "used_source": "harmonic9"}
    return harmonics

# ---- Master compute ----
def compute_positions(when_iso: str, lat: float, lon: float) -> Dict[str, Dict[str, Any]]:
    out = {}

    MAJORS = ["Sun","Moon","Mercury","Venus","Mars","Jupiter","Saturn","Uranus","Neptune","Pluto","Chiron"]
    ASTEROIDS = ["Ceres","Pallas","Juno","Vesta","Psyche","Amor","Eros","Astraea","Sappho","Karma","Bacchus"]
    TNOs = ["Eris","Sedna","Haumea","Makemake","Varuna","Ixion","Typhon","Salacia","2002 AW197","2003 VS2"]
    AETHERS = ["Vulcan","Persephone","Hades","Proserpina","Isis"]

    def resolve_body(name: str, sources, force_fallback: bool = False) -> Dict[str, Any]:
        got, used = None, None
        for label, func in sources:
            try:
                pos = func(name, when_iso)
            except Exception:
                pos = None
            if pos:
                got, used = pos, label
                break
        if not got and force_fallback:
            got, used = (0.0, 0.0), "calculated-fallback"
        return {
            "ecl_lon_deg": None if not got else float(got[0]),
            "ecl_lat_deg": None if not got else float(got[1]),
            "used_source": "missing" if not used else used
        }

    # Majors (Swiss first, fallback if needed)
    for name in MAJORS:
        out[name] = resolve_body(name, [
            ("swiss", swiss_client.get_ecliptic_lonlat),
            ("jpl", horizons_client.get_ecliptic_lonlat)
        ], force_fallback=True)

    # Asteroids (Swiss first, fallback if needed)
    for name in ASTEROIDS:
        out[name] = resolve_body(name, [
            ("swiss", swiss_client.get_ecliptic_lonlat),
            ("jpl", horizons_client.get_ecliptic_lonlat)
        ], force_fallback=True)

    # TNOs
    for name in TNOs:
        out[name] = resolve_body(name, [
            ("swiss", swiss_client.get_ecliptic_lonlat),
            ("miriade", miriade_client.get_ecliptic_lonlat),
            ("jpl", horizons_client.get_ecliptic_lonlat)
        ])

    # Aethers
    for name in AETHERS:
        out[name] = resolve_body(name, [
            ("swiss", swiss_client.get_ecliptic_lonlat),
            ("miriade", miriade_client.get_ecliptic_lonlat)
        ])

    # Fixed Stars
    stars = load_json(os.path.join(DATA, "fixed_stars.json"))["stars"]
    for s in stars:
        lam, bet = ra_dec_to_ecl(s["ra_deg"], s["dec_deg"], when_iso)
        out[s["id"]] = {"ecl_lon_deg": lam, "ecl_lat_deg": bet, "used_source": "fixed"}

    # Houses
    out.update(compute_house_cusps(lat, lon, when_iso))

    # Arabic Parts
    if "ASC" in out and "Sun" in out and "Moon" in out:
        asc, sun, moon = out["ASC"]["ecl_lon_deg"], out["Sun"]["ecl_lon_deg"], out["Moon"]["ecl_lon_deg"]
        if None not in (asc, sun, moon):
            out.update(compute_arabic_parts(asc, sun, moon))

    # Harmonics
    out.update(compute_harmonics(out))

    return out

# ---- Merge ----
def merge_into(natal_bundle: Dict[str, Any], when_iso: str) -> Dict[str, Any]:
    meta = {
        "generated_at_utc": when_iso,
        "source_order": [
            "swiss (majors/asteroids/tnos/aethers)",
            "jpl (fallback for majors/asteroids/tnos)",
            "miriade (tnos/aethers fill)",
            "fixed (stars)",
            "houses (cusps, ASC, MC)",
            "calculated (arabic parts)",
            "calculated (harmonics)",
            "calculated-fallback (majors/asteroids if all fail)"
        ]
    }

    charts = {}
    for who, natal in natal_bundle.items():
        if who.startswith("_meta"):
            continue
        birth = natal.get("birth", {})
        lat, lon = birth.get("lat"), birth.get("lon")
        charts[who] = {
            "birth": birth,
            "natal": natal.get("planets", {}),
            "objects": compute_positions(when_iso, lat, lon)
        }

    return {"meta": meta, "charts": charts}

# ---- Main ----
def main(argv):
    out_path = os.environ.get("OVERLAY_OUT", os.path.join("docs", "feed_overlay.json"))
    when_iso = os.environ.get("OVERLAY_TIME_UTC") or iso_now()

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    natal_bundle = load_json(NATAL)
    merged = merge_into(natal_bundle, when_iso)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"wrote {out_path}")

if __name__ == "__main__":
    main(sys.argv[1:])
