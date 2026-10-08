#!/usr/bin/env python3
"""Derived motion + true-station layer for the six-month feed.

The raw six-month feed (docs/feed_overlay_6month_*.json) is NEVER modified.
This module reads it and writes a SEPARATE derived file:

    docs/derived/sixmonth_derived_<stamp>.json

Rules (2026-10-08 transit-workflow rules, ZodiacOracle.SixMonthTransit.v3):
  * sample instants = meta.range_utc[0] + i days (actual time of day is
    preserved; date keys are NOT treated as midnight)
  * speed: central difference wrap180(L[i+1] - L[i-1]) / 2 days; one-sided
    wrap180(L[1]-L[0]) / 1 day and wrap180(L[n-1]-L[n-2]) / 1 day at edges
  * true stations: physical moving bodies only (no fixed stars, Aether points,
    Sun, Moon or nodes); sign change of derived speed, + -> - = station
    retrograde, - -> + = station direct; refined by least-squares quadratic
    vertex of the unwrapped longitude around the turning sample
  * every derived value carries provenance
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "config" / "celestial_catalog.json"
DERIVED_DIR = ROOT / "docs" / "derived"

DERIVED_ENGINE = "ZodiacOracle.SixMonthTransit.v3.derived"
SPEED_SOURCE = "six_month_central_difference"
STATION_EXCLUDED_CATEGORIES = {"fixed_stars", "aether_points", "lunar_nodes"}
STATION_EXCLUDED_BODIES = {"Sun", "Moon", "True_Node", "Mean_Node", "South_Node"}
# SPEC §4.6 / luminous_gate_reconstruction.json aspects_orbs.stations
SPEC_CORE_STATION_BODIES = ["Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto", "Chiron"]
HALF_WINDOW_DAYS = {"Mercury": 2, "Venus": 3, "Mars": 4, "Jupiter": 7, "Saturn": 7,
                    "Uranus": 10, "Neptune": 10, "Pluto": 10, "Chiron": 7}
# Not in SPEC: documented conservative default for other physical bodies.
DEFAULT_HALF_WINDOW_DAYS = 7


def wrap180(x: float) -> float:
    """((x + 180) mod 360 + 360) mod 360 - 180, range [-180, 180)."""
    return ((x + 180.0) % 360.0 + 360.0) % 360.0 - 180.0


def norm360(x: float) -> float:
    return ((x % 360.0) + 360.0) % 360.0


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_categories(path: Path = CATALOG_PATH) -> Dict[str, str]:
    cat = json.loads(path.read_text(encoding="utf-8"))
    out: Dict[str, str] = {}
    for c, objs in (cat.get("categories") or {}).items():
        if isinstance(objs, list):
            for o in objs:
                if isinstance(o, dict) and o.get("name"):
                    out[str(o["name"])] = c
    out.setdefault("South_Node", "lunar_nodes")
    return out


def body_category(name: str, sample: Dict[str, Any], cats: Dict[str, str]) -> str:
    if name in cats:
        return cats[name]
    if sample.get("source") == "fixed":
        return "fixed_stars"
    if name.startswith("Aetheric_"):
        return "aether_points"
    return "unknown"


def station_eligible(name: str, category: str) -> bool:
    return name not in STATION_EXCLUDED_BODIES and category not in STATION_EXCLUDED_CATEGORIES


def sample_times(payload: Dict[str, Any]) -> Tuple[List[str], List[datetime], List[str]]:
    keys = list(payload["transits"].keys())
    t0 = _parse_iso(payload["meta"]["range_utc"][0])
    times = [t0 + timedelta(days=i) for i in range(len(keys))]
    mismatches = [k for k, t in zip(keys, times) if t.strftime("%Y-%m-%d") != k]
    return keys, times, mismatches


def series_for(payload: Dict[str, Any], keys: List[str], name: str) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for k in keys:
        v = (payload["transits"][k] or {}).get(name) or {}
        lon = v.get("ecl_lon_deg")
        out.append(float(lon) if isinstance(lon, (int, float)) and math.isfinite(lon) else None)
    return out


def finite_difference_speed(L: List[Optional[float]], step_days: float = 1.0) -> Tuple[List[Optional[float]], List[str]]:
    n = len(L)
    sp: List[Optional[float]] = [None] * n
    meth: List[str] = ["unresolved"] * n
    for i in range(n):
        if 0 < i < n - 1 and L[i - 1] is not None and L[i + 1] is not None:
            sp[i] = wrap180(L[i + 1] - L[i - 1]) / (2.0 * step_days)
            meth[i] = "central"
        elif i == 0 and n > 1 and L[0] is not None and L[1] is not None:
            sp[i] = wrap180(L[1] - L[0]) / step_days
            meth[i] = "forward_one_sided"
        elif i == n - 1 and n > 1 and L[i] is not None and L[i - 1] is not None:
            sp[i] = wrap180(L[i] - L[i - 1]) / step_days
            meth[i] = "backward_one_sided"
    return sp, meth


def unwrap(L: List[float]) -> List[float]:
    out = [L[0]]
    for x in L[1:]:
        out.append(out[-1] + wrap180(x - out[-1]))
    return out


def _polyfit2(xs: List[float], ys: List[float]) -> Tuple[float, float, float, float]:
    import numpy as np
    c = np.polyfit(np.array(xs), np.array(ys), 2)
    resid = float(np.sqrt(np.mean((np.polyval(c, np.array(xs)) - np.array(ys)) ** 2)))
    return float(c[0]), float(c[1]), float(c[2]), resid


def detect_stations(name: str, L: List[Optional[float]], speed: List[Optional[float]],
                    times: List[datetime]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    n = len(L)
    for i in range(n - 1):
        a, b = speed[i], speed[i + 1]
        if a is None or b is None or a == b:
            continue
        if not ((a > 0 >= b) or (a < 0 <= b)):
            continue
        stype = "station_retrograde" if a > 0 else "station_direct"
        h = HALF_WINDOW_DAYS.get(name, DEFAULT_HALF_WINDOW_DAYS)
        # turning sample = extreme of unwrapped longitude among i, i+1
        lo, hi = max(0, i - h), min(n - 1, i + 1 + h)
        idx = [j for j in range(lo, hi + 1) if L[j] is not None]
        uw = unwrap([L[j] for j in idx])
        xs = [float(j - i) for j in idx]
        method = "least_squares_quadratic_vertex"
        rec: Dict[str, Any] = {"body": name, "station_type": stype}
        try:
            if len(xs) < 3:
                raise ValueError("insufficient samples")
            c2, c1, c0, resid = _polyfit2(xs, uw)
            if c2 == 0:
                raise ValueError("degenerate fit")
            xv = -c1 / (2 * c2)
            if not (-1.0 <= xv <= 2.0):
                raise ValueError("vertex outside bracket")
            lon = norm360(c0 + c1 * xv + c2 * xv * xv)
            rec.update({"fit_rms_deg": resid, "fit_half_window_days": h, "fit_samples": len(xs),
                        "fit_window_truncated": (i - h < 0) or (i + 1 + h > n - 1)})
        except Exception as exc:  # fall back to linear interpolation of speed
            xv = a / (a - b)
            lon = norm360(L[i] + wrap180(L[i + 1] - L[i]) * xv) if L[i] is not None and L[i + 1] is not None else None
            method = f"linear_speed_interpolation ({exc})"
        t = times[i] + timedelta(days=xv)
        rec.update({
            "timestamp_utc": iso_z(t),
            "timestamp_precision": "about +/- 0.5 day for slow bodies (flat motion near station); daily sampling",
            "longitude": lon,
            "bracket_samples_utc": [iso_z(times[i]), iso_z(times[i + 1])],
            "bracket_speeds_deg_per_day": [a, b],
            "derivation_method": f"sign change of {SPEED_SOURCE} speed; refined by {method}",
            "spec_core_station_body": name in SPEC_CORE_STATION_BODIES,
        })
        out.append(rec)
    return out


def swiss_station_crosscheck(stations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Independent check: Swiss Ephemeris λ̇ zero crossing for major bodies."""
    try:
        import swisseph as swe
    except Exception:
        return []
    swe.set_ephe_path(str(ROOT / "ephe"))
    ids = {"Mercury": swe.MERCURY, "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
           "Saturn": swe.SATURN, "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE, "Pluto": swe.PLUTO,
           "Chiron": swe.CHIRON}
    res = []
    for st in stations:
        if st["body"] not in ids:
            continue
        t = _parse_iso(st["timestamp_utc"])
        jd0 = swe.julday(t.year, t.month, t.day, t.hour + t.minute / 60 + t.second / 3600)
        f = lambda jd: swe.calc_ut(jd, ids[st["body"]], swe.FLG_SWIEPH | swe.FLG_SPEED)[0][3]
        a, b = jd0 - 3, jd0 + 3
        try:
            fa, fb = f(a), f(b)
            if fa * fb > 0:
                res.append({"body": st["body"], "station_type": st["station_type"], "result": "NO_BRACKET"})
                continue
            for _ in range(60):
                m = (a + b) / 2
                fm = f(m)
                if fa * fm <= 0:
                    b, fb = m, fm
                else:
                    a, fa = m, fm
            jd = (a + b) / 2
            lon = swe.calc_ut(jd, ids[st["body"]], swe.FLG_SWIEPH | swe.FLG_SPEED)[0][0]
            y, mo, d, hr = swe.revjul(jd)
            ts = datetime(y, mo, d, tzinfo=timezone.utc) + timedelta(hours=hr)
            dh = (ts - t).total_seconds() / 3600
            res.append({"body": st["body"], "station_type": st["station_type"], "swiss_timestamp_utc": iso_z(ts),
                        "swiss_longitude": lon, "time_diff_hours": round(dh, 2),
                        "longitude_diff_deg": round(abs(wrap180(lon - st["longitude"])), 5),
                        "result": "PASS" if abs(dh) <= 24 and abs(wrap180(lon - st["longitude"])) <= 0.05 else "FAIL"})
        except Exception as exc:
            res.append({"body": st["body"], "station_type": st["station_type"], "result": f"ERROR {exc}"})
    return res


def build_derived(payload: Dict[str, Any], source_file: str) -> Dict[str, Any]:
    cats = load_categories()
    keys, times, mismatches = sample_times(payload)
    first_day = payload["transits"][keys[0]]
    names = list(first_day.keys())
    bodies: Dict[str, Any] = {}
    stations: List[Dict[str, Any]] = []
    wrap_checks = []
    for name in names:
        cat = body_category(name, first_day.get(name) or {}, cats)
        L = series_for(payload, keys, name)
        sp, meth = finite_difference_speed(L)
        eligible = station_eligible(name, cat)
        if cat == "fixed_stars":
            motion = ["fixed" if s is not None else "unresolved" for s in sp]
        else:
            motion = [("unresolved" if s is None else ("retrograde" if s < 0 else "direct")) for s in sp]
        max_jump = max((abs(wrap180(L[i + 1] - L[i])) for i in range(len(L) - 1)
                        if L[i] is not None and L[i + 1] is not None), default=None)
        bodies[name] = {
            "category": cat,
            "station_eligible": eligible,
            "speed_deg_per_day": sp,
            "speed_method": meth,
            "motion": motion,
            "max_abs_daily_step_deg": max_jump,
        }
        if eligible:
            stations.extend(detect_stations(name, L, sp, times))
        wrap_checks.append(max_jump)
    stations.sort(key=lambda s: s["timestamp_utc"])
    xcheck = swiss_station_crosscheck(stations)
    return {
        "engine_version": DERIVED_ENGINE,
        "layer": "derived (separate from raw feed; raw positions untouched)",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_feed": source_file,
        "source_engine_version": payload.get("engine_version"),
        "source_range_utc": payload["meta"]["range_utc"],
        "sample_time_rule": "sample[i] = meta.range_utc[0] + i days; actual time of day preserved; date keys are labels, not midnight",
        "sample_timestamps_utc": [iso_z(t) for t in times],
        "sample_date_keys": keys,
        "date_key_mismatches": mismatches,
        "speed_provenance": {
            "speed_source": SPEED_SOURCE,
            "formula_interior": "wrap180(L[i+1] - L[i-1]) / 2 days",
            "formula_edges": "wrap180(L[1]-L[0]) / 1 day (first), wrap180(L[n-1]-L[n-2]) / 1 day (last)",
            "units": "deg/day, apparent geocentric ecliptic of date (from raw ecl_lon_deg)",
            "authority": "derived; never overrides a newer valid daily longitude_speed",
        },
        "station_rules": {
            "authoritative_station_detector": True,
            "eligible": "physical moving bodies only",
            "excluded": ["fixed stars", "Aether points", "Sun", "Moon", "lunar nodes (unless approved later)"],
            "station_retrograde": "derived speed + -> -",
            "station_direct": "derived speed - -> +",
            "refinement": "least-squares quadratic vertex of unwrapped longitude over +/- half_window_days around the sign change",
            "half_window_days": dict(HALF_WINDOW_DAYS, default_other_bodies=DEFAULT_HALF_WINDOW_DAYS),
            "half_window_provenance": "SPEC §4.6 (luminous_gate_reconstruction.json aspects_orbs.stations.half_window_days); default 7 for non-SPEC bodies is a documented conservative parameter",
            "spec_core_station_bodies": SPEC_CORE_STATION_BODIES,
        },
        "stations": stations,
        "station_swiss_crosscheck": xcheck,
        "bodies": bodies,
        "summary": {
            "body_count": len(bodies),
            "sample_count": len(keys),
            "station_eligible_count": sum(1 for b in bodies.values() if b["station_eligible"]),
            "stations_found": len(stations),
            "stations_spec_core": sum(1 for s in stations if s["spec_core_station_body"]),
            "fixed_star_stations": sum(1 for s in stations if bodies[s["body"]]["category"] == "fixed_stars"),
            "excluded_body_stations": sum(1 for s in stations if not bodies[s["body"]]["station_eligible"]),
            "max_abs_daily_step_deg_all_bodies": max(x for x in wrap_checks if x is not None),
            "swiss_crosscheck_pass": sum(1 for x in xcheck if x.get("result") == "PASS"),
            "swiss_crosscheck_total": len(xcheck),
        },
    }


def derived_paths(raw_path: Path) -> Dict[str, Path]:
    stem = raw_path.stem[len("feed_overlay_6month_"):] if raw_path.stem.startswith("feed_overlay_6month_") else raw_path.stem
    return {
        "derived": DERIVED_DIR / f"sixmonth_derived_{stem}.json",
        "natal_reference": DERIVED_DIR / f"sixmonth_transit_to_natal_reference_{stem}.json",
    }


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def latest_raw() -> Path:
    def stamp(f: Path):
        raw = f.stem[len("feed_overlay_6month_"):].removesuffix("_Pacific")
        return datetime.strptime(raw, "%b-%d-%Y_%I-%M%p")
    return max((ROOT / "docs").glob("feed_overlay_6month_*.json"), key=stamp)


def latest_daily_feed() -> Optional[Path]:
    files = sorted((ROOT / "docs").glob("feed_overlay_[0-9][0-9][0-9][0-9]_[0-9][0-9]_[0-9][0-9].json"))
    return files[-1] if files else None


def run(raw_path: Path, natal_source: Optional[Path] = None) -> Dict[str, Path]:
    import hashlib
    from scripts.transit_to_natal import load_natal, run_transit_to_natal, load_rules
    raw_bytes = raw_path.read_bytes()
    payload = json.loads(raw_bytes.decode("utf-8"))
    rel = str(raw_path.relative_to(ROOT)) if ROOT in raw_path.parents else str(raw_path)
    derived = build_derived(payload, rel)
    derived["source_feed_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
    paths = derived_paths(raw_path)
    write_json(paths["derived"], derived)
    out = {"derived": paths["derived"]}
    if natal_source is not None and natal_source.exists():
        natal = load_natal(natal_source, reference_label="reference/test data (daily-feed embedded natal); not a user's chart")
        report = run_transit_to_natal(payload, derived, natal, load_rules(), source_file=rel,
                                      derived_file=str(paths["derived"].relative_to(ROOT)))
        write_json(paths["natal_reference"], report)
        out["natal_reference"] = paths["natal_reference"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Six-month derived speed/station layer (+ reference transit-to-natal)")
    ap.add_argument("raw", nargs="?", help="raw six-month feed (default: newest by filename timestamp)")
    ap.add_argument("--natal", help="natal source (daily feed with natal_chart, natal snapshot, or generic points JSON)")
    a = ap.parse_args()
    raw = Path(a.raw).resolve() if a.raw else latest_raw()
    natal = Path(a.natal).resolve() if a.natal else latest_daily_feed()
    out = run(raw, natal)
    for k, p in out.items():
        print(f"[OK] {k}: {p}")


if __name__ == "__main__":
    main()
