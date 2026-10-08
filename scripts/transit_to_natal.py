#!/usr/bin/env python3
"""Generic transit-to-natal engine over the six-month series.

Accepts ANY natal chart (daily-feed natal_chart block, natal snapshot
``positions`` file, or a generic ``{"points": {name: longitude}}`` JSON) and
computes, from the six-month raw positions + derived speeds:

  transit-to-natal aspects, exact hits, orb entry/exit windows, near misses,
  applying/separating, retrograde multi-pass sequences, returns, cycle
  checkpoints, lunations, eclipse candidates, recurring activation and
  candidate convergence windows.

Every TransitSeries records entry, exact pass(es), exit, pass number, station
involvement, applying/separating, near miss and provenance.

Aspect set, orbs, f(t), EXACT/APPLYING/SEPARATING, exactness search, station,
lunation and eclipse-candidate rules come from config/transit_to_natal_rules.json
(copied verbatim from luminous_gate_reconstruction.json aspects_orbs). Anything
not defined there is a labelled documented parameter with a decision ref.
Personal birth details are never copied into the report.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "config" / "transit_to_natal_rules.json"
ENGINE = "ZodiacOracle.TransitToNatal.v1"

ASPECTS = {"conjunction": 0.0, "opposition": 180.0, "square": 90.0, "trine": 120.0, "sextile": 60.0, "quincunx": 150.0}
ORB_KEY = {"conjunction": "conj_opp", "opposition": "conj_opp", "square": "square", "trine": "trine",
           "sextile": "sextile", "quincunx": "quincunx"}
PHASES = ["New", "Crescent", "First Quarter", "Gibbous", "Full", "Disseminating", "Last Quarter", "Balsamic"]
BONUS_TARGETS = {"Sun", "Moon", "ASC", "MC"}


def wrap180(x: float) -> float:
    return ((x + 180.0) % 360.0 + 360.0) % 360.0 - 180.0


def norm360(x: float) -> float:
    return ((x % 360.0) + 360.0) % 360.0


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def load_rules(path: Path = RULES_PATH) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- natal input
def load_natal(path: Path, reference_label: str = "user-supplied natal chart",
               include: Optional[List[str]] = None) -> Dict[str, Any]:
    """Load any natal chart into {points: {name: lon}} (no birth details kept)."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    pts: Dict[str, float] = {}
    angles = False
    if isinstance(d.get("natal_chart"), dict):          # daily feed
        nc = d["natal_chart"]
        for n, v in (nc.get("planets") or {}).items():
            if isinstance(v, dict) and isinstance(v.get("longitude"), (int, float)):
                pts[n] = float(v["longitude"])
        ang = ((nc.get("houses_and_angles") or {}).get("angles")) or {}
        for a in ("ASC", "MC"):
            if isinstance(ang.get(a), (int, float)):
                pts[a] = float(ang[a]); angles = True
        src_kind = "daily_feed.natal_chart"
    elif isinstance(d.get("positions"), dict):          # natal snapshot
        for n, v in d["positions"].items():
            if isinstance(v, dict) and isinstance(v.get("longitude"), (int, float)):
                pts[n] = float(v["longitude"])
        src_kind = "natal_snapshot.positions"
    else:                                               # generic
        raw = d.get("points", d)
        for n, v in raw.items():
            if isinstance(v, (int, float)):
                pts[n] = float(v)
            elif isinstance(v, dict) and isinstance(v.get("longitude"), (int, float)):
                pts[n] = float(v["longitude"])
        angles = "ASC" in pts or "MC" in pts
        src_kind = "generic_points"
    # Defaults: Mean_Node excluded (SPEC §4.2); South_Node is the mirror of True_Node
    # (conj/opp to True_Node already cover it); DSC/IC mirror ASC/MC (deduplicated).
    for n in ("Mean_Node", "South_Node", "DSC", "IC"):
        pts.pop(n, None)
    if include:
        pts = {k: v for k, v in pts.items() if k in include}
    try:
        rel = str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        rel = Path(path).name
    return {"label": reference_label, "source_file": rel, "source_kind": src_kind,
            "angles_available": angles, "points": {k: norm360(v) for k, v in pts.items()}}


# ---------------------------------------------------------------- classes / orbs
def body_class(name: str, rules: Dict[str, Any], category: str) -> str:
    bc = rules["body_classes"]
    for cls in ("LUMINARY", "PERSONAL", "SOCIAL", "OUTER", "NODE", "CHIRON_MAJOR", "CATALOG_MINOR", "AETHER"):
        if name in bc[cls]:
            return cls
    if category == "fixed_stars":
        return "FIXED_STAR"
    if name in ("Mean_Node", "South_Node"):
        return "NODE_EXCLUDED"
    return "OTHER_MINOR"


def class_orbs(cls: str, name: str, rules: Dict[str, Any]) -> Dict[str, float]:
    t = rules["aspects_orbs"]["transit_to_natal_orbs_deg"]["table"]
    if cls == "LUMINARY" and name == "Sun":
        row = t["Sun, Mercury, Venus, Mars"]
    elif cls == "PERSONAL":
        row = t["Sun, Mercury, Venus, Mars"]
    elif cls == "SOCIAL":
        row = t["Jupiter, Saturn"]
    elif cls == "OUTER":
        row = t["Uranus, Neptune, Pluto"]
    elif cls == "NODE":
        row = t["NODE"]
    elif cls == "CHIRON_MAJOR":
        row = t["CHIRON_MAJOR"]
    elif cls == "CATALOG_MINOR":
        return {"conjunction": 1.0, "opposition": 1.0}
    elif cls == "OTHER_MINOR":
        return {"conjunction": 0.5, "opposition": 0.5}
    elif cls == "AETHER":
        row = t["AETHER"]
    else:
        return {}
    out = {}
    for asp, key in ORB_KEY.items():
        v = row.get(key)
        if isinstance(v, (int, float)):
            out[asp] = float(v)
    return out  # minor aspects are off by default (aspects_orbs.aspect_set.minor_off_by_default)


# ---------------------------------------------------------------- interpolation helpers
def _quad_root(y: Tuple[float, float, float], lo: float, hi: float) -> Optional[float]:
    """Root of the parabola through (0,y0),(1,y1),(2,y2) inside [lo,hi]."""
    y0, y1, y2 = y
    a = (y0 - 2 * y1 + y2) / 2.0
    b = y1 - y0 - a
    c = y0
    if abs(a) < 1e-12:
        return -c / b if b != 0 and lo <= -c / b <= hi else None
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    r = [(-b + s * math.sqrt(disc)) / (2 * a) for s in (1, -1)]
    r = [x for x in r if lo - 1e-9 <= x <= hi + 1e-9]
    return min(r, key=lambda x: abs(x - (lo + hi) / 2)) if r else None


def _root_between(f: List[float], i: int, slow: bool) -> Tuple[float, str]:
    """Fractional sample index of a sign change between i and i+1."""
    lin = i + f[i] / (f[i] - f[i + 1])
    if slow and len(f) >= 3:
        j = i - 1 if i >= 1 else i
        if j + 2 >= len(f):
            j = len(f) - 3
        r = _quad_root((f[j], f[j + 1], f[j + 2]), i - j, i - j + 1)
        if r is not None:
            return j + r, "quadratic (|speed| < 0.05 deg/day near station)"
    return lin, "linear"


def _at(times: List[datetime], x: float) -> datetime:
    i = int(math.floor(x))
    i = max(0, min(len(times) - 1, i))
    return times[i] + timedelta(days=x - i)


def _interp(vals: List[float], x: float, circular: bool = False) -> float:
    i = max(0, min(len(vals) - 2, int(math.floor(x))))
    fr = x - i
    if circular:
        return norm360(vals[i] + wrap180(vals[i + 1] - vals[i]) * fr)
    return vals[i] + (vals[i + 1] - vals[i]) * fr


# ---------------------------------------------------------------- core series
def _series_for_signature(T: str, N: str, asp: str, side: int, orb: float, LT: List[float], SP: List[Optional[float]],
                          lamN: float, times: List[datetime], stations: List[Dict[str, Any]],
                          rules: Dict[str, Any], eps_exact: float, max_step: float) -> Optional[Dict[str, Any]]:
    A = ASPECTS[asp]
    f = [wrap180(l - lamN - side * A) for l in LT]
    n = len(f)
    inside = [abs(x) <= orb for x in f]
    if not any(inside):
        return None
    point = norm360(lamN + side * A)
    # windows
    wins = []
    i = 0
    while i < n:
        if inside[i]:
            j = i
            while j + 1 < n and inside[j + 1]:
                j += 1
            wins.append((i, j))
            i = j + 1
        else:
            i += 1

    def motion_at(x: float) -> str:
        fv = _interp(f, x)
        sv = SP[max(0, min(n - 1, int(round(x))))]
        if sv is None:
            return "unresolved"
        if abs(fv) <= eps_exact:
            return "exact"
        return "applying" if fv * sv < 0 else "separating"

    def crossing(a: int, b: int) -> float:
        # fractional index where |f| == orb between samples a (one side) and b
        fa, fb = f[a], f[b]
        target = orb if (fa if abs(fa) > orb else fb) > 0 else -orb
        if fb == fa:
            return float(b)
        return a + (target - fa) / (fb - fa)

    windows = []
    hits_all = []
    for (a, b) in wins:
        entry_open = a == 0
        exit_open = b == n - 1
        ex = a if entry_open else crossing(a - 1, a)
        xx = b if exit_open else crossing(b, b + 1)
        hits = []
        lo, hi = max(0, a - 1), min(n - 2, b)
        for k in range(lo, hi + 1):
            if ((f[k] < 0 <= f[k + 1]) or (f[k] > 0 >= f[k + 1])) and abs(f[k] - f[k + 1]) < max_step:
                slow = any(s is not None and abs(s) < 0.05 for s in (SP[k], SP[k + 1]))
                x, meth = _root_between(f, k, slow)
                spd = _interp([s if s is not None else 0.0 for s in SP], x)
                hits.append({"timestamp_utc": _iso(_at(times, x)), "x": x,
                             "transit_longitude": _interp(LT, x, circular=True),
                             "speed_deg_per_day": spd, "direction": "retrograde" if spd < 0 else "direct",
                             "interpolation": meth})
        near = None
        in_orb_no_exact = False
        if not hits:
            k = min(range(a, b + 1), key=lambda q: abs(f[q]))
            if 0 < k < n - 1 and abs(f[k]) <= abs(f[k - 1]) and abs(f[k]) <= abs(f[k + 1]):
                near = {"timestamp_utc": _iso(times[k]), "min_abs_orb_deg": abs(f[k]),
                        "classification": "NEAR_MISS (touch: local min |f| <= orb without sign change; not a hit)"}
            else:
                in_orb_no_exact = True  # minimum at the horizon edge: not a near miss
        st_inv = []
        t_entry, t_exit = _at(times, ex), _at(times, xx)
        for s in stations:
            if s["body"] != T:
                continue
            ts = _parse(s["timestamp_utc"])
            if t_entry <= ts <= t_exit:
                st_inv.append({"station_type": s["station_type"], "timestamp_utc": s["timestamp_utc"],
                               "longitude": s["longitude"],
                               "station_on_point": abs(wrap180(s["longitude"] - point)) <= 1.5})
        windows.append({
            "entry_utc": _iso(t_entry) if not entry_open else None,
            "entry_open_before_range": entry_open,
            "exit_utc": _iso(t_exit) if not exit_open else None,
            "exit_open_after_range": exit_open,
            "entry_motion": motion_at(ex if not entry_open else a),
            "exit_motion": motion_at(xx if not exit_open else b),
            "min_abs_orb_deg": min(abs(f[q]) for q in range(a, b + 1)),
            "exact_hits": [{k2: v for k2, v in h.items() if k2 != "x"} for h in hits],
            "near_miss": near,
            "in_orb_no_exact_within_horizon": in_orb_no_exact,
            "station_involvement": st_inv,
        })
        hits_all.extend(hits)
    # pass numbering
    hits_all.sort(key=lambda h: h["x"])
    pn = {h["timestamp_utc"]: idx + 1 for idx, h in enumerate(hits_all)}
    for w in windows:
        for h in w["exact_hits"]:
            h["pass_number"] = pn[h["timestamp_utc"]]
    state0 = motion_at(0) if inside[0] else "not_in_orb"
    return {
        "transit_body": T, "natal_point": N, "aspect": asp, "aspect_angle": A, "side": side,
        "aspect_point_longitude": point, "orb_deg": orb,
        "entry_utc": windows[0]["entry_utc"], "entry_open_before_range": windows[0]["entry_open_before_range"],
        "exit_utc": windows[-1]["exit_utc"], "exit_open_after_range": windows[-1]["exit_open_after_range"],
        "exact_pass_count": len(hits_all),
        "exact_passes_utc": [h["timestamp_utc"] for h in hits_all],
        "multi_pass": len(hits_all) >= 2,
        "window_count": len(windows),
        "recurring_activation": len(windows) >= int(rules["documented_parameters"]["recurring_activation_min_windows"]["value"]),
        "retrograde_multi_pass": len(hits_all) >= 2 and any(h["direction"] == "retrograde" for h in hits_all),
        "near_miss": any(w["near_miss"] for w in windows),
        "station_involved": any(w["station_involvement"] for w in windows),
        "station_on_point": any(s["station_on_point"] for w in windows for s in w["station_involvement"]),
        "motion_at_range_start": state0,
        "return": (T == N and asp == "conjunction"),
        "cycle_checkpoint": (T == N and asp in ("square", "opposition")),
        "windows": windows,
    }


def run_transit_to_natal(payload: Dict[str, Any], derived: Dict[str, Any], natal: Dict[str, Any],
                         rules: Dict[str, Any], source_file: str, derived_file: str) -> Dict[str, Any]:
    keys = derived["sample_date_keys"]
    times = [_parse(t) for t in derived["sample_timestamps_utc"]]
    bodies = derived["bodies"]
    stations = derived["stations"]
    params = rules["documented_parameters"]
    adequacy = params["sampling_adequacy_max_daily_step_deg"]["value"]
    max_step = params["exact_hit_max_step_deg"]["value"]
    eps_exact = 0.1  # aspects_orbs.motion.EXACT |f| <= 0.1
    series: List[Dict[str, Any]] = []
    skipped: Dict[str, str] = {}

    def lon_series(name):
        return [float((payload["transits"][k].get(name) or {}).get("ecl_lon_deg")) for k in keys]

    for T, b in bodies.items():
        cls = body_class(T, rules, b["category"])
        if cls == "FIXED_STAR":
            skipped[T] = "fixed star: not a transit series (static over horizon)"; continue
        if cls == "NODE_EXCLUDED":
            skipped[T] = "Mean_Node excluded by default / South_Node covered by True_Node conj-opp"; continue
        if T == "Moon":
            skipped[T] = "Moon orbs are DAILY-only (orb table); use daily/weekly 6h snapshots for Moon timing"; continue
        if (b.get("max_abs_daily_step_deg") or 0) >= adequacy:
            skipped[T] = f"sampling_insufficient: max daily step {b['max_abs_daily_step_deg']:.2f} deg >= {adequacy} (documented parameter)"; continue
        orbs = class_orbs(cls, T, rules)
        LT = lon_series(T)
        SP = b["speed_deg_per_day"]
        for N, lamN in natal["points"].items():
            for asp, orb in orbs.items():
                o = orb + (0.5 if N in BONUS_TARGETS else 0.0)
                sides = (1,) if asp in ("conjunction", "opposition") else (1, -1)
                for s in sides:
                    r = _series_for_signature(T, N, asp, s, o, LT, SP, lamN, times, stations, rules, eps_exact, max_step)
                    if r:
                        r["transit_class"] = cls
                        r["provenance"] = {"positions": source_file, "speeds": derived_file,
                                           "speed_source": "six_month_central_difference",
                                           "rules": "config/transit_to_natal_rules.json (aspects_orbs from luminous_gate_reconstruction.json)",
                                           "known_defect": ("Aetheric_SunMoon_Midpoint is computed as Sun+Moon (a sum, not a midpoint); used as coded (D-AETHER)"
                                                            if T == "Aetheric_SunMoon_Midpoint" else None)}
                        series.append(r)
    series.sort(key=lambda r: (r["exact_passes_utc"][0] if r["exact_passes_utc"] else (r["entry_utc"] or "0")))

    # ---- lunations / eclipse candidates
    sun, moon = lon_series("Sun"), lon_series("Moon")
    mlat = [float((payload["transits"][k].get("Moon") or {}).get("ecl_lat_deg")) for k in keys]
    lunations = []
    for kind, off in (("new_moon", 0.0), ("full_moon", 180.0)):
        D = [wrap180(m - s - off) for m, s in zip(moon, sun)]
        for i in range(len(D) - 1):
            if D[i] < 0 <= D[i + 1] and abs(D[i + 1] - D[i]) < 30:
                j = i - 1 if i >= 1 else i
                if j + 2 >= len(D):
                    j = len(D) - 3
                r = _quad_root((D[j], D[j + 1], D[j + 2]), i - j, i - j + 1)
                x = j + r if r is not None else i + D[i] / (D[i] - D[i + 1])
                t = _at(times, x)
                t_hour = (t + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
                lat = _interp(mlat, x)
                lon = norm360(_interp(moon, x, circular=True))
                lim = 1.6 if kind == "new_moon" else 1.1
                on_pts = []
                for N, lamN in natal["points"].items():
                    for asp, A, orb in (("conjunction", 0, 3.0), ("opposition", 180, 2.0), ("square", 90, 2.0)):
                        if abs(abs(wrap180(lon - lamN)) - A) <= orb:
                            on_pts.append({"natal_point": N, "aspect": asp, "orb": abs(abs(wrap180(lon - lamN)) - A)})
                lunations.append({"type": kind, "timestamp_utc_rounded_hour": _iso(t_hour), "moon_longitude": lon,
                                  "moon_ecl_lat_deg": lat,
                                  "eclipse_candidate": abs(lat) < lim,
                                  "eclipse_rule": f"|Moon ecl_lat| < {lim} ('candidate' until an eclipse table is imported; D-ECLIPSE)",
                                  "on_natal_points": on_pts,
                                  "precision": "daily samples, quadratic root; rounded to the hour"})
    lunations.sort(key=lambda r: r["timestamp_utc_rounded_hour"])

    # ---- cycle phases (own natal position)
    cycles = []
    for T in natal["points"]:
        if T not in bodies or T in skipped or T in ("ASC", "MC"):
            continue
        LT = lon_series(T)
        lamN = natal["points"][T]
        node = T == "True_Node"
        ph = [norm360((lamN - l) if node else (l - lamN)) for l in LT]
        idx0 = int(ph[0] // 45)
        crossings = []
        for i in range(len(ph) - 1):
            a, b = ph[i], ph[i] + wrap180(ph[i + 1] - ph[i])
            for kb in range(-8, 9):
                bd = kb * 45.0 + 360.0 * math.floor(a / 360.0)
                if (a < bd <= b) or (b < bd <= a):
                    x = i + (bd - a) / (b - a)
                    crossings.append({"timestamp_utc": _iso(_at(times, x)),
                                      "boundary_deg": norm360(bd),
                                      "entering_phase": PHASES[int(norm360(bd if b > a else bd - 1e-9) // 45) % 8]})
        cycles.append({"body": T, "phase_at_range_start": PHASES[idx0], "phase_angle_at_range_start": ph[0],
                       "phase_boundary_crossings": crossings,
                       "rule": "phase = norm(lambda_T - lambda_N) (nodes: norm(lambda_N - lambda_T)); 8 phases of 45 degrees"})

    # ---- recurring activation + convergence (documented parameters)
    rec_min = params["recurring_activation_min_windows"]["value"]
    conv_min = params["convergence_min_simultaneous_windows"]["value"]
    recurring = [{"transit_body": r["transit_body"], "aspect": r["aspect"], "side": r["side"],
                  "natal_point": r["natal_point"], "window_count": len(r["windows"]),
                  "entries_utc": [w["entry_utc"] for w in r["windows"]]}
                 for r in series if len(r["windows"]) >= rec_min]
    conv_classes = set(params["convergence_min_simultaneous_windows"].get("classes", []))
    day_bodies: Dict[str, List[set]] = {N: [set() for _ in keys] for N in natal["points"]}
    for r in series:
        if r["transit_class"] not in conv_classes:
            continue
        A, N = r["aspect_angle"], natal["points"][r["natal_point"]]
        LT = lon_series(r["transit_body"])
        for i, l in enumerate(LT):
            if abs(wrap180(l - N - r["side"] * A)) <= r["orb_deg"]:
                day_bodies[r["natal_point"]][i].add(r["transit_body"])
    conv = []
    for Np, db in day_bodies.items():
        i = 0
        while i < len(keys):
            if len(db[i]) >= conv_min:
                j = i
                while j + 1 < len(keys) and len(db[j + 1]) >= conv_min:
                    j += 1
                peak = max(range(i, j + 1), key=lambda q: len(db[q]))
                conv.append({"natal_point": Np, "start_sample_utc": _iso(times[i]), "end_sample_utc": _iso(times[j]),
                             "peak_sample_utc": _iso(times[peak]), "peak_body_count": len(db[peak]),
                             "peak_bodies": sorted(db[peak]),
                             "classification": "candidate (D-CONVERGENCE: 'unique signal' undefined)"})
                i = j + 1
            else:
                i += 1
    conv.sort(key=lambda c: c["start_sample_utc"])

    hits = sum(r["exact_pass_count"] for r in series)
    return {
        "engine_version": ENGINE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "natal_input": {k: natal[k] for k in ("label", "source_file", "source_kind", "angles_available")},
        "natal_points_used": sorted(natal["points"]),
        "data_role": "reference/test validation of the generic engine; not personal evidence; no birth details restated",
        "source_feed": source_file,
        "derived_layer": derived_file,
        "horizon_utc": [derived["sample_timestamps_utc"][0], derived["sample_timestamps_utc"][-1]],
        "rules": {
            "orbs": "aspects_orbs.transit_to_natal_orbs_deg (+0.5 for natal Sun/Moon/ASC/MC)",
            "aspects": "major + quincunx; minor off by default",
            "f": rules["aspects_orbs"]["motion"]["f"],
            "exact": "|f| <= 0.1", "applying": "f*speed < 0", "separating": "f*speed > 0",
            "hit": "f(t_i)*f(t_i+1) <= 0 and |f_i - f_i+1| < 30; linear, quadratic near stations (|speed| < 0.05)",
            "near_miss": "local min |f| <= orb without sign change",
            "documented_parameters": params,
        },
        "skipped_transiting_bodies": skipped,
        "summary": {
            "transit_series": len(series),
            "exact_hits": hits,
            "windows": sum(len(r["windows"]) for r in series),
            "multi_pass_series": sum(1 for r in series if r["multi_pass"]),
            "retrograde_multi_pass_series": sum(1 for r in series if r["retrograde_multi_pass"]),
            "near_miss_series": sum(1 for r in series if r["near_miss"]),
            "station_involved_series": sum(1 for r in series if r["station_involved"]),
            "station_on_point_series": sum(1 for r in series if r["station_on_point"]),
            "returns": sum(1 for r in series if r["return"]),
            "cycle_checkpoint_series": sum(1 for r in series if r["cycle_checkpoint"]),
            "lunations": len(lunations),
            "eclipse_candidates": sum(1 for l in lunations if l["eclipse_candidate"]),
            "lunations_on_natal_points": sum(1 for l in lunations if l["on_natal_points"]),
            "recurring_activation_series": len(recurring),
            "candidate_convergence_windows": len(conv),
            "series_by_class": {c: sum(1 for r in series if r["transit_class"] == c) for c in sorted({r["transit_class"] for r in series})},
        },
        "transit_series": series,
        "lunations": lunations,
        "cycle_phases": cycles,
        "recurring_activation": recurring,
        "candidate_convergence_windows": conv,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Generic transit-to-natal engine (six-month series)")
    ap.add_argument("sixmonth")
    ap.add_argument("derived")
    ap.add_argument("natal", help="daily feed (natal_chart), natal snapshot, or generic {points:{name:lon}}")
    ap.add_argument("--label", default="user-supplied natal chart")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    payload = json.loads(Path(a.sixmonth).read_text(encoding="utf-8"))
    derived = json.loads(Path(a.derived).read_text(encoding="utf-8"))
    natal = load_natal(Path(a.natal), a.label)
    rep = run_transit_to_natal(payload, derived, natal, load_rules(), a.sixmonth, a.derived)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(rep["summary"], indent=1))


if __name__ == "__main__":
    main()
