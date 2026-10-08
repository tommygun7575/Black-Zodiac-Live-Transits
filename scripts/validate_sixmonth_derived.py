#!/usr/bin/env python3
"""Validate the six-month derived layer against its raw feed.

Checks: raw feed hash unchanged; derived sample start == raw meta.range_utc[0]
(time of day preserved, not midnight); one speed per sample per body; edge
methods one-sided; derived speed agrees with Swiss Ephemeris λ̇ at sample
instants for Sun..Pluto (|diff| <= 0.02 deg/day; Mercury/Moon looser);
no station for excluded bodies; Swiss station cross-check all PASS; reference
transit-to-natal report present, contains no fixed-star series and only
uses aspects_orbs orbs. Writes a JSON report, exits 1 on failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sixmonth_derived import derived_paths, latest_raw, _parse_iso  # noqa: E402

TOL = {"Moon": 0.6, "Mercury": 0.05}
DEFAULT_TOL = 0.02


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", nargs="?")
    ap.add_argument("--report")
    a = ap.parse_args()
    raw_path = Path(a.raw).resolve() if a.raw else latest_raw()
    paths = derived_paths(raw_path)
    raw_bytes = raw_path.read_bytes()
    raw = json.loads(raw_bytes)
    der = json.loads(paths["derived"].read_text(encoding="utf-8"))
    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})

    check("raw_feed_unchanged_sha256", der.get("source_feed_sha256") == hashlib.sha256(raw_bytes).hexdigest(),
          {"sha256": hashlib.sha256(raw_bytes).hexdigest()})
    t0 = _parse_iso(raw["meta"]["range_utc"][0])
    s0 = _parse_iso(der["sample_timestamps_utc"][0])
    check("sample_start_preserves_actual_time", abs((s0 - t0).total_seconds()) < 1.0 and (t0.hour, t0.minute) != (0, 0) or t0 == s0,
          {"range_utc_start": raw["meta"]["range_utc"][0], "derived_first_sample": der["sample_timestamps_utc"][0]})
    check("date_keys_match_sample_dates", not der["date_key_mismatches"], {"mismatches": der["date_key_mismatches"][:5]})
    n = len(raw["transits"])
    bad_len = [b for b, v in der["bodies"].items() if len(v["speed_deg_per_day"]) != n]
    bad_edge = [b for b, v in der["bodies"].items() if v["speed_method"][0] != "forward_one_sided" or v["speed_method"][-1] != "backward_one_sided"]
    nulls = [b for b, v in der["bodies"].items() if any(x is None for x in v["speed_deg_per_day"])]
    check("speed_series_complete_central_with_one_sided_edges", not bad_len and not bad_edge and not nulls,
          {"bodies": len(der["bodies"]), "samples": n, "bad_length": bad_len, "bad_edges": bad_edge, "null_speeds": nulls})
    # Swiss λ̇ cross-check at sample instants
    sw_rows = {}
    ok_sw = True
    try:
        import swisseph as swe
        swe.set_ephe_path(str(ROOT / "ephe"))
        ids = {"Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY, "Venus": swe.VENUS, "Mars": swe.MARS,
               "Jupiter": swe.JUPITER, "Saturn": swe.SATURN, "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE, "Pluto": swe.PLUTO}
        for name, sid in ids.items():
            sp = der["bodies"][name]["speed_deg_per_day"]
            worst, sign_mismatch = 0.0, 0
            for i, ts in enumerate(der["sample_timestamps_utc"]):
                if i in (0, n - 1):
                    continue  # one-sided edges are O(h) — reported separately
                t = _parse_iso(ts)
                jd = swe.julday(t.year, t.month, t.day, t.hour + t.minute / 60 + t.second / 3600)
                v = swe.calc_ut(jd, sid, swe.FLG_SWIEPH | swe.FLG_SPEED)[0][3]
                worst = max(worst, abs(v - sp[i]))
                if abs(v) > 0.01 and (v < 0) != (sp[i] < 0):
                    sign_mismatch += 1
            tol = TOL.get(name, DEFAULT_TOL)
            sw_rows[name] = {"max_abs_diff_deg_per_day": round(worst, 5), "tolerance": tol, "direction_mismatches": sign_mismatch}
            ok_sw &= worst <= tol and sign_mismatch == 0
    except Exception as exc:
        ok_sw = False
        sw_rows["error"] = str(exc)
    check("derived_speed_vs_swiss_interior_samples", ok_sw, sw_rows)
    excl = [s for s in der["stations"] if not der["bodies"][s["body"]]["station_eligible"]]
    stars = [s for s in der["stations"] if der["bodies"][s["body"]]["category"] in ("fixed_stars", "aether_points", "lunar_nodes")]
    check("no_station_for_excluded_bodies", not excl and not stars, {"stations": len(der["stations"])})
    xc = der.get("station_swiss_crosscheck", [])
    check("station_swiss_crosscheck_all_pass", bool(xc) and all(x.get("result") == "PASS" for x in xc),
          {"pass": sum(1 for x in xc if x.get("result") == "PASS"), "total": len(xc),
           "max_abs_time_diff_hours": max((abs(x.get("time_diff_hours", 0)) for x in xc), default=None)})
    rep_path = paths["natal_reference"]
    if rep_path.exists():
        rep = json.loads(rep_path.read_text(encoding="utf-8"))
        fs = [s for s in rep["transit_series"] if s["transit_class"] == "FIXED_STAR"]
        bad_orb = [s for s in rep["transit_series"] if s["orb_deg"] not in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5)]
        check("transit_to_natal_reference_report", rep["summary"]["transit_series"] > 0 and not fs and not bad_orb,
              {"file": str(rep_path.relative_to(ROOT)), "summary": rep["summary"], "fixed_star_series": len(fs),
               "orbs_outside_table": len(bad_orb)})
    else:
        check("transit_to_natal_reference_report", False, {"missing": str(rep_path)})
    out = {
        "raw_file": str(raw_path.relative_to(ROOT)),
        "derived_file": str(paths["derived"].relative_to(ROOT)),
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "all_passed": all(c["result"] == "PASS" for c in checks),
        "stations": [{k: s[k] for k in ("body", "station_type", "timestamp_utc", "longitude")} for s in der["stations"]],
        "checks": checks,
    }
    stem = paths["derived"].stem.replace("sixmonth_derived_", "")
    rp = Path(a.report) if a.report else ROOT / "docs" / "derived" / f"sixmonth_validation_{stem}.json"
    rp.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for c in checks:
        print(f"[{c['result']}] {c['check']}")
    print(f"report: {rp}")
    return 0 if out["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
