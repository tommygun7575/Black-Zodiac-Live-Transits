"""Offline validation of the reconstructed natal datasets (natal_charts/, config natal records).

Recomputes with Swiss Ephemeris (repo ephe/) and repo helper functions; no network.
Authoritative birth table: user-supplied 2026-10-09 (local clock time at birthplace).
"""
import json
import math
import unittest
from datetime import datetime
from itertools import combinations
from pathlib import Path
from zoneinfo import ZoneInfo

import swisseph as swe

ROOT = Path(__file__).resolve().parents[1]
swe.set_ephe_path(str(ROOT / "ephe"))

AUTHORITATIVE = {
    "Tommy": ("1975-09-12", "09:20", "America/New_York", "1975-09-12T13:20:00Z", True, "Bronx"),
    "Milena": ("1992-03-29", "09:14", "America/Los_Angeles", "1992-03-29T17:14:00Z", False, "Carson City"),
    "Trinity": ("2002-03-28", "07:17", "America/Los_Angeles", "2002-03-28T15:17:00Z", False, "Carson City"),
    "Christine": ("1989-07-05", "15:01", "America/New_York", "1989-07-05T19:01:00Z", True, "Islip"),
}
SE_BODIES = {"Sun": 0, "Moon": 1, "Mercury": 2, "Venus": 3, "Mars": 4, "Jupiter": 5, "Saturn": 6, "Uranus": 7,
             "Neptune": 8, "Pluto": 9, "Chiron": 15, "Pholus": 16, "Ceres": 17, "Pallas": 18, "Juno": 19, "Vesta": 20}


def w180(x):
    return (x + 180.0) % 360.0 - 180.0


def sep(a, b):
    return abs(w180(a - b))


def load(p):
    return json.loads((ROOT / "natal_charts" / f"{p}_natal_snapshot.json").read_text(encoding="utf-8"))


class NatalReconstructionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = {p: load(p) for p in AUTHORITATIVE}
        cls.ks = json.loads((ROOT / "config/natal/3_combined_kitchen_sink.json").read_text(encoding="utf-8"))
        cls.profiles = json.loads((ROOT / "config/natal_profiles.json").read_text(encoding="utf-8"))
        cls.live = json.loads((ROOT / "config/live_config.json").read_text(encoding="utf-8"))

    # ---------------------------------------------------------------- birth data
    def test_birth_utc_dst_and_jd(self):
        for p, (date, time, tz, utc, dst, place) in AUTHORITATIVE.items():
            d = self.snap[p]
            local = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tz))
            u = local.astimezone(ZoneInfo("UTC"))
            self.assertEqual(u.strftime("%Y-%m-%dT%H:%M:%SZ"), utc, p)
            self.assertEqual(bool(local.dst()), dst, p)
            self.assertEqual(d["birth_timestamp_utc"], utc, p)
            b = d["birth"]
            self.assertEqual((b["date"], b["time_local"], b["timezone"]), (date, time, tz), p)
            self.assertIn(place, b["place_name"], p)
            self.assertEqual(b["dst_in_effect"], dst, p)
            jd = swe.julday(u.year, u.month, u.day, u.hour + u.minute / 60.0)
            self.assertAlmostEqual(b["julian_day_ut"], jd, places=6)

    def test_all_records_agree(self):
        live = {c["name"]: c for c in self.live["natal_charts"]}
        for p, (date, time, tz, utc, dst, place) in AUTHORITATIVE.items():
            b = self.snap[p]["birth"]
            prof = self.profiles[p]
            self.assertEqual(datetime.strptime(prof["birth_date"] + " " + prof["birth_time"], "%m-%d-%Y %I:%M %p"),
                             datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M"), p)
            self.assertEqual(prof["timezone"], tz)
            self.assertIn(place.split()[0], prof["birth_place"])
            self.assertEqual((live[p]["date"], live[p]["time"], live[p]["timezone"]), (date, time, tz), p)
            kb = self.ks[p]["birth"]
            self.assertEqual((kb["date"], kb["time"], kb["tz"]), (date, time, tz), p)
            for rec in ((prof["latitude"], prof["longitude"]), (live[p]["lat"], live[p]["lon"]), (kb["lat"], kb["lon"])):
                self.assertAlmostEqual(rec[0], b["latitude"], places=6)
                self.assertAlmostEqual(rec[1], b["longitude"], places=6)
        obs = json.loads((ROOT / "config/natal_observer.json").read_text())
        self.assertEqual(obs["birth"]["datetime_utc_iso"], AUTHORITATIVE["Tommy"][3])
        self.assertEqual(obs["birth"]["timezone"], "America/New_York")
        # Tommy: never Pacific time / Spanish Springs for the birth
        for rec in (self.profiles["Tommy"], self.ks["Tommy"]["birth"], live["Tommy"], self.snap["Tommy"]["birth"]):
            self.assertNotIn("Los_Angeles", json.dumps(rec))
            self.assertNotIn("Spanish", json.dumps(rec))

    # ---------------------------------------------------------------- positions
    def test_bodies_vs_swiss(self):
        for p, d in self.snap.items():
            jd = d["birth"]["julian_day_ut"]
            for name, code in SE_BODIES.items():
                pos = d["positions"][name]
                ref = swe.calc_ut(jd, code, swe.FLG_SWIEPH | swe.FLG_SPEED)[0]
                tol = 0.05 if name == "Moon" else 0.01
                self.assertLessEqual(sep(pos["longitude"], ref[0]), tol, f"{p} {name}")
                self.assertEqual(pos["retrograde"], ref[3] < 0, f"{p} {name} retrograde")

    def test_nodes_lilith(self):
        for p, d in self.snap.items():
            jd = d["birth"]["julian_day_ut"]; P = d["positions"]
            self.assertLessEqual(sep(P["True_Node"]["longitude"], swe.calc_ut(jd, swe.TRUE_NODE)[0][0]), 0.01)
            self.assertLessEqual(sep(P["Mean_Node"]["longitude"], swe.calc_ut(jd, swe.MEAN_NODE)[0][0]), 0.01)
            self.assertLessEqual(sep(P["South_Node"]["longitude"], P["True_Node"]["longitude"] + 180.0), 1e-9)
            self.assertLessEqual(sep(P["Lilith"]["longitude"], swe.calc_ut(jd, swe.MEAN_APOG)[0][0]), 0.01)

    def test_houses_and_angles_placidus(self):
        for p, d in self.snap.items():
            b = d["birth"]
            cusps, ascmc = swe.houses(b["julian_day_ut"], b["latitude"], b["longitude"], b"P")
            h = d["houses_and_angles"]
            self.assertEqual(h["system"], "P")
            for i in range(12):
                self.assertLessEqual(sep(h["cusps"][f"House_{i + 1}"], cusps[i]), 0.1, f"{p} cusp {i + 1}")
            A = h["angles"]
            for k, ref in (("ASC", ascmc[0]), ("MC", ascmc[1]), ("DSC", ascmc[0] + 180), ("IC", ascmc[1] + 180), ("Vertex", ascmc[3])):
                self.assertLessEqual(sep(A[k], ref), 0.1, f"{p} {k}")
                self.assertLessEqual(sep(d["positions"][k]["longitude"], ref), 0.1, f"{p} {k} position")

    def test_house_assignment_and_kitchen_sink(self):
        from scripts.utils.houses_parts import house_number_for_longitude
        signs = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius",
                 "Capricorn", "Aquarius", "Pisces"]
        keymap = {"Node": "True_Node"}
        for p, d in self.snap.items():
            cusps = [d["houses_and_angles"]["cusps"][f"House_{i}"] for i in range(1, 13)]
            ks = self.ks[p]["planets"]
            for k, e in ks.items():
                if k == "Fortune":
                    lon = d["arabic_parts"]["parts"]["Part_of_Fortune"]["longitude"]
                else:
                    lon = d["positions"][keymap.get(k, k)]["longitude"]
                ks_lon = signs.index(e["sign"]) * 30 + e["degree"]
                self.assertLessEqual(sep(ks_lon, lon), 0.006, f"{p} {k}")
                if "house" in e:
                    self.assertEqual(e["house"], house_number_for_longitude(lon, cusps), f"{p} {k} Placidus house")
            # no duplicated values between distinct KS points (e.g. Node == ASC)
            vals = [(signs.index(e["sign"]) * 30 + e["degree"], k) for k, e in ks.items()]
            for (a, ka), (b2, kb) in combinations(vals, 2):
                self.assertGreater(sep(a, b2), 1e-9, f"{p} duplicate value {ka}/{kb}")

    def test_arabic_parts(self):
        for p, d in self.snap.items():
            A = d["houses_and_angles"]["angles"]["ASC"]; P = d["positions"]
            S, M, V = P["Sun"]["longitude"], P["Moon"]["longitude"], P["Venus"]["longitude"]
            ap = d["arabic_parts"]
            day = P["Sun"]["house"] >= 7
            self.assertEqual(ap["sect"], "day" if day else "night")
            F = (A + M - S) if day else (A + S - M)
            Sp = (A + S - M) if day else (A + M - S)
            mid = S + w180(M - S) / 2.0                          # circular Sun/Moon midpoint
            K = A + mid
            exp = {"Part_of_Fortune": F, "Part_of_Spirit": Sp, "Part_of_Eros": A + M - V, "Part_of_Karma": K,
                   "Part_of_Treachery": A + M - K, "Part_of_Victory": A + S - K, "Part_of_Deliverance": A + Sp - F}
            for k, v in exp.items():
                self.assertLessEqual(sep(ap["parts"][k]["longitude"], v), 1e-6, f"{p} {k}")
            self.assertIsNone(ap["parts"]["Part_of_Necessity"]["longitude"])

    def test_fixed_stars_precessed_to_birth_date(self):
        for p, d in self.snap.items():
            jd = d["birth"]["julian_day_ut"]
            stars = {k: v for k, v in d["positions"].items() if v.get("category") == "fixed_stars"}
            self.assertEqual(len(stars), 19, p)
            for k, v in stars.items():
                ref = swe.fixstar2_ut(k, jd, swe.FLG_SWIEPH)[0][0]
                self.assertLessEqual(sep(v["longitude"], ref), 0.01, f"{p} {k}")
        # 1975 chart must not carry J2000 star longitudes (~0.34 deg precession)
        reg = self.snap["Tommy"]["positions"]["Regulus"]["longitude"]
        self.assertGreater(sep(reg, 149.8291), 0.3)

    def test_aspects_geometry(self):
        for p, d in self.snap.items():
            pos = d["positions"]
            self.assertGreater(len(d["aspects"]), 0)
            for a in d["aspects"]:
                s = sep(pos[a["body_a"]]["longitude"], pos[a["body_b"]]["longitude"])
                self.assertAlmostEqual(s, a["separation"], places=6)
                self.assertLessEqual(abs(s - a["exact_angle"]), 1.5 + 1e-9)
                self.assertIn(a["motion"], ("applying", "separating", "exact", "unresolved"))
            for x in d["declination_aspects"]:
                da, db = pos[x["body_a"]]["declination"], pos[x["body_b"]]["declination"]
                self.assertLessEqual(abs(da - db) if x["type"] == "parallel" else abs(da + db), 1.0 + 1e-9)
            for x in d["contacts"]["fixed_star"]:
                self.assertLessEqual(sep(pos[x["body"]]["longitude"], pos[x["star"]]["longitude"]), 1.0 + 1e-9)

    def test_patterns_geometry(self):
        orb = 2.0
        for p, d in self.snap.items():
            L = {k: v["longitude"] for k, v in d["positions"].items() if v.get("longitude") is not None}
            for pat in d["geometric_patterns"]:
                b = pat["bodies"]
                if pat["type"] == "grand_trine":
                    for x, y in combinations(b, 2):
                        self.assertLessEqual(abs(sep(L[x], L[y]) - 120), orb)
                elif pat["type"] == "t_square":
                    o1, o2 = pat["opposition"]
                    self.assertLessEqual(abs(sep(L[o1], L[o2]) - 180), orb)
                    for o in (o1, o2):
                        self.assertLessEqual(abs(sep(L[o], L[pat["apex"]]) - 90), orb)
                elif pat["type"] == "stellium":
                    for x, y in combinations(b, 2):
                        self.assertLessEqual(sep(L[x], L[y]), 8.0)
                elif pat["type"] == "yod":
                    x, y = pat["base"]
                    self.assertLessEqual(abs(sep(L[x], L[y]) - 60), orb)
                    for o in (x, y):
                        self.assertLessEqual(abs(sep(L[o], L[pat["apex"]]) - 150), orb)

    # ---------------------------------------------------------------- integrity / schema
    def test_resolution_and_no_fabrication(self):
        cat = json.loads((ROOT / "config/celestial_catalog.json").read_text())
        names = [b["name"] for objs in cat["categories"].values() for b in objs]
        self.assertEqual(len(names), len(set(names)))
        for p, d in self.snap.items():
            P = d["positions"]
            for n in names:
                self.assertIn(n, P, f"{p} missing {n}")
                e = P[n]
                if e.get("longitude") is None:
                    self.assertEqual(e["source"], "unresolved")
                    self.assertTrue(e.get("errors"), f"{p} {n} unresolved without reason")
                else:
                    self.assertIn(e["source"], ("horizons", "swiss", "calculated", "fixed_star_catalog"))
                    for k in ("longitude", "latitude", "source", "category", "timestamp"):
                        self.assertIn(k, e)
            self.assertEqual(len(d["unresolved"]), sum(1 for v in P.values() if v.get("longitude") is None))
            self.assertTrue(d["provenance"]["no_fabricated_positions"])

    def test_consumers_load(self):
        from scripts.transit_to_natal import load_natal
        from scripts.build_overlays import build_overlay
        for p in AUTHORITATIVE:
            n = load_natal(ROOT / "natal_charts" / f"{p}_natal_snapshot.json", p)
            for k in ("Sun", "Moon", "True_Node", "ASC", "MC"):
                self.assertIn(k, n["points"])
            self.assertNotIn("DSC", n["points"])
            ov = build_overlay(self.ks[p], {"planets": {}})
            self.assertEqual(ov["birth"]["date"], AUTHORITATIVE[p][0])


if __name__ == "__main__":
    unittest.main()
