import json, os, sys, math
from datetime import datetime, timezone
from typing import Dict, Any
from math import fmod
import swisseph as swe
from dateutil import parser
import pytz
from scripts.sources import horizons_client, swiss_client, miriade_client
from scripts.utils.coords import ra_dec_to_ecl

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA = os.path.join(ROOT, "data")
NATAL = os.path.join("config", "natal", "3_combined_kitchen_sink.json")

# Ensure Swiss ephemeris is pointed correctly
swe.set_ephe_path(os.path.join(ROOT, "ephe"))

# Aliases for Sun/Moon
NAME_ALIASES = {
    "Sun": ["Sun", "SUN", "10"],
    "Moon": ["Moon", "MOON", "301"]
}

def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def normalize(deg: float) -> float:
    return fmod(deg + 360.0, 360.0)

# Arabic Parts calculation
def compute_arabic_parts(asc, sun, moon):
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
        parts[name] = {
            "ecl_lon_deg": normalize(lon),
            "ecl_lat_deg": 0.0,
            "used_source": "calculated"
        }
    return parts

# Houses calculation
def compute_house_cusps(lat, lon, when_iso, hsys="P"):
    dt = parser.isoparse(when_iso)
    jd = swe.julday(dt.year, dt.month, dt.day,
                    dt.hour + dt.minute/60.0 + dt.second/3600.0)
    cusps, ascmc = swe.houses(jd, lat, lon, hsys.encode("utf-8"))
    houses = {f"House_{i}": {"ecl_lon_deg": cusp, "ecl_lat_deg": 0.0, "used_source": f"houses-{hsys}"} 
              for i, cusp in enumerate(cusps, start=1)}
    houses["ASC"] = {"ecl_lon_deg": ascmc[0], "ecl_lat_deg": 0.0, "used_source": "houses"}
    houses["MC"] = {"ecl_lon_deg": ascmc[1], "ecl_lat_deg": 0.0, "used_source": "houses"}
    return houses

# Harmonics
def compute_harmonics(base_positions: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    harmonics = {}
    for body, pos in base_positions.items():
        if pos["ecl_lon_deg"] is None:
            continue
        lon = pos["ecl_lon_deg"]
        harmonics[f"{body}_h8"] = {"ecl_lon_deg": normalize(lon*8 % 360), "ecl_lat_deg": 0.0, "used_source": "harmonic8"}
        harmonics[f"{body}_h9"] = {"ecl_lon_deg": normalize(lon*9 % 360), "ecl_lat_deg": 0.0, "used_source": "harmonic9"}
    return harmonics

# Resolver
def resolve_body(name, sources, when_iso, force_fallback=False):
    got, used = None, None
    aliases = NAME_ALIASES.get(name, [name])
    for alias in aliases:
        for label, func in sources:
            try:
                pos = func(alias, when_iso)
            except Exception:
                pos = None
            if pos:
                lon, lat = pos
                if lon is not None and lat is not None and not (math.isnan(lon) or math.isnan(lat)):
                    got, used = (lon, lat), label
                    break
        if got:
            break
    if not got and force_fallback:
        got, used = (0.0, 0.0), "calculated-fallback"
    return {"ecl_lon_deg": None if not got else float(got[0]),
            "ecl_lat_deg": None if not got else float(got[1]),
            "used_source": "missing" if not used else used}

def compute_positions(when_iso, lat, lon):
    out = {}
    MAJORS = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto", "Chiron"]
    ASTEROIDS = ["Ceres", "Pallas", "Juno", "Vesta", "Psyche", "Amor", "Eros", "Astraea", "Sappho", "Karma", "Bacchus", "Hygiea", "Nessus"]
    TNOs = ["Eris", "Sedna", "Haumea", "Makemake", "Varuna", "Ixion", "Typhon", "Salacia", "2002 AW197", "2003 VS2", "Orcus", "Quaoar"]
    AETHERS = ["Vulcan", "Persephone", "Hades", "Proserpina", "Isis"]

    for name in MAJORS + ASTEROIDS + TNOs:
        out[name] = resolve_body(name, [
            ("jpl", horizons_client.get_ecliptic_lonlat),
            ("miriade", miriade_client.get_ecliptic_lonlat),
            ("swiss", swiss_client.get_ecliptic_lonlat)
        ], when_iso, force_fallback=True)

    for name in AETHERS:
        out[name] = resolve_body(name, [("swiss", swiss_client.get_ecliptic_lonlat)], when_iso, force_fallback=True)

    stars = load_json(os.path.join(DATA, "fixed_stars.json"))["stars"]
    for s in stars:
        lam, bet = ra_dec_to_ecl(s["ra_deg"], s["dec_deg"], when_iso)
        out[s["id"]] = {"ecl_lon_deg": lam, "ecl_lat_deg": bet, "used_source": "fixed"}

    out.update(compute_house_cusps(lat, lon, when_iso))
    if "ASC" in out and "Sun" in out and "Moon" in out:
        asc, sun, moon = out["ASC"]["ecl_lon_deg"], out["Sun"]["ecl_lon_deg"], out["Moon"]["ecl_lon_deg"]
        if None not in (asc, sun, moon):
            out.update(compute_arabic_parts(asc, sun, moon))
    out.update(compute_harmonics(out))
    return out

def merge_into(natal_bundle, when_iso):
    meta = {
        "generated_at_utc": when_iso,
        "source_order": [
            "jpl (majors/asteroids/tnos)",
            "miriade (fallback)",
            "swiss (fallback)",
            "fixed (stars)",
            "houses (cusps, ASC, MC)",
            "calculated (arabic parts)",
            "calculated (harmonics)",
            "calculated-fallback"
        ]
    }
    charts = {}
    for who, natal in natal_bundle.items():
        if who.startswith("_meta"): continue
        birth = natal.get("birth", {})
        lat, lon = birth.get("lat"), birth.get("lon")
        charts[who] = {"birth": birth, "natal": natal.get("planets", {}), "objects": compute_positions(when_iso, lat, lon)}
    return {"meta": meta, "charts": charts}

def main(argv):
    when_iso = os.environ.get("OVERLAY_TIME_UTC") or iso_now()

    # Convert UTC → Pacific
    utc_dt = parser.isoparse(when_iso).replace(tzinfo=pytz.utc)
    pacific = pytz.timezone("America/Los_Angeles")
    pac_dt = utc_dt.astimezone(pacific)

    # Filename with Pacific time
    dt_tag = pac_dt.strftime("%b-%d-%Y_%I-%M%p_Pacific")
    out_name = f"feed_overlay_{dt_tag}.json"
    out_path = os.path.join("docs", out_name)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    natal_bundle = load_json(NATAL)
    merged = merge_into(natal_bundle, when_iso)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"[OK] wrote overlay → {out_path}")

if __name__ == "__main__":
    main(sys.argv[1:])
