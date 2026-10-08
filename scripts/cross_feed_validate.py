#!/usr/bin/env python3
"""Cross-feed comparison at the daily feed's exact timestamp.

Compares Daily (ZodiacOracle.DailyTransit.v3), Current week
(ZodiacOracle.LiveTransit.vHybrid.multiSnap6h) and Six-month
(ZodiacOracle.SixMonthTransit.v3) positions and speeds for the same instant.
Weekly and six-month data are interpolated to the daily timestamp (3-point
Lagrange on unwrapped longitudes); raw nearest-sample and interpolated
differences are both reported. Disagreements are NEVER averaged; each one gets
a cause: timestamp difference, interpolation, provider difference, fixed-star
catalog, or derived vs direct speed.
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
CORE = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto",
        "True_Node", "Chiron", "Ceres", "Pallas", "Juno", "Vesta"]
AETHER = ["Aetheric_SunMoon_Midpoint", "Aetheric_Jovian_Arc", "Aetheric_Elemental_Balance"]
POS_TOL_DEG = 0.0005      # documented: 1.8 arcsec agreement tolerance after interpolation
SPEED_TOL = 0.005         # documented: deg/day agreement tolerance for speeds (Moon: 0.05)


def wrap180(x: float) -> float:
    return ((x + 180.0) % 360.0 + 360.0) % 360.0 - 180.0


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def load(src: str) -> Dict[str, Any]:
    if src.startswith("http"):
        with urllib.request.urlopen(src, timeout=60) as r:
            return json.loads(r.read().decode())
    return json.loads(Path(src).read_text(encoding="utf-8"))


def lagrange3(ts: List[datetime], vals: List[float], t: datetime) -> Tuple[float, float]:
    """Quadratic (3 nearest samples) and linear interpolation of an angle."""
    idx = sorted(range(len(ts)), key=lambda i: abs((ts[i] - t).total_seconds()))[:3]
    idx.sort()
    base = vals[idx[0]]
    xs = [(ts[i] - t).total_seconds() / 86400 for i in idx]
    ys = [base + wrap180(vals[i] - base) for i in idx]
    q = 0.0
    for j in range(3):
        lj = 1.0
        for m in range(3):
            if m != j:
                lj *= (0 - xs[m]) / (xs[j] - xs[m])
        q += ys[j] * lj
    # linear between bracketing samples
    lo = max(i for i in range(len(ts)) if ts[i] <= t)
    hi = min(lo + 1, len(ts) - 1)
    fr = (t - ts[lo]).total_seconds() / max(1.0, (ts[hi] - ts[lo]).total_seconds())
    lin = vals[lo] + wrap180(vals[hi] - vals[lo]) * fr
    return q % 360.0, lin % 360.0


def nearest(ts: List[datetime], vals: List[float], t: datetime) -> Tuple[float, float, str]:
    i = min(range(len(ts)), key=lambda k: abs((ts[k] - t).total_seconds()))
    return vals[i], (ts[i] - t).total_seconds() / 3600.0, ts[i].strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", required=True)
    ap.add_argument("--weekly", required=True)
    ap.add_argument("--weekly-derived", required=True)
    ap.add_argument("--sixmonth", required=True)
    ap.add_argument("--sixmonth-derived", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    daily, weekly, wder = load(a.daily), load(a.weekly), load(a.weekly_derived)
    six, sder = load(a.sixmonth), load(a.sixmonth_derived)
    t = parse(daily["generated_at_utc"])
    tp = daily["transit_positions"]
    stars = sorted(n for n, v in tp.items() if v.get("category") == "fixed_stars")
    bodies = CORE + AETHER + stars
    w_slots = wder["snapshot_timestamps_utc"]
    w_ts = [parse(s) for s in w_slots]
    s_ts = [parse(s) for s in sder["sample_timestamps_utc"]]
    s_keys = sder["sample_date_keys"]
    rows = []
    for n in bodies:
        d = tp[n]
        dl = d["longitude"]
        wb = weekly["bodies"].get(n)
        wv = [wb["snapshots"][s] for s in w_slots]
        sv = [six["transits"][k][n]["ecl_lon_deg"] for k in s_keys]
        w_raw, w_dt, w_at = nearest(w_ts, wv, t)
        s_raw, s_dt, s_at = nearest(s_ts, sv, t)
        w_q, w_lin = lagrange3(w_ts, wv, t)
        s_q, s_lin = lagrange3(s_ts, sv, t)
        # speeds
        ds = d.get("longitude_speed")
        wsp = wder["bodies"][n]["speed_deg_per_day"]
        ssp = sder["bodies"][n]["speed_deg_per_day"]
        w_speed = None
        if None not in wsp:
            lo = max(i for i in range(len(w_ts)) if w_ts[i] <= t)
            fr = (t - w_ts[lo]).total_seconds() / (w_ts[lo + 1] - w_ts[lo]).total_seconds()
            w_speed = wsp[lo] + (wsp[lo + 1] - wsp[lo]) * fr  # speeds are not angles: plain linear
        s_speed = None
        if None not in ssp:
            lo = max(i for i in range(len(s_ts)) if s_ts[i] <= t)
            fr = (t - s_ts[lo]).total_seconds() / 86400
            s_speed = ssp[lo] + (ssp[lo + 1] - ssp[lo]) * fr
        cat = d.get("category")
        srcs = {"daily": d.get("source"), "weekly": wb.get("source"),
                "six_month": six["transits"][s_keys[0]][n].get("source")}
        diffs = {
            "weekly_raw_nearest_minus_daily_deg": wrap180(w_raw - dl),
            "weekly_interp_minus_daily_deg": wrap180(w_q - dl),
            "weekly_linear_interp_minus_daily_deg": wrap180(w_lin - dl),
            "six_month_raw_nearest_minus_daily_deg": wrap180(s_raw - dl),
            "six_month_interp_minus_daily_deg": wrap180(s_q - dl),
            "six_month_linear_interp_minus_daily_deg": wrap180(s_lin - dl),
            "six_month_interp_minus_weekly_interp_deg": wrap180(s_q - w_q),
        }
        reasons = []
        raw_big = max(abs(diffs["weekly_raw_nearest_minus_daily_deg"]), abs(diffs["six_month_raw_nearest_minus_daily_deg"])) > POS_TOL_DEG
        res_w, res_s = abs(diffs["weekly_interp_minus_daily_deg"]), abs(diffs["six_month_interp_minus_daily_deg"])
        if raw_big:
            reasons.append(f"timestamp difference: nearest weekly sample {w_dt:+.2f} h, nearest six-month sample {s_dt:+.2f} h from the daily instant (removed by interpolation down to the residuals below)")
        for label, res, other_src in (("weekly", res_w, srcs["weekly"]), ("six_month", res_s, srcs["six_month"])):
            if res <= POS_TOL_DEG:
                continue
            if cat == "fixed_stars":
                reasons.append(f"fixed-star catalog: {label} residual {res*3600:.2f}\" (daily/six-month use data/fixed_star_catalog.json apparent-of-date; weekly uses Swiss sefstars)")
            elif cat == "aether_points":
                reasons.append(f"interpolation (+ provider of components): {label} residual {res*3600:.2f}\" — Aether formula point built from Sun/Moon/Jupiter etc.; "
                               + ("KNOWN DEFECT: 'SunMoon midpoint' is Sun+Moon (a sum), so it inherits the Moon's interpolation error; not fixed (D-AETHER)" if n == "Aetheric_SunMoon_Midpoint" else "non-linear formula is interpolated, not recomputed"))
            elif str(other_src).lower() == "swiss" and str(srcs["daily"]).lower() == "swiss":
                reasons.append(f"provider difference (same provider, different implementation): {label} residual {res*3600:.2f}\" — both Swiss Ephemeris, computed by different code/flags in each repo")
            elif str(other_src).lower() not in ("jpl", "horizons") or str(srcs["daily"]).lower() not in ("jpl", "horizons"):
                reasons.append(f"provider difference: {label} residual {res*3600:.2f}\" (daily={srcs['daily']}, {label}={other_src})")
            else:
                reasons.append(f"interpolation: {label} residual {res*3600:.2f}\" ({'6 h' if label == 'weekly' else '1 day'} sampling of a {'fast' if abs(ds or 0) > 2 else 'curving'} body)")
        speed_rows = {"daily_longitude_speed": ds, "weekly_6h_derived": w_speed, "six_month_derived": s_speed}
        stol = 0.05 if n == "Moon" else SPEED_TOL
        if cat == "fixed_stars":
            reasons.append("derived vs direct speed: daily fixed-star longitude_speed is a 0.0 catalog placeholder; derived series show apparent-of-date drift (precession + nutation + annual aberration, ~1e-4 deg/day or less); motion 'fixed', never a station")
        elif ds is None:
            reasons.append("derived vs direct speed: daily longitude_speed is null (unresolved, not fabricated); weekly/six-month derived speeds are the fallback")
        else:
            for label, v in (("weekly", w_speed), ("six_month", s_speed)):
                if v is not None and abs(v - ds) > stol:
                    reasons.append(f"derived vs direct speed: {label} finite-difference {v:+.5f} vs daily {ds:+.5f} deg/day (|diff| {abs(v-ds):.5f})")
        rows.append({
            "body": n, "category": cat, "sources": srcs,
            "daily_longitude": dl,
            "weekly": {"nearest_sample_utc": w_at, "nearest_offset_hours": w_dt, "raw_nearest": w_raw, "interpolated": w_q, "linear": w_lin},
            "six_month": {"nearest_sample_utc": s_at, "nearest_offset_hours": s_dt, "raw_nearest": s_raw, "interpolated": s_q, "linear": s_lin},
            "differences": diffs,
            "max_interp_residual_arcsec": max(res_w, res_s) * 3600,
            "speeds_deg_per_day": speed_rows,
            "agree_after_interpolation": max(res_w, res_s) <= POS_TOL_DEG,
            "reasons": reasons or ["agree within tolerance at every comparison"],
        })
    rows_sorted = sorted(rows, key=lambda r: -r["max_interp_residual_arcsec"])
    out = {
        "engine": "cross_feed_validation.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "comparison_instant_utc": daily["generated_at_utc"],
        "inputs": {"daily": a.daily, "weekly": a.weekly, "weekly_derived": a.weekly_derived,
                   "six_month": a.sixmonth, "six_month_derived": a.sixmonth_derived},
        "method": {
            "interpolation": "3-point Lagrange (quadratic) on unwrapped longitudes around the daily instant; linear also reported",
            "no_averaging": "disagreements are recorded per feed, never averaged",
            "authority": "daily position is authoritative for the instant; weekly/six-month never override it",
            "position_tolerance_deg": POS_TOL_DEG, "speed_tolerance_deg_per_day": SPEED_TOL, "moon_speed_tolerance": 0.05,
        },
        "summary": {
            "bodies_compared": len(rows),
            "agree_after_interpolation": sum(1 for r in rows if r["agree_after_interpolation"]),
            "largest_interp_residuals": [{"body": r["body"], "arcsec": round(r["max_interp_residual_arcsec"], 3), "reason": r["reasons"][-1] if len(r["reasons"]) else ""} for r in rows_sorted[:8]],
            "largest_raw_nearest_differences_deg": sorted(
                [{"body": r["body"], "weekly_raw_deg": round(r["differences"]["weekly_raw_nearest_minus_daily_deg"], 5),
                  "six_month_raw_deg": round(r["differences"]["six_month_raw_nearest_minus_daily_deg"], 5)} for r in rows],
                key=lambda x: -max(abs(x["weekly_raw_deg"]), abs(x["six_month_raw_deg"])))[:6],
        },
        "rows": rows,
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"{'body':28s} {'w_raw':>9s} {'w_int\"':>8s} {'6m_raw':>9s} {'6m_int\"':>8s}  first reason")
    for r in rows_sorted:
        dd = r["differences"]
        print(f"{r['body']:28s} {dd['weekly_raw_nearest_minus_daily_deg']:9.4f} {abs(dd['weekly_interp_minus_daily_deg'])*3600:8.2f} "
              f"{dd['six_month_raw_nearest_minus_daily_deg']:9.4f} {abs(dd['six_month_interp_minus_daily_deg'])*3600:8.2f}  {r['reasons'][-1][:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
