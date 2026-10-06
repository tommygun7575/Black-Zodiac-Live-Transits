"""Schemas, shared-config parity, aether lock, unresolved behavior, provider stubs."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import generate_feed_6month as six
from scripts import generate_transits as daily
from scripts.fetch_ephemeris import CATALOG_PATH, load_catalog
from scripts.utils.celestial_math import (
    compute_aether_longitudes,
    normalize,
)
from scripts.validate_config import (
    REQUIRED_AETHER,
    validate_catalog,
    validate_daily_6mo_parity,
)
from scripts.validate_output_schema import validate_payload

ROOT = Path(__file__).resolve().parents[1]
DAILY_SCHEMA = ROOT / "schemas" / "daily_overlay.schema.json"
SIX_SCHEMA = ROOT / "schemas" / "sixmonth_overlay.schema.json"


class TestLongitudeNormalize(unittest.TestCase):
    def test_normalize_wraps_negative_and_over_360(self):
        self.assertAlmostEqual(normalize(-10), 350.0)
        self.assertAlmostEqual(normalize(370), 10.0)
        self.assertAlmostEqual(normalize(-370), 350.0)
        self.assertAlmostEqual(normalize(720), 0.0)
        self.assertAlmostEqual(normalize(359.999), 359.999)

    def test_normalize_identity_on_canonical_range(self):
        for value in (0.0, 90.0, 180.0, 270.0, 359.0):
            self.assertAlmostEqual(normalize(value), value)


class TestAetherThreeFormulasOnly(unittest.TestCase):
    def test_compute_aether_returns_exactly_three_keys(self):
        vals = compute_aether_longitudes(10, 20, 30, 60, 100, 40)
        self.assertEqual(list(REQUIRED_AETHER), list(vals.keys()))
        self.assertEqual(3, len(vals))

    def test_catalog_rejects_extra_aether_names(self):
        catalog = load_catalog(CATALOG_PATH)
        categories = catalog["categories"]
        forged = json.loads(json.dumps(categories["aether_points"]))
        forged.append(
            {
                "name": "Vulcan",
                "category": "aether_points",
                "provider_priority": ["calculated"],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "celestial_catalog.json"
            path.write_text(
                json.dumps({"categories": {**categories, "aether_points": forged}}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as ctx:
                validate_catalog(path)
            self.assertIn("exactly the three verified", str(ctx.exception))


class TestDailySixMonthConfigParity(unittest.TestCase):
    def test_validate_catalog_live(self):
        summary = validate_catalog(CATALOG_PATH)
        self.assertEqual(3, summary["aether_count"])
        self.assertGreaterEqual(summary["fixed_star_count"], 19)
        self.assertEqual(
            {"Mean_Node", "South_Node", "True_Node"},
            set(summary["lunar_nodes"]),
        )

    def test_daily_6mo_shared_catalog_parity(self):
        parity = validate_daily_6mo_parity()
        self.assertEqual("config/celestial_catalog.json", parity["catalog"])
        self.assertEqual(list(REQUIRED_AETHER), list(parity["aether"]))
        moving, fixed, aether = six.load_catalog_targets(six.CATALOG_PATH)
        daily_sets = daily._catalog_target_sets(load_catalog(CATALOG_PATH))
        self.assertTrue(set(b["name"] for b in moving).issubset(daily_sets["moving"] | {"South_Node"}))
        self.assertEqual(set(aether), daily_sets["aether"])
        self.assertEqual(set(fixed), daily_sets["fixed"])


class TestUnresolvedBehavior(unittest.TestCase):
    def test_unresolved_position_is_not_counted_resolved(self):
        unresolved = {
            "longitude": None,
            "latitude": None,
            "source": "unresolved",
            "timestamp": "2026-10-06T00:00:00Z",
            "reason": "all providers failed",
        }
        self.assertFalse(daily._position_is_resolved(unresolved))

    def test_finite_lon_lat_counts_resolved(self):
        ok = {
            "longitude": 10.0,
            "latitude": 0.0,
            "source": "horizons",
            "timestamp": "2026-10-06T00:00:00Z",
        }
        self.assertTrue(daily._position_is_resolved(ok))

    def test_coverage_lists_unresolved_names(self):
        mini_catalog = {
            "categories": {
                "core_bodies": [
                    {"name": "Alpha"},
                    {"name": "Beta"},
                    {"name": "Gamma"},
                ],
                "fixed_stars": [],
                "aether_points": [],
            }
        }
        positions = {
            "Alpha": {
                "longitude": 1.0,
                "latitude": 0.0,
                "source": "horizons",
                "timestamp": "t",
                "category": "core_bodies",
            },
            "Beta": {
                "longitude": None,
                "latitude": None,
                "source": "unresolved",
                "timestamp": "t",
                "category": "core_bodies",
            },
        }
        report = daily._build_coverage_report(positions, mini_catalog)
        self.assertIn("Beta", report["unresolved"])
        self.assertIn("Gamma", report["missing"])
        self.assertNotIn("Alpha", report["unresolved"])


class TestProviderFallbackStubs(unittest.TestCase):
    def test_horizons_gap_falls_back_to_miriade_stub(self):
        body = {"name": "StubBody", "_provider_chain": ["jpl", "miriade", "swiss"]}
        dt_list = [
            __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc),
            __import__("datetime").datetime(2026, 1, 2, tzinfo=__import__("datetime").timezone.utc),
        ]
        stats = {
            "jpl_range_requests": 0,
            "jpl_range_failures": 0,
            "jpl_retries": 0,
            "jpl_timeouts": 0,
            "miriade_fallback_requests": 0,
            "miriade_range_requests": 0,
            "miriade_points_resolved": 0,
            "swiss_fallback_requests": 0,
        }

        def fake_jpl(_body, _dts, _stats):
            return {
                "2026-01-01": {
                    "ecl_lon_deg": 11.0,
                    "ecl_lat_deg": 0.0,
                    "source": "jpl",
                }
            }

        def fake_miriade(_body, missing_dates, _stats):
            self.assertEqual(1, len(missing_dates))
            return {
                "2026-01-02": {
                    "ecl_lon_deg": 22.0,
                    "ecl_lat_deg": 0.1,
                    "source": "miriade",
                }
            }

        with patch.object(six, "fetch_horizons_range", side_effect=fake_jpl), patch.object(
            six, "fetch_miriade_range", side_effect=fake_miriade
        ), patch.object(six, "fetch_swiss_point", return_value=None) as swiss:
            resolved, missing = six.resolve_moving_body(body, dt_list, stats)

        self.assertEqual([], missing)
        self.assertEqual("jpl", resolved["2026-01-01"]["source"])
        self.assertEqual("miriade", resolved["2026-01-02"]["source"])
        swiss.assert_not_called()

    def test_all_providers_fail_yields_missing_diagnostics(self):
        body = {"name": "Gone", "_provider_chain": ["jpl", "miriade", "swiss"]}
        dt_list = [
            __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc)
        ]
        stats = {
            "jpl_range_requests": 0,
            "jpl_range_failures": 0,
            "jpl_retries": 0,
            "jpl_timeouts": 0,
            "miriade_fallback_requests": 0,
            "miriade_range_requests": 0,
            "miriade_points_resolved": 0,
            "swiss_fallback_requests": 0,
        }
        with patch.object(six, "fetch_horizons_range", return_value={}), patch.object(
            six, "fetch_miriade_range", return_value={}
        ), patch.object(six, "fetch_swiss_point", return_value=None):
            resolved, missing = six.resolve_moving_body(body, dt_list, stats)
        self.assertEqual({}, resolved)
        self.assertEqual(1, len(missing))
        self.assertEqual("Gone", missing[0]["body"])
        self.assertEqual(["JPL", "Miriade", "Swiss"], missing[0]["providers_attempted"])


class TestSchemaValidation(unittest.TestCase):
    def test_daily_schema_accepts_current_feed(self):
        feed = ROOT / "docs" / "feed_overlay_2026_10_06.json"
        payload = json.loads(feed.read_text(encoding="utf-8"))
        validate_payload(payload, schema_path=DAILY_SCHEMA)

    def test_daily_schema_rejects_missing_provenance(self):
        feed = ROOT / "docs" / "feed_overlay_2026_10_06.json"
        payload = json.loads(feed.read_text(encoding="utf-8"))
        del payload["provenance"]
        with self.assertRaises(ValueError):
            validate_payload(payload, schema_path=DAILY_SCHEMA)

    def test_daily_schema_rejects_extra_aether(self):
        feed = ROOT / "docs" / "feed_overlay_2026_10_06.json"
        payload = json.loads(feed.read_text(encoding="utf-8"))
        payload["aether_points"]["Vulcan"] = {
            "longitude": 1.0,
            "latitude": 0.0,
            "source": "calculated",
            "timestamp": "t",
        }
        with self.assertRaises(ValueError):
            validate_payload(payload, schema_path=DAILY_SCHEMA)

    def test_sixmonth_schema_accepts_latest_feed(self):
        files = sorted((ROOT / "docs").glob("feed_overlay_6month_*.json"))
        self.assertTrue(files)
        payload = json.loads(files[-1].read_text(encoding="utf-8"))
        validate_payload(payload, schema_path=SIX_SCHEMA)


if __name__ == "__main__":
    unittest.main()
