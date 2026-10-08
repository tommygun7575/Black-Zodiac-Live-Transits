#!/usr/bin/env python3
"""Validate station/motion rules in a generated daily feed.

Checks (2026-10-08 transit-workflow rules):
  * coverage: resolved == total, coverage == 1.0, no missing targets
  * no fixed star has station=true or motion_status='station'
  * every fixed star has motion_status='fixed' and station=false
  * no Aether point / Sun / Moon / node is a station event
  * null longitude_speed objects stay explicit: motion_status 'unresolved',
    retrograde null, motion_fallback_available listed (never fabricated)
  * stations.items lists only station-eligible bodies
  * major bodies: longitude_speed agrees with Swiss Ephemeris at the feed
    instant (|diff| <= 0.01 deg/day) and retrograde == (speed < 0)
  * calculated_harmonics scoped transit_to_transit_sky_geometry; natal blocks
    labelled reference_test_data

Writes a JSON report (optional --report) and exits 1 on any failure.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAJOR = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto"]
NON_STATION = {"Sun", "Moon", "True_Node", "Mean_Node", "South_Node"}
SPEED_TOL = 0.01


def _swiss_speeds(ts_iso: str):
    try:
        import swisseph as swe
    except Exception as exc:  # pragma: no cover
        return None, f"swisseph unavailable: {exc}"
    swe.set_ephe_path(str(ROOT / "ephe"))
    dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    jd = swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute / 60 + (dt.second + dt.microsecond / 1e6) / 3600)
    ids = {"Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY, "Venus": swe.VENUS, "Mars": swe.MARS,
           "Jupiter": swe.JUPITER, "Saturn": swe.SATURN, "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE,
           "Pluto": swe.PLUTO}
    out = {}
    for n, i in ids.items():
        xx, _ = swe.calc_ut(jd, i, swe.FLG_SWIEPH | swe.FLG_SPEED)
        out[n] = xx[3]
    return out, None


def validate(path: Path) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    tp = d["transit_positions"]
    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})

    check("coverage_78_of_78",
          d.get("resolved_targets") == d.get("total_targets") and d.get("coverage") == 1.0 and not d.get("missing"),
          f"{d.get('resolved_targets')}/{d.get('total_targets')} coverage={d.get('coverage')} missing={d.get('missing')}")
    stars = {n: v for n, v in tp.items() if v.get("category") == "fixed_stars"}
    star_station_true = sorted(n for n, v in stars.items() if v.get("station") is True)
    star_motion_station = sorted(n for n, v in stars.items() if v.get("motion_status") == "station")
    star_not_fixed = sorted(n for n, v in stars.items() if v.get("motion_status") != "fixed" or v.get("station") is not False)
    check("fixed_star_station_true_count_zero", not star_station_true, {"count": len(star_station_true), "bodies": star_station_true})
    check("fixed_star_motion_status_station_count_zero", not star_motion_station, {"count": len(star_motion_station)})
    check("fixed_stars_motion_fixed_station_false", not star_not_fixed, {"fixed_stars": len(stars), "violations": star_not_fixed})
    bad_non_station = sorted(n for n, v in tp.items()
                             if (v.get("category") in ("aether_points", "lunar_nodes") or n in NON_STATION) and v.get("station") is True)
    check("aether_sun_moon_nodes_never_station", not bad_non_station, {"violations": bad_non_station})
    null_speed = sorted(n for n, v in tp.items() if v.get("longitude_speed") is None)
    bad_null = sorted(n for n, v in tp.items() if v.get("longitude_speed") is None and not (
        v.get("motion_status") == "unresolved" and v.get("retrograde") is None
        and v.get("motion_fallback_available") == ["weekly_6h_difference", "six_month_series"]))
    lost_pos = sorted(n for n in null_speed if tp[n].get("longitude") is None)
    check("null_speed_explicit_unresolved_not_fabricated", not bad_null and not lost_pos,
          {"null_speed_count": len(null_speed), "violations": bad_null, "positions_dropped": lost_pos,
           "null_speed_bodies": null_speed})
    items = d.get("stations", {}).get("items", [])
    bad_items = sorted(i["body"] for i in items if i["body"] in NON_STATION or tp.get(i["body"], {}).get("category") in ("fixed_stars", "aether_points", "lunar_nodes"))
    check("stations_items_eligible_only", not bad_items and d.get("stations", {}).get("true_station_source") is False,
          {"items": [f"{i['body']}:{i['status']}" for i in items], "violations": bad_items})
    sw, err = _swiss_speeds(d["generated_at_utc"])
    major = {}
    major_ok = True
    for n in MAJOR:
        v = tp.get(n, {})
        s = v.get("longitude_speed")
        row = {"longitude_speed": s, "retrograde": v.get("retrograde"), "motion_status": v.get("motion_status")}
        ok = s is not None and v.get("retrograde") == (s < 0)
        if sw:
            row["swiss_speed"] = round(sw[n], 6)
            row["abs_diff"] = round(abs(sw[n] - s), 6) if s is not None else None
            ok = ok and s is not None and abs(sw[n] - s) <= SPEED_TOL and (sw[n] < 0) == (s < 0)
        major_ok &= ok
        major[n] = row
    check("major_body_speed_and_retrograde", major_ok and err is None, {"tolerance_deg_per_day": SPEED_TOL, "bodies": major, "error": err})
    harm = d.get("calculated_harmonics") or []
    check("harmonics_scoped_sky_geometry", all(h.get("scope") == "transit_to_transit_sky_geometry" for h in harm),
          {"rows": len(harm)})
    roles = {k: (d.get(k) or {}).get("data_role", "") for k in ("natal_chart", "houses_and_angles", "arabic_parts")}
    check("natal_blocks_reference_only", all(r.startswith("reference_test_data") for r in roles.values()), {"blocks": list(roles)})
    return {
        "file": str(path.relative_to(ROOT)) if path.is_absolute() and ROOT in path.parents else str(path),
        "engine_version": d.get("engine_version"),
        "generated_at_utc": d.get("generated_at_utc"),
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "all_passed": all(c["result"] == "PASS" for c in checks),
        "summary": {
            "coverage": d.get("coverage"),
            "resolved": f"{d.get('resolved_targets')}/{d.get('total_targets')}",
            "fixed_star_station_true": len(star_station_true),
            "fixed_star_motion_station": len(star_motion_station),
            "null_longitude_speed_count": len(null_speed),
            "null_longitude_speed_station_eligible": sum(1 for n in null_speed if tp[n].get("station_eligible")),
            "null_longitude_speed_aether": sum(1 for n in null_speed if tp[n].get("category") == "aether_points"),
            "daily_station_items": len(items),
        },
        "checks": checks,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("feed")
    ap.add_argument("--report")
    a = ap.parse_args()
    rep = validate(Path(a.feed).resolve())
    if a.report:
        Path(a.report).parent.mkdir(parents=True, exist_ok=True)
        Path(a.report).write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    for c in rep["checks"]:
        print(f"[{c['result']}] {c['check']}")
    print(json.dumps(rep["summary"]))
    return 0 if rep["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
