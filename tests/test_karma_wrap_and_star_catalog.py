"""Regression tests: Part of Karma 0/360 wrap and the Zubenelgenubi catalog entry.

- Part_of_Karma = ASC + (Sun + Moon) / 2 must use the Sun/Moon midpoint on the shorter arc.
  A plain arithmetic mean returns the far midpoint (180 deg off) when Sun and Moon straddle 0 Aries.
- data/fixed_star_catalog.json and data/fixed_stars.json: Zubenelgenubi = alpha-2 Librae,
  ICRS J2000 RA 222.7196379, Dec -16.0417765 (SIMBAD), previously RA 222.676 (~151 arcsec off).
"""
import json
import math
import unittest
from pathlib import Path

import swisseph as swe

from scripts.utils.houses_parts import compute_arabic_parts_from_longitudes

ROOT = Path(__file__).resolve().parents[1]
swe.set_ephe_path(str(ROOT / "ephe"))


def w180(x):
    return (x + 180.0) % 360.0 - 180.0


def sep(a, b):
    return abs(w180(a - b))


def parts(asc, sun, moon, venus=0.0, sun_house=10):
    return compute_arabic_parts_from_longitudes(asc=asc, sun=sun, moon=moon, venus=venus, sun_house=sun_house)["parts"]


class KarmaWrapTest(unittest.TestCase):
    def test_wrap_uses_shorter_arc_midpoint(self):
        # Milena 1992-03-29 17:14 UTC: Sun/Moon straddle 0 Aries (arithmetic mean would give ~241.11)
        p = parts(77.247955, 9.264118, 318.469996)
        self.assertAlmostEqual(p["Part_of_Karma"]["longitude"], 61.1146, places=3)
        self.assertGreater(sep(p["Part_of_Karma"]["longitude"], 241.1146), 179.0)

    def test_non_wrap_unchanged(self):
        # no wrap: midpoint == arithmetic mean
        p = parts(10.0, 100.0, 140.0)
        self.assertAlmostEqual(p["Part_of_Karma"]["longitude"], 130.0, places=9)

    def test_symmetric_and_dependent_parts(self):
        for asc, sun, moon in ((77.2, 9.3, 318.5), (200.0, 350.0, 20.0), (0.0, 359.0, 1.0), (45.0, 170.0, 260.0)):
            a, b = parts(asc, sun, moon), parts(asc, moon, sun)
            self.assertLessEqual(sep(a["Part_of_Karma"]["longitude"], b["Part_of_Karma"]["longitude"]), 1e-9)
            k = a["Part_of_Karma"]["longitude"]
            mid = sun + w180(moon - sun) / 2.0
            self.assertLessEqual(sep(k, asc + mid), 1e-9)
            self.assertLessEqual(sep(a["Part_of_Treachery"]["longitude"], asc + moon - k), 1e-9)
            self.assertLessEqual(sep(a["Part_of_Victory"]["longitude"], asc + sun - k), 1e-9)

    def test_milena_snapshot_single_value(self):
        d = json.loads((ROOT / "natal_charts/Milena_natal_snapshot.json").read_text(encoding="utf-8"))
        ap = d["arabic_parts"]
        self.assertAlmostEqual(ap["Part_of_Karma"], 61.115, places=3)
        self.assertAlmostEqual(ap["parts"]["Part_of_Karma"]["longitude"], 61.115, places=3)
        self.assertNotIn("karma_wrap_correction", ap)
        for v in ap["parts"].values():
            self.assertNotIn("repo_code_value", v)
            if "Karma" in v.get("inputs", {}):
                self.assertAlmostEqual(v["inputs"]["Karma"], ap["Part_of_Karma"], places=9)


class ZubenelgenubiCatalogTest(unittest.TestCase):
    FILES = ("data/fixed_star_catalog.json", "data/fixed_stars.json")

    def stars(self, rel):
        return {s["id"]: s for s in json.loads((ROOT / rel).read_text(encoding="utf-8"))["stars"]}

    def test_alpha2_lib_j2000(self):
        for rel in self.FILES:
            z = self.stars(rel)["Zubenelgenubi"]
            self.assertAlmostEqual(z["ra_deg"], 222.7196379, places=6, msg=rel)
            self.assertAlmostEqual(z["dec_deg"], -16.0417765, places=6, msg=rel)

    def test_catalog_matches_swiss_sefstars_j2000(self):
        # astrometric ICRS position at J2000 from sefstars.txt; 5 arcsec admits 3-decimal entries
        flags = swe.FLG_SWIEPH | swe.FLG_EQUATORIAL | swe.FLG_J2000 | swe.FLG_ICRS | swe.FLG_NOABERR | swe.FLG_NOGDEFL
        for rel in self.FILES:
            for sid, s in self.stars(rel).items():
                ra, dec = swe.fixstar2(sid, 2451545.0, flags)[0][:2]
                d = math.hypot((s["ra_deg"] - ra) * math.cos(math.radians(dec)), s["dec_deg"] - dec) * 3600
                self.assertLess(d, 5.0, f"{rel} {sid} {d:.1f} arcsec from sefstars")


if __name__ == "__main__":
    unittest.main()
