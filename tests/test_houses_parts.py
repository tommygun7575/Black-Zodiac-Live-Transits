"""Natal observer houses + sect-aware Arabic Parts (no fabrication)."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.utils.houses_parts import (
    NATAL_OBSERVER_PATH,
    birth_datetime_utc,
    compute_arabic_parts_from_longitudes,
    compute_houses_and_angles,
    house_number_for_longitude,
    load_natal_observer,
)

ROOT = Path(__file__).resolve().parents[1]


class TestNatalObserverConfig(unittest.TestCase):
    def test_config_exists_with_geocode_provenance(self):
        self.assertTrue(NATAL_OBSERVER_PATH.exists())
        obs = load_natal_observer()
        birth = obs["birth"]
        self.assertEqual(birth["date"], "1975-09-12")
        self.assertEqual(birth["time_local"], "09:20")
        self.assertEqual(birth["timezone"], "America/New_York")
        self.assertAlmostEqual(birth["latitude"], 40.8466508, places=5)
        self.assertAlmostEqual(birth["longitude"], -73.8785937, places=5)
        geo = birth["geocode"]
        self.assertEqual(geo["provider"], "OpenStreetMap Nominatim")
        self.assertIn("osm_id", geo)

    def test_birth_utc_matches_edt(self):
        obs = load_natal_observer()
        dt = birth_datetime_utc(obs)
        self.assertEqual(dt.astimezone(timezone.utc).isoformat(), "1975-09-12T13:20:00+00:00")


class TestHousesAndParts(unittest.TestCase):
    def test_natal_houses_asc_mc(self):
        obs = load_natal_observer()
        birth = obs["birth"]
        dt = birth_datetime_utc(obs)
        houses = compute_houses_and_angles(
            dt,
            birth["latitude"],
            birth["longitude"],
            context="natal",
            place_name=birth["place_name"],
        )
        self.assertEqual(houses["status"], "computed")
        # Kitchen-sink ASC ≈ Libra 21.38° = 201.38
        self.assertAlmostEqual(houses["angles"]["ASC"], 201.3887, places=2)
        self.assertAlmostEqual(houses["angles"]["MC"], 115.1012, places=2)
        self.assertAlmostEqual(
            houses["angles"]["DSC"],
            (houses["angles"]["ASC"] + 180.0) % 360.0,
            places=6,
        )
        self.assertAlmostEqual(
            houses["angles"]["IC"],
            (houses["angles"]["MC"] + 180.0) % 360.0,
            places=6,
        )
        for i in range(1, 13):
            self.assertIn(f"House_{i}", houses["cusps"])

    def test_tommy_day_sect_fortune_matches_kitchen_sink(self):
        # Swiss natal Sun/Moon from Tommy snapshot + Swiss ASC
        asc = 201.3887488004298
        sun = 169.16294214647107
        moon = 259.8451565366586
        venus = 146.03620999481913
        cusps = [
            201.3887, 228.9805, 260.6549, 295.1012, 328.4283, 357.4267,
            21.3887, 48.9805, 80.6549, 115.1012, 148.4283, 177.4267,
        ]
        sun_house = house_number_for_longitude(sun, cusps)
        self.assertGreaterEqual(sun_house, 7)  # day chart
        parts = compute_arabic_parts_from_longitudes(
            asc=asc, sun=sun, moon=moon, venus=venus, sun_house=sun_house
        )
        self.assertEqual(parts["status"], "computed")
        self.assertEqual(parts["sect"], "day")
        self.assertAlmostEqual(parts["Part_of_Fortune"], 292.07, places=1)
        self.assertAlmostEqual(parts["Part_of_Spirit"], 110.71, places=1)
        self.assertIsNotNone(parts["Part_of_Eros"])
        self.assertIsNotNone(parts["Part_of_Karma"])
        self.assertIsNotNone(parts["Part_of_Victory"])
        self.assertIsNotNone(parts["Part_of_Treachery"])
        self.assertIsNotNone(parts["Part_of_Deliverance"])
        self.assertIsNone(parts["Part_of_Necessity"])
        self.assertEqual(
            parts["parts"]["Part_of_Necessity"]["status"], "unavailable"
        )
        self.assertIn("No Part_of_Necessity formula", parts["parts"]["Part_of_Necessity"]["reason"])

    def test_night_sect_swaps_fortune_spirit(self):
        parts = compute_arabic_parts_from_longitudes(
            asc=0.0, sun=10.0, moon=40.0, venus=20.0, sun_house=3
        )
        self.assertEqual(parts["sect"], "night")
        # Night Fortune = ASC + Sun - Moon = 0+10-40 = -30 → 330
        self.assertAlmostEqual(parts["Part_of_Fortune"], 330.0, places=6)
        self.assertAlmostEqual(parts["Part_of_Spirit"], 30.0, places=6)


if __name__ == "__main__":
    unittest.main()
