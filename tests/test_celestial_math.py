import math
import unittest

from scripts.utils.celestial_math import (
    aspect_motion_status,
    body_midpoint,
    compute_aether_longitudes,
    declination_aspects,
    ecliptic_to_equatorial,
    geometric_patterns,
    lunar_geometry,
    normalize,
    shortest_arc,
)
from scripts.utils.coords import ra_dec_to_ecl


class TestCelestialMath(unittest.TestCase):
    def test_normalize(self):
        self.assertAlmostEqual(normalize(-10), 350.0)
        self.assertAlmostEqual(normalize(370), 10.0)

    def test_aether_formulas_exact(self):
        vals = compute_aether_longitudes(
            sun=10.0,
            moon=20.0,
            venus=30.0,
            mars=60.0,
            jupiter=100.0,
            saturn=40.0,
        )
        self.assertAlmostEqual(vals["Aetheric_SunMoon_Midpoint"], 30.0)
        self.assertAlmostEqual(vals["Aetheric_Jovian_Arc"], 60.0)
        self.assertAlmostEqual(vals["Aetheric_Elemental_Balance"], 36.666666666666664)

    def test_ecliptic_equatorial_roundtrip_approx(self):
        # Equator-ish ecliptic point should map near RA=lon when lat~0 and small obliquity effect
        ra, dec = ecliptic_to_equatorial(0.0, 0.0)
        lon, lat = ra_dec_to_ecl(ra, dec)
        self.assertAlmostEqual(lon, 0.0, places=6)
        self.assertAlmostEqual(lat, 0.0, places=6)

    def test_south_node_formula(self):
        self.assertAlmostEqual(normalize(10 + 180), 190.0)

    def test_lunar_geometry_new_moon(self):
        positions = {
            "Sun": {"longitude": 100.0, "source": "test"},
            "Moon": {"longitude": 100.0, "source": "test"},
        }
        geom = lunar_geometry(positions)
        self.assertEqual(geom["status"], "ok")
        self.assertEqual(geom["phase_name"], "New Moon")
        self.assertAlmostEqual(geom["illumination_fraction"], 0.0, places=6)

    def test_midpoint_shorter_arc(self):
        # 350 and 10 -> midpoint 0
        self.assertAlmostEqual(body_midpoint(350.0, 10.0), 0.0, places=6)

    def test_declination_parallel(self):
        positions = {
            "A": {"longitude": 0.0, "latitude": 0.0, "declination": 10.0, "source": "t", "category": "core_bodies"},
            "B": {"longitude": 20.0, "latitude": 0.0, "declination": 10.2, "source": "t", "category": "core_bodies"},
            "C": {"longitude": 40.0, "latitude": 0.0, "declination": -10.1, "source": "t", "category": "core_bodies"},
        }
        aspects = declination_aspects(positions, orb=0.5)
        types = {(a["body_a"], a["body_b"], a["type"]) for a in aspects}
        self.assertIn(("A", "B", "parallel"), types)
        self.assertIn(("A", "C", "contraparallel"), types)

    def test_aspect_motion_requires_speeds(self):
        m = aspect_motion_status(0.0, 90.0, None, 1.0, 90.0, 0.5)
        self.assertEqual(m["motion"], "unresolved")

    def test_harmonic_septile_angle(self):
        from scripts.calculate_aspects import HARMONIC_ANGLES
        self.assertIn(7, HARMONIC_ANGLES)
        self.assertAlmostEqual(HARMONIC_ANGLES[7], 360.0 / 7.0, places=8)

    def test_grand_trine_detection(self):
        positions = {
            "Sun": {"longitude": 0.0, "source": "t"},
            "Moon": {"longitude": 120.0, "source": "t"},
            "Mars": {"longitude": 240.0, "source": "t"},
            "Mercury": {"longitude": 10.0, "source": "t"},
            "Venus": {"longitude": 20.0, "source": "t"},
            "Jupiter": {"longitude": 30.0, "source": "t"},
            "Saturn": {"longitude": 40.0, "source": "t"},
            "Uranus": {"longitude": 50.0, "source": "t"},
            "Neptune": {"longitude": 60.0, "source": "t"},
            "Pluto": {"longitude": 70.0, "source": "t"},
        }
        patterns = geometric_patterns(positions, orb=1.0)
        types = {p["type"] for p in patterns}
        self.assertIn("grand_trine", types)


    def test_normalize_large_negative(self):
        self.assertAlmostEqual(normalize(-725.5), 354.5)

    def test_aether_formulas_only_three_keys(self):
        vals = compute_aether_longitudes(0, 0, 0, 0, 0, 0)
        self.assertEqual(
            {
                "Aetheric_SunMoon_Midpoint",
                "Aetheric_Jovian_Arc",
                "Aetheric_Elemental_Balance",
            },
            set(vals.keys()),
        )

    def test_aether_unresolved_when_inputs_missing(self):
        vals = compute_aether_longitudes(None, 10.0, 20.0, 30.0, None, 40.0)
        self.assertIsNone(vals["Aetheric_SunMoon_Midpoint"])
        self.assertIsNone(vals["Aetheric_Jovian_Arc"])
        self.assertAlmostEqual(vals["Aetheric_Elemental_Balance"], 20.0)

if __name__ == "__main__":
    unittest.main()
